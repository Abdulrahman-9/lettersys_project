# -*- coding: utf-8 -*-
"""
Tests for core/views/books_*.py modules.

Covers:
- books_api.py  : save_book_api, delete, bulk-delete, bulk-status, undo, detail-json, inline-status
- books_list.py : book_unified, api_unified_data, trash_list
- books_detail.py: book_detail, book_edit, book_change_status
"""

import json
import tempfile
from datetime import date, timedelta

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, Client, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import Book, BookHistory, BookComment, Attachment, Entity, OCRResult


# ---------------------------------------------------------------------------
# Shared setUp mixin
# ---------------------------------------------------------------------------

class BookViewsBase(TestCase):
    """Creates a standard set of users and books for all tests."""

    def setUp(self):
        self.client = Client()

        # owner user  — creates books
        self.user = User.objects.create_user(
            username='owner', password='pass1234'
        )
        # other user  — must NOT see owner's books
        self.other = User.objects.create_user(
            username='other', password='pass1234'
        )
        # superuser   — sees everything
        self.superuser = User.objects.create_superuser(
            username='admin', password='pass1234', email='admin@test.com'
        )

        self.entity = Entity.objects.create(
            name='وزارة الداخلية', code='MOI', etype='issuer', is_active=True
        )

        self.book = Book.objects.create(
            our_number='2024-001',
            title='كتاب تجريبي',
            date=date(2024, 1, 15),
            kind='incoming_internal',
            due_date=date.today() + timedelta(days=5),  # قيد المتابعة
            is_archived=False,
            created_by=self.user,
        )

        # A second book owned by `other` — مؤرشف (بلا due_date)
        self.other_book = Book.objects.create(
            our_number='2024-999',
            title='كتاب المستخدم الآخر',
            date=date(2024, 1, 20),
            kind='outgoing_internal',
            is_archived=True,
            created_by=self.other,
        )

    def _login(self, user=None):
        user = user or self.user
        self.client.force_login(user)


# ===========================================================================
# books_api.py — save_book_api
# ===========================================================================

class SaveBookAPITests(BookViewsBase):

    URL = 'save-book-api'

    def _post(self, data=None):
        return self.client.post(reverse(self.URL), data or {})

    def test_login_required(self):
        resp = self._post({'title': 'x'})
        self.assertIn(resp.status_code, [302, 403])

    def test_get_not_allowed(self):
        self._login()
        resp = self.client.get(reverse(self.URL))
        self.assertEqual(resp.status_code, 405)
        self.assertFalse(resp.json()['success'])

    def test_missing_required_field_returns_400(self):
        self._login()
        # missing 'title' and 'date'
        resp = self._post({'our_number': '2024-100', 'kind': 'incoming_internal'})
        self.assertEqual(resp.status_code, 400)
        data = resp.json()
        self.assertFalse(data['success'])
        self.assertEqual(data['error_code'], 'MISSING_FIELD')

    def test_invalid_date_returns_400(self):
        self._login()
        resp = self._post({
            'our_number': '2024-100',
            'title': 'كتاب',
            'date': 'not-a-date',
            'kind': 'incoming_internal',
        })
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()['error_code'], 'INVALID_DATE')

    def test_duplicate_number_returns_409(self):
        self._login()
        resp = self._post({
            'our_number': self.book.our_number,  # already exists
            'title': 'كتاب آخر',
            'date': '2024-02-01',
            'kind': self.book.kind,
        })
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.json()['error_code'], 'DUPLICATE_NUMBER')

    def test_success_creates_book(self):
        self._login()
        before = Book.objects.count()
        resp = self._post({
            'our_number': '2024-NEW-1',
            'title': 'كتاب جديد',
            'date': '2024-03-01',
            'kind': 'incoming_internal',
        })
        self.assertEqual(resp.status_code, 201)
        data = resp.json()
        self.assertTrue(data['success'])
        self.assertIn('book_id', data)
        self.assertEqual(Book.objects.count(), before + 1)

    def test_success_creates_book_history(self):
        self._login()
        resp = self._post({
            'our_number': '2024-NEW-2',
            'title': 'كتاب مع سجل',
            'date': '2024-03-02',
            'kind': 'incoming_internal',
        })
        self.assertEqual(resp.status_code, 201)
        book_id = resp.json()['book_id']
        self.assertTrue(
            BookHistory.objects.filter(book_id=book_id, action='create').exists()
        )

    def test_issuing_entity_by_id(self):
        self._login()
        resp = self._post({
            'our_number': '2024-ENTITY-1',
            'title': 'كتاب مع جهة',
            'date': '2024-04-01',
            'kind': 'incoming_internal',
            'issuing_entity_ids[]': [self.entity.pk],
        })
        self.assertEqual(resp.status_code, 201)
        book = Book.objects.get(pk=resp.json()['book_id'])
        self.assertIn(self.entity, book.issuing_entities.all())

    def test_new_entity_created_on_save(self):
        self._login()
        resp = self._post({
            'our_number': '2024-ENTITY-2',
            'title': 'كتاب جهة جديدة',
            'date': '2024-04-02',
            'kind': 'incoming_internal',
            'issuing_entity_new[]': ['جهة جديدة تماماً'],
        })
        self.assertEqual(resp.status_code, 201)
        self.assertTrue(Entity.objects.filter(name__iexact='جهة جديدة تماماً').exists())


