# -*- coding: utf-8 -*-
"""
Scanner Module - نظام المسح الضوئي
تشغيل Canon CaptureOnTouch وربط الملفات الممسوحة بالكتب

وحدة متخصصة لإدارة عمليات المسح الضوئي:
- تشغيل برنامج Canon CaptureOnTouch
- مراقبة مجلدات الحفظ
- التحقق من صحة الملفات الممسوحة
- دمج PDF مع المرفقات الموجودة
- إنشاء مرفقات جديدة
"""

import glob
import json
import logging
import os
import shutil
import subprocess
import time
from io import BytesIO
from pathlib import Path

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.files import File
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from pypdf import PdfReader, PdfWriter

from ..decorators import rate_limit_scan, reset_scan_rate_limit_for_request
from ..models import Attachment, Book, BookHistory, ScanJob

logger = logging.getLogger(__name__)


# ==============================================================================
# Helper: Validate scanned file before processing
# ==============================================================================

def _detect_magic_mime(file_path):
    """
    التعرّف على نوع الملف الفعلي عبر magic bytes (بدون مكتبات خارجية).
    يعتمد على توقيعات قياسية لـ PDF / JPEG / PNG / TIFF / GIF.

    Returns: 'pdf' | 'jpeg' | 'png' | 'tiff' | 'gif' | None
    """
    try:
        with open(file_path, 'rb') as f:
            head = f.read(12)
    except OSError:
        return None
    if not head:
        return None
    if head.startswith(b'%PDF-'):
        return 'pdf'
    if head.startswith(b'\xff\xd8\xff'):
        return 'jpeg'
    if head.startswith(b'\x89PNG\r\n\x1a\n'):
        return 'png'
    if head.startswith(b'II*\x00') or head.startswith(b'MM\x00*'):
        return 'tiff'
    if head[:6] in (b'GIF87a', b'GIF89a'):
        return 'gif'
    return None


# الامتدادات المسموح بها فقط (قائمة بيضاء صارمة)
_ALLOWED_SCAN_EXTENSIONS = {'.pdf', '.jpg', '.jpeg', '.png', '.tif', '.tiff'}

# توافق الامتداد مع التوقيع الحقيقي
_EXT_TO_MAGIC = {
    '.pdf': {'pdf'},
    '.jpg': {'jpeg'},
    '.jpeg': {'jpeg'},
    '.png': {'png'},
    '.tif': {'tiff'},
    '.tiff': {'tiff'},
}


def _validate_scanned_file(file_path, logger):
    """
    التحقق من صحة الملف الممسوح:
    - الامتداد ضمن قائمة بيضاء صارمة (PDF/JPEG/PNG/TIFF فقط)
    - magic bytes الحقيقية تطابق الامتداد (يمنع .exe المعاد تسميته)
    - حجم الملف معقول
    - ملف PDF: التحقق من البنية الأساسية
    - ملف صورة: التحقق من إمكانية فتحه

    Returns: (is_valid, error_message, file_size)
    """
    try:
        if not os.path.exists(file_path):
            return False, "الملف غير موجود", 0

        file_size = os.path.getsize(file_path)
        if file_size == 0:
            return False, "الملف فارغ (حجم 0 بايت). قد يكون هناك خطأ في عملية المسح", 0
        if file_size < 100:
            return False, f"حجم الملف صغير جداً ({file_size} بايت). قد يكون الملف تالفاً", file_size

        # 🔒 1) قائمة بيضاء للامتدادات
        ext = os.path.splitext(file_path)[1].lower()
        if ext not in _ALLOWED_SCAN_EXTENSIONS:
            logger.error("Rejected scanned file with disallowed extension: %s", file_path)
            return False, f"امتداد الملف غير مسموح: {ext or '(بدون امتداد)'} — المسموح فقط: PDF/JPEG/PNG/TIFF", file_size

        # 🔒 2) فحص magic bytes الحقيقية ومطابقتها للامتداد
        magic_kind = _detect_magic_mime(file_path)
        expected = _EXT_TO_MAGIC.get(ext, set())
        if magic_kind is None:
            logger.error("Rejected scanned file with unknown magic bytes: %s", file_path)
            return False, "تعذّر التعرّف على نوع الملف الفعلي — قد يكون تالفاً أو مزيّفاً", file_size
        if magic_kind not in expected:
            logger.error("Magic/extension mismatch: ext=%s magic=%s file=%s", ext, magic_kind, file_path)
            return False, f"نوع الملف الفعلي ({magic_kind}) لا يطابق الامتداد ({ext}) — مرفوض لأسباب أمنية", file_size

        # PDF validation
        if ext == '.pdf':
            try:
                reader = PdfReader(file_path)
                if len(reader.pages) == 0:
                    return False, "ملف PDF لا يحتوي على أي صفحات", file_size
                logger.info("✅ PDF validation passed: %d bytes, %d pages", file_size, len(reader.pages))
                return True, None, file_size
            except Exception as e:
                return False, f"ملف PDF تالف: {e}", file_size

        # Image validation
        try:
            from PIL import Image
            with Image.open(file_path) as img:
                img.verify()
            logger.info("✅ Image validation passed: %d bytes (%s)", file_size, magic_kind)
            return True, None, file_size
        except ImportError:
            logger.warning("PIL not installed, skipping deep image validation")
            return True, None, file_size
        except Exception as e:
            return False, f"ملف الصورة تالف: {e}", file_size

    except Exception as e:
        logger.error("File validation error: %s", e, exc_info=True)
        return False, f"خطأ في التحقق من الملف: {e}", 0


