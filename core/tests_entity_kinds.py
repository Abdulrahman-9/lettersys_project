# -*- coding: utf-8 -*-
"""حرّاسُ تبويب الجهة — **قرارٌ مخزَّنٌ يملكه المالك** لا استنتاجٌ من الاسم."""

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from core.entity_kinds import EXTERNAL, INTERNAL, KINDS, UNIT, suggest_kind
from core.models import Department, Entity


class SuggestKindTests(TestCase):
    """الاقتراحُ يخدم الجهةَ الجديدة — ولا يُقرّر عن المالك."""

    def setUp(self):
        self.body = Entity.objects.create(name='هيئة العمليات', code='ع')
        Department.objects.create(name='هيئة العمليات', code='ع', entity=self.body)

    def test_sub_unit_and_person_and_branch_and_outsider(self):
        self.assertEqual(suggest_kind('شعبة المتابعة الفنية'), UNIT)
        self.assertEqual(suggest_kind('السيد وسام حميد خالد'), UNIT)
        self.assertEqual(suggest_kind('هيئة العمليات / قسم حقول الانبار'), UNIT)
        self.assertEqual(suggest_kind('وزارة النفط'), EXTERNAL)

    def test_twinned_entity_suggests_internal(self):
        self.assertEqual(suggest_kind(self.body), INTERNAL)

    def test_suggestion_never_overwrites_a_stored_choice(self):
        """المالكُ قال «خارجية» لجهةٍ اسمُها «شعبة» — يبقى قولُه.

        هذا هو العقدُ كلُّه: الاقتراحُ مدخلٌ لا حاكم.
        """
        entity = Entity.objects.create(name='شعبة الاتصال بالوزارة',
                                       kind=EXTERNAL)
        entity.refresh_from_db()

        self.assertEqual(entity.kind, EXTERNAL)
        self.assertEqual(suggest_kind(entity), UNIT)   # الاقتراحُ يخالف — ولا أثر له


class EntityKindWriteTests(TestCase):
    """نقلُ المحدَّد إلى تبويب — الأداةُ التي يشكّل بها المالكُ مجموعاته."""

    def setUp(self):
        self.staff = User.objects.create_user('clerk', 'c@x.co', 'pw', is_staff=True)
        self.client.force_login(self.staff)
        self.a = Entity.objects.create(name='جهة أ', kind=EXTERNAL)
        self.b = Entity.objects.create(name='جهة ب', kind=EXTERNAL)

    def test_bulk_move_sets_the_chosen_tab(self):
        res = self.client.post(reverse('entity_set_kind'),
                               {'kind': INTERNAL, 'selected': [self.a.pk, self.b.pk]})

        self.assertEqual(res.status_code, 302)
        self.a.refresh_from_db(); self.b.refresh_from_db()
        self.assertEqual(self.a.kind, INTERNAL)
        self.assertEqual(self.b.kind, INTERNAL)

    def test_unknown_tab_changes_nothing(self):
        self.client.post(reverse('entity_set_kind'),
                         {'kind': 'ملفّق', 'selected': [self.a.pk]})

        self.a.refresh_from_db()
        self.assertEqual(self.a.kind, EXTERNAL)

    def test_empty_selection_changes_nothing(self):
        self.client.post(reverse('entity_set_kind'), {'kind': UNIT})

        self.a.refresh_from_db()
        self.assertEqual(self.a.kind, EXTERNAL)

    def test_only_the_selected_rows_move(self):
        self.client.post(reverse('entity_set_kind'),
                         {'kind': UNIT, 'selected': [self.a.pk]})

        self.a.refresh_from_db(); self.b.refresh_from_db()
        self.assertEqual(self.a.kind, UNIT)
        self.assertEqual(self.b.kind, EXTERNAL)

    def test_ordinary_user_cannot_move(self):
        """التبويبُ يُعيد تشكيل صفحةٍ يراها الجميع — فالكتابةُ للموظّفين."""
        self.client.force_login(User.objects.create_user('nobody', 'n@x.co', 'pw'))

        self.client.post(reverse('entity_set_kind'),
                         {'kind': UNIT, 'selected': [self.a.pk]})

        self.a.refresh_from_db()
        self.assertEqual(self.a.kind, EXTERNAL)

    def test_open_redirect_is_refused(self):
        """`back` سلسلةُ استعلامٍ لا عنوانٌ كامل."""
        res = self.client.post(reverse('entity_set_kind'),
                               {'kind': UNIT, 'selected': [self.a.pk],
                                'back': 'https://evil.example/x'})

        self.assertEqual(res['Location'], reverse('entity_list'))

    def test_back_preserves_the_filter(self):
        """العودةُ إلى المرشِّح نفسِه — والعربيّةُ تُرمَّز في الترويسة."""
        res = self.client.post(reverse('entity_set_kind'),
                               {'kind': UNIT, 'selected': [self.a.pk],
                                'back': '?kind=external&page=2'})

        self.assertEqual(res['Location'],
                         reverse('entity_list') + '?kind=external&page=2')


class EntityFormKindTests(TestCase):
    def test_form_exposes_the_tab_field(self):
        from core.forms import EntityForm

        self.assertIn('kind', EntityForm().fields)

    def test_choices_cover_exactly_the_three_tabs(self):
        self.assertEqual(sorted(k for k, _ in Entity.KIND_CHOICES), sorted(KINDS))