# ===========================================================================
# books_api.py — api_delete_book
# ===========================================================================

class DeleteBookAPITests(BookViewsBase):

    def _url(self, book_id):
        return reverse('api_delete_book', args=[book_id])

    def test_login_required(self):
        resp = self.client.post(self._url(self.book.pk))
        self.assertIn(resp.status_code, [302, 403])

    def test_get_not_allowed(self):
        self._login()
        resp = self.client.get(self._url(self.book.pk))
        self.assertEqual(resp.status_code, 405)

    def test_unauthorized_user_gets_403(self):
        self._login(self.other)
        resp = self.client.post(self._url(self.book.pk))
        self.assertEqual(resp.status_code, 403)

    def test_owner_can_soft_delete(self):
        self._login()
        resp = self.client.post(self._url(self.book.pk))
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()['success'])
        self.book.refresh_from_db()
        self.assertTrue(self.book.is_deleted)

    def test_superuser_can_delete_any(self):
        self._login(self.superuser)
        resp = self.client.post(self._url(self.other_book.pk))
        self.assertEqual(resp.status_code, 200)
        self.other_book.refresh_from_db()
        self.assertTrue(self.other_book.is_deleted)

    def test_delete_creates_history(self):
        self._login()
        self.client.post(self._url(self.book.pk))
        self.assertTrue(
            BookHistory.objects.filter(book=self.book, action='delete').exists()
        )

    def test_404_for_nonexistent_book(self):
        self._login(self.superuser)
        resp = self.client.post(self._url(99999))
        self.assertEqual(resp.status_code, 404)


# ===========================================================================
# books_api.py — api_bulk_delete_books
# ===========================================================================

class BulkDeleteBooksTests(BookViewsBase):

    URL = 'api_bulk_delete_books'

    def _post(self, book_ids):
        return self.client.post(
            reverse(self.URL),
            data=json.dumps({'book_ids': book_ids}),
            content_type='application/json',
        )

    def test_login_required(self):
        resp = self._post([self.book.pk])
        self.assertIn(resp.status_code, [302, 403])

    def test_empty_ids_returns_400(self):
        self._login()
        resp = self._post([])
        self.assertEqual(resp.status_code, 400)

    def test_owner_can_bulk_delete_own_books(self):
        self._login()
        resp = self._post([self.book.pk])
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data['success'])
        self.assertEqual(data['deleted_count'], 1)
        self.book.refresh_from_db()
        self.assertTrue(self.book.is_deleted)

    def test_non_owner_cannot_delete_others_books(self):
        self._login()
        resp = self._post([self.other_book.pk])
        data = resp.json()
        self.assertEqual(data['deleted_count'], 0)
        self.other_book.refresh_from_db()
        self.assertFalse(self.other_book.is_deleted)

    def test_superuser_deletes_any(self):
        self._login(self.superuser)
        resp = self._post([self.book.pk, self.other_book.pk])
        data = resp.json()
        self.assertEqual(data['deleted_count'], 2)


# ===========================================================================
# books_api.py — api_bulk_update_status_books
# ===========================================================================

