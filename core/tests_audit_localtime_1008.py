# -*- coding: utf-8 -*-
"""تدقيقُ 2026-10-08 — الأوقاتُ تُعرض بتوقيت الخادم المحلّيّ لا UTC.

``strftime`` على وقتٍ واعٍ (``USE_TZ=True``) يكتب UTC: معاينةُ الكتاب كانت تقول «أُنشئ 05:21» والكتابُ
أُنشئ 08:21 (Asia/Baghdad)، والتعليقُ المضاف للتوّ يظهر بساعةٍ متأخّرةٍ ثلاثاً حتى يُعاد تحميلُ الصفحة،
واسمُ ملفّ النسخة الاحتياطيّة بساعة UTC فيختار المديرُ النسخةَ الخطأ عند الاستعادة.
"""
import json
import re
from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import Book

ROOT = Path(__file__).resolve().parent.parent
User = get_user_model()


class LocalTimeShownTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.boss = User.objects.create_superuser('tz_boss', 'z@x.co', 'pw-tz-boss-1')
        cls.book = Book.objects.create(kind='incoming_external', our_number='7901', title='توقيت',
                                       created_by=cls.boss)

    def setUp(self):
        self.client.force_login(self.boss)

    def test_the_server_zone_is_not_utc(self):
        # بلا فارقٍ لا يُثبت الاختبارُ شيئاً
        self.assertNotEqual(timezone.localtime(self.book.created_at).utcoffset().total_seconds(), 0)

    def test_preview_created_at_is_local(self):
        data = self.client.get(reverse('api_book_detail_json', args=[self.book.pk])).json()
        self.assertEqual(data['created_at'],
                         timezone.localtime(self.book.created_at).strftime('%Y-%m-%d %H:%M'))

    def test_new_comment_time_is_local(self):
        resp = self.client.post(reverse('add_book_comment', args=[self.book.pk]),
                                data=json.dumps({'content': 'تعليقٌ للتوقيت'}), content_type='application/json')
        payload = resp.json()
        from core.models import BookComment
        comment = BookComment.objects.get(pk=payload['comment']['id'])
        self.assertEqual(payload['comment']['created_at'],
                         timezone.localtime(comment.created_at).strftime('%d/%m/%Y %H:%M'))


class NoUtcStrftimeTests(SimpleTestCase):
    """لا ``<حقل>_at.strftime(`` ولا ``timezone.now().strftime(`` في طبقة العرض والخدمات."""

    def test_no_raw_aware_strftime(self):
        offenders = []
        files = list((ROOT / 'core' / 'views').glob('*.py')) + list((ROOT / 'core').glob('*_service.py'))
        for path in files:
            for no, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
                if re.search(r'\b\w+_at\.strftime\(|timezone\.now\(\)\.strftime\(', line):
                    offenders.append('%s:%d' % (path.relative_to(ROOT).as_posix(), no))
        self.assertEqual(offenders, [])
