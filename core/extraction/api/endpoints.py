# -*- coding: utf-8 -*-
"""
core.extraction.api.endpoints
===============================
REST API endpoints for AI extraction operations.

Routes (all mounted under /books/ or /api/ in core/urls.py):
  POST /api/extract/              → start_extraction
  GET  /api/extract/<id>/         → get_extraction_result
  POST /api/extract/<id>/feedback/ → submit_feedback
  POST /api/extract/<id>/review/  → review_extraction
  GET  /api/extract/statistics/   → extraction_statistics
  POST /api/extract/smart/        → smart_extract_direct
  GET  /api/suggestions/          → suggestions_api
"""
import logging
import os
import tempfile
from pathlib import Path
import uuid
from django.conf import settings
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse, StreamingHttpResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_http_methods
from django.utils import timezone
from django.utils.dateparse import parse_date

from core.tasks import process_attachment_extraction
from core.extraction.pipeline import AIExtractionService, slim_entity_matches
from core.decorators import rate_limit_scan, rate_limit
from core.models import (
    Attachment,
    DataExtractionResult,
    ExtractionFeedback,
    SuggestionCategory,
    SuggestionItem,
    ExtractionStatistics,
)
from core.extraction.kinds import BOOK_KIND_LABELS, DEFAULT_BOOK_KIND, get_kind_label, normalize_book_kind
logger = logging.getLogger(__name__)


def _request_id():
    return uuid.uuid4().hex[:8]


def _api_response(success, message, *, status_code=200, error_code=None, details=None):
    payload = {
        'success': success,
        'message': message,
        'request_id': _request_id(),
    }
    if error_code:
        payload['error_code'] = error_code
    if details:
        payload['details'] = details
    return Response(payload, status=status_code)


def _fallback_suggestions(category_key: str):
    defaults = {
        'issuing_entity': [
            'وزارة الداخلية', 'وزارة العدل', 'وزارة التربية', 'وزارة الصحة', 'وزارة الخارجية'
        ],
        'receiving_entity': [
            'قسم المتابعة', 'قسم الأرشيف', 'قسم الإدارة', 'قسم التدقيق', 'قسم المستندات'
        ],
        'secret_level': ['اعتيادي', 'سري', 'سري للغاية'],
        'book_kind': list(BOOK_KIND_LABELS.keys()),
    }
    return defaults.get(category_key, [])


