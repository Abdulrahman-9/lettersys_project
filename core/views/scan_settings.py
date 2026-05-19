# -*- coding: utf-8 -*-
"""
core.views.scan_settings
=========================
صفحة إعدادات الماسح الضوئي — CaptureOnTouch + Hot Folder Watcher.
"""
import json
import logging
import os
import re
import sys
from urllib.parse import quote

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render, redirect
from django.views.decorators.http import require_http_methods

from core.models import ScanSettings

logger = logging.getLogger('lettersys')

# المسارات الشائعة لتثبيت CaptureOnTouch على Windows
_COT_SEARCH_PATHS = [
    r"C:\Program Files\Canon\CaptureOnTouch\CaptureOnTouch.exe",
    r"C:\Program Files (x86)\Canon\CaptureOnTouch\CaptureOnTouch.exe",
    r"C:\Program Files\Canon\My Image Garden\CaptureOnTouch.exe",
    r"C:\Program Files (x86)\Canon\My Image Garden\CaptureOnTouch.exe",
    r"C:\Program Files\Canon\IJ Scan Utility\CaptureOnTouch.exe",
    r"C:\Program Files (x86)\Canon\IJ Scan Utility\CaptureOnTouch.exe",
]


def _detect_capture_exe() -> str:
    """يبحث عن CaptureOnTouch.exe في المسارات الشائعة وفي Registry."""
    # 1) فحص المسارات الشائعة
    for path in _COT_SEARCH_PATHS:
        if os.path.isfile(path):
            return path

    # 2) البحث في Registry (HKCU + HKLM)
    if sys.platform == 'win32':
        try:
            import winreg
            for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
                for reg_path in (
                    r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
                    r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall",
                ):
                    try:
                        with winreg.OpenKey(hive, reg_path) as base:
                            for i in range(winreg.QueryInfoKey(base)[0]):
                                try:
                                    with winreg.OpenKey(base, winreg.EnumKey(base, i)) as sub:
                                        name = winreg.QueryValueEx(sub, 'DisplayName')[0]
                                        if 'CaptureOnTouch' in name or 'Canon' in name:
                                            loc = winreg.QueryValueEx(sub, 'InstallLocation')[0]
                                            candidate = os.path.join(loc, 'CaptureOnTouch.exe')
                                            if os.path.isfile(candidate):
                                                return candidate
                                except (OSError, FileNotFoundError):
                                    continue
                    except OSError:
                        continue
        except Exception:
            pass

    return ''


def _detect_watch_folder() -> str:
    """يكتشف مجلد المسح الضوئي — يفحص OneDrive + Pictures + Documents بالترتيب."""
    from django.conf import settings as dj_settings
    # 1) من settings.py / .env
    folder = getattr(dj_settings, 'SCAN_WATCH_FOLDER', '').strip()
    if folder and os.path.isdir(folder):
        return folder

    home     = os.path.expanduser('~')
    onedrive = os.environ.get('OneDrive', os.path.join(home, 'OneDrive'))

    # المرشّحون مرتَّبون تنازلياً حسب الأولوية
    candidates = [
        os.path.join(onedrive, 'Pictures', 'Scans'),   # OneDrive\Pictures\Scans (Canon/CaptureOnTouch)
        os.path.join(onedrive, 'Pictures', 'Scan'),
        os.path.join(onedrive, 'Documents', 'Scans'),
        os.path.join(home,     'Pictures', 'Scans'),
        os.path.join(home,     'Pictures', 'Scan'),
        os.path.join(home,     'Documents', 'Scans'),
    ]
    for c in candidates:
        if os.path.isdir(c):
            return c

    # Fallback: أنشئ المجلد عند الحاجة (لا يُنشأ هنا — فقط اقتراح)
    return os.path.join(home, 'Documents', 'Scans')


def _get_system_info() -> dict:
    """معلومات النظام لعرضها في صفحة الإعدادات."""
    base = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    scan_manager_path = os.path.join(base, 'scan_manager', 'scan_manager.py')
    register_script   = os.path.join(base, 'scan_manager', 'register_scan_protocol.py')

    pythonw = os.path.join(os.path.dirname(sys.executable), 'pythonw.exe')
    if not os.path.isfile(pythonw):
        pythonw = sys.executable

    return {
        'scan_manager_path': scan_manager_path,
        'register_script':   register_script,
        'python_exe':        sys.executable,
        'pythonw_exe':       pythonw,
        'platform':          sys.platform,
        'scan_manager_exists': os.path.isfile(scan_manager_path),
        'register_exists':     os.path.isfile(register_script),
    }


