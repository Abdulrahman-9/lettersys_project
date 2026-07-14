# -*- coding: utf-8 -*-
"""اختبارات core/extraction/matchers/pattern.py — استخراج البيانات بالأنماط.

دوال نقية (بلا DB): رقم الكتاب، التاريخ (عربي/رقمي)، السرية، النوع، التاريخ المرن.
"""
from datetime import datetime

from django.test import SimpleTestCase

from core.extraction.matchers.pattern import (
    PatternMatcher, DateParser, extract_structured_data, parse_date_flexible,
)


class DomainRulesTests(SimpleTestCase):
    """قوانين المجال التي أملاها المالك (شركة نفط الوسط / قسم المتابعة ش13)،
    مقيسة على 9,155 كتاباً مؤكَّداً — انظر تعليقات pattern.py."""

    def setUp(self):
        self.m = PatternMatcher()
        # ترويسة نظام إدارة الجودة كما في مستندات الشركة (صورة المالك)
        self.memo = (
            'وزارة النفط\n'
            'شركة نفط الوسط\n'
            'قسم الصحة والسلامة المهنية والبيئة\n'
            'مذكرة داخلية\n'
            'العدد: ش8/د/1844\n'
            'التاريخ: 19/7/2026\n'
            'الى / كافة الهيئات والاقسام المركزية\n'
            'م/ اجراءات ارتفاع درجات الحرارة\n'
            'نظراً لارتفاع درجات الحرارة …\n'
        )

    # ── رمز السجلّ: يُجرَّد من الرقم (عُرف الموظف: 99% رقمي صرف) ويُعاد إشارةً ──
    def test_arabic_register_code_stripped_from_number(self):
        num, _ = self.m.extract_sender_number(self.memo)
        self.assertEqual(num, '1844')                       # لا 'ش8/د/1844'

    def test_register_code_exposed_separately(self):
        self.assertEqual(self.m.extract_register_code(self.memo), 'ش8/د')

    def test_simple_department_code(self):
        num, _ = self.m.extract_sender_number('شركة نفط الوسط\nالعدد: ش13/2571\nالتاريخ:')
        self.assertEqual(num, '2571')
        self.assertEqual(
            self.m.extract_register_code('شركة نفط الوسط\nالعدد: ش13/2571\nالتاريخ:'), 'ش13')

    def test_space_separated_code_outgoing_external(self):
        """الصادر الخارجي: رقمه يأتي من مكتب المدير العام بصيغة «العدد: ش13 2571»
        (فاصلٌ مسافة، لا شرطة) — كان لا يُلتقط إطلاقاً قبل هذا الإصلاح."""
        doc = ('شركة نفط الوسط\nمكتب المدير العام\n'
               'العدد : ش13 2571\nالتاريخ: 19/7/2026\n'
               'الى / شركة النفط الوطنية\nم/ تخويل\n')
        num, _ = self.m.extract_sender_number(doc)
        self.assertEqual(num, '2571')
        self.assertEqual(self.m.extract_register_code(doc), 'ش13')
        self.assertEqual(self.m.extract_recipient(doc), 'شركة النفط الوطنية')

    def test_latin_company_code_kept_whole(self):
        """الوارد الخارجي: الموظف يُبقي كود الشركة (11% مقيسة) — لا نجرّده."""
        num, _ = self.m.extract_sender_number('EBS PETROLEUM\nRef: EBS-MdOC-20260603\nDate:')
        self.assertEqual(num, 'EBS-MdOC-20260603')
        self.assertIsNone(self.m.extract_register_code('EBS PETROLEUM\nRef: EBS-MdOC-20260603'))

    # ── نوع الوثيقة: مطبوعٌ في الترويسة (لا تعلّم آلة) ──
    def test_doc_type_broadcast_beats_internal_memo(self):
        """الإعمام يُعرَف من مُخاطَبه «كافة الهيئات والاقسام» ولو حملت الترويسة
        «مذكرة داخلية» — الأخصّ يفوز."""
        t, conf = self.m.extract_document_type(self.memo)
        self.assertEqual(t, 'اعمام')
        self.assertGreater(conf, 0.5)

    def test_doc_type_internal_memo(self):
        t, _ = self.m.extract_document_type(
            'شركة نفط الوسط\nقسم العقود\nمذكرة داخلية\nالعدد: ش4/12\nالى / قسم المتابعة')
        self.assertEqual(t, 'مذكرة داخلية')

    def test_doc_type_admin_order(self):
        t, _ = self.m.extract_document_type('شركة نفط الوسط\nامر اداري\nالعدد: 55')
        self.assertEqual(t, 'امر اداري')

    def test_doc_type_silent_when_absent(self):
        t, conf = self.m.extract_document_type('شركة نفط الوسط\nالعدد: 55\nالتاريخ: 1/1/2026')
        self.assertIsNone(t)
        self.assertEqual(conf, 0.0)

    # ── المُخاطَب: بعد «الى/» في الرأس ──
    def test_recipient_broadcast(self):
        self.assertEqual(self.m.extract_recipient(self.memo), 'كافة الهيئات والاقسام المركزية')

    def test_recipient_named_department(self):
        r = self.m.extract_recipient('شركة نفط الوسط\nالعدد: ش4/12\nالى / قسم المتابعة\nم/ كتاب')
        self.assertEqual(r, 'قسم المتابعة')

    def test_recipient_ignores_body_lines(self):
        self.assertIsNone(self.m.extract_recipient('شركة نفط الوسط\nالعدد: 12\nم/ موضوع\nالى / جهة في المتن'))

    # ── الحقول الأخرى تبقى سليمة على نفس المستند (لا تراجع) ──
    def test_memo_full_extraction_intact(self):
        data = self.m.extract_all_data(self.memo)
        self.assertEqual(data['sender_number'], '1844')
        self.assertTrue((data['sender_date'] or '').startswith('2026-07-19'))
        self.assertEqual(data['title'], 'اجراءات ارتفاع درجات الحرارة')
        self.assertEqual(data['document_type'], 'اعمام')
        self.assertEqual(data['register_code'], 'ش8/د')


