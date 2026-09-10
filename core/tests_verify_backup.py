# -*- coding: utf-8 -*-
"""اختباراتُ ``verify_backup`` — **بلا PostgreSQL** (عقدُ Merge9 §10.6).

نصُّ ``COPY`` محضَّرٌ داخل الاختبار، و``iter_restore_sql`` تُستبدَل بمولِّدٍ يُعيده،
وملفّاتُ Fernet مؤقّتةٌ بمفتاحٍ اختباريّ. فلا حاجةَ لخادمِ قاعدةٍ ولا لـ``pg_restore``
ولا لمفتاحِ الإنتاج — وهذا شرطُ أن تُشغَّل الحزمةُ على أيّ جهاز.

كلُّ متطلَّبٍ من 10.6-1 … 10.6-13 له اختبارٌ، وكلُّ حارسٍ له **طفرةٌ حمراء**
مسجَّلةٌ في ``D:/migration/logs/verify_backup_mutations.md``.
"""

from __future__ import annotations

import json
import os
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from cryptography.fernet import Fernet
from django.conf import settings
from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase

from core import backup_verify as bv

#: قيمةٌ مشفَّرةٌ **مصطنَعة** تلعب دور كلمة البريد — لا يجوز أن تظهر في أيّ مخرَج.
FAKE_SECRET = 'enc::gAAAAABm' + 'Z' * 100        # 112 حرفاً، بادئتُه enc::
FAKE_SECRET_CHUNK = FAKE_SECRET[20:36]           # 16 حرفاً من جوفه

PGDMP_BYTES = b'PGDMP' + b'\x00' * 64 + b'fake custom-format dump'


# ════════════════════════════════════════════════════════════════════════════
#  نصُّ COPY المحضَّر
# ════════════════════════════════════════════════════════════════════════════

def copy_block(table, columns, rows):
    lines = ['COPY public.%s (%s) FROM stdin;' % (table, ', '.join(columns))]
    lines += ['\t'.join(str(c) for c in row) for row in rows]
    lines.append('\\.')
    lines.append('')
    return lines


def sample_sql(*, books=3, training=1, deleted=1, entities=4, merged=2,
               active_entities=3, migration_head='0077_archive_events_and_history',
               usernames=('admin', 'clerk'), smtp=FAKE_SECRET,
               imap_sync='t', mail_active='t', memory_rows=2,
               emaillog=(('sent', 2), ('failed', 1)), history=2,
               attachments=2, attach_deleted=1,
               sequences=((bv.COPY_NULL, 'incoming_internal', 2433),
                          (bv.COPY_NULL, 'outgoing_internal', 358))):
    """أسطرُ SQL كما يُخرجها ``pg_restore -f -`` — بأرقامٍ يتحكّم بها الاختبار."""
    lines = ['--', '-- PostgreSQL database dump', '--', '',
             'SET statement_timeout = 0;', '']

    book_rows = []
    for i in range(1, books + 1):
        book_rows.append((i, 'incoming_internal',
                          't' if i <= training else 'f',
                          't' if i <= deleted else 'f'))
    lines += copy_block('core_book', ('id', 'kind', 'is_training', 'is_deleted'),
                        book_rows)

    entity_rows = []
    for i in range(1, entities + 1):
        entity_rows.append((i, f'جهة{i}',
                            '1' if i <= merged else bv.COPY_NULL,
                            't' if i <= active_entities else 'f'))
    lines += copy_block('core_entity', ('id', 'name', 'merged_into_id', 'is_active'),
                        entity_rows)

    lines += copy_block(
        'core_emailsettings',
        ('id', 'smtp_password', 'imap_password', 'imap_sync_enabled', 'is_active'),
        [(1, smtp, smtp, imap_sync, mail_active)])

    lines += copy_block(
        'django_migrations', ('id', 'app', 'name', 'applied'),
        [(1, 'core', '0001_initial', '2026-01-01'),
         (7, 'contenttypes', '0002_x', '2026-01-01'),
         (5, 'core', migration_head, '2026-09-01')])

    lines += copy_block(
        'auth_user', ('id', 'username', 'is_active'),
        [(i + 1, name, 't') for i, name in enumerate(usernames)])

    lines += copy_block(
        'core_booksequence', ('id', 'department_id', 'kind', 'next_number'),
        [(i + 1, dept, kind, num)
         for i, (dept, kind, num) in enumerate(sequences)])

    lines += copy_block('core_letterheadmemory', ('id', 'letterhead'),
                        [(i + 1, 'ترويسة') for i in range(memory_rows)])

    log_rows, rid = [], 0
    for status, count in emaillog:
        for _ in range(count):
            rid += 1
            log_rows.append((rid, 'x@y.z', status))
    lines += copy_block('core_bookemaillog', ('id', 'to_address', 'status'), log_rows)

    lines += copy_block('core_bookhistory', ('id', 'book_id'),
                        [(i + 1, 1) for i in range(history)])
    lines += copy_block(
        'core_attachment', ('id', 'book_id', 'is_deleted'),
        [(i + 1, 1, 't' if i < attach_deleted else 'f') for i in range(attachments)])
    lines.append('-- انتهى')
    return lines


