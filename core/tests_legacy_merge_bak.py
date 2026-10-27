# -*- coding: utf-8 -*-
"""الدمجُ الآليُّ من ملفّ باكاب قديم — حرّاسُه.

لا SQL Server ولا ملفَّ باكابٍ حقيقيّ هنا: `pyodbc` مُحاكى بالكامل، وما يُثبَت
هو **وصلاتُ القرار** التي كانت مكسورة:
  • الحدُّ يُقرأ بالمفتاح المنطقيّ لا باسم القاعدة المؤقتة (وإلّا صار كلُّ قديمٍ
    لم يُستورَد «جديداً» يُضاف بلا قرار).
  • الحدُّ الجديد يُكتب بعد نجاح الدمج وحدَه.
  • «معاينة فقط» لا تستدعي `run()` إطلاقاً.
  • الصفحةُ لا تنفّذ الدمج داخل الطلب — تُنشئ مهمّةً وتُشغّل عمليةً مستقلّة.
"""
import os
import sys
import tempfile
from unittest import mock

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from core.legacy_restore import LegacyRestoreEngine
from core.models import RestoreJob


class _FakeCursor:
    """مؤشّرٌ يفهم الاستعلامات الثلاثة التي يرسلها `restore_from_bak` فقط."""

    description = [('LogicalName',), ('Type',), ('Size',)]

    def __init__(self):
        self.executed = []

    def execute(self, sql, *args):
        self.executed.append(sql)
        return self

    def fetchall(self):
        return [('ARCHMDOC_data', 'D', 1024), ('ARCHMDOC_log', 'L', 512)]

    def fetchone(self):
        return ('',)          # InstanceDefaultDataPath فارغ ⇒ يسقط إلى مجلّد الباكاب

    def nextset(self):
        return False


class _FakeConn:
    def __init__(self):
        self.cursors = []
        self.closed = False

    def cursor(self):
        c = _FakeCursor()
        c.connection = self          # مسارُ الإسقاط يغلق الاتصال عبر المؤشّر
        self.cursors.append(c)
        return c

    def close(self):
        self.closed = True


class _FakePyodbc:
    def __init__(self):
        self.conns = []

    def connect(self, *args, **kwargs):
        c = _FakeConn()
        self.conns.append(c)
        return c


class _BakFixture(TestCase):
    """ملفُّ .bak وهميّ على القرص + pyodbc محاكى."""

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix='legacy_bak_test_')
        self.addCleanup(lambda: self._rmtree(self.dir))
        self.bak = os.path.join(self.dir, 'archive.bak')
        with open(self.bak, 'wb') as fh:
            fh.write(b'FAKEBAK')
        self.pyodbc = _FakePyodbc()
        patcher = mock.patch.dict(sys.modules, {'pyodbc': self.pyodbc})
        patcher.start()
        self.addCleanup(patcher.stop)

    @staticmethod
    def _rmtree(path):
        import shutil
        shutil.rmtree(path, ignore_errors=True)


