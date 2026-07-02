#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
اختبار سريع: التحقق من أن attachment_url يتم تسلسله بشكل صحيح في AJAX
"""

import os
import sys
import django
from pathlib import Path
from io import BytesIO
from django.core.files.uploadedfile import SimpleUploadedFile

# Setup Django
BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'lettersys.settings_test')
django.setup()

from django.contrib.auth.models import User
from core.models import Book, Attachment, Entity
from core.views.books_list import _serialize_book
from django.test import Client
from django.urls import reverse
from django.utils import timezone

def test_attachment_url_serialization():
    """اختبار: التحقق من أن attachment_url يتم تسلسله بشكل صحيح"""
    
    print("=" * 70)
    print("اختبار تسلسل attachment_url")
    print("=" * 70)
    
    # إنشاء مستخدم
    user = User.objects.create_user(username='testuser', password='pass123')
    print(f"✓ تم إنشاء المستخدم: {user}")
    
    # إنشاء جهة
    entity = Entity.objects.create(name='جهة اختبار', code='TEST')
    print(f"✓ تم إنشاء الجهة: {entity}")
    
    # إنشاء كتاب
    book = Book.objects.create(
        our_number='001',
        title='كتاب اختبار',
        kind='incoming_internal',
        date=timezone.now(),
        created_by=user,
    )
    book.issuing_entities.add(entity)
    print(f"✓ تم إنشاء الكتاب: {book}")
    
    # إنشاء مرفق PDF
    pdf_content = b'%PDF-1.4\n%%EOF'  # محتوى PDF بسيط
    pdf_file = SimpleUploadedFile(
        'test.pdf',
        pdf_content,
        content_type='application/pdf'
    )
    attachment = Attachment.objects.create(
        book=book,
        file=pdf_file
    )
    print(f"✓ تم إنشاء المرفق: {attachment}")
    print(f"  - اسم الملف: {attachment.file.name}")
    print(f"  - حجم الملف: {attachment.file.size}")
    
    # اختبار 1: book.attachment property
    print("\n--- اختبار 1: book.attachment property ---")
    retrieved_attachment = book.attachment
    print(f"✓ retrieved_attachment: {retrieved_attachment}")
    print(f"  - has file: {retrieved_attachment.file if retrieved_attachment else 'None'}")
    if retrieved_attachment and retrieved_attachment.file:
        print(f"  - file URL: {retrieved_attachment.file.url}")
    
    # اختبار 2: _serialize_book
    print("\n--- اختبار 2: _serialize_book function ---")
    serialized = _serialize_book(book)
    print(f"✓ Serialized book:")
    for key, value in serialized.items():
        print(f"  - {key}: {value}")
    
    # اختبار 3: API endpoint
    print("\n--- اختبار 3: api_unified_data endpoint ---")
    client = Client()
    client.login(username='testuser', password='pass123')
    response = client.get(reverse('api_unified_data'))
    
    print(f"✓ Response status: {response.status_code}")
    data = response.json()
    print(f"✓ Books in response: {len(data['books'])}")
    
    if data['books']:
        book_data = data['books'][0]
        print(f"\n✓ First book in response:")
        for key, value in book_data.items():
            if key == 'attachment_url':
                print(f"  ✓✓ {key}: {value}")  # Highlight attachment_url
            else:
                print(f"  - {key}: {value}")
    else:
        print("⚠ لا توجد كتب في الاستجابة!")
    
    print("\n" + "=" * 70)
    print("✓ انتهى الاختبار")
    print("=" * 70)

if __name__ == '__main__':
    test_attachment_url_serialization()