# ==============================================================================
# Scanner Integration View
# ==============================================================================


def _err(message, message_en, error_code, status, **extra):
    """Build a standardized error JsonResponse."""
    data = {
        "status": "error",
        "message": message,
        "message_en": message_en,
        "error_code": error_code,
    }
    data.update(extra)
    return JsonResponse(data, status=status)


def _to_int(val):
    try:
        return int(val) if val not in (None, "") else None
    except (TypeError, ValueError):
        return None


# ──────────── 1. Parse request & resolve book ────────────

def _parse_scan_request(request):
    """
    Parse POST payload and resolve book + check permissions.
    Returns (book_id, attachment_id, book, error_response).
    error_response is None on success.
    """
    try:
        payload = json.loads(request.body or "{}")
    except (json.JSONDecodeError, ValueError):
        payload = {}

    book_id = _to_int(payload.get("book_id") or request.POST.get("book_id"))
    attachment_id = _to_int(payload.get("attachment_id") or request.POST.get("attachment_id"))

    book = None
    if book_id:
        book = get_object_or_404(Book, id=book_id, is_deleted=False)
        if not (request.user.is_superuser or request.user.is_staff or book.created_by == request.user):
            return book_id, attachment_id, book, _err(
                "غير مصرح لك بالوصول إلى هذا الكتاب",
                "You do not have permission to access this book",
                "PERMISSION_DENIED", 403,
            )

    return book_id, attachment_id, book, None


# ──────────── 2. Scanner config & folders ────────────

def _get_scanner_config():
    """Return a dict of scanner-related settings."""
    return {
        "scan_source": getattr(settings, "SCAN_SOURCE", os.path.join(settings.MEDIA_ROOT, "scan_source")),
        "scan_inbox": getattr(settings, "SCAN_INBOX", os.path.join(settings.MEDIA_ROOT, "scan_inbox")),
        "scanner_exe": getattr(
            settings, "SCAN_EXE",
            r"C:\Program Files (x86)\Canon Electronics\CaptureOnTouch\TouchDR.exe",
        ),
        "simulator_mode": getattr(settings, "SCAN_SIMULATOR_MODE", False),
        "simulator_delay": getattr(settings, "SCAN_SIMULATOR_DELAY", 3),
        # عند True: يُنهى TouchDR.exe بعد كل مسحة ناجحة بدلاً من تصغيره فقط.
        # هذا يُغلق جلسة TWAIN ويمنع خطأ Canon -4400 (Scanner not ready)
        # الذي يحدث عندما ينام الماسح بينما الجلسة لا تزال مفتوحة.
        "terminate_after_scan": getattr(settings, "SCAN_TERMINATE_AFTER_SCAN", True),
    }