@login_required
def scan_settings_page(request):
    """عرض وحفظ إعدادات الماسح الضوئي."""
    cfg = ScanSettings.get()

    if request.method == 'POST':
        cfg.capture_exe_path  = request.POST.get('capture_exe_path', '').strip()
        cfg.watch_folder      = request.POST.get('watch_folder', '').strip()
        cfg.server_url        = request.POST.get('server_url', 'http://localhost:8000').strip()
        cfg.auto_open_browser = request.POST.get('auto_open_browser') == 'on'
        cfg.window_topmost    = request.POST.get('window_topmost') == 'on'
        cfg.save()
        logger.info('[ScanSettings] updated by %s', request.user)

        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'ok': True, 'message': 'تم حفظ الإعدادات بنجاح'})
        return redirect('scan_settings')

    # اكتشاف تلقائي للمسارات إذا كانت الحقول فارغة
    suggested_exe    = '' if cfg.capture_exe_path else _detect_capture_exe()
    suggested_folder = '' if cfg.watch_folder     else _detect_watch_folder()

    auto_saved = False
    update_fields = []

    # حفظ مسار CaptureOnTouch تلقائياً عند الاكتشاف
    if suggested_exe and not cfg.capture_exe_path:
        cfg.capture_exe_path = suggested_exe
        update_fields.append('capture_exe_path')
        auto_saved = True
        logger.info('[ScanSettings] auto-detected CaptureOnTouch: %s', suggested_exe)

    # حفظ مجلد المراقبة تلقائياً عند الاكتشاف (يُشغّل الـ watcher تلقائياً)
    if suggested_folder and not cfg.watch_folder and os.path.isdir(suggested_folder):
        cfg.watch_folder = suggested_folder
        update_fields.append('watch_folder')
        auto_saved = True
        logger.info('[ScanSettings] auto-detected watch folder: %s', suggested_folder)

    if update_fields:
        cfg.save(update_fields=update_fields)

    ctx = {
        'cfg':              cfg,
        'watcher_status':   cfg.watcher_status,
        'suggested_exe':    suggested_exe,
        'suggested_folder': suggested_folder,
        'auto_saved':       auto_saved,
        'sys_info':         _get_system_info(),
    }
    return render(request, 'core/scan_settings.html', ctx)


@login_required
@require_http_methods(['GET'])
def scan_watcher_status_api(request):
    """حالة الـ watcher الخلفي — تُستدعى بـ AJAX من الصفحة."""
    from django.core.cache import cache
    status     = cache.get('scan_watcher_status', 'stopped')
    last       = cache.get('scan_watcher_last_file', '')
    count      = cache.get('scan_watcher_file_count', 0)
    last_token = cache.get('scan_watcher_last_token', '')
    return JsonResponse({'status': status, 'last_file': last, 'file_count': count, 'last_token': last_token})


