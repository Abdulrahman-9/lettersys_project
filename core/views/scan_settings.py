# -*- coding: utf-8 -*-
"""
core.views.scan_settings
=========================
المسح الضوئي عبر وكيل NAPS2 المحلي (التدفّق الوحيد المدعوم).

استُبدل الإعداد القديم بالكامل (CaptureOnTouch + بروتوكول lettersys-scan + مراقب
المجلد): كل حالة الوكيل/الأجهزة تُجلب عميلياً من وكيل المسح المحلي عبر JS، والمسح
يمرّ بـ process-upload (رفع PDF من الوكيل) ثم يُعرض عبر serve/preview بالـtoken.
"""
import logging
import os

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_http_methods

logger = logging.getLogger('lettersys')


def _token_owner_ok(data, user):
    """صاحب رمز المسح فقط (أو superuser) — يسدّ IDOR على الرموز المُسرَّبة.
    الرموز القديمة بلا user_id تُقبل (توافق رجعي)."""
    uid = (data or {}).get('user_id')
    return uid is None or uid == user.id or user.is_superuser


@login_required
def scan_settings_page(request):
    """صفحة حالة الماسح (وكيل NAPS2 المحلي) — الحالة تُجلب عميلياً عبر JS."""
    return render(request, 'core/scan_settings.html', {})


@login_required
@require_http_methods(['GET'])
def scan_file_serve(request, token: str):
    """يخدم ملف المسح المرتبط بـ scan_token للعرض. processed_path من الكاش لا المستخدم."""
    import mimetypes
    from django.http import FileResponse, Http404
    from django.core.cache import cache

    data = cache.get(f'scan_token:{token}')
    if not data:
        logger.warning('[ScanServe] token not in cache: %s', token[:8])
        raise Http404('token expired')
    if not _token_owner_ok(data, request.user):
        raise Http404('token not yours')

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
def scan_preview_page(request, token: str):
    """يعرض صفحةً من PDF الممسوح كصورة PNG (عبر PyMuPDF).

    المستند الممسوح صورة بلا نص؛ تحويله إلى PNG يجعل المعاينة <img> تلائم اللوحة
    دائماً (object-fit) بدل عارض PDF المدمج غير الموثوق. المسار من الكاش لا المستخدم.
    """
    from django.http import HttpResponse, FileResponse, Http404
    from django.core.cache import cache

    data = cache.get(f'scan_token:{token}')
    if not data:
        raise Http404('token expired')
    if not _token_owner_ok(data, request.user):
        raise Http404('token not yours')
    file_path = data.get('processed_path', '')
    if not file_path or not os.path.isfile(file_path):
        raise Http404('file missing')

    # ملف صورة مخزّن بـtoken (لا PDF): أعِده كما هو
    if os.path.splitext(file_path)[1].lower() != '.pdf':
        return FileResponse(open(file_path, 'rb'))

    try:
        page = int(request.GET.get('page', '1'))
    except (TypeError, ValueError):
        page = 1
    try:
        dpi = int(request.GET.get('dpi', '130'))
    except (TypeError, ValueError):
        dpi = 130
    dpi = min(max(dpi, 72), 220)               # سقف صارم لحماية ذاكرة الخادم (8GB)

    try:
        import fitz
        doc = fitz.open(file_path)
        try:
            count = doc.page_count
            if page < 1 or page > count:
                raise Http404('page out of range')
            mat = fitz.Matrix(dpi / 72, dpi / 72)
            pix = doc[page - 1].get_pixmap(matrix=mat, alpha=False)
            # WebP أصغر حجماً وأسرع فكَّ ترميز؛ سقوط إلى PNG إن لم يدعمه إصدار PyMuPDF
            try:
                body, ctype = pix.tobytes('webp'), 'image/webp'
            except Exception:
                body, ctype = pix.tobytes('png'), 'image/png'
            del pix
        finally:
            doc.close()                        # تحرير الذاكرة فوراً
    except Http404:
        raise
    except Exception as exc:
        logger.error('[ScanPreview] render failed token=%s page=%s: %s', token[:8], page, exc)
        raise Http404('render failed')

    resp = HttpResponse(body, content_type=ctype)
    resp['X-Scan-Pages'] = str(count)
    # بلا immutable — نُبقي إمكانية إعادة التحقّق مع تبديل _v بعد تعديل الصفحات
    resp['Cache-Control'] = 'private, max-age=86400'
    return resp