@api_view(['POST'])
@permission_classes([IsAuthenticated])
@rate_limit('extract_start', max_attempts=15, window_seconds=300, by='user')
def start_extraction(request):
    """Kick off AI extraction for an existing attachment (async via Celery)."""
    attachment_id = request.data.get('attachment_id')
    if not attachment_id:
        return Response({'detail': 'attachment_id is required'}, status=status.HTTP_400_BAD_REQUEST)

    try:
        attachment = Attachment.objects.get(id=attachment_id)
    except Attachment.DoesNotExist:
        return Response({'detail': 'Attachment not found'}, status=status.HTTP_404_NOT_FOUND)

    try:
        async_result = process_attachment_extraction.delay(attachment.id)
        task_id = async_result.id
    except Exception:
        # في بيئات الاختبار/التطوير بدون وسيط رسائل متاح
        task_id = 'dev-null'
    return Response({'task_id': task_id, 'attachment_id': attachment.id}, status=status.HTTP_202_ACCEPTED)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_extraction_result(request, attachment_id: int):
    """Get the latest extraction result for an attachment."""
    attachment = get_object_or_404(Attachment, id=attachment_id)
    extraction = getattr(attachment, 'data_extraction', None)

    if not extraction:
        return Response({'status': 'pending', 'detail': 'No extraction found'}, status=status.HTTP_404_NOT_FOUND)

    payload = {
        'extraction_id': extraction.id,
        'attachment_id': attachment.id,
        'status': extraction.status,
        'book_number': extraction.book_number,
        'book_number_confidence': extraction.book_number_confidence,
        'book_date': extraction.book_date,
        'book_date_confidence': extraction.book_date_confidence,
        'title': extraction.title,
        'title_confidence': extraction.title_confidence,
        'margin_text': extraction.margin_text,
        'margin_confidence': extraction.margin_confidence,
        'secret_level': extraction.secret_level,
        'secret_level_confidence': extraction.secret_level_confidence,
        'book_kind': normalize_book_kind(extraction.book_kind, default=None) or '',
        'book_kind_label': get_kind_label(extraction.book_kind) if extraction.book_kind else '',
        'book_kind_confidence': extraction.book_kind_confidence,
        'issuing_entity_candidates': extraction.issuing_entity_candidates,
        'receiving_entity_candidates': extraction.receiving_entity_candidates,
        'overall_confidence': extraction.overall_confidence,
        'additional_data': extraction.additional_data,
        'created_at': extraction.created_at,
    }
    return Response(payload, status=status.HTTP_200_OK)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def submit_feedback(request, extraction_id: int):
    """Store user feedback for learning/QA."""
    extraction = get_object_or_404(DataExtractionResult, id=extraction_id)
    field_name = request.data.get('field_name')
    feedback_type = request.data.get('feedback_type')
    original_value = request.data.get('original_value', '')
    corrected_value = request.data.get('corrected_value', '')
    reason = request.data.get('reason', request.data.get('notes', ''))

    if not field_name or not feedback_type:
        return Response({'detail': 'field_name and feedback_type are required'}, status=status.HTTP_400_BAD_REQUEST)

    feedback = ExtractionFeedback.objects.create(
        extraction=extraction,
        field_name=field_name,
        feedback_type=feedback_type,
        original_value=original_value,
        corrected_value=corrected_value,
        reason=reason,
        created_by=request.user,
    )

    return Response({'id': feedback.id, 'detail': 'feedback saved'}, status=status.HTTP_201_CREATED)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def review_extraction(request, extraction_id: int):
    """Approve or reject an extraction and optionally apply corrected fields."""
    extraction = get_object_or_404(DataExtractionResult, id=extraction_id)
    action = request.data.get('action')
    if action not in ['approve', 'reject']:
        return Response({'detail': 'action must be approve or reject'}, status=status.HTTP_400_BAD_REQUEST)

    fields = request.data.get('fields', {}) or {}
    notes = request.data.get('notes', '')
    now = timezone.now()
    previous_status = extraction.status

    # Apply user corrections when provided
    allowed_fields = {
        'book_number', 'title', 'secret_level', 'book_kind', 'margin_text',
        'issuing_entity_id', 'receiving_entity_id', 'book_date'
    }
    for key, value in fields.items():
        if key not in allowed_fields:
            continue
        if key == 'book_date' and value:
            parsed = parse_date(value)
            setattr(extraction, key, parsed)
        elif key == 'book_kind':
            setattr(extraction, key, normalize_book_kind(value, DEFAULT_BOOK_KIND) if value else '')
        else:
            setattr(extraction, key, value)

    extraction.reviewed_by = request.user
    extraction.reviewed_at = now

    if action == 'approve':
        extraction.status = 'approved'
        extraction.approved_by = request.user
        extraction.approved_at = now
        feedback_type = 'correct'
    else:
        extraction.status = 'rejected'
        feedback_type = 'incorrect'

    if notes:
        extraction.notes = notes

    extraction.save()

    ExtractionFeedback.objects.create(
        extraction=extraction,
        field_name='__overall__',
        feedback_type=feedback_type,
        original_value=previous_status,
        corrected_value=extraction.status,
        reason=notes,
        created_by=request.user,
    )

    return Response(
        {
            'status': extraction.status,
            'reviewed_by': request.user.username,
            'reviewed_at': extraction.reviewed_at,
            'approved_by': extraction.approved_by.username if extraction.approved_by else None,
            'approved_at': extraction.approved_at,
        },
        status=status.HTTP_200_OK,
    )


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def extraction_statistics(request):
    """Return recent extraction statistics (7-day window)."""
    from datetime import timedelta

    # Query latest statistics from database directly
    start_date = timezone.now() - timedelta(days=7)
    stats = ExtractionStatistics.objects.filter(
        date__gte=start_date.date()
    ).order_by('-date')

    if not stats:
        return Response({'detail': 'no statistics yet'}, status=status.HTTP_200_OK)

    latest = stats.first()
    return Response({
        'total_images_processed': latest.total_images_processed,
        'successful_extractions': latest.successful_extractions,
        'failed_extractions': latest.failed_extractions,
        'manual_review_required': latest.manual_review_required,
        'average_confidence': latest.average_confidence,
        'average_processing_time': latest.average_processing_time,
        'min_processing_time': latest.min_processing_time,
        'max_processing_time': latest.max_processing_time,
        'field_stats': latest.field_stats,
        'date': latest.date.isoformat(),
    }, status=status.HTTP_200_OK)