@login_required
@require_http_methods(['GET'])
def scan_watcher_diagnostics(request):
    """
    تشخيص شامل لـ Hot Folder Watcher — يُستدعى من لوحة التشخيص في صفحة الإعدادات.
    يجمع كل المؤشرات لصورة كاملة عن صحة المنظومة:
      • حالة الـ thread (running/stopped/error + آخر دورة)
      • المجلد (موجود؟ قابل للقراءة؟ كم ملفاً فيه الآن؟)
      • الإحصائيات التراكمية (rأى/تخطّى/عالج)
      • إعدادات CaptureOnTouch
    """
    import time as _time
    from pathlib import Path
    from django.core.cache import cache

    cfg = ScanSettings.get()
    folder = (cfg.watch_folder or '').strip()

    # ─ معلومات الـ watcher ────────────────────────────────────────────────────
    status         = cache.get('scan_watcher_status', 'stopped')
    last_cycle_at  = cache.get('scan_watcher_last_cycle_at')
    last_error     = cache.get('scan_watcher_last_error', '')
    pid            = cache.get('scan_watcher_pid')
    seconds_since  = (_time.time() - last_cycle_at) if last_cycle_at else None

    watcher_info = {
        'status':                    status,
        'pid':                       pid,
        'last_cycle_at':             last_cycle_at,
        'seconds_since_last_cycle':  round(seconds_since, 1) if seconds_since is not None else None,
        'last_error':                last_error or '',
        # الـ thread يفترض أن يدور كل 2s، فإذا تجاوز 10s فهناك مشكلة
        'is_alive':                  bool(last_cycle_at and seconds_since is not None and seconds_since < 10),
    }

    # ─ معلومات المجلد ─────────────────────────────────────────────────────────
    folder_info = {
        'configured':    folder,
        'exists':        False,
        'readable':      False,
        'is_dir':        False,
        'file_count_now': 0,
        'files_preview': [],
    }
    if folder:
        p = Path(folder)
        folder_info['exists'] = p.exists()
        folder_info['is_dir'] = p.is_dir() if p.exists() else False
        if folder_info['is_dir']:
            try:
                EXTS = {'.pdf', '.jpg', '.jpeg', '.png', '.tif', '.tiff'}
                files = sorted(
                    (f for f in p.iterdir() if f.is_file() and f.suffix.lower() in EXTS),
                    key=lambda f: f.stat().st_mtime,
                    reverse=True,
                )
                folder_info['readable']       = True
                folder_info['file_count_now'] = len(files)
                folder_info['files_preview']  = [
                    {
                        'name':    f.name,
                        'size':    f.stat().st_size,
                        'age_sec': round(_time.time() - f.stat().st_mtime, 1),
                    }
                    for f in files[:5]
                ]
            except (PermissionError, OSError) as exc:
                folder_info['readable'] = False
                folder_info['error']    = str(exc)

    # ─ الإحصائيات التراكمية ───────────────────────────────────────────────────
    stats = {
        'files_seen_total':      cache.get('scan_watcher_files_seen', 0),
        'files_skipped_total':   cache.get('scan_watcher_files_skipped', 0),
        'files_processed_total': cache.get('scan_watcher_file_count', 0),
        'last_file':             cache.get('scan_watcher_last_file', ''),
        'last_token':            cache.get('scan_watcher_last_token', ''),
    }

    # ─ إعدادات CaptureOnTouch ─────────────────────────────────────────────────
    settings_info = {
        'capture_exe_path':   cfg.capture_exe_path,
        'capture_exe_exists': bool(cfg.capture_exe_path and os.path.isfile(cfg.capture_exe_path)),
        'auto_open_browser':  cfg.auto_open_browser,
        'window_topmost':     cfg.window_topmost,
        'server_url':         cfg.server_url,
    }

    return JsonResponse({
        'watcher':  watcher_info,
        'folder':   folder_info,
        'stats':    stats,
        'settings': settings_info,
    })


# بايتات PNG صغيرة صالحة (1x1 أبيض) — تُستخدم كـ fallback لاختبار الالتقاط
# إذا لم يوجد ملف اختبار حقيقي في static/test_assets/
_PNG_1X1_WHITE = bytes.fromhex(
    '89504e470d0a1a0a'  # PNG signature
    '0000000d49484452000000010000000108060000001f15c489'  # IHDR
    '0000000d49444154789c63f8cfc0c000000003000100182d0e8a0000000049454e44ae426082'  # IDAT + IEND
)


