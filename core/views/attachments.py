# -*- coding: utf-8 -*-
"""
Attachments Views - معالجات المرفقات
إدارة ملفات المرفقات: حذف، استبدال، دمج صفحات، حذف صفحات
"""

import logging
import mimetypes
import os
from io import BytesIO
from pathlib import Path
from urllib.parse import quote as urlquote

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_http_methods
from django.core.exceptions import SuspiciousOperation, ValidationError
from django.core.files import File
from django.core.files.base import ContentFile
from django.http import (FileResponse, Http404, HttpResponse,
                         HttpResponseForbidden, JsonResponse)
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone
from django.utils._os import safe_join
from django.utils.http import content_disposition_header, url_has_allowed_host_and_scheme
from pypdf import PdfReader, PdfWriter

from ..attachment_service import attachment_write, ensure_pdf, validate_attachment_file
from ..models import Attachment, AttachmentVersion, BookHistory
from core.scoping import can_edit_book, can_open_content, is_privileged

logger = logging.getLogger(__name__)


def _serve_media_file(full_path, rel_path, *, as_attachment=False, download_name=None):
    """يخدم ملفَّ وسائطٍ **بعد أن يكون المتصل قد أذِن** (لا فحصَ صلاحيّةٍ هنا).

    الإنتاج (``USE_X_ACCEL_REDIRECT``): يفوّض البثَّ إلى nginx بترويسة
    X-Accel-Redirect إلى الموقع الداخليّ — فلا يشغل عاملَ gunicorn بالبثّ.
    التطوير/الاختبار: FileResponse من Django (لا nginx أمامه).
    """
    if getattr(settings, 'USE_X_ACCEL_REDIRECT', False):
        prefix = settings.X_ACCEL_MEDIA_PREFIX
        if not prefix.endswith('/'):
            prefix += '/'
        resp = HttpResponse()
        ctype, _enc = mimetypes.guess_type(download_name or rel_path)
        resp['Content-Type'] = ctype or 'application/octet-stream'
        # nginx يفكّ ترميزَ الـURI الداخليّ؛ نرمّز المسار (فراغات/أسماء عربيّة).
        resp['X-Accel-Redirect'] = prefix + urlquote(rel_path.replace('\\', '/'))
        # nginx يحسب Content-Length من الملفّ الداخليّ — لا نتركه صفراً.
        if resp.has_header('Content-Length'):
            del resp['Content-Length']
        if as_attachment and download_name:
            cd = content_disposition_header(True, download_name)
            if cd:
                resp['Content-Disposition'] = cd
        return resp
    return FileResponse(open(full_path, 'rb'), as_attachment=as_attachment,
                        filename=download_name)


def serve_shared_attachment(request, token):
    """يخدم مرفقاً واحداً عبر رابط موقّع محدود المدة — **بلا تسجيل دخول**.

    هذا المسار الوحيد المفتوح على المرفقات، ووجوده ضروري: الجهة الخارجية التي
    نراسلها لا حساب لها في النظام، والملفات الكبيرة لا تُرفَق بالبريد (حدّ ~25MB).

    الحماية: الرمز موقّع بـSECRET_KEY (لا يُزوَّر)، ينتهي بعد مدّة، ويفتح مرفقاً
    واحداً بعينه لا غير. والمرفق المحذوف لا يُخدَم ولو كان الرمز صالحاً.
    """
    from ..attachment_sharing import read_share_token

    attachment_id = read_share_token(token)
    if attachment_id is None:
        raise Http404("رابط التحميل غير صالح أو انتهت صلاحيته.")

    attachment = Attachment.objects.filter(pk=attachment_id).first()
    if attachment is None:
        raise Http404("الملف لم يعد متاحاً.")

    try:
        full_path = attachment.file.path
    except (NotImplementedError, ValueError):
        full_path = None
    if not full_path or not os.path.isfile(full_path):
        logger.warning("serve_shared_attachment: الملف مفقود على القرص — %s", attachment_id)
        raise Http404("الملف غير موجود.")

    logger.info("serve_shared_attachment: served attachment %s", attachment_id)
    # رابطٌ موقَّعٌ يفتحه مَن لا حسابَ له — يُسجَّل بلا مستخدمٍ وبعنوانه
    from core.audit_service import record_event
    record_event(request, 'SHARED_LINK_OPEN', book=attachment.book,
                 metadata={'attachment_id': attachment.pk})

    return _serve_media_file(full_path, attachment.file.name,
                             as_attachment=True, download_name=attachment.filename)