class BoundaryWiringTests(_BakFixture):

    def test_boundary_read_by_logical_key_not_temp_database(self):
        """
        القاعدةُ المؤقتة اسمُها `LEGACYRESTORE_<طابع زمنيّ>` يتغيّر كلَّ تشغيل،
        فقراءةُ الحدّ به لا تجد ملفّاً أبداً. يجب أن يُقرأ بالمفتاح المنطقيّ.
        """
        seen = {}

        def fake_load(database, path=None):
            seen['key'] = database
            return {'IIMAIL_2026': 2432}

        def fake_run(self, created_by, **kw):
            seen['boundary'] = kw.get('boundary')
            seen['include_held'] = kw.get('include_held')
            return {'books': 3}

        with mock.patch.object(LegacyRestoreEngine, 'load_boundary', staticmethod(fake_load)), \
             mock.patch.object(LegacyRestoreEngine, 'run', fake_run), \
             mock.patch.object(LegacyRestoreEngine, 'capture_boundary',
                               lambda self, **kw: {'path': 'X'}):
            summary = LegacyRestoreEngine.restore_from_bak(
                self.bak, work_dir=self.dir, boundary_key='ARCHMDOC')

        self.assertEqual(seen['key'], 'ARCHMDOC')
        self.assertEqual(seen['boundary'], {'IIMAIL_2026': 2432})
        self.assertFalse(seen['include_held'])
        self.assertEqual(summary['books'], 3)

    def test_new_boundary_written_after_successful_merge(self):
        captured = {}

        def fake_capture(self, note='', path=None, label=None):
            captured['path'] = path
            captured['label'] = label
            captured['note'] = note
            return {'path': path}

        with mock.patch.object(LegacyRestoreEngine, 'load_boundary', staticmethod(lambda *a, **k: None)), \
             mock.patch.object(LegacyRestoreEngine, 'run', lambda self, created_by, **kw: {'books': 1}), \
             mock.patch.object(LegacyRestoreEngine, 'capture_boundary', fake_capture):
            summary = LegacyRestoreEngine.restore_from_bak(
                self.bak, work_dir=self.dir, boundary_key='ARCHMDOC')

        self.assertEqual(captured['path'], LegacyRestoreEngine.boundary_path('ARCHMDOC'))
        self.assertEqual(captured['label'], 'ARCHMDOC')
        self.assertIn('archive.bak', captured['note'])
        self.assertEqual(summary['boundary_path'], captured['path'])

    def test_boundary_not_written_when_merge_aborts(self):
        """حدٌّ يُكتب بعد دمجٍ أُوقف يعني أن الصفوف غير المستوردة تصير «قديمة» بلا سبب."""
        calls = []
        with mock.patch.object(LegacyRestoreEngine, 'load_boundary', staticmethod(lambda *a, **k: None)), \
             mock.patch.object(LegacyRestoreEngine, 'run',
                               lambda self, created_by, **kw: {'aborted': True, 'reason': 'لا'}), \
             mock.patch.object(LegacyRestoreEngine, 'capture_boundary',
                               lambda self, **kw: calls.append(kw)):
            summary = LegacyRestoreEngine.restore_from_bak(self.bak, work_dir=self.dir)

        self.assertTrue(summary['aborted'])
        self.assertEqual(calls, [])

    def test_delta_only_never_runs_the_merge(self):
        ran = []
        with mock.patch.object(LegacyRestoreEngine, 'load_boundary',
                               staticmethod(lambda *a, **k: {'IIMAIL_2026': 2432})), \
             mock.patch.object(LegacyRestoreEngine, 'run',
                               lambda self, created_by, **kw: ran.append(1)), \
             mock.patch.object(LegacyRestoreEngine, 'capture_boundary',
                               lambda self, **kw: ran.append(2)), \
             mock.patch.object(LegacyRestoreEngine, 'delta',
                               lambda self, progress_cb=None, boundary=None: {
                                   'totals': {'new': 7}, 'boundary_seen': boundary}):
            summary = LegacyRestoreEngine.restore_from_bak(
                self.bak, work_dir=self.dir, delta_only=True)

        self.assertEqual(ran, [])
        self.assertTrue(summary['delta_only'])
        self.assertEqual(summary['totals']['new'], 7)
        self.assertEqual(summary['boundary_seen'], {'IIMAIL_2026': 2432})

    def test_temp_database_is_dropped_even_when_merge_raises(self):
        with mock.patch.object(LegacyRestoreEngine, 'load_boundary', staticmethod(lambda *a, **k: None)), \
             mock.patch.object(LegacyRestoreEngine, 'run',
                               lambda self, created_by, **kw: (_ for _ in ()).throw(RuntimeError('انقطع'))):
            with self.assertRaises(RuntimeError):
                LegacyRestoreEngine.restore_from_bak(self.bak, work_dir=self.dir)

        dropped = [sql for conn in self.pyodbc.conns for cur in conn.cursors
                   for sql in cur.executed if 'DROP DATABASE' in sql]
        self.assertEqual(len(dropped), 1, 'القاعدة المؤقتة لم تُسقَط بعد الفشل')


class CaptureBoundaryLabelTests(TestCase):

    def test_label_overrides_temp_database_name(self):
        eng = LegacyRestoreEngine('localhost', 'LEGACYRESTORE_123', 'sa', 'x')
        path = os.path.join(tempfile.mkdtemp(prefix='bnd_'), 'boundary.json')
        self.addCleanup(lambda: os.path.exists(path) and os.unlink(path))

        with mock.patch.object(LegacyRestoreEngine, 'connect', lambda self: None), \
             mock.patch.object(LegacyRestoreEngine, 'close', lambda self: None):
            eng._conn = mock.MagicMock()
            eng._conn.cursor.return_value.fetchall.return_value = []
            eng._conn.cursor.return_value.fetchone.return_value = (0, None, None, None)
            payload = eng.capture_boundary(note='n', path=path, label='ARCHMDOC')

        self.assertEqual(payload['database'], 'ARCHMDOC')
        self.assertTrue(os.path.exists(path))