# ════════════════════════════════════════════════════════════════════════════
#  10.6-7 — parse_copy_stats دالّةٌ نقيّة
# ════════════════════════════════════════════════════════════════════════════

class ParseCopyStatsTests(SimpleTestCase):

    def test_counts_rows_per_table(self):
        stats = bv.parse_copy_stats(sample_sql(books=5, entities=4))
        self.assertEqual(stats['core_book']['rows'], 5)
        self.assertEqual(stats['core_entity']['rows'], 4)
        self.assertEqual(stats['core_letterheadmemory']['rows'], 2)

    def test_book_fingerprints(self):
        stats = bv.parse_copy_stats(sample_sql(books=10, training=4, deleted=3))
        self.assertEqual(stats['core_book']['is_training'], 4)
        self.assertEqual(stats['core_book']['is_deleted'], 3)

    def test_entity_fingerprints_read_three_measures(self):
        """674 صفّاً · 353 نشطة · 256 merged_into — ثلاثةٌ تُقرأ معاً (C4)."""
        stats = bv.parse_copy_stats(
            sample_sql(entities=10, merged=3, active_entities=6))
        self.assertEqual(stats['core_entity']['rows'], 10)
        self.assertEqual(stats['core_entity']['merged_into'], 3)
        self.assertEqual(stats['core_entity']['merged_into_null'], 7)
        self.assertEqual(stats['core_entity']['is_active'], 6)

    def test_email_probe_keeps_prefix_and_length_only(self):
        stats = bv.parse_copy_stats(sample_sql())
        entry = stats['core_emailsettings']['smtp_password']
        self.assertEqual(entry, {'prefix': 'enc::', 'len': len(FAKE_SECRET)})
        self.assertEqual(stats['core_emailsettings']['imap_sync_enabled'], 't')
        self.assertEqual(stats['core_emailsettings']['is_active'], 't')

    def test_email_probe_flags_plaintext_password(self):
        stats = bv.parse_copy_stats(sample_sql(smtp='hunter2plaintext'))
        self.assertEqual(stats['core_emailsettings']['smtp_password']['prefix'], 'plain')

    def test_migration_head_is_highest_core_id(self):
        stats = bv.parse_copy_stats(sample_sql(migration_head='0077_x'))
        self.assertEqual(stats['django_migrations']['core_head'], '0077_x')

    def test_usernames_and_sequences_and_emaillog(self):
        stats = bv.parse_copy_stats(sample_sql(
            usernames=('zed', 'admin'), emaillog=(('sent', 2), ('failed', 3))))
        self.assertEqual(sorted(stats['auth_user']['usernames']), ['admin', 'zed'])
        self.assertEqual(stats['core_bookemaillog']['by_status'],
                         {'sent': 2, 'failed': 3})
        self.assertEqual(
            [s['next_number'] for s in stats['core_booksequence']['sequences']],
            ['2433', '358'])
        self.assertEqual(stats['core_attachment']['is_deleted'], 1)
        self.assertEqual(stats['core_bookhistory']['rows'], 2)

    def test_missing_table_is_absent_not_an_error(self):
        stats = bv.parse_copy_stats(['-- لا كتلَ COPY هنا'])
        self.assertNotIn('core_book', stats)
        report = '\n'.join(bv.format_report(stats))
        self.assertIn('core_book', report)
        self.assertIn('غيرُ موجود', report)


