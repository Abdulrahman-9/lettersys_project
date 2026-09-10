# -*- coding: utf-8 -*-
"""حارسُ `purge_dev_seed_books` — التفريغُ يطال المحذوفَ ناعماً أيضاً.

**العطبُ الذي كشفته بروفةُ الخادم (2026-09-10)**: الأمرُ كان يعاين بـ`all_objects`
(فيعِد بحذف 129 مرفقاً) ثمّ يحذف بـ`objects` (فيحذف 117 فقط — المديرُ الافتراضيّ
يُخفي المحذوفَ ناعماً). المرفقاتُ الاثنا عشرَ الباقيةُ تحرس كتبَها عبر
``Attachment.book = PROTECT`` ⟵ ``ProtectedError`` والأمرُ كلُّه يتراجع. وكذلك
``Book.objects`` كان سيترك 32 كتابَ تدريبٍ محذوفاً ناعماً في القاعدة.

هذه الاختباراتُ تُثبّت الحالتَين معاً، وتحمرّان إن عاد أيُّ سطرٍ إلى `objects`.
"""

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from core.models import Attachment, Book


def _out():
    from io import StringIO
    return StringIO()


class PurgeDevSeedSoftDeletedTests(TestCase):
    """الكتبُ والمرفقاتُ المحذوفةُ ناعماً تُحذف مع غيرها، ولا تحجب."""

    def setUp(self):
        self.user = User.objects.create_user('purger', password='p')
        # كتابُ تدريبٍ ظاهر + مرفقٌ ظاهر
        self.live = self._book('T900')
        self.att_live = self._att(self.live, 'live.pdf')
        # كتابُ تدريبٍ ظاهر + مرفقٌ **محذوفٌ ناعماً** (هو الذي كان يحجب الحذف)
        self.guarded = self._book('T901')
        self.att_soft = self._att(self.guarded, 'soft.pdf')
        Attachment.all_objects.filter(pk=self.att_soft.pk).update(is_deleted=True)
        # كتابُ تدريبٍ **محذوفٌ ناعماً** (كان يبقى في القاعدة بعد التفريغ)
        self.soft_book = self._book('T902')
        Book.all_objects.filter(pk=self.soft_book.pk).update(is_deleted=True)
        # كتابٌ حقيقيٌّ لا يُمسّ
        self.keeper = self._book('2433', training=False)

    def _book(self, number, training=True):
        b = Book.objects.create(
            our_number=number,
            kind='incoming_internal',
            title='كتاب',
            date=timezone.now(),
            created_by=self.user,
        )
        if training:
            Book.all_objects.filter(pk=b.pk).update(is_training=True)
        return b

    def _att(self, book, name):
        return Attachment.objects.create(
            book=book,
            file=SimpleUploadedFile(name, b'%PDF-1.4 test', content_type='application/pdf'),
        )

    def test_purge_removes_training_books_including_soft_deleted(self):
        call_command('purge_dev_seed_books', '--yes', '--no-reseed', stdout=_out())

        self.assertEqual(
            Book.all_objects.filter(is_training=True).count(), 0,
            'بقيت كتبُ تدريبٍ بعد التفريغ — على الأرجح حُذف بـobjects لا all_objects',
        )
        self.assertEqual(
            Attachment.all_objects.filter(book_id__in=[self.live.pk, self.guarded.pk]).count(), 0,
            'بقيت مرفقاتُ كتب التدريب — المحذوفُ ناعماً لم يُحذف',
        )
        self.assertTrue(
            Book.all_objects.filter(pk=self.keeper.pk).exists(),
            'حُذف كتابٌ حقيقيٌّ — التفريغُ تجاوز نطاقَ is_training',
        )

    def test_soft_deleted_attachment_does_not_block_delete(self):
        """الطفرةُ الحاسمة: بـ`Attachment.objects` يرمي جانغو ProtectedError هنا."""
        call_command('purge_dev_seed_books', '--yes', '--no-reseed', stdout=_out())
        self.assertFalse(Attachment.all_objects.filter(pk=self.att_soft.pk).exists())
        self.assertFalse(Book.all_objects.filter(pk=self.guarded.pk).exists())

    def test_preview_count_matches_what_gets_deleted(self):
        """العددُ المعروضُ في المعاينة هو نفسُه المحذوفُ فعلاً (كان 129 مقابل 117)."""
        buf = _out()
        call_command('purge_dev_seed_books', stdout=buf)          # معاينةٌ فقط
        preview = buf.getvalue()
        self.assertIn('مرفقات ستُحذف', preview)
        promised = int([ln for ln in preview.splitlines() if 'مرفقات ستُحذف' in ln][0].split(':')[-1])

        before = Attachment.all_objects.count()
        call_command('purge_dev_seed_books', '--yes', '--no-reseed', stdout=_out())
        actually = before - Attachment.all_objects.count()

        self.assertEqual(promised, actually, 'وعدت المعاينةُ بعددٍ وحذف الأمرُ غيرَه')
