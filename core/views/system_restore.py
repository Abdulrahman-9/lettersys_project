# -*- coding: utf-8 -*-
"""صفحةُ «استعادة نسخة النظام» — نسخُ القاعدة المشفّرة (``*.dump.enc``) إلى قاعدةٍ جديدة.

القراءةُ والتحقّقُ والبدءُ لمدير النظام وحدَه (``can_restore_system``). التحقّقُ يُشغّل
``verify_backup --json --expect-live`` في عمليّةٍ ابنة ويعيد العدّادات وحدَها؛ والبدءُ
يطلب كتابةَ اسم الملفّ تأكيداً، ثمّ يُطلق ``restore_system_backup`` في الخلفية وتُستطلَع
حالتُه من ``restore_job_status`` كمهامّ الدمج.
"""
import json
import os
import subprocess
import sys

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_POST

from core import backup_verify as bv
from core.backup_service import default_backup_dir, list_db_backups
from core.models import RestoreJob
from core.scoping import can_restore_system
from core.system_restore_service import RestoreRefused, check_target, safe_backup_path, target_name


def _guard(request):
    if not can_restore_system(request.user):
        raise PermissionDenied('استعادةُ نسخة النظام لمدير النظام.')


@login_required
def system_restore(request):
    _guard(request)
    jobs = RestoreJob.objects.filter(params__kind='pg_restore').order_by('-created_at')[:5]
    return render(request, 'core/system_restore.html', {
        'backups': list_db_backups(),
        'backup_dir': default_backup_dir(),
        'running': RestoreJob.running(),
        'jobs': jobs,
        'live_db': settings.DATABASES['default']['NAME'],
    })


@login_required
@require_POST
def system_restore_verify(request):
    """يتحقّق من نسخةٍ قبل استعادتها — العدّاداتُ مقابل القاعدة الحيّة، بلا مساراتٍ ولا مفاتيح."""
    _guard(request)
    try:
        path = safe_backup_path(request.POST.get('file'))
    except RestoreRefused as exc:
        return JsonResponse({'ok': False, 'error': str(exc)}, status=400)
    try:
        res = subprocess.run(
            [sys.executable, 'manage.py', 'verify_backup', str(path), '--json', '--expect-live'],
            cwd=str(settings.BASE_DIR), capture_output=True, timeout=1800,
            env=dict(os.environ, PYTHONIOENCODING='utf-8'),
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    except subprocess.TimeoutExpired:
        return JsonResponse({'ok': False, 'error': 'طال التحقّقُ أكثر من نصف ساعة — جرّبه من الخادم.'})
    try:
        payload = json.loads(res.stdout.decode('utf-8', errors='replace') or '{}')
    except ValueError:
        payload = {}
    if res.returncode not in (bv.EXIT_OK, bv.EXIT_MISMATCH) or not payload:
        return JsonResponse({'ok': False, 'error': f'تعذّر التحقّقُ من النسخة (رمز {res.returncode}).'})
    return JsonResponse({
        'ok': True,
        'matches_live': res.returncode == bv.EXIT_OK,
        'tables': payload.get('tables', {}),
        'differences': payload.get('differences', []),
    })


@login_required
@require_POST
def system_restore_start(request):
    """يبدأ الاستعادةَ إلى قاعدةٍ جديدة بعد تأكيدٍ مكتوب (اسمُ الملفّ نفسُه)."""
    _guard(request)
    name = (request.POST.get('file') or '').strip()
    try:
        safe_backup_path(name)
    except RestoreRefused as exc:
        return JsonResponse({'ok': False, 'error': str(exc)}, status=400)
    if (request.POST.get('confirm') or '').strip() != name:
        return JsonResponse({'ok': False, 'error': 'اكتب اسمَ الملفّ كما هو تأكيداً للاستعادة.'}, status=400)

    live = RestoreJob.running()
    if live:
        return JsonResponse({'ok': False, 'job_id': live.id,
                             'error': f'توجد مهمّةٌ قيد التنفيذ (#{live.id}) — انتظر انتهاءها.'})
    target = target_name()
    try:
        check_target(target)
    except RestoreRefused as exc:
        return JsonResponse({'ok': False, 'error': str(exc)})

    job = RestoreJob.objects.create(
        created_by=request.user, params={'kind': 'pg_restore', 'file': name, 'target': target})
    try:
        subprocess.Popen(
            [sys.executable, 'manage.py', 'restore_system_backup', '--job', str(job.id)],
            cwd=str(settings.BASE_DIR), env=dict(os.environ, PYTHONIOENCODING='utf-8'),
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError as exc:
        RestoreJob.objects.filter(pk=job.pk).update(
            status=RestoreJob.STATUS_FAILED, finished_at=timezone.now(),
            error_message=f'تعذّر تشغيلُ العمليّة: {type(exc).__name__}')
        return JsonResponse({'ok': False, 'error': 'تعذّر تشغيلُ الاستعادة على الخادم.'})
    return JsonResponse({'ok': True, 'job_id': job.id, 'target': target})
