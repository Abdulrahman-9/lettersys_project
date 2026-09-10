# -*- coding: utf-8 -*-
"""``verify_backup`` — بوّابةُ بصماتٍ على نسخةِ ``pg_dump`` قبل شحنها (Merge9 §10.6).

    python manage.py verify_backup <ملفّ.enc|.dump> [--key PATH]
        [--expect جدول=عدد …] [--expect-live] [--write-plain PATH] [--json]

رموزُ الخروج: 0 مطابق · 1 خطأ · 2 اختلافٌ عن المتوقَّع · 3 المفتاحُ غائب ·
4 ``pg_restore`` غائب.

المنطقُ كلُّه في ``core/backup_verify.py`` (يُختبَر بلا PostgreSQL)؛ هنا التسليكُ
والطباعة. ولا يُطبع محتوى مفتاحٍ ولا قيمةُ عمودٍ مشفَّر — بادئةٌ وطولٌ وبصمة.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from django.core.management.base import BaseCommand

from core import backup_verify as bv


def _plain(value):
    """قيمةٌ قابلةٌ للتسلسل — الاختلافُ قد يحمل قوائمَ وقواميس."""
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    return str(value)


class Command(BaseCommand):
    help = ("يتحقّق من نسخةِ pg_dump (مشفَّرةً أو خاماً) ويطبع بصماتِها — "
            "الأعدادُ وحدَها ليست بصمة (Merge9 §10.1).")

    def add_arguments(self, parser):
        parser.add_argument('backup', help='مسارُ الملفّ (.enc أو .dump)')
        parser.add_argument('--key', default=None,
                            help='مسارُ مفتاح Fernet (الافتراضيّ: .encryption_key)')
        parser.add_argument('--expect', action='append', default=[],
                            metavar='TABLE=COUNT',
                            help='عددُ صفوفٍ متوقَّع لجدول (يتكرّر)')
        parser.add_argument('--expect-live', action='store_true',
                            help='قارِن بالقاعدة الحيّة (Book.all_objects)')
        parser.add_argument('--write-plain', default=None, metavar='PATH',
                            help='احفظ الصريحَ في هذا المسار (خارج المستودع، غيرِ موجود)')
        parser.add_argument('--json', action='store_true', dest='as_json',
                            help='اطبع كلَّ ما قِيس بصيغة JSON')

    # ────────────────────────────────────────────────────────────────────
    def handle(self, *args, **options):
        try:
            payload = self._verify(options)
        except bv.VerifyError as exc:
            self.stderr.write(self.style.ERROR(str(exc)))
            raise SystemExit(exc.code)

        differences = payload.pop('_differences')
        stats = payload.pop('_stats')
        if options['as_json']:
            payload['differences'] = [
                {'key': k, 'in_backup': _plain(a), 'expected': _plain(b)}
                for k, a, b in differences
            ]
            self.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            self._print_text(payload, stats, differences)

        if differences:
            raise SystemExit(bv.EXIT_MISMATCH)
        raise SystemExit(bv.EXIT_OK)

    # ────────────────────────────────────────────────────────────────────
    def _verify(self, options):
        source = Path(options['backup'])
        if not source.is_file():
            raise bv.VerifyError(f'الملفُّ غيرُ موجود: {source}')

        # 1) فحصُ الوجهة أوّلاً (خطأُ مستخدمٍ محضٌ) ثمّ pg_restore — خروج 4
        #    **قبل أيّ فكّ**، فلا يُكتَب صريحٌ على القرص بلا داعٍ.
        target = None
        if options['write_plain']:
            target = bv.check_write_plain_target(options['write_plain'])
        pg_restore_bin = bv.resolve_pg_restore()

        # 2) الفكّ (إن لزم) — المفتاحُ من الملفّ مباشرةً؛ غيابُه خروج 3.
        raw = source.read_bytes()
        plain_bytes, key_sha = bv.decrypt_if_needed(raw, options['key'])
        if not plain_bytes.startswith(bv.PGDMP_MAGIC):
            raise bv.VerifyError(
                'المحتوى ليس نسخةَ pg_dump: رأسُ PGDMP غائب '
                '(التمييزُ بالرأس لا بالامتداد).')

        # 3) الصريحُ إلى مجلّدٍ مؤقّتٍ خارج المستودع، ويُحذف في finally.
        tempdir = bv.make_secure_tempdir()
        try:
            plain_path = bv.write_private(tempdir / 'plain.dump', plain_bytes)
            plain_sha = bv.sha256_of(plain_path)

            stats = bv.parse_copy_stats(
                bv.iter_restore_sql(pg_restore_bin, plain_path))

            if target is not None:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(plain_path, target)
                try:
                    target.chmod(0o600)
                except OSError:
                    pass
        finally:
            shutil.rmtree(tempdir, ignore_errors=True)

        differences = bv.diff_against_expect(stats, self._parse_expect(options['expect']))
        if options['expect_live']:
            differences += bv.diff_against_live(stats)

        return {
            'source': str(source),
            'source_bytes': source.stat().st_size,
            'source_sha256': bv.sha256_of(source),
            'encrypted': key_sha is not None,
            'key_sha8': key_sha,
            'plain_sha256': plain_sha,
            'plain_bytes': len(plain_bytes),
            'pg_restore': str(pg_restore_bin),
            'wrote_plain': str(target) if options['write_plain'] else None,
            'tables': bv.json_payload(stats),
            '_differences': differences,
            '_stats': stats,
        }

    @staticmethod
    def _parse_expect(items):
        expectations = {}
        for item in items:
            if '=' not in item:
                raise bv.VerifyError(f'--expect يحتاج صيغة TABLE=COUNT: {item}')
            table, _, count = item.partition('=')
            try:
                expectations[table.strip()] = int(count.strip())
            except ValueError:
                raise bv.VerifyError(f'--expect: عددٌ غيرُ صحيح في {item}')
        return expectations

    # ────────────────────────────────────────────────────────────────────
    def _print_text(self, payload, stats, differences):
        write = self.stdout.write
        write('── verify_backup ' + '─' * 46)
        write(f'الملفّ        {payload["source"]}')
        write(f'الحجم         {payload["source_bytes"]:,} بايت')
        write(f'sha256(enc)   {payload["source_sha256"]}')
        write(f'المفتاح       ' + (f'sha={payload["key_sha8"]}' if payload['encrypted']
                                   else '(خامٌّ — لا فكّ)'))
        write(f'sha256(plain) {payload["plain_sha256"]}  ({payload["plain_bytes"]:,} بايت)')
        write(f'pg_restore    {payload["pg_restore"]}')
        if payload['wrote_plain']:
            write(f'--write-plain {payload["wrote_plain"]}')
        write('─' * 62)
        for line in bv.format_report(stats):
            write(line)
        write('─' * 62)
        if differences:
            write(self.style.ERROR(f'اختلافات: {len(differences)}'))
            for key, in_backup, expected in differences:
                write(self.style.ERROR(
                    f'  {key}: في النسخة={in_backup!r} · المتوقَّع={expected!r}'))
        else:
            write(self.style.SUCCESS('مطابق — لا اختلاف.'))
