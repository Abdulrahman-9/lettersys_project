from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class OutgoingUpgradeTests(TransactionTestCase):
    def test_deployed_reservation_schema_upgrades_without_losing_office_numbers(self):
        previous = [("core", "0085_reservation_assignment_time")]
        target = [("core", "0086_merge_outgoing_reservation")]
        executor = MigrationExecutor(connection)
        try:
            executor.migrate([("core", "0084_attachment_version_unique")])
            executor = MigrationExecutor(connection)
            executor.migrate(previous)
            apps = executor.loader.project_state(previous).apps
            User = apps.get_model("auth", "User")
            Department = apps.get_model("core", "Department")
            Book = apps.get_model("core", "Book")
            user = User.objects.create(username="outgoing-upgrade")
            first = Department.objects.create(name="First", code="upgrade-1")
            second = Department.objects.create(name="Second", code="upgrade-2")
            records = [
                Book.objects.create(
                    kind="outgoing_external", our_number=office,
                    department_id=department.pk, created_by_id=user.pk,
                    title="Upgrade fixture",
                )
                for department, office in [(first, "109"), (first, "250"), (second, "109")]
            ]
            numberless = Book.objects.create(
                kind="outgoing_external", our_number="",
                department_id=first.pk, created_by_id=user.pk,
                title="Numberless fixture",
            )
            training = Book.objects.create(
                kind="outgoing_external", our_number="T131", is_training=True,
                department_id=first.pk, created_by_id=user.pk,
                title="Training fixture",
            )
            executor = MigrationExecutor(connection)
            executor.migrate(target)
            apps = executor.loader.project_state(target).apps
            Book = apps.get_model("core", "Book")
            Sequence = apps.get_model("core", "BookSequence")
            self.assertEqual(
                list(Book.objects.filter(pk__in=[b.pk for b in records])
                     .order_by("pk").values_list("our_number", "director_general_number")),
                [("1", "109"), ("2", "250"), ("1", "109")],
            )
            self.assertEqual(
                Book.objects.filter(pk=numberless.pk)
                .values_list("our_number", "director_general_number").get(),
                ("", ""),
            )
            self.assertEqual(
                Book.objects.filter(pk=training.pk)
                .values_list("our_number", "director_general_number", "is_training").get(),
                ("T131", "", True),
            )
            self.assertEqual(
                Sequence.objects.get(department_id=first.pk, kind="outgoing_external").next_number,
                3,
            )
            self.assertEqual(
                Sequence.objects.get(department_id=second.pk, kind="outgoing_external").next_number,
                2,
            )
            self.assertIsNotNone(
                apps.get_model("core", "BookNumberReservation")._meta.get_field("assigned_at")
            )
        finally:
            MigrationExecutor(connection).migrate(target)
