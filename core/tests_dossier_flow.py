# -*- coding: utf-8 -*-
"""كيف تمتلئ الأضبارة — «يتدفّق لها الكتبُ من ذكر اسمها في الصادر والوارد»."""

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from core.models import Book, Department, Entity, UserProfile
from core.scoping import scope_books_for


class DossierFlowTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user('owner', 'o@x.co', 'pw')

        self.unit_entity = Entity.objects.create(name='وحدة التقارير', code='ف.و')
        self.unit = Department.objects.create(name='وحدة التقارير', code='ف.و',
                                              entity=self.unit_entity)
        self.other_entity = Entity.objects.create(name='وحدة أخرى', code='ف.خ')
        self.other = Department.objects.create(name='وحدة أخرى', code='ف.خ',
                                               entity=self.other_entity)

        self.worker = User.objects.create_user('worker', 'w@x.co', 'pw')
        UserProfile.objects.update_or_create(
            user=self.worker, defaults={'department': self.unit})

    def _book(self, number, *, issuing=None, receiving=None):
        book = Book.objects.create(kind='incoming_external', title='كتاب ' + number,
                                   our_number=number, created_by=self.owner,
                                   department=self.other)
        if issuing:
            book.issuing_entities.set(issuing)
        if receiving:
            book.receiving_entities.set(receiving)
        return book

    def test_a_mention_as_receiver_flows_into_my_dossier(self):
        """اسمي في «الوارد» ⟵ الكتابُ لي، ولو أنشأه غيري وملكَه قسمٌ آخر."""
        book = self._book('7001', receiving=[self.unit_entity])

        visible = scope_books_for(self.worker, Book.objects.all())

        self.assertIn(book, visible)

    def test_a_mention_as_issuer_flows_too(self):
        """والصادرُ كالوارد — «من ذكر اسمها في الجهات الصادر والوارد»."""
        book = self._book('7002', issuing=[self.unit_entity])

        self.assertIn(book, scope_books_for(self.worker, Book.objects.all()))

    def test_another_units_book_does_not_flow(self):
        """ذكرُ وحدةٍ أخرى لا يفتح لي شيئاً — الأضبارةُ ليست دفتراً عامّاً."""
        book = self._book('7003', receiving=[self.other_entity])

        self.assertNotIn(book, scope_books_for(self.worker, Book.objects.all()))

    def test_a_unit_without_a_twin_entity_has_no_dossier(self):
        """وحدةٌ بلا توأمِ جهةٍ لا اسمَ لها يُذكَر — فلا أضبارة، وهذا صحيحٌ لا نقص."""
        orphan = Department.objects.create(name='وحدة بلا توأم', code='ف.ي')
        stranger = User.objects.create_user('stranger', 's@x.co', 'pw')
        UserProfile.objects.update_or_create(
            user=stranger, defaults={'department': orphan})
        self._book('7004', receiving=[self.unit_entity])

        self.assertEqual(scope_books_for(stranger, Book.objects.all()).count(), 0)

    def test_the_mention_is_not_duplicated_by_the_join(self):
        """كتابٌ يذكر وحدتي مرّتين (صادراً ووارداً) يبقى صفّاً واحداً.

        وصلُ علاقتَي M2M يُنتج ضرباً ديكارتيّاً — ولهذا الشقُّ استعلامٌ فرعيّ.
        """
        self._book('7005', issuing=[self.unit_entity], receiving=[self.unit_entity])

        self.assertEqual(scope_books_for(self.worker, Book.objects.all()).count(), 1)

    def test_the_dossier_page_shows_the_flowed_books(self):
        """والصفحةُ تُظهر ما تدفّق — لا الاستعلامُ وحده.

        كانت `_book_base_filter` نسخةً خاصّةً من قاعدة الرؤية سبقت بُعدَ القسم،
        فتُفتح الأضبارةُ فارغةً لموظّفٍ لم يُنشئ كتبَها بيده. يفشل عليها.
        """
        self._book('7006', receiving=[self.unit_entity])
        self.client.force_login(self.worker)

        res = self.client.get(reverse('dossier_detail', args=[self.unit_entity.pk]))

        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.context['incoming_count'], 1)
        self.assertEqual(res.context['outgoing_count'], 0)

    def test_the_dossier_page_was_empty_before_the_single_source(self):
        """والعدُّ في القائمة يتبع النطاقَ نفسَه — لا نسخةً ثانية منه."""
        self._book('7007', receiving=[self.unit_entity])
        self.client.force_login(self.worker)

        res = self.client.get(reverse('dossier_list'), {'kind': self.unit_entity.kind})
        rows = {e.name: e for e in res.context['page_obj'].object_list}

        self.assertIn('وحدة التقارير', rows)
        self.assertEqual(rows['وحدة التقارير'].received_count, 1)