def _read_captureontouch_output_paths():
    """
    Read Canon CaptureOnTouch config XMLs to discover all configured save paths.
    Checks both Preset/Output (defaults) and Preset/Job/Output (active job overrides).
    
    Save_Location codes: 0=Documents, 1=Pictures, 2=Custom(Save_Path), 3=Desktop
    
    Returns: list of folder paths discovered from CaptureOnTouch config.
    """
    home = str(Path.home())
    # Map CaptureOnTouch Save_Location codes to actual Windows folders
    location_map = {
        "0": os.path.join(home, "Documents"),
        "1": os.path.join(home, "Pictures"),
        "3": os.path.join(home, "Desktop"),
    }

    discovered = []
    config_dirs = [
        r"C:\ProgramData\Canon Electronics\CaptureOnTouch\Preset\Job\Output",
        r"C:\ProgramData\Canon Electronics\CaptureOnTouch\Preset\Output",
    ]

    for config_dir in config_dirs:
        for xml_path in glob.glob(os.path.join(config_dir, "*.xml")):
            try:
                import xml.etree.ElementTree as ET
                tree = ET.parse(xml_path)
                info = tree.getroot().find(".//OutputInfo")
                if info is None:
                    continue

                save_loc = info.findtext("Save_Location", "").strip()
                save_path = info.findtext("Save_Path", "").strip()

                # Custom path takes priority
                if save_path and os.path.isdir(save_path):
                    discovered.append(save_path)
                    logger.info("[Scanner] CaptureOnTouch custom save path: %s", save_path)
                elif save_loc == "2" and save_path:
                    # Code 2 = custom path, might not exist yet
                    if os.path.isdir(save_path):
                        discovered.append(save_path)
                    elif os.path.isdir(os.path.dirname(save_path)):
                        os.makedirs(save_path, exist_ok=True)
                        discovered.append(save_path)

                # Map known location code
                if save_loc in location_map:
                    folder = location_map[save_loc]
                    if os.path.isdir(folder):
                        discovered.append(folder)
            except Exception as exc:
                logger.debug("Could not parse CaptureOnTouch config %s: %s", xml_path, exc)

    return list(dict.fromkeys(discovered))  # Deduplicate preserving order


def _prepare_scan_folders(cfg):
    """
    Create inbox folder, discover all possible save locations, snapshot them.
    Combines: CaptureOnTouch config paths + project paths + common Windows folders.
    Returns (before_files, accessible, error_response).
    """
    scan_inbox = cfg["scan_inbox"]
    try:
        os.makedirs(scan_inbox, exist_ok=True)
    except OSError:
        return None, None, _err(
            "تعذر إنشاء مجلد الحفظ المؤقت",
            "Failed to create temporary scan folder",
            "FOLDER_CREATION_FAILED", 500,
        )

    home = str(Path.home())

    # 1) Auto-detected from CaptureOnTouch config (highest priority)
    ct_paths = _read_captureontouch_output_paths()

    # 2) Project-configured paths
    project_paths = [cfg["scan_source"], scan_inbox]

    # 3) Common Windows scan/save locations (broad coverage)
    common_paths = [
        os.path.join(home, "Desktop"),
        os.path.join(home, "Documents"),
        os.path.join(home, "Documents", "My Scans"),
        os.path.join(home, "Documents", "Scanned Documents"),
        os.path.join(home, "Pictures"),
        os.path.join(home, "Pictures", "Scans"),
        os.path.join(home, "Downloads"),
        os.path.join(home, "OneDrive", "Documents"),
        os.path.join(home, "OneDrive", "Desktop"),
    ]

    # Merge all, deduplicate
    all_folders = list(dict.fromkeys(ct_paths + project_paths + common_paths))

    before_files = {}
    accessible = []
    for folder in all_folders:
        if folder and os.path.isdir(folder):
            try:
                before_files[folder] = set(os.listdir(folder))
                accessible.append(folder)
            except (PermissionError, OSError) as exc:
                logger.warning("Cannot list folder %s: %s", folder, exc)
                before_files[folder] = set()
        else:
            before_files[folder] = set()

    if not accessible:
        return None, None, _err(
            "لا يمكن الوصول لأي مجلد للحفظ. غيّر مسار الحفظ في CaptureOnTouch أو عدّل الأذونات",
            "No accessible folders to monitor. Change save path in CaptureOnTouch or adjust permissions",
            "NO_ACCESSIBLE_FOLDERS", 500,
        )

    logger.info("[Scanner] Monitoring %d folders (CaptureOnTouch: %d, total: %d)",
                len(accessible), len(ct_paths), len(all_folders))
    return before_files, accessible, None


# ──────────── 3. Acquire scanned file ────────────

def _run_simulator(cfg):
    """
    Simulator mode: create a fake PDF for testing.
    Returns (found_file, found_folder, error_response).
    """
    scan_inbox = cfg["scan_inbox"]
    logger.info("🤖 Simulator mode enabled - creating test file...")
    test_file = os.path.join(scan_inbox, f"test_scan_{int(time.time())}.pdf")
    try:
        with open(test_file, 'wb') as f:
            f.write(b'%PDF-1.4\n%fake test scan file\n%%EOF')
        time.sleep(cfg["simulator_delay"])
        logger.info("✅ Simulator: Created test file: %s", test_file)
        return os.path.basename(test_file), scan_inbox, None
    except Exception as exc:
        logger.error("❌ Simulator mode failed: %s", exc)
        return None, None, _err(
            f"فشل وضع المحاكاة: {exc}",
            f"Simulator mode failed: {exc}",
            "SIMULATOR_FAILED", 500,
        )