def _mint_scan_token(result) -> str:
    """يسكّ رمز مسحٍ لأيّ استخراج (رفعٌ يدويّ أو بثّ) ويخزّن اقتراحه في الكاش.

    **إصلاح حلقة التعلّم (2026-08-16، تشخيصٌ على الكتاب 11298):** كانت الحلقة تُنشئ
    الرمز في مسار **وكيل المسح وحده** (`scan_settings`)، فكلُّ مستندٍ يُرفع يدوياً لا
    يُنتج رمزاً ⟵ `books_api` يتخطّى `persist_extraction_capture` ⟵ **تصحيحُ الكاتب
    يضيع**. الدليل: 6 سجلّات التقاطٍ في القاعدة كلّها (و0 لهذا الكتاب) مقابل آلاف
    الحفظات. المخزَّن هو `result_to_scan_data` نفسه لأن الالتقاط يقرأ منه raw_text
    والحقول والثقات وصندوق العدد. يُعاد الرمز في الاستجابة لترسله الواجهة عند الحفظ."""
    try:
        import uuid

        from django.core.cache import cache as _cache

        from core.extraction.pipeline import result_to_scan_data
        token = uuid.uuid4().hex
        payload = result_to_scan_data(result)
        _cache.set(f'scan_token:{token}', payload, timeout=86400)
        # **ونسخةٌ دائمة**: الكاش مسارُ السرعة وهذا مسارُ الحقيقة. بلا REDIS_CACHE_URL
        # يكون الكاش LocMemCache — نسخةٌ لكلّ عمليّة — فرمزٌ يُسكّ في عاملٍ لا يراه
        # عاملٌ آخر يستقبل الحفظ، وكلّ إعادة تشغيلٍ تمحو المعلّق. وضياعُ زوج (قصاصة،
        # حقيقة) لا يُعوَّض: النصّ الخاطئ يُعاد حسابه غداً، وما كتبه الكاتب يضيع أبداً.
        try:
            from core.models import ScanPayload
            ScanPayload.objects.update_or_create(token=token, defaults={'data': payload})
        except Exception as exc:                  # الدوام تحسينٌ لا شرط
            logger.warning('[capture] تعذّر حفظ حمولة المسح دائماً: %s', type(exc).__name__)
        return token
    except Exception as exc:                      # الحلقة تحسينٌ لا شرط — لا تُفشل الاستخراج
        logger.warning('[capture] تعذّر سكّ رمز المسح: %s', type(exc).__name__)
        return ''


