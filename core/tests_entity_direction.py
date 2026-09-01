# -*- coding: utf-8 -*-
"""اتّجاه الكتاب يحكم مصادر الجهة المستلِمة (فيبل، قياس 2026-08-16).

الجذر المُقاس: المستلِمة **0/30** على نصوصٍ حقيقيّة — لا لعطلٍ في المطابقة بل لأن
المهمّة مُؤطَّرةٌ خطأً: في الوارد لا تُذكر جهتُنا المستلِمة في الكتاب؛ سطر «الى/» يحمل
المُخاطَب داخل جهة المُرسِل، والكاتب يسجّل **وجهة التوجيه عندنا** (9,360 كتاباً: 45
قيمة فقط، السائدة 64.9%). الذاكرة تخزّن هذا التوجيه — لكنّ «الى/» كان يتصدّرها.
LOO على 300 صفّ: أساس 51.3% مقابل ذاكرة 58.7% (+7.4، تجاوز بوّابة فيبل +5).

تُختبَر الدالّة التي يستعملها الأنبوب نفسه (`entity_source_plan`) — لا نسخةٌ منها."""
from django.test import SimpleTestCase, TestCase

from core.extraction.matchers.entity import EntityMatcher
from core.extraction.pipeline import entity_source_plan, prefer_jmc_committee
from django.contrib.auth.models import User

from core.models import Book, Entity, LetterheadMemory


class EntitySourcePlanTests(SimpleTestCase):
    def test_outgoing_keeps_recipient_line_first(self):
        """الصادر لا يُمسّ: «الى/» هو المُخاطَب الحقيقيّ ⟵ يتصدّر."""
        for kind in ('outgoing_internal', 'outgoing_external'):
            p = entity_source_plan('receiver', kind, True)
            self.assertIn('recipient_line_first', p, kind)
            self.assertNotIn('recipient_line_after_memory', p, kind)

    def test_incoming_internal_memory_first_then_recipient(self):
        p = entity_source_plan('receiver', 'incoming_internal', True)
        self.assertIn('memory', p)
        self.assertIn('recipient_line_after_memory', p)
        self.assertNotIn('recipient_line_first', p)

    def test_incoming_external_drops_recipient_line(self):
        """«الى/» في الوارد الخارجيّ يسمّي مُخاطَباً داخل جهة المُرسِل ⟵ يُسقط."""
        p = entity_source_plan('receiver', 'incoming_external', True)
        self.assertIn('memory', p)
        self.assertNotIn('recipient_line_first', p)
        self.assertNotIn('recipient_line_after_memory', p)

    def test_letterhead_never_feeds_receiver_on_incoming(self):
        """الترويسة اسمُ المُرسِل دائماً ⟵ تُمنع عن حقل المستلِمة في الوارد (جذر #11298)."""
        for kind in ('incoming_internal', 'incoming_external'):
            self.assertNotIn('letterhead', entity_source_plan('receiver', kind, True), kind)

    def test_letterhead_still_used_for_issuer_and_for_outgoing_receiver(self):
        self.assertIn('letterhead', entity_source_plan('issuer', 'incoming_external', True))
        self.assertIn('letterhead', entity_source_plan('receiver', 'outgoing_external', True))

    def test_no_recipient_text_means_no_recipient_source(self):
        p = entity_source_plan('receiver', 'incoming_internal', False)
        self.assertNotIn('recipient_line_after_memory', p)
        self.assertIn('memory', p)

    def test_unknown_kind_behaves_like_outgoing(self):
        """اتّجاهٌ مجهول (نمطٌ لم يُستنتَج) ⟵ السلوك السابق، بلا مفاجآت."""
        p = entity_source_plan('receiver', '', True)
        self.assertIn('recipient_line_first', p)
        self.assertIn('letterhead', p)


class PreferJmcCommitteeTests(SimpleTestCase):
    """عُرف المالك: في كتب اللجان المشتركة الجهةُ المُصدِرة هي **اللجنة** لا الشركة
    المُشغِّلة. إعادةُ ترتيبٍ لا إقصاء — مقيس: 73%→77% (أصابت #8720)، صفر تراجع."""

    JMC = ('ترويسة\n'
           'لجنة الادارة المشتركة لرقعة النفط خانة\n'
           'NK Petroleum Company Limited')

    def _c(self, *names):
        return [{'entity_id': i, 'entity_name': n} for i, n in enumerate(names, 1)]

    def test_promotes_committee_over_operator(self):
        out = prefer_jmc_committee(
            self._c('NK Petroleum Company Limited', 'لجنة الادارة المشتركة لرقعة'), self.JMC)
        self.assertEqual(out[0]['entity_name'], 'لجنة الادارة المشتركة لرقعة')
        self.assertEqual(len(out), 2, 'إعادة ترتيبٍ لا حذف')

    def test_no_committee_candidate_keeps_order(self):
        c = self._c('NK Petroleum Company Limited', 'قسم تقنية المعلومات')
        self.assertEqual(prefer_jmc_committee(c, self.JMC), c)

    def test_no_jmc_in_text_never_fires(self):
        c = self._c('Zhongman', 'لجنة الادارة المشتركة')
        self.assertEqual(prefer_jmc_committee(c, 'Zhongman Babylon Oil & Gas DMCC'), c)

    def test_committee_already_top_untouched(self):
        c = self._c('لجنة الادارة المشتركة لحقل بدرة', 'NK Petroleum')
        self.assertEqual(prefer_jmc_committee(c, self.JMC), c)

    def test_empty_ranked_safe(self):
        self.assertEqual(prefer_jmc_committee([], self.JMC), [])


