# -*- coding: utf-8 -*-
"""حرّاسُ تظليل ``dumpdata`` — Merge9 §8.6-ج.

الاختبارُ الفاصل هنا ``test_scan_deletes_the_file_when_the_exclusion_fails``:
يُطفئ الاستثناءَ فيُعيد إنتاجَ حادثة 2026-09-08 حرفيّاً — كلمةُ المرور في القاعدة
``enc::`` سليمة، و``from_db`` يفكّها، فيكتبها المُسلسِلُ **صريحةً** في الملفّ.
وعندها يجب أن يُحذَف الملفُّ ويفشل الأمر.
"""

import json
import tempfile
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.contrib.auth.models import User
from django.core.management import CommandError, call_command, get_commands
from django.test import TestCase

from core.management.commands import dumpdata as shadow
from core.models import EmailSettings

PLAIN = 'app-password-16ch'


class ShadowResolutionTests(TestCase):
    def test_the_shadow_is_what_manage_py_runs(self):
        """لو عاد الاسمُ إلى django.core لسقطت الحرّاسُ الأربعةُ صامتةً."""
        self.assertEqual(get_commands()['dumpdata'], 'core')


class OutputPathGuardTests(TestCase):
    def test_stdout_is_refused(self):
        with self.assertRaises(CommandError) as caught:
            call_command('dumpdata', '--all', verbosity=0)
        self.assertIn('stdout', str(caught.exception))

    def test_writing_inside_the_repository_is_refused(self):
        target = Path(settings.BASE_DIR) / 'leak_should_not_exist.json'

        with self.assertRaises(CommandError) as caught:
            call_command('dumpdata', '--all', '-o', str(target), verbosity=0)

        self.assertIn('المستودع', str(caught.exception))
        self.assertFalse(target.exists(), 'كُتب ملفٌّ داخل المستودع رغم الرفض')

    def test_a_subdirectory_of_the_repository_is_refused_too(self):
        target = Path(settings.BASE_DIR) / 'core' / 'leak_should_not_exist.json'

        with self.assertRaises(CommandError):
            call_command('dumpdata', '--all', '-o', str(target), verbosity=0)

        self.assertFalse(target.exists())

    def test_zip_is_refused_because_django_renames_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(CommandError) as caught:
                call_command('dumpdata', '--all', '-o', str(Path(tmp) / 'd.zip'),
                             verbosity=0)
        self.assertIn('.zip', str(caught.exception))


class AllFlagGuardTests(TestCase):
    def test_dump_without_all_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'd.json'
            with self.assertRaises(CommandError) as caught:
                call_command('dumpdata', '-o', str(target), verbosity=0)
            self.assertIn('--all', str(caught.exception))
            self.assertFalse(target.exists())


