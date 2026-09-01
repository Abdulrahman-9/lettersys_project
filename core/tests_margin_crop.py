# -*- coding: utf-8 -*-
"""حرّاسُ قصاصة الهامش — من التحقّق إلى التخزين إلى البوّابة."""

import json

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from core.models import Attachment, Book, BookReferral, Department, Entity, UserProfile
from core.page_render import normalise_crop


class NormaliseCropTests(TestCase):
    """الواردُ من العميل لا يُصدَّق — والقصاصةُ تُخزَّن كسوراً لا بكسلات."""

    def test_a_sound_crop_survives(self):
        out = normalise_crop({'page': 2, 'x': .1, 'y': .2, 'w': .3, 'h': .25,
                              'attachment': '7'})

        self.assertEqual(out, {'page': 2, 'x': .1, 'y': .2, 'w': .3, 'h': .25,
                               'attachment': 7})

    def test_a_rectangle_without_area_is_refused(self):
        self.assertIsNone(normalise_crop({'page': 1, 'x': .1, 'y': .1, 'w': 0, 'h': .3}))
        self.assertIsNone(normalise_crop({'page': 1, 'x': .1, 'y': .1, 'w': .3, 'h': 0}))

    def test_a_speck_is_refused(self):
        """نقرةٌ طائشةٌ ليست تحديداً — تُسقَط بدل أن تُصيَّر قصاصةً بلا معنى."""
        self.assertIsNone(normalise_crop({'page': 1, 'x': .5, 'y': .5,
                                          'w': .005, 'h': .005}))

    def test_spilling_outside_the_page_is_refused(self):
        self.assertIsNone(normalise_crop({'page': 1, 'x': .9, 'y': .1, 'w': .5, 'h': .2}))
        self.assertIsNone(normalise_crop({'page': 1, 'x': .1, 'y': .9, 'w': .2, 'h': .5}))

    def test_negatives_and_junk_are_refused(self):
        self.assertIsNone(normalise_crop({'page': 1, 'x': -.1, 'y': .1, 'w': .2, 'h': .2}))
        self.assertIsNone(normalise_crop({'page': 0, 'x': .1, 'y': .1, 'w': .2, 'h': .2}))
        self.assertIsNone(normalise_crop({'page': 999, 'x': .1, 'y': .1, 'w': .2, 'h': .2}))
        self.assertIsNone(normalise_crop({'x': 'كثير', 'y': .1, 'w': .2, 'h': .2}))
        self.assertIsNone(normalise_crop({'page': 1, 'y': .1, 'w': .2, 'h': .2}))
        self.assertIsNone(normalise_crop(None))
        self.assertIsNone(normalise_crop('نصّ'))

    def test_a_missing_attachment_is_kept_null_not_invented(self):
        out = normalise_crop({'page': 1, 'x': .1, 'y': .1, 'w': .2, 'h': .2})

        self.assertIsNone(out['attachment'])


class DistributeWithCropTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser('root', 'r@x.co', 'pw')
        self.client.force_login(self.admin)
        self.dept = Department.objects.create(name='قسم القصاصة', code='ق.ق')
        self.unit = Department.objects.create(name='وحدة القصاصة', code='ق.و',
                                              parent=self.dept)
        self.book = Book.objects.create(kind='incoming_external', title='ك',
                                        our_number='8800', department=self.dept,
                                        created_by=self.admin)

    def _post(self, crop):
        return self.client.post(
            reverse('api_distribute', args=[self.book.pk]),
            # الأهدافُ نصوصٌ بالصيغة `dep:<id>` — لا قواميس.
            data=json.dumps({'targets': ['dep:%d' % self.unit.pk],
                             'margin': 'للتنفيذ', 'margin_crop': crop}),
            content_type='application/json')

    def test_the_crop_reaches_the_row(self):
        """المسارُ كان مقطوعاً: الحقلُ والخدمةُ جاهزان والنقطةُ لا تقرأ شيئاً."""
        res = self._post({'page': 1, 'x': .12, 'y': .3, 'w': .6, 'h': .18})

        self.assertEqual(res.status_code, 200)
        row = BookReferral.objects.get(book=self.book)
        self.assertEqual(row.margin_crop['w'], .6)
        self.assertEqual(row.margin_crop['page'], 1)

    def test_a_bad_crop_does_not_break_the_distribution(self):
        """قصاصةٌ فاسدةٌ تُسقَط والتفريقُ يتمّ — العملُ لا يقف على معاينة."""
        res = self._post({'x': 5, 'y': 5, 'w': 5, 'h': 5})

        self.assertEqual(res.status_code, 200)
        self.assertIsNone(BookReferral.objects.get(book=self.book).margin_crop)

    def test_distribution_without_a_crop_still_works(self):
        res = self._post(None)

        self.assertEqual(res.status_code, 200)
        self.assertIsNone(BookReferral.objects.get(book=self.book).margin_crop)


class PageImageGateTests(TestCase):
    """صورةُ الصفحة صورةٌ من المستند — فبوّابةُ المحتوى هي بوّابتُها."""

    def setUp(self):
        self.owner = User.objects.create_superuser('owner', 'o@x.co', 'pw')
        self.dept = Department.objects.create(name='قسم الصورة', code='ص.ق')
        self.far = Department.objects.create(name='قسم بعيد', code='ص.ب')
        self.book = Book.objects.create(kind='incoming_external', title='ك',
                                        our_number='8801', department=self.dept,
                                        created_by=self.owner)
        self.att = Attachment.objects.create(book=self.book, file='books/none.pdf')

    def test_an_outsider_gets_404_not_403(self):
        """403 يُسرّب وجودَ المرفق — و404 لا يقول شيئاً."""
        stranger = User.objects.create_user('stranger', 's@x.co', 'pw')
        UserProfile.objects.update_or_create(user=stranger,
                                             defaults={'department': self.far})
        self.client.force_login(stranger)

        res = self.client.get(reverse('attachment_page_image',
                                      args=[self.att.pk, 1]))

        self.assertEqual(res.status_code, 404)

    def test_login_is_required(self):
        res = self.client.get(reverse('attachment_page_image', args=[self.att.pk, 1]))

        self.assertIn(res.status_code, (302, 404))

    def test_an_unrenderable_file_is_404_not_a_crash(self):
        """ملفٌّ غيرُ موجودٍ أو غيرُ مستند: 404 صريح لا استثناءٌ يصل المستخدم."""
        self.client.force_login(self.owner)

        res = self.client.get(reverse('attachment_page_image', args=[self.att.pk, 1]))

        self.assertEqual(res.status_code, 404)
