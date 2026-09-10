# -*- coding: utf-8 -*-
"""حارسُ ``enc::`` — Merge9 §8.6-ب.

كلُّ اختبارٍ هنا يُطفَّر: تعطيلُ الحارس (سطرُ `find_plaintext` في `db_healthcheck`
أو في `core/checks.py`) يجب أن يُحمّرها. والقيمةُ الصريحةُ تُكتب بـ
``QuerySet.update()`` عمداً — هو الطريقُ نفسُه الذي يتخطّى ``save()`` كما يفعل
``loaddata`` بـ``raw=True``، أي **إعادةُ إنتاجٍ للحادثة لا محاكاةٌ لها**.
"""

from django.core.checks import Error as CheckError
from django.core.management import CommandError, call_command
from django.db import connection
from django.test import TestCase

from core.checks import PLAINTEXT_SECRET_ID, check_encrypted_columns
from core.encrypted_columns import (encrypted_columns, encrypted_models,
                                    find_plaintext, plaintext_lines)
from core.models import AIIntegrationSettings, EmailSettings

#: قيمةٌ صريحةٌ مميّزة — يُتحقَّق أنّها **لا تظهر** في أيّ مخرَجٍ للحارس.
PLAIN = 'p4ssw0rd-in-the-clear'


def _raw(model, column, pk):
    """القيمةُ الخام في القاعدة — بـSQL لا بالـORM (الـORM يفكّ فيُخفي الفرق)."""
    with connection.cursor() as cursor:
        cursor.execute(
            f'SELECT {connection.ops.quote_name(column)} FROM '
            f'{connection.ops.quote_name(model._meta.db_table)} WHERE id = %s', [pk])
        return cursor.fetchone()[0]


class EncryptedColumnDiscoveryTests(TestCase):
    def test_discovery_reads_the_registry_not_a_hand_list(self):
        labels = {m._meta.label_lower for m in encrypted_models()}
        self.assertIn('core.emailsettings', labels)
        self.assertIn('core.aiintegrationsettings', labels)

    def test_columns_carry_table_and_db_column(self):
        found = {(c.table, c.column) for c in encrypted_columns()}
        self.assertEqual(found, {
            (EmailSettings._meta.db_table, 'smtp_password'),
            (EmailSettings._meta.db_table, 'imap_password'),
            (AIIntegrationSettings._meta.db_table, 'azure_key'),
        })


class PlaintextScanTests(TestCase):
    def test_clean_database_has_no_findings(self):
        settings_row = EmailSettings.get()
        settings_row.smtp_password = PLAIN
        settings_row.save()

        self.assertTrue(_raw(EmailSettings, 'smtp_password', settings_row.pk)
                        .startswith('enc::'))
        self.assertEqual(find_plaintext(), [])

    def test_plaintext_row_written_around_save_is_found(self):
        settings_row = EmailSettings.get()
        EmailSettings.objects.filter(pk=settings_row.pk).update(smtp_password=PLAIN)

        findings = find_plaintext()

        self.assertEqual(len(findings), 1, 'الحارسُ لم يرَ النصَّ الصريح')
        column, rows = findings[0]
        self.assertEqual(column.column, 'smtp_password')
        self.assertEqual(column.table, EmailSettings._meta.db_table)
        self.assertEqual(rows, 1)

    def test_report_names_the_column_and_never_the_value(self):
        row = EmailSettings.get()
        EmailSettings.objects.filter(pk=row.pk).update(imap_password=PLAIN)

        lines = plaintext_lines(find_plaintext())

        self.assertEqual(len(lines), 1)
        self.assertIn('imap_password', lines[0])
        self.assertIn(EmailSettings._meta.db_table, lines[0])
        self.assertNotIn(PLAIN, lines[0])

    def test_empty_and_encrypted_values_are_not_flagged(self):
        """الفارغُ لا يُعدّ تسريباً، والمشفَّرُ سليم — وإلّا صرخ الحارسُ دوماً فأُهمل."""
        EmailSettings.get()  # كلُّ الحقول فارغة
        AIIntegrationSettings.objects.create(azure_key='k' * 32)

        self.assertEqual(find_plaintext(), [])


class HealthcheckGuardTests(TestCase):
    def test_command_is_green_on_a_clean_database(self):
        EmailSettings.get()
        call_command('db_healthcheck', '--skip-model-check', verbosity=0)

    def test_command_exits_nonzero_and_names_table_and_column(self):
        row = EmailSettings.get()
        EmailSettings.objects.filter(pk=row.pk).update(smtp_password=PLAIN)

        with self.assertRaises(CommandError):
            call_command('db_healthcheck', '--skip-model-check', verbosity=0)

    def test_command_output_carries_the_names_without_the_value(self):
        from io import StringIO

        row = EmailSettings.get()
        EmailSettings.objects.filter(pk=row.pk).update(smtp_password=PLAIN)
        out = StringIO()

        with self.assertRaises(CommandError):
            call_command('db_healthcheck', '--skip-model-check', stdout=out, stderr=out)

        printed = out.getvalue()
        self.assertIn('smtp_password', printed)
        self.assertIn(EmailSettings._meta.db_table, printed)
        self.assertNotIn(PLAIN, printed)

    def test_guard_does_not_heal_the_row(self):
        """الشفاءُ الذاتيُّ يسكّ مفتاحاً ثالثاً صامتاً — الحارسُ يصرخ ولا يلمس."""
        row = EmailSettings.get()
        EmailSettings.objects.filter(pk=row.pk).update(smtp_password=PLAIN)

        with self.assertRaises(CommandError):
            call_command('db_healthcheck', '--skip-model-check', verbosity=0)

        self.assertEqual(_raw(EmailSettings, 'smtp_password', row.pk), PLAIN)


class BootCheckTests(TestCase):
    def test_silent_when_no_database_is_requested(self):
        row = EmailSettings.get()
        EmailSettings.objects.filter(pk=row.pk).update(smtp_password=PLAIN)

        self.assertEqual(check_encrypted_columns(None, databases=None), [])

    def test_error_when_a_database_is_requested(self):
        row = EmailSettings.get()
        EmailSettings.objects.filter(pk=row.pk).update(smtp_password=PLAIN)

        issues = check_encrypted_columns(None, databases=['default'])

        self.assertEqual(len(issues), 1)
        self.assertIsInstance(issues[0], CheckError)
        self.assertEqual(issues[0].id, PLAINTEXT_SECRET_ID)
        self.assertIn('smtp_password', issues[0].msg)
        self.assertNotIn(PLAIN, issues[0].msg)
        self.assertNotIn(PLAIN, issues[0].hint)

    def test_clean_database_yields_no_issue(self):
        EmailSettings.get()
        self.assertEqual(check_encrypted_columns(None, databases=['default']), [])
