"""
الحذف الناعم افتراضاً — اختبارات انحدار لسجلّ العيوب ح4.

قبل هذه الدفعة: صفر managers مخصّصة، و`is_deleted=False` مكتوبة يدويّاً 73 مرّة.
أيّ استعلامٍ ينسى الشرط يُظهر ما حُذف — فشلٌ صامت لا يُخطئ بل يُسرّب.
"""

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.utils import timezone

from core.models import Attachment, Book


class SoftDeleteManagerTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user('owner', password='pw-owner-11')
        cls.live = Book.objects.create(kind='incoming_internal', title='كتاب حيّ', created_by=cls.user)
        cls.gone = Book.objects.create(
            kind='incoming_internal', title='كتاب محذوف', created_by=cls.user,
            is_deleted=True, deleted_at=timezone.now(),
        )

    def test_default_manager_hides_deleted(self):
        titles = set(Book.objects.values_list('title', flat=True))
        self.assertIn('كتاب حيّ', titles)
        self.assertNotIn('كتاب محذوف', titles, 'المحذوف ظهر في المدير الافتراضي')

    def test_all_objects_is_the_explicit_escape_hatch(self):
        self.assertEqual(Book.all_objects.count(), 2)
        self.assertEqual(Book.all_objects.filter(is_deleted=True).count(), 1)

    def test_get_on_deleted_raises_through_default_manager(self):
        with self.assertRaises(Book.DoesNotExist):
            Book.objects.get(pk=self.gone.pk)
        self.assertEqual(Book.all_objects.get(pk=self.gone.pk).pk, self.gone.pk)

    def test_reverse_relation_hides_deleted_attachments(self):
        """‏book.attachments لا يُظهر المرفق المحذوف — العلاقة العكسيّة تتبع الافتراضيّ."""
        Attachment.objects.create(
            book=self.live, file=SimpleUploadedFile('a.pdf', b'%PDF-1.4'),
        )
        Attachment.objects.create(
            book=self.live, file=SimpleUploadedFile('b.pdf', b'%PDF-1.4'),
            is_deleted=True, deleted_at=timezone.now(),
        )
        self.assertEqual(self.live.attachments.count(), 1, 'المرفق المحذوف ظهر في العلاقة العكسيّة')
        self.assertEqual(Attachment.all_objects.filter(book=self.live).count(), 2)

    def test_forward_fk_to_deleted_book_still_resolves(self):
        """الفخّ الذي يكسر التطبيقات: اجتياز FK إلى صفٍّ محذوف يجب ألّا يرمي.

        جانغو يستعمل ``_base_manager`` (مديراً عاديّاً غير مُرشَّح) لهذا الاجتياز
        ما لم يُضبط ``Meta.base_manager_name`` — وهو ما لم نضبطه عمداً.
        """
        att = Attachment.objects.create(
            book=self.gone, file=SimpleUploadedFile('c.pdf', b'%PDF-1.4'),
        )
        fetched = Attachment.objects.get(pk=att.pk)
        self.assertEqual(fetched.book.pk, self.gone.pk)   # لا DoesNotExist


class TrashFlowStillWorksTests(TestCase):
    """المدير الجديد لا يعمي سلّة المحذوفات ولا الاستعادة."""

    def setUp(self):
        self.staff = User.objects.create_superuser('boss2', 'boss2@x.com', 'pw-boss-22')
        self.client.force_login(self.staff)
        self.book = Book.objects.create(
            kind='incoming_internal', title='للحذف', created_by=self.staff,
            is_deleted=True, deleted_at=timezone.now(),
        )

    def test_trash_page_lists_deleted_books(self):
        resp = self.client.get('/books/trash/')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'للحذف')

    def test_restore_brings_the_book_back(self):
        resp = self.client.post(f'/books/trash/book/{self.book.pk}/restore/')
        self.assertEqual(resp.status_code, 302, 'الاستعادة تُعيد التوجيه إلى السلّة')
        self.book.refresh_from_db()
        self.assertFalse(self.book.is_deleted)
        self.assertTrue(Book.objects.filter(pk=self.book.pk).exists())
