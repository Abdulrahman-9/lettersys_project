# -*- coding: utf-8 -*-
"""
core.extraction.helpers
========================
مساعدات لتبسيط عملية الاستخراج والملء التلقائي للمستخدم النهائي
"""

import logging
from typing import Dict, List, Tuple, Optional, Any
from datetime import datetime, date

from django.db import transaction
from django.utils import timezone

from core.extraction.kinds import normalize_book_kind
from core.models import (
    Attachment, Book, BookHistory, DataExtractionResult, Entity, ExtractionFeedback
)

logger = logging.getLogger(__name__)


def _normalize_secret_level(value: Optional[str]) -> str:
    normalized = (value or 'normal').strip().lower()
    aliases = {
        '': 'normal',
        'normal': 'normal',
        'confidential': 'secret',
        'secret': 'secret',
        'top_secret': 'topsecret',
        'topsecret': 'topsecret',
    }
    return aliases.get(normalized, 'normal')


class ExtractionWorkflow:
    """
    سير عمل متكامل لاستخراج البيانات وملء النموذج بسهولة

    الخطوات:
    1. اختيار المرفق (صورة/PDF)
    2. تشغيل الاستخراج الآلي
    3. مراجعة النتائج مع إبراز الأخطاء المحتملة
    4. تصحيح يدوي إذا لزم
    5. حفظ وتعلم من التصحيحات
    """

    def __init__(self, attachment_id: int, user=None):
        self.attachment_id = attachment_id
        self.user = user
        self.attachment = None
        self.extraction = None
        self.corrections = {}

    def validate_attachment(self) -> Tuple[bool, str]:
        """التحقق من صحة المرفق"""
        try:
            self.attachment = Attachment.objects.get(id=self.attachment_id)

            # التحقق من نوع الملف
            allowed_types = ['image/jpeg', 'image/png', 'image/jpg', 'application/pdf']
            content_type = None
            try:
                # بعض ملفات الاختبار لا تحتفظ بـ content_type بعد الحفظ
                content_type = getattr(getattr(self.attachment.file, 'file', None), 'content_type', None)
            except Exception:
                content_type = None
            if not content_type:
                # استدلال النوع من الامتداد عند غياب content_type
                name = (self.attachment.file.name or '').lower()
                if name.endswith(('.jpg', '.jpeg')):
                    content_type = 'image/jpeg'
                elif name.endswith('.png'):
                    content_type = 'image/png'
                elif name.endswith('.pdf'):
                    content_type = 'application/pdf'
            if content_type not in allowed_types:
                return False, "نوع الملف غير مدعوم. استخدم صورة أو PDF"

            # التحقق من حجم الملف (أقصى 10MB)
            if self.attachment.file.size > 10 * 1024 * 1024:
                return False, "حجم الملف أكبر من 10MB"

            return True, "المرفق صحيح"
        except Attachment.DoesNotExist:
            return False, "المرفق غير موجود"

    def start_extraction(self) -> Dict[str, Any]:
        """بدء عملية الاستخراج"""
        is_valid, msg = self.validate_attachment()
        if not is_valid:
            return {'success': False, 'error': msg}

        try:
            # جلب أحدث نتيجة استخراج
            self.extraction = self.attachment.data_extraction

            return {
                'success': True,
                'extraction_id': self.extraction.id,
                'confidence': self.extraction.overall_confidence,
                'status': self.extraction.status,
                'message': 'تم جلب نتائج الاستخراج بنجاح'
            }
        except DataExtractionResult.DoesNotExist:
            return {'success': False, 'error': 'لم تتم معالجة هذا المرفق بعد'}

    def get_review_summary(self) -> Dict[str, Any]:
        """الحصول على ملخص المراجعة مع الأخطاء المحتملة"""
        if not self.extraction:
            return {'error': 'لا توجد نتائج للمراجعة'}

        issues = []
        warnings = []

        # فحص كل حقل
        checks = [
            ('book_number', self.extraction.book_number, 0.7, 'رقم الكتاب'),
            ('book_date', self.extraction.book_date, 0.75, 'تاريخ الكتاب'),
            ('title', self.extraction.title, 0.8, 'العنوان'),
            ('secret_level', self.extraction.secret_level, 0.7, 'مستوى السرية'),
        ]

        for field, value, min_conf, label in checks:
            conf = getattr(self.extraction, f'{field}_confidence', 0)
            if not value:
                issues.append(f'❌ {label}: لم يتم استخراجه')
            elif conf < min_conf:
                warnings.append(f'⚠️ {label}: ثقة منخفضة ({conf*100:.0f}%)')

        return {
            'overall_confidence': self.extraction.overall_confidence,
            'issues': issues,
            'warnings': warnings,
            'is_ready': len(issues) == 0,  # جاهز للحفظ إذا لا توجد أخطاء حرجة
        }

    def apply_corrections(self, corrections: Dict[str, any]) -> Tuple[bool, str]:
        """تطبيق التصحيحات وحفظها"""
        if not self.extraction:
            return False, 'لا توجد نتائج للتصحيح'

        self.corrections = corrections

        try:
            with transaction.atomic():
                # حفظ القيم الأصلية قبل التعديل
                originals = {}
                for field, value in corrections.items():
                    if hasattr(self.extraction, field):
                        originals[field] = getattr(self.extraction, field)
                # تحديث الاستخراج
                for field, value in corrections.items():
                    if hasattr(self.extraction, field) and value is not None:
                        setattr(self.extraction, field, value)

                self.extraction.updated_at = timezone.now()
                self.extraction.reviewed_by = self.user
                self.extraction.reviewed_at = timezone.now()
                self.extraction.save()

                # تسجيل التصحيحات للتعلم
                for field, value in corrections.items():
                    if value is not None:
                        original = originals.get(field)
                        if str(original) != str(value):
                            ExtractionFeedback.objects.create(
                                extraction=self.extraction,
                                field_name=field,
                                feedback_type='incorrect' if original not in [None, ''] else 'partial',
                                original_value=str(original or ''),
                                corrected_value=str(value),
                                reason='User correction',
                                created_by=self.user
                            )

                logger.info(f"تم حفظ التصحيحات للاستخراج {self.extraction.id}")
                return True, 'تم حفظ التصحيحات بنجاح'

        except Exception as e:
            logger.error(f"خطأ في حفظ التصحيحات: {str(e)}")
            return False, f'خطأ: {str(e)}'

    def create_book_from_extraction(self, book_data: Dict[str, any]) -> Tuple[bool, str, Optional[Book]]:
        """إنشاء كتاب من نتائج الاستخراج"""
        if not self.extraction:
            return False, 'لا توجد نتائج استخراج', None
        if not self.user:
            return False, 'يجب تحديد المستخدم المنشئ للكتاب', None

        try:
            book_date = QuickFillAssistant.normalize_date(
                book_data.get('date') or book_data.get('book_date') or self.extraction.book_date
            ) or timezone.localdate()
            sender_date = QuickFillAssistant.normalize_date(book_data.get('sender_date'))
            due_date = QuickFillAssistant.normalize_date(book_data.get('due_date'))
            needs_followup = bool(book_data.get('needs_followup'))
            effective_due = due_date if needs_followup else None

            # دمج بيانات الاستخراج مع البيانات المقدمة من المستخدم
            merged_data = {
                'our_number': book_data.get('our_number') or book_data.get('book_number') or self.extraction.book_number or '',
                'sender_number': book_data.get('sender_number', ''),
                'kind': normalize_book_kind(book_data.get('kind') or book_data.get('book_kind') or self.extraction.book_kind),
                'title': book_data.get('title') or self.extraction.title,
                'secret_level': _normalize_secret_level(book_data.get('secret_level') or self.extraction.secret_level),
                'date': book_date,
                'sender_date': sender_date,
                'due_date': effective_due,
                'is_archived': (effective_due is None),
                'margin': book_data.get('margin') or book_data.get('margin_text') or self.extraction.margin_text or '',
                'created_by': self.user,
            }

            # جلب الجهات
            issuing_entity_id = book_data.get('issuing_entity_id') or self.extraction.issuing_entity_id
            receiving_entity_id = book_data.get('receiving_entity_id') or self.extraction.receiving_entity_id

            if not issuing_entity_id or not receiving_entity_id:
                return False, 'يجب تحديد الجهات المرسلة والمستقبلة', None

            issuing_entity = Entity.objects.filter(pk=issuing_entity_id).first()
            receiving_entity = Entity.objects.filter(pk=receiving_entity_id).first()
            if not issuing_entity or not receiving_entity:
                return False, 'الجهات المحددة غير موجودة', None

            with transaction.atomic():
                book = Book.objects.create(**merged_data)
                book.issuing_entities.add(issuing_entity)
                book.receiving_entities.add(receiving_entity)
                BookHistory.objects.create(book=book, action='create', by=self.user)

            # ربط الاستخراج بالكتاب
            self.extraction.book = book
            self.extraction.status = 'approved'
            self.extraction.approved_by = self.user
            self.extraction.approved_at = timezone.now()
            self.extraction.reviewed_by = self.user
            self.extraction.reviewed_at = timezone.now()
            self.extraction.save()

            logger.info(f"تم إنشاء الكتاب {book.id} من الاستخراج {self.extraction.id}")
            return True, f'تم إنشاء الكتاب بنجاح (#{book.our_number})', book

        except Exception as e:
            logger.error(f"خطأ في إنشاء الكتاب: {str(e)}")
            return False, f'خطأ: {str(e)}', None


