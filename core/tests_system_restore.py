# -*- coding: utf-8 -*-
"""استعادةُ نسخة النظام إلى قاعدةٍ جديدة (قرارُ المالك 2026‑10‑07، البند 3) — حرّاسُها.

لا قاعدةَ حقيقيّة ولا pg_restore في الاختبار: كلُّ ما يلمس الخادمَ مُحاكى، ويُثبَت أنّه لم
يُستدعَ حين يجب أن يُرفض الطلبُ قبله.
"""
import shutil
import subprocess
import tempfile
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse

from core import backup_verify as bv
from core import system_restore_service as svc
from core.models import RestoreJob

PLAIN = b'PGDMP' + b'\x00' * 64


class _BackupDir(TestCase):

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix='sysrestore_test_'))
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        (self.dir / 'db_20261007.dump.enc').write_bytes(b'ENCRYPTED')
        patcher = mock.patch('core.system_restore_service.default_backup_dir', return_value=self.dir)
        patcher.start()
        self.addCleanup(patcher.stop)


class ServiceRefusalTests(_BackupDir):

    def test_unsafe_names_are_refused(self):
        for bad in ('../db.dump.enc', 'x/db.dump.enc', 'x\\db.dump.enc', 'notes.txt', '', 'missing.dump.enc'):
            with self.subTest(name=bad), self.assertRaises(svc.RestoreRefused):
                svc.safe_backup_path(bad)
        self.assertEqual(svc.safe_backup_path('db_20261007.dump.enc').name, 'db_20261007.dump.enc')

    @mock.patch('core.system_restore_service.subprocess.run')
    def test_the_live_database_is_never_a_target(self, run):
        live = 'lettersys_r_20261007_1200'
        with override_settings(DATABASES={**settings.DATABASES,
                                          'default': {**settings.DATABASES['default'], 'NAME': live}}):
            with self.assertRaises(svc.RestoreRefused):
                svc.check_target(live)
        run.assert_not_called()

    @mock.patch('core.system_restore_service.subprocess.run')
    @mock.patch('core.system_restore_service.database_exists', return_value=True)
    def test_an_existing_database_is_refused_before_anything_runs(self, _exists, run):
        with self.assertRaises(svc.RestoreRefused):
            svc.restore_into_new_database('db_20261007.dump.enc', 'lettersys_r_20261007_1200')
        run.assert_not_called()

    @mock.patch('core.system_restore_service.subprocess.run')
    @mock.patch('core.system_restore_service.create_database')
    @mock.patch('core.system_restore_service.database_exists', return_value=False)
    @mock.patch.object(bv, 'resolve_pg_restore', return_value=Path('pg_restore'))
    @mock.patch.object(bv, 'decrypt_if_needed', return_value=(b'NOT-A-DUMP', 'sha'))
    def test_content_that_is_not_a_dump_is_refused(self, _dec, _pg, _exists, create, run):
        with self.assertRaises(svc.RestoreRefused):
            svc.restore_into_new_database('db_20261007.dump.enc', 'lettersys_r_20261007_1200')
        create.assert_not_called()
        run.assert_not_called()

    @mock.patch('core.system_restore_service.create_database')
    @mock.patch('core.system_restore_service.database_exists', return_value=False)
    @mock.patch.object(bv, 'resolve_pg_restore', return_value=Path('pg_restore'))
    @mock.patch.object(bv, 'decrypt_if_needed', return_value=(PLAIN, 'sha'))
    def test_the_plaintext_tempdir_is_removed_when_pg_restore_fails(self, _dec, _pg, _exists, _create):
        made = []
        real = bv.make_secure_tempdir

        def tracked():
            d = real()
            made.append(d)
            return d

        with mock.patch.object(bv, 'make_secure_tempdir', side_effect=tracked), \
                mock.patch('core.system_restore_service.subprocess.run',
                           side_effect=subprocess.CalledProcessError(1, 'pg_restore')):
            with self.assertRaises(subprocess.CalledProcessError):
                svc.restore_into_new_database('db_20261007.dump.enc', 'lettersys_r_20261007_1200')
        self.assertEqual(len(made), 1)
        self.assertFalse(made[0].exists())


class PageGateTests(_BackupDir):

    def setUp(self):
        super().setUp()
        self.boss = User.objects.create_superuser('srboss', 's@x.invalid', 'pw-srboss-1111111')
        self.staff = User.objects.create_user('srstaff', password='pw-srstaff-1111111', is_staff=True)
        for target in ('core.views.system_restore.list_db_backups', 'core.views.system_restore.default_backup_dir'):
            p = mock.patch(target, return_value=[] if 'list' in target else self.dir)
            p.start()
            self.addCleanup(p.stop)

    def test_staff_cannot_open_or_post(self):
        self.client.force_login(self.staff)
        self.assertEqual(self.client.get(reverse('system_restore')).status_code, 403)
        self.assertEqual(self.client.post(reverse('system_restore_verify'), {'file': 'db_20261007.dump.enc'}).status_code, 403)
        self.assertEqual(self.client.post(reverse('system_restore_start'), {'file': 'db_20261007.dump.enc'}).status_code, 403)

    def test_a_traversal_name_is_a_400(self):
        self.client.force_login(self.boss)
        resp = self.client.post(reverse('system_restore_verify'), {'file': '../../etc/passwd.dump.enc'})
        self.assertEqual(resp.status_code, 400)

    @mock.patch('core.views.system_restore.subprocess.Popen')
    def test_start_needs_the_typed_name_and_then_launches_in_the_background(self, popen):
        self.client.force_login(self.boss)
        resp = self.client.post(reverse('system_restore_start'), {'file': 'db_20261007.dump.enc', 'confirm': 'نعم'})
        self.assertEqual(resp.status_code, 400)
        popen.assert_not_called()
        with mock.patch('core.views.system_restore.check_target'):
            resp = self.client.post(reverse('system_restore_start'),
                                    {'file': 'db_20261007.dump.enc', 'confirm': 'db_20261007.dump.enc'})
        self.assertTrue(resp.json()['ok'])
        job = RestoreJob.objects.get(pk=resp.json()['job_id'])
        self.assertEqual(job.params['kind'], 'pg_restore')
        self.assertTrue(svc.TARGET_RE.match(job.params['target']))
        self.assertIn('restore_system_backup', popen.call_args.args[0])

    def test_the_page_renders_for_the_boss(self):
        self.client.force_login(self.boss)
        self.assertContains(self.client.get(reverse('system_restore')), 'استعادة نسخة النظام')
