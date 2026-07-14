# -*- coding: utf-8 -*-
"""اختبارات core/entity_dedup.py — كشف ودمج الجهات المكرّرة.

يغطّي عملية الدمج المدمِّرة غير القابلة للتراجع (merge_entities) ومنطق
الكشف والتطبيع. الهدف: ضمان سلامة إعادة توجيه الكتب، عدم ازدواج الروابط،
نقل بيانات الاتصال بأمان، وتعطيل النسخ مع ضبط merged_into.
"""
from datetime import date
from io import StringIO

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase

from .models import Book, Entity, LetterheadMemory
from . import entity_dedup as dd


def make_book(num, user, **kw):
    return Book.objects.create(
        our_number=num, title='كتاب', date=date(2024, 1, 1),
        kind='incoming_internal', created_by=user, **kw,
    )


class NormKeyTests(TestCase):
    """تطبيع الاسم: يوحّد الفروق الإملائية الشائعة فقط."""

    def test_taa_marbuta_equiv(self):
        self.assertEqual(dd.norm_key('مديرية'), dd.norm_key('مديريه'))

    def test_hamza_alef_equiv(self):
        self.assertEqual(dd.norm_key('أحمد'), dd.norm_key('احمد'))
        self.assertEqual(dd.norm_key('إدارة'), dd.norm_key('ادارة'))
        self.assertEqual(dd.norm_key('آمنة'), dd.norm_key('امنة'))

    def test_alef_maqsura_equiv(self):
        self.assertEqual(dd.norm_key('مستشفى'), dd.norm_key('مستشفي'))

    def test_whitespace_collapse_and_strip(self):
        self.assertEqual(dd.norm_key('  وزارة   التعليم  '), dd.norm_key('وزارة التعليم'))

    def test_case_insensitive(self):
        self.assertEqual(dd.norm_key('ABC Co'), dd.norm_key('abc co'))

    def test_hamza_on_waw_yaa_equiv(self):
        self.assertEqual(dd.norm_key('مسؤول'), dd.norm_key('مسوول'))

    def test_distinct_names_stay_distinct(self):
        self.assertNotEqual(dd.norm_key('وزارة الصحة'), dd.norm_key('وزارة المالية'))


class CorrectnessScoreTests(TestCase):
    """درجة صحّة الإملاء — تُستخدم لاختيار الجهة الأمّ الأصحّ."""

    def test_taa_marbuta_scores_higher(self):
        self.assertGreater(
            dd.correctness_score(Entity(name='مديرية')),
            dd.correctness_score(Entity(name='مديريه')),
        )

    def test_trailing_space_penalized(self):
        self.assertGreater(
            dd.correctness_score(Entity(name='وزارة')),
            dd.correctness_score(Entity(name='وزارة ')),
        )


class ClusterDetectionTests(TestCase):
    """find_duplicate_clusters: يجمع المتطابقين بعد التطبيع ويختار الأمّ."""

    def test_finds_one_cluster_for_spelling_variants(self):
        e1 = Entity.objects.create(name='مديرية التربية', etype='both')
        e2 = Entity.objects.create(name='مديريه التربيه', etype='both')
        clusters = dd.find_duplicate_clusters()
        self.assertEqual(len(clusters), 1)
        self.assertEqual({m.id for m in clusters[0]['members']}, {e1.id, e2.id})

    def test_singleton_makes_no_cluster(self):
        Entity.objects.create(name='جهة فريدة')
        self.assertEqual(dd.find_duplicate_clusters(), [])

    def test_inactive_member_excluded(self):
        Entity.objects.create(name='مديرية التربية')
        Entity.objects.create(name='مديريه التربيه', is_active=False)
        self.assertEqual(dd.find_duplicate_clusters(), [])  # نشطة واحدة فقط

    def test_canonical_prefers_entity_with_code(self):
        no_code = Entity.objects.create(name='مديرية الماء')
        with_code = Entity.objects.create(name='مديريه الماء', code='WATER')
        self.assertEqual(dd.find_duplicate_clusters()[0]['canonical'].id, with_code.id)

    def test_canonical_prefers_correct_spelling_when_no_code(self):
        correct = Entity.objects.create(name='مديرية الكهرباء')   # ة سليمة
        Entity.objects.create(name='مديريه الكهرباء')             # ه خاطئة
        self.assertEqual(dd.find_duplicate_clusters()[0]['canonical'].id, correct.id)