class ConfidenceAnalyzer:
    """تحليل درجات الثقة واقتراح التحسينات"""

    CONFIDENCE_THRESHOLDS = {
        'high': 0.85,
        'medium': 0.65,
        'low': 0.50,
    }

    @classmethod
    def get_field_reliability(cls, field_name: str, confidence: float) -> Dict[str, Any]:
        """الحصول على موثوقية الحقل"""
        if confidence >= cls.CONFIDENCE_THRESHOLDS['high']:
            level = 'عالية جداً ✓'
            color = 'success'
            action = 'يمكن الحفظ مباشرة'
        elif confidence >= cls.CONFIDENCE_THRESHOLDS['medium']:
            level = 'متوسطة ⚠️'
            color = 'warning'
            action = 'يرجى المراجعة'
        else:
            level = 'منخفضة ❌'
            color = 'danger'
            action = 'يجب التصحيح يدوياً'

        return {
            'level': level,
            'color': color,
            'action': action,
            'percentage': f'{confidence * 100:.0f}%'
        }

    @classmethod
    def get_extraction_quality_score(cls, extraction: DataExtractionResult) -> Dict[str, Any]:
        """حساب درجة جودة الاستخراج الكلية"""
        fields = [
            ('book_number', extraction.book_number_confidence),
            ('book_date', extraction.book_date_confidence),
            ('title', extraction.title_confidence),
            ('secret_level', extraction.secret_level_confidence),
            ('book_kind', extraction.book_kind_confidence),
        ]

        weighted_score = sum(conf for _, conf in fields if conf > 0) / len([f for f in fields if f[1] > 0])

        if weighted_score >= 0.85:
            grade = 'ممتاز'
            recommendation = 'جاهز للحفظ الفوري'
        elif weighted_score >= 0.70:
            grade = 'جيد'
            recommendation = 'يحتاج مراجعة سريعة'
        else:
            grade = 'ضعيف'
            recommendation = 'يحتاج تصحيح يدوي شامل'

        return {
            'score': weighted_score,
            'grade': grade,
            'recommendation': recommendation,
            'fields': {f: cls.get_field_reliability(f, c) for f, c in fields}
        }