class BulkUpdateStatusTests(BookViewsBase):

    URL = 'api_bulk_update_status_books'

    def _post(self, book_ids, status):
        return self.client.post(
            reverse(self.URL),
            data=json.dumps({'book_ids': book_ids, 'status': status}),
            content_type='application/json',
        )

    def test_login_required(self):
        resp = self._post([self.book.pk], 'done')
        self.assertIn(resp.status_code, [302, 403])

    def test_invalid_status_returns_400(self):
        self._login()
        resp = self._post([self.book.pk], 'invalid_status')
        self.assertEqual(resp.status_code, 400)

    def test_empty_ids_returns_400(self):
        self._login()
        resp = self._post([], 'done')
        self.assertEqual(resp.status_code, 400)

    def test_valid_status_update(self):
        """أرشفة الكتاب (إنهاء المتابعة)."""
        self._login()
        resp = self._post([self.book.pk], 'archived')
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data['success'])
        self.assertEqual(data['updated_count'], 1)
        self.book.refresh_from_db()
        self.assertTrue(self.book.is_archived)
        self.assertEqual(self.book.followup_state, 'archived')

    def test_non_integer_ids_returns_400(self):
        self._login()
        resp = self._post(['notanint'], 'archived')
        self.assertEqual(resp.status_code, 400)

    def test_same_status_not_counted_as_update(self):
        """الكتاب الافتراضي قيد المتابعة (is_archived=False)؛ 'reopen' لا يغيّر شيئاً."""
        self._login()
        resp = self._post([self.book.pk], 'reopen')
        data = resp.json()
        self.assertEqual(data['updated_count'], 0)


# ===========================================================================
# books_api.py — api_undo_delete_book
# ===========================================================================

class UndoDeleteBookTests(BookViewsBase):

    def setUp(self):
        super().setUp()
        # soft-delete the book first
        self.book.is_deleted = True
        self.book.deleted_at = timezone.now()
        self.book.deleted_by = self.user
        self.book.save()

    def _url(self, book_id):
        return reverse('api_undo_delete_book', args=[book_id])

    def test_login_required(self):
        resp = self.client.post(self._url(self.book.pk))
        self.assertIn(resp.status_code, [302, 403])

    def test_get_not_allowed(self):
        self._login()
        resp = self.client.get(self._url(self.book.pk))
        self.assertEqual(resp.status_code, 405)

    def test_unauthorized_gets_403(self):
        self._login(self.other)
        resp = self.client.post(self._url(self.book.pk))
        self.assertEqual(resp.status_code, 403)

    def test_owner_restores_book(self):
        self._login()
        resp = self.client.post(self._url(self.book.pk))
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()['success'])
        self.book.refresh_from_db()
        self.assertFalse(self.book.is_deleted)
        self.assertIsNone(self.book.deleted_at)

    def test_restore_creates_history(self):
        self._login()
        self.client.post(self._url(self.book.pk))
        self.assertTrue(
            BookHistory.objects.filter(book=self.book, action='restore').exists()
        )


# ===========================================================================
# books_api.py — api_book_detail_json
# ===========================================================================

class BookDetailJSONTests(BookViewsBase):

    def _url(self, pk):
        return reverse('api_book_detail_json', args=[pk])

    def test_login_required(self):
        resp = self.client.get(self._url(self.book.pk))
        self.assertIn(resp.status_code, [302, 403])

    def test_unauthorized_gets_403(self):
        self._login(self.other)
        resp = self.client.get(self._url(self.book.pk))
        self.assertEqual(resp.status_code, 403)

    def test_nonexistent_gets_404(self):
        self._login(self.superuser)
        resp = self.client.get(self._url(99999))
        self.assertEqual(resp.status_code, 404)

    def test_returns_correct_json_fields(self):
        self._login()
        resp = self.client.get(self._url(self.book.pk))
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        for field in ['id', 'our_number', 'title', 'kind', 'date', 'followup_state',
                      'is_archived', 'followup_label',
                      'issuing_entities', 'receiving_entities', 'attachments',
                      'edit_url', 'detail_url']:
            self.assertIn(field, data, f"Missing field: {field}")
        self.assertEqual(data['id'], self.book.pk)
        self.assertEqual(data['our_number'], '2024-001')

    def test_inline_status_url_present(self):
        self._login()
        data = self.client.get(self._url(self.book.pk)).json()
        self.assertIn('inline_status_url', data)
        self.assertEqual(
            data['inline_status_url'],
            reverse('api_book_inline_status', args=[self.book.pk]),
        )


# ===========================================================================
# books_api.py — api_book_detail_json attachment hints (Phase 1 inline preview)
# ===========================================================================

