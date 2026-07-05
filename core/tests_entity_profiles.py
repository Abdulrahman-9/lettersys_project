# -*- coding: utf-8 -*-
"""اختبارات بصمة الجهة الاستخراجية — تعلّم قوالب الترقيم من الكتب المؤكَّدة.

يغطّي: استنتاج القالب، بناء نمط البحث (بادئات حرفية + رفض المبهم)، الفهرس من
قاعدة البيانات، الالتقاط الكامل من نصّ مشوّه، وأسبقية أول ظهور (رأس المستند)."""
from datetime import date

from django.contrib.auth.models import User
from django.test import TestCase

from core.extraction.matchers import profile as pf
from core.models import Book, Entity


def make_book(num, user, sender_number, entity):
    b = Book.objects.create(
        our_number=num, title='كتاب', date=date(2026, 1, 1),
        kind='incoming_external', created_by=user, sender_number=sender_number,
    )
    b.issuing_entities.add(entity)
    return b


class InduceTemplateTests(TestCase):
    def test_latin_compound(self):
        self.assertEqual(pf.induce_template('NK-20260237'), 'L2-D8')
        self.assertEqual(pf.induce_template('MF-2026-195'), 'L2-D4-D3')

    def test_arabic_prefix_and_digits(self):
        self.assertEqual(pf.induce_template('هغ/٨٨١'), 'ح2/D3')

    def test_bare_number(self):
        self.assertEqual(pf.induce_template('20260237'), 'D8')


class TemplateRegexTests(TestCase):
    def test_letter_prefixed_matches_garbled_context(self):
        rx = pf._template_regex('L2-D4-D3', {'MF', 'EBN'})
        m = rx.search('Reference Number: MF-2026-195 ,zrl9 junk')
        self.assertIsNotNone(m)
        self.assertEqual(m.group().replace(' ', ''), 'MF-2026-195')

    def test_flexible_separator(self):
        rx = pf._template_regex('L2-D8', {'NK'})
        self.assertIsNotNone(rx.search('Ref: NK - 20260237'))

    def test_bare_digit_template_rejected(self):
        # قالب أرقام مجرّدة مبهم (يطابق سنين/هواتف) — لا يُبنى له نمط بحث مباشر
        self.assertIsNone(pf._template_regex('D4', None))
        self.assertIsNone(pf._template_regex('D4', set()))

    def test_single_letter_prefix_rejected(self):
        # بادئة بحرف واحد (مثل «و») مبهمة — تُرفض
        self.assertIsNone(pf._template_regex('ح1/D3', {'و'}))

    def test_no_partial_match_inside_longer_number(self):
        rx = pf._template_regex('L2-D4', {'MF'})
        self.assertIsNone(rx.search('code XMF-2026 and MF-20261'))


class ProfileIndexTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('prof', password='p')
        self.zh = Entity.objects.create(name='Zhongman Babylon')
        self.profiles = pf.SenderNumberProfiles()

    def test_learns_and_finds_full_code(self):
        make_book('p-1', self.user, 'MF-2026-101', self.zh)
        make_book('p-2', self.user, 'MF-2026-150', self.zh)
        text = 'Babylon Oil\nReference Number: MF-2026-195 ,zrl9\nSubject: Meeting'
        hit = self.profiles.find(text, self.zh.id)
        self.assertIsNotNone(hit)
        self.assertEqual(hit.value, 'MF-2026-195')
        self.assertEqual(hit.template, 'L2-D4-D3')
        self.assertGreaterEqual(hit.confidence, 0.85)

    def test_single_example_lower_confidence(self):
        make_book('p-3', self.user, 'EBN-2025050', self.zh)
        hit = self.profiles.find('Ref: EBN-2026077', self.zh.id)
        self.assertIsNotNone(hit)
        self.assertEqual(hit.confidence, 0.75)

    def test_unknown_entity_returns_none(self):
        other = Entity.objects.create(name='جهة بلا تاريخ')
        self.assertIsNone(self.profiles.find('Ref: MF-2026-195', other.id))

    def test_first_occurrence_wins(self):
        # رقم المستند في الرأس يسبق الإحالات في المتن — الأوّل يفوز
        make_book('p-4', self.user, 'NK-20260001', self.zh)
        make_book('p-5', self.user, 'NK-20260002', self.zh)
        text = 'Ref: NK-20260237\nبالإشارة إلى كتابكم NK-20269999'
        hit = self.profiles.find(text, self.zh.id)
        self.assertEqual(hit.value, 'NK-20260237')

    def test_arabic_indic_digits_in_text(self):
        make_book('p-6', self.user, 'خل/123', self.zh)
        make_book('p-7', self.user, 'خل/456', self.zh)
        hit = self.profiles.find('العدد: خل/٧٨٩', self.zh.id)
        self.assertIsNotNone(hit)
        self.assertEqual(hit.value, 'خل/789')


class ContextPrefixLearningTests(TestCase):
    """تعلّم بادئة السياق من ذاكرة الترويسة: القيمة المخزَّنة رقمية مجرّدة
    («2026-101») لكن الترويسة تحمل الكود الكامل («MF-2026-101») — البصمة
    تكتشف البادئة من «كيف التُقط الرقم سابقاً» وتلتقط الكود الكامل مستقبلاً."""

    def setUp(self):
        from core.models import LetterheadMemory
        self.user = User.objects.create_user('ctx', password='p')
        self.zh = Entity.objects.create(name='Zhongman Babylon')
        for i, seq in enumerate(('101', '150')):
            b = make_book(f'c-{i}', self.user, f'2026-{seq}', self.zh)   # مخزَّن بلا بادئة
            LetterheadMemory.objects.create(
                letterhead=f'Zhongman Babylon Oil\nReference Number: MF-2026-{seq}\nTo: MdOC',
                issuing_entity=self.zh, book=b)
        self.profiles = pf.SenderNumberProfiles()

    def test_learns_ctx_prefix_and_captures_full_code(self):
        text = 'Babylon Oil\nReference Number: MF-2026-195 ,zrl9\nSubject: Meeting'
        hit = self.profiles.find(text, self.zh.id)
        self.assertIsNotNone(hit)
        self.assertEqual(hit.value, 'MF-2026-195')   # الكود الكامل، لا «195»

    def test_marker_words_not_learned_as_prefixes(self):
        from core.models import LetterheadMemory
        e = Entity.objects.create(name='جهة عربية')
        for i, seq in enumerate(('2216', '2301')):
            b = make_book(f'm-{i}', self.user, seq, e)
            LetterheadMemory.objects.create(
                letterhead=f'وزارة النفط\nNO {seq} التاريخ', issuing_entity=e, book=b)
        # «NO» علامة لا بادئة كود — يجب ألا تُتعلَّم فلا يُلتقط «NO 2216» ككود
        self.assertIsNone(self.profiles.find('NO 9999 نصّ آخر', e.id))
