# -*- coding: utf-8 -*-
"""النسخُ والاستعادة (11-22، حكمُ فيبل): مسارٌ واحد للنسخ، والصريحُ لا يبقى، ورسالةٌ صادقةٌ لكلّ سبب،
والاستعادةُ تنظّف خلفها، والتبديلُ أمرٌ يُلصق ويُرجَع عنه.
"""
import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from unittest import mock

from django.contrib.auth.models import User
from django.contrib.messages import get_messages
from django.core.management import CommandError, call_command
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from core import backup_service as bs


def _tmpdir(case):
    path = Path(tempfile.mkdtemp(prefix='bk1122_'))
    case.addCleanup(shutil.rmtree, path, ignore_errors=True)
    return path


class DumpLeavesNoPlaintextTests(SimpleTestCase):

    def setUp(self):
        self.dir = _tmpdir(self)

    def _dump_then(self, effect):
        def run(command, **kwargs):
            Path(next(a for a in command if a.startswith('--file='))[7:]).write_bytes(b'PGDMP plaintext')
            if effect:
                raise effect
        return run

    def test_a_failed_dump_leaves_no_plaintext(self):
        for effect in (subprocess.CalledProcessError(1, 'pg_dump'), subprocess.TimeoutExpired('pg_dump', 1)):
            with self.subTest(effect=type(effect).__name__), \
                    mock.patch.object(bs, '_find_pg_dump', return_value='pg_dump'), \
                    mock.patch.object(bs.subprocess, 'run', side_effect=self._dump_then(effect)):
                with self.assertRaises(type(effect)):
                    bs.create_encrypted_pg_backup(self.dir, 'x.dump')
                self.assertEqual(list(self.dir.iterdir()), [], 'نسخةٌ صريحةٌ ناقصة بقيت على القرص')

    def test_pg_dump_cannot_hang_the_page_forever(self):
        with mock.patch.object(bs, '_find_pg_dump', return_value='pg_dump'), \
                mock.patch.object(bs.subprocess, 'run',
                                  side_effect=self._dump_then(subprocess.CalledProcessError(1, 'x'))) as run:
            with self.assertRaises(subprocess.CalledProcessError):
                bs.create_encrypted_pg_backup(self.dir, 'x.dump')
        self.assertEqual(run.call_args.kwargs.get('timeout'), bs.PG_DUMP_TIMEOUT)

    def test_a_failed_encryption_leaves_no_plaintext(self):
        with mock.patch.object(bs, '_find_pg_dump', return_value='pg_dump'), \
                mock.patch.object(bs.subprocess, 'run', side_effect=self._dump_then(None)), \
                mock.patch('core.encryption.encrypt_file', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                bs.create_encrypted_pg_backup(self.dir, 'x.dump')
        self.assertEqual(list(self.dir.iterdir()), [])

    def test_a_missing_pg_dump_is_its_own_error_and_writes_nothing(self):
        with mock.patch.object(bs, '_find_pg_dump', return_value=None), \
                mock.patch.object(bs.subprocess, 'run') as run:
            with self.assertRaises(bs.PgDumpMissing):
                bs.create_encrypted_pg_backup(self.dir, 'x.dump')
        run.assert_not_called()

    def test_each_cause_gets_its_own_words(self):
        # القرصُ الغائب يرمي FileNotFoundError أيضاً — كان يُقال له «تعذّر العثور على pg_dump»
        missing_drive = bs.describe_backup_error(FileNotFoundError(2, 'No such file', 'Q:/backups'))
        self.assertIn('القرصَ موصولٌ', missing_drive)
        self.assertNotIn('pg_dump', missing_drive)
        self.assertIn('تعذّر العثور على pg_dump', bs.describe_backup_error(bs.PgDumpMissing('x')))
        self.assertIn('نصف ساعة', bs.describe_backup_error(subprocess.TimeoutExpired('pg_dump', 1)))
        self.assertIn('فشل pg_dump', bs.describe_backup_error(subprocess.CalledProcessError(1, 'pg_dump')))


class OneBackupPathTests(TestCase):
    """الزرُّ والمهمّةُ المجدولة يأخذان النسخةَ الكاملة نفسَها."""

    def setUp(self):
        self.client.force_login(User.objects.create_superuser('bk1122', password='pw-bk-1122'))

    def _post(self, report):
        with mock.patch('core.views.dashboard.run_full_backup', return_value=report) as full:
            response = self.client.post(reverse('backup_database'), {'target_directory': 'C:/elsewhere'})
        full.assert_called_once_with()          # بلا مسارٍ من الطلب
        return [(m.level_tag, str(m)) for m in get_messages(response.wsgi_request)]

    def test_the_button_reports_every_part(self):
        said = self._post({'database': 'D:/trackbackup/pg_backup_20261122_1015.dump.enc', 'config': 'c.tar.enc',
                           'media': {'copied': 3}, 'models': {'copied': 0}, 'encryption_key': {'exists': True}})
        self.assertEqual(len(said), 1)
        level, text = said[0]
        self.assertEqual(level, 'success')
        for part in ('«pg_backup_20261122_1015.dump.enc»', 'ملفّات الإعداد', 'مرآة المرفقات (3', 'مرآة النماذج (0'):
            self.assertIn(part, text)

    def test_a_failed_part_says_why_and_the_rest_still_counts(self):
        said = dict(self._post({'database_error': 'تعذّرت الكتابةُ في مجلّد النسخ — …', 'config': None,
                                'media_error': 'x', 'encryption_key': {'exists': False}}))
        self.assertIn('القاعدة لم تُنسخ: تعذّرت الكتابةُ', said['error'])
        self.assertNotIn('success', said)
        warnings = [t for lvl, t in self._post({'database': 'a.dump.enc', 'media_error': 'لا قرص',
                                                'encryption_key': {'exists': False}}) if lvl == 'warning']
        self.assertTrue(any('مرآة المرفقات لم تُنسخ: لا قرص' in t for t in warnings))
        self.assertTrue(any('.encryption_key' in t for t in warnings))

    def test_the_scheduled_task_runs_the_same_function(self):
        from core import tasks
        with mock.patch('core.backup_service.run_full_backup', return_value={'database': 'a'}) as full, \
                mock.patch.object(tasks, '_backup_is_due', return_value=True):
            self.assertEqual(tasks.scheduled_backup(), {'database': 'a'})
        full.assert_called_once_with()


class UseRestoredDatabaseTests(SimpleTestCase):

    def setUp(self):
        self.base = _tmpdir(self)
        self.env = self.base / '.env'
        self.env.write_bytes('SECRET_KEY=k\r\nDB_NAME=lettersys\r\nDB_PASSWORD=p@ss\r\n'.encode('utf-8'))
        for name, value in (('database_exists', True), ('count_books', 11183)):
            patcher = mock.patch(f'core.management.commands.use_restored_database.{name}', return_value=value)
            setattr(self, name, patcher.start())
            self.addCleanup(patcher.stop)
        settings_patch = override_settings(BASE_DIR=self.base)
        settings_patch.enable()
        self.addCleanup(settings_patch.disable)

    def run_cmd(self, *args):
        call_command('use_restored_database', *args, stdout=mock.MagicMock())

    def test_switch_then_undo_touch_only_the_db_line(self):
        self.run_cmd('lettersys_r_20261122_1015')
        self.assertEqual(self.env.read_bytes(),
                         'SECRET_KEY=k\r\nDB_NAME=lettersys_r_20261122_1015\r\nDB_PASSWORD=p@ss\r\n'.encode('utf-8'))
        state = json.loads((self.base / 'var' / 'db_switch.json').read_text(encoding='utf-8'))
        self.assertEqual((state['previous'], state['current']), ('lettersys', 'lettersys_r_20261122_1015'))
        self.assertNotIn('p@ss', json.dumps(state))             # لا نسخةَ من .env ولا من كلمة المرور
        self.run_cmd('--undo')
        self.assertEqual(self.env.read_bytes(), 'SECRET_KEY=k\r\nDB_NAME=lettersys\r\nDB_PASSWORD=p@ss\r\n'.encode('utf-8'))
        self.assertFalse((self.base / 'var' / 'db_switch.json').exists())
        self.assertEqual(sorted(p.name for p in self.base.iterdir()), ['.env', 'var'])   # لا ملفَّ مؤقّتٌ باقٍ

    def test_refusals_change_nothing(self):
        before = self.env.read_bytes()
        cases = [(('lettersys_dev',), 'ليس قاعدةً مستعادة'), (('--undo',), 'لا تبديلَ سابقاً')]
        for args, words in cases:
            with self.subTest(args=args), self.assertRaisesMessage(CommandError, words):
                self.run_cmd(*args)
        self.count_books.return_value = 0
        with self.assertRaisesMessage(CommandError, 'بلا كتب'):
            self.run_cmd('lettersys_r_20261122_1015')
        self.database_exists.return_value = False
        with self.assertRaisesMessage(CommandError, 'لا قاعدةَ باسم'):
            self.run_cmd('lettersys_r_20261122_1015')
        self.assertEqual(self.env.read_bytes(), before)

    def test_undo_refuses_when_the_env_changed_by_hand_since(self):
        self.run_cmd('lettersys_r_20261122_1015')
        self.env.write_bytes(b'DB_NAME=other\r\n')
        with self.assertRaisesMessage(CommandError, 'تغيّر بعده بيدٍ أخرى'):
            self.run_cmd('--undo')
        self.assertEqual(self.env.read_bytes(), b'DB_NAME=other\r\n')

    def test_two_db_lines_are_refused(self):
        self.env.write_bytes(b'DB_NAME=a\nDB_NAME=b\n')
        with self.assertRaisesMessage(CommandError, '2 سطرٍ'):
            self.run_cmd('lettersys_r_20261122_1015')
