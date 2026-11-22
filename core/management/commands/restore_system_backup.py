# -*- coding: utf-8 -*-
"""restore_system_backup — يستعيد نسخةَ النظام المشفّرة إلى قاعدةٍ **جديدة** (مهمّةٌ في الخلفية).

تُطلقها صفحةُ «استعادة نسخة النظام» (``/books/restore-system/``) بعد تأكيدٍ مكتوب، وتُستطلَع
حالتُها من ``restore_job_status`` كمهامّ الدمج. لا تكتب في القاعدة الحيّة شيئاً؛ والتبديلُ
إلى القاعدة الجديدة أمرٌ يشغّله المالكُ (``use_restored_database``) ثمّ إعادةُ تشغيل الخادم.

    python manage.py restore_system_backup --job 12
"""
import logging
import os

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from core import backup_verify as bv
from core.models import RestoreJob
from core.system_restore_service import RestoreRefused, restore_into_new_database

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'يستعيد نسخةَ النظام المشفّرة إلى قاعدةٍ جديدة (لا فوق الحيّة).'

    def add_arguments(self, parser):
        parser.add_argument('--job', type=int, required=True, help='معرّفُ مهمّة الاستعادة')

    def handle(self, *args, **options):
        job = RestoreJob.objects.filter(pk=options['job']).first()
        if not job or (job.params or {}).get('kind') != 'pg_restore':
            raise CommandError(f"لا مهمّةَ استعادةٍ بالمعرّف {options['job']}.")
        if job.status not in RestoreJob.LIVE_STATUSES:
            raise CommandError(f'المهمّة #{job.id} حالتها «{job.status}» — لا تُستأنف.')

        RestoreJob.objects.filter(pk=job.pk).update(
            status=RestoreJob.STATUS_RUNNING, pid=os.getpid(), phase='بدء التنفيذ…', error_message='')

        def fail(message):
            RestoreJob.objects.filter(pk=job.pk).update(
                status=RestoreJob.STATUS_FAILED, finished_at=timezone.now(), phase='فشلت',
                error_message=message)

        params = job.params
        try:
            summary = restore_into_new_database(
                params.get('file', ''), params.get('target', ''), report=lambda phase: job.touch(phase=phase))
        except (RestoreRefused, bv.VerifyError) as exc:
            # فشلُ pg_restore يصل RestoreRefused من الخدمة بعد إزالة القاعدة الناقصة (11-22)
            fail(str(exc))
            raise CommandError(str(exc))
        except Exception as exc:
            fail(f'فشلت الاستعادة: {type(exc).__name__} — التفصيلُ في سجلّ الخادم.')
            logger.exception('restore_system_backup job=%s failed', job.pk)
            raise

        RestoreJob.objects.filter(pk=job.pk).update(
            status=RestoreJob.STATUS_DONE, finished_at=timezone.now(), phase='اكتملت', summary=summary)
        self.stdout.write(self.style.SUCCESS(
            f"اكتملت: {summary['books']} كتاباً في «{summary['target']}». للتبديل: {summary['command']} ثمّ أعد تشغيل الخادم."))