class ManualClusterTests(TestCase):
    """build_manual_cluster: تجاوز يدوي للكشف الآلي."""

    def test_returns_none_when_fewer_than_two_active(self):
        e = Entity.objects.create(name='جهة')
        self.assertIsNone(dd.build_manual_cluster([e.id]))
        inactive = Entity.objects.create(name='جهة٢', is_active=False)
        self.assertIsNone(dd.build_manual_cluster([e.id, inactive.id]))

    def test_builds_cluster_from_semantically_related_names(self):
        a = Entity.objects.create(name='هيئة الاستثمار', code='INV')
        b = Entity.objects.create(name='الهيئة العامة للاستثمار')
        cluster = dd.build_manual_cluster([a.id, b.id])
        self.assertIsNotNone(cluster)
        self.assertTrue(cluster['manual'])
        self.assertEqual(cluster['canonical'].id, a.id)   # صاحبة الرمز


class AnnotateBookCountsTests(TestCase):
    """annotate_book_counts: عدّ الكتب المُصدَرة/المستلَمة بلا ضرب ديكارتي."""

    def setUp(self):
        self.user = User.objects.create_user('u', password='p')

    def test_counts_issued_and_received(self):
        e = Entity.objects.create(name='جهة العدّ')
        b1 = make_book('c-1', self.user); b1.issuing_entities.add(e)
        b2 = make_book('c-2', self.user); b2.issuing_entities.add(e)
        b3 = make_book('c-3', self.user); b3.receiving_entities.add(e)
        got = dd.annotate_book_counts(Entity.objects.filter(id=e.id)).first()
        self.assertEqual(got.issued_count, 2)
        self.assertEqual(got.received_count, 1)
        self.assertEqual(dd.book_count(got), 3)

    def test_deleted_books_not_counted(self):
        e = Entity.objects.create(name='جهة محذوفة')
        b = make_book('c-4', self.user, is_deleted=True); b.issuing_entities.add(e)
        got = dd.annotate_book_counts(Entity.objects.filter(id=e.id)).first()
        self.assertEqual(got.issued_count, 0)


class MergeEntitiesTests(TestCase):
    """merge_entities: العملية المدمِّرة — إعادة التوجيه + النقل + التعطيل."""

    def setUp(self):
        self.user = User.objects.create_user('u', password='p')
        self.canon = Entity.objects.create(name='وزارة الصحة', etype='both')
        self.victim = Entity.objects.create(name='وزاره الصحه', etype='both')

    def test_repoints_issuing_and_receiving_books(self):
        b1 = make_book('m-1', self.user); b1.issuing_entities.add(self.victim)
        b2 = make_book('m-2', self.user); b2.receiving_entities.add(self.victim)
        res = dd.merge_entities(self.canon.id, [self.victim.id])
        self.assertIn(self.canon, b1.issuing_entities.all())
        self.assertNotIn(self.victim, b1.issuing_entities.all())
        self.assertIn(self.canon, b2.receiving_entities.all())
        self.assertEqual(res['moved_books'], 2)

    def test_dedupes_shared_book_link(self):
        b = make_book('m-3', self.user)
        b.issuing_entities.add(self.canon, self.victim)   # مربوط بالاثنين
        dd.merge_entities(self.canon.id, [self.victim.id])
        through = Book.issuing_entities.through
        self.assertEqual(through.objects.filter(book_id=b.id, entity_id=self.canon.id).count(), 1)
        self.assertEqual(through.objects.filter(book_id=b.id, entity_id=self.victim.id).count(), 0)

    def test_deactivates_victim_and_sets_merged_into(self):
        dd.merge_entities(self.canon.id, [self.victim.id])
        self.victim.refresh_from_db()
        self.assertFalse(self.victim.is_active)
        self.assertEqual(self.victim.merged_into_id, self.canon.id)

    def test_carries_contact_when_canonical_empty(self):
        self.victim.email = 'v@x.com'
        self.victim.phone = '07700000000'
        self.victim.save()
        dd.merge_entities(self.canon.id, [self.victim.id])
        self.canon.refresh_from_db()
        self.assertEqual(self.canon.email, 'v@x.com')
        self.assertEqual(self.canon.phone, '07700000000')

    def test_does_not_overwrite_existing_contact(self):
        self.canon.email = 'canon@x.com'
        self.canon.save()
        self.victim.email = 'victim@x.com'
        self.victim.save()
        dd.merge_entities(self.canon.id, [self.victim.id])
        self.canon.refresh_from_db()
        self.assertEqual(self.canon.email, 'canon@x.com')   # محفوظ

    def test_carries_code_and_frees_victim_code(self):
        self.victim.code = 'HEALTH'
        self.victim.save()
        dd.merge_entities(self.canon.id, [self.victim.id])
        self.canon.refresh_from_db()
        self.victim.refresh_from_db()
        self.assertEqual(self.canon.code, 'HEALTH')
        self.assertIsNone(self.victim.code)   # حُرِّر لتفادي تعارض التفرّد

    def test_ignores_canonical_listed_as_victim(self):
        res = dd.merge_entities(self.canon.id, [self.canon.id])
        self.assertEqual(res['merged'], 0)
        self.canon.refresh_from_db()
        self.assertTrue(self.canon.is_active)

    def test_empty_victims_is_noop(self):
        res = dd.merge_entities(self.canon.id, [])
        self.assertEqual(res['merged'], 0)
        self.assertEqual(res['moved_books'], 0)

    def test_merged_victim_excluded_from_future_clusters(self):
        dd.merge_entities(self.canon.id, [self.victim.id])
        self.assertEqual(dd.find_duplicate_clusters(), [])   # النسخة عُطّلت

    def test_summary_counts(self):
        v2 = Entity.objects.create(name='وزارة الصحه')   # نسخة ثالثة
        b = make_book('m-4', self.user); b.issuing_entities.add(self.victim)
        res = dd.merge_entities(self.canon.id, [self.victim.id, v2.id])
        self.assertEqual(res['merged'], 2)
        self.assertEqual(res['moved_books'], 1)
        self.assertEqual(res['canonical'].id, self.canon.id)