# ════════════════════════════════════════════════════════════════════════════
#  البنيةُ المشتركة لاختبارات الأمر
# ════════════════════════════════════════════════════════════════════════════

class CommandHarness:
    """يُحضّر ملفّ مفتاحٍ ونسخةً مشفَّرةً ويستبدل ``pg_restore``."""

    def setUp(self):
        super().setUp()
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)

        self.key = Fernet.generate_key()
        self.key_path = self.tmp / 'testing.key'
        self.key_path.write_bytes(self.key)

        self.enc_path = self.tmp / 'pg_backup_test.dump.enc'
        self.enc_path.write_bytes(Fernet(self.key).encrypt(PGDMP_BYTES))

        self.sql_lines = sample_sql()
        self._patch(mock.patch.object(
            bv, 'iter_restore_sql',
            side_effect=lambda binary, path: iter(self.sql_lines)))
        self._patch(mock.patch(
            'core.backup_service.find_pg_restore',
            return_value=str(self.tmp / 'fake_pg_restore')))
        # حارسٌ دائم: أيُّ استدعاءٍ لسكّ المفتاح يُسقط الاختبار (10.6-3).
        self.mint = self._patch(mock.patch(
            'core.encryption.get_or_create_encryption_key',
            side_effect=AssertionError('verify_backup استدعى سكَّ المفتاح')))

    def _patch(self, patcher):
        started = patcher.start()
        self.addCleanup(patcher.stop)
        return started

    def run_command(self, *args, **kwargs):
        """يُشغّل الأمرَ ويُعيد ``(رمزُ الخروج، المخرَجُ النصّيّ)``."""
        out, err = StringIO(), StringIO()
        kwargs.setdefault('stdout', out)
        kwargs.setdefault('stderr', err)
        try:
            call_command('verify_backup', *args, **kwargs)
            code = 0
        except SystemExit as exc:
            code = exc.code
        return code, out.getvalue() + err.getvalue()


# ════════════════════════════════════════════════════════════════════════════
#  10.6-1/2 — القبولُ والتمييزُ بالرأس
# ════════════════════════════════════════════════════════════════════════════

class SourceDetectionTests(CommandHarness, SimpleTestCase):

    def test_encrypted_backup_passes(self):
        code, out = self.run_command(str(self.enc_path), key=str(self.key_path))
        self.assertEqual(code, 0, out)
        self.assertIn('core_book', out)

    def test_raw_dump_passes_without_key(self):
        raw = self.tmp / 'plain.dump'
        raw.write_bytes(PGDMP_BYTES)
        code, out = self.run_command(str(raw))
        self.assertEqual(code, 0, out)
        self.assertIn('خامٌّ', out)

    def test_header_decides_not_extension(self):
        """ملفٌّ اسمُه .dump وهو مشفَّرٌ فعلاً — يُفكّ ويمرّ."""
        misnamed = self.tmp / 'looks_raw.dump'
        misnamed.write_bytes(Fernet(self.key).encrypt(PGDMP_BYTES))
        code, out = self.run_command(str(misnamed), key=str(self.key_path))
        self.assertEqual(code, 0, out)

    def test_content_without_pgdmp_header_fails(self):
        bad = self.tmp / 'not_a_dump.dump.enc'
        bad.write_bytes(Fernet(self.key).encrypt(b'this is not a dump at all'))
        code, out = self.run_command(str(bad), key=str(self.key_path))
        self.assertNotEqual(code, 0)
        self.assertIn('PGDMP', out)

    def test_missing_file_fails(self):
        code, _ = self.run_command(str(self.tmp / 'nope.enc'))
        self.assertEqual(code, bv.EXIT_ERROR)


# ════════════════════════════════════════════════════════════════════════════
#  10.6-3/4 — المفتاح: قراءةٌ مباشرة · خروج 3 · لا سكّ · sha[:8]
# ════════════════════════════════════════════════════════════════════════════

