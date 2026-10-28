# -*- coding: utf-8 -*-
"""
دمجٌ آليٌّ كامل من ملفّ باكاب النظام القديم إلى قاعدة الإنتاج — بأمرٍ واحد.

يسلسل الخطوات التي كانت تُنفَّذ يدوياً، بلا فجوةٍ بينها:
  ١ فكّ الضغط إن لزم (.zip / .tar.gz)
  ٢ استعادة الـ.bak إلى قاعدة SQL Server **مؤقتة** (لا تُلمس قاعدةٌ قائمة)
  ٣ قراءة حدّ المصدر المحفوظ ⟵ تمييز «الجديد» عن «القديم الذي لم يُستورد»
  ٤ دمج الجديد وحدَه بمفتاح `source_ref` (لا يحذف ولا يطمس شيئاً)
  ٥ كتابة الحدّ الجديد ليكون أساس الدمج القادم
  ٦ إسقاط القاعدة المؤقتة وملفاتها، ثمّ إعادة بذر عدّادات الترقيم

التقدّم يُكتب في صفّ `RestoreJob`، فتعرضه صفحة «استعادة البيانات» ويقبل الإلغاء.

    $env:LEGACY_SQL_PASSWORD="…"
    python manage.py merge_legacy_bak "D:\\Backups\\archive.bak" --dry-run
    python manage.py merge_legacy_bak "D:\\Backups\\archive.bak" --work-dir D:\\sqltmp

`--dry-run` يستعيد ويحسب الفرق ويعرضه بلا كتابة أيّ كتاب — شغّله أوّلاً دائماً.
`--keep-db` يُبقي القاعدة المستعادة، و`--from-database <اسم>` يدمج منها مباشرةً:
معاينةٌ ثمّ دمجٌ باستعادةٍ **واحدة** بدل اثنتين (الاستعادة هي الساعاتُ لا الدمج).
قاعدةُ القسم فارغة؟ لا حدَّ محفوظاً ⟵ كلُّ صفوف المصدر «جديدة» وتُؤخذ كلُّها.
"""
import os
import shutil
import subprocess
import sys
import traceback

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from core.legacy_restore import LegacyRestoreEngine
from core.models import RestoreJob

SQL_SERVICE = 'MSSQLSERVER'


def _service_state(name):
    """حالة خدمة ويندوز: 'running' / 'stopped' / None إن تعذّر القياس."""
    if sys.platform != 'win32':
        return None
    sc = shutil.which('sc')
    if not sc:
        return None
    try:
        out = subprocess.run([sc, 'query', name], capture_output=True, text=True,
                             timeout=20).stdout.upper()
    except (OSError, subprocess.SubprocessError):
        return None
    if 'RUNNING' in out:
        return 'running'
    if 'STOPPED' in out or 'STOP_PENDING' in out:
        return 'stopped'
    return None


def _start_service(name):
    """محاولة تشغيل الخدمة. يُعيد (نجح, رسالة) — الفشل ليس استثناءً."""
    net = shutil.which('net')
    if not net:
        return False, 'الأداة net غير متاحة.'
    try:
        p = subprocess.run([net, 'start', name], capture_output=True, text=True, timeout=180)
    except (OSError, subprocess.SubprocessError) as exc:
        return False, str(exc)
    if p.returncode == 0:
        return True, ''
    return False, (p.stdout or p.stderr or '').strip()[:300]


