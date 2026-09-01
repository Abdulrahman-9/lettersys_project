# -*- coding: utf-8 -*-
"""
ينفّذ مهمّة دمج مسجَّلة في `RestoreJob` — خارج دورة الطلب.

يُستدعى بطريقتين، ونفس المسار في الحالتين:
  • من الواجهة: تُنشئ صفّ المهمّة ثم تُشغّل هذا الأمر كعمليةٍ منفصلة وتعود فوراً.
  • من الطرفية مباشرةً — للمزامنة الكبيرة الأولى، حيث تريد أن ترى التقدّم بعينك.

الاعتماد يصل عبر بيئة العملية (LEGACY_SQL_PASSWORD) ولا يُحفظ في صفّ المهمّة.

    python manage.py run_restore_job --job 12
    python manage.py run_restore_job --database ARCHMDOC --mode skip_existing --user admin
"""
import os
import traceback

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from core.legacy_restore import LegacyRestoreEngine
from core.models import RestoreJob


class Command(BaseCommand):
    help = 'تنفيذ مهمّة دمج من المصدر القديم (RestoreJob) خارج دورة الطلب.'

    def add_arguments(self, parser):
        parser.add_argument('--job', type=int, default=None,
                            help='معرّف مهمّة قائمة. بدونه تُنشأ مهمّة جديدة من الوسائط.')
        parser.add_argument('--server', default='localhost')
        parser.add_argument('--database', default='ARCHMDOC')
        parser.add_argument('--sql-user', default='sa')
        parser.add_argument('--mode', default='skip_existing',
                            choices=['skip_existing', 'update_existing', 'fresh'])
        parser.add_argument('--no-files', action='store_true', help='بلا إحضار المرفقات')
        parser.add_argument('--include-held', action='store_true',
                            help='استيراد الصفوف الموقوفة أيضاً (قرار صريح)')
        parser.add_argument('--user', default=None, help='اسم المستخدم المالك للكتب المُنشأة')

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
            owner = (User.objects.filter(username=options['user']).first()
                     if options['user'] else None) or \
                    User.objects.filter(is_superuser=True, is_active=True).order_by('id').first()
            p = {
                'server': options['server'], 'database': options['database'],
                'username': options['sql_user'], 'mode': options['mode'],
                'restore_files': not options['no_files'],
                'include_held': options['include_held'],
            }
            job = RestoreJob.objects.create(params=p, created_by=owner)
            self.stdout.write(f'أُنشئت المهمّة #{job.id}')

        if job.status not in RestoreJob.LIVE_STATUSES:
            raise CommandError(f'المهمّة #{job.id} حالتها «{job.status}» — لا تُستأنف.')

        RestoreJob.objects.filter(pk=job.pk).update(
            status=RestoreJob.STATUS_RUNNING, pid=os.getpid(),
            phase='بدء التنفيذ…', error_message='')

        def progress(msg):
            # الإلغاء يُفحص بين الدفعات لا داخل نقل مرفق — فلا يُترك ملفٌ نصفه.
            if RestoreJob.objects.filter(pk=job.pk, cancel_requested=True).exists():
                raise KeyboardInterrupt('أُلغيت بطلب المستخدم')
            job.touch(phase=msg)
            self.stdout.write(f'  … {msg}')

        engine = LegacyRestoreEngine(p.get('server', 'localhost'), p.get('database', 'ARCHMDOC'),
                                     p.get('username', 'sa'), password)
        try:
            summary = engine.run(
                created_by=job.created_by,
                restore_files=p.get('restore_files', True),
                mode=p.get('mode', 'skip_existing'),
                include_held=p.get('include_held', False),
                progress_cb=progress,
            )
            if summary.get('aborted'):
                RestoreJob.objects.filter(pk=job.pk).update(
                    status=RestoreJob.STATUS_FAILED, finished_at=timezone.now(),
                    phase='أُوقفت', error_message=summary.get('reason', ''))
                self.stdout.write(self.style.WARNING(summary.get('reason', 'أُوقفت.')))
                return

            summary['created_entities'] = engine._created_entities[:200]
            RestoreJob.objects.filter(pk=job.pk).update(
                status=RestoreJob.STATUS_DONE, finished_at=timezone.now(),
                phase='اكتملت', summary=summary)

            from core.views.dashboard import _reseed_book_sequences
            _reseed_book_sequences()

            self.stdout.write(self.style.SUCCESS(
                'اكتمل الدمج: ' + '، '.join(f'{k}={v}' for k, v in sorted(summary.items())
                                             if isinstance(v, int) and v)))
        except KeyboardInterrupt as exc:
            engine.close()
            RestoreJob.objects.filter(pk=job.pk).update(
                status=RestoreJob.STATUS_CANCELLED, finished_at=timezone.now(),
                phase='أُلغيت', error_message=str(exc))
            self.stdout.write(self.style.WARNING('أُلغيت المهمّة.'))
        except Exception as exc:
            engine.close()
            RestoreJob.objects.filter(pk=job.pk).update(
                status=RestoreJob.STATUS_FAILED, finished_at=timezone.now(),
                phase='فشلت', error_message=f'{exc}\n{traceback.format_exc()[-2000:]}')
            raise CommandError(f'فشل الدمج: {exc}')