class KeyHandlingTests(CommandHarness, SimpleTestCase):

    def test_missing_key_exits_3(self):
        code, out = self.run_command(
            str(self.enc_path), key=str(self.tmp / 'absent.key'))
        self.assertEqual(code, bv.EXIT_NO_KEY)
        self.assertIn('absent.key', out)

    def test_empty_key_file_exits_3(self):
        empty = self.tmp / 'empty.key'
        empty.write_bytes(b'')
        code, _ = self.run_command(str(self.enc_path), key=str(empty))
        self.assertEqual(code, bv.EXIT_NO_KEY)

    def test_never_calls_get_or_create_encryption_key(self):
        """الحارسُ الأهمّ: السكُّ يُخفي أنّ المفتاحَ الصحيح غائب."""
        code, out = self.run_command(str(self.enc_path), key=str(self.key_path))
        self.assertEqual(code, 0, out)
        self.mint.assert_not_called()

    def test_missing_key_does_not_mint_either(self):
        code, _ = self.run_command(
            str(self.enc_path), key=str(self.tmp / 'absent.key'))
        self.assertEqual(code, bv.EXIT_NO_KEY)
        self.mint.assert_not_called()

    def test_prints_key_sha8(self):
        code, out = self.run_command(str(self.enc_path), key=str(self.key_path))
        self.assertEqual(code, 0, out)
        self.assertIn(bv.key_fingerprint(self.key), out)
        self.assertEqual(len(bv.key_fingerprint(self.key)), 8)

    def test_never_prints_key_material(self):
        _, out = self.run_command(str(self.enc_path), key=str(self.key_path))
        self.assertNotIn(self.key.decode(), out)
        self.assertNotIn(self.key.decode()[:16], out)

    def test_wrong_key_fails_clearly(self):
        other = self.tmp / 'other.key'
        other.write_bytes(Fernet.generate_key())
        code, out = self.run_command(str(self.enc_path), key=str(other))
        self.assertEqual(code, bv.EXIT_ERROR)
        self.assertIn('InvalidToken', out)

    def test_default_key_path_is_the_encryption_module_constant(self):
        from core.encryption import ENCRYPTION_KEY_FILE
        self.assertEqual(bv.default_key_path(), Path(ENCRYPTION_KEY_FILE))


# ════════════════════════════════════════════════════════════════════════════
#  10.6-5/6 — الصريح: mkdtemp خارج المستودع · 0600 · sha · حذفٌ في finally
# ════════════════════════════════════════════════════════════════════════════

