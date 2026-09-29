"""
الأضبارةُ ليست بابَ خلفٍ للسرّيّ — البحثُ والعرضُ والتقريرُ المطبوع.

قِيس على القاعدة الحيّة: عضوُ قسمٍ عاديّ يرى صفوفَ السرّيّ في الأضبارة
(صحيح — «السرّي يُحفظ في السجلّ عاديّ»)، لكنّ الأضبارةَ كانت تطبع عنوانَه
وهامشَه خامَين، و``?q=`` فيها بلا حارس: كلمةٌ من العنوان أو الهامش تُعيد
الكتاب — أداةُ استنطاق. والقائمةُ الموحّدة أُغلقت سلفاً (``tests_secrecy``)،
وهذه الاختباراتُ تسأل الأضبارةَ الأسئلةَ نفسَها **على HTML المُصيَّر**.

ومراجعةُ فيبل (2026-09-27) وجدت ما لا يُطبع لكنّه يُجيب: الفرزُ بالعنوان يضع
المحجوبَ في موضع عنوانه الحقيقيّ، والبحثُ الرقميُّ يطابق رقمَ الجهة والهامش،
ونوعُ المستند يُسمّي ملفَّ الكتاب المحجوب — وكان الاتجاهُ الواردُ بلا اختبار.
"""

import re

from django.urls import reverse

from core.models import Book, Entity
from core.scoping import STUB_TITLE
from core.tests_secrecy import SecrecyTestCase
from core.views.filter_helpers import BookSortEngine

SECRET_TITLE = 'مناقصةُ الحفر السرّيّة'
SECRET_MARGIN = 'هامشٌ حسّاس'
SECRET_TYPE = 'عقد توريد خاص'
COUNTERPART = 'لجنة العطاءات المغلقة'

# الكتابُ السرّيُّ **الوارد** إلى الأضبارة: الجهةُ مستلِمتُه، والمورّدُ مُصدِرُه.
SECRET_IN_TITLE = 'عرضُ المعدّات المختوم'
SECRET_IN_MARGIN = 'تأمينٌ بمبلغ 95000 وكفالةٌ 1234567'
SECRET_IN_TYPE = 'عرض سعر مغلق'
SUPPLIER = 'مورّدُ المعدّات الخاصّة'

#: سلّةُ الكتب بلا نوع — وفيها يسكن المقيَّدُ عند مَن لا يملك محتواه.
MISC_FOLDER = 'متفرقة'

_REPORT_NUMBERS = re.compile(r'<td class="num">([^<]+)</td>')
_DETAIL_NUMBERS = re.compile(r'<a class="num" href="[^"]*">([^<]+)</a>')


