#!/usr/bin/env python
"""
Pre-load EasyOCR model to avoid first-time delay.
Run this once after installation: python preload_ocr_model.py
"""
import os
import django

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'lettersys.settings')
django.setup()

from core.ai_ocr_service import OCRService

print("🔄 تحميل نموذج EasyOCR مسبقاً...")
print("⏳ قد يستغرق هذا عدة دقائق في المرة الأولى...")

try:
    service = OCRService()
    print("✅ تم تحميل النموذج بنجاح!")
    print("📌 الآن يمكنك استخدام النظام بدون تأخير.")
except Exception as e:
    print(f"❌ فشل التحميل: {e}")
    print("⚠️  تأكد من تثبيت easyocr: pip install easyocr")