class PlaintextHandlingTests(CommandHarness, SimpleTestCase):

    def test_tempdir_is_outside_base_dir(self):
        created = []
        real = bv.make_secure_tempdir

        def spy():
            path = real()
            created.append(path)
            return path

        with mock.patch.object(bv, 'make_secure_tempdir', side_effect=spy):
            code, out = self.run_command(str(self.enc_path), key=str(self.key_path))

        self.assertEqual(code, 0, out)
        self.assertEqual(len(created), 1)
        self.assertFalse(bv.is_inside_repo(created[0]))

    def test_tempdir_inside_repo_is_refused(self):
        """لو أشارت TMPDIR إلى داخل الشجرة (مستودعٌ عامّ) — يُرفض."""
        inside = Path(settings.BASE_DIR) / 'verify_backup_inside_tmp'
        inside.mkdir(exist_ok=True)
        self.addCleanup(lambda: inside.exists() and inside.rmdir())
        with mock.patch('tempfile.mkdtemp', return_value=str(inside)):
            with self.assertRaises(bv.VerifyError) as ctx:
                bv.make_secure_tempdir()
        self.assertIn('داخل المستودع', str(ctx.exception))

    def test_tempdir_removed_even_on_exception(self):
        created = []
        real = bv.make_secure_tempdir

        def spy():
            path = real()
            created.append(path)
            return path

        with mock.patch.object(bv, 'make_secure_tempdir', side_effect=spy), \
                mock.patch.object(bv, 'iter_restore_sql',
                                  side_effect=bv.VerifyError('pg_restore انفجر')):
            code, _ = self.run_command(str(self.enc_path), key=str(self.key_path))

        self.assertEqual(code, bv.EXIT_ERROR)
        self.assertEqual(len(created), 1)
        self.assertFalse(created[0].exists(), 'المجلّدُ المؤقّت بقي بعد الاستثناء')

    def test_prints_plain_sha256_before_deleting(self):
        import hashlib
        expected = hashlib.sha256(PGDMP_BYTES).hexdigest()
        code, out = self.run_command(str(self.enc_path), key=str(self.key_path))
        self.assertEqual(code, 0, out)
        self.assertIn(expected, out)

    def test_write_private_sets_owner_only_mode(self):
        target = self.tmp / 'p.bin'
        bv.write_private(target, b'x')
        if os.name != 'nt':                       # ويندوز لا يطبّق بتّات POSIX
            self.assertEqual(target.stat().st_mode & 0o777, 0o600)
        self.assertEqual(target.read_bytes(), b'x')

    # ── --write-plain ───────────────────────────────────────────────────
    def test_write_plain_writes_outside_repo(self):
        target = self.tmp / 'ship.dump'
        code, out = self.run_command(str(self.enc_path), key=str(self.key_path),
                                     write_plain=str(target))
        self.assertEqual(code, 0, out)
        self.assertEqual(target.read_bytes(), PGDMP_BYTES)

    def test_write_plain_refuses_existing_file_and_leaves_it(self):
        target = self.tmp / 'existing.dump'
        target.write_bytes(b'DO NOT TOUCH')
        code, out = self.run_command(str(self.enc_path), key=str(self.key_path),
                                     write_plain=str(target))
        self.assertNotEqual(code, 0)
        self.assertEqual(target.read_bytes(), b'DO NOT TOUCH')

    def test_write_plain_refuses_path_inside_repo(self):
        target = Path(settings.BASE_DIR) / 'leaked_ship.dump'
        # تنظيفٌ دفاعيّ: إن سقط الحارسُ (أو عُطِّل في طفرة) لا يبقى الأثرُ في الشجرة.
        self.addCleanup(lambda: target.exists() and target.unlink())
        code, out = self.run_command(str(self.enc_path), key=str(self.key_path),
                                     write_plain=str(target))
        self.assertNotEqual(code, 0)
        self.assertIn('المستودع', out)
        self.assertFalse(target.exists())


# ════════════════════════════════════════════════════════════════════════════
#  10.6-8 — لا يُطبع سرّ
# ════════════════════════════════════════════════════════════════════════════

class SecretRedactionTests(CommandHarness, SimpleTestCase):

    def test_text_output_has_no_secret_value(self):
        code, out = self.run_command(str(self.enc_path), key=str(self.key_path))
        self.assertEqual(code, 0, out)
        self.assertNotIn(FAKE_SECRET, out)
        self.assertNotIn(FAKE_SECRET_CHUNK, out)

    def test_text_output_describes_prefix_and_length(self):
        _, out = self.run_command(str(self.enc_path), key=str(self.key_path))
        self.assertIn('prefix=enc::', out)
        self.assertIn(f'len={len(FAKE_SECRET)}', out)
        # `enc::` لا يظهر إلّا موصوفاً — لا كقيمةٍ عارية.
        self.assertEqual(out.count('enc::'), out.count('prefix=enc::'))

    def test_json_output_has_no_secret_value(self):
        code, out = self.run_command(str(self.enc_path), key=str(self.key_path),
                                     as_json=True)
        self.assertEqual(code, 0, out)
        self.assertNotIn(FAKE_SECRET, out)
        self.assertNotIn(FAKE_SECRET_CHUNK, out)
        payload = json.loads(out)
        mail = payload['tables']['core_emailsettings']
        self.assertEqual(mail['smtp_password'],
                         {'prefix': 'enc::', 'len': len(FAKE_SECRET)})

    def test_plaintext_password_is_flagged_without_being_shown(self):
        self.sql_lines = sample_sql(smtp='SuperSecretPlaintextPassword!!')
        code, out = self.run_command(str(self.enc_path), key=str(self.key_path))
        self.assertEqual(code, 0, out)
        self.assertIn('prefix=plain', out)
        self.assertNotIn('SuperSecretPlaintextPassword!!', out)
        self.assertNotIn('SuperSecretPlaint', out)