class DossierSecrecyTestCase(SecrecyTestCase):
    """أضبارةُ جهةٍ واحدة بالاتجاهين: العلنيُّ والسرّيُّ صادران منها، والسرّيُّ
    الثاني واردٌ إليها من مورّدٍ لا يظهر اسمُه لمن لا يملك المحتوى."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.entity = Entity.objects.create(name='شركة الحفر الوطنية', code='DRL')
        cls.counterpart = Entity.objects.create(name=COUNTERPART, code='BID')
        cls.supplier = Entity.objects.create(name=SUPPLIER, code='SUP')
        Book.objects.filter(pk=cls.secret.pk).update(document_type=SECRET_TYPE)
        cls.secret.issuing_entities.add(cls.entity)
        cls.secret.receiving_entities.add(cls.counterpart)
        cls.plain.issuing_entities.add(cls.entity)

        cls.secret_in = Book.objects.create(
            kind='incoming_internal', title=SECRET_IN_TITLE, created_by=cls.author,
            department=cls.dept, our_number='2441', secret_level='topsecret',
            sender_number='ع/02441', legacy_number='قديم-5-12',
            margin=SECRET_IN_MARGIN, document_type=SECRET_IN_TYPE,
        )
        cls.secret_in.issuing_entities.add(cls.supplier)
        cls.secret_in.receiving_entities.add(cls.entity)

    def _folder(self, user):
        """ملفُّ النوع الذي يسكنه السرّيُّ **في عين قارئه**: نوعُه لمن يملكه،
        و«متفرقة» للكاتب — نوعُ المحجوب محجوبٌ كعنوانه."""
        return MISC_FOLDER if user == self.clerk else SECRET_TYPE

    def _detail(self, user, **params):
        """التفصيلُ داخل ملفّ النوع — حيث تُصيَّر الصفوف (خارجه بطاقاتُ مجلّدات)."""
        self.client.force_login(user)
        params.setdefault('document_type', self._folder(user))
        resp = self.client.get(reverse('dossier_detail', args=[self.entity.pk]), params)
        self.assertEqual(resp.status_code, 200)
        return resp

    def _report(self, user, **params):
        self.client.force_login(user)
        resp = self.client.get(reverse('dossier_report', args=[self.entity.pk]), params)
        self.assertEqual(resp.status_code, 200)
        return resp

    def _card(self, user, book=None):
        return self._report(user, book_id=(book or self.secret).pk)

    def _unified(self, user, **params):
        self.client.force_login(user)
        params.setdefault('tab', 'all')
        resp = self.client.get('/books/api/unified/data/', params)
        self.assertEqual(resp.status_code, 200)
        return [b['our_number'] for b in resp.json()['books']]

    @property
    def secret_url(self):
        return reverse('book_detail', args=[self.secret.pk])

    @property
    def secret_in_url(self):
        return reverse('book_detail', args=[self.secret_in.pk])


class DossierSearchIsNotAnInterrogationToolTests(DossierSecrecyTestCase):
    """T1 — كلمةٌ من العنوان أو الهامش لا تُعيد السرّيَّ لعضو القسم."""

    def test_title_word_finds_nothing_in_detail(self):
        resp = self._detail(self.clerk, q='مناقصة')
        self.assertEqual(resp.context['total_count'], 0)
        self.assertNotContains(resp, self.secret_url)
        self.assertNotContains(resp, SECRET_TITLE)

    def test_margin_word_finds_nothing_in_detail(self):
        resp = self._detail(self.clerk, q='حسّاس')
        self.assertEqual(resp.context['total_count'], 0)
        self.assertNotContains(resp, self.secret_url)
        self.assertNotContains(resp, SECRET_MARGIN)

    def test_title_word_finds_nothing_in_report(self):
        resp = self._report(self.clerk, q='مناقصة')
        self.assertEqual(resp.context['total_count'], 0)
        self.assertNotContains(resp, '<td class="num">2437</td>', html=False)
        self.assertNotContains(resp, SECRET_TITLE)

    def test_margin_word_finds_nothing_in_report(self):
        resp = self._report(self.clerk, q='حسّاس')
        self.assertEqual(resp.context['total_count'], 0)
        self.assertNotContains(resp, '<td class="num">2437</td>', html=False)
        self.assertNotContains(resp, SECRET_MARGIN)

    def test_plain_text_search_still_works(self):
        """الحارسُ يستثني السرّيَّ وحده — البحثُ النصّيُّ في العلنيّ باقٍ."""
        resp = self._report(self.clerk, q='علنيّ')
        self.assertEqual(resp.context['total_count'], 1)
        self.assertContains(resp, 'كتابٌ علنيّ')


class DossierRowIsStubbedTests(DossierSecrecyTestCase):
    """T2 — الرقمُ يجده (الدفترُ يكشفه)، والمظروفُ مغلق في كلّ سطحٍ مطبوع."""

    def test_number_search_finds_the_stub_row_in_detail(self):
        resp = self._detail(self.clerk, q='2437')
        self.assertEqual(resp.context['total_count'], 1)
        self.assertContains(resp, self.secret_url)
        self.assertContains(resp, f'<td>{STUB_TITLE}</td>', html=False)
        self.assertNotContains(resp, SECRET_TITLE)
        self.assertNotContains(resp, SECRET_TYPE)
        self.assertNotContains(resp, COUNTERPART)

    def test_number_search_finds_the_stub_row_in_report(self):
        resp = self._report(self.clerk, q='2437')
        self.assertEqual(resp.context['total_count'], 1)
        self.assertContains(resp, '<td class="num">2437</td>', html=False)
        self.assertContains(resp, f'<td>{STUB_TITLE}</td>', html=False)
        self.assertNotContains(resp, SECRET_TITLE)
        self.assertNotContains(resp, SECRET_TYPE)
        self.assertNotContains(resp, COUNTERPART)

    def test_full_report_prints_the_stub_not_the_title(self):
        resp = self._report(self.clerk)
        self.assertContains(resp, f'<td>{STUB_TITLE}</td>', html=False)
        self.assertNotContains(resp, SECRET_TITLE)
        self.assertNotContains(resp, SECRET_MARGIN)

    def test_book_card_prints_the_stub_and_no_margin(self):
        resp = self._card(self.clerk)
        self.assertContains(resp, 'بطاقة كتاب')
        self.assertContains(resp, f'<div class="bc-v">{STUB_TITLE}</div>', html=False)
        self.assertNotContains(resp, SECRET_TITLE)
        self.assertNotContains(resp, SECRET_MARGIN)
        self.assertNotContains(resp, '<div class="bc-k">ملاحظات</div>', html=False)
        self.assertNotContains(resp, SECRET_TYPE)
        self.assertNotContains(resp, COUNTERPART)


class IncomingDirectionIsStubbedTests(DossierSecrecyTestCase):
    """نصفُ الأضبارة الثاني — الواردُ إليها: جدولُ التقرير الوارد وصفُّ
    ``side == 'in'`` و``shown_issuing``. كانت بلا اختبار، فكان حذفُ حجبها أخضر."""

    def test_report_incoming_table_prints_the_stub(self):
        resp = self._report(self.clerk)
        self.assertContains(resp, '<td class="num">2441</td>', html=False)
        # صفّان محجوبان: الصادرُ (2437) والواردُ (2441)
        self.assertContains(resp, f'<td>{STUB_TITLE}</td>', count=2, html=False)
        for leaked in (SECRET_IN_TITLE, SECRET_IN_TYPE, SECRET_IN_MARGIN, SUPPLIER):
            self.assertNotContains(resp, leaked)

    def test_detail_incoming_row_prints_the_stub(self):
        resp = self._detail(self.clerk)
        self.assertContains(resp, self.secret_in_url)
        self.assertContains(resp, f'<td>{STUB_TITLE}</td>', count=2, html=False)
        for leaked in (SECRET_IN_TITLE, SECRET_IN_TYPE, SUPPLIER):
            self.assertNotContains(resp, leaked)

    def test_book_card_of_the_incoming_book_is_stubbed(self):
        resp = self._card(self.clerk, self.secret_in)
        self.assertContains(resp, f'<div class="bc-v">{STUB_TITLE}</div>', html=False)
        for leaked in (SECRET_IN_TITLE, SECRET_IN_TYPE, SECRET_IN_MARGIN, SUPPLIER):
            self.assertNotContains(resp, leaked)

    def test_officer_sees_the_incoming_book_in_full(self):
        report = self._report(self.officer)
        self.assertContains(report, f'<td>{SECRET_IN_TITLE}</td>', html=False)
        self.assertContains(report, f'<td>{SECRET_IN_TYPE}</td>', html=False)
        self.assertContains(report, SUPPLIER)

        detail = self._detail(self.officer, document_type=SECRET_IN_TYPE)
        self.assertContains(detail, f'<td>{SECRET_IN_TITLE}</td>', html=False)
        self.assertContains(detail, SUPPLIER)

        card = self._card(self.officer, self.secret_in)
        self.assertContains(card, SUPPLIER)
        self.assertContains(card, SECRET_IN_MARGIN)


class DocumentTypeIsNotAFolderLabelTests(DossierSecrecyTestCase):
    """نوعُ المستند محجوبٌ كالعنوان (``STUB_BLANK_FIELDS``) — فلا يُسمّي ملفّاً
    ولا يُعدّ في القائمة المنسدلة ولا يُصفّى به."""

    def test_folder_grid_and_dropdown_do_not_name_the_secret_types(self):
        resp = self._detail(self.clerk, document_type='')
        self.assertEqual(resp.context['total_count'], 3)   # الصفوفُ تُعدّ — النوعُ لا يُسمّى
        for leaked in (SECRET_TYPE, SECRET_IN_TYPE):
            self.assertNotContains(resp, leaked)

    def test_the_type_filter_cannot_select_the_secret(self):
        for params in ({'document_type': SECRET_TYPE},
                       {'document_type': SECRET_TYPE, 'secret_level': 'secret'},
                       {'document_type': SECRET_IN_TYPE}):
            with self.subTest(**params):
                detail = self._detail(self.clerk, **params)
                self.assertEqual(detail.context['total_count'], 0)
                self.assertNotContains(detail, self.secret_url)
                self.assertNotContains(detail, self.secret_in_url)

                report = self._report(self.clerk, **params)
                self.assertEqual(report.context['total_count'], 0)

    def test_the_secret_sits_in_misc_for_the_clerk(self):
        resp = self._detail(self.clerk, document_type=MISC_FOLDER)
        self.assertContains(resp, self.secret_url)
        self.assertContains(resp, self.secret_in_url)

    def test_officer_still_files_it_under_its_type(self):
        grid = self._detail(self.officer, document_type='')
        self.assertContains(grid, SECRET_TYPE)
        self.assertContains(grid, SECRET_IN_TYPE)

        folder = self._detail(self.officer, document_type=SECRET_TYPE)
        self.assertEqual(folder.context['total_count'], 1)
        self.assertContains(folder, self.secret_url)


class NumericSearchIsNotAnOracleTests(DossierSecrecyTestCase):
    """البحثُ الرقميُّ يطابق رقمَ الجهة والرقمَ القديم والعنوانَ والهامشَ أيضاً —
    فلا يُبقي من المقيَّد إلّا ما طابق **هويّتَه** (رقمَ قيدنا)."""

    #: أرقامٌ من المحتوى المحجوب — كلٌّ يمرّ من فرعٍ رقميٍّ مختلف.
    PROBES = (
        '771',        # رقمُ جهة الصادر السرّيّ (≤5 خانات: iregex بحدود)
        '95000',      # رقمٌ في هامش الوارد السرّيّ (≤5 خانات: icontains)
        '1234567',    # رقمٌ طويلٌ في الهامش (>5 خانات)
        '5-12',       # رقمٌ مركّبٌ في الرقم القديم
    )

    def test_content_digits_do_not_find_the_secret(self):
        for probe in self.PROBES:
            with self.subTest(probe=probe):
                self.assertEqual(self._unified(self.clerk, q=probe), [])
                self.assertEqual(self._report(self.clerk, q=probe).context['total_count'], 0)
                self.assertEqual(self._detail(self.clerk, q=probe).context['total_count'], 0)

    def test_the_probes_do_match_for_the_entitled(self):
        """الضابطُ الموجب: بلاه يمرّ الاختبارُ أعلاه لو لم تطابق المجسّاتُ شيئاً."""
        for probe in self.PROBES:
            with self.subTest(probe=probe):
                self.assertEqual(len(self._unified(self.officer, q=probe)), 1)

    def test_our_number_still_finds_both_stubs(self):
        self.assertEqual(self._unified(self.clerk, q='2437'), ['2437'])
        self.assertEqual(self._unified(self.clerk, q='2441'), ['2441'])
        self.assertEqual(self._unified(self.clerk, q='02441'), ['2441'])   # صفرٌ بادئ: هويّةٌ لا محتوى

    def test_relevance_order_does_not_answer_for_the_sender_number(self):
        """«02441» يطابق قيدَ '2441' نمطاً — ورقمُ جهته المحجوب 'ع/02441' كان يرفع
        رتبتَه فوق جارٍ علنيّ؛ فالترتيبُ نفسُه يُجيب. الآن: لا يتغيّر بتغيّره."""
        Book.objects.create(kind='incoming_internal', title='إحالةٌ على 02441',
                            created_by=self.clerk, department=self.dept, our_number='2460')
        before = self._unified(self.clerk, q='02441')
        Book.objects.filter(pk=self.secret_in.pk).update(sender_number='ع/ 88')
        after = self._unified(self.clerk, q='02441')

        self.assertEqual(sorted(before), ['2441', '2460'])
        self.assertEqual(before, after)


class TitleSortIsNotAnOracleTests(DossierSecrecyTestCase):
    """الفرزُ بالعنوان على العنوان **كما يراه القارئ**: تغييرُ عنوانِ السرّيّ وحده
    لا يُحرّك صفَّه عند الكاتب — وإلّا استُخرج حرفاً حرفاً بين جارَين يملكهما."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        # جارٌ علنيّ في الملفّ نفسه: عنوانُه بعد «مناقصة» وقبل «أوّل» أبجديّاً
        cls.neighbour = Book.objects.create(
            kind='incoming_internal', title='يوميّاتُ الورشة', created_by=cls.clerk,
            department=cls.dept, our_number='2450',
        )
        cls.neighbour.issuing_entities.add(cls.entity)

    def _retitle_secret(self):
        Book.objects.filter(pk=self.secret.pk).update(title='أوّلُ العناوين أبجديّاً')

    def _orders(self, user, sort):
        report = self._report(user, sort=sort).content.decode()
        orders = {
            'report': _REPORT_NUMBERS.findall(report),
            'unified': self._unified(user, sort=sort),
        }
        if user == self.clerk:     # ملفُّ «متفرقة» يجمع الثلاثة عند الكاتب وحده
            detail = self._detail(user, sort=sort).content.decode()
            orders['detail'] = _DETAIL_NUMBERS.findall(detail)
        return orders

    def test_clerk_order_ignores_the_hidden_title(self):
        for sort in ('title', '-title'):
            before = self._orders(self.clerk, sort)
            self._retitle_secret()
            after = self._orders(self.clerk, sort)
            for surface, order in before.items():
                with self.subTest(sort=sort, surface=surface):
                    self.assertIn('2437', order)
                    self.assertEqual(order, after[surface])
            Book.objects.filter(pk=self.secret.pk).update(title=SECRET_TITLE)

    def test_officer_order_follows_the_real_title(self):
        """الضابطُ الموجب: الترتيبُ يتحرّك فعلاً بتغيير العنوان — فثباتُه عند
        الكاتب حجبٌ لا مصادفة."""
        for sort in ('title', '-title'):
            before = self._orders(self.officer, sort)
            self._retitle_secret()
            after = self._orders(self.officer, sort)
            for surface, order in before.items():
                with self.subTest(sort=sort, surface=surface):
                    self.assertNotEqual(order, after[surface])
            Book.objects.filter(pk=self.secret.pk).update(title=SECRET_TITLE)

    def test_sort_without_a_user_fails_closed(self):
        qs = Book.objects.filter(pk__in=[self.plain.pk, self.secret.pk, self.neighbour.pk])

        def order():
            return list(BookSortEngine.apply_sort(qs, 'title')
                        .values_list('our_number', flat=True))

        before = order()
        self._retitle_secret()
        self.assertEqual(order(), before)