def _find_running_scanner():
    """
    Check if CaptureOnTouch is already running.
    Returns process name if found, None otherwise.
    """
    try:
        result = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq TouchDR.exe", "/NH", "/FO", "CSV"],
            capture_output=True, text=True, timeout=5, check=False,
        )
        if "TouchDR.exe" in result.stdout:
            return "TouchDR.exe"
    except Exception:
        pass
    return None


def _bring_scanner_to_front():
    """Bring the CaptureOnTouch window to foreground (best-effort)."""
    try:
        powershell_cmd = '''
$proc = Get-Process | Where-Object {$_.MainWindowTitle -match "Canon|CaptureOnTouch|TouchDR" -or $_.ProcessName -match "TouchDR"} | Select-Object -First 1
if ($proc -and $proc.MainWindowHandle -ne 0) {
    Add-Type @"
using System; using System.Runtime.InteropServices;
public class W32 {
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int c);
    [DllImport("user32.dll")] public static extern bool BringWindowToTop(IntPtr h);
    [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
    [DllImport("user32.dll")] public static extern bool AttachThreadInput(uint idAttach, uint idAttachTo, bool fAttach);
    [DllImport("kernel32.dll")] public static extern uint GetCurrentThreadId();
    [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
    [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, IntPtr lpdwProcessId);
}
"@
    $hwnd = $proc.MainWindowHandle
    # Attach to foreground thread to allow SetForegroundWindow
    $fgHwnd = [W32]::GetForegroundWindow()
    $fgThread = [W32]::GetWindowThreadProcessId($fgHwnd, [IntPtr]::Zero)
    $ourThread = [W32]::GetCurrentThreadId()
    [W32]::AttachThreadInput($ourThread, $fgThread, $true) | Out-Null
    [W32]::ShowWindow($hwnd, 9)  # SW_RESTORE
    [W32]::BringWindowToTop($hwnd)
    [W32]::SetForegroundWindow($hwnd)
    [W32]::AttachThreadInput($ourThread, $fgThread, $false) | Out-Null
}
'''
        subprocess.run(
            ["powershell", "-NoProfile", "-Command", powershell_cmd],
            capture_output=True, timeout=5, check=False,
        )
    except Exception as exc:
        logger.warning("Could not bring scanner window to front: %s", exc)


def _terminate_scanner():
    """
    Terminate CaptureOnTouch process after scan is complete.
    Uses taskkill for a clean shutdown.
    """
    try:
        subprocess.run(
            ["taskkill", "/IM", "TouchDR.exe", "/F"],
            capture_output=True, timeout=5, check=False,
        )
        logger.info("✅ Scanner process terminated after scan completion")
    except Exception as exc:
        logger.warning("Could not terminate scanner process: %s", exc)


def _minimize_scanner_window():
    """
    Minimize CaptureOnTouch window to taskbar after Finish (best-effort).
    تصغير نافذة الماسح إلى شريط المهام بعد اكتمال المسح بدون إنهاء العملية.
    """
    try:
        powershell_cmd = '''
$proc = Get-Process | Where-Object {$_.MainWindowTitle -match "Canon|CaptureOnTouch|TouchDR" -or $_.ProcessName -match "TouchDR"} | Select-Object -First 1
if ($proc -and $proc.MainWindowHandle -ne 0) {
    Add-Type @"
using System; using System.Runtime.InteropServices;
public class W32M { [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int c); }
"@
    [W32M]::ShowWindow($proc.MainWindowHandle, 6) | Out-Null  # SW_MINIMIZE
}
'''
        subprocess.run(
            ["powershell", "-NoProfile", "-Command", powershell_cmd],
            capture_output=True, timeout=3, check=False,
        )
        logger.info("✅ Scanner window minimized to taskbar")
    except Exception as exc:
        logger.warning("Could not minimize scanner window: %s", exc)