class ExternalDateFormatsTests(SimpleTestCase):
    """صيغ التاريخ المطبوعة للجهات الخارجية — **كما قِيست** على 468 مستنداً رقمياً
    من 26 جهة (2026-07-14): لكل شركة صيغتها، وOCR يشوّه أسماء الأشهر."""

    def setUp(self):
        self.m = PatternMatcher()

    def _d(self, text):
        got, _c = self.m.extract_sender_date(text)
        return got.date().isoformat() if got else None

    def test_nk_month_day_comma_no_space(self):
        """NK: «June 20,2026» — الشكل الأشيع (20 مرة) وبلا مسافة بعد الفاصلة."""
        self.assertEqual(self._d('NK Petroleum\nDate: June 20,2026\nSubject: x'), '2026-06-20')

    def test_qurnain_month_day_comma_space(self):
        self.assertEqual(self._d('qurnain\nDate : April 26, 2026\nSubject'), '2026-04-26')

    def test_zhongman_day_month_year(self):
        """Zhongman: «16 March 2026»."""
        self.assertEqual(self._d('Zhongman\nDate: 16 March 2026\nSubject'), '2026-03-16')

    def test_ebs_month_day_no_comma(self):
        self.assertEqual(self._d('EBS PETROLEUM\nDate: May 16 2026\nSubject'), '2026-05-16')

    def test_abbreviated_month_with_period(self):
        """ZPEC: «07 Aug., 2025» — اختصارٌ بنقطة ثم فاصلة."""
        self.assertEqual(self._d('ZPEC\nDate: 07 Aug., 2025\nSubject'), '2025-08-07')

    def test_no_space_between_month_and_day(self):
        """«September2,2025» — التصاقٌ تامّ (كان يفلت من النمط القديم)."""
        self.assertEqual(self._d('Slb\nDate: September2,2025\nSubject'), '2025-09-02')

    def test_ocr_mangled_month_july(self):
        """«luly 5 2026» — OCR قرأ July خطأً (كتب EBS الممسوحة)."""
        self.assertEqual(self._d('EBS\nDate: luly 5 2026\nSubject'), '2026-07-05')

    def test_ocr_mangled_month_april(self):
        """«Aptil 23,2026» — OCR قرأ April خطأً (كتب BADRA)."""
        self.assertEqual(self._d('BADRA\nDate: Aptil 23,2026\nSubject'), '2026-04-23')

    def test_arabic_numeric_still_day_first(self):
        """الصيغة الرقمية تبقى يوم/شهر (العُرف العراقي) — لا تنقلب."""
        self.assertEqual(self._d('شركة نفط الوسط\nالتاريخ: 7/6/2026\nم/ x'), '2026-06-07')

    # ── ضجيج OCR بين العلامة والتاريخ (قراءةٌ بالعين لكتب صامتة، 2026-07-14) ──
    def test_semicolon_separator_and_backslash_date(self):
        """CNOOC #9389: «Date; 16\\ 4 \\ 2026» — فاصلةٌ منقوطة + شرطة مقلوبة."""
        self.assertEqual(self._d('CNOOC AFRICA\nRef:LSD\\ 179\nDate; 16\\ 4 \\ 2026\nTo\\ x'),
                         '2026-04-16')

    def test_ocr_read_colon_as_digit(self):
        """EBS #11189: «Date3 May 16 2026» — OCR قرأ النقطتين رقماً فالتصقت."""
        self.assertEqual(self._d('EBS Petroleum\nRef. No. EBS-MdOC-20260456\n'
                                 'Date3 May 16 2026\nSubject: ITP'), '2026-05-16')

    def test_month_glued_to_day_not_mangled_by_ocr_repair(self):
        """EBS #7064: «Date: April4, 2026» — إصلاحُ l→1 كان يفسدها إلى «Apri14»."""
        self.assertEqual(self._d('EBS Petroleum\nRef. No. EBS-MdOC-20260324\n'
                                 'Date: April4, 2026\nAttn.: Mr. x'), '2026-04-04')

    def test_ocr_digit_repair_only_on_numeric_tokens(self):
        r = PatternMatcher._repair_ocr_digits
        self.assertEqual(r('l8 February 2025'), '18 February 2025')   # رقمٌ مشوَّه
        self.assertEqual(r('2l April 2025'), '21 April 2025')
        self.assertEqual(r('April4, 2026'), 'April4, 2026')           # شهرٌ سليم لا يُمَسّ

    # ── علاماتٌ شوّهها OCR أو ألصقها (قراءةٌ بالعين لسبعة كتب صامتة) ──
    def test_label_mangled_dater(self):
        """qurnain #7021: «Dater March 16,2026» — النقطتان قُرِئتا حرف r."""
        self.assertEqual(self._d('QURNAIN\nRef. No. QPC-MoO-2026\nDater March 16,2026\nAttn:'),
                         '2026-03-16')

    def test_label_mangled_dete(self):
        """NK #7049: «Dete: March 30, 2026» — «Date» نفسها مقروءة خطأً."""
        self.assertEqual(self._d('NK\nDete: March 30, 2026\nTo : MdOC'), '2026-03-30')

    def test_label_glued_to_number(self):
        """Geo-Jade #7023: «Ref:ZU-20260015Date: March 20, 2026» — التصاقٌ برقم."""
        self.assertEqual(self._d('Geo-Jade\nRef:ZU-20260015Date: March 20, 2026\nTo: Mr. x'),
                         '2026-03-20')

    def test_label_glued_to_word(self):
        """Zhongman #11097: «JMC ChairmanDate: 09 Feb. 2026» — التصاقٌ بكلمة."""
        self.assertEqual(self._d('Zhongman\nReference Number; MF-2026-045\n'
                                 'cc: Mr. Sattar, JMC ChairmanDate: 09 Feb. 2026\nSubject: x'),
                         '2026-02-09')

    def test_bare_numeric_date_line_when_no_label(self):
        """BADRA #11040: نموذجٌ مطبوع بلا كلمة «Date» — سطرٌ عارٍ «24.10.2025 № AG-8748»."""
        doc = ('BADRA PROJECT\nRoyal Tulip Al-Rasheed Hotel, Office 335\n'
               'International Green Zone, Yafa Street, 8070\nBaghdad, Republic of Iraq\n'
               'www.badraproject.com\n24.10.2025  No  AG-8748\n'
               'Attn.: Mr. Mohammed Yaseen Hasan\nSubject: Bids technical evaluation\n')
        self.assertEqual(self._d(doc), '2025-10-24')

    def test_bare_line_does_not_beat_a_real_label(self):
        """السطر العاري ملاذٌ أخير: لا يزاحم علامةً صريحة."""
        doc = 'NK\n01.01.2020\nDate: March 30, 2026\nTo: MdOC\n'
        self.assertEqual(self._d(doc), '2026-03-30')

    def test_common_words_containing_date_are_not_labels(self):
        """«update/candidate/mandate» ليست علامات — والقيمة الصارمة تحرس ما بقي."""
        self.assertIsNone(self._d('We will update 20 March 2026 records\nحسب الخطة'))
        self.assertIsNone(self._d('The candidate 5 May 2026 was chosen'))

    def test_qms_table_date_rev_still_rejected(self):
        """«Date Rev / May 2025» في جدول الترويسة ليست تاريخ الكتاب."""
        doc = ('وزارة النفط\nشركة نفط الوسط\nمذكرة داخلية\n'
               'Rev No.  Date Rev  Doc.No.\nNo.1  May,2025  F-018Q\n'
               'العدد: ش/12 1556\nالتاريخ: 9/7/2026\nم/ صيانة\n')
        self.assertEqual(self._d(doc), '2026-07-09')     # لا 2025-05-xx

    def test_month_repair_does_not_touch_other_words(self):
        from core.extraction.matchers.pattern import repair_month_name
        self.assertEqual(repair_month_name('Dear Sir, Ref: MF-2026'), 'Dear Sir, Ref: MF-2026')
        self.assertEqual(repair_month_name('luly'), 'July')


