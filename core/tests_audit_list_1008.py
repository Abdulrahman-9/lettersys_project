# -*- coding: utf-8 -*-
"""تدقيقُ 2026-10-08، مجموعةُ «القائمة الموحّدة».

١. **الجماعيُّ بقاعدة الفرديّ**: الحذفُ والحالةُ الجماعيّان كانا يقرّران بـ«مُنشئُه أو مديرُ
   النظام» والفرديُّ بشجرة القسم المالك (``can_edit_book``، Q1‑ج) — فيحذف المُنشئُ جماعيّاً
   كتاباً صار لقسمٍ آخر، ويُترك كتابُ زميل القسم صامتاً.
٢. **الواجهةُ لا تُخمّن**: كانت تمحو كلَّ المحدَّد وتكتب حالتَه ولو رفض الخادمُ بعضَه؛ الآن
   تعرض رسالةَ الخادم (التي تسمّي المتروك) وتُعيد القائمة منه. والمعرّفاتُ النصّيّة («12»)
   كانت تُعدّ «فاشلةً» ولو حُذفت.
٣. **المعاينةُ تعرض الرقمَ المعروض** («825/2025») لا المخزَّن («20250825»)، والتواريخَ يوماً/شهراً/سنة.
٤. **شريطُ الترقيم يُرسم دائماً** (مخفيّاً بلا صفحاتٍ أخرى) فيجد التحميلُ اللاحق أين يرسم «التالي».
"""
import json
import re
from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from core.models import Book, Department, UserProfile

ROOT = Path(__file__).resolve().parent.parent
User = get_user_model()


def _member(name, department):
    user = User.objects.create_user(name, name + '@x.co', 'pw-' + name + '-1008')
    UserProfile.objects.update_or_create(user=user, defaults={'department': department})
    return user


class BulkFollowsSingleRuleTests(TestCase):
    """الحذفُ والحالةُ الجماعيّان = ``can_edit_book`` على كلّ كتاب، كالفرديّ."""

    def setUp(self):
        self.mine = Department.objects.create(name='قسم التدقيق', code='ت.د')
        self.other = Department.objects.create(name='قسمٌ غيره', code='ت.غ')
        self.me = _member('auditor1008', self.mine)
        self.colleague = _member('colleague1008', self.mine)
        # كتابُ زميلي في قسمي: الفرديُّ يحذفه — فالجماعيُّ أيضاً
        self.dept_book = Book.objects.create(kind='incoming_external', title='كتابُ القسم',
                                             our_number='7101', department=self.mine,
                                             created_by=self.colleague, due_date='2026-12-01')
        # كتابٌ أنشأتُه وصار لقسمٍ آخر: الفرديُّ يرفضه — فالجماعيُّ أيضاً
        self.moved_book = Book.objects.create(kind='incoming_external', title='كتابٌ انتقل',
                                              our_number='7102', department=self.other,
                                              created_by=self.me, due_date='2026-12-01')
        # الكتابُ يولد «بلا متابعة» (is_archived=True) — افتحهما ليكون للإنهاء ما يغيّره
        Book.objects.filter(pk__in=[self.dept_book.pk, self.moved_book.pk]).update(is_archived=False)
        self.client.force_login(self.me)

    def _post(self, name, **body):
        return self.client.post(reverse(name), data=json.dumps(body), content_type='application/json')

    def test_single_rule_is_the_reference(self):
        single_ok = self.client.post(reverse('api_delete_book', args=[self.dept_book.pk]))
        self.assertEqual(single_ok.status_code, 200)
        single_no = self.client.post(reverse('api_delete_book', args=[self.moved_book.pk]))
        self.assertEqual(single_no.status_code, 403)

    def test_bulk_delete_matches_single(self):
        data = self._post('api_bulk_delete_books',
                          book_ids=[str(self.dept_book.pk), str(self.moved_book.pk)]).json()
        self.assertEqual(data['deleted_count'], 1)
        self.assertEqual(data['failed_ids'], [self.moved_book.pk])
        self.assertIn('الباقي ليس لقسمك', data['message'])
        self.dept_book.refresh_from_db()
        self.moved_book.refresh_from_db()
        self.assertTrue(self.dept_book.is_deleted)
        self.assertFalse(self.moved_book.is_deleted)

    def test_string_ids_are_not_reported_as_failures(self):
        data = self._post('api_bulk_delete_books', book_ids=[str(self.dept_book.pk)]).json()
        self.assertEqual((data['deleted_count'], data['failed_ids']), (1, []))
        self.assertNotIn('الباقي', data['message'])

    def test_bulk_status_matches_single(self):
        data = self._post('api_bulk_update_status_books', status='archived',
                          book_ids=[self.dept_book.pk, self.moved_book.pk]).json()
        self.assertEqual(data['updated_count'], 1)
        self.assertIn('ليس لقسمك', data['message'])
        self.dept_book.refresh_from_db()
        self.moved_book.refresh_from_db()
        self.assertTrue(self.dept_book.is_archived)
        self.assertFalse(self.moved_book.is_archived)

    def test_bulk_status_names_the_unchanged(self):
        Book.objects.filter(pk=self.dept_book.pk).update(is_archived=True)
        data = self._post('api_bulk_update_status_books', status='archived',
                          book_ids=[self.dept_book.pk]).json()
        self.assertEqual(data['updated_count'], 0)
        self.assertIn('لم يتغيّر', data['message'])

    def test_get_is_refused(self):
        self.assertEqual(self.client.get(reverse('api_bulk_delete_books')).status_code, 405)