def _launch_scanner_exe(scanner_exe):
    """
    Start Canon CaptureOnTouch (or reuse if already running) and bring to foreground.
    Returns error_response or None on success.
    """
    # If already running, just bring to front — don't spawn a duplicate
    if _find_running_scanner():
        logger.info("Scanner already running, bringing to foreground")
        _bring_scanner_to_front()
        return None

    try:
        # Use os.startfile for Windows GUI apps — equivalent to double-clicking
        # This ensures the window appears visible and in foreground
        os.startfile(scanner_exe)
        logger.info("Scanner launched via os.startfile: %s", scanner_exe)
    except FileNotFoundError:
        return _err("لم يتم العثور على برنامج الماسح الضوئي",
                     "Scanner executable not found", "SCANNER_EXE_NOT_FOUND", 500)
    except PermissionError:
        return _err("لا توجد صلاحية لتشغيل برنامج الماسح الضوئي",
                     "Permission denied to execute scanner", "SCANNER_PERMISSION_DENIED", 500)
    except Exception as exc:
        return _err(
            f"خطأ غير متوقع أثناء تشغيل الماسح الضوئي: {exc}",
            f"Unexpected error launching scanner: {exc}",
            "SCANNER_LAUNCH_ERROR", 500,
        )

    # Wait for CaptureOnTouch to fully initialize its window (heavy app)
    # تقليل الإنتظار الأولي والتصعيد الفوري للواجهة
    time.sleep(0.6)
    _bring_scanner_to_front()

    # Bring to foreground with retries (app may take variable time to load)
    for attempt in range(5):
        if _find_running_scanner():
            _bring_scanner_to_front()
            logger.info("Scanner window brought to front (attempt %d)", attempt + 1)
            break
        time.sleep(0.4)
    else:
        # Even if we can't confirm the process, it may still be loading
        _bring_scanner_to_front()

    return None


def _get_scan_timeout():
    """Return scan timeout from settings (default 120s for multi-page docs)."""
    return getattr(settings, "SCAN_TIMEOUT", 120)


def _wait_for_file_ready(file_path, max_wait=10):
    """
    Wait until a file is fully written and unlocked.
    Fast path: stable size for ~0.5s + readable.
    Returns True if file is ready, False on timeout.
    """
    prev_size = -1
    stable_count = 0

    for _ in range(max_wait * 5):  # Check every 0.2s
        try:
            current_size = os.path.getsize(file_path)
            if current_size > 0 and current_size == prev_size:
                stable_count += 1
                if stable_count >= 2:  # مستقر ~0.4s
                    try:
                        with open(file_path, 'rb') as f:
                            f.read(1)
                        return True
                    except (PermissionError, OSError):
                        stable_count = 0  # Still locked, reset
            else:
                stable_count = 0
            prev_size = current_size
        except OSError:
            pass
        time.sleep(0.2)

    return False


def _poll_for_scanned_file(before_files, accessible, timeout=None, poll_interval=0.4):
    """
    Monitor folders for a new file matching supported extensions.
    Uses fast 0.4s polling with robust file-stability check to ensure
    the file is fully written and unlocked before returning.
    Returns (found_file, found_folder, error_response).
    """
    if timeout is None:
        timeout = _get_scan_timeout()

    supported_ext = (".pdf", ".jpg", ".jpeg", ".png", ".tif", ".tiff")
    found_file = None
    found_folder = None

    logger.info("🔍 Monitoring %d folders for scanned files (timeout: %ds)...", len(accessible), timeout)
    start_time = time.time()

    while True:
        elapsed = time.time() - start_time
        if elapsed >= timeout:
            break

        for folder in accessible:
            try:
                current = set(os.listdir(folder))
                new_files = [f for f in current - before_files.get(folder, set())
                             if f.lower().endswith(supported_ext)]
                if new_files:
                    newest = max(new_files, key=lambda fn: os.path.getmtime(os.path.join(folder, fn)))
                    candidate_path = os.path.join(folder, newest)

                    # Robust file-stability check with lock verification
                    if _wait_for_file_ready(candidate_path):
                        found_file = newest
                        found_folder = folder
                        logger.info("✅ Found scanned file: %s in %s (after %.1fs, %d bytes)",
                                    found_file, found_folder, elapsed,
                                    os.path.getsize(candidate_path))
                        break

                before_files[folder] = current
            except (PermissionError, FileNotFoundError, OSError) as exc:
                logger.warning("Issue monitoring %s: %s", folder, exc)
                continue

        if found_file:
            break

        if int(elapsed) % 10 == 0 and elapsed > 1:
            logger.info("⏳ Still waiting for scan... (%.0fs elapsed)", elapsed)

        time.sleep(poll_interval)

    if not found_file:
        logger.error("❌ No scanned file found within timeout. Folders monitored: %s", accessible)
        return None, None, _err(
            f"لم يتم العثور على ملف مسح ضوئي خلال المهلة المحددة ({timeout} ثانية)",
            f"No scanned file found within the timeout period ({timeout} seconds)",
            "SCAN_TIMEOUT", 408,
            timeout_seconds=timeout,
            monitored_folders=accessible,
            troubleshooting={
                "ar": [
                    "تأكد من إكمال عملية المسح في برنامج CaptureOnTouch",
                    "تحقق من مسار الحفظ المحدد في إعدادات البرنامج",
                    "جرب حفظ الملف في أحد المجلدات المراقبة: " + ", ".join(accessible),
                    "تأكد من وجود أذونات الكتابة على المجلد المستهدف"
                ],
                "en": [
                    "Make sure to complete the scan process in CaptureOnTouch",
                    "Check the save path configured in the program settings",
                    f"Try saving to one of the monitored folders: {', '.join(accessible)}",
                    "Ensure write permissions on the target folder"
                ]
            },
        )

    return found_file, found_folder, None