@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class BookDetailJSONAttachmentTests(BookViewsBase):
    """تلميحات المرفقات (is_pdf/is_image/content_type/is_primary) للعرض المضمّن."""

    def _url(self, pk):
        return reverse('api_book_detail_json', args=[pk])

    def _attach(self, name, content=b'data'):
        return Attachment.objects.create(
            book=self.book,
            file=SimpleUploadedFile(name, content),
        )

    def test_no_attachment_is_safe(self):
        self._login()
        resp = self.client.get(self._url(self.book.pk))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['attachments'], [])

    def test_pdf_attachment_hints(self):
        self._attach('letter.pdf', b'%PDF-1.4 test')
        self._login()
        att = self.client.get(self._url(self.book.pk)).json()['attachments'][0]
        self.assertTrue(att['is_pdf'])
        self.assertFalse(att['is_image'])
        self.assertTrue(att['is_primary'])
        self.assertEqual(att['content_type'], 'application/pdf')

    def test_image_attachment_hints(self):
        self._attach('scan.png', b'\x89PNG test')
        self._login()
        att = self.client.get(self._url(self.book.pk)).json()['attachments'][0]
        self.assertTrue(att['is_image'])
        self.assertFalse(att['is_pdf'])
        self.assertTrue(att['is_primary'])

    def test_pdf_preferred_as_primary_over_image(self):
        self._attach('scan.png', b'img')
        self._attach('letter.pdf', b'%PDF')
        self._login()
        atts = self.client.get(self._url(self.book.pk)).json()['attachments']
        primary = [a for a in atts if a['is_primary']]
        self.assertEqual(len(primary), 1)
        self.assertTrue(primary[0]['is_pdf'])


# ===========================================================================
# books_api.py — api_book_inline_status
# ===========================================================================

class InlineStatusTests(BookViewsBase):

    def _url(self, pk):
        return reverse('api_book_inline_status', args=[pk])

    def _post(self, pk, status, user=None):
        self._login(user)
        return self.client.post(
            self._url(pk),
            data=json.dumps({'status': status}),
            content_type='application/json',
        )

    def test_login_required(self):
        resp = self.client.post(self._url(self.book.pk))
        self.assertIn(resp.status_code, [302, 403])

    def test_get_not_allowed(self):
        self._login()
        resp = self.client.get(self._url(self.book.pk))
        self.assertEqual(resp.status_code, 405)

    def test_invalid_status_returns_400(self):
        resp = self._post(self.book.pk, 'bad_status')
        self.assertEqual(resp.status_code, 400)

    def test_unauthorized_returns_403(self):
        resp = self._post(self.book.pk, 'archived', user=self.other)
        self.assertEqual(resp.status_code, 403)

    def test_valid_update_returns_success(self):
        """أرشفة الكتاب القائم (قيد المتابعة) — يصبح مؤرشفاً."""
        resp = self._post(self.book.pk, 'archived')
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data['success'])
        self.assertEqual(data['followup_state'], 'archived')
        self.book.refresh_from_db()
        self.assertTrue(self.book.is_archived)

    def test_same_status_no_history_created(self):
        """الكتاب قيد المتابعة بالفعل؛ 'reopen' لا يضيف سجل تاريخ."""
        before = BookHistory.objects.filter(book=self.book, action='status').count()
        self._post(self.book.pk, 'reopen')
        after = BookHistory.objects.filter(book=self.book, action='status').count()
        self.assertEqual(before, after)


# ===========================================================================
# books_list.py — book_unified
# ===========================================================================

class AttachmentOcrTextTests(BookViewsBase):
    """عقد نقطة نصّ OCR للمرفق (يعتمد عليها العارض المضمّن في صفحة التفاصيل)."""

    def _att(self):
        return Attachment.objects.create(book=self.book)

    def _url(self, att_id):
        return reverse('attachment_ocr_text', args=[att_id])

    def test_login_required(self):
        att = self._att()
        resp = self.client.get(self._url(att.id))
        self.assertIn(resp.status_code, [302, 403])

    def test_returns_ocr_text_and_confidence(self):
        att = self._att()
        OCRResult.objects.create(attachment=att, cleaned_text='النص المنظّف', confidence_score=88.0)
        self._login()
        data = self.client.get(self._url(att.id)).json()
        self.assertEqual(data['status'], 'ok')
        self.assertTrue(data['has_text'])
        self.assertEqual(data['text'], 'النص المنظّف')
        self.assertEqual(data['confidence'], 88.0)

    def test_prefers_cleaned_over_raw(self):
        att = self._att()
        OCRResult.objects.create(attachment=att, raw_text='خام', cleaned_text='منظّف')
        self._login()
        self.assertEqual(self.client.get(self._url(att.id)).json()['text'], 'منظّف')

    def test_no_ocr_returns_has_text_false(self):
        att = self._att()
        self._login()
        data = self.client.get(self._url(att.id)).json()
        self.assertEqual(data['status'], 'ok')
        self.assertFalse(data['has_text'])
        self.assertEqual(data['text'], '')

    def test_unauthorized_403(self):
        att = self._att()
        self._login(self.other)
        resp = self.client.get(self._url(att.id))
        self.assertEqual(resp.status_code, 403)