@login_required
@require_http_methods(['POST'])
def scan_test_capture(request):
    """
    اختبار end-to-end للـ Watcher:
      1. يلتقط عدّاد files_seen الحالي
      2. ينسخ ملف اختبار إلى المجلد المُراقَب (sample_scan.pdf أو PNG اصطناعي)
      3. ينتظر حتى 15 ثانية، يتحقق ما إذا التقطه الـ Watcher (زاد العدّاد)
      4. يُعيد نتيجة واضحة مع تفاصيل التشخيص
    """
    import time as _time
    import shutil
    from pathlib import Path
    from django.core.cache import cache
    from django.conf import settings as dj_settings

    cfg = ScanSettings.get()
    folder = (cfg.watch_folder or '').strip()

    if not folder:
        return JsonResponse({
            'ok': False, 'stage': 'config',
            'error': 'مجلد المراقبة غير مكوّن في الإعدادات',
        }, status=400)

    watch_path = Path(folder)
    if not watch_path.exists() or not watch_path.is_dir():
        return JsonResponse({
            'ok': False, 'stage': 'folder',
            'error': f'المجلد غير موجود: {folder}',
        }, status=400)

    # ابحث عن ملف اختبار حقيقي في static/test_assets/
    base = Path(dj_settings.BASE_DIR) if hasattr(dj_settings, 'BASE_DIR') else Path(__file__).resolve().parent.parent.parent
    sample_candidates = [
        base / 'static' / 'test_assets' / 'sample_scan.pdf',
        base / 'static' / 'test_assets' / 'sample_scan.png',
        base / 'static' / 'test_assets' / 'sample_scan.jpg',
    ]
    sample_src = next((c for c in sample_candidates if c.is_file()), None)

    test_name = f'_watcher_test_{int(_time.time())}'
    if sample_src:
        ext = sample_src.suffix.lower()
        test_file = watch_path / f'{test_name}{ext}'
        try:
            shutil.copy2(str(sample_src), str(test_file))
        except OSError as exc:
            return JsonResponse({
                'ok': False, 'stage': 'copy',
                'error': f'فشل نسخ ملف الاختبار: {exc}',
            }, status=500)
        used_real_sample = True
    else:
        test_file = watch_path / f'{test_name}.png'
        try:
            with open(test_file, 'wb') as f:
                f.write(_PNG_1X1_WHITE)
        except OSError as exc:
            return JsonResponse({
                'ok': False, 'stage': 'write',
                'error': f'فشل كتابة ملف الاختبار: {exc}',
            }, status=500)
        used_real_sample = False

    # استطلاع الـ Watcher
    seen_before = cache.get('scan_watcher_files_seen', 0) or 0
    proc_before = cache.get('scan_watcher_file_count', 0) or 0
    deadline = _time.time() + 15.0
    detected = False
    processed = False
    while _time.time() < deadline:
        _time.sleep(0.7)
        seen_now = cache.get('scan_watcher_files_seen', 0) or 0
        proc_now = cache.get('scan_watcher_file_count', 0) or 0
        if seen_now > seen_before:
            detected = True
            if proc_now > proc_before:
                processed = True
                break
            # ربما لا يزال يعالج OCR — انتظر قليلاً للاكتمال
            if processed:
                break

    # تنظيف: إذا الملف لم يُلتَقَط فلن يُنقَل، نحذفه يدوياً
    if test_file.exists():
        try:
            test_file.unlink()
        except OSError:
            pass

    last_file  = cache.get('scan_watcher_last_file', '')
    last_token = cache.get('scan_watcher_last_token', '')
    last_error = cache.get('scan_watcher_last_error', '')

    if detected and processed:
        return JsonResponse({
            'ok':         True,
            'stage':      'done',
            'message':    'نجح الاختبار: الـ Watcher التقط الملف ومعالجه بنجاح',
            'last_file':  last_file,
            'last_token': last_token,
            'used_real_sample': used_real_sample,
        })
    if detected:
        return JsonResponse({
            'ok':         True,
            'stage':      'detected_only',
            'message':    'الـ Watcher التقط الملف لكن المعالجة لم تكتمل خلال 15 ثانية (قد يكون OCR بطيء)',
            'last_file':  last_file,
            'last_error': last_error,
            'used_real_sample': used_real_sample,
        })
    return JsonResponse({
        'ok':         False,
        'stage':      'not_detected',
        'error':      'الـ Watcher لم يلتقط ملف الاختبار خلال 15 ثانية',
        'hint':       'تحقق من حالة الـ Watcher في لوحة التشخيص (هل يدور؟)، وأن المجلد صحيح',
        'last_error': last_error,
    }, status=504)