def _get_page_count(file_path):
    """
    Get page count for PDF files. Returns None for non-PDF files.
    """
    if not file_path.lower().endswith('.pdf'):
        return None
    try:
        reader = PdfReader(file_path)
        return len(reader.pages)
    except Exception:
        return None


def _cleanup_source_file(src_path, found_folder, scan_inbox):
    """
    Remove the original scanned file from CaptureOnTouch output folder
    after it has been successfully processed and stored in the system.
    Only deletes if the source is NOT inside scan_inbox (avoid deleting our own copies).
    """
    try:
        src_abs = os.path.abspath(src_path)
        inbox_abs = os.path.abspath(scan_inbox)
        if not src_abs.startswith(inbox_abs) and os.path.isfile(src_path):
            os.remove(src_path)
            logger.info("🧹 Source file cleaned up: %s", src_path)
    except OSError as exc:
        logger.warning("Could not clean up source file %s: %s", src_path, exc)


def _acquire_scanned_file(cfg, before_files, accessible):
    """
    Get a scanned file via simulator or real scanner.
    Terminates CaptureOnTouch after file acquisition to free resources.
    Returns (found_file, found_folder, error_response).
    """
    if cfg["simulator_mode"]:
        return _run_simulator(cfg)

    if not os.path.isfile(cfg["scanner_exe"]):
        return None, None, _err(
            "برنامج Canon CaptureOnTouch غير موجود في المسار المحدد. "
            "🔧 للاختبار بدون البرنامج: اضبط SCAN_SIMULATOR_MODE=True في المتغيرات البيئية",
            "Canon CaptureOnTouch executable not found at the specified path. "
            "🔧 For testing without the program: Set SCAN_SIMULATOR_MODE=True in environment variables",
            "SCANNER_NOT_FOUND", 500,
            expected_path=cfg["scanner_exe"],
            simulator_available=True,
            setup_instructions={
                "ar": "ثبت برنامج Canon CaptureOnTouch أو استخدم وضع المحاكاة",
                "en": "Install Canon CaptureOnTouch or enable simulator mode"
            },
        )

    launch_err = _launch_scanner_exe(cfg["scanner_exe"])
    if launch_err:
        return None, None, launch_err

    found_file, found_folder, poll_err = _poll_for_scanned_file(before_files, accessible)

    # عند العثور على ملف: تصغير النافذة (لا إنهاء) ليبقى السكنر جاهزاً للاستخدام
    # عند المهلة: إنهاء كامل للعملية
    # ملاحظة: إبقاء TouchDR.exe شغّالاً يفتح جلسة TWAIN دائمة، فإذا نام الماسح
    # ترجع برمجية Canon خطأ -4400. لذا نُتيح إنهاء العملية بعد كل مسحة ناجحة
    # عبر إعداد SCAN_TERMINATE_AFTER_SCAN (افتراضياً True).
    if found_file:
        if cfg.get("terminate_after_scan", True):
            _terminate_scanner()
        else:
            _minimize_scanner_window()
    else:
        _terminate_scanner()

    if poll_err:
        return None, None, poll_err

    return found_file, found_folder, None


# ──────────── 4. Process scanned file ────────────

def _validate_and_check_file(found_file, found_folder):
    """
    Verify file still exists and passes validation.
    Returns (src_path, file_size, error_response).
    """
    src_path = os.path.join(found_folder, found_file)
    if not os.path.isfile(src_path):
        return src_path, 0, _err(
            "الملف الممسوح اختفى قبل معالجته",
            "Scanned file disappeared before processing",
            "FILE_DISAPPEARED", 500,
        )

    is_valid, validation_error, file_size = _validate_scanned_file(src_path, logger)
    if not is_valid:
        logger.error("❌ File validation failed: %s (file: %s)", validation_error, src_path)
        return src_path, file_size, _err(
            f"ملف المسح غير صالح: {validation_error}",
            f"Scanned file is invalid: {validation_error}",
            "FILE_VALIDATION_FAILED", 400,
            file_name=found_file, file_size=file_size,
            troubleshooting={
                "ar": [
                    "تأكد من اكتمال عملية المسح الضوئي",
                    "جرب مسح المستند مرة أخرى",
                    "تحقق من إعدادات الماسح الضوئي (الجودة، الدقة)",
                    "تأكد من وضع المستند بشكل صحيح على الماسح"
                ],
                "en": [
                    "Ensure the scan process completed",
                    "Try scanning the document again",
                    "Check scanner settings (quality, resolution)",
                    "Make sure the document is placed correctly on the scanner"
                ]
            },
        )

    logger.info("✅ File validation passed: %s (%d bytes)", found_file, file_size)
    return src_path, file_size, None