@api_view(['POST'])
@permission_classes([IsAuthenticated])
@rate_limit_scan(max_attempts=20, window_seconds=300)
def smart_extract_direct(request):
    """Synchronous extraction for the smart desktop UI (handles direct file uploads)."""

    logger.info(f"[smart_extract_direct] START - User: {request.user}, Method: {request.method}")
    logger.info(f"[smart_extract_direct] Content-Type: {request.content_type}")
    logger.info(f"[smart_extract_direct] FILES keys: {list(request.FILES.keys())}")

    upload = request.FILES.get('file')
    if not upload:
        logger.warning("[smart_extract_direct] No file uploaded")
        return _api_response(False, 'file is required', status_code=status.HTTP_400_BAD_REQUEST, error_code='MISSING_FILE')

    logger.info(f"[smart_extract_direct] File received: {upload.name}, size: {upload.size}, type: {upload.content_type}")

    allowed_types = {'image/jpeg', 'image/png', 'application/pdf'}
    if upload.content_type not in allowed_types:
        logger.warning(f"[smart_extract_direct] Invalid file type: {upload.content_type}")
        return _api_response(False, 'unsupported file type', status_code=status.HTTP_400_BAD_REQUEST, error_code='FILE_TYPE', details={'allowed': list(allowed_types)})

    max_size = 10 * 1024 * 1024  # 10MB
    if upload.size > max_size:
        logger.warning(f"[smart_extract_direct] File too large: {upload.size} bytes")
        return _api_response(False, 'file too large (max 10MB)', status_code=status.HTTP_400_BAD_REQUEST, error_code='FILE_SIZE', details={'max_bytes': max_size})

    temp_path = None
    try:
        suffix = Path(upload.name).suffix or '.tmp'
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            for chunk in upload.chunks():
                tmp.write(chunk)
            temp_path = tmp.name

        logger.info(f"[smart_extract_direct] Saved to temp: {temp_path}")

        try:
            logger.info("[smart_extract_direct] Starting AI processing...")
            service = AIExtractionService()
            result = service.process_image(temp_path)
            if getattr(result, 'status', '') == 'failed':
                # رسالة خطأ مفهومة للمستخدم من pipeline
                user_msg = getattr(result, 'user_message', '') or 'تعذر معالجة الملف'
                raise ValueError(user_msg)
            logger.info("[smart_extract_direct] AI processing complete. Confidence: %s", result.overall_confidence)
            payload = {
                'success': True,
                'message': getattr(result, 'user_message', 'تم الاستخراج بنجاح'),
                'request_id': _request_id(),
                'progress_stage': getattr(result, 'progress_stage', 'completed'),
                'book_number': result.book_number,
                'book_number_confidence': result.book_number_confidence,
                'book_date': result.book_date,
                'book_date_confidence': result.book_date_confidence,
                'sender_date': result.sender_date,
                'sender_date_confidence': result.sender_date_confidence,
                # القصاصةُ والاقتراح كانا يصلان في مسار البثّ ورمز المسح ويغيبان
                # عن الرفع المباشر — ثلاثةُ مسارات لحمولةٍ واحدة يجب أن تتساوى،
                # وإلّا اختلف سلوكُ الحقل باختلاف طريق المستخدم إليه.
                'sender_date_crop': getattr(result, 'sender_date_crop', None),
                'sender_date_suggestion': getattr(result, 'sender_date_suggestion', None),
                'sender_number': result.sender_number,
                'sender_number_confidence': result.sender_number_confidence,
                'title': result.title,
                'title_confidence': result.title_confidence,
                # اقتراحُ الموضوع الضعيف — المسارات الثلاثة تتساوى حمولةً
                'title_suggestion': getattr(result, 'title_suggestion', None),
                'issuing_entity': result.issuing_entity_name,
                'issuing_entity_confidence': result.issuing_entity_confidence,
                'issuing_entity_matches': slim_entity_matches(result.issuing_entity_matches),
                'receiving_entity': result.receiving_entity_name,
                'receiving_entity_confidence': result.receiving_entity_confidence,
                'receiving_entity_matches': slim_entity_matches(result.receiving_entity_matches),
                'secret_level': result.secret_level,
                'secret_level_confidence': result.secret_level_confidence,
                'book_kind': result.book_kind,
                'book_kind_confidence': result.book_kind_confidence,
                'overall_confidence': result.overall_confidence,
                'cached': result.cached,
                'needs_review': getattr(result, 'status', '') == 'manual_review',
                # حلقة التعلّم: ترسله الواجهة عند الحفظ فيُلتقَط (اقتراح → تصحيح الكاتب)
                'scan_token': _mint_scan_token(result),
            }
        except Exception as exc:
            logger.exception("Smart extract processing failed")
            if not getattr(settings, 'AI_ALLOW_MOCK_EXTRACTION', False):
                # تحديد رسالة مفهومة من نوع الخطأ
                err_str = str(exc)
                return _api_response(
                    False,
                    err_str or 'تعذر استخراج البيانات من الملف المرفوع',
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    error_code='EXTRACTION_FAILED',
                    details={'detail': err_str},
                )

            logger.warning("Smart extract mock fallback enabled")
            payload = {
                'success': True,
                'message': 'extraction mock used',
                'request_id': _request_id(),
                'book_number': '2024-001',
                'book_number_confidence': 0.92,
                'book_date': '2024-01-15',
                'book_date_confidence': 0.8,
                'title': 'تقرير شهري',
                'title_confidence': 0.9,
                'issuing_entity': 'وزارة الداخلية',
                'issuing_entity_confidence': 0.85,
                'receiving_entity': 'قسم المتابعة',
                'receiving_entity_confidence': 0.82,
                'secret_level': 'اعتيادي',
                'secret_level_confidence': 0.75,
                'book_kind': DEFAULT_BOOK_KIND,
                'book_kind_confidence': 0.8,
                'overall_confidence': 0.84,
                'cached': False,
                'detail': str(exc),
                'details': {
                    'fallback': True,
                    'reason': str(exc) or 'ai_service_unavailable'
                }
            }

        return Response(payload, status=status.HTTP_200_OK)
    except Exception as exc:
        logger.exception("Smart extract fatal error")
        return _api_response(False, 'extraction failed', status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, error_code='SERVER_ERROR', details={'detail': str(exc)})
    finally:
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass


