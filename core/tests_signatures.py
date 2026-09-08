# -*- coding: utf-8 -*-
"""حرّاسُ توقيع المصادقة — الحوكمةُ والبصمةُ وصفحةُ التحقّق."""

from django.contrib.auth.models import Group, User
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from core.models import (Attachment, Book, BookHistory, BookSignature,
                         Department, UserProfile)
from core.roles import CONTROLLER_GROUP_NAME
from core.signature_service import can_sign, revoke, sign_attachment, verify


def _pdf(pages=1):
    """مستندٌ صغيرٌ صالحٌ فعلاً — لا بايتاتٌ تدّعي أنّها PDF."""
    import fitz

    doc = fitz.open()
    for _ in range(pages):
        doc.new_page()
    data = doc.tobytes()
    doc.close()
    return data


def _member(name, department, *, head=False, controller=False, admin=False):
    if admin:
        user = User.objects.create_superuser(name, name + '@x.co', 'pw')
    else:
        user = User.objects.create_user(name, name + '@x.co', 'pw')
    UserProfile.objects.update_or_create(
        user=user, defaults={'department': department, 'is_department_head': head})
    if controller:
        group, _ = Group.objects.get_or_create(name=CONTROLLER_GROUP_NAME)
        user.groups.add(group)
    return user


class SignatureGovernanceTests(TestCase):
    def setUp(self):
        self.dept = Department.objects.create(name='قسم التوقيع', code='ع.ق')
        self.other = Department.objects.create(name='قسم آخر', code='ع.خ')
        self.owner = _member('owner', self.dept)
        self.book = Book.objects.create(kind='incoming_external', title='ك',
                                        our_number='9500', department=self.dept,
                                        created_by=self.owner)
        self.att = Attachment.objects.create(
            book=self.book, file=SimpleUploadedFile('d.pdf', _pdf()))

    def test_the_department_head_may_sign(self):
        self.assertTrue(can_sign(_member('head', self.dept, head=True), self.book))

    def test_the_mail_officer_may_not_sign(self):
        """يُسلّم ويستلم ولا يُصادق — الخلطُ بينهما هو ما يمنعه التوقيع."""
        clerk = _member('clerk', self.dept, controller=True)

        self.assertFalse(can_sign(clerk, self.book))
        with self.assertRaises(PermissionDenied):
            sign_attachment(self.att, by=clerk)

    def test_a_head_of_another_department_may_not_sign(self):
        self.assertFalse(can_sign(_member('stranger', self.other, head=True), self.book))

    def test_an_ordinary_employee_may_not_sign(self):
        self.assertFalse(can_sign(_member('worker', self.dept), self.book))


class SignatureEffectTests(TestCase):
    def setUp(self):
        self.dept = Department.objects.create(name='قسم الأثر', code='ث.ق')
        self.head = _member('head', self.dept, head=True)
        self.book = Book.objects.create(kind='incoming_external', title='ك',
                                        our_number='9501', department=self.dept,
                                        created_by=self.head)
        self.att = Attachment.objects.create(
            book=self.book, file=SimpleUploadedFile('d.pdf', _pdf()))

    def test_signing_creates_a_new_version_and_keeps_the_original(self):
        """الختمُ نسخةٌ جديدة لا كتابةٌ فوق الأصل."""
        signature = sign_attachment(self.att, by=self.head)

        self.assertIsNotNone(signature.version)
        self.assertEqual(self.att.versions.count(), 1)
        self.assertNotEqual(signature.version.file.name, self.att.file.name)

    def test_the_digest_matches_right_after_signing(self):
        state = verify(sign_attachment(self.att, by=self.head))

        self.assertTrue(state['valid'])
        self.assertTrue(state['matches'])

    def test_tampering_is_detected(self):
        """أيُّ تعديلٍ يُنتج بصمةً أخرى — «هذا ليس ما وُقّع عليه»."""
        signature = sign_attachment(self.att, by=self.head)
        with open(signature.version.file.path, 'ab') as handle:
            handle.write(b'% tampered')

        state = verify(signature)

        self.assertFalse(state['matches'])
        self.assertIn('تغيّر', state['reason'])

    def test_the_stamp_is_on_every_page(self):
        """صفحةٌ تُقتطع من مستندٍ موقَّع تحمل ختمَها — وإلّا فالختمُ للغلاف."""
        import fitz

        multi = Attachment.objects.create(
            book=self.book, file=SimpleUploadedFile('m.pdf', _pdf(pages=3)))

        signature = sign_attachment(multi, by=self.head)

        with fitz.open(signature.version.file.path) as out:
            self.assertEqual(out.page_count, 3)
            for page in out:
                self.assertIn('verify', page.get_text())

    def test_signing_is_recorded_in_history(self):
        sign_attachment(self.att, by=self.head)

        self.assertTrue(BookHistory.objects.filter(book=self.book, action='sign').exists())

    def test_a_non_pdf_is_refused_plainly(self):
        """رسالةٌ صادقة: «الختمُ يعمل على PDF فقط» لا استثناءٌ يصل المستخدم."""
        text = Attachment.objects.create(
            book=self.book, file=SimpleUploadedFile('n.txt', b'not a pdf'))

        with self.assertRaises(ValidationError):
            sign_attachment(text, by=self.head)