class ListScriptsTests(SimpleTestCase):
    def read(self, rel):
        return (ROOT / rel).read_text(encoding='utf-8')

    def test_bulk_actions_reload_from_the_server(self):
        src = self.read('static/js/book_unified_actions.js')
        self.assertNotIn('window.confirm(', src)
        self.assertNotIn('removeBooksFromDom', src)
        self.assertNotIn('applyStatusToBookInDom', src)
        for handler in ('bulkDeleteBtn.addEventListener', 'confirmBulkUpdateBtn.addEventListener'):
            with self.subTest(handler=handler):
                block = src[src.index(handler):]
                block = block[:block.index('\n    }\n')]
                self.assertIn('await reloadList(', block)
                self.assertIn('announceMessage(payload.message', block)

    def test_escape_spares_open_dialogs_and_fields(self):
        src = self.read('static/js/book_unified_actions.js')
        esc = src[src.index('if (event.key !== "Escape") return;'):]
        esc = esc[:esc.index('clearSelection();')]
        self.assertIn('.modal.show', esc)
        self.assertIn('INPUT|TEXTAREA|SELECT', esc)

    def test_single_delete_uses_the_app_dialog(self):
        src = self.read('static/js/book_unified_api.js')
        self.assertNotIn('window.confirm(', src)
        self.assertIn('window.confirmDelete({', src)
        self.assertNotIn('await response.json();', src)

    def test_preview_shows_the_display_number_and_dmy_dates(self):
        src = self.read('templates/core/partials/book_preview_modal.html')
        self.assertIn('const shownNumber = d.our_number_display || d.our_number;', src)
        self.assertNotIn("text('bpOurNumber', d.our_number)", src)
        for field in ('d.date', 'd.created_at', 'd.sender_date', 'd.due_date'):
            with self.subTest(field=field):
                self.assertIn('dmy(%s)' % field, src)

    def test_pagination_nav_is_shown_and_hidden_by_the_renderer(self):
        src = self.read('static/js/book_unified_ajax_manager.js')
        self.assertIn("nav.hidden = !(p.total > 1);", src)


class ListPageRenderTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.boss = User.objects.create_superuser('listboss1008', 'l@x.co', 'pw-list-1008')
        cls.tagged = Book.objects.create(kind='incoming_external', title='كتابٌ موسوم',
                                         our_number='20250825', created_by=cls.boss)

    def setUp(self):
        self.client.force_login(self.boss)

    def test_single_page_still_carries_a_hidden_nav(self):
        html = self.client.get(reverse('book_unified')).content.decode('utf-8')
        self.assertRegex(html, r'<nav aria-label="ترقيم الصفحات" id="paginationNav" hidden>')
        self.assertIn('id="paginationList"', html)

    def test_delete_confirmation_names_the_display_number(self):
        html = self.client.get(reverse('book_unified')).content.decode('utf-8')
        shown = self.tagged.our_number_display
        self.assertNotEqual(shown, '20250825')
        self.assertIn('data-book-number="%s"' % shown, html)
        self.assertNotIn('data-book-number="20250825"', html)
