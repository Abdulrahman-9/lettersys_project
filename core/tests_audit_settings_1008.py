# -*- coding: utf-8 -*-
"""تدقيقُ 2026-10-08، مجموعةُ «مركز الإعدادات» — جدوى كلّ تبويبٍ ومحتواه وتصميمه.

١. **تبويبُ «الإشعارات» يَعِد بما لا يجري**: «فحصُ الكتب المتأخّرة الذي يجري كلَّ يوم» — وأمرُ
   `notify_overdue_books` غيرُ مجدولٍ في أيّ مكان. الآن يقول ما جرى: آخرُ إشعار تأخّرٍ أُرسل، أو تنبيهٌ
   أنّه لم يجرِ قطّ وأنّ المفاتيح بلا أثرٍ حتى يُجدوَل.
٢. **تلميحُ «الأمان» ناقص**: الحدُّ الأدنى يُطبَّق أيضاً على إعادة التعيين وتغيير المستخدم كلمتَه.
٣. **تسمياتٌ غيرُ مربوطةٍ بحقولها** في «عام» و«الأمان» و«النسخ» والعدّادات (قارئُ الشاشة لا يسمّي الحقل).
٤. حذفُ جهازٍ من سجلّ الشبكة بحواريّة التطبيق لا `confirm()`.
"""
import re
from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

ROOT = Path(__file__).resolve().parent.parent
User = get_user_model()


class SettingsHubTruthTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.boss = User.objects.create_superuser('set_boss', 's@x.co', 'pw-set-boss-1')

    def html(self):
        self.client.force_login(self.boss)
        return self.client.get(reverse('settings_hub')).content.decode('utf-8')

    def test_never_ran_is_said(self):
        html = self.html()
        self.assertNotIn('الذي يجري كلَّ يوم', html)
        self.assertIn('لم يُرسَل أيُّ إشعار تأخّرٍ قطّ', html)

    def test_last_notice_is_shown(self):
        from core.models import Book, BookHistory

        book = Book.objects.create(kind='incoming_external', our_number='7801', title='متأخّر',
                                   created_by=self.boss)
        BookHistory.objects.create(book=book, action='overdue', by=None, notes='x')
        html = self.html()
        self.assertIn('آخرُ إشعار تأخّرٍ أُرسل', html)
        self.assertNotIn('لم يُرسَل أيُّ إشعار تأخّرٍ قطّ', html)

    def test_security_hint_names_every_path(self):
        self.assertIn('وإعادة تعيين كلماتهم، وعند تغيير المستخدم كلمتَه بنفسه', self.html())

    def test_every_label_is_bound(self):
        html = self.html()
        for field in ('app_name', 'brand_subtitle', 'password_min_length', 'frequency', 'hour', 'retention_days'):
            with self.subTest(field=field):
                tag = re.search(r'<(?:input|select)\b[^>]*\bname="%s"[^>]*>' % field, html)
                self.assertIsNotNone(tag, field)
                ident = re.search(r'\bid="([^"]+)"', tag.group(0))
                self.assertIsNotNone(ident, field)
                self.assertIn('for="%s"' % ident.group(1), html)


class SettingsScriptsTests(SimpleTestCase):
    def test_device_delete_uses_the_app_dialog(self):
        src = (ROOT / 'static' / 'network_settings.js').read_text(encoding='utf-8')
        # أيُّ confirm() أصليّ — عارٍ أو window.confirm — لا confirmDelete(
        self.assertNotRegex(src, r'(?<!\w)confirm\(')
        self.assertIn('window.confirmDelete({', src)

    def test_sequence_labels_are_bound(self):
        src = (ROOT / 'templates' / 'core' / 'sequence_settings.html').read_text(encoding='utf-8')
        self.assertIn('for="next_{{ seq.kind }}"', src)
        self.assertIn('id="next_{{ seq.kind }}"', src)
        self.assertIn('for="resTtl"', src)