class RealCompanyDocumentsTests(SimpleTestCase):
    """وثائق حقيقية من أرشيف المالك (صور مُرسَلة 2026-07-13) — كل حالةٍ قانونُ مجال:
    ترويسة نظام الجودة، رمز السجلّ بصيغه الثلاث، الإعمام بـ«كافة» متقدّمةً أو
    متأخّرة، والصادر الخارجي ثنائي اللغة."""

    def setUp(self):
        self.m = PatternMatcher()

    def test_it_department_slash_code(self):
        """قسم تقنية المعلومات: «العدد : ش/12 1556» — رمزٌ بشرطةٍ داخلية ثم مسافة."""
        doc = ('وزارة النفط\nشركة نفط الوسط\nقسم تقنية المعلومات\nمذكرة داخلية\n'
               'العدد : ش/12 1556\nالتاريخ : 9/7/2026\n'
               'الى / الهيئات والاقسام المركزية كافة\nم/ صيانة وقائية\n'
               'تحية طيبة …\nنظراً لأهمية المحافظة على جاهزية المعدات …\n')
        self.assertEqual(self.m.extract_sender_number(doc)[0], '1556')
        self.assertEqual(self.m.extract_register_code(doc), 'ش/12')   # ← لا «ش» وحدها
        self.assertEqual(self.m.extract_document_type(doc)[0], 'اعمام')
        self.assertEqual(self.m.extract_recipient(doc), 'الهيئات والاقسام المركزية كافة')
        self.assertEqual(self.m.extract_title_keywords(doc), 'صيانة وقائية')

    def test_broadcast_kaffa_leading(self):
        """«الى / كافة الهيئات والاقسام المركزية ( )» — كافة متقدّمة + قوس فارغ."""
        doc = ('شركة نفط الوسط\nقسم تقنية المعلومات\nمذكرة داخلية\n'
               'العدد : ش/12 1471\nالتاريخ : 14/7/2026\n'
               'الى / كافة الهيئات والاقسام المركزية ( )\n'
               'م/ إطلاق بوابة الموظف الإلكترونية\nتحية طيبة،\n')
        self.assertEqual(self.m.extract_document_type(doc)[0], 'اعمام')
        self.assertEqual(self.m.extract_title_keywords(doc), 'إطلاق بوابة الموظف الإلكترونية')
        self.assertEqual(self.m.extract_sender_number(doc)[0], '1471')

    def test_broadcast_with_manual_routing_paren(self):
        """قسم حماية المنشآت: «الى/ الهيئات و الاقسام المركزية كافة ( قسم المتابعة )»
        — القوس تأشيرٌ يدوي يُقتطع من اسم المُخاطَب."""
        doc = ('شركة نفط الوسط\nقسم حماية المنشآت النفطية\nمذكرة داخلية\n'
               'العدد: ح م/ 903\nالتاريخ: 21/3/2026\n'
               'الى/ الهيئات و الاقسام المركزية كافة ( قسم المتابعة )\n'
               'م/ توجيهات\nتحية طيبة،\n')
        self.assertEqual(self.m.extract_document_type(doc)[0], 'اعمام')
        self.assertEqual(self.m.extract_recipient(doc), 'الهيئات و الاقسام المركزية كافة')
        self.assertEqual(self.m.extract_sender_number(doc)[0], '903')
        self.assertEqual(self.m.extract_register_code(doc), 'حم')     # «ح م/» بلا مسافات

    def test_named_department_recipient(self):
        """قسم العقود → هيئة الحقول: مُخاطَبٌ مسمّى (لا إعمام)."""
        doc = ('شركة نفط الوسط\nقسم العقود\nمذكرة داخلية\n'
               'العدد: ش5/5005\nالتاريخ: 21/5/2026\n'
               'الى/ هيئة الحقول\nم / تمويل مشروعات\nتحية طيبة ..\n')
        self.assertEqual(self.m.extract_recipient(doc), 'هيئة الحقول')
        self.assertEqual(self.m.extract_document_type(doc)[0], 'مذكرة داخلية')
        self.assertEqual(self.m.extract_register_code(doc), 'ش5')
        self.assertEqual(self.m.extract_title_keywords(doc), 'تمويل مشروعات')

    def test_outgoing_external_dg_office(self):
        """صادر خارجي بترويسة الشركة ورقم مكتب المدير العام: «العدد: ش /13 7436»."""
        doc = ('جمهورية العراق\nوزارة النفط\nشركة نفط الوسط (شركة عامة)\n'
               'العدد: ش /13 7436\nالتاريخ: 30/4/2026\n'
               'الى / وزارة النفط / دائرة العقود والتراخيص البترولية\n'
               'م/ موقف مشاريع جولتي التراخيص التكميلية والسادسة\nتحية طيبة …\n')
        self.assertEqual(self.m.extract_sender_number(doc)[0], '7436')
        self.assertEqual(self.m.extract_register_code(doc), 'ش/13')
        self.assertEqual(self.m.extract_recipient(doc), 'وزارة النفط / دائرة العقود والتراخيص البترولية')
        self.assertEqual(self.m.extract_sender_date(doc)[0].date().isoformat(), '2026-04-30')

    def test_outgoing_external_bilingual(self):
        """صادر خارجي ثنائي اللغة (قانون جديد): Ref/Date/To/Subject إنكليزية
        بجوار العربية — الأولوية للعربية في الموضوع، والرقم/التاريخ من أيّهما."""
        doc = ('Republic of Iraq\nMinistry of Oil\nMidland Oil Company\n'
               'جمهورية العراق\nوزارة النفط\nشركة نفط الوسط\n'
               'Ref : 7298\nDate : 28/4/2026\n'
               'To: Anwar alsuda Trade and General Contracting\n'
               'الى / شركة انوار السدة للتجارة والمقاولات العامة محدودة المسؤولية\n'
               'Subject/ A Letter of Interest\nالموضوع/ A Letter of Interest\n'
               'Greetings,\nتحية طيبة.\n')
        self.assertEqual(self.m.extract_sender_number(doc)[0], '7298')
        self.assertEqual(self.m.extract_sender_date(doc)[0].date().isoformat(), '2026-04-28')
        # المُخاطَب: السطر العربي هو المعتمد (يسبق «To» في الفحص لأنه أعلى؟ لا —
        # نقبل أيّهما ما دام يطابق الجهة نفسها؛ نثبت أنّ الالتقاط لا يفشل)
        self.assertIn(self.m.extract_recipient(doc),
                      ('Anwar alsuda Trade and General Contracting',
                       'شركة انوار السدة للتجارة والمقاولات العامة محدودة المسؤولية'))
        self.assertEqual(self.m.extract_title_keywords(doc), 'A Letter of Interest')

    def test_hr_broadcast_circulars(self):
        """هيئة الموارد البشرية: «الــى / الهيئات والاقسام المركزية كافة» (تطويل)
        + «م/ تعاميم» → إعمام."""
        doc = ('شركة نفط الوسط\nهيئة ادارة وتنمية الموارد البشرية\nمذكرة داخلية\n'
               'العدد: د/4288\nالتاريخ : 15/7/2026\n'
               'الــى / الهيئات والاقسام المركزية كافة\nم/ تعاميم\nتحية طيبة ،\n')
        self.assertEqual(self.m.extract_document_type(doc)[0], 'اعمام')
        self.assertEqual(self.m.extract_register_code(doc), 'د')
        self.assertEqual(self.m.extract_sender_number(doc)[0], '4288')
        self.assertEqual(self.m.extract_recipient(doc), 'الهيئات والاقسام المركزية كافة')