@login_required
@require_http_methods(['GET'])
def scan_check_protocol(request):
    """
    يفحص وجود بروتوكول lettersys-scan:// في Registry (Windows فقط).
    يتحقق أيضاً أن scan_manager.py في الأمر المسجَّل فعلاً موجود على القرص.
    """
    if sys.platform != 'win32':
        return JsonResponse({'installed': False, 'platform': sys.platform})
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r'Software\Classes\lettersys-scan\shell\open\command',
        )
        cmd, _ = winreg.QueryValueEx(key, '')
        winreg.CloseKey(key)
        # تحقق أن scan_manager.py في الأمر موجود فعلاً (يحمي من تثبيت يدوي بمسار خاطئ)
        m = re.search(r'"([^"]+scan_manager\.py)"', cmd, re.IGNORECASE)
        if m and not os.path.isfile(m.group(1)):
            return JsonResponse({'installed': False, 'reason': 'script_missing', 'command': cmd})
        return JsonResponse({'installed': True, 'command': cmd})
    except FileNotFoundError:
        return JsonResponse({'installed': False})
    except Exception as exc:
        return JsonResponse({'installed': False, 'error': str(exc)})


@login_required
@require_http_methods(['GET'])
def scan_download_installer(request):
    """تحميل سكريبت تثبيت البروتوكول كملف .py."""
    from django.http import FileResponse, Http404
    script_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        'scan_manager', 'register_scan_protocol.py',
    )
    if not os.path.isfile(script_path):
        raise Http404
    return FileResponse(
        open(script_path, 'rb'),
        as_attachment=True,
        filename='register_scan_protocol.py',
    )


@login_required
@require_http_methods(['POST'])
def scan_install_protocol(request):
    """
    يُسجّل بروتوكول lettersys-scan:// مباشرة في HKCU.
    يعمل بنفس صلاحيات مستخدم Django — لا يحتاج Run as Administrator.
    """
    if sys.platform != 'win32':
        return JsonResponse({'ok': False, 'error': 'هذه الميزة تعمل على Windows فقط'})
    try:
        import winreg

        base              = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        scan_manager_path = os.path.join(base, 'scan_manager', 'scan_manager.py')

        if not os.path.isfile(scan_manager_path):
            return JsonResponse({
                'ok': False,
                'error': f'لم يُعثر على scan_manager.py في: {scan_manager_path}',
            })

        pythonw = os.path.join(os.path.dirname(sys.executable), 'pythonw.exe')
        if not os.path.isfile(pythonw):
            pythonw = sys.executable

        command  = f'"{pythonw}" "{scan_manager_path}" "%1"'
        protocol = 'lettersys-scan'
        root     = winreg.HKEY_CURRENT_USER
        base_key = rf'Software\Classes\{protocol}'

        key = winreg.CreateKey(root, base_key)
        winreg.SetValueEx(key, '',             0, winreg.REG_SZ, 'URL:LetterSys Scan Protocol')
        winreg.SetValueEx(key, 'URL Protocol', 0, winreg.REG_SZ, '')
        winreg.CloseKey(key)

        icon_key = winreg.CreateKey(root, rf'{base_key}\DefaultIcon')
        winreg.SetValueEx(icon_key, '', 0, winreg.REG_SZ, f'"{pythonw}",0')
        winreg.CloseKey(icon_key)

        cmd_key = winreg.CreateKey(root, rf'{base_key}\shell\open\command')
        winreg.SetValueEx(cmd_key, '', 0, winreg.REG_SZ, command)
        winreg.CloseKey(cmd_key)

        logger.info('[ScanProtocol] installed by %s: %s', request.user, command)
        return JsonResponse({'ok': True, 'command': command})
    except Exception as exc:
        logger.error('[ScanProtocol] install failed: %s', exc)
        return JsonResponse({'ok': False, 'error': str(exc)})


@login_required
@require_http_methods(['GET'])
def scan_file_serve(request, token: str):
    """
    يخدم ملف المسح المرتبط بـ scan_token للعرض في الواجهة.
    processed_path يأتي من الكاش الداخلي — ليس من مدخلات المستخدم.
    """
    import mimetypes
    from django.http import FileResponse, Http404
    from django.core.cache import cache

    data = cache.get(f'scan_token:{token}')
    if not data:
        logger.warning('[ScanServe] token not in cache: %s', token[:8])
        raise Http404('token expired')

    file_path = data.get('processed_path', '')
    if not file_path:
        logger.warning('[ScanServe] processed_path missing for token %s — cache keys: %s',
                       token[:8], list(data.keys()))
        raise Http404('processed_path missing')

    if not os.path.isfile(file_path):
        logger.warning('[ScanServe] file not on disk: %s', file_path)
        raise Http404('file not on disk')

    mime, _ = mimetypes.guess_type(file_path)
    mime = mime or 'application/octet-stream'
    return FileResponse(open(file_path, 'rb'), content_type=mime)