@login_required
def serve_media(request, path):
    """
    خدمة ملفات MEDIA خلف مصادقة (يحلّ محلّ static(MEDIA_URL) المفتوح للجميع).

    - يمنع اجتياز المسار (safe_join).
    - ملفات المرفقات (Attachment/AttachmentVersion) تتطلّب ملكية الكتاب أو staff.
    - أي media أخرى (شعارات…) تُخدَم لأي مستخدم مُصادَق فقط.

    ملاحظة نشر: في الإنتاج يجب توجيه /media/ عبر هذا العرض (أو تكرار الفحص
    على مستوى الويب-سيرفر) — لا تَخدمه مباشرةً دون مصادقة. مع
    ``USE_X_ACCEL_REDIRECT`` يبقى الإذنُ هنا ويتولّى nginx البثَّ (انظر
    docs/DEPLOY_MEDIA.md).
    """
    try:
        full_path = safe_join(settings.MEDIA_ROOT, path)
    except (ValueError, SuspiciousOperation):
        raise Http404("ملف غير موجود")
    if not os.path.isfile(full_path):
        raise Http404("ملف غير موجود")

    # حدّد الكتاب المالك إن كان الملف مرفقاً أو نسخة مرفق
    owner_book = None
    att = Attachment.objects.filter(file=path).select_related("book").first()
    if att is not None:
        owner_book = att.book
    else:
        ver = AttachmentVersion.objects.filter(file=path).select_related("attachment__book").first()
        if ver is not None and ver.attachment_id:
            owner_book = ver.attachment.book

    if owner_book is not None:
        if not can_open_content(owner_book, request.user):
            return HttpResponseForbidden("غير مصرح بالوصول لهذا الملف")

        # **التمييزُ حاسم:** عارضُ المستند يطلب عشرات صور الصفحات لكلّ فتحة،
        # فتسجيلُها خامّاً يعني ثلاثين صفّاً للفتحة الواحدة. العرضُ يُطوى على
        # مستوى الكتاب، والتحميلُ الصريح (`?download=1`) واقعةٌ لا تُطوى.
        from core.audit_service import record_event, record_view
        from core.logging_models import UserActivityLog

        if request.GET.get('download'):
            record_event(request, 'DOWNLOAD_ATTACHMENT', book=owner_book,
                         metadata={'path': path[:200]})
        else:
            record_view(request, owner_book, action=UserActivityLog.VIEW_ATTACHMENT)

    return _serve_media_file(full_path, path,
                             as_attachment=bool(request.GET.get('download')))


def _save_attachment_version(attachment, user, save_file, note="", merge_type="none", page_count=None):
    """
    حفظ نسخة من الملف قبل عمليات التعديل (حذف صفحات، دمج، إلخ)
    
    Args:
        attachment: كائن الملف المرفق
        user: المستخدم الذي قام بالعملية
        note: ملاحظة حول التعديل
        merge_type: نوع الدمج (pdf, image, none)
        page_count: عدد الصفحات بعد التعديل
    
    Returns:
        AttachmentVersion: النسخة المحفوظة؛ الفشل يوقف العملية.
    """
    try:
        last_version = attachment.versions.order_by("-version_number").first()
        next_version = (last_version.version_number + 1) if last_version else 1
        base = Path(attachment.file.name).stem
        ext = Path(attachment.file.name).suffix
        version_name = f"{base}_v{next_version}{ext}"

        with attachment.file.open("rb") as fh:
            version = AttachmentVersion(
                attachment=attachment,
                version_number=next_version,
                created_by=user,
                note=note,
                merge_type=merge_type,
                merged_from_version=last_version,
                file_size=attachment.file.size or 0,
                page_count=page_count,
                is_merged=merge_type != "none",
            )
            save_file(version.file, version_name, File(fh))
            version.save()
        return version
    except Exception as exc:
        logger.warning("Could not save attachment version: %s", exc, exc_info=True)
        raise