class SignatureRevokeTests(TestCase):
    def setUp(self):
        self.dept = Department.objects.create(name='قسم الإبطال', code='ب.ق')
        self.head = _member('head', self.dept, head=True)
        self.book = Book.objects.create(kind='incoming_external', title='ك',
                                        our_number='9502', department=self.dept,
                                        created_by=self.head)
        att = Attachment.objects.create(
            book=self.book, file=SimpleUploadedFile('d.pdf', _pdf()))
        self.signature = sign_attachment(att, by=self.head)

    def test_revoking_marks_and_does_not_delete(self):
        """التوقيعُ واقعةٌ حدثت — الإبطالُ وسمٌ لا محو."""
        revoke(self.signature, by=self.head, reason='وُقّع خطأً')

        self.signature.refresh_from_db()
        self.assertIsNotNone(self.signature.revoked_at)
        self.assertTrue(BookSignature.objects.filter(pk=self.signature.pk).exists())
        self.assertFalse(verify(self.signature)['valid'])

    def test_a_stranger_cannot_revoke(self):
        other = _member('other', self.dept)

        with self.assertRaises(PermissionDenied):
            revoke(self.signature, by=other)


class VerifyPageTests(TestCase):
    def setUp(self):
        self.dept = Department.objects.create(name='قسم التحقّق', code='ح.ق')
        self.head = _member('head', self.dept, head=True)
        self.book = Book.objects.create(kind='incoming_external',
                                        title='عنوانٌ لا يُعرض في صفحة التحقّق',
                                        our_number='9503', department=self.dept,
                                        created_by=self.head)
        att = Attachment.objects.create(
            book=self.book, file=SimpleUploadedFile('d.pdf', _pdf()))
        self.signature = sign_attachment(att, by=self.head)

    def _get(self, token):
        return self.client.get(reverse('verify_signature', args=[token]))

    def test_the_page_is_public(self):
        """تُفتح من ورقةٍ خرجت من الشركة — فقد يقرؤها مَن ليس مستخدماً."""
        res = self._get(self.signature.verify_token)

        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'لم يتغيّر')

    def test_the_page_never_leaks_the_book_content(self):
        res = self._get(self.signature.verify_token)

        self.assertNotContains(res, 'عنوانٌ لا يُعرض في صفحة التحقّق')

    def test_an_unknown_token_answers_plainly_not_404(self):
        """مَن يقرأ ختماً يحتاج جواباً مفهوماً لا شاشةَ خطأ."""
        res = self._get('nosuchtoken')

        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'لا يقابل توقيعاً')

    def test_the_page_states_what_this_signature_is_not(self):
        """الخلطُ بالتوقيع المعياريّ يُنتج ثقةً كاذبة — فيُقال صراحةً."""
        res = self._get(self.signature.verify_token)

        self.assertContains(res, 'ليس توقيعاً رقميّاً معياريّاً')
