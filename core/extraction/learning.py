# -*- coding: utf-8 -*-
"""
core.extraction.learning
=========================
نظام التعلم من تصحيحات المستخدمين لتحسين دقة الاستخراج الآلي
"""

import logging
from django.db.models import Q, Count, Avg
from django.utils import timezone
from datetime import timedelta

from core.models import (
    DataExtractionResult,
    ExtractionFeedback,
    ExtractionStatistics,
    OCRResult
)

logger = logging.getLogger(__name__)


class ExtractionLearningSystem:
    """نظام التعلم المستمر من التصحيحات"""

    @staticmethod
    def analyze_feedback_patterns(days=7):
        """تحليل أنماط التصحيحات في آخر X أيام"""
        cutoff_date = timezone.now() - timedelta(days=days)

        feedback = ExtractionFeedback.objects.filter(
            created_at__gte=cutoff_date
        ).values('field_name').annotate(
            total_corrections=Count('id'),
        ).order_by('-total_corrections')

        patterns = {}
        for item in feedback:
            # تقدير معدل الأخطاء ككل التصحيحات على أنها أخطاء (لا توجد درجة ثقة محفوظة)
            patterns[item['field_name']] = {
                'total_corrections': item['total_corrections'],
                'error_rate': 1.0 if item['total_corrections'] else 0.0,
                'average_confidence': 0.0,
                'severity': 'high' if item['total_corrections'] > 10 else 'medium' if item['total_corrections'] > 5 else 'low'
            }

        return patterns

    @staticmethod
    def get_field_accuracy_score(field_name, days=30):
        """حساب درجة دقة حقل معين"""
        cutoff_date = timezone.now() - timedelta(days=days)

        feedback = ExtractionFeedback.objects.filter(
            field_name=field_name,
            created_at__gte=cutoff_date
        )

        total = feedback.count()
        if total == 0:
            return None

        incorrect = feedback.filter(feedback_type='incorrect').count()
        correct = total - incorrect
        accuracy = correct / total

        return {
            'field': field_name,
            'accuracy': accuracy,
            'correct': correct,
            'total': total,
            'grade': 'A' if accuracy >= 0.95 else 'B' if accuracy >= 0.85 else 'C' if accuracy >= 0.70 else 'D'
        }

    @staticmethod
    def get_most_corrected_fields(limit=5, days=30):
        """الحقول الأكثر تصحيحاً"""
        cutoff_date = timezone.now() - timedelta(days=days)

        return ExtractionFeedback.objects.filter(
            created_at__gte=cutoff_date,
            feedback_type='incorrect'
        ).values('field_name').annotate(
            error_count=Count('id')
        ).order_by('-error_count')[:limit]

    @staticmethod
    def get_confidence_threshold_recommendation():
        """توصيات لحد ثقة أمثل"""
        # لا توجد بيانات أخطاء مباشرة على نتيجة الاستخراج حالياً، نُرجع عتبات افتراضية

        thresholds = {
            'auto_approve': 0.90,  # توافق تلقائي
            'manual_review': 0.70,  # يحتاج مراجعة
            'manual_correction': 0.50,  # يحتاج تصحيح يدوي
            'rejection': 0.30  # رفض كامل
        }

        return thresholds

    @staticmethod
    def suggest_improvements():
        """اقتراحات لتحسين النظام"""
        suggestions = []

        # تحليل الحقول الضعيفة
        field_accuracy = {}
        for field in ['book_number', 'title', 'book_date', 'secret_level', 'book_kind']:
            score = ExtractionLearningSystem.get_field_accuracy_score(field)
            if score:
                field_accuracy[field] = score['accuracy']

        # اقتراح الحقول التي تحتاج تحسين
        for field, accuracy in field_accuracy.items():
            if accuracy < 0.80:
                suggestions.append({
                    'type': 'field_accuracy',
                    'field': field,
                    'current_accuracy': accuracy,
                    'recommendation': f'تحسين استخراج {field}: النسبة الحالية {accuracy*100:.1f}%',
                    'priority': 'high' if accuracy < 0.70 else 'medium'
                })

        # تحليل أنماط الأخطاء
        patterns = ExtractionLearningSystem.analyze_feedback_patterns()
        for field, pattern in patterns.items():
            if pattern['error_rate'] > 0.15:
                suggestions.append({
                    'type': 'error_pattern',
                    'field': field,
                    'error_rate': pattern['error_rate'],
                    'recommendation': f'نمط أخطاء متكرر في {field}: {pattern["error_rate"]*100:.1f}% من الاستخراجات بها أخطاء',
                    'priority': pattern['severity']
                })

        return suggestions

    @staticmethod
    def update_statistics():
        """تحديث إحصائيات الاستخراج"""
        today = timezone.now().date()

        # جلب الإحصائيات
        total_extractions = DataExtractionResult.objects.filter(
            created_at__date=today
        ).count()

        successful = DataExtractionResult.objects.filter(
            created_at__date=today,
            overall_confidence__gte=0.80
        ).count()

        failed = DataExtractionResult.objects.filter(
            created_at__date=today,
            overall_confidence__lt=0.50
        ).count()

        manual_review = DataExtractionResult.objects.filter(
            created_at__date=today,
            overall_confidence__gte=0.50,
            overall_confidence__lt=0.80
        ).count()

        avg_conf = DataExtractionResult.objects.filter(created_at__date=today).aggregate(avg=Avg('overall_confidence'))['avg'] or 0.0

        # حفظ الإحصائيات باستخدام الحقول الحالية للموديل
        stats, _ = ExtractionStatistics.objects.get_or_create(
            date=today,
            defaults={
                'total_images_processed': total_extractions,
                'successful_extractions': successful,
                'failed_extractions': failed,
                'manual_review_required': manual_review,
                'average_confidence': float(avg_conf),
                'average_processing_time': 0.0,
                'min_processing_time': 0.0,
                'max_processing_time': 0.0,
                'field_stats': {},
            }
        )
        # تحديث عند وجود قيّم جديدة
        stats.total_images_processed = total_extractions
        stats.successful_extractions = successful
        stats.failed_extractions = failed
        stats.manual_review_required = manual_review
        stats.average_confidence = float(avg_conf)
        stats.save()
        return stats

    @staticmethod
    def predict_extraction_quality(field_values):
        """التنبؤ بجودة الاستخراج بناءً على التاريخ"""
        # تحليل الأنماط التاريخية
        historical_patterns = ExtractionLearningSystem.analyze_feedback_patterns(days=30)

        predicted_quality = {
            'overall_score': 0.85,  # افتراضي
            'field_scores': {},
            'recommendation': 'proceed'
        }

        for field, value in field_values.items():
            if field in historical_patterns:
                pattern = historical_patterns[field]
                # حساب النسبة المتوقعة
                expected_score = 1 - pattern['error_rate']
                predicted_quality['field_scores'][field] = expected_score

        # حساب النسبة الكلية
        if predicted_quality['field_scores']:
            avg_score = sum(predicted_quality['field_scores'].values()) / len(predicted_quality['field_scores'])
            predicted_quality['overall_score'] = avg_score

            if avg_score < 0.50:
                predicted_quality['recommendation'] = 'reject'
            elif avg_score < 0.70:
                predicted_quality['recommendation'] = 'manual_review'
            elif avg_score < 0.90:
                predicted_quality['recommendation'] = 'review_before_save'
            else:
                predicted_quality['recommendation'] = 'auto_save'

        return predicted_quality

    @staticmethod
    def get_learning_report(days=30):
        """تقرير التعلم الشامل"""
        cutoff_date = timezone.now() - timedelta(days=days)

        report = {
            'period_days': days,
            'total_extractions': DataExtractionResult.objects.filter(
                created_at__gte=cutoff_date
            ).count(),
            'total_corrections': ExtractionFeedback.objects.filter(
                created_at__gte=cutoff_date
            ).count(),
            'field_accuracy': {},
            'top_errors': [],
            'suggestions': [],
            'overall_trend': 'improving',  # improving, stable, declining
        }

        # دقة الحقول
        for field in ['book_number', 'title', 'book_date', 'secret_level', 'book_kind']:
            score = ExtractionLearningSystem.get_field_accuracy_score(field, days)
            if score:
                report['field_accuracy'][field] = score

        # أكثر الأخطاء
        top_errors = ExtractionLearningSystem.get_most_corrected_fields(limit=5, days=days)
        report['top_errors'] = list(top_errors)

        # الاقتراحات
        report['suggestions'] = ExtractionLearningSystem.suggest_improvements()

        return report