class SecretModelExclusionTests(TestCase):
    def setUp(self):
        row = EmailSettings.get()
        row.smtp_password = PLAIN
        row.save()
        User.objects.create_user('kateb', password='x')

    def test_secret_model_and_its_password_are_absent_from_the_dump(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'd.json'
            call_command('dumpdata', '--all', '-o', str(target), verbosity=0)
            # `errors='replace'`: جانغو يكتب بترميز اللغة المحلّيّة لا UTF-8
            # (مقيسٌ: cp1256 هنا) — وASCII يبقى سليماً فالفحصُ صادق.
            text = target.read_text(encoding='utf-8', errors='replace')

        self.assertIn('auth.user', text, 'المخرَجُ فارغٌ — الاختبارُ لا يثبت شيئاً')
        self.assertNotIn('core.emailsettings', text.lower())
        self.assertNotIn(PLAIN, text)

    def test_explicitly_asking_for_a_secret_model_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'd.json'
            with self.assertRaises(CommandError) as caught:
                call_command('dumpdata', 'core.EmailSettings', '--all',
                             '-o', str(target), verbosity=0)
            self.assertIn('EmailSettings', str(caught.exception))
            self.assertFalse(target.exists())

    def test_the_users_own_exclude_is_kept(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'd.json'
            call_command('dumpdata', '--all', '-e', 'auth.User',
                         '-o', str(target), verbosity=0)
            text = target.read_text(encoding='utf-8', errors='replace')

        self.assertNotIn('"auth.user"', text.lower())
        self.assertNotIn('core.emailsettings', text.lower())

    def test_a_crash_mid_write_leaves_no_unscanned_file(self):
        """جانغو لا يحذف المكتوبَ جزئيّاً — فيبقى نصفُ نسخةٍ لم يمرّ عليها فحص."""
        from django.core.management.commands.dumpdata import (
            Command as Original)

        def crash(command, *args, **options):
            Path(options['output']).write_text('[{"model": "auth.user"',
                                               encoding='utf-8')
            raise RuntimeError('boom')

        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'd.json'
            with mock.patch.object(Original, 'handle', crash):
                with self.assertRaises(RuntimeError):
                    call_command('dumpdata', '--all', '-o', str(target), verbosity=0)

            self.assertFalse(target.exists(), 'بقي ملفٌّ لم يُفحَص على القرص')

    def test_scan_deletes_the_file_when_the_exclusion_fails(self):
        """إعادةُ إنتاج حادثة 09-08: العمودُ enc:: سليم، والمُسلسِلُ يكتب الصريح."""
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'd.json'
            with mock.patch.object(shadow, 'secret_model_labels', return_value=()):
                with self.assertRaises(CommandError) as caught:
                    call_command('dumpdata', '--all', '-o', str(target), verbosity=0)

            self.assertFalse(target.exists(), 'الملفُّ المسرِّبُ بقي على القرص')

        message = str(caught.exception)
        self.assertIn('core.emailsettings', message)
        self.assertIn('smtp_password', message)
        self.assertNotIn(PLAIN, message, 'الحارسُ طبع السرَّ الذي يحرسه')


class DumpScanTests(TestCase):
    """فحصُ ما بعد الكتابة وحدَه — بملفّاتٍ مصنوعةٍ باليد."""

    def _write(self, tmp, payload, name='d.json'):
        target = Path(tmp) / name
        target.write_text(json.dumps(payload), encoding='utf-8')
        return target

    def test_clean_dump_has_no_violation(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = self._write(tmp, [
                {'model': 'auth.user', 'pk': 1, 'fields': {'username': 'kateb'}}])
            self.assertEqual(shadow.scan_dump_for_secrets(target), [])

    def test_plaintext_value_is_named_without_being_printed(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = self._write(tmp, [{
                'model': 'core.emailsettings', 'pk': 1,
                'fields': {'smtp_password': PLAIN, 'imap_password': ''}}])

            violations = shadow.scan_dump_for_secrets(target)

        self.assertEqual(len(violations), 1)
        self.assertIn('smtp_password', violations[0])
        self.assertNotIn('imap_password', violations[0])
        self.assertNotIn(PLAIN, violations[0])

    def test_encrypted_record_is_a_violation_too(self):
        """المشفَّرُ لا يُشحَن في ملفٍّ عابر — ووجودُه يعني أنّ الاستثناءَ لم يقع."""
        with tempfile.TemporaryDirectory() as tmp:
            target = self._write(tmp, [{
                'model': 'core.emailsettings', 'pk': 1,
                'fields': {'smtp_password': 'enc::gAAAAAB'}}])

            violations = shadow.scan_dump_for_secrets(target)

        self.assertEqual(len(violations), 1)
        self.assertIn('الاستثناءُ لم يقع', violations[0])

    def test_non_json_format_is_flagged_on_the_name_alone(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'd.xml'
            target.write_text('<object model="core.EmailSettings"></object>',
                              encoding='utf-8')

            violations = shadow.scan_dump_for_secrets(target, fmt='xml')

        self.assertEqual(len(violations), 1)
        self.assertIn('core.emailsettings', violations[0])

    def test_unparsable_json_with_a_secret_name_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'd.json'
            target.write_text('[{"model": "core.emailsettings", "fields"',
                              encoding='utf-8')

            violations = shadow.scan_dump_for_secrets(target)

        self.assertEqual(len(violations), 1)
        self.assertIn('لا يُفحَص', violations[0])

    def test_compressed_output_is_read_back(self):
        import gzip

        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'd.json.gz'
            with gzip.open(target, 'wt', encoding='utf-8') as handle:
                json.dump([{'model': 'core.emailsettings', 'pk': 1,
                            'fields': {'smtp_password': PLAIN}}], handle)

            violations = shadow.scan_dump_for_secrets(target)

        self.assertEqual(len(violations), 1)
        self.assertIn('smtp_password', violations[0])


class LocaleEncodingNoticeTests(TestCase):
    """جانغو يكتب المخرَجَ بترميز اللغة المحلّيّة — تشويهٌ صامتٌ للعربيّة."""

    def _dump(self, encoding):
        from io import StringIO
        out = StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(shadow.locale, 'getpreferredencoding',
                                   return_value=encoding):
                call_command('dumpdata', '--all', '-o', str(Path(tmp) / 'd.json'),
                             stdout=out)
        return out.getvalue()

    def test_non_utf8_locale_is_announced(self):
        self.assertIn('cp1256', self._dump('cp1256'))

    def test_utf8_locale_is_silent(self):
        self.assertNotIn('ترميز اللغة المحلّيّة', self._dump('UTF-8'))