class MemorySelfMatchExclusionTests(TestCase):
    """قناع `exclude_book_id`: صفّ الكتاب نفسه لا يُصوِّت لنفسه (قياسٌ نظيف).

    الجذر المُقاس (2026-08-17): بلا القناع كان المستند يتعرّف على ترويسة **نفسه**
    المخزَّنة في LetterheadMemory فيُصوّت لها بتشابهٍ 1.0 — فأظهر القياسُ 73% للجهة
    المُصدِرة، وهو **تسريبٌ لا أداء**. نظيفاً: 60%. الإنتاج سليمٌ أصلاً (الكتاب الجديد
    بلا صفّ)، والمعطوب كان المسطرة. هذا الاختبار يمنع عودة التسريب."""

    def test_own_row_excluded_from_vote(self):
        head = 'شركة نفط الوسط قسم شؤون التراخيص البترولية العدد التاريخ'
        user = User.objects.create_user('leak', password='x')
        ent = Entity.objects.create(name='قسم شؤون التراخيص البترولية')
        book = Book.objects.create(title='ت', kind='incoming_internal', created_by=user)
        LetterheadMemory.objects.create(book=book, letterhead=head, issuing_entity=ent)

        em = EntityMatcher()
        self.assertTrue(em.match_from_memory(head, 'issuer'),
                        'الصفّ الوحيد يجب أن يُطابق حين لا إقصاء')
        self.assertEqual(em.match_from_memory(head, 'issuer', exclude_book_id=book.id), [],
                         'صفّ الكتاب نفسه يجب أن يُقصى ⟵ لا مرشّح')


class MemoryVoteCapTests(TestCase):
    """سقف مساهمات الجهة الواحدة: التواتر لا يشتري الصدارة.

    الجذر المُقاس: الترتيب كان بمجموعٍ **مفتوح** لكلّ صفوف الجهة، فجهةٌ بأربعين صفّاً
    متوسّط التشابه تسبق جهةً بصفّين ممتازين. مسحٌ على 1000 استعلامٍ مُجمَّد (LOO نظيف):
    ∞→46.3% مقابل 5→49.0%، ربح 40 خسارة 13، والاختيار يتكرّر على نصفٍ محجوز (+2.2)."""

    def test_two_excellent_rows_beat_many_mediocre(self):
        user = User.objects.create_user('cap', password='x')
        strong = Entity.objects.create(name='هيئة الاستثمار')
        noisy = Entity.objects.create(name='قسم الحسابات')
        head = 'جمهورية العراق هيئة الاستثمار الوطنية مكتب الرئيس'

        def _row(ent, text):
            bk = Book.objects.create(title='ت', kind='incoming_internal', created_by=user)
            LetterheadMemory.objects.create(book=bk, letterhead=text, issuing_entity=ent)

        for _ in range(2):
            _row(strong, head)                       # مطابقٌ تماماً — صفّان
        for i in range(20):                          # مُشوّشٌ مِكثار — عشرون صفّاً
            _row(noisy, f'جمهورية العراق قسم الحسابات شعبة {i} مكتب')

        got = EntityMatcher().match_from_memory(head, 'issuer', top_k=2)
        self.assertTrue(got, 'يجب أن تُرجَع مرشّحات')
        self.assertEqual(got[0]['entity_id'], strong.id,
                         'الصفّان الممتازان يجب أن يسبقا عشرين صفّاً متوسّطاً')


class OutgoingSenderFieldGateTests(SimpleTestCase):
    """حقول الجهة تُفرَّغ في الصادر **على الخادم** لا في الواجهة وحدها.

    قِيس في القاعدة (2026-08-18): **11 كتاباً صادراً** تحمل حقول جهةٍ تسرّبت
    (تاريخٌ في 2 · عددٌ في 9) من 1,777. المسار: رمز المسح يملأ الحقلين بلا شرط ولا
    يستدعي `syncKindUI`، فيحتفظ حقلٌ مخفيٌّ بقيمته ويُرسَل. والضرر أبعد من التجميل:
    `SenderNumberProfiles` يقرأ كلّ كتابٍ بعددِ جهةٍ **بلا مرشِّح نوع**، فصادرٌ ملوَّث
    يُدرّب قالبَ أرقامٍ لأحد أقسامنا كأنّه جهةٌ مُرسِلة."""

    def test_outgoing_kinds_are_emptied(self):
        from core.views.books_api import _strip_sender_fields_for_outgoing as gate
        for kind in ('outgoing_internal', 'outgoing_external'):
            self.assertEqual(gate(kind, '1754', '2026-08-13'), ('', ''), kind)

    def test_incoming_kinds_pass_through(self):
        from core.views.books_api import _strip_sender_fields_for_outgoing as gate
        for kind in ('incoming_internal', 'incoming_external', 'incoming'):
            self.assertEqual(gate(kind, '1754', '2026-08-13'), ('1754', '2026-08-13'), kind)

    def test_unknown_kind_is_treated_as_outgoing(self):
        """المجهول يُفرَّغ: خانةٌ فارغةٌ في الوارد تُصحَّح بنقرة، وقيمةٌ مفبركةٌ في
        الصادر تُسمّم قوالب الأرقام صامتةً."""
        from core.views.books_api import _strip_sender_fields_for_outgoing as gate
        for kind in ('', None, 'غير معروف'):
            self.assertEqual(gate(kind, '1754', '2026-08-13'), ('', ''), repr(kind))