class ExtractBookNumberTests(SimpleTestCase):
    def setUp(self):
        self.m = PatternMatcher()

    def test_labeled_number(self):
        num, conf = self.m.extract_book_number('رقم الكتاب: 123')
        self.assertEqual(num, '123')
        self.assertGreater(conf, 0)

    def test_kitab_raqm(self):
        num, _ = self.m.extract_book_number('كتاب رقم 456')
        self.assertEqual(num, '456')

    def test_bare_number(self):
        num, _ = self.m.extract_book_number('12345')
        self.assertEqual(num, '12345')

    def test_no_number(self):
        self.assertEqual(self.m.extract_book_number('نص بلا أرقام'), (None, 0.0))

    def test_labeled_has_higher_confidence_than_bare(self):
        _, labeled = self.m.extract_book_number('رقم الكتاب: 123')
        _, bare = self.m.extract_book_number('45678')
        self.assertGreater(labeled, bare)   # المعنون أوثق من رقم مجرّد


class ExtractDateTests(SimpleTestCase):
    def setUp(self):
        self.m = PatternMatcher()

    def test_arabic_month(self):
        d, conf = self.m.extract_date('بتاريخ 15 من يناير 2024')
        self.assertEqual((d.year, d.month, d.day), (2024, 1, 15))
        self.assertGreater(conf, 0.9)

    def test_numeric_dmy(self):
        d, _ = self.m.extract_date('التاريخ 15-01-2024')
        self.assertEqual((d.year, d.month, d.day), (2024, 1, 15))

    def test_iso_fallback(self):
        d, _ = self.m.extract_date('Created 2024-03-10 by user')
        self.assertEqual((d.year, d.month, d.day), (2024, 3, 10))

    def test_no_date(self):
        self.assertEqual(self.m.extract_date('بلا تاريخ هنا'), (None, 0.0))

    def test_impossible_date_rejected(self):
        self.assertEqual(self.m.extract_date('45-13-2024'), (None, 0.0))