class BakViewSpawnsBackgroundJobTests(TestCase):
    """الصفحةُ كانت تنفّذ استعادةَ ٢٠ ج.ب داخل الطلب — تنتهي المهلةُ ويظنّ المستخدمُ أنها فشلت."""

    def setUp(self):
        self.user = User.objects.create_superuser('boss', 'b@x.y', 'pw12345!')
        self.client.force_login(self.user)

    def test_post_creates_job_and_spawns_process(self):
        with mock.patch('core.views.dashboard._spawn_restore_process',
                        return_value=(True, '')) as spawn, \
             mock.patch.object(LegacyRestoreEngine, 'restore_from_bak') as sync:
            resp = self.client.post(reverse('data_restore'), {
                'action': 'restore_from_bak',
                'bak_path': r'G:\snapshot.bak',
                'bak_server': 'localhost',
                'bak_user': 'sa',
                'bak_password': 'secret',
                'bak_work_dir': r'D:\sqltmp',
                'merge_mode': 'skip_existing',
                'restore_files': 'on',
                'dry_run': 'on',
            })

        self.assertEqual(resp.status_code, 200)
        sync.assert_not_called()
        job = RestoreJob.objects.get()
        self.assertEqual(job.params['bak_path'], r'G:\snapshot.bak')
        self.assertEqual(job.params['work_dir'], r'D:\sqltmp')
        self.assertTrue(job.params['delta_only'])
        self.assertFalse(job.params['include_held'])
        self.assertEqual(spawn.call_args[0][0], 'merge_legacy_bak')
        self.assertEqual(spawn.call_args[0][2], 'secret')
        # الاعتماد لا يُحفظ في الصفّ أبداً
        self.assertNotIn('secret', str(job.params))

    def test_second_job_refused_while_one_is_live(self):
        RestoreJob.objects.create(created_by=self.user, status=RestoreJob.STATUS_RUNNING)
        with mock.patch('core.views.dashboard._spawn_restore_process') as spawn:
            self.client.post(reverse('data_restore'), {
                'action': 'restore_from_bak', 'bak_path': r'G:\s.bak',
                'bak_password': 'secret',
            })
        spawn.assert_not_called()
        self.assertEqual(RestoreJob.objects.count(), 1)


class CommandArgumentTests(TestCase):
    """الأمرُ يقبل ثلاثةَ مداخل، وحارسُه كان يطلب الباكابَ حتّى مع قاعدةٍ مستعادة."""

    def setUp(self):
        User.objects.create_superuser('boss2', 'b2@x.y', 'pw12345!')
        patcher = mock.patch.dict(os.environ, {'LEGACY_SQL_PASSWORD': 'x'})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_from_database_alone_is_accepted(self):
        from django.core.management import call_command

        with mock.patch('core.legacy_restore.LegacyRestoreEngine.merge_from_database',
                        return_value={'books': 5}) as merge, \
             mock.patch('core.legacy_restore.LegacyRestoreEngine.drop_database',
                        return_value=True) as drop, \
             mock.patch('core.views.dashboard._reseed_book_sequences'), \
             mock.patch('core.management.commands.merge_legacy_bak._service_state',
                        return_value='running'):
            call_command('merge_legacy_bak', '--from-database', 'LEGACYRESTORE_1')

        merge.assert_called_once()
        self.assertEqual(merge.call_args[0][0], 'LEGACYRESTORE_1')
        drop.assert_called_once()                      # تُسقَط بعد النجاح
        job = RestoreJob.objects.get()
        self.assertEqual(job.status, RestoreJob.STATUS_DONE)
        self.assertEqual(job.summary['books'], 5)

    def test_keep_db_leaves_the_restored_database(self):
        from django.core.management import call_command

        with mock.patch('core.legacy_restore.LegacyRestoreEngine.merge_from_database',
                        return_value={'books': 1}), \
             mock.patch('core.legacy_restore.LegacyRestoreEngine.drop_database') as drop, \
             mock.patch('core.views.dashboard._reseed_book_sequences'), \
             mock.patch('core.management.commands.merge_legacy_bak._service_state',
                        return_value='running'):
            call_command('merge_legacy_bak', '--from-database', 'LEGACYRESTORE_1', '--keep-db')

        drop.assert_not_called()

    def test_no_source_at_all_is_refused(self):
        from django.core.management import call_command
        from django.core.management.base import CommandError as CE

        with self.assertRaises(CE):
            call_command('merge_legacy_bak')
        self.assertEqual(RestoreJob.objects.count(), 0)