class CommentNotesAPITests(BookViewsBase):
    """عقود نقاط التعليقات/الملاحظات التي يعتمد عليها static/book_detail.js."""

    # ── notes ──
    def test_update_notes_saves_and_logs(self):
        self._login()
        url = reverse('update_book_notes', args=[self.book.pk])
        resp = self.client.post(url, data=json.dumps({'margin': 'هامش جديد'}),
                                content_type='application/json')
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data['status'], 'ok')
        self.assertEqual(data['margin'], 'هامش جديد')
        self.book.refresh_from_db()
        self.assertEqual(self.book.margin, 'هامش جديد')
        self.assertTrue(BookHistory.objects.filter(book=self.book, action='update_notes').exists())

    def test_update_notes_unauthorized_403(self):
        self._login(self.other)
        url = reverse('update_book_notes', args=[self.book.pk])
        resp = self.client.post(url, data=json.dumps({'margin': 'x'}),
                                content_type='application/json')
        self.assertEqual(resp.status_code, 403)

    # ── comments ──
    def test_add_comment_returns_comment_shape(self):
        self._login()
        url = reverse('add_book_comment', args=[self.book.pk])
        resp = self.client.post(url, data=json.dumps({'content': 'تعليق'}),
                                content_type='application/json')
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data['status'], 'ok')
        for field in ['id', 'content', 'created_by', 'created_at', 'is_edited']:
            self.assertIn(field, data['comment'], f"Missing comment field: {field}")
        self.assertEqual(data['comment']['content'], 'تعليق')

    def test_add_empty_comment_400(self):
        self._login()
        url = reverse('add_book_comment', args=[self.book.pk])
        resp = self.client.post(url, data=json.dumps({'content': '   '}),
                                content_type='application/json')
        self.assertEqual(resp.status_code, 400)

    def test_add_comment_unauthorized_403(self):
        self._login(self.other)
        url = reverse('add_book_comment', args=[self.book.pk])
        resp = self.client.post(url, data=json.dumps({'content': 'x'}),
                                content_type='application/json')
        self.assertEqual(resp.status_code, 403)

    def test_edit_own_comment_sets_is_edited(self):
        c = BookComment.objects.create(book=self.book, created_by=self.user, content='قديم')
        self._login()
        url = reverse('edit_book_comment', args=[c.pk])
        resp = self.client.post(url, data=json.dumps({'content': 'محدّث'}),
                                content_type='application/json')
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data['comment']['is_edited'])
        c.refresh_from_db()
        self.assertEqual(c.content, 'محدّث')

    def test_edit_others_comment_403(self):
        c = BookComment.objects.create(book=self.book, created_by=self.user, content='قديم')
        self._login(self.other)
        url = reverse('edit_book_comment', args=[c.pk])
        resp = self.client.post(url, data=json.dumps({'content': 'x'}),
                                content_type='application/json')
        self.assertEqual(resp.status_code, 403)

    def test_delete_own_comment(self):
        c = BookComment.objects.create(book=self.book, created_by=self.user, content='احذفني')
        self._login()
        url = reverse('delete_book_comment', args=[c.pk])
        resp = self.client.post(url)
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(BookComment.objects.filter(pk=c.pk).exists())


class BookUnifiedTests(BookViewsBase):

    URL = 'book_unified'

    def test_login_required(self):
        resp = self.client.get(reverse(self.URL))
        self.assertEqual(resp.status_code, 302)

    def test_renders_for_owner(self):
        self._login()
        resp = self.client.get(reverse(self.URL))
        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(resp, 'core/book_unified.html')

    def test_context_contains_books(self):
        self._login()
        resp = self.client.get(reverse(self.URL))
        self.assertIn('books', resp.context)

    def test_owner_sees_only_own_books(self):
        self._login()
        resp = self.client.get(reverse(self.URL))
        books = resp.context['books']
        ids = [b.id for b in books]
        self.assertIn(self.book.pk, ids)
        self.assertNotIn(self.other_book.pk, ids)

    def test_superuser_sees_all_books(self):
        self._login(self.superuser)
        resp = self.client.get(reverse(self.URL), {'tab': 'all'})
        books = resp.context['books']
        ids = [b.id for b in books]
        self.assertIn(self.book.pk, ids)
        self.assertIn(self.other_book.pk, ids)

    def test_search_filter(self):
        self._login(self.superuser)
        resp = self.client.get(reverse(self.URL), {'q': 'تجريبي'})
        self.assertEqual(resp.status_code, 200)
        books = resp.context['books']
        self.assertTrue(all('تجريبي' in b.title for b in books))

    def test_deleted_books_not_shown(self):
        self._login()
        self.book.is_deleted = True
        self.book.save()
        resp = self.client.get(reverse(self.URL))
        ids = [b.id for b in resp.context['books']]
        self.assertNotIn(self.book.pk, ids)