# تسميات المراحل كما يراها المستخدم (مصدر واحد لرسائل التقدّم الحيّة)
_STAGE_LABELS = {
    'cache_check': 'تجهيز المستند',
    'image_enhancement': 'تحسين الصورة',
    'ocr': 'قراءة النص',
    'ocr_azure_fallback': 'تحسين القراءة (سحابة)',
    'pattern_matching': 'استخراج الحقول',
    'entity_matching': 'مطابقة الجهات',
    'handwritten_number': 'قراءة الرقم بخط اليد',
    'confidence': 'حساب الثقة',
}


@login_required
@require_http_methods(['POST'])
def smart_extract_stream(request):
    """بثّ الاستخراج تدريجياً (NDJSON): سطرٌ لكل مرحلة بحقولها المكتملة ثم سطر نهائي.

    يتيح للواجهة ملء الحقول لحظياً برسائل صادقة من الأنبوب نفسه، وإيقافاً يُبقي ما
    وصل — بدل انتظار الحصيلة كاملةً في نداء متزامن واحد.

    البنية: خيطٌ منتِج يشغّل process_image ويدفع أحداث on_progress إلى طابور،
    والمولّد يستنزف الطابور ويبثّ. قطع العميل للاتصال يُنهي البثّ، والخيط يُكمل
    ويُنظّف ملفه المؤقّت (لا يُقتَل — قتل خيط OCR غير آمن).
    """
    upload = request.FILES.get('file')
    if not upload:
        return JsonResponse({'ok': False, 'error': 'file مطلوب'}, status=400)
    if upload.content_type not in {'image/jpeg', 'image/png', 'application/pdf'}:
        return JsonResponse({'ok': False, 'error': 'نوع الملف غير مدعوم'}, status=400)
    if upload.size > 10 * 1024 * 1024:
        return JsonResponse({'ok': False, 'error': 'حجم الملف يتجاوز 10MB'}, status=400)

    suffix = Path(upload.name).suffix or '.tmp'
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        for chunk in upload.chunks():
            tmp.write(chunk)
        temp_path = tmp.name

    def _events():
        import json as _json
        import queue as _queue
        import threading as _threading
        from core.extraction.pipeline import result_to_scan_data

        events = _queue.Queue()
        box = {}

        def _on_progress(stage, fields):
            events.put({'type': 'stage', 'stage': stage,
                        'label': _STAGE_LABELS.get(stage, stage), 'fields': fields})

        def _work():
            try:
                box['result'] = AIExtractionService().process_image(
                    temp_path, on_progress=_on_progress)
            except Exception as exc:              # noqa: BLE001 — يُبلَّغ للعميل كسطر خطأ
                logger.exception('[extract-stream] فشل الاستخراج')
                box['error'] = str(exc)
            finally:
                # التنظيف في الخيط لا المولّد: العميل قد ينقطع مبكراً بينما OCR ما زال
                # يقرأ الملف (حذفه حينها يفشل على ويندوز فيتسرّب).
                try:
                    os.remove(temp_path)
                except OSError:
                    pass
                events.put(None)

        _threading.Thread(target=_work, daemon=True).start()

        while True:
            item = events.get()
            if item is None:
                break
            yield _json.dumps(item, ensure_ascii=False) + '\n'

        result = box.get('result')
        if result is None:
            yield _json.dumps({'type': 'error',
                               'message': box.get('error') or 'تعذّر استخراج البيانات'},
                              ensure_ascii=False) + '\n'
        else:
            payload = result_to_scan_data(result)
            payload.update({
                'type': 'done',
                'success': True,
                'request_id': _request_id(),
                'overall_confidence': result.overall_confidence,
                'cached': result.cached,
                # حلقة التعلّم: ترسله الواجهة عند الحفظ فيُلتقَط (اقتراح → تصحيح الكاتب)
                'scan_token': _mint_scan_token(result),
            })
            yield _json.dumps(payload, ensure_ascii=False) + '\n'

    resp = StreamingHttpResponse(_events(), content_type='application/x-ndjson; charset=utf-8')
    resp['Cache-Control'] = 'no-cache'
    resp['X-Accel-Buffering'] = 'no'      # امنع التخزين الوسيط (nginx) كي يصل التقدّم فوراً
    return resp


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def scan_token_retrieve(request, token: str):
    """
    استرجاع بيانات مسح مُعالَج مسبقاً عبر رمز مؤقت.
    يستخدمه Hot Folder Watcher لتمرير النتائج إلى الواجهة.
    صلاحية الرمز: 30 دقيقة.
    """
    from django.core.cache import cache
    data = cache.get(f'scan_token:{token}')
    if data is None:
        return _api_response(
            False, 'رمز المسح منتهي الصلاحية أو غير موجود',
            status_code=status.HTTP_404_NOT_FOUND,
            error_code='TOKEN_NOT_FOUND',
        )
    # ربط الرمز بصاحبه (يسدّ IDOR على رمز مُسرَّب)
    uid = data.get('user_id')
    if uid is not None and uid != request.user.id and not request.user.is_superuser:
        return _api_response(
            False, 'رمز المسح غير متاح',
            status_code=status.HTTP_404_NOT_FOUND, error_code='TOKEN_NOT_FOUND',
        )
    # لا نُسرّب مسار الخادم المطلق ولا user_id للواجهة — نكشف has_file فقط
    safe = {k: v for k, v in data.items() if k not in ('processed_path', 'user_id')}
    safe['has_file'] = bool(data.get('processed_path'))
    return Response({'success': True, 'data': safe}, status=status.HTTP_200_OK)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def suggestions_api(request):
    """Return suggestions from database with safe fallbacks."""

    category_key = request.query_params.get('category')
    if not category_key:
        return _api_response(False, 'category is required', status_code=status.HTTP_400_BAD_REQUEST, error_code='MISSING_CATEGORY')

    items = SuggestionItem.objects.filter(
        category__key=category_key,
        category__is_active=True,
        is_active=True,
    ).order_by('order', 'value')

    fallback_used = False
    if items.exists():
        values = [item.value for item in items]
    else:
        values = _fallback_suggestions(category_key)
        fallback_used = True

    return _api_response(True, 'ok', details={'items': values, 'fallback': fallback_used})
