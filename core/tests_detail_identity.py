"""حرّاسُ «ملفّ الكتاب» على الهويّة الموحّدة (11-12).

١. **ملفٌّ غائبٌ عن التخزين لا يُسقط الصفحة**: كان ``{{ att.file.size }}`` يرفع FileNotFoundError
   فتسقط تفاصيلُ الكتاب كلُّها بـ500 (الكتاب 3914 على قاعدة التطوير)، والعارضُ وقصاصةُ الهامش
   يطلبان الملفَّ الغائب. المصدرُ الواحد ``core.file_presence.stored_size`` للقالب والعرض معاً.
٢. **الوضعان من الرموز**: رموزُ ‎--bx-*‎ على ‎--lx-*‎، ولا كتلةَ داكنٍ على سمة الوضع القديم المحذوف؛
   ورموزُ ‎.lc-scope‎ تُربط في v2 وحدَها (الكتابُ السرّيّ لم يُنقل بعد).
"""
import re
from pathlib import Path

from django.conf import settings
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from core.file_presence import stored_size
from core.models import Attachment, Book
from core.testing import as_writer

ROOT = Path(settings.BASE_DIR)
MISSING = 'الملفُّ غيرُ موجود في التخزين'


def _read(rel):
    return (ROOT / rel).read_text(encoding='utf-8')


class MissingFileTests(TestCase):

    def setUp(self):
        self.user = as_writer(User.objects.create_user('bdx', password='pw-bdx-11', is_staff=True))
        self.book = Book.objects.create(kind='incoming_internal', title='ملفٌّ غائب', created_by=self.user)
        self.client.force_login(self.user)

    def _get(self):
        return self.client.get(reverse('book_detail', args=[self.book.pk]))

    def test_a_missing_file_says_so_instead_of_a_500(self):
        Attachment.objects.create(book=self.book, file='books/2026/never-there.pdf')
        r = self._get()
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, MISSING)
        self.assertNotContains(r, 'preview-btn')
        self.assertEqual(r.context['attachment_series'], [])
        self.assertIsNone(r.context['crop_source'])

    def test_a_present_file_keeps_its_viewer_and_crop(self):
        Attachment.objects.create(book=self.book, file='books/2026/never-there.pdf')
        att = Attachment.objects.create(book=self.book, file=SimpleUploadedFile('here.pdf', b'%PDF-1.4'))
        r = self._get()
        self.assertContains(r, 'preview-btn', count=1)
        self.assertEqual([s['id'] for s in r.context['attachment_series']], [att.pk])
        self.assertEqual(r.context['crop_source'], att)

    def test_the_page_is_migrated(self):
        self.assertContains(self._get(), 'data-lx-page="v2"')


class StoredSizeTests(TestCase):

    def test_none_for_no_file_or_a_missing_one_and_the_size_otherwise(self):
        book = Book.objects.create(kind='incoming_internal', title='حجم',
                                   created_by=User.objects.create_user('bdz', password='pw-bdz-11'))
        self.assertIsNone(stored_size(Attachment(book=book).file))
        self.assertIsNone(stored_size(Attachment.objects.create(book=book, file='books/x/none.pdf').file))
        here = Attachment.objects.create(book=book, file=SimpleUploadedFile('a.pdf', b'%PDF-1.4'))
        self.assertEqual(stored_size(here.file), 8)


class DetailStylesheetTests(SimpleTestCase):

    def test_page_tokens_read_the_identity_and_the_dead_dark_block_is_gone(self):
        css = _read('static/css/book_detail_v2.css')
        self.assertNotIn('[data-theme="dark"] .bx', css)
        self.assertNotIn('[data-theme="dark"] .bx-btn', css)
        block = css[css.index('.bx {\n'):css.index('}', css.index('.bx {\n'))]
        tokens = dict(re.findall(r'(--bx-[\w-]+):\s*([^;]+);', block))
        self.assertGreaterEqual(len(tokens), 15)
        for name, value in tokens.items():
            with self.subTest(token=name):
                self.assertIn('var(--lx-', value)

    def test_filled_controls_use_the_fill_and_its_ink(self):
        css = _read('static/css/book_detail_v2.css')
        for rule in ('.bx-step.now i.n', '.bx-btn--primary'):
            with self.subTest(rule=rule):
                body = css[css.index(rule):css.index('}', css.index(rule))]
                self.assertIn('var(--lx-pri-fill)', body)
                self.assertIn('var(--lx-pri-fill-ink)', body)

    def test_lifecycle_tokens_move_only_inside_v2(self):
        css = _read('static/css/lifecycle_design.css')
        self.assertIn('--amber:      #b45309;', css)        # الصفحاتُ غيرُ المنقولة على حالها
        block = css[css.index('html[data-lx-page="v2"] .lc-scope {'):]
        block = block[:block.index('}')]
        self.assertIn('--amber: var(--lx-pri);', block)
        self.assertIn('--paper: var(--lx-surface);', block)

    def test_the_crop_stage_has_no_inline_colours(self):
        src = _read('templates/core/_lifecycle_dialogs.html')
        stage = src[src.index('data-crop-stage'):src.index('data-crop-value')]
        self.assertNotRegex(stage, r'#[0-9a-fA-F]{3,6}\b|rgba\(')