# ===========================================================================
# books_list.py — api_unified_data
# ===========================================================================

class ApiUnifiedDataTests(BookViewsBase):

    URL = 'api_unified_data'

    def test_login_required(self):
        resp = self.client.get(reverse(self.URL))
        self.assertEqual(resp.status_code, 302)

    def test_returns_json(self):
        self._login()
        resp = self.client.get(reverse(self.URL))
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn('books', data)
        self.assertIn('pagination', data)

    def test_pagination_structure(self):
        self._login()
        resp = self.client.get(reverse(self.URL))
        pagination = resp.json()['pagination']
        for key in ['current', 'total', 'count', 'per_page', 'has_next', 'has_prev']:
            self.assertIn(key, pagination)

    def test_book_fields_in_response(self):
        self._login()
        resp = self.client.get(reverse(self.URL))
        books = resp.json()['books']
        if books:
            book = books[0]
            for field in ['id', 'our_number', 'title', 'kind', 'status', 'urls']:
                self.assertIn(field, book)

    def test_attachment_url_in_response_without_attachment(self):
        """Test that attachment_url is present in response (None when no attachment)"""
        self._login()
        resp = self.client.get(reverse(self.URL))
        books = resp.json()['books']
        if books:
            book = books[0]
            self.assertIn('attachment_url', book)
            self.assertIsNone(book['attachment_url'])

    def test_attachment_url_in_response_with_attachment(self):
        """Test that attachment_url contains proper file URL when attachment exists"""
        from io import BytesIO
        from django.core.files.uploadedfile import SimpleUploadedFile
        
        # Create an attachment for the book
        pdf_content = b'%PDF-1.4\n%%EOF'
        pdf_file = SimpleUploadedFile('test.pdf', pdf_content, content_type='application/pdf')
        attachment = Attachment.objects.create(book=self.book, file=pdf_file)
        
        self._login()
        resp = self.client.get(reverse(self.URL))
        books = resp.json()['books']
        
        # Find our book in the response
        our_book = None
        for b in books:
            if b['id'] == self.book.id:
                our_book = b
                break
        
        self.assertIsNotNone(our_book, "Book not found in response")
        self.assertIn('attachment_url', our_book, "attachment_url field missing from response")
        
        # Debug output
        print(f"\n--- DEBUG: Attachment URL Test ---")
        print(f"Book ID: {self.book.id}")
        print(f"Response Book ID: {our_book['id']}")
        print(f"Attachment URL: {our_book['attachment_url']}")
        print(f"All book fields: {list(our_book.keys())}")
        print(f"--- END DEBUG ---\n")
        
        self.assertIsNotNone(our_book['attachment_url'], "attachment_url should not be None when attachment exists")
        self.assertTrue(
            our_book['attachment_url'].endswith('.pdf'),
            f"Expected PDF URL, got: {our_book['attachment_url']}"
        )


# ===========================================================================
# books_list.py — trash_list
# ===========================================================================

class TrashListTests(BookViewsBase):

    URL = 'trash_list'

    def setUp(self):
        super().setUp()
        self.book.is_deleted = True
        self.book.deleted_at = timezone.now()
        self.book.save()

    def test_login_required(self):
        resp = self.client.get(reverse(self.URL))
        self.assertEqual(resp.status_code, 302)

    def test_renders_trash(self):
        self._login()
        resp = self.client.get(reverse(self.URL))
        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(resp, 'core/trash.html')

    def test_owner_sees_own_deleted_books(self):
        self._login()
        resp = self.client.get(reverse(self.URL))
        ids = [b.id for b in resp.context['deleted_books']]
        self.assertIn(self.book.pk, ids)

    def test_owner_does_not_see_others_deleted_books(self):
        # soft-delete other_book
        self.other_book.is_deleted = True
        self.other_book.save()
        self._login()
        resp = self.client.get(reverse(self.URL))
        ids = [b.id for b in resp.context['deleted_books']]
        self.assertNotIn(self.other_book.pk, ids)

    def test_superuser_sees_all_deleted(self):
        self.other_book.is_deleted = True
        self.other_book.save()
        self._login(self.superuser)
        resp = self.client.get(reverse(self.URL))
        ids = [b.id for b in resp.context['deleted_books']]
        self.assertIn(self.book.pk, ids)
        self.assertIn(self.other_book.pk, ids)


# ===========================================================================
# books_detail.py — book_detail
# ===========================================================================