# ════════════════════════════════════════════════════════════════════════════
#  10.6-11 — pg_restore غائبٌ ⟵ خروج 4 قبل أيّ فكّ
# ════════════════════════════════════════════════════════════════════════════

class PgRestoreLookupTests(CommandHarness, SimpleTestCase):

    def test_missing_pg_restore_exits_4(self):
        with mock.patch('core.backup_service.find_pg_restore', return_value=None):
            code, out = self.run_command(str(self.enc_path), key=str(self.key_path))
        self.assertEqual(code, bv.EXIT_NO_PG_RESTORE)
        self.assertIn('PG_RESTORE_BIN', out)

    def test_missing_pg_restore_reported_before_any_decryption(self):
        """الرمزُ 4 يسبق قراءةَ المفتاح — لا صريحَ ولا فكَّ بلا أداةٍ تقرؤه."""
        with mock.patch('core.backup_service.find_pg_restore', return_value=None), \
                mock.patch.object(bv, 'decrypt_if_needed',
                                  side_effect=AssertionError('فُكَّ قبل فحص pg_restore')):
            code, _ = self.run_command(
                str(self.enc_path), key=str(self.tmp / 'absent.key'))
        self.assertEqual(code, bv.EXIT_NO_PG_RESTORE)

    def test_prints_pg_restore_path(self):
        _, out = self.run_command(str(self.enc_path), key=str(self.key_path))
        self.assertIn('fake_pg_restore', out)

    def test_env_var_wins_over_path(self):
        from core.backup_service import find_pg_tool
        fake = self.tmp / 'custom_pg_restore.exe'
        fake.write_text('x')
        with mock.patch.dict(os.environ, {'PG_RESTORE_BIN': str(fake)}):
            self.assertEqual(find_pg_tool('pg_restore', 'PG_RESTORE_BIN'), str(fake))


# ════════════════════════════════════════════════════════════════════════════
#  10.6-9/10 — --expect و --expect-live
# ════════════════════════════════════════════════════════════════════════════

class ExpectTests(CommandHarness, SimpleTestCase):

    def test_expect_match_exits_0(self):
        self.sql_lines = sample_sql(books=13239)
        code, out = self.run_command(str(self.enc_path), key=str(self.key_path),
                                     expect=['core_book=13239'])
        self.assertEqual(code, 0, out)

    def test_expect_mismatch_exits_2_and_names_the_difference(self):
        self.sql_lines = sample_sql(books=13238)
        code, out = self.run_command(str(self.enc_path), key=str(self.key_path),
                                     expect=['core_book=13239'])
        self.assertEqual(code, bv.EXIT_MISMATCH)
        self.assertIn('core_book.rows', out)

    def test_expect_unknown_table_is_a_difference(self):
        code, out = self.run_command(str(self.enc_path), key=str(self.key_path),
                                     expect=['core_nope=1'])
        self.assertEqual(code, bv.EXIT_MISMATCH)

    def test_expect_bad_syntax_errors(self):
        code, _ = self.run_command(str(self.enc_path), key=str(self.key_path),
                                   expect=['core_book'])
        self.assertEqual(code, bv.EXIT_ERROR)