@login_required
@require_http_methods(['GET'])
def scan_list_files(request):
    """
    قائمة بآخر الملفات الممسوحة في المجلد المُكوَّن (أو OneDrive\\Pictures\\Scans افتراضياً).
    تُرتَّب تنازلياً حسب آخر تعديل. الحد الأقصى 20 ملفاً.
    """
    import time as _time
    from pathlib import Path

    ALLOWED_EXTS = {'.pdf', '.jpg', '.jpeg', '.png', '.tif', '.tiff'}
    cfg = ScanSettings.get()

    # اختر المجلد: مكوَّن → مُكتشَف → اقتراح
    folder = (cfg.watch_folder or '').strip() or _detect_watch_folder()
    folder_path = Path(folder)

    if not folder_path.exists() or not folder_path.is_dir():
        return JsonResponse({
            'ok': True,
            'folder': str(folder),
            'folder_exists': False,
            'files': [],
            'message': 'المجلد غير موجود — راجع إعدادات الماسح',
        })

    files = []
    try:
        for entry in folder_path.iterdir():
            if not entry.is_file() or entry.suffix.lower() not in ALLOWED_EXTS:
                continue
            try:
                stat = entry.stat()
                files.append({
                    'name':  entry.name,
                    'path':  str(entry),
                    'size':  stat.st_size,
                    'mtime': stat.st_mtime,
                    'ext':   entry.suffix.lower().lstrip('.'),
                    'age_sec': _time.time() - stat.st_mtime,
                })
            except OSError:
                continue
    except (PermissionError, OSError) as exc:
        return JsonResponse({
            'ok': False,
            'folder': str(folder),
            'error': f'تعذّر قراءة المجلد: {exc}',
        }, status=500)

    files.sort(key=lambda f: f['mtime'], reverse=True)
    files = files[:20]

    return JsonResponse({
        'ok': True,
        'folder': str(folder),
        'folder_exists': True,
        'count': len(files),
        'files': files,
    })