class DossierOpensForTheEntitledTests(DossierSecrecyTestCase):
    """T3/T4 — الضابطُ الموجب: مَن يملك المحتوى يراه ويجده بكلمةٍ منه."""

    def _assert_full(self, user):
        detail = self._detail(user)
        self.assertContains(detail, f'<td>{SECRET_TITLE}</td>', html=False)
        self.assertContains(detail, COUNTERPART)

        report = self._report(user)
        self.assertContains(report, f'<td>{SECRET_TITLE}</td>', html=False)
        self.assertNotContains(report, f'<td>{STUB_TITLE}</td>', html=False)

        card = self._card(user)
        self.assertContains(card, f'<div class="bc-v">{SECRET_TITLE}</div>', html=False)
        self.assertContains(card, SECRET_MARGIN)
        self.assertContains(card, SECRET_TYPE)
        self.assertContains(card, COUNTERPART)

    def _assert_found_by_word(self, user):
        self.assertEqual(self._detail(user, q='مناقصة').context['total_count'], 1)
        report = self._report(user, q='حسّاس')
        self.assertEqual(report.context['total_count'], 1)
        self.assertContains(report, f'<td>{SECRET_TITLE}</td>', html=False)

    def test_mail_officer_sees_and_finds_the_full_book(self):
        self._assert_full(self.officer)
        self._assert_found_by_word(self.officer)

    def test_author_sees_and_finds_the_full_book(self):
        self._assert_full(self.author)
        self._assert_found_by_word(self.author)

    def test_superuser_is_unchanged(self):
        self._assert_full(self.root)
        self._assert_found_by_word(self.root)
