# -*- coding: utf-8 -*-
"""
register_scan_protocol.py
==========================
يُسجّل بروتوكول  lettersys-scan://  في Windows Registry.
شغّله مرة واحدة فقط بصلاحيات مسؤول (أو بدونها — يكتب في HKCU).

الاستخدام:
    python register_scan_protocol.py          ← تثبيت
    python register_scan_protocol.py --remove ← إزالة
    python register_scan_protocol.py --check  ← فحص

بعد التثبيت، عندما يفتح المتصفح رابطاً مثل:
    lettersys-scan://start?exe=C:\\...exe&topmost=1
سيستدعي Windows هذا السكريبت تلقائياً.
"""

import sys
import os

# ─── التحقق من Windows ────────────────────────────────────────────
if sys.platform != 'win32':
    print('هذا السكريبت يعمل على Windows فقط.')
    sys.exit(1)

import winreg  # noqa — متوفر في Python/Windows افتراضياً

PROTOCOL      = 'lettersys-scan'
DISPLAY_NAME  = 'LetterSys Scan Protocol'
SCRIPT_PATH   = os.path.abspath(os.path.join(os.path.dirname(__file__), 'scan_manager.py'))
PYTHON_EXE    = os.path.join(os.path.dirname(sys.executable), 'pythonw.exe')

# إذا لم يُوجد pythonw.exe، استخدم python.exe
if not os.path.isfile(PYTHON_EXE):
    PYTHON_EXE = sys.executable

# أمر التشغيل الكامل: "C:\Python\pythonw.exe" "C:\...\scan_manager.py" "%1"
COMMAND = f'"{PYTHON_EXE}" "{SCRIPT_PATH}" "%1"'

REG_ROOT = winreg.HKEY_CURRENT_USER  # لا يحتاج صلاحيات مسؤول
REG_PATH = rf'Software\Classes\{PROTOCOL}'


def install():
    """تسجيل البروتوكول في HKCU."""
    try:
        # المفتاح الجذر
        key = winreg.CreateKey(REG_ROOT, REG_PATH)
        winreg.SetValueEx(key, '', 0, winreg.REG_SZ, f'URL:{DISPLAY_NAME}')
        winreg.SetValueEx(key, 'URL Protocol', 0, winreg.REG_SZ, '')
        winreg.CloseKey(key)

        # DefaultIcon
        icon_key = winreg.CreateKey(REG_ROOT, rf'{REG_PATH}\DefaultIcon')
        winreg.SetValueEx(icon_key, '', 0, winreg.REG_SZ, f'"{PYTHON_EXE}",0')
        winreg.CloseKey(icon_key)

        # shell\open\command
        cmd_key = winreg.CreateKey(REG_ROOT, rf'{REG_PATH}\shell\open\command')
        winreg.SetValueEx(cmd_key, '', 0, winreg.REG_SZ, COMMAND)
        winreg.CloseKey(cmd_key)

        print(f'✓ تم تسجيل البروتوكول بنجاح: {PROTOCOL}://')
        print(f'  المفسّر : {PYTHON_EXE}')
        print(f'  السكريبت: {SCRIPT_PATH}')
        print(f'  الأمر   : {COMMAND}')
    except Exception as exc:
        print(f'✗ فشل التسجيل: {exc}')
        sys.exit(1)


def remove():
    """إزالة البروتوكول من Registry."""
    import shutil
    try:
        winreg.DeleteKey(REG_ROOT, rf'{REG_PATH}\shell\open\command')
        winreg.DeleteKey(REG_ROOT, rf'{REG_PATH}\shell\open')
        winreg.DeleteKey(REG_ROOT, rf'{REG_PATH}\shell')
        winreg.DeleteKey(REG_ROOT, rf'{REG_PATH}\DefaultIcon')
        winreg.DeleteKey(REG_ROOT, REG_PATH)
        print(f'✓ تم حذف البروتوكول: {PROTOCOL}://')
    except FileNotFoundError:
        print('البروتوكول غير مسجّل.')
    except Exception as exc:
        print(f'✗ فشل الحذف: {exc}')
        sys.exit(1)


def check():
    """التحقق من وجود البروتوكول."""
    try:
        key = winreg.OpenKey(REG_ROOT, rf'{REG_PATH}\shell\open\command')
        cmd, _ = winreg.QueryValueEx(key, '')
        winreg.CloseKey(key)
        print(f'✓ البروتوكول مسجّل: {PROTOCOL}://')
        print(f'  الأمر: {cmd}')
        sys.exit(0)
    except FileNotFoundError:
        print(f'✗ البروتوكول غير مسجّل بعد: {PROTOCOL}://')
        sys.exit(1)


if __name__ == '__main__':
    arg = sys.argv[1] if len(sys.argv) > 1 else '--install'
    if arg == '--remove':
        remove()
    elif arg == '--check':
        check()
    else:
        install()