class ExtractSenderDateTests(SimpleTestCase):
    def setUp(self):
        self.m = PatternMatcher()

    def test_header_date_extracted(self):
        d, _c = self.m.extract_sender_date(
            'جمهورية العراق\nالعدد: 123\nالتاريخ: 2026/6/9\nالموضوع: كذا')
        self.assertIsNotNone(d)
        self.assertEqual((d.year, d.month, d.day), (2026, 6, 9))

    def test_arabic_indic_digits(self):
        d, _c = self.m.extract_sender_date('التاريخ: ٢٠٢٦/٦/٩')
        self.assertIsNotNone(d)
        self.assertEqual(d.year, 2026)

    def test_no_header_date(self):
        self.assertEqual(self.m.extract_sender_date('لا تاريخ ترويسة'), (None, 0.0))

    def test_english_date_month_name(self):
        # إيميل إنجليزي: Date: June 20, 2026
        d, _c = self.m.extract_sender_date('NK Petroleum\nDate: June 20, 2026 Ref: NK-1\nTo: x')
        self.assertIsNotNone(d)
        self.assertEqual((d.year, d.month, d.day), (2026, 6, 20))

    def test_english_date_day_first(self):
        d, _c = self.m.extract_sender_date('Dated: 20 June 2026')
        self.assertIsNotNone(d)
        self.assertEqual((d.year, d.month, d.day), (2026, 6, 20))

    def test_english_date_numeric(self):
        d, _c = self.m.extract_sender_date('Date: 20/06/2026')
        self.assertIsNotNone(d)
        self.assertEqual((d.year, d.month, d.day), (2026, 6, 20))

    def test_garbled_layer_date_recovered(self):
        # طبقة مسح مشوَّهة: «Jul 2, 2026» → «lul 22026» (J→l + فاصلة ساقطة) —
        # حالة حقيقية من إيميل QPC ممرَّر عبر ماسحة مكتب
        d, _c = self.m.extract_sender_date('Ref. No. QPC-1\nDate: lul 22026\nSubject: x')
        self.assertIsNotNone(d)
        self.assertEqual((d.year, d.month, d.day), (2026, 7, 2))

    def test_garbled_month_sibling(self):
        d, _c = self.m.extract_sender_date('Date: Ian 5, 2026')   # Jan بحرف I
        self.assertIsNotNone(d)
        self.assertEqual((d.year, d.month, d.day), (2026, 1, 5))

    def test_degarble_confined_to_date_zone(self):
        # «lul» خارج نافذة التاريخ لا يُمَسّ — التصحيح محصور بعد العلامة
        d, _c = self.m.extract_sender_date('lul 22026 بلا علامة تاريخ')
        self.assertIsNone(d)

    def test_body_citation_date_ignored(self):
        # حالة #11222 الحقيقية: تاريخ الكتاب فارغ (يدوي) وإحالة «بتأريخ» في المتن —
        # يجب None لا تاريخ الإحالة (تاريخ خاطئ أسوأ من فراغ)
        text = ('جمهورية العراق\nوزارة النفط\nالتاريخ: / /\nإلى / المقاولين كافة\n'
                'م / تجهيز أنابيب النفط والغاز من شركة\nعمران التركية\n'
                'نرافق لكم نسخة من كتاب الوزارة المرقم 11\nبتأريخ 2026/5/3 المتضمن الدراسة')
        self.assertIsNone(self.m.extract_sender_date(text)[0])

    def test_ba_prefixed_date_label_rejected(self):
        # «بتأريخ/بالتاريخ» ظرف إحالة لا تسمية حقل — تُرفض حتى في الرأس
        self.assertIsNone(self.m.extract_sender_date('العدد: 5\nبتأريخ 2026/5/3\nإلى فلان')[0])

    def test_header_date_beyond_cap_ignored(self):
        # علامة تاريخ بعد سقف منطقة الرأس (15 سطراً) لا تُلتقط
        filler = '\n'.join(f'سطر حشو {i}' for i in range(16))
        self.assertIsNone(self.m.extract_sender_date(filler + '\nالتاريخ: 2026/6/9')[0])

    def test_bare_date_line_in_header(self):
        # قالب Slb الغربي: التاريخ سطرٌ عارٍ أول الرسالة بلا «Date:» (حالة حيّة)
        d, _c = self.m.extract_sender_date('July 6 , 2026\nLetter Reference 135\nTo: MdOC')
        self.assertIsNotNone(d)
        self.assertEqual((d.year, d.month, d.day), (2026, 7, 6))

    def test_bare_date_only_when_whole_line(self):
        # تاريخٌ داخل جملة (إحالة) ليس سطرَ تاريخٍ عارياً — لا يُلتقط
        self.assertIsNone(self.m.extract_sender_date(
            'نشير الى كتابكم المؤرخ 2026/5/3 بخصوص التعيينات')[0])


