# -*- coding: utf-8 -*-
"""
scan_manager.py
===============
سكريبت Windows يُنفَّذ عند الضغط على زر "ابدأ المسح" في المتصفح.
مُسجَّل كـ Protocol Handler لـ lettersys-scan://

ما يفعله:
  1. يُشغّل CaptureOnTouch.exe
  2. ينتظر ظهور نافذته ثم يجعلها عائمة فوق المتصفح (HWND_TOPMOST)
  3. يراقب العملية — عندما ينتهي المستخدم ويضغط Finish:
     a. يُغلق أو يُصغّر نافذة CaptureOnTouch
     b. يُعيد المتصفح للأمام (SetForegroundWindow)
  4. Hot Folder Watcher (يعمل في الخلفية) يكتشف الملف الجديد
     ويفتح صفحة الاستخراج تلقائياً

الاستخدام:
    pythonw scan_manager.py "lettersys-scan://start?exe=C:\\...exe&topmost=1&server=http://localhost:8000"

متطلبات Windows:
    pip install pywin32   (أو استخدام ctypes المدمج — لا تثبيت إضافي)
"""

import sys
import os
import time
import subprocess
import ctypes
import ctypes.wintypes
import urllib.parse
import logging

# ─── Logging خفيف (يكتب في AppData\Roaming\LetterSys\scan_manager.log) ────────
_log_dir = os.path.join(os.environ.get('APPDATA', os.path.expanduser('~')), 'LetterSys')
os.makedirs(_log_dir, exist_ok=True)
logging.basicConfig(
    filename=os.path.join(_log_dir, 'scan_manager.log'),
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s',
    encoding='utf-8',
)
log = logging.getLogger('scan_manager')

# ─── Win32 API عبر ctypes (بدون pywin32) ─────────────────────────────────────
user32   = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

HWND_TOPMOST    = -1
HWND_NOTOPMOST  = -2
SWP_NOMOVE      = 0x0002
SWP_NOSIZE      = 0x0001
SWP_NOACTIVATE  = 0x0010
SW_RESTORE      = 9
SW_MINIMIZE     = 6
GW_OWNER        = 4
WM_CLOSE        = 0x0010
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

# أسماء عمليات المتصفحات المعروفة — تُستخدم لتصفية النوافذ بدقّة
# (يمنع التقاط محرّرات النصوص مثل VS Code/Notepad++ التي قد يحوي عنوانها اسم المشروع)
_BROWSER_EXES = {
    'chrome.exe', 'msedge.exe', 'firefox.exe',
    'brave.exe', 'opera.exe', 'vivaldi.exe',
    'iexplore.exe',
}

EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)


def _get_window_title(hwnd) -> str:
    buf = ctypes.create_unicode_buffer(512)
    user32.GetWindowTextW(hwnd, buf, 512)
    return buf.value


def _get_window_process_exe(hwnd) -> str:
    """يُعيد basename للـexe المالك للنافذة (مثال: 'chrome.exe') أو '' عند الفشل."""
    try:
        pid = ctypes.wintypes.DWORD(0)
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if not pid.value:
            return ''
        h_proc = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
        if not h_proc:
            return ''
        try:
            buf = ctypes.create_unicode_buffer(512)
            size = ctypes.wintypes.DWORD(512)
            if kernel32.QueryFullProcessImageNameW(h_proc, 0, buf, ctypes.byref(size)):
                return os.path.basename(buf.value).lower()
        finally:
            kernel32.CloseHandle(h_proc)
    except Exception:
        pass
    return ''


def find_windows_by_partial_title(partial: str, browser_only: bool = False) -> list:
    """
    العثور على نوافذ مرئية تحتوي على نص معيّن في عنوانها.
    browser_only=True يُصفّي النتائج لتشمل فقط نوافذ متصفّحات حقيقية
    (chrome/edge/firefox/...) — يمنع التقاط VS Code أو محرّرات أخرى.
    """
    result = []

    def callback(hwnd, _):
        if not user32.IsWindowVisible(hwnd):
            return True
        if partial.lower() not in _get_window_title(hwnd).lower():
            return True
        if browser_only and _get_window_process_exe(hwnd) not in _BROWSER_EXES:
            return True
        result.append(hwnd)
        return True

    user32.EnumWindows(EnumWindowsProc(callback), 0)
    return result


def set_topmost(hwnd, topmost: bool = True) -> None:
    flag = HWND_TOPMOST if topmost else HWND_NOTOPMOST
    user32.SetWindowPos(hwnd, flag, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)


def bring_browser_to_front() -> None:
    """
    يُعيد نافذة المتصفح التي تعرض LetterSys إلى الأمام.
    يُصفّي حسب اسم عملية المتصفح فعليّاً (chrome/msedge/firefox/...) لتفادي
    استدعاء محرّرات النصوص (VS Code/Notepad++) عندما يحوي عنوانها اسم المشروع.
    """
    # كلمات مفتاحية مخصّصة (لها أولوية إن طابقت نافذة متصفّح فعلية)
    specific = ['localhost:8000', 'نظام الكتب']
    # ثم أي نافذة لمتصفّح معروف
    generic  = [' - ', '']  # أي عنوان لمتصفّح

    for kw in specific:
        hwnds = find_windows_by_partial_title(kw, browser_only=True)
        if hwnds:
            hwnd = hwnds[0]
            user32.ShowWindow(hwnd, SW_RESTORE)
            user32.SetForegroundWindow(hwnd)
            log.info('Brought browser to front: hwnd=%s title="%s"', hwnd, _get_window_title(hwnd))
            return

    # Fallback: ابحث عن أي نافذة لمتصفّح معروف (بدون تقييد عنوان)
    for kw in generic:
        hwnds = find_windows_by_partial_title(kw, browser_only=True)
        if hwnds:
            hwnd = hwnds[0]
            user32.ShowWindow(hwnd, SW_RESTORE)
            user32.SetForegroundWindow(hwnd)
            log.info('Brought browser to front (fallback): hwnd=%s title="%s"',
                     hwnd, _get_window_title(hwnd))
            return

    log.warning('Could not find browser window to bring to front')


