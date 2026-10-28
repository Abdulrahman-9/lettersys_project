"""Regression tests for the deployed 0079 -> 0083 reservation upgrade."""

import importlib.util
import os
from datetime import timedelta
from io import StringIO
from unittest import mock, skipUnless

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import SimpleTestCase, TransactionTestCase
from django.utils import timezone


class PostgreSQLTestSettingsTests(SimpleTestCase):
    def load_settings(self, name):
        path = settings.BASE_DIR / "lettersys" / "settings_test_postgresql.py"
        spec = importlib.util.spec_from_file_location("pg_test_settings_probe", path)
        module = importlib.util.module_from_spec(spec)
        with mock.patch.dict(os.environ, {"LETTERSYS_PG_TEST_DB": name}):
            spec.loader.exec_module(module)
        return module

    def test_missing_or_unsafe_database_name_is_rejected(self):
        for name in ("", "lettersys", "test_other", "test_lettersys_;DROP DATABASE"):
            with self.subTest(name=name), self.assertRaises(RuntimeError):
                self.load_settings(name)

    def test_explicit_test_database_keeps_test_isolation_settings(self):
        module = self.load_settings("test_lettersys_upgrade_probe")
        self.assertEqual(module.DATABASES["default"]["ENGINE"],
                         "django.db.backends.postgresql")
        self.assertEqual(module.DATABASES["default"]["TEST"]["NAME"],
                         "test_lettersys_upgrade_probe")
        self.assertEqual(module.DATABASES["default"]["CONN_MAX_AGE"], 0)
        self.assertTrue(module.CELERY_TASK_ALWAYS_EAGER)
        self.assertEqual(module.EMAIL_BACKEND,
                         "django.core.mail.backends.locmem.EmailBackend")

    def test_runtime_database_is_rejected_even_with_a_test_prefix(self):
        with mock.patch("lettersys.settings.DATABASES", {
            "default": {"NAME": "test_lettersys_upgrade_probe"},
        }), self.assertRaises(RuntimeError):
            self.load_settings("test_lettersys_upgrade_probe")


@skipUnless(connection.vendor == "postgresql", "Requires PostgreSQL migration/constraint semantics")
class ReservationUpgradeTests(TransactionTestCase):
    old_target = [("core", "0079_reservation_ttl")]
    latest_target = [("core", "0083_alter_bookhistory_action_alter_bookreferral_status")]

    def migrate(self, target):
        executor = MigrationExecutor(connection)
        executor.migrate(target)
        return executor.loader.project_state(target).apps

    def setUp(self):
        super().setUp()
        self.latest_target = MigrationExecutor(connection).loader.graph.leaf_nodes("core")
        self.addCleanup(self.migrate, self.latest_target)
        self.apps = self.migrate(self.old_target)
        Department = self.apps.get_model("core", "Department")
        self.default, _ = Department.objects.get_or_create(
            code="ش13", defaults={"name": "Upgrade default department"})
        self.other = Department.objects.create(
            code="upgrade-other", name="Upgrade other department")
        self.user = self.apps.get_model("auth", "User").objects.create(username="upgrade-user")

    def reservation(self, apps=None, **overrides):
        fields = dict(
            user_id=self.user.pk, kind="incoming_internal",
            number=100, year=2026, formatted="100", status="active",
            expires_at=timezone.now() + timedelta(minutes=45),
        )
        fields.update(overrides)
        return (apps or self.apps).get_model(
            "core", "BookNumberReservation").objects.create(**fields)

    def test_strict_healthcheck_rejects_pending_upgrade_then_passes(self):
        output = StringIO()
        executor = MigrationExecutor(connection)
        pending = len(executor.migration_plan(self.latest_target))
        with self.assertRaisesMessage(CommandError, "DB healthcheck failed"):
            call_command(
                "db_healthcheck", strict=True, skip_model_check=True,
                stdout=output, stderr=output,
            )
        self.assertIn(f"{pending} pending", output.getvalue())
        self.migrate(self.latest_target)
        output = StringIO()
        call_command(
            "db_healthcheck", strict=True, skip_model_check=True,
            stdout=output, stderr=output,
        )
        self.assertIn("No unapplied migrations", output.getvalue())

    def test_upgrade_assigns_departments_and_expires_only_unbound_live_holds(self):
        Book = self.apps.get_model("core", "Book")
        book = Book.objects.create(
            kind="incoming_internal", our_number="100",
            title="Upgrade book", department_id=self.other.pk,
            created_by_id=self.user.pk,
        )
        used_at = timezone.now()
        used = self.reservation(status="used", book_id=book.pk, used_at=used_at)
        stale = [
            self.reservation(status=status, number=number, formatted=str(number))
            for number, status in enumerate(("active", "reactivated", "cooldown"), 101)
        ]
        voided = self.reservation(status="voided", void_reason="user_cancelled")

        apps = self.migrate(self.latest_target)
        Reservation = apps.get_model("core", "BookNumberReservation")
        saved = Reservation.objects.get(pk=used.pk)
        self.assertEqual(saved.department_id, self.other.pk)
        self.assertEqual(saved.status, "used")
        self.assertEqual(saved.book_id, book.pk)
        self.assertEqual(saved.used_at, used_at)
        self.assertEqual(saved.client_key, "")
        for row in stale:
            saved = Reservation.objects.get(pk=row.pk)
            self.assertEqual(saved.department_id, self.default.pk)
            self.assertEqual(saved.status, "expired")
            self.assertEqual(saved.void_reason, "forced_disconnect")
            self.assertIsNotNone(saved.voided_at)
        self.assertEqual(Reservation.objects.get(pk=voided.pk).status, "voided")
        self.assertEqual(Book.objects.get(pk=book.pk).our_number, "100")

    def test_duplicate_cleanup_and_client_scoped_unique_constraint(self):
        apps = self.migrate([("core", "0080_reservation_department")])
        first = self.reservation(apps, department_id=self.default.pk)
        duplicate = self.reservation(
            apps, department_id=self.default.pk, number=101,
            formatted="101", status="reactivated")

        apps = self.migrate(self.latest_target)
        Reservation = apps.get_model("core", "BookNumberReservation")
        self.assertEqual(Reservation.objects.get(pk=first.pk).status, "active")
        saved = Reservation.objects.get(pk=duplicate.pk)
        self.assertEqual(saved.status, "cooldown")
        self.assertEqual(saved.void_reason, "forced_disconnect")
        self.assertIsNotNone(saved.cooldown_until)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self.reservation(apps, department_id=self.default.pk)
        self.reservation(apps, department_id=self.default.pk, client_key="second-browser")
        self.reservation(apps, department_id=self.other.pk)
        self.reservation(apps, department_id=self.default.pk, status="used")

    def test_schema_rollback_and_reapply_with_distinct_clients(self):
        apps = self.migrate(self.latest_target)
        self.reservation(apps, department_id=self.default.pk, client_key="browser-a")
        self.reservation(
            apps, department_id=self.default.pk, client_key="browser-b",
            number=101, formatted="101")
        # Reversing 0082 restores the narrower 0081 uniqueness rule. It must
        # fail rather than silently discard distinct browser reservations.
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self.migrate([("core", "0081_active_reservation_guard")])
        self.assertEqual(apps.get_model("core", "BookNumberReservation").objects.count(), 2)