class TitleWrapJoinTests(SimpleTestCase):
    """ضمّ تتمّة الموضوع الملتفّ — حالة #11222 + الموانع (توصية استشارية)."""

    def setUp(self):
        self.m = PatternMatcher()

    def test_wrapped_arabic_subject_joined(self):
        text = ('وزارة النفط\nإلى / المقاولين كافة\n'
                'م / تجهيز أنابيب النفط والغاز من شركة\nعمران التركية\nنرافق لكم نسخة')
        t = self.m.extract_title_keywords(text)
        self.assertIn('عمران', t)
        self.assertIn('التركية', t)

    def test_body_opener_never_joined(self):
        text = 'م / تعميم ضوابط الدوام الرسمي للموظفين\nنرافق لكم نسخة من الضوابط'
        self.assertNotIn('نرافق', self.m.extract_title_keywords(text))

    def test_english_salutation_not_joined(self):
        text = 'Subject: Coordination on Gas Pipeline Hot Tapping Activities\nDear Sir,'
        self.assertNotIn('Dear', self.m.extract_title_keywords(text))

    def test_short_complete_subject_not_joined(self):
        # موضوع قصير مكتمل (<20 محرفاً، لا ينتهي بكلمة ربط) — لا ضمّ
        self.assertEqual(self.m.extract_title_keywords('م / الإجازات\nكافة الأقسام مدعوة'),
                         'الإجازات')

    def test_wrapped_english_subject_joined(self):
        # حالة 195 الحقيقية: Subject ملتفّ لسطر ثانٍ
        text = ('Subject: Request Meeting with Ministerial Cost Team (MCT) to Discuss\n'
                'Estimate for MF Drilling Project\nDear Mr. Hassan,')
        t = self.m.extract_title_keywords(text)
        self.assertIn('Estimate', t)

    def test_m_marker_with_invisible_mark_beats_ila_line(self):
        # بلاغ المالك: «م‏/» (بعلامة RTL خفية) كانت تفشل فيُلتقط سطر «إلى/» موضوعاً —
        # م/ هي الدلالة الأقوى دائماً ويجب أن تفوز
        text = ('وزارة النفط\nإلى/ الجهات كافة\nم‏/ ضوابط منح الإجازات الدراسية\nتحية طيبة')
        t = self.m.extract_title_keywords(text)
        self.assertIn('ضوابط', t)
        self.assertNotIn('الجهات', t)

    def test_ila_line_never_title_even_without_m(self):
        # حتى بلا م/ إطلاقاً: سطر المُرسَل إليه يُتخطّى لأول سطر جوهري بعده
        text = 'إلى / المقاولين المشغلين كافة\nتعليمات الصرف للموازنة التشغيلية المحدثة'
        t = self.m.extract_title_keywords(text)
        self.assertNotIn('المقاولين', t)
        self.assertIn('تعليمات', t)

    def test_bilingual_columns_arabic_wins_regardless_of_order(self):
        # كتب بعمودين (عربي + ترجمة إنكليزية): OCR قد يُخرج Subject قبل م/ —
        # العربية (الأصل المعتمد) تفوز دائماً (توجيه مالك)
        text = ('Subject: Approval of the Operational Budget Instructions\n'
                'م/ تعليمات الموازنة التشغيلية\nتحية طيبة')
        t = self.m.extract_title_keywords(text)
        self.assertIn('الموازنة', t)
        self.assertNotIn('Approval', t)

    def test_english_only_doc_still_uses_subject(self):
        # مستند إنكليزي صرف (لا علامة عربية): Subject يعمل كما كان
        t = self.m.extract_title_keywords('NK Petroleum\nSubject: Gas Pipeline Coordination\nDear Sir')
        self.assertIn('Pipeline', t)

    def test_full_width_body_line_not_joined(self):
        # بلاغ مالك حيّ: بعد م/ سليمة، سطرُ متنٍ كامل العرض («حرصاً على…») ضُمّ خطأً —
        # بوّابة الطول (>45) تصدّه حتى لو غابت افتتاحيته من القائمة
        text = ('م/ معوقات عمل قسم الرقابة والتدقيق الداخلي\n'
                'سعياً الى تحقيق افضل النتائج في تقويم الاداء وتطوير اجراءات العمل النافذة')
        t = self.m.extract_title_keywords(text)
        self.assertIn('معوقات', t)
        self.assertNotIn('تقويم', t)