def _merge_scan_with_attachment(src_path, found_file, attachment, book, user, request):
    """
    Merge a scanned PDF into an existing PDF attachment.
    Returns JsonResponse.
    """
    from .attachments import _save_attachment_version

    att = attachment
    if not att.file.name.lower().endswith(".pdf"):
        return _err("الدمج متاح فقط لملفات PDF. المرفق الحالي ليس PDF",
                     "Merge is only available for PDF files. Current attachment is not PDF",
                     "NOT_PDF_ATTACHMENT", 400)
    if not found_file.lower().endswith(".pdf"):
        return _err("يجب أن يكون الملف الممسوح بصيغة PDF لدمجه مع المرفق الحالي",
                     "Scanned file must be PDF format for merging",
                     "SCANNED_NOT_PDF", 400)

    try:
        with transaction.atomic():
            existing_reader = PdfReader(att.file)
            new_reader = PdfReader(src_path)
            writer = PdfWriter()
            for page in existing_reader.pages:
                writer.add_page(page)
            for page in new_reader.pages:
                writer.add_page(page)

            backup_page_count = len(existing_reader.pages)
            new_page_count = len(new_reader.pages)
            _save_attachment_version(att, user, note="scan-merge", merge_type="pdf", page_count=backup_page_count)

            buffer = BytesIO()
            writer.write(buffer)
            buffer.seek(0)
            base, ext = os.path.splitext(Path(att.file.name).name)
            merged_name = f"{base}_merged{ext}"
            att.file.save(merged_name, File(buffer), save=True)

            BookHistory.objects.create(
                book=book, action="merge", by=user,
                notes=f"دمج ملف مسح جديد: {found_file} ({new_page_count} صفحات)",
                attachment=att,
            )
    except Exception as exc:
        logger.error("PDF merge failed: %s", exc, exc_info=True)
        return _err(f"فشل دمج ملفات PDF: {exc}", f"PDF merge failed: {exc}", "PDF_MERGE_FAILED", 500)

    # Clean up source file from CaptureOnTouch output folder
    _cleanup_source_file(src_path, os.path.dirname(src_path),
                         getattr(settings, 'SCAN_INBOX', ''))

    total = backup_page_count + new_page_count
    return JsonResponse({
        "status": "success",
        "message": f"تم المسح والدمج بنجاح ({new_page_count} صفحة جديدة، المجموع {total})",
        "message_en": f"Scan and merge completed ({new_page_count} new pages, total {total})",
        "file_name": merged_name,
        "attachment_id": att.id,
        "file_url": request.build_absolute_uri(att.file.url),
        "total_pages": total,
        "new_pages": new_page_count,
        "operation": "merge",
    })


def _attach_scan_to_book(src_path, found_file, book, user, request):
    """
    Create a new Attachment for an existing book from the scanned file.
    Returns JsonResponse.
    """
    try:
        with transaction.atomic():
            att = Attachment(book=book)
            if hasattr(att, "uploaded_by"):
                att.uploaded_by = user
            logger.info("📎 Creating attachment from scan: %s -> book %d", src_path, book.id)
            with open(src_path, "rb") as fh:
                att.file.save(found_file, File(fh), save=True)
            logger.info("✅ Attachment created: ID=%d, file=%s", att.id, att.file.name)
            BookHistory.objects.create(
                book=book, action="attach", by=user,
                notes=f"أضاف مرفق عبر المسح الضوئي: {found_file}", attachment=att,
            )
    except Exception as exc:
        logger.error("❌ Failed to create attachment from scan: %s", exc, exc_info=True)
        return _err(f"فشل إنشاء المرفق: {exc}", f"Failed to create attachment: {exc}",
                     "ATTACHMENT_CREATION_FAILED", 500)

    # Clean up source file from CaptureOnTouch output folder
    _cleanup_source_file(src_path, os.path.dirname(src_path),
                         getattr(settings, 'SCAN_INBOX', ''))

    page_count = _get_page_count(att.file.path) if att.file else None
    file_size = os.path.getsize(att.file.path) if att.file else 0
    msg = "تم المسح الضوئي وإرفاق الملف بنجاح"
    if page_count:
        msg = f"تم المسح الضوئي وإرفاق الملف بنجاح ({page_count} صفحة)"

    logger.info("🎉 Scan completed! Book %d, Attachment %d, pages=%s", book.id, att.id, page_count)
    return JsonResponse({
        "status": "success",
        "message": msg,
        "message_en": f"Scan completed and file attached successfully"
                      + (f" ({page_count} pages)" if page_count else ""),
        "file_name": found_file,
        "attachment_id": att.id,
        "file_url": request.build_absolute_uri(att.file.url),
        "book_id": book.id,
        "page_count": page_count,
        "file_size": file_size,
        "operation": "attach",
    })


