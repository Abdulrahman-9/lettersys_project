# -*- coding: utf-8 -*-
"""تدقيقُ 2026-10-08، مجموعةُ «القشرة» وما خرج منها إلى البريد الصادر.

١. **البريدُ الخارجُ يكتب الرقمَ المخزَّن** («20250825») في موضوع الرسالة وجسمها وإشعار الردّ وموضوع
   الإنشاء — والجهةُ الخارجيّةُ ترى على ورقتها «825/2025». الآن ``our_number_display`` (numbering.py
   مصدرٌ وحيدٌ للعرض)، وتاريخُ الجسم يوم/شهر/سنة.
٢. **جسمُ إشعار الكتاب يُدرج العنوانَ واسمَ المؤسّسة في HTML بلا تهريب** — عنوانٌ فيه `<` يصير وسماً في
   بريد المستلم. الآن ``escape``.
٣. **صفحةُ «بلا اتّصال» تقول «لا يوجد اتصال بالإنترنت»** والنظامُ على شبكة المكتب — الآن «تعذّر الوصول إلى الخادم».
٤. صفحةُ التحقّق العامّة بتاريخ يوم/شهر/سنة، وملفٌّ فارغ (`keyboard_nav.js`) كان يُحمَّل بلا عمل — حُذف.
"""
import datetime
from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from core.models import Book, Entity

ROOT = Path(__file__).resolve().parent.parent
User = get_user_model()


class OutgoingMailNumberTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.boss = User.objects.create_superuser('shell_boss', 'b@x.co', 'pw-shell-boss-1')
        cls.book = Book.objects.create(kind='incoming_external', our_number='20250825',
                                       title='<b>عنوانٌ</b> & غيره', date=datetime.date(2025, 3, 9),
                                       created_by=cls.boss)
        cls.entity = Entity.objects.create(name='جهةٌ تُراسَل', email='x@example.com')
        cls.book.issuing_entities.add(cls.entity)

    def test_notification_body_is_escaped_and_displayed(self):
        from core.messaging.engines.smtp import SMTPEngine

        html = SMTPEngine()._render_notification_html(self.book, self.entity, 'received')
        self.assertIn('825/2025', html)
        self.assertNotIn('20250825', html)
        self.assertIn('&lt;b&gt;عنوانٌ&lt;/b&gt; &amp; غيره', html)
        self.assertNotIn('<b>عنوانٌ</b>', html)
        self.assertIn('09/03/2025', html)

    def test_compose_subject_uses_the_display_number(self):
        self.client.force_login(self.boss)
        ctx = self.client.get(reverse('mail_compose_book', args=[self.book.pk])).context
        self.assertIn('825/2025', ctx['prefill']['subject'])
        self.assertNotIn('20250825', ctx['prefill']['subject'])

    def test_no_stored_number_in_outgoing_text(self):
        for rel in ('core/messaging/engines/smtp.py', 'core/messaging/engines/imap.py',
                    'core/messaging/api/email_endpoints.py', 'core/messaging/views/ui.py'):
            with self.subTest(file=rel):
                src = (ROOT / rel).read_text(encoding='utf-8')
                self.assertNotRegex(src, r"\{[a-z_.]*book\.our_number( or '')?\}")


class ShellPagesTests(SimpleTestCase):
    def read(self, rel):
        return (ROOT / rel).read_text(encoding='utf-8')

    def test_offline_page_names_the_office_network(self):
        src = self.read('templates/offline.html')
        self.assertNotIn('لا يوجد اتصال بالإنترنت', src)
        self.assertIn('تعذّر الوصول إلى الخادم', src)

    def test_verify_page_dates(self):
        src = self.read('templates/core/signature_verify.html')
        self.assertNotIn('date:"Y/m/d', src)
        self.assertIn('date:"d/m/Y', src)

    def test_empty_shim_is_gone(self):
        self.assertFalse((ROOT / 'static' / 'keyboard_nav.js').exists())
        self.assertNotIn('keyboard_nav.js', self.read('templates/core/extraction_smart_desktop.html'))