@login_required
@require_http_methods(['POST'])
def scan_process_local_file(request):
    """
    يعالج ملفاً موجوداً على القرص بمسار محلي (Django والمستخدم على نفس الجهاز).
    يشغّل OCR ويُعيد scan_token لعرض الوثيقة في الواجهة.

    الأمان: يتحقق أن المسار ضمن المجلدات المسموحة (watch_folder + OneDrive Scans).
    """
    import uuid
    import mimetypes
    from django.core.cache import cache

    body       = json.loads(request.body or b'{}')
    file_path  = body.get('path', '').strip()

    if not file_path:
        return JsonResponse({'ok': False, 'error': 'path مطلوب'}, status=400)

    # ─ التحقق من المسار ──────────────────────────────────────────────────────
    ALLOWED_EXTS = {'.pdf', '.jpg', '.jpeg', '.png', '.tif', '.tiff'}
    if not os.path.splitext(file_path)[1].lower() in ALLOWED_EXTS:
        return JsonResponse({'ok': False, 'error': 'نوع الملف غير مدعوم'}, status=400)

    if not os.path.isfile(file_path):
        return JsonResponse({'ok': False, 'error': f'الملف غير موجود: {file_path}'}, status=404)

    # ─ حدود الحجم ────────────────────────────────────────────────────────────
    MAX_BYTES = 50 * 1024 * 1024  # 50 MB
    if os.path.getsize(file_path) > MAX_BYTES:
        return JsonResponse({'ok': False, 'error': 'حجم الملف يتجاوز 50 MB'}, status=400)

    # ─ التحقق من أن المسار ضمن المجلدات المسموحة ────────────────────────────
    import pathlib
    allowed_roots = set()
    cfg = ScanSettings.get()
    if cfg.watch_folder:
        allowed_roots.add(str(pathlib.Path(cfg.watch_folder).resolve()))

    home     = os.path.expanduser('~')
    onedrive = os.environ.get('OneDrive', os.path.join(home, 'OneDrive'))
    for candidate in [
        os.path.join(onedrive, 'Pictures', 'Scans'),
        os.path.join(onedrive, 'Pictures', 'Scan'),
        os.path.join(onedrive, 'Documents', 'Scans'),
        os.path.join(home, 'Pictures', 'Scans'),
        os.path.join(home, 'Pictures', 'Scan'),
        os.path.join(home, 'Documents', 'Scans'),
        os.path.join(home, 'Pictures'),
        os.path.join(home, 'Documents'),
        os.path.join(home, 'Downloads'),
        os.path.join(home, 'Desktop'),
    ]:
        allowed_roots.add(str(pathlib.Path(candidate).resolve()))

    resolved = str(pathlib.Path(file_path).resolve())
    if not any(resolved.startswith(root) for root in allowed_roots):
        logger.warning('[ScanLocal] rejected path outside allowed roots: %s', file_path)
        return JsonResponse({'ok': False, 'error': 'المسار خارج المجلدات المسموحة'}, status=403)

    # ─ تشغيل OCR ─────────────────────────────────────────────────────────────
    logger.info('[ScanLocal] processing local file: %s (user=%s)', file_path, request.user)
    try:
        from core.extraction.pipeline import AIExtractionService
        service = AIExtractionService()
        result  = service.process_image(file_path)
        data = {
            'book_number':               result.book_number,
            'book_number_confidence':    result.book_number_confidence,
            'book_date':                 result.book_date,
            'book_date_confidence':      result.book_date_confidence,
            'title':                     result.title,
            'title_confidence':          result.title_confidence,
            'issuing_entity':            result.issuing_entity_name,
            'issuing_entity_confidence': result.issuing_entity_confidence,
            'receiving_entity':          result.receiving_entity_name,
            'receiving_entity_confidence': result.receiving_entity_confidence,
            'secret_level':              result.secret_level,
            'secret_level_confidence':   result.secret_level_confidence,
            'book_kind':                 result.book_kind,
            'book_kind_confidence':      result.book_kind_confidence,
            'overall_confidence':        result.overall_confidence,
            'needs_review':              result.status == 'manual_review',
            'source_file':               os.path.basename(file_path),
            'processed_path':            resolved,   # الملف لم يُنقل — يُعرض من مكانه
            'user_message':              result.user_message,
        }
    except Exception as exc:
        logger.error('[ScanLocal] OCR failed: %s', exc)
        return JsonResponse({'ok': False, 'error': f'فشل الاستخراج: {exc}'}, status=500)

    # ─ حفظ في الكاش وإعادة token ─────────────────────────────────────────────
    token = uuid.uuid4().hex
    cache.set(f'scan_token:{token}', data, timeout=1800)
    logger.info('[ScanLocal] done, token=%s confidence=%.0f%%', token[:8], (data['overall_confidence'] or 0) * 100)

    return JsonResponse({
        'ok':        True,
        'token':     token,
        'redirect':  f'/books/extract/smart-desktop/?scan_token={token}',
        'source_file': data['source_file'],
        'overall_confidence': data['overall_confidence'],
    })


@login_required
@require_http_methods(['POST'])
def scan_launch_api(request):
    """
    يُطلق CaptureOnTouch ويضبطه عائماً فوق النافذة.
    يُستدعى بـ AJAX من زر "ابدأ المسح" في الواجهة.
    يعمل على Windows فقط عبر سكريبت scan_manager المثبَّت كـ Protocol Handler.
    """
    cfg = ScanSettings.get()
    fix_url = '/books/settings/scan/'

    if not cfg.capture_exe_path:
        return JsonResponse({
            'ok': False,
            'error': 'مسار CaptureOnTouch غير مكوّن في الإعدادات',
            'reason': 'not_configured',
            'fix_url': fix_url,
        }, status=400)

    if not os.path.isfile(cfg.capture_exe_path):
        return JsonResponse({
            'ok': False,
            'error': f'ملف CaptureOnTouch غير موجود: {cfg.capture_exe_path}',
            'reason': 'file_not_found',
            'fix_url': fix_url,
        }, status=400)

    scan_url = (
        f"lettersys-scan://start"
        f"?exe={quote(cfg.capture_exe_path, safe='')}"
        f"&topmost={'1' if cfg.window_topmost else '0'}"
        f"&server={quote(cfg.server_url, safe=':/.')}"
    )
    return JsonResponse({'ok': True, 'scan_url': scan_url})