def _is_ajax(request):
    return request.headers.get("x-requested-with") == "XMLHttpRequest"


def _mgmt_result(request, book, *, ok=True, message="", status=None, **extra):
    """
    استجابة موحّدة لعمليات إدارة المرفقات:
    - طلب AJAX (لوحة الإدارة في صفحة التعديل) → JSON {success, message, ...}.
    - طلب عادي (توافق رجعي) → رسالة flash ثم توجيه لوجهة آمنة (next) أو تفاصيل الكتاب.
    """
    if _is_ajax(request):
        payload = {"success": ok, "message": message}
        payload.update(extra)
        return JsonResponse(payload, status=status or (200 if ok else 400))
    if message:
        (messages.success if ok else messages.error)(request, message)
    nxt = (request.POST.get("next") or request.GET.get("next") or "").strip()
    if nxt and url_has_allowed_host_and_scheme(
        nxt, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return redirect(nxt)
    return redirect("book_detail", pk=book.pk)


@login_required
def attachment_delete(request, pk):
    """
    نقل مرفق إلى سلة المهملات (حذف ناعم)
    
    Args:
        request: HTTP request (POST)
        pk: معرف المرفق
    
    Returns:
        Redirect to book detail page
    """
    att = get_object_or_404(Attachment, id=pk)
    book = att.book
    
    # تعديلُ ملفّ الكتاب كتابةٌ عليه — للقسم المالك وطاولته والمدير (Q1‑ج)
    if not can_edit_book(book, request.user):
        return _mgmt_result(request, book, ok=False, message="غير مصرح بحذف هذا المرفق.", status=403)

    if request.method != "POST":
        return _mgmt_result(request, book, ok=False, message="طريقة غير مسموحة.", status=405)

    try:
        with attachment_write(att) as (att, save_file):
            _save_attachment_version(att, request.user, save_file, note="Deleted from book_detail")
            att.is_deleted = True
            att.deleted_at = timezone.now()
            att.deleted_by = request.user
            att.save(update_fields=["is_deleted", "deleted_at", "deleted_by"])
            BookHistory.objects.create(
                book=att.book, action='delete-attachment', by=request.user, attachment=att,
                notes=f"Deleted attachment: {att.file.name}",
            )
    except Exception:
        logger.error("Attachment deletion failed", exc_info=True)
        return _mgmt_result(request, book, ok=False, message="فشل حذف المرفق؛ لم تُحفظ العملية.", status=500)

    return _mgmt_result(request, book, ok=True, message="تم نقل المرفق إلى سلة المهملات.", attachment_id=att.id)


@login_required
def attachment_replace(request, pk):
    """
    استبدال ملف مرفق بملف جديد
    
    Args:
        request: HTTP POST request مع ملف جديد
        pk: معرف المرفق
    
    Returns:
        Redirect to book detail page
    """
    att = get_object_or_404(Attachment, id=pk)
    book = att.book
    
    # تعديلُ ملفّ الكتاب كتابةٌ عليه — للقسم المالك وطاولته والمدير (Q1‑ج)
    if not can_edit_book(book, request.user):
        return _mgmt_result(request, book, ok=False, message="غير مصرح باستبدال هذا المرفق.", status=403)

    if not (request.method == "POST" and request.FILES.get("file")):
        return _mgmt_result(request, book, ok=False, message="لم يُرفَع ملف للاستبدال.", status=400)

    new_file = request.FILES["file"]

    # تحقّق موحّد من الحجم والنوع قبل أي حفظ نسخة/كتابة — #12
    try:
        validate_attachment_file(new_file)
    except ValidationError as ve:
        return _mgmt_result(request, book, ok=False, message="؛ ".join(ve.messages), status=400)

    try:
        with attachment_write(att) as (att, save_file):
            _save_attachment_version(att, request.user, save_file, note="Replaced with new file")
            try:
                pdf_bytes, _converted, _orig = ensure_pdf(new_file)
            except ValueError:
                logger.warning("PDF conversion failed during attachment replacement", exc_info=True)
                new_file.seek(0)
                save_file(att.file, new_file.name, new_file)
            else:
                base = Path(new_file.name).stem or "document"
                save_file(att.file, f"{base}.pdf", ContentFile(pdf_bytes))
            att.save(update_fields=["file"])
            BookHistory.objects.create(
                book=book, action="replace-attachment", by=request.user, attachment=att,
                notes=f"Replaced attachment: {new_file.name}",
            )
    except Exception:
        logger.error("Attachment replacement failed", exc_info=True)
        return _mgmt_result(request, book, ok=False, message="فشل استبدال المرفق؛ بقي الأصل محفوظاً.", status=500)

    return _mgmt_result(request, book, ok=True, message="تم استبدال المرفق بنجاح.", attachment_id=att.id)


@login_required
def attachment_merge_pages(request, pk):
    """
    دمج ملفات PDF متعددة في مرفق واحد
    
    المميزات:
    - فحص أن الملف الأساسي PDF
    - دمج عدة ملفات PDF
    - حفظ نسخة من الملف قبل الدمج
    - تسجيل العملية
    
    Args:
        request: HTTP POST request مع ملفات PDF للدمج
        pk: معرف المرفق الأساسي
    
    Returns:
        Redirect to book detail page
    """
    att = get_object_or_404(Attachment, id=pk)
    book = att.book
    
    # تعديلُ ملفّ الكتاب كتابةٌ عليه — للقسم المالك وطاولته والمدير (Q1‑ج)
    if not can_edit_book(book, request.user):
        return _mgmt_result(request, book, ok=False, message="غير مصرح بدمج الملفات.", status=403)

    # التحقق من أن الملف PDF (الموديل لا يملك حقل file_type — نفحص الامتداد)
    if not (att.file and att.file.name.lower().endswith(".pdf")):
        return _mgmt_result(request, book, ok=False, message="يمكن دمج الملفات فقط مع ملفات PDF.", status=400)

    if request.method == "POST" and request.FILES.getlist("merge_files"):
        # تحقّق موحّد من كل ملف دمج (حجم + نوع) قبل أي حفظ — #12
        try:
            for _mf in request.FILES.getlist("merge_files"):
                validate_attachment_file(_mf)
        except ValidationError as ve:
            return _mgmt_result(request, book, ok=False, message="؛ ".join(ve.messages), status=400)
        try:
            with attachment_write(att) as (att, save_file):
                if not att.file.name.lower().endswith(".pdf"):
                    raise ValidationError("يمكن دمج الملفات فقط مع ملفات PDF.")
                _save_attachment_version(
                    att, request.user, save_file, note="Merged with other PDFs", merge_type="pdf")
                with att.file.open("rb") as handle:
                    main_bytes = handle.read()
                writer = PdfWriter()
                main_reader = PdfReader(BytesIO(main_bytes))
                for page in main_reader.pages:
                    writer.add_page(page)
                merge_files = request.FILES.getlist("merge_files")
                for merge_file in merge_files:
                    merge_file.seek(0)
                    merge_reader = PdfReader(merge_file)
                    for page in merge_reader.pages:
                        writer.add_page(page)
                buffer = BytesIO()
                writer.write(buffer)
                writer.close()
                buffer.seek(0)
                save_file(att.file, Path(att.file.name).name, File(buffer))
                att.save(update_fields=["file"])
                BookHistory.objects.create(
                    book=book, action="merge-pages", by=request.user, attachment=att,
                    notes=f"Merged {len(merge_files)} PDFs",
                )
            
            return _mgmt_result(request, book, ok=True, message=f"تم دمج {len(merge_files)} ملفات بنجاح.", attachment_id=att.id)
        except Exception as e:
            logger.error("PDF merge failed: %s", e, exc_info=True)
            return _mgmt_result(request, book, ok=False, message=f"فشل دمج الملفات: {e}", status=500)

    return _mgmt_result(request, book, ok=False, message="لم تُحدَّد ملفات للدمج.", status=400)


@login_required
def attachment_remove_pages(request, pk):
    """
    حذف صفحات محددة من ملف PDF
    
    المميزات:
    - تحديد الصفحات بصيغة: 1,3,5-7 (صفحات فردية ونطاقات)
    - فحص أن الملف PDF
    - حفظ نسخة قبل التحرير
    - تسجيل العملية
    
    Args:
        request: HTTP POST request مع قائمة الصفحات المراد حذفها
        pk: معرف المرفق
    
    Returns:
        Redirect to book detail page
    """
    att = get_object_or_404(Attachment, id=pk)
    book = att.book
    
    # تعديلُ ملفّ الكتاب كتابةٌ عليه — للقسم المالك وطاولته والمدير (Q1‑ج)
    if not can_edit_book(book, request.user):
        return _mgmt_result(request, book, ok=False, message="غير مصرح بحذف الصفحات.", status=403)

    # التحقق من أن الملف PDF (الموديل لا يملك حقل file_type — نفحص الامتداد)
    if not (att.file and att.file.name.lower().endswith(".pdf")):
        return _mgmt_result(request, book, ok=False, message="يمكن حذف الصفحات فقط من ملفات PDF.", status=400)

    if request.method == "POST":
        try:
            pages_to_remove = request.POST.get("pages_to_remove", "")
            if not pages_to_remove.strip():
                return _mgmt_result(request, book, ok=False, message="يرجى تحديد الصفحات المراد حذفها.", status=400)
            
            # تحليل أرقام الصفحات
            page_numbers = []
            for part in pages_to_remove.split(","):
                part = part.strip()
                if "-" in part:
                    start, end = part.split("-")
                    page_numbers.extend(range(int(start.strip())-1, int(end.strip())))
                else:
                    page_numbers.append(int(part)-1)
            
            with attachment_write(att) as (att, save_file):
                if not att.file.name.lower().endswith(".pdf"):
                    raise ValidationError("يمكن حذف الصفحات فقط من ملفات PDF.")
                _save_attachment_version(
                    att, request.user, save_file, note=f"Removed pages: {pages_to_remove}")
                with att.file.open("rb") as handle:
                    pdf_bytes = handle.read()
                reader = PdfReader(BytesIO(pdf_bytes))
                writer = PdfWriter()
                for idx, page in enumerate(reader.pages):
                    if idx not in page_numbers:
                        writer.add_page(page)
                buffer = BytesIO()
                writer.write(buffer)
                writer.close()
                buffer.seek(0)
                save_file(att.file, Path(att.file.name).name, File(buffer))
                att.save(update_fields=["file"])
                BookHistory.objects.create(
                    book=book, action="remove-pages", by=request.user, attachment=att,
                    notes=f"Removed pages: {pages_to_remove}",
                )
            
            return _mgmt_result(request, book, ok=True, message="تم حذف الصفحات بنجاح.", attachment_id=att.id)
        except Exception as e:
            logger.error("Page removal failed: %s", e, exc_info=True)
            return _mgmt_result(request, book, ok=False, message=f"فشل حذف الصفحات: {e}", status=500)

    return _mgmt_result(request, book, ok=False, message="طريقة غير مسموحة.", status=405)

@login_required
@require_http_methods(["GET"])
def attachment_page_image(request, pk, page):
    """صورةُ صفحةٍ من مرفق — لأجل تحديد قصاصة الهامش عليها.

    **بوّابةُ المحتوى هي البوّابة**: الصفحةُ صورةٌ من المستند نفسِه، فمن لا
    يفتح المستندَ لا يرى صفحتَه. و404 لا 403: وجودُ المرفق لا يُسرَّب.
    """
    from core.page_render import render_page

    attachment = get_object_or_404(Attachment, id=pk)
    if not can_open_content(attachment.book, request.user):
        raise Http404

    try:
        path = attachment.file.path
    except (ValueError, AttributeError):
        raise Http404

    data, mimetype = render_page(path, int(page))
    if data is None:
        raise Http404

    response = HttpResponse(data, content_type=mimetype)
    # الصفحةُ لا تتغيّر بعد رفعها — فالكاشُ الخاصّ طويلٌ بلا خطر.
    response['Cache-Control'] = 'private, max-age=86400'
    return response