class ExpectLiveTests(CommandHarness, TestCase):
    """يقارن بالقاعدة الحيّة — SQLite في الذاكرة يكفي (لا PostgreSQL)."""

    def setUp(self):
        super().setUp()
        from core.models import Book, EmailSettings, Entity

        parent = Entity.objects.create(name='الجهة الأمّ')
        Entity.objects.create(name='نسخةٌ مدموجة', merged_into=parent, is_active=False)
        clerk = User.objects.create_user('clerk', password='x')
        Book.objects.create(title='كتابٌ عاديّ', kind='incoming_internal',
                            created_by=clerk)
        Book.objects.create(title='كتابُ تدريب', kind='incoming_internal',
                            created_by=clerk, is_training=True)
        deleted = Book.objects.create(title='محذوف', kind='incoming_internal',
                                      created_by=clerk)
        Book.all_objects.filter(pk=deleted.pk).update(is_deleted=True)
        mail = EmailSettings.get()
        EmailSettings.objects.filter(pk=mail.pk).update(
            smtp_password=FAKE_SECRET, imap_password=FAKE_SECRET,
            imap_sync_enabled=True, is_active=True)

        self.live = bv.live_fingerprints()
        self.sql_lines = self._sql_matching_live()

    def _sql_matching_live(self):
        """نصُّ COPY مبنيٌّ على القاعدة الحيّة — الاختلافُ يُدخَل عمداً في كلّ اختبار."""
        return sample_sql(**self._live_kwargs())

    def _live_kwargs(self, **overrides):
        live = self.live
        kwargs = dict(
            books=live['core_book']['rows'],
            training=live['core_book']['is_training'],
            deleted=live['core_book']['is_deleted'],
            entities=live['core_entity']['rows'],
            merged=live['core_entity']['merged_into'],
            active_entities=live['core_entity']['is_active'],
            migration_head=live['django_migrations']['core_head'],
            usernames=tuple(live['auth_user']['usernames']),
            memory_rows=live['core_letterheadmemory']['rows'],
            emaillog=tuple(live['core_bookemaillog']['by_status'].items()),
            history=live['core_bookhistory']['rows'],
            attachments=live['core_attachment']['rows'],
            attach_deleted=live['core_attachment']['is_deleted'],
            sequences=tuple((s['department_id'], s['kind'], s['next_number'])
                            for s in live['core_booksequence']['sequences']),
        )
        kwargs.update(overrides)
        return kwargs

    def test_matching_backup_exits_0(self):
        code, out = self.run_command(str(self.enc_path), key=str(self.key_path),
                                     expect_live=True)
        self.assertEqual(code, 0, out)
        self.assertIn('مطابق', out)

    def test_book_count_drift_exits_2(self):
        self.sql_lines = sample_sql(
            **self._live_kwargs(books=self.live['core_book']['rows'] + 1))
        code, out = self.run_command(str(self.enc_path), key=str(self.key_path),
                                     expect_live=True)
        self.assertEqual(code, bv.EXIT_MISMATCH)
        self.assertIn('core_book.rows', out)

    def test_merged_into_drift_exits_2(self):
        """درسُ 10.1 حرفيّاً: الأعدادُ تطابق والبصمةُ لا."""
        # الأعدادُ كلُّها كما هي — البصمةُ وحدَها تغيّرت (درسُ 10.1 حرفيّاً).
        self.sql_lines = sample_sql(**self._live_kwargs(merged=0))
        code, out = self.run_command(str(self.enc_path), key=str(self.key_path),
                                     expect_live=True)
        self.assertEqual(code, bv.EXIT_MISMATCH)
        self.assertIn('core_entity.merged_into', out)

    def test_uses_all_objects_not_default_manager(self):
        """المديرُ الافتراضيّ يُخفي المحذوفَ ناعماً — استعمالُه يُعلن نسخةً سليمةً ناقصة."""
        from core.models import Book
        self.assertEqual(self.live['core_book']['rows'], Book.all_objects.count())
        self.assertGreater(Book.all_objects.count(), Book.objects.count())

    def test_password_shape_drift_exits_2(self):
        self.sql_lines = self._sql_matching_live()
        self.sql_lines = [line.replace(FAKE_SECRET, 'plaintextpassword')
                          for line in self.sql_lines]
        code, out = self.run_command(str(self.enc_path), key=str(self.key_path),
                                     expect_live=True)
        self.assertEqual(code, bv.EXIT_MISMATCH)
        self.assertIn('core_emailsettings.smtp_password', out)
        self.assertNotIn('plaintextpassword', out)

    def test_migration_head_drift_exits_2(self):
        self.sql_lines = sample_sql(
            **self._live_kwargs(migration_head='0001_initial_only'))
        code, out = self.run_command(str(self.enc_path), key=str(self.key_path),
                                     expect_live=True)
        self.assertEqual(code, bv.EXIT_MISMATCH)
        self.assertIn('django_migrations.core_head', out)