class MemoryRepointOnMergeTests(TestCase):
    """إصلاح الثغرة: merge_entities يُعيد توجيه LetterheadMemory أيضاً — وإلا تبقى
    الإشارة مُشظّاة على النسخة المُعطّلة (فهرس match_from_memory يقرأ issuing_entity)."""

    def test_merge_repoints_letterhead_memory(self):
        canon = Entity.objects.create(name='مديرية التربية')
        victim = Entity.objects.create(name='مديريه التربيه')
        LetterheadMemory.objects.create(letterhead='ترويسة أ', issuing_entity=canon)
        lm_iss = LetterheadMemory.objects.create(letterhead='ترويسة ب', issuing_entity=victim)
        lm_rcv = LetterheadMemory.objects.create(letterhead='ترويسة ج', receiving_entity=victim)

        res = dd.merge_entities(canon.id, [victim.id])

        self.assertEqual(res['moved_memory'], 2)                 # صفّان أُعيد توجيههما
        lm_iss.refresh_from_db(); lm_rcv.refresh_from_db()
        self.assertEqual(lm_iss.issuing_entity_id, canon.id)     # المُصدِرة → الأمّ
        self.assertEqual(lm_rcv.receiving_entity_id, canon.id)   # المستقبِلة → الأمّ
        # لا فقد: الأمّ تجمع كل الذاكرة الآن، لا شيء على النسخة
        self.assertEqual(LetterheadMemory.objects.filter(issuing_entity=canon).count(), 2)
        self.assertEqual(LetterheadMemory.objects.filter(issuing_entity=victim).count(), 0)


class PrepareEntitiesCommandTests(TestCase):
    """أمر التهيئة prepare_entities — تهيئة قاعدة بيانات جديدة عند النشر."""

    def setUp(self):
        self.user = User.objects.create_user('prep', password='p')

    def test_apply_merges_and_repoints(self):
        canon = Entity.objects.create(name='وزارة النفط')
        dup = Entity.objects.create(name='وزاره النفط')          # نفس norm_key
        lm = LetterheadMemory.objects.create(letterhead='ترويسة', issuing_entity=dup)

        call_command('prepare_entities', '--apply', stdout=StringIO())

        dup.refresh_from_db(); lm.refresh_from_db()
        self.assertFalse(dup.is_active)
        self.assertEqual(dup.merged_into_id, canon.id)
        self.assertEqual(lm.issuing_entity_id, canon.id)         # الذاكرة تبعت الدمج

    def test_dry_run_changes_nothing(self):
        canon = Entity.objects.create(name='وزارة المالية')
        dup = Entity.objects.create(name='وزاره الماليه')
        call_command('prepare_entities', stdout=StringIO())      # بلا --apply
        dup.refresh_from_db()
        self.assertTrue(dup.is_active)
        self.assertIsNone(dup.merged_into_id)