def _store_scan_for_new_book(src_path, found_file, scan_inbox, user, request):
    """
    Copy the scanned file to inbox and create a ScanJob for later book creation.
    Returns JsonResponse.
    """
    dest_path = os.path.join(scan_inbox, found_file)
    try:
        if os.path.abspath(src_path) != os.path.abspath(dest_path):
            # Move instead of copy — removes source automatically
            shutil.move(src_path, dest_path)
        # If src==dest, file is already in inbox, no cleanup needed
    except Exception as exc:
        logger.error("Failed to store scanned file for new book: %s", exc, exc_info=True)
        return _err("فشل تحضير الملف لكتاب جديد", "Failed to prepare file for new book",
                     "FILE_PREPARATION_FAILED", 500)

    page_count = _get_page_count(dest_path)
    file_size = os.path.getsize(dest_path) if os.path.isfile(dest_path) else 0

    scan_job = ScanJob.objects.create(
        user=user, status="captured", file_name=found_file, inbox_path=dest_path,
    )
    relative_path = os.path.relpath(dest_path, settings.MEDIA_ROOT).replace("\\", "/")
    file_url = request.build_absolute_uri(settings.MEDIA_URL + relative_path)

    msg = "تم المسح بنجاح. يرجى حفظ الكتاب لربط الملف"
    if page_count:
        msg = f"تم المسح بنجاح ({page_count} صفحة). يرجى حفظ الكتاب لربط الملف"

    logger.info("🎉 Scan completed for new book! File: %s, ScanJob: %d, pages=%s",
                found_file, scan_job.id, page_count)
    return JsonResponse({
        "status": "success",
        "message": msg,
        "message_en": f"Scan completed"
                      + (f" ({page_count} pages)" if page_count else "")
                      + ". Please save the book to attach the file",
        "file_name": found_file,
        "file_url": file_url,
        "temp_file_path": relative_path,
        "page_count": page_count,
        "file_size": file_size,
        "operation": "scan_for_new_book",
        "scan_job_id": scan_job.id,
    })

@login_required
@rate_limit_scan(max_attempts=3, window_seconds=300)
def scan_capture_api(request):
    """
    تشغيل الماسح الضوئي (Canon CaptureOnTouch) وربط الملف الممسوح بكتاب.

    Orchestrates: request parsing → folder setup → file acquisition →
    validation → merge / attach / store-for-new-book.
    """
    if request.method != "POST":
        return _err("طريقة الطلب غير صحيحة. يُسمح فقط بـ POST",
                     "Invalid request method. Only POST is allowed",
                     "INVALID_METHOD", 405)

    # 1. Parse request
    book_id, attachment_id, book, err = _parse_scan_request(request)
    if err:
        return err

    # 2. Scanner config & folder setup
    cfg = _get_scanner_config()
    before_files, accessible, err = _prepare_scan_folders(cfg)
    if err:
        return err

    # 3. Acquire scanned file (simulator or real scanner)
    found_file, found_folder, err = _acquire_scanned_file(cfg, before_files, accessible)
    if err:
        return err

    # 4. Validate the file
    src_path, file_size, err = _validate_and_check_file(found_file, found_folder)
    if err:
        return err

    # 5. Route to the correct processing path
    if attachment_id and book:
        att = Attachment.objects.filter(id=attachment_id, book=book, is_deleted=False).first()
        if not att:
            return _err("المرفق المحدد غير موجود أو محذوف",
                         "Specified attachment not found or deleted",
                         "ATTACHMENT_NOT_FOUND", 404)
        response = _merge_scan_with_attachment(src_path, found_file, att, book, request.user, request)
    elif book:
        response = _attach_scan_to_book(src_path, found_file, book, request.user, request)
    else:
        response = _store_scan_for_new_book(src_path, found_file, cfg["scan_inbox"], request.user, request)

    if getattr(response, 'status_code', 500) < 400:
        reset_scan_rate_limit_for_request(request)

    return response