@login_required
@require_http_methods(['GET'])
def scan_manifest(request, token: str):
    """هندسة كل صفحة (عرض/ارتفاع/دوران) لرسم هيكل عظمي بأبعاد صحيحة (صفر قفزة تخطيط).
    لا يرسم بكسلات — رخيص حتى لـ PDF كبير. نفس بوابة الملكية (IDOR) ونفس مصدر المسار."""
    from django.http import Http404
    from django.core.cache import cache

    data = cache.get(f'scan_token:{token}')
    if not data:
        raise Http404('token expired')
    if not _token_owner_ok(data, request.user):
        raise Http404('token not yours')
    file_path = data.get('processed_path', '')
    if not file_path or not os.path.isfile(file_path):
        raise Http404('file missing')

    pages = []
    if os.path.splitext(file_path)[1].lower() == '.pdf':
        try:
            import fitz
            doc = fitz.open(file_path)
            try:
                for i in range(doc.page_count):
                    p = doc[i]
                    r = p.rect
                    pages.append({'n': i + 1, 'w': round(r.width), 'h': round(r.height), 'rot': p.rotation})
            finally:
                doc.close()
        except Exception as exc:
            logger.warning('[ScanManifest] pdf geometry failed token=%s: %s', token[:8], exc)
            pages = []
    else:
        try:
            from PIL import Image
            with Image.open(file_path) as im:
                pages = [{'n': 1, 'w': im.width, 'h': im.height, 'rot': 0}]
        except Exception:
            pages = [{'n': 1, 'w': 827, 'h': 1169, 'rot': 0}]  # A4 افتراضي
    if not pages:
        pages = [{'n': 1, 'w': 827, 'h': 1169, 'rot': 0}]
    return JsonResponse({'ok': True, 'page_count': len(pages), 'pages': pages, 'version': data.get('_v', 0)})


