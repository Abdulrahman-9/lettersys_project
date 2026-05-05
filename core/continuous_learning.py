"""
===================================================
Continuous Learning Service
===================================================

نظام التعلم المستمر لـ OCR
يتعلم من التصحيحات اليدوية ويبني datasets تلقائياً
"""

import os
import json
import logging
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Dict, Optional

from django.conf import settings
from django.utils import timezone
from django.db.models import Count, Q

from .models import OCRFeedback, TrainingDataset, OCRModelVersion

logger = logging.getLogger(__name__)


class ContinuousLearningService:
    """
    خدمة التعلم المستمر
    """
    
    def __init__(self):
        self.min_samples_for_training = 500  # الحد الأدنى لبدء التدريب
        self.training_interval_days = 7  # كل أسبوع
    
    def record_feedback(
        self,
        image_path: str,
        original_text: str,
        corrected_text: str,
        language: str = 'ar',
        original_confidence: float = 0.0,
        user=None
    ) -> OCRFeedback:
        """
        تسجيل تصحيح يدوي
        
        Args:
            image_path: مسار الصورة
            original_text: النص المستخرج من OCR
            corrected_text: النص المصحح
            language: اللغة
            original_confidence: ثقة OCR الأصلية
            user: المستخدم الذي صحح
        
        Returns:
            OCRFeedback object
        """
        feedback = OCRFeedback.objects.create(
            image_path=image_path,
            original_text=original_text,
            corrected_text=corrected_text,
            language=language,
            original_confidence=original_confidence,
            corrected_by=user
        )
        
        # حساب نوع التصحيح تلقائياً
        feedback.calculate_correction_type()
        feedback.save()
        
        logger.info(f"[ContinuousLearning] تم تسجيل تصحيح جديد: {feedback.id} ({language})")
        
        # تحقق إذا كان لدينا عدد كافٍ للتدريب
        self.check_and_trigger_training()
        
        return feedback
    
    def check_and_trigger_training(self) -> bool:
        """
        تحقق إذا كان يجب بدء التدريب
        
        Returns:
            True إذا بدأ التدريب
        """
        # عدد التصحيحات غير المستخدمة
        pending_count = OCRFeedback.objects.filter(
            used_for_training=False
        ).count()
        
        logger.info(f"[ContinuousLearning] عدد التصحيحات المعلقة: {pending_count}")
        
        # تحقق من الحد الأدنى
        if pending_count < self.min_samples_for_training:
            logger.info(f"[ContinuousLearning] لم نصل للحد الأدنى ({self.min_samples_for_training})")
            return False
        
        # تحقق من آخر تدريب
        last_training = OCRModelVersion.objects.filter(
            is_production=True
        ).order_by('-created_at').first()
        
        if last_training:
            days_since = (timezone.now() - last_training.created_at).days
            if days_since < self.training_interval_days:
                logger.info(f"[ContinuousLearning] التدريب الأخير كان قبل {days_since} أيام فقط")
                return False
        
        # ابدأ التدريب!
        logger.info(f"[ContinuousLearning] ✅ بدء التدريب التلقائي!")
        self.build_training_dataset()
        return True
    
    def build_training_dataset(self) -> Optional[TrainingDataset]:
        """
        بناء dataset من التصحيحات المعلقة
        
        Returns:
            TrainingDataset object
        """
        logger.info("[ContinuousLearning] بناء Dataset جديد...")
        
        # احصل على جميع التصحيحات غير المستخدمة
        feedbacks = OCRFeedback.objects.filter(
            used_for_training=False
        ).select_related('corrected_by')
        
        if not feedbacks.exists():
            logger.warning("[ContinuousLearning] لا توجد تصحيحات للتدريب!")
            return None
        
        # إحصائيات
        stats = feedbacks.aggregate(
            total=Count('id'),
            arabic=Count('id', filter=Q(language='ar')),
            english=Count('id', filter=Q(language='en'))
        )
        
        # إنشاء dataset
        dataset_name = f"auto_dataset_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        dataset = TrainingDataset.objects.create(
            name=dataset_name,
            dataset_type='feedback',
            status='processing',
            total_samples=stats['total'],
            arabic_samples=stats['arabic'],
            english_samples=stats['english']
        )
        
        # بناء ملف البيانات
        dataset_file_path = self._build_dataset_file(feedbacks, dataset)
        
        if dataset_file_path:
            dataset.status = 'ready'
            dataset.save()
            
            logger.info(f"[ContinuousLearning] ✅ تم بناء Dataset: {dataset.name}")
            logger.info(f"   - إجمالي العينات: {stats['total']}")
            logger.info(f"   - عربي: {stats['arabic']}")
            logger.info(f"   - إنجليزي: {stats['english']}")
            
            # ضع علامة على الفيدباكات كمستخدمة
            feedbacks.update(
                used_for_training=True,
                training_date=timezone.now()
            )
            
            return dataset
        else:
            dataset.status = 'error'
            dataset.save()
            logger.error("[ContinuousLearning] ❌ فشل بناء Dataset!")
            return None
    
    def _build_dataset_file(
        self,
        feedbacks,
        dataset: TrainingDataset
    ) -> Optional[str]:
        """
        بناء ملف Dataset فعلي
        
        Returns:
            مسار الملف
        """
        try:
            # مجلد الحفظ
            dataset_dir = Path(settings.MEDIA_ROOT) / 'training_datasets'
            dataset_dir.mkdir(parents=True, exist_ok=True)
            
            dataset_file = dataset_dir / f"{dataset.name}.jsonl"
            
            # كتابة البيانات
            with open(dataset_file, 'w', encoding='utf-8') as f:
                for feedback in feedbacks:
                    data = {
                        'image_path': feedback.image_path,
                        'original_text': feedback.original_text,
                        'corrected_text': feedback.corrected_text,
                        'language': feedback.language,
                        'confidence': feedback.original_confidence,
                        'correction_type': feedback.correction_type,
                        'corrected_at': feedback.corrected_at.isoformat()
                    }
                    f.write(json.dumps(data, ensure_ascii=False) + '\n')
            
            logger.info(f"[ContinuousLearning] حُفظ Dataset في: {dataset_file}")
            return str(dataset_file)
            
        except Exception as e:
            logger.error(f"[ContinuousLearning] خطأ في بناء ملف Dataset: {e}")
            return None
    
    def get_training_statistics(self) -> Dict:
        """
        احصل على إحصائيات التدريب
        """
        stats = {
            'total_feedbacks': OCRFeedback.objects.count(),
            'pending_feedbacks': OCRFeedback.objects.filter(
                used_for_training=False
            ).count(),
            'used_feedbacks': OCRFeedback.objects.filter(
                used_for_training=True
            ).count(),
            'total_datasets': TrainingDataset.objects.count(),
            'ready_datasets': TrainingDataset.objects.filter(
                status='ready'
            ).count(),
            'total_models': OCRModelVersion.objects.count(),
            'active_model': None,
        }
        
        # النموذج النشط
        active_model = OCRModelVersion.objects.filter(is_active=True).first()
        if active_model:
            stats['active_model'] = {
                'version': active_model.version,
                'accuracy_arabic': active_model.accuracy_arabic,
                'accuracy_english': active_model.accuracy_english,
                'created_at': active_model.created_at.isoformat()
            }
        
        # إحصائيات حسب اللغة
        language_stats = OCRFeedback.objects.values('language').annotate(
            count=Count('id')
        )
        stats['by_language'] = {
            item['language']: item['count']
            for item in language_stats
        }
        
        return stats
    
    def extract_from_archive(
        self,
        archive_path: str,
        max_files: int = 1000,
        save_to_feedback: bool = True
    ) -> Dict:
        """
        استخراج البيانات من ملفات الأرشيف القديمة (PDF)
        
        Args:
            archive_path: مسار مجلد الأرشيف
            max_files: الحد الأقصى للملفات
            save_to_feedback: حفظ كـ feedback للتدريب؟
        
        Returns:
            معلومات الاستخراج
        """
        import fitz  # PyMuPDF
        from .ai_ocr_service import OCRService
        
        logger.info(f"[ContinuousLearning] بدء الاستخراج من الأرشيف: {archive_path}")
        
        # إنشاء instance من OCRService
        ocr_service = OCRService()
        
        archive_path = Path(archive_path)
        if not archive_path.exists():
            logger.error(f"[ContinuousLearning] المسار غير موجود: {archive_path}")
            return {'success': False, 'error': 'المسار غير موجود'}
        
        # ابحث عن جميع ملفات PDF
        pdf_files = list(archive_path.glob('**/*.pdf'))[:max_files]
        
        if not pdf_files:
            logger.warning(f"[ContinuousLearning] لا توجد ملفات PDF في: {archive_path}")
            return {'success': False, 'error': 'لا توجد ملفات PDF'}
        
        logger.info(f"[ContinuousLearning] وُجد {len(pdf_files)} ملف PDF")
        
        extracted_data = []
        errors = 0
        
        for i, pdf_file in enumerate(pdf_files, 1):
            try:
                logger.info(f"[ContinuousLearning] معالجة {i}/{len(pdf_files)}: {pdf_file.name}")
                
                # فتح PDF
                try:
                    doc = fitz.open(str(pdf_file))
                except Exception as e:
                    logger.error(f"[ContinuousLearning] فشل فتح PDF: {pdf_file.name} - {e}")
                    errors += 1
                    continue
                
                try:
                    # معالجة أول 3 صفحات فقط (للسرعة)
                    num_pages = min(len(doc), 3)
                    
                    for page_num in range(num_pages):
                        page = doc[page_num]
                        
                        try:
                            # تحويل الصفحة إلى صورة
                            pix = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5))  # 1.5x zoom للسرعة
                            img_data = pix.tobytes("png")
                            
                            if not img_data:
                                logger.warning(f"[ContinuousLearning] فشل تحويل الصفحة: {pdf_file.name}")
                                continue
                        except Exception as e:
                            logger.warning(f"[ContinuousLearning] خطأ في تحويل الصفحة: {e}")
                            errors += 1
                            continue
                        
                        # حفظ مؤقت
                        import tempfile
                        tmp_path = None
                        try:
                            with tempfile.NamedTemporaryFile(suffix='.png', delete=False, mode='wb') as tmp:
                                tmp.write(img_data)
                                tmp_path = tmp.name
                            
                            # التحقق من كتابة الملف
                            if not Path(tmp_path).exists():
                                logger.warning(f"فشل كتابة الملف المؤقت: {tmp_path}")
                                continue
                            
                            # استخراج النص بـ OCR
                            result = ocr_service.extract_text(tmp_path, detail=True)
                            
                            if result and result.get('status') == 'success' and result.get('raw_text'):
                                text = result['raw_text']
                                confidence = float(result.get('avg_confidence', 0.0))
                                language = self._detect_language(text) or 'unknown'
                                
                                # ✅ تصحيح البيانات
                                confidence = max(0.0, min(1.0, confidence))  # تثبيت في [0, 1]
                                
                                # حفظ كـ feedback للتدريب
                                if save_to_feedback and len(text.strip()) > 10:
                                    try:
                                        feedback = OCRFeedback.objects.create(
                                            image_path=f"archive:{pdf_file.name}:page{page_num+1}",
                                            original_text=text,
                                            corrected_text=text,  # نفس النص (لا يوجد تصحيح)
                                            language=language,
                                            original_confidence=confidence,
                                            used_for_training=False,
                                            correction_type='minor',
                                        )
                                        
                                        extracted_data.append({
                                            'file': pdf_file.name,
                                            'page': page_num + 1,
                                            'text': text[:100] + '...',
                                            'confidence': confidence,
                                            'language': language,
                                            'feedback_id': feedback.id
                                        })
                                    except (ValueError, TypeError) as e:
                                        logger.error(f"خطأ في البيانات: {e}")
                                        errors += 1
                                    except Exception as e:
                                        logger.error(f"فشل حفظ التصحيح: {e}")
                                        errors += 1
                        
                        finally:
                            # حذف آمن للملف المؤقت
                            if tmp_path and Path(tmp_path).exists():
                                try:
                                    Path(tmp_path).unlink()
                                except OSError as e:
                                    logger.debug(f"فشل حذف الملف المؤقت: {e}")
                
                finally:
                    # ✅ إغلاق PDF بشكل آمن
                    try:
                        doc.close()
                    except Exception as e:
                        logger.debug(f"خطأ في إغلاق PDF: {e}")
                    
            except Exception as e:
                errors += 1
                logger.error(f"[ContinuousLearning] خطأ في {pdf_file.name}: {e}", exc_info=True)
        
        # النتائج
        if extracted_data:
            logger.info(f"[ContinuousLearning] تم استخراج {len(extracted_data)} صفحة من {len(pdf_files)} ملف")
            
            return {
                'success': True,
                'total_files': len(pdf_files),
                'extracted': len(extracted_data),
                'errors': errors,
                'samples': extracted_data[:10]  # أول 10 للمعاينة
            }
        else:
            return {
                'success': False,
                'total_files': len(pdf_files),
                'extracted': 0,
                'errors': errors,
                'error': 'لم يتم استخراج أي بيانات'
            }
    
    def _save_archive_dataset(
        self,
        name: str,
        extracted_data: List[Dict]
    ) -> Optional[TrainingDataset]:
        """
        حفظ البيانات المستخرجة من الأرشيف
        """
        try:
            # إحصائيات
            arabic_count = sum(1 for d in extracted_data if d['language'] == 'ar')
            english_count = sum(1 for d in extracted_data if d['language'] == 'en')
            
            # إنشاء dataset
            dataset = TrainingDataset.objects.create(
                name=name,
                dataset_type='archive',
                status='ready',
                total_samples=len(extracted_data),
                arabic_samples=arabic_count,
                english_samples=english_count
            )
            
            # حفظ الملف
            dataset_dir = Path(settings.MEDIA_ROOT) / 'training_datasets'
            dataset_dir.mkdir(parents=True, exist_ok=True)
            dataset_file = dataset_dir / f"{name}.jsonl"
            
            with open(dataset_file, 'w', encoding='utf-8') as f:
                for data in extracted_data:
                    f.write(json.dumps(data, ensure_ascii=False) + '\n')
            
            logger.info(f"[ContinuousLearning] ✅ حُفظ dataset الأرشيف: {dataset.name}")
            return dataset
            
        except Exception as e:
            logger.error(f"[ContinuousLearning] خطأ في حفظ dataset: {e}")
            return None
    
    def _detect_language(self, text: str) -> str:
        """
        كشف لغة النص (بسيط)
        """
        if not text:
            return 'unknown'
        
        arabic_chars = sum(1 for c in text if '\u0600' <= c <= '\u06FF')
        english_chars = sum(1 for c in text if 'a' <= c.lower() <= 'z')
        
        if arabic_chars > english_chars:
            return 'ar'
        elif english_chars > arabic_chars:
            return 'en'
        else:
            return 'mixed'


# مثيل عام
continuous_learning = ContinuousLearningService()
