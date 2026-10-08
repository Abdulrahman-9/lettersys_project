# -*- coding: utf-8 -*-
"""تدقيقُ 2026-10-08، مجموعةُ «الجهات» بمبادئ نيلسن العشرة.

١. **المرشِّحاتُ تضيع (H3)**: روابطُ قائمة الجهات تُبنى يدويّاً فيُسقط كلٌّ منها مفتاحاً — الترقيمُ يُسقط
   الترتيب (الصفحةُ الثانية من «الأكثر كتباً» أبجديّة)، و«مسح» البحث يُسقط التبويبَ واللغة. الآن
   ``{% qs %}`` واحدٌ يحمل كلَّ المرشّحات ويغيّر مفتاحاً واحداً؛ والتعطيلُ الفرديّ يعود إلى المرشِّح.
٢. **صفحةُ الجهة تدلّ الموظّفَ على 403 (H5)**: «القائمة» و«تعديل» لكلّ موظّف والصفحتان لإدارة النظام.
٣. **صفُّ كتابٍ سرّيٍّ يفتح معاينةً تقول «ليس لديك صلاحية» (H5/H9)** — الصفُّ المحجوب بلا معاينة.
٤. **ترقيمُ «المستلمة» يُعيد الصفحةَ على «المُصدرة» (H1/H3)**، وتسلسلُ الصفوف يبدأ من 1 في كلّ صفحة.
"""
import re

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase
from django.template import Context, Template
from django.urls import reverse

from core.models import Book, Department, Entity, UserProfile

User = get_user_model()


class QsTagTests(TestCase):
    def render(self, query, tag):
        request = RequestFactory().get('/books/entities/' + query)
        return Template('{% load qs %}' + tag).render(Context({'request': request}))

    def test_keeps_every_filter_and_changes_one(self):
        out = self.render('?kind=gov&lang=ar&sort=books&q=x&page=3', "{% qs page=4 %}")
        self.assertEqual(sorted(out.lstrip('?').split('&amp;')),
                         sorted(['kind=gov', 'lang=ar', 'sort=books', 'q=x', 'page=4']))

    def test_a_new_filter_starts_at_page_one(self):
        out = self.render('?kind=gov&sort=books&page=3', "{% qs kind='co' %}")
        self.assertNotIn('page=', out)
        self.assertIn('sort=books', out)
        self.assertIn('kind=co', out)

    def test_empty_removes(self):
        self.assertEqual(self.render('?q=x', "{% qs q='' %}"), '?')


class EntityListLinksTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user('ent_admin', password='pw-ent-admin-1', is_staff=True)
        # الصفحةُ 100 جهة — 120 تكفي لصفحتين
        Entity.objects.bulk_create([Entity(name='جهة رقم %03d' % i) for i in range(120)])

    def test_paging_keeps_the_sort_and_clearing_keeps_the_tab(self):
        self.client.force_login(self.admin)
        html = self.client.get(reverse('entity_list'), {'sort': 'books', 'lang': 'ar', 'q': 'جهة'}).content.decode()
        pages = re.findall(r'class="page-link" href="([^"]+)"', html)
        self.assertTrue(pages, 'لا ترقيم')
        for href in pages:
            with self.subTest(href=href):
                self.assertIn('sort=books', href)
                self.assertIn('lang=ar', href)
        clear = re.search(r'href="([^"]*)" class="btn btn-outline-secondary">مسح<', html).group(1)
        self.assertIn('sort=books', clear)
        self.assertIn('lang=ar', clear)
        self.assertNotIn('q=', clear)

    def test_single_disable_returns_to_the_same_filter(self):
        self.client.force_login(self.admin)
        e = Entity.objects.first()
        resp = self.client.post(reverse('entity_delete', args=[e.pk]), {'back': '?sort=books&lang=ar'})
        self.assertEqual(resp['Location'], reverse('entity_list') + '?sort=books&lang=ar')
        # ورابطٌ خارجيّ لا يُتبَع (لا تحويلَ مفتوح)
        resp = self.client.post(reverse('entity_delete', args=[e.pk]), {'back': 'https://evil.example/'})
        self.assertEqual(resp['Location'], reverse('entity_list'))


class EntityDetailTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.dept = Department.objects.create(name='قسم الجهة', code='ج.ه')
        cls.clerk = User.objects.create_user('ent_clerk', password='pw-ent-clerk-1')
        UserProfile.objects.update_or_create(user=cls.clerk, defaults={'department': cls.dept})
        cls.writer = User.objects.create_user('ent_writer', password='pw-ent-writer-1')
        UserProfile.objects.update_or_create(user=cls.writer, defaults={'department': cls.dept})
        cls.admin = User.objects.create_user('ent_admin2', password='pw-ent-admin-2', is_staff=True)
        cls.entity = Entity.objects.create(name='جهةٌ تُراسَل')
        cls.open_book = Book.objects.create(kind='incoming_external', our_number='7501', title='عاديّ',
                                            department=cls.dept, created_by=cls.writer)
        cls.secret_book = Book.objects.create(kind='incoming_external', our_number='7502', title='سرّيّ',
                                              department=cls.dept, created_by=cls.writer,
                                              secret_level='secret')
        for b in (cls.open_book, cls.secret_book):
            b.issuing_entities.add(cls.entity)
            b.receiving_entities.add(cls.entity)

    def html(self, user, **params):
        self.client.force_login(user)
        resp = self.client.get(reverse('entity_detail', args=[self.entity.pk]), params)
        self.assertEqual(resp.status_code, 200)
        return resp.content.decode('utf-8')

    def test_no_link_to_a_403_for_a_clerk(self):
        html = self.html(self.clerk)
        self.assertNotIn('href="%s"' % reverse('entity_list'), html)
        self.assertNotIn(reverse('entity_edit', args=[self.entity.pk]), html)
        self.assertEqual(self.client.get(reverse('entity_list')).status_code, 403)
        admin_html = self.html(self.admin)
        self.assertIn('href="%s"' % reverse('entity_list'), admin_html)

    def test_a_restricted_row_opens_no_preview(self):
        html = self.html(self.clerk)
        self.assertIn('data-book-preview="%d"' % self.open_book.pk, html)
        self.assertNotIn('data-book-preview="%d"' % self.secret_book.pk, html)

    def test_received_pagination_stays_on_its_tab(self):
        html = self.html(self.clerk, pr=1)
        self.assertRegex(html, r'id="received-tab"[^>]*aria-selected="true"')
        self.assertRegex(html, r'class="tab-pane fade show active" id="received-pane"')
        html = self.html(self.clerk)
        self.assertRegex(html, r'class="tab-pane fade show active" id="issued-pane"')


class FollowupWordTests(TestCase):
    """«مؤرشف» كلمةُ الورق لا المتابعة (نيلسن A#4) — بقيت شارةً في ثلاثة مواضع (H4)."""

    def test_no_followup_badge_says_archived(self):
        from pathlib import Path
        root = Path(__file__).resolve().parent.parent / 'templates' / 'core'
        for rel in ('entity_detail.html', 'partials/book_preview_modal.html',
                    'partials/book_unified_card_mobile.html'):
            with self.subTest(template=rel):
                src = (root / rel).read_text(encoding='utf-8')
                self.assertNotRegex(src, r">\s*مؤرشف\s*<|label: 'مؤرشف'|</i> مؤرشف")
                self.assertIn('مُنجَز / بلا متابعة', src)