class ExtractSenderNumberTests(SimpleTestCase):
    """رقم صادر الجهة المطبوع (إيميلات/مكتوب): كودٌ مركّب بعد العدد/ref، لا الفاكس."""
    def setUp(self):
        self.m = PatternMatcher()

    def test_compound_code_after_aladad(self):
        n, c = self.m.extract_sender_number('شركة النفط\nالعدد: KHL/25/32\nالموضوع: كذا')
        self.assertEqual(n, 'KHL/25/32')
        self.assertGreater(c, 0)

    def test_english_ref_marker(self):
        n, _c = self.m.extract_sender_number('From: x\nRef: EMDOC-2025-043\nBody')
        self.assertEqual(n, 'EMDOC-2025-043')

    def test_bare_number_after_ref(self):
        # رقمٌ مجرّد بعد علامة صريحة (بلا بادئة) — يُلتقط أيضاً
        n, _c = self.m.extract_sender_number('Date: June 20\nRef: 20260237\nTo: x')
        self.assertEqual(n, '20260237')

    def test_prefix_compound_preferred(self):
        # حين توجد بادئة، يُلتقط الكود المركّب كاملاً (NK-...) لا الرقم المجرّد
        n, _c = self.m.extract_sender_number('Ref: NK-20260237')
        self.assertEqual(n, 'NK-20260237')

    def test_arabic_indic_digits_normalized(self):
        n, _c = self.m.extract_sender_number('العدد: هغ/٨٨١')
        self.assertIsNotNone(n)
        self.assertTrue(n.endswith('881'))

    def test_fax_number_ignored(self):
        # رقمٌ بعد «فاكس» ليس رقم صادر — يجب تجاهله
        self.assertEqual(self.m.extract_sender_number('فاكس: 00964-1/2345'), (None, 0.0))

    def test_no_number(self):
        self.assertEqual(self.m.extract_sender_number('نصّ بلا رقم مرجعي'), (None, 0.0))

    def test_adad_slash_form(self):
        # توجيه المالك المُتحقَّق (53% من الكتب فيها «العدد» رأسياً): «العدد / 1754»
        # (الرقم الثلاثي «585» مؤجَّل خلف بوّابة بصمة الجهة — خفضُ الأرضية قِيس
        # فرفع الكاذبة 9→23 بخربشات خط اليد)
        self.assertEqual(self.m.extract_sender_number('جمهورية العراق\nالعدد /1754\nالتاريخ:')[0], '1754')
        self.assertIsNone(self.m.extract_sender_number('جمهورية العراق\nالعدد /585\nالتاريخ:')[0])

    def test_adad_with_invisible_mark(self):
        # ثاني أشيع «فاصل» بعد العدد في 331 كتاباً: علامة LRM الخفية (48 كتاباً)
        self.assertEqual(self.m.extract_sender_number('وزارة النفط\nالعدد‎ 1754\nإلى')[0], '1754')

    def test_arabic_digits_slash_letter(self):
        # صيغة عربية شائعة: رقم ثم حرف سجلّ (و=وارد، ص=صادر) — «241/و».
        # تغيّر السلوك عمداً (2026-07-13): الحرف يُجرَّد ويبقى التسلسل — عُرفُ
        # الموظف المقيس على 9,155 كتاباً (الوارد الداخلي 99% رقمي صرف).
        self.assertEqual(self.m.extract_sender_number('العدد: 241/و')[0], '241')
        self.assertEqual(self.m.extract_sender_number('الرقم 12/ص')[0], '12')

    def test_reference_number_marker(self):
        # «Reference Number» علامة كاملة — لا «ref» فقط (الذي يفشل داخل «Reference»)
        n, _c = self.m.extract_sender_number('Reference Number: MF-2026-195')
        self.assertEqual(n, 'MF-2026-195')

    def test_body_citation_number_ignored(self):
        # 41/45 إيجابية كاذبة مقيسة: «العدد» في إحالة متن تحت سطر الموضوع — تُرفض
        text = ('جمهورية العراق\nالعدد: \nالموضوع: متابعة\n'
                'اشارة الى الامر الوزاري العدد 5978 في 2025/1/3 نرجو الاطلاع')
        self.assertIsNone(self.m.extract_sender_number(text)[0])

    def test_ba_prefixed_adad_rejected(self):
        # «بالعدد» ظرف إحالة لا تسمية حقل — تُرفض حتى في الرأس
        self.assertIsNone(self.m.extract_sender_number('كتاب الشركة بالعدد 26910 المؤرخ')[0])

    def test_header_adad_beyond_cap_ignored(self):
        filler = '\n'.join(f'سطر حشو {i}' for i in range(16))
        self.assertIsNone(self.m.extract_sender_number(filler + '\nالعدد: 1234')[0])

    def test_dotted_ref_no_and_two_segment_code(self):
        # حالة EBS الحيّة: «Ref. No.» بنقطة + كود بمقطعين حرفيين وأرقام ملتصقة
        n, _c = self.m.extract_sender_number('EBSPetroleum\nRef. No. EBS-MdOC20260594\nDate: July 3')
        self.assertEqual(n, 'EBS-MdOC20260594')

    def test_two_segment_code_with_spaces(self):
        # حالة QPC الحيّة: مسافة بعد الشرطة الأولى
        n, _c = self.m.extract_sender_number('Ref. No. QPC- MdOC-20260083\nSubject: x')
        self.assertEqual(n, 'QPC-MdOC-20260083')

    def test_reference_to_prose_still_ignored(self):
        # «reference to …» النثرية لا تُلتقط (لا كود بعدها)
        self.assertIsNone(self.m.extract_sender_number(
            'With reference to single source tender discussions held earlier')[0])