@login_required
@require_http_methods(['POST'])
def scan_edit_page(request, token: str):
    """يعدّل PDF المسح المؤقت **قبل الحفظ**: تدوير/حذف/إعادة ترتيب الصفحات.

    يعمل على الملف المؤقت المرتبط بـ scan_token (المسار من الكاش لا المستخدم،
    اتساقاً مع serve/preview). يحدّث page_count في الكاش ويعيده للواجهة لتعيد الرسم.

    body (JSON):
      {op:'rotate', page:N|'all', angle:90|180|270}
      {op:'delete', page:N}
      {op:'reorder', order:[ترتيب أرقام الصفحات 1-based يغطّي كل الصفحات]}
    """
    import json
    from django.core.cache import cache

    data = cache.get(f'scan_token:{token}')
    if not data:
        return JsonResponse({'ok': False, 'error': 'انتهت صلاحية الجلسة'}, status=404)
    if not _token_owner_ok(data, request.user):
        return JsonResponse({'ok': False, 'error': 'غير مصرح'}, status=403)
    file_path = data.get('processed_path', '')
    if (not file_path or not os.path.isfile(file_path)
            or os.path.splitext(file_path)[1].lower() != '.pdf'):
        return JsonResponse({'ok': False, 'error': 'الملف غير متاح'}, status=404)

    try:
        body = json.loads((request.body or b'{}').decode('utf-8'))
    except (ValueError, UnicodeDecodeError):
        return JsonResponse({'ok': False, 'error': 'طلب غير صالح'}, status=400)
    op = body.get('op')

    try:
        import fitz
        doc = fitz.open(file_path)
        try:
            count = doc.page_count
            inserted_at = None    # (op=insert) موضع أول صفحة مُلحقة (0-based)
            inserted_count = 0

            if op == 'rotate':
                try:
                    angle = int(body.get('angle', 90))
                except (TypeError, ValueError):
                    return JsonResponse({'ok': False, 'error': 'زاوية غير صالحة'}, status=400)
                if angle % 90 != 0:
                    return JsonResponse({'ok': False, 'error': 'الزاوية يجب أن تكون من مضاعفات 90'}, status=400)
                page = body.get('page')
                if page in (None, 'all'):
                    targets = range(count)
                else:
                    try:
                        targets = [int(page) - 1]
                    except (TypeError, ValueError):
                        return JsonResponse({'ok': False, 'error': 'رقم صفحة غير صالح'}, status=400)
                for i in targets:
                    if i < 0 or i >= count:
                        return JsonResponse({'ok': False, 'error': 'رقم صفحة خارج النطاق'}, status=400)
                    doc[i].set_rotation((doc[i].rotation + angle) % 360)

            elif op == 'delete':
                if count <= 1:
                    return JsonResponse({'ok': False, 'error': 'لا يمكن حذف الصفحة الوحيدة'}, status=400)
                try:
                    i = int(body.get('page')) - 1
                except (TypeError, ValueError):
                    return JsonResponse({'ok': False, 'error': 'رقم صفحة غير صالح'}, status=400)
                if i < 0 or i >= count:
                    return JsonResponse({'ok': False, 'error': 'رقم صفحة خارج النطاق'}, status=400)
                doc.delete_page(i)

            elif op == 'reorder':
                order = body.get('order') or []
                try:
                    idx = [int(p) - 1 for p in order]
                except (TypeError, ValueError):
                    return JsonResponse({'ok': False, 'error': 'ترتيب غير صالح'}, status=400)
                if sorted(idx) != list(range(count)):
                    return JsonResponse({'ok': False, 'error': 'الترتيب يجب أن يغطّي كل الصفحات دون حذف'}, status=400)
                doc.select(idx)

            elif op == 'insert':
                # إلحاق/إدراج مستند مصدر (ممسوح أو مرفوع، مُهيَّأ عبر process-upload) في الملف المؤقّت.
                # المصدر يُمرَّر كـ source_token (يعيد استخدام تجهيز process-upload: تحويل صورة→PDF + قصّ فراغات).
                # at اختياري (0-based): None = النهاية (إلحاق مباشر) — وهو الحالة الأشيع.
                src_token = body.get('source_token', '')
                src = cache.get(f'scan_token:{src_token}') if src_token else None
                if not src or not _token_owner_ok(src, request.user):
                    return JsonResponse({'ok': False, 'error': 'مصدر الإلحاق غير متاح أو انتهت صلاحيته'}, status=404)
                src_path = src.get('processed_path', '')
                if (not src_path or not os.path.isfile(src_path)
                        or os.path.splitext(src_path)[1].lower() != '.pdf'):
                    return JsonResponse({'ok': False, 'error': 'مصدر الإلحاق غير صالح'}, status=404)
                at = body.get('at')
                if at is None:
                    inserted_at = count
                else:
                    try:
                        inserted_at = max(0, min(int(at), count))
                    except (TypeError, ValueError):
                        return JsonResponse({'ok': False, 'error': 'موضع إدراج غير صالح'}, status=400)
                try:
                    src_doc = fitz.open(src_path)
                except Exception:
                    return JsonResponse({'ok': False, 'error': 'تعذّر فتح مصدر الإلحاق'}, status=400)
                try:
                    inserted_count = src_doc.page_count
                    if inserted_count == 0:
                        return JsonResponse({'ok': False, 'error': 'مصدر الإلحاق فارغ'}, status=400)
                    doc.insert_pdf(src_doc, start_at=inserted_at)
                finally:
                    src_doc.close()

            else:
                return JsonResponse({'ok': False, 'error': 'عملية غير معروفة'}, status=400)

            out_bytes = doc.tobytes(garbage=3, deflate=True)
            new_count = doc.page_count
        finally:
            doc.close()

        with open(file_path, 'wb') as fh:
            fh.write(out_bytes)
    except Exception as exc:
        logger.error('[ScanEdit] failed token=%s op=%s: %s', token[:8], op, exc)
        return JsonResponse({'ok': False, 'error': 'تعذّر تعديل المستند'}, status=500)

    data['page_count'] = new_count
    cache.set(f'scan_token:{token}', data, timeout=86400)
    logger.info('[ScanEdit] token=%s op=%s pages=%s', token[:8], op, new_count)
    resp = {'ok': True, 'page_count': new_count}
    if op == 'insert':
        resp['inserted_from'] = (inserted_at or 0) + 1   # 1-based: أول صفحة مُلحقة (للتمييز البصري)
        resp['inserted_count'] = inserted_count
    return JsonResponse(resp)