class Command(BaseCommand):
    help = 'دمج آليّ كامل من ملفّ باكاب قديم (.bak/.zip) إلى قاعدة الإنتاج.'

    def add_arguments(self, parser):
        parser.add_argument('bak_path', nargs='?', default=None,
                            help='مسار ملفّ الباكاب. يُقرأ من المهمّة عند تمرير --job.')
        parser.add_argument('--job', type=int, default=None,
                            help='تنفيذ مهمّة قائمة بدل إنشاء واحدة.')
        parser.add_argument('--server', default='localhost')
        parser.add_argument('--sql-user', default='sa')
        parser.add_argument('--work-dir', default='',
                            help='مجلّد ملفّات القاعدة المؤقتة (قرصٌ فيه مساحة ~٢.٥ ضعف حجم الباكاب).')
        parser.add_argument('--mode', default='skip_existing',
                            choices=['skip_existing', 'update_existing'],
                            help='skip_existing: الجديد فقط. update_existing: يُحدّث المُستورَد سابقاً أيضاً.')
        parser.add_argument('--no-files', action='store_true', help='بلا إحضار المرفقات')
        parser.add_argument('--include-held', action='store_true',
                            help='استيراد الصفوف القديمة غير المستوردة أيضاً (قرار صريح).')
        parser.add_argument('--dry-run', action='store_true',
                            help='استعادة + حساب الفرق فقط، بلا كتابة أيّ كتاب.')
        parser.add_argument('--boundary-key', default='ARCHMDOC',
                            help='اسم المصدر المنطقيّ الذي يُحفظ حدّه (الافتراضي ARCHMDOC).')
        parser.add_argument('--user', default=None, help='مالك الكتب المُنشأة.')
        parser.add_argument('--no-start-sql', action='store_true',
                            help='لا تحاول تشغيل خدمة SQL Server إن كانت متوقّفة.')
        parser.add_argument('--keep-db', action='store_true',
                            help='أبقِ القاعدة المؤقتة بعد الانتهاء (لدمجٍ تالٍ بلا إعادة استعادة).')
        parser.add_argument('--from-database', default='',
                            help='ادمج من قاعدةٍ مستعادة سلفاً (تخطّي الاستعادة). تُسقَط بعدها إلّا مع --keep-db.')

    def handle(self, *args, **options):
        password = os.environ.get('LEGACY_SQL_PASSWORD', '')
        if not password:
            raise CommandError('LEGACY_SQL_PASSWORD غير مضبوط في بيئة العملية.')

        User = get_user_model()
        if options['job']:
            job = RestoreJob.objects.filter(pk=options['job']).first()
            if not job:
                raise CommandError(f"لا توجد مهمّة بالمعرّف {options['job']}.")
            p = job.params or {}
        else:
            if not options['bak_path'] and not options['from_database']:
                raise CommandError(
                    'مطلوبٌ أحدُ ثلاثة: مسارُ باكاب، أو --from-database لقاعدةٍ '
                    'مستعادة سلفاً، أو --job لمهمّةٍ قائمة.')
            owner = (User.objects.filter(username=options['user']).first()
                     if options['user'] else None) or \
                User.objects.filter(is_superuser=True, is_active=True).order_by('id').first()
            p = {
                'source': 'bak',
                'bak_path': options['bak_path'],
                'server': options['server'],
                'username': options['sql_user'],
                'work_dir': options['work_dir'],
                'mode': options['mode'],
                'restore_files': not options['no_files'],
                'include_held': options['include_held'],
                'delta_only': options['dry_run'],
                'boundary_key': options['boundary_key'],
                'keep_db': options['keep_db'],
                'from_database': options['from_database'],
            }
            job = RestoreJob.objects.create(params=p, created_by=owner)
            self.stdout.write(f'أُنشئت المهمّة #{job.id}')

        bak_path = p.get('bak_path') or ''
        from_database = (p.get('from_database') or '').strip()
        if not bak_path and not from_database:
            raise CommandError('المهمّة بلا مسار باكاب ولا قاعدةٍ مستعادة.')
        if job.status not in RestoreJob.LIVE_STATUSES:
            raise CommandError(f'المهمّة #{job.id} حالتها «{job.status}» — لا تُستأنف.')

        RestoreJob.objects.filter(pk=job.pk).update(
            status=RestoreJob.STATUS_RUNNING, pid=os.getpid(),
            phase='فحص المتطلّبات…', error_message='')

        def progress(msg):
            # الإلغاء يُفحص بين الخطوات لا داخل نقل مرفق — فلا يُترك ملفٌّ نصفه.
            if RestoreJob.objects.filter(pk=job.pk, cancel_requested=True).exists():
                raise KeyboardInterrupt('أُلغيت بطلب المستخدم')
            job.touch(phase=msg)
            self.stdout.write(f'  … {msg}')

        # ── تشغيل خدمة SQL Server إن كانت متوقّفة ──
        # الخدمة تبقى متوقّفة على هذا الجهاز بين الدمجات، وتركُها للمستخدم كان
        # يُنهي التشغيل برسالة اتصالٍ غامضة بعد دقائق من فكّ الضغط.
        state = _service_state(SQL_SERVICE)
        if state == 'stopped' and not options['no_start_sql']:
            progress(f'خدمة {SQL_SERVICE} متوقّفة — محاولة تشغيلها…')
            ok, err = _start_service(SQL_SERVICE)
            if not ok:
                msg = (f'تعذّر تشغيل خدمة {SQL_SERVICE} آلياً ({err}). '
                       f'شغّلها بصلاحية مسؤول: net start {SQL_SERVICE}')
                RestoreJob.objects.filter(pk=job.pk).update(
                    status=RestoreJob.STATUS_FAILED, finished_at=timezone.now(),
                    phase='متطلّب ناقص', error_message=msg)
                raise CommandError(msg)

        delta_only = bool(p.get('delta_only'))
        keep_db = bool(p.get('keep_db'))
        common = dict(
            sql_server=p.get('server', 'localhost'),
            admin_user=p.get('username', 'sa'),
            admin_password=password,
            created_by=job.created_by,
            restore_files=p.get('restore_files', True),
            mode=p.get('mode', 'skip_existing'),
            boundary_key=p.get('boundary_key', 'ARCHMDOC'),
            include_held=p.get('include_held', False),
            delta_only=delta_only,
            progress_cb=progress,
        )
        try:
            if from_database:
                # النسخةُ مستعادةٌ سلفاً: نتخطّى عشرات الدقائق ونمضي إلى الدمج.
                summary = LegacyRestoreEngine.merge_from_database(
                    from_database, note=from_database, **common)
                summary['temp_db'] = from_database
                if not keep_db and not summary.get('aborted'):
                    progress(f'جارٍ إسقاط القاعدة المؤقتة [{from_database}]…')
                    LegacyRestoreEngine.drop_database(
                        from_database, sql_server=common['sql_server'],
                        admin_user=common['admin_user'], admin_password=password)
                    summary['temp_db_kept'] = False
                else:
                    summary['temp_db_kept'] = True
            else:
                summary = LegacyRestoreEngine.restore_from_bak(
                    bak_path, work_dir=p.get('work_dir') or None,
                    keep_db=keep_db, **common)
            if summary.get('aborted'):
                RestoreJob.objects.filter(pk=job.pk).update(
                    status=RestoreJob.STATUS_FAILED, finished_at=timezone.now(),
                    phase='أُوقفت', error_message=summary.get('reason', ''))
                self.stdout.write(self.style.WARNING(summary.get('reason', 'أُوقفت.')))
                return

            RestoreJob.objects.filter(pk=job.pk).update(
                status=RestoreJob.STATUS_DONE, finished_at=timezone.now(),
                phase='اكتملت المعاينة' if delta_only else 'اكتملت', summary=summary)

            if summary.get('temp_db_kept'):
                self.stdout.write(self.style.WARNING(
                    f"  القاعدة المؤقتة باقية: [{summary['temp_db']}] — "
                    f"ادمج منها بـ--from-database {summary['temp_db']} (تُسقَط بعدها)."))
            if delta_only:
                self._report_delta(summary)
            else:
                from core.views.dashboard import _reseed_book_sequences
                _reseed_book_sequences()
                self.stdout.write(self.style.SUCCESS(
                    'اكتمل الدمج: ' + '، '.join(f'{k}={v}' for k, v in sorted(summary.items())
                                                 if isinstance(v, int) and v)))
                if summary.get('boundary_path'):
                    self.stdout.write(f"  حدّ المصدر الجديد: {summary['boundary_path']}")
        except KeyboardInterrupt as exc:
            RestoreJob.objects.filter(pk=job.pk).update(
                status=RestoreJob.STATUS_CANCELLED, finished_at=timezone.now(),
                phase='أُلغيت', error_message=str(exc))
            self.stdout.write(self.style.WARNING('أُلغيت المهمّة.'))
        except Exception as exc:
            RestoreJob.objects.filter(pk=job.pk).update(
                status=RestoreJob.STATUS_FAILED, finished_at=timezone.now(),
                phase='فشلت', error_message=f'{exc}\n{traceback.format_exc()[-2000:]}')
            raise CommandError(f'فشل الدمج: {exc}')

    def _report_delta(self, summary):
        t = summary.get('totals') or {}
        w = self.stdout.write
        w(self.style.SUCCESS('معاينة فقط — لم يُكتب أيّ كتاب.'))
        w(f"  صفوف المصدر: {t.get('rows', 0):,}")
        w(f"  معروفٌ عندنا: {t.get('known', 0):,}")
        w(self.style.SUCCESS(f"  جديد يُضاف:   {t.get('new', 0):,}"
                             f"  ({(t.get('new_bytes', 0) / 2**20):.0f} م.ب مرفقات)"))
        w(f"  موقوفٌ (قديم لم يُستورد، يحتاج --include-held): {t.get('held', 0):,}")
        w(f"  كتبٌ من داخل التطبيق لا تُمسّ: {t.get('app_only', 0):,}")
        if not summary.get('has_boundary'):
            w(self.style.WARNING(
                '  لا حدَّ محفوظاً لهذا المصدر — كلّ غير المعروف عُدّ «جديداً».'))
        for row in summary.get('tables', []):
            if row.get('new') or row.get('held'):
                w(f"    {row['table']}: جديد {row['new']} (معرّفات "
                  f"{row.get('first_new_id')}–{row.get('last_new_id')}) · موقوف {row['held']}")
