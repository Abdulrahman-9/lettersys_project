# -*- coding: utf-8 -*-
"""
ocr_process — يشغّل OCR على ملفّ واحد في عملية معزولة.

الغرض: محرّك OCR (EasyOCR/PyTorch) قد يُحدث تعطّلاً أصلياً (segfault)
لا يمكن التقاطه بـ try/except — وإذا عمل داخل عملية خادم الويب أسقطها
كاملةً. تشغيله كعملية فرعية يجعل التعطّل محصوراً فيها وحدها.

الاستخدام (داخلي — يستدعيه run_ocr_isolated):
    python manage.py ocr_process <مسار_الصورة> <مسار_ملف_الإخراج_JSON>
"""
import json

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'تشغيل OCR على ملفّ واحد في عملية معزولة وكتابة الناتج JSON.'

    def add_arguments(self, parser):
        parser.add_argument('image_path')
        parser.add_argument('output_json')

    def handle(self, *args, **options):
        image_path = options['image_path']
        output_json = options['output_json']
        try:
            from core.extraction.pipeline import AIExtractionService, result_to_scan_data
            service = AIExtractionService()
            result = service.process_image(image_path)
            payload = {'ok': True, 'data': result_to_scan_data(result)}
        except Exception as exc:  # noqa: BLE001 — نُبلّغ كل خطأ كنتيجة
            payload = {'ok': False, 'data': {'needs_review': True, '_error': str(exc)}}

        with open(output_json, 'w', encoding='utf-8') as f:
            json.dump(payload, f, ensure_ascii=False, default=str)