@login_required
@require_http_methods(['GET'])
def scan_stage_attachment(request, attachment_id: int):
    """يُهيّئ مرفقاً محفوظاً لعرضه في معاينة الصفحات (وضع التعديل).

    ينسخ ملف المرفق إلى ملف مسح مؤقت ويعيد token كي تعمل نفس معاينة الصفحات
    (وأدوات التحرير) دون المساس بالأصل المحفوظ. الصلاحيات: مالك الكتاب أو موظف.
    """
    import shutil
    import tempfile
    import uuid
    from pathlib import Path
    from django.core.cache import cache
    from django.shortcuts import get_object_or_404
    from core.models import Attachment

    att = get_object_or_404(Attachment, id=attachment_id, is_deleted=False)
    book = att.book
    if not (request.user.is_superuser or request.user.is_staff or book.created_by == request.user):
        return JsonResponse({'ok': False, 'error': 'غير مصرح'}, status=403)
    if not att.file:
        return JsonResponse({'ok': False, 'error': 'لا يوجد ملف لهذا المرفق'}, status=404)

    scan_dir = Path(tempfile.gettempdir()) / 'lettersys_scan'
    scan_dir.mkdir(parents=True, exist_ok=True)
    ext = os.path.splitext(att.file.name)[1].lower() or '.pdf'
    tmp_path = str(scan_dir / f'scan_{uuid.uuid4().hex}{ext}')
    try:
        with att.file.open('rb') as src, open(tmp_path, 'wb') as dst:
            shutil.copyfileobj(src, dst)
    except Exception as exc:
        logger.error('[ScanStage] copy failed att=%s: %s', attachment_id, exc)
        return JsonResponse({'ok': False, 'error': 'تعذّر تجهيز الملف للعرض'}, status=500)

    page_count = 1
    if ext == '.pdf':
        try:
            import fitz
            with fitz.open(tmp_path) as _doc:
                page_count = _doc.page_count
        except Exception:
            page_count = 1

    token = uuid.uuid4().hex
    cache.set(f'scan_token:{token}', {
        'processed_path': tmp_path,
        'source_file': os.path.basename(att.file.name),
        'page_count': page_count,
        'user_id': request.user.id,
    }, timeout=86400)
    return JsonResponse({
        'ok': True, 'token': token, 'page_count': page_count,
        'source_file': os.path.basename(att.file.name),
    })


# ════════════ وكيل المسح المحلي (NAPS2) ════════════
_AGENT_TOKEN_FILE = os.path.join(
    os.environ.get('LOCALAPPDATA', os.path.expanduser('~')), 'LetterSys', 'agent_token.txt'
)
_AGENT_PORT = int(os.environ.get('LETTERSYS_AGENT_PORT', '17865'))  # نفس متغيّر بيئة الوكيل


def _agent_is_alive(port, timeout=0.35):
    """اختبار حياة الوكيل فعلياً: اتصال socket خاطف بالمنفذ المحلي (رفض الاتصال فوريّ على
    localhost فلا تأخير عند التوقّف). يمنع «available=true» الكاذب من ملف token قديم بقي
    بعد إغلاق الوكيل — فتصير رسالة الواجهة صادقة (شغّل الوكيل) بدل «تعذّر الاتصال رغم تشغيله»."""
    import socket
    try:
        with socket.create_connection(('127.0.0.1', port), timeout=timeout):
            return True
    except OSError:
        return False


@login_required
@require_http_methods(['GET'])
def scan_agent_token(request):
    """يقرأ token وكيل المسح المحلي (نفس الملف الذي يكتبه الوكيل) ويتحقّق من أنه حيّ فعلاً.

    Django والوكيل على نفس الجهاز، فنقرأ الملف مباشرةً + نفحص حياة المنفذ — بلا إعداد يدوي،
    وبلا تضليل عند بقاء ملف token بعد توقّف الوكيل.
    """
    try:
        with open(_AGENT_TOKEN_FILE, 'r', encoding='utf-8') as f:
            token = f.read().strip()
    except OSError:
        token = ''
    alive = bool(token) and _agent_is_alive(_AGENT_PORT)
    return JsonResponse({
        'available': alive,
        'token': token if alive else '',
        'agent_url': f'http://127.0.0.1:{_AGENT_PORT}',
    })


