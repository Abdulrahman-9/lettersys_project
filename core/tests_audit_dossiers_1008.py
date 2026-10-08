# -*- coding: utf-8 -*-
"""تدقيقُ 2026-10-08، مجموعةُ «الأضابير» بمبادئ نيلسن.

**الاتّجاهُ الظاهرُ يضيع (H1/H3)**: ملفُّ نوعٍ يُفتح من تبويب «وارد» كان يُعيد الصفحةَ على «صادر» متى
وُجد صادرٌ من النوع نفسِه — فيرى المستخدمُ كتباً غيرَ التي نقر عليها. وكذلك «تطبيق» المرشّحات بعد
التبديل إلى «وارد». الآن `side` يُحمل في بطاقات الملفّات والنموذج والعنوان، وبلا اختيارٍ: حيث الكتب.
"""
import re
from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from core.models import Book, Entity

ROOT = Path(__file__).resolve().parent.parent
User = get_user_model()


class DossierSideTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.boss = User.objects.create_superuser('dos_boss', 'd@x.co', 'pw-dos-boss-1')
        cls.entity = Entity.objects.create(name='جهةُ الإضبارة')
        out = Book.objects.create(kind='outgoing_external', our_number='', title='صادرٌ إليها',
                                  document_type='مذكرة', created_by=cls.boss)
        out.issuing_entities.add(cls.entity)
        inc = Book.objects.create(kind='incoming_external', our_number='7701', title='واردٌ منها',
                                  document_type='مذكرة', created_by=cls.boss)
        inc.receiving_entities.add(cls.entity)

    def html(self, **params):
        self.client.force_login(self.boss)
        resp = self.client.get(reverse('dossier_detail', args=[self.entity.pk]), params)
        self.assertEqual(resp.status_code, 200)
        return resp.content.decode('utf-8')

    def active_pane(self, html):
        return re.search(r'class="dd-pane active" id="(pane-\w+)"', html).group(1)

    def test_default_is_where_the_books_are(self):
        self.assertEqual(self.active_pane(self.html()), 'pane-out')

    def test_an_incoming_folder_opens_on_incoming(self):
        html = self.html()
        pane_in = html[html.index('id="pane-in"'):]
        self.assertRegex(pane_in, r'href="\?[^"]*document_type=[^"]*&(amp;)?side=in"')
        html = self.html(document_type='مذكرة', side='in')
        self.assertEqual(self.active_pane(html), 'pane-in')
        self.assertIn('name="side" id="dd-side" value="in"', html)

    def test_back_to_all_files_keeps_the_side(self):
        html = self.html(document_type='مذكرة', side='in')
        back = re.search(r'class="sf-back" href="([^"]+)"', html).group(1)
        self.assertIn('side=in', back)
        self.assertNotIn('document_type', back)

    def test_garbage_side_falls_back(self):
        self.assertEqual(self.active_pane(self.html(side='sideways')), 'pane-out')


class DossierScriptTests(SimpleTestCase):
    def test_tab_switch_carries_the_side(self):
        src = (ROOT / 'templates' / 'core' / 'dossier_detail.html').read_text(encoding='utf-8')
        self.assertIn("if (tab.dataset.side) setSide(tab.dataset.side);", src)
        self.assertIn("p.set('side', side);", src)