class BookDetailTests(BookViewsBase):

    def _url(self, pk):
        return reverse('book_detail', args=[pk])

    def test_login_required(self):
        resp = self.client.get(self._url(self.book.pk))
        self.assertEqual(resp.status_code, 302)

    def test_owner_can_view(self):
        self._login()
        resp = self.client.get(self._url(self.book.pk))
        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(resp, 'core/book_detail.html')

    def test_unauthorized_gets_403(self):
        self._login(self.other)
        from django.core.exceptions import PermissionDenied
        resp = self.client.get(self._url(self.book.pk))
        self.assertEqual(resp.status_code, 403)

    def test_superuser_can_view_any(self):
        self._login(self.superuser)
        resp = self.client.get(self._url(self.other_book.pk))
        self.assertEqual(resp.status_code, 200)

    def test_deleted_book_returns_404(self):
        self.book.is_deleted = True
        self.book.save()
        self._login()
        resp = self.client.get(self._url(self.book.pk))
        self.assertEqual(resp.status_code, 404)

    def test_context_contains_book(self):
        self._login()
        resp = self.client.get(self._url(self.book.pk))
        self.assertEqual(resp.context['book'].pk, self.book.pk)


# ===========================================================================
# books_detail.py — book_edit
# ===========================================================================

class BookEditTests(BookViewsBase):

    def _url(self, pk):
        return reverse('book_edit', args=[pk])

    def _update_url(self):
        return reverse('update-book-api')

    def test_login_required(self):
        resp = self.client.get(self._url(self.book.pk))
        self.assertEqual(resp.status_code, 302)

    def test_owner_get_redirects_to_smart_desktop(self):
        """book_edit GET يُعيد توجيهاً للواجهة الذكية مع edit_pk."""
        self._login()
        resp = self.client.get(self._url(self.book.pk))
        self.assertEqual(resp.status_code, 302)
        location = resp['Location']
        self.assertIn('smart-desktop', location)
        self.assertIn(f'edit_pk={self.book.pk}', location)

    def test_unauthorized_gets_403(self):
        self._login(self.other)
        resp = self.client.get(self._url(self.book.pk))
        self.assertEqual(resp.status_code, 403)

    def _entity_payload(self):
        """إنشاء جهة مستقبلة للاستخدام في اختبارات update_book_api."""
        from core.models import Entity
        receiver = Entity.objects.get_or_create(
            name='جهة مستقبلة', defaults={'code': 'RCV', 'etype': 'receiver', 'is_active': True}
        )[0]
        return {
            'issuing_entity_ids[]': [self.entity.pk],
            'receiving_entity_ids[]': [receiver.pk],
        }

    def test_update_api_updates_book(self):
        """update_book_api يحدّث بيانات الكتاب."""
        self._login()
        payload = {'edit_pk': self.book.pk, 'title': 'عنوان معدّل', 'date': '2024-01-15', 'secret_level': 'normal'}
        payload.update(self._entity_payload())
        resp = self.client.post(self._update_url(), payload)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()['success'])
        self.book.refresh_from_db()
        self.assertEqual(self.book.title, 'عنوان معدّل')

    def test_update_api_creates_history(self):
        """update_book_api يسجّل تاريخ التعديل."""
        self._login()
        payload = {'edit_pk': self.book.pk, 'title': 'عنوان معدّل 2', 'date': '2024-01-15', 'secret_level': 'normal'}
        payload.update(self._entity_payload())
        self.client.post(self._update_url(), payload)
        self.assertTrue(BookHistory.objects.filter(book=self.book, action='edit').exists())

    def test_update_api_unauthorized_returns_403(self):
        """update_book_api يرفض الطلب غير المُخوَّل."""
        self._login(self.other)
        resp = self.client.post(self._update_url(), {
            'edit_pk': self.book.pk, 'title': 'محاولة اختراق', 'date': '2024-01-15', 'secret_level': 'normal',
        })
        self.assertEqual(resp.status_code, 403)

    def test_update_api_file_replaces_only_targeted_attachment(self):
        """رفع ملف في التعديل يستبدل المرفق المستهدَف (attachment_id) فقط
        ولا يؤرشف بقية مرفقات الكتاب (إصلاح استبدال-الكل)."""
        from core.models import Attachment
        pdf = b'%PDF-1.4\n%%EOF'
        att1 = Attachment.objects.create(
            book=self.book, file=SimpleUploadedFile('a1.pdf', pdf, content_type='application/pdf'))
        att2 = Attachment.objects.create(
            book=self.book, file=SimpleUploadedFile('a2.pdf', pdf, content_type='application/pdf'))

        self._login()
        payload = {
            'edit_pk': self.book.pk, 'title': 'تعديل مع ملف', 'date': '2024-01-15',
            'secret_level': 'normal', 'attachment_id': att1.pk,
            'file': SimpleUploadedFile('new.pdf', pdf, content_type='application/pdf'),
        }
        payload.update(self._entity_payload())
        resp = self.client.post(self._update_url(), payload)
        self.assertEqual(resp.status_code, 200, resp.content)

        att1.refresh_from_db()
        att2.refresh_from_db()
        self.assertTrue(att1.is_deleted, 'المرفق المستهدَف يجب أن يُؤرشف')
        self.assertFalse(att2.is_deleted, 'المرفق غير المستهدَف يجب أن يبقى نشطاً (لا استبدال-كل)')
        active = self.book.attachments.filter(is_deleted=False)
        # المتبقّي: att2 + المرفق الجديد
        self.assertEqual(active.count(), 2)
        self.assertTrue(active.exclude(pk=att2.pk).exists(), 'يجب إنشاء مرفق جديد للملف المرفوع')