class SemanticCandidatesTests(TestCase):
    """الكشف الذكي: يمسك ما يفوت التطبيع (تصحيف/التصاق/تشريف) ولا يخلط الدلالات."""

    def test_single_letter_typo_paired(self):
        a = Entity.objects.create(name='مكتب السيد المدير العام')
        b = Entity.objects.create(name='مكتب السيد المدبر العام')     # تصحيف حرف
        got = {m.id for c in dd.find_semantic_candidates() for m in c['members']}
        self.assertEqual(got, {a.id, b.id})

    def test_honorific_only_difference_paired(self):
        a = Entity.objects.create(name='رئيس لجنة الادارة المشتركة')
        b = Entity.objects.create(name='السيد رئيس لجنة الادارة المشتركة')
        clusters = dd.find_semantic_candidates()
        self.assertEqual(len(clusters), 1)
        self.assertEqual({m.id for m in clusters[0]['members']}, {a.id, b.id})

    def test_fused_words_paired(self):
        a = Entity.objects.create(name='السيد المدير العام')
        b = Entity.objects.create(name='السيد المديرالعام')            # التصاق
        self.assertEqual(len(dd.find_semantic_candidates()), 1)

    def test_semantic_difference_not_paired(self):
        Entity.objects.create(name='مكتب معاون المدير العام للشؤون الفنية')
        Entity.objects.create(name='مكتب معاون المدير العام للشؤون الادارية')
        self.assertEqual(dd.find_semantic_candidates(), [])   # الفنية ≠ الادارية

    def test_subordination_not_paired(self):
        Entity.objects.create(name='قسم المتابعة')
        Entity.objects.create(name='شعبة المتابعة الفنية')             # تبعية لا تكرار
        self.assertEqual(dd.find_semantic_candidates(), [])


class MergePlanTests(TestCase):
    """خطة الدمج المُخلَّدة — قرارات مُراجَعة بشرياً تُعاد عند كل استعادة."""

    def setUp(self):
        self.user = User.objects.create_user('plan', password='p')
        self.plan = [{'canonical': 'هيئة العمليات',
                      'variants': ['هيأة العمليات', 'هيئة الععمليات']}]

    def test_export_follows_merge_chain_to_active_canonical(self):
        a = Entity.objects.create(name='الجهة الاولى')
        b = Entity.objects.create(name='الجهه الاولي')
        c = Entity.objects.create(name='الجهة الأولى')
        dd.merge_entities(b.id, [c.id])          # ج → ب
        dd.merge_entities(a.id, [b.id])          # ب → أ (سلسلة)
        plan = dd.export_merge_plan()
        self.assertEqual(len(plan), 1)
        self.assertEqual(plan[0]['canonical'], 'الجهة الاولى')
        self.assertEqual(set(plan[0]['variants']), {'الجهه الاولي', 'الجهة الأولى'})

    def test_actions_pick_canonical_name_holder_as_target(self):
        target = Entity.objects.create(name='هيئة العمليات')
        victim = Entity.objects.create(name='هيأة العمليات')
        actions = dd.plan_actions(self.plan)
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0]['target'].id, target.id)
        self.assertEqual([v.id for v in actions[0]['victims']], [victim.id])

    def test_apply_renames_best_variant_when_canonical_absent(self):
        v1 = Entity.objects.create(name='هيأة العمليات')
        v2 = Entity.objects.create(name='هيئة الععمليات')
        b = make_book('p-1', self.user)
        b.issuing_entities.add(v2)

        actions = dd.plan_actions(self.plan)
        self.assertEqual(len(actions), 1)
        res = dd.apply_plan_action(actions[0])

        self.assertEqual(res['merged'], 1)
        survivor = Entity.objects.get(name='هيئة العمليات', is_active=True)
        self.assertIn(survivor.id, {v1.id, v2.id})   # سُمّيت على القانوني
        self.assertEqual(b.issuing_entities.first().id, survivor.id)
        # إعادة التشغيل لا تفعل شيئاً — الخطة idempotent
        self.assertEqual(dd.plan_actions(self.plan), [])

    def test_claim_name_swaps_with_inactive_holder(self):
        holder = Entity.objects.create(name='هيئة العمليات', is_active=False)
        e = Entity.objects.create(name='هيأة العمليات')
        self.assertTrue(dd._claim_name(e, 'هيئة العمليات'))
        e.refresh_from_db(); holder.refresh_from_db()
        self.assertEqual(e.name, 'هيئة العمليات')
        self.assertEqual(holder.name, 'هيأة العمليات')   # مبادلة تحفظ الأثر

    def test_claim_name_refuses_active_holder(self):
        Entity.objects.create(name='هيئة العمليات')
        e = Entity.objects.create(name='هيأة العمليات')
        self.assertFalse(dd._claim_name(e, 'هيئة العمليات'))
        e.refresh_from_db()
        self.assertEqual(e.name, 'هيأة العمليات')        # لم يُمسّ

    def test_unmatched_plan_is_silent(self):
        self.assertEqual(dd.plan_actions(
            [{'canonical': 'جهة غير موجودة', 'variants': ['ولا هذه']}]), [])