@login_required
@require_http_methods(['POST'])
def scan_process_upload(request):
    """يستقبل مستنداً مرفوعاً (PDF من وكيل المسح، أو PDF/صورة من زر الرفع)،
    يوحّده إلى PDF ويحفظه مؤقتاً ويعيد scan_token. الصور تُحوَّل إلى PDF كي تمرّ
    بنفس مسار المعاينة/التحرير/الحفظ. الاستخراج (OCR) مؤجَّل خلف SCAN_AUTO_OCR."""
    import uuid
    import time as _time
    import tempfile
    from pathlib import Path
    from django.core.cache import cache

    up = request.FILES.get('file')
    if not up:
        return JsonResponse({'ok': False, 'error': 'file مطلوب'}, status=400)
    ext = os.path.splitext(up.name)[1].lower()
    ALLOWED_EXTS = {'.pdf', '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.tif', '.tiff'}
    if ext not in ALLOWED_EXTS:
        return JsonResponse({'ok': False, 'error': 'نوع الملف غير مدعوم (PDF أو صورة)'}, status=400)

    MAX_BYTES = 50 * 1024 * 1024
    if up.size > MAX_BYTES:
        return JsonResponse({'ok': False, 'error': 'حجم الملف يتجاوز 50 MB'}, status=400)

    # مجلد مُدار خارج MEDIA (كي لا يُكشف عبر /media) + تنظيف تلقائي للأقدم من 24 ساعة
    # (= عمر الكاش) — يمنع تسرّب ملفات المسح المؤقتة على القرص.
    scan_dir = Path(tempfile.gettempdir()) / 'lettersys_scan'
    scan_dir.mkdir(parents=True, exist_ok=True)
    cutoff = _time.time() - 86400
    # 'scan_*' (لا 'scan_*.pdf') كي يشمل الكنسُ ملفات stage-attachment غير الـPDF أيضاً
    for old in scan_dir.glob('scan_*'):
        try:
            if old.is_file() and old.stat().st_mtime < cutoff:
                old.unlink()
        except OSError:
            pass

    tmp_path = str(scan_dir / f'scan_{uuid.uuid4().hex}.pdf')
    try:
        if ext == '.pdf':
            with open(tmp_path, 'wb') as out:
                for chunk in up.chunks():
                    out.write(chunk)
            # تحقّق من توقيع PDF الفعلي لا الامتداد فقط (الاسم يضبطه العميل).
            # مواصفة PDF (§7.5.2) تسمح بورود الترويسة ضمن أول 1024 بايت، فقد تسبقها
            # UTF-8 BOM (EF BB BF) أو مسافات — نبحث عنها ضمن المقدّمة تماماً كما يفعل
            # PyMuPDF/القارئات (وإلا رُفض PDF سليم صادرٌ عن أدوات تكتب BOM بادئاً).
            with open(tmp_path, 'rb') as fh:
                head = fh.read(1024)
            if b'%PDF-' not in head:            # الحذف بعد إغلاق المقبض (وإلا WinError 32)
                os.unlink(tmp_path)
                return JsonResponse({'ok': False, 'error': 'الملف ليس PDF صالحاً'}, status=400)
        else:
            # صورة مرفوعة → تُحوَّل إلى PDF لتوحيد المعاينة والتحرير والحفظ
            from core.attachment_service import ensure_pdf_bytes
            try:
                pdf_bytes, _, _ = ensure_pdf_bytes(up.read(), up.name)
            except ValueError:
                return JsonResponse({'ok': False, 'error': 'تعذّر تحويل الصورة إلى PDF'}, status=400)
            with open(tmp_path, 'wb') as out:
                out.write(pdf_bytes)

        from django.conf import settings as dj_settings

        # إزالة الصفحات الفارغة تلقائياً (مسح مزدوج لمستند أحادي → ظهور فارغة تُحذف).
        # يطلبها مسار المسح فقط (trim_blanks=1)، لا الرفع اليدوي. قابلة للتعطيل والضبط
        # عبر الإعدادات، وعتبتها محافِظة جداً كي لا تُحذف صفحات قليلة المحتوى.
        trimmed_pages = 0
        if (request.POST.get('trim_blanks') in ('1', 'true', 'True')
                and getattr(dj_settings, 'SCAN_TRIM_BLANK_PAGES', True)):
            try:
                from core.attachment_service import remove_blank_pages
                max_dark = int(getattr(dj_settings, 'SCAN_BLANK_PAGE_MAX_DARK_PX', 10))
                with open(tmp_path, 'rb') as fh:
                    _orig = fh.read()
                _out, trimmed_pages = remove_blank_pages(_orig, max_dark_px=max_dark)
                if trimmed_pages:
                    with open(tmp_path, 'wb') as out:
                        out.write(_out)
                    logger.info('[ScanUpload] أُزيلت %d صفحة فارغة تلقائياً', trimmed_pages)
            except Exception as exc:
                logger.warning('[ScanUpload] تخطّي إزالة الفراغات: %s', exc)
        # الاستخراج التلقائي (OCR) مؤجَّل افتراضياً: محرّك EasyOCR ثقيل وقد يتعطّل أصلياً
        # على الأجهزة محدودة الذاكرة. حتى يجهز عامل OCR المقيم، نلتقط المستند ونترك
        # الإدخال يدوياً. يُعاد تفعيله بضبط SCAN_AUTO_OCR=True.
        if getattr(dj_settings, 'SCAN_AUTO_OCR', False):
            # Tesseract يعمل كبرنامج خارجي (لا segfault) فنشغّله داخل العملية: أسرع
            # بكثير (بلا إعادة إقلاع Django ~5-11ث). EasyOCR/PyTorch يحتاج عزل عملية فرعية.
            if getattr(dj_settings, 'AI_OFFLINE_ENGINE', 'tesseract') == 'tesseract':
                from core.extraction.pipeline import run_ocr_inprocess
                data = run_ocr_inprocess(tmp_path)
            else:
                from core.extraction.pipeline import run_ocr_isolated
                data = run_ocr_isolated(tmp_path)  # OCR معزول (segfault لا يُسقط الخادم)
            # فشل OCR لا يُهدر المسح: نحتفظ بالـPDF ونتابع لإدخال يدوي.
            if data.get('_error'):
                logger.warning('[ScanUpload] فشل OCR — نتابع لإدخال يدوي: %s', data['_error'])
                data['needs_review'] = True
                warning = 'تعذّر استخراج النص تلقائياً — حُفِظ المستند الممسوح، يُرجى إدخال البيانات يدوياً.'
            else:
                warning = ''
        else:
            data = {'needs_review': True}
            warning = 'حُفِظ المستند الممسوح — أدخل البيانات يدوياً (الاستخراج التلقائي مؤجَّل حالياً).'

        source_name = (request.POST.get('source_name') or up.name or 'scan.pdf').strip()
        data['source_file'] = os.path.basename(source_name)
        data['processed_path'] = tmp_path          # scan_file_serve يخدمه من هنا (عبر عرض مُصادَق لا /media)
        data['user_id'] = request.user.id          # ربط الرمز بصاحبه (يسدّ IDOR)

        # عدد الصفحات (لمعاينة متعددة الصفحات في duplex) — best-effort
        try:
            import fitz
            with fitz.open(tmp_path) as _doc:
                data['page_count'] = _doc.page_count
                # حارس المسح الفارغ (مبدأ المالك: صفر حقول ≠ نجاح): صفحاتٌ بيضاء
                # ناصعة (تباين شبه معدوم) = وجه ورقة خاطئ/تغذية فارغة — نُصارح فوراً
                # بدل استخراجٍ صامتٍ فارغ يُحسَب انتكاساً. فحصٌ رخيص (72dpi رمادي).
                import numpy as _np
                _all_blank = True
                for _i in range(_doc.page_count):
                    _pix = _doc[_i].get_pixmap(dpi=72, colorspace=fitz.csGRAY, alpha=False)
                    _arr = _np.frombuffer(_pix.samples, dtype=_np.uint8)
                    if _arr.std() >= 4:            # أيّ حبرٍ حقيقي يرفع التباين فوق هذا
                        _all_blank = False
                        break
                if _all_blank:
                    data['needs_review'] = True
                    data['blank_scan'] = True
                    warning = ('⚠ المسح فارغ — الصفحات بيضاء بلا محتوى. '
                               'تحقّق من وجه الورقة واتجاه التغذية ثم أعد المسح.')
        except Exception:
            data['page_count'] = 1

        token = uuid.uuid4().hex
        cache.set(f'scan_token:{token}', data, timeout=86400)
        logger.info('[ScanUpload] done token=%s user=%s conf=%.0f%% pages=%s auto_ocr=%s',
                    token[:8], request.user,
                    (data.get('overall_confidence') or 0) * 100, data['page_count'],
                    getattr(dj_settings, 'SCAN_AUTO_OCR', False))
        return JsonResponse({
            'ok': True,
            'token': token,
            'redirect': f'/books/extract/smart-desktop/?scan_token={token}',
            'source_file': data['source_file'],
            'overall_confidence': data.get('overall_confidence'),
            'page_count': data.get('page_count', 1),
            'trimmed_pages': trimmed_pages,
            'warning': warning,
        })
    except Exception as exc:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        logger.error('[ScanUpload] failed: %s', exc)
        return JsonResponse({'ok': False, 'error': str(exc)}, status=500)