class SplitRefFromTitleTests(SimpleTestCase):
    """نمط Slb: رقم الصادر داخل سطر الموضوع («Ref-135, Akkas…») — يُقتطع ويُنظَّف."""

    def setUp(self):
        self.m = PatternMatcher()

    def test_slb_real_saved_titles(self):
        # عناوين محفوظة حرفياً من كتب المالك (#11238، #11188)
        n, t = self.m.split_ref_from_title('Ref-135 Akkas-8 Abandonment and Sidetrack Program, MdOC-F-25069')
        self.assertEqual(n, '135')
        self.assertTrue(t.startswith('Akkas-8'))
        n2, t2 = self.m.split_ref_from_title('ref-129, Akkas tubing requirements , mdoc -F-25069')
        self.assertEqual(n2, '129')
        self.assertTrue(t2.startswith('Akkas'))

    def test_plain_title_untouched(self):
        n, t = self.m.split_ref_from_title('Submission of Weekly Report No 11')
        self.assertIsNone(n)
        self.assertEqual(t, 'Submission of Weekly Report No 11')

    def test_reference_prose_not_split(self):
        # «Reference is made…» نثرٌ لا كود — لا اقتطاع
        n, _t = self.m.split_ref_from_title('Reference is made to your letter regarding the pipeline')
        self.assertIsNone(n)


class ExtractSecretLevelTests(SimpleTestCase):
    def setUp(self):
        self.m = PatternMatcher()

    def test_topsecret_wins_over_secret(self):
        lvl, _ = self.m.extract_secret_level('وثيقة سري للغاية')
        self.assertEqual(lvl, 'topsecret')

    def test_secret(self):
        self.assertEqual(self.m.extract_secret_level('ملف سري')[0], 'secret')

    def test_normal(self):
        self.assertEqual(self.m.extract_secret_level('كتاب اعتيادي')[0], 'normal')

    def test_none(self):
        self.assertEqual(self.m.extract_secret_level('بلا تصنيف'), (None, 0.0))


class ExtractBookKindTests(SimpleTestCase):
    def setUp(self):
        self.m = PatternMatcher()

    def test_incoming_arabic(self):
        self.assertEqual(self.m.extract_book_kind('كتاب وارد')[0], 'incoming')

    def test_outgoing_arabic(self):
        self.assertEqual(self.m.extract_book_kind('كتاب صادر')[0], 'outgoing')

    def test_incoming_english(self):
        self.assertEqual(self.m.extract_book_kind('INCOMING letter')[0], 'incoming')

    def test_none(self):
        self.assertEqual(self.m.extract_book_kind('نص محايد'), (None, 0.0))


class DateParserTests(SimpleTestCase):
    def test_iso(self):
        self.assertEqual(DateParser.parse('2024-01-15').date().isoformat(), '2024-01-15')

    def test_arabic_month_name(self):
        d = DateParser.parse('15 آذار 2024')
        self.assertEqual((d.year, d.month, d.day), (2024, 3, 15))

    def test_invalid_returns_none(self):
        self.assertIsNone(DateParser.parse('ليس تاريخاً'))
        self.assertIsNone(DateParser.parse(''))
        self.assertIsNone(DateParser.parse(None))

    def test_format_date(self):
        self.assertEqual(DateParser.format_date(datetime(2024, 1, 15)), '2024-01-15')


class HelpersTests(SimpleTestCase):
    def test_extract_structured_data_keys(self):
        data = extract_structured_data('كتاب وارد سري رقم الكتاب: 99 بتاريخ 15-01-2024')
        for key in ('book_number', 'date', 'secret_level', 'book_kind', 'entities', 'title'):
            self.assertIn(key, data)
        self.assertEqual(data['book_kind'], 'incoming')
        self.assertEqual(data['secret_level'], 'secret')

    def test_parse_date_flexible(self):
        self.assertEqual(parse_date_flexible('2024-01-15').date().isoformat(), '2024-01-15')