class QuickFillAssistant:
    """مساعد الملء السريع والذكي"""

    @staticmethod
    def get_entity_suggestions(text: str, entity_type: str = 'both') -> List[Dict[str, Any]]:
        """اقتراح جهات بناءً على النص"""
        if not text or len(text) < 2:
            return []

        # البحث البسيط (يمكن تحسينه بـ fuzzy matching)
        entities = Entity.objects.filter(
            name__icontains=text
        )

        if entity_type != 'both':
            entities = entities.filter(etype__in=[entity_type, 'both'])

        return [
            {'id': e.id, 'name': e.name, 'code': e.code}
            for e in entities[:5]  # أعلى 5 نتائج
        ]

    @staticmethod
    def normalize_date(date_input: any) -> Optional[date]:
        """تحويل التاريخ لصيغة موحدة"""
        if isinstance(date_input, date):
            return date_input

        if isinstance(date_input, str):
            # محاولة تحويل من عدة صيغ
            for fmt in ['%Y-%m-%d', '%d-%m-%Y', '%d/%m/%Y', '%Y/%m/%d']:
                try:
                    return datetime.strptime(date_input, fmt).date()
                except ValueError:
                    continue

        return None

    @staticmethod
    def extract_confidence_summary(extraction: DataExtractionResult) -> str:
        """ملخص نصي عن الثقة"""
        score = extraction.overall_confidence

        if score >= 0.9:
            return '🟢 استخراج موثوق جداً - لا توجد مشاكل'
        elif score >= 0.8:
            return '🟡 استخراج جيد - قد توجد بعض التفاصيل الدقيقة'
        elif score >= 0.6:
            return '🟠 استخراج متوسط - يرجى المراجعة'
        else:
            return '🔴 استخراج ضعيف - يحتاج تصحيح يدوي'