def wait_for_window(title_partial: str, timeout: float = 15.0) -> int:
    """
    ينتظر ظهور نافذة جديدة تحتوي على النص المطلوب.
    يُعيد HWND أو 0 إذا انتهت المهلة.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        hwnds = find_windows_by_partial_title(title_partial)
        if hwnds:
            return hwnds[0]
        time.sleep(0.5)
    return 0


def parse_scan_url(url: str) -> dict:
    """تحليل رابط lettersys-scan://start?exe=...&topmost=1&server=..."""
    parsed = urllib.parse.urlparse(url)
    params = urllib.parse.parse_qs(parsed.query)
    return {
        'exe':      params.get('exe',      [''])[0],
        'topmost':  params.get('topmost',  ['1'])[0] == '1',
        'server':   params.get('server',   ['http://localhost:8000'])[0],
    }


def main():
    if len(sys.argv) < 2:
        log.error('No URL argument provided')
        sys.exit(1)

    raw_url = sys.argv[1]
    log.info('scan_manager started: %s', raw_url)

    params   = parse_scan_url(raw_url)
    exe_path = params['exe']
    topmost  = params['topmost']
    server   = params['server'].rstrip('/')

    if not exe_path or not os.path.isfile(exe_path):
        log.error('CaptureOnTouch not found: %s', exe_path)
        settings_url = f"{server}/books/settings/scan/"
        try:
            import webbrowser
            webbrowser.open(settings_url)
        except Exception:
            pass
        ctypes.windll.user32.MessageBoxW(
            0,
            f'مسار CaptureOnTouch غير صحيح:\n{exe_path}\n\nتم فتح صفحة إعدادات الماسح في المتصفح.\n{settings_url}',
            'LetterSys — خطأ',
            0x10,  # MB_ICONERROR
        )
        sys.exit(1)

    # ─── 1. تشغيل CaptureOnTouch ────────────────────────────────────
    log.info('Launching: %s', exe_path)
    try:
        proc = subprocess.Popen([exe_path], cwd=os.path.dirname(exe_path))
    except Exception as exc:
        log.error('Failed to launch: %s', exc)
        sys.exit(1)

    # ─── 2. انتظار نافذة CaptureOnTouch ────────────────────────────
    capture_titles = ['CaptureOnTouch', 'كابجر اون تاج', 'Canon']
    capture_hwnd = 0
    for title_kw in capture_titles:
        capture_hwnd = wait_for_window(title_kw, timeout=15)
        if capture_hwnd:
            log.info('Found window: hwnd=%s title="%s"', capture_hwnd, _get_window_title(capture_hwnd))
            break

    if not capture_hwnd:
        log.warning('CaptureOnTouch window not found within timeout; continuing anyway')

    # ─── 3. جعل النافذة عائمة فوق المتصفح ─────────────────────────
    if capture_hwnd and topmost:
        set_topmost(capture_hwnd, True)
        log.info('Set CaptureOnTouch as TOPMOST')

    # ─── 4. مراقبة حتى ينتهي المستخدم من المسح ────────────────────
    # ملاحظة مهمّة: بعض launchers (مثل TouchDR.exe من Canon) تنفصل عن العملية
    # الرئيسية فوراً بعد إطلاقها (proc.poll() != None خلال أجزاء ثانية) لكن
    # نافذة المسح تبقى مفتوحة عبر child process مستقل. لذا نعتمد فقط على
    # رؤية النافذة لا على حياة الـlauncher process — وإلا سنخرج مبكراً
    # ونستدعي bring_browser_to_front أثناء عمل المستخدم على المسح.
    log.info('Waiting for CaptureOnTouch window to close...')
    launcher_exited = False
    while True:
        # سجّل خروج الـlauncher مرّةً واحدة (للتشخيص فقط — لا نكسر)
        if not launcher_exited and proc.poll() is not None:
            launcher_exited = True
            log.info('Launcher process exited (code=%s) — continuing to monitor window',
                     proc.returncode)

        # افحص جميع نوافذ CaptureOnTouch المحتملة (قد تفتح نافذة مختلفة عند الحفظ)
        any_open = any(find_windows_by_partial_title(kw) for kw in capture_titles)
        if not any_open:
            log.info('All CaptureOnTouch windows closed')
            break

        time.sleep(0.8)

    # ─── 5. إزالة TOPMOST وإعادة المتصفح للأمام ────────────────────
    time.sleep(1.0)  # انتظر قليلاً حتى يُكمل CaptureOnTouch الحفظ

    if capture_hwnd:
        set_topmost(capture_hwnd, False)

    # أعد المتصفح للأمام — الـ Hot Folder Watcher سيفتح tab الاستخراج قريباً
    bring_browser_to_front()

    log.info('scan_manager finished successfully')


if __name__ == '__main__':
    main()