# ===========================================================================
# books_detail.py — book_change_status
# ===========================================================================

class BookChangeStatusTests(BookViewsBase):

    def _url(self, pk):
        return reverse('book_change_status', args=[pk])

    def test_login_required(self):
        resp = self.client.post(self._url(self.book.pk), {'action': 'archived'})
        self.assertEqual(resp.status_code, 302)  # redirect to login

    def test_unauthorized_redirects_with_error(self):
        self._login(self.other)
        self.client.post(self._url(self.book.pk), {'action': 'archived'}, follow=True)
        self.book.refresh_from_db()
        self.assertFalse(self.book.is_archived)  # لم يتغيّر

    def test_valid_archive_action(self):
        """أرشفة الكتاب (قيد المتابعة → مؤرشف)."""
        self._login()
        resp = self.client.post(self._url(self.book.pk), {'action': 'archived'})
        self.assertRedirects(resp, reverse('book_detail', args=[self.book.pk]))
        self.book.refresh_from_db()
        self.assertTrue(self.book.is_archived)

    def test_invalid_action_not_applied(self):
        self._login()
        old = self.book.is_archived
        self.client.post(self._url(self.book.pk), {'action': 'invalid_xyz'})
        self.book.refresh_from_db()
        self.assertEqual(self.book.is_archived, old)

    def test_status_change_creates_history(self):
        self._login()
        self.client.post(self._url(self.book.pk), {'action': 'archived'})
        self.assertTrue(
            BookHistory.objects.filter(book=self.book, action='status').exists()
        )


# ===========================================================================
# books_helpers.py — _normalize_secret_level_value, _resolve_entities
# ===========================================================================

class HelpersTests(TestCase):

    def test_normalize_empty_is_normal(self):
        from .views.books_helpers import _normalize_secret_level_value
        self.assertEqual(_normalize_secret_level_value(''), 'normal')
        self.assertEqual(_normalize_secret_level_value(None), 'normal')

    def test_normalize_aliases(self):
        from .views.books_helpers import _normalize_secret_level_value
        self.assertEqual(_normalize_secret_level_value('confidential'), 'secret')
        self.assertEqual(_normalize_secret_level_value('top_secret'), 'topsecret')
        self.assertEqual(_normalize_secret_level_value('NORMAL'), 'normal')

    def test_resolve_entities_by_id(self):
        from .views.books_helpers import _resolve_entities
        entity = Entity.objects.create(name='جهة 1', etype='issuer', is_active=True)
        result = _resolve_entities([entity.pk], [], 'issuer')
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].pk, entity.pk)

    def test_resolve_entities_creates_new(self):
        from .views.books_helpers import _resolve_entities
        result = _resolve_entities([], ['جهة مُنشأة'], 'issuer')
        self.assertEqual(len(result), 1)
        self.assertTrue(Entity.objects.filter(name__iexact='جهة مُنشأة').exists())

    def test_resolve_entities_deduplicates(self):
        from .views.books_helpers import _resolve_entities
        entity = Entity.objects.create(name='جهة مكررة', etype='issuer', is_active=True)
        result = _resolve_entities([entity.pk, entity.pk], [], 'issuer')
        self.assertEqual(len(result), 1)

    def test_resolve_entities_activates_inactive(self):
        from .views.books_helpers import _resolve_entities
        entity = Entity.objects.create(name='جهة غير نشطة', etype='issuer', is_active=False)
        _resolve_entities([entity.pk], [], 'issuer')
        entity.refresh_from_db()
        self.assertTrue(entity.is_active)
