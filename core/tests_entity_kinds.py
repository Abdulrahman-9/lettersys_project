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


class EntityNameCheckTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user(
            'entity_check_staff', password='pw-entity-check-111', is_staff=True
        )
        self.client.force_login(self.staff)
        self.active = Entity.objects.create(name='وزارة النفط')
        self.inactive = Entity.objects.create(name='هيئة قديمة', is_active=False)
        self.merged = Entity.objects.create(
            name='مؤسسة مدموجة', is_active=False, merged_into=self.active
        )

    def check(self, name):
        return self.client.get(reverse('entity_name_check'), {'name': name})

    def test_name_check_returns_exact_active_match(self):
        response = self.check(self.active.name)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['exact']['status'], 'active')
        self.assertEqual(response.json()['exact']['id'], self.active.pk)

    def test_name_check_flags_inactive_and_merged_names(self):
        inactive = self.check(self.inactive.name).json()['exact']
        merged = self.check(self.merged.name).json()['exact']
        self.assertEqual(inactive['status'], 'inactive')
        self.assertEqual(merged['status'], 'merged')
        self.assertEqual(merged['merged_into']['id'], self.active.pk)

    def test_short_name_skips_search(self):
        self.assertEqual(self.check('س').json()['matches'], [])

    def test_create_modal_and_entities_table_show_review_fields(self):
        response = self.client.get(reverse('entity_list'))
        self.assertEqual(response.status_code, 200)
        html = response.content.decode('utf-8')
        self.assertIn('id="entityCreateModal"', html)
        self.assertIn('data-check-url=', html)
        self.assertIn('آخرُ كتاب', html)
        self.assertIn('الحركة', html)
        self.assertIn('href="%s"' % reverse('dossier_detail', args=[self.active.pk]), html)

    def test_sort_new_puts_recently_created_entities_first(self):
        older = Entity.objects.create(name='جهة أقدم')
        recent = Entity.objects.create(name='جهة أحدث')
        response = self.client.get(reverse('entity_list'), {'sort': 'new'})
        html = response.content.decode('utf-8')
        self.assertLess(html.index(recent.name), html.index(older.name))


class ExtractionNewEntityTests(TestCase):
    """جهةٌ تُكتب في صفحة الاستخراج — مراجعة 2026‑10‑12."""

    def setUp(self):
        self.parent = Entity.objects.create(name='وزارة النفط')
        self.victim = Entity.objects.create(name='وزارة  النفط', is_active=False,
                                            merged_into=self.parent)

    def test_entity_picker_exposes_combobox_and_live_status_semantics(self):
        staff = User.objects.create_user('entity_picker_staff', password='pw-picker', is_staff=True)
        self.client.force_login(staff)

        response = self.client.get(reverse('extraction-smart-desktop'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'role="combobox"')
        self.assertContains(response, 'aria-controls="issuingEntityDropdown"')
        self.assertContains(response, 'id="issuingEntityStatus"')
        self.assertContains(response, 'id="receivingEntityStatus"')

    def test_typed_name_of_a_merged_variant_resolves_to_the_parent(self):
        """كان `get_or_create` يجد الضحيّةَ المدموجة ويُحييها فينقض الدمجَ صامتاً."""
        from core.views.books_helpers import _resolve_entities

        result = _resolve_entities([], ['وزارة  النفط'], 'issuer')

        self.assertEqual([e.pk for e in result], [self.parent.pk])
        self.victim.refresh_from_db()
        self.assertFalse(self.victim.is_active)

    def test_stale_id_of_a_merged_variant_resolves_to_the_parent(self):
        from core.views.books_helpers import _resolve_entities

        result = _resolve_entities([self.victim.pk], [], 'issuer')

        self.assertEqual([e.pk for e in result], [self.parent.pk])
        self.victim.refresh_from_db()
        self.assertFalse(self.victim.is_active)

    def test_new_name_gets_the_suggested_tab(self):
        """كانت كلُّ جهةٍ جديدةٍ تسقط في «خارجية» لأنّ الاقتراح لم يُستدعَ."""
        from core.views.books_helpers import _resolve_entities

        [created] = _resolve_entities([], ['شعبة الحاسبة الالكترونية'], 'receiver')

        self.assertEqual(created.kind, UNIT)

    def test_existing_entity_keeps_the_owner_choice(self):
        from core.views.books_helpers import _resolve_entities

        owned = Entity.objects.create(name='شعبة الاتصال', kind=EXTERNAL)
        [got] = _resolve_entities([], ['شعبة الاتصال'], 'issuer')

        self.assertEqual(got.pk, owned.pk)
        got.refresh_from_db()
        self.assertEqual(got.kind, EXTERNAL)


class EntityFormCreateTests(TestCase):
    def test_create_with_empty_tab_takes_the_suggestion(self):
        from core.forms import EntityForm

        form = EntityForm(data={'name': 'شعبة الأرشيف', 'kind': ''})

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data['kind'], UNIT)
        self.assertNotIn('is_active', form.fields)

    def test_explicit_choice_on_create_wins(self):
        from core.forms import EntityForm

        form = EntityForm(data={'name': 'شعبة الأرشيف', 'kind': EXTERNAL})

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data['kind'], EXTERNAL)

    def test_edit_still_requires_a_tab(self):
        from core.forms import EntityForm

        entity = Entity.objects.create(name='جهة قائمة')
        form = EntityForm(data={'name': 'جهة قائمة', 'kind': ''}, instance=entity)

        self.assertFalse(form.is_valid())
        self.assertIn('kind', form.errors)


class EntityCacheBumpTests(TestCase):
    def test_bulk_tab_move_invalidates_entity_search_cache(self):
        from django.core.cache import cache
        from core.signals import ENTITY_CACHE_VERSION_KEY

        staff = User.objects.create_user('clerk2', 'c2@x.co', 'pw', is_staff=True)
        self.client.force_login(staff)
        e = Entity.objects.create(name='جهة للنقل')
        before = cache.get(ENTITY_CACHE_VERSION_KEY)

        self.client.post(reverse('entity_set_kind'), {'kind': UNIT, 'selected': [e.pk]})

        self.assertNotEqual(cache.get(ENTITY_CACHE_VERSION_KEY), before)


class EntityDossierLinkTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('u1', 'u1@x.co', 'pw')
        self.client.force_login(self.user)
        self.entity = Entity.objects.create(name='جهة مرتبطة', kind=INTERNAL)

    def test_entity_page_links_to_its_dossier_and_shows_the_tab(self):
        res = self.client.get(reverse('entity_detail', args=[self.entity.pk]))

        self.assertContains(res, reverse('dossier_detail', args=[self.entity.pk]))
        self.assertContains(res, self.entity.get_kind_display())

    def test_dossier_links_back_to_the_entity_card(self):
        res = self.client.get(reverse('dossier_detail', args=[self.entity.pk]))

        self.assertContains(res, reverse('entity_detail', args=[self.entity.pk]))

    def test_inactive_entity_page_is_not_served(self):
        """البطاقةُ كالإضبارة للنشطة وحدَها — فلا رابطَ ميّتاً بينهما."""
        self.entity.is_active = False
        self.entity.save()

        res = self.client.get(reverse('entity_detail', args=[self.entity.pk]))

        self.assertEqual(res.status_code, 404)
