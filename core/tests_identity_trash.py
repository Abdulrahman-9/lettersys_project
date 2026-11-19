# -*- coding: utf-8 -*-
"""حرّاسُ سلّة المهملات على الهويّة الموحّدة (11-19، دفعةُ الصفحات المتبقّية).

١. **الصفحةُ منقولة (v2)** وورقتُها ‎css/trash.css‎ بالرموز وحدها (لا لونَ خامّاً ولا ‎[data-theme]‎ الميّت ولا
   ‎!important‎)، مربوطةً بنسخة الكاش، ولا نمطَ مضمَّناً في القالب.
٢. **لا حواريّةَ أصليّة**: الحذفُ النهائيّ بحواريّة التطبيق (‎data-confirm‎ بعنوانه وزرّه)، والاستعادةُ بلا سؤال.
٣. **الهدّامُ لا يجاور الآمن**: نموذجُ الحذف النهائيّ بعد فاصل، والزرّان في سطرٍ واحد — كان التفافُ المرن
   يكدّسهما في خليّةٍ بعرض محتواها.
٤. **لا ‎.table‎ ولا ‎.card‎**: app.css يلصق على الأوّل عموداً أخيراً أبيضَ لاصقاً (أبيضُ في الداكن) وصفوفاً تكبُر
   تحت المؤشّر، وعلى الثاني بطاقاتٍ تقفز.
٥. **لا زرَّ يُعرض ليُرفض**: مرفقُ كتابٍ في السلّة يعود مع كتابه — ‎restore_attachment‎ يرفضه وحده.
٦. **الأرقامُ والتواريخ معزولة**، واسمُ الملفّ بلا مسار التخزين (كان المسارُ المضاعف يتبعثر في خليّته).
٧. **الطرفُ الآخر** كما في القائمة الموحّدة: «من» للوارد و«إلى» للصادر (مُصدِرُ الصادر قسمُنا نفسُه).
٨. **حدُّ التركيز ظاهر** على الأزرار الورقيّة: ظلُّها في theme.css يغلب حلقةَ Bootstrap التي تُسقط الحدّ.
٩. **الهاتف**: الصفوفُ بطاقات، والرأسُ مخفيٌّ بصريّاً لا سمعيّاً، والأفعالُ 44px.
"""
import re

from django.contrib.auth.models import Group, User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import Attachment, Book, Department, Entity, UserCapabilityOverride, UserProfile
from core.roles import CONTROLLER_GROUP_NAME, ENTRY_GROUP_NAME, ensure_role_groups
from core.tests_list_identity import DECL, _read, _strip

TEMPLATE = 'templates/core/trash.html'
SHEET = 'static/css/trash.css'
NAMED_COLOURS = {'white', 'black', 'red', 'green', 'blue', 'gray', 'grey', 'orange', 'yellow', 'silver', 'maroon'}
LEGACY_CLASSES = {'table', 'table-light', 'table-responsive', 'card', 'card-header', 'card-body', 'bg-white'}


def _rule(css, selector):
    """جسمُ أوّلِ قاعدةٍ محدِّدُها ``selector`` بالضبط."""
    start = css.index(selector + ' {')
    return css[start:css.index('}', start)]


class TrashSourceTests(SimpleTestCase):

    def test_the_page_wears_the_identity(self):
        src = _read(TEMPLATE)
        self.assertIn('{% block html_attrs %} data-lx-page="v2"{% endblock %}', src)
        self.assertIn("{% static 'css/trash.css' %}?v=20261119-pages", src)

    def test_the_sheet_speaks_tokens_only(self):
        css = _strip(_read(SHEET))
        values = ' '.join(m.group(2) for m in DECL.finditer(css))
        self.assertEqual({h.lower() for h in re.findall(r'#[0-9a-fA-F]{3,8}\b', values)} - {'#fff'}, set())
        # ‎rgba(var(--lx-pri-rgb), .45)‎ رمزٌ بشفافيّة — والرقمُ الصريح لونٌ خامّ
        self.assertNotRegex(values, r'\b(?:rgba?|hsla?)\(\s*[\d.]')
        self.assertEqual(set(re.findall(r'[a-z]+', values)) & NAMED_COLOURS, set())
        self.assertNotIn('data-theme', css)
        self.assertNotIn('!important', css)

    def test_no_inline_style_and_no_native_dialog(self):
        src = _read(TEMPLATE)
        self.assertNotIn('style=', src)
        for native in ('confirm(', 'alert(', 'onsubmit=', 'onclick='):
            with self.subTest(native=native):
                self.assertNotIn(native, src)

    def test_no_legacy_table_or_card(self):
        classes = {c for attr in re.findall(r'class="([^"]*)"', _read(TEMPLATE)) for c in attr.split()}
        self.assertEqual(classes & LEGACY_CLASSES, set())

    def test_the_destructive_action_stands_apart_on_one_line(self):
        css = _read(SHEET)
        self.assertIn('flex-wrap: nowrap', _rule(css, '.trash-acts'))
        self.assertIn('border-inline-start: 1px solid var(--lx-line)', _rule(css, '.trash-purge'))
        src = _read(TEMPLATE)
        self.assertEqual(src.count('class="trash-purge"'), 2)
        self.assertEqual(src.count('class="btn btn-sm btn-danger"'), 2)

    def test_paper_buttons_show_their_focus(self):
        css = _read(SHEET)
        start = css.index('.trash-page .btn:focus-visible')
        self.assertIn('outline: 2px solid var(--lx-pri)', css[start:css.index('}', start)])

    def test_phone_rows_become_cards_with_big_targets(self):
        css = _read(SHEET)
        phone = css[css.index('@media (max-width: 767.98px)'):]
        self.assertIn('clip-path: inset(50%)', _rule(phone, '.trash-table thead'))
        self.assertIn('display: grid', _rule(phone, '.trash-table tbody tr'))
        self.assertIn('min-height: 44px', _rule(phone, '.trash-acts .btn'))


class TrashPageTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        ensure_role_groups()
        cls.dept = Department.objects.create(name='قسم هويّة السلّة', code='هس1')
        far = Department.objects.create(name='قسمٌ بعيدٌ عن السلّة', code='هس2')
        cls.admin = User.objects.create_superuser('trash_id_admin', password='pw-trash-id-1119')
        cls.mail = cls.person('trash_id_mail', cls.dept, CONTROLLER_GROUP_NAME)
        cls.clerk = cls.person('trash_id_clerk', cls.dept, ENTRY_GROUP_NAME)
        UserCapabilityOverride.objects.create(user=cls.clerk, capability='book.trash', allowed=True)
        cls.far_mail = cls.person('trash_id_far', far, CONTROLLER_GROUP_NAME)

        cls.incoming = cls.book('incoming_external', '7105', 'واردٌ محذوف')
        cls.incoming.issuing_entities.add(Entity.objects.create(name='وزارةُ المُرسِل الاختباريّة'))
        cls.outgoing = cls.book('outgoing_external', '7106', 'صادرٌ محذوف')
        cls.outgoing.issuing_entities.add(Entity.objects.create(name='مُصدِرُ الصادر الاختباريّ'))
        cls.outgoing.receiving_entities.add(Entity.objects.create(name='شركةُ المستلِم الاختباريّة'))
        cls.numberless = cls.book('incoming_internal', '', 'بلا رقمٍ محذوف')
        live = cls.book('incoming_internal', '7107', 'كتابٌ حيّ')
        cls.live_att = cls.attachment(live, 'live_scan.pdf')
        cls.gone_att = cls.attachment(cls.incoming, 'gone_scan.pdf')

        when = timezone.make_aware(timezone.datetime(2026, 11, 3, 14, 7))
        Book.all_objects.filter(pk__in=[cls.incoming.pk, cls.outgoing.pk, cls.numberless.pk]).update(
            is_deleted=True, deleted_at=when)
        Attachment.all_objects.filter(pk__in=[cls.live_att.pk, cls.gone_att.pk]).update(
            is_deleted=True, deleted_at=when)

    @classmethod
    def person(cls, name, dept, group):
        user = User.objects.create_user(name, password='pw-trash-id-1119')
        UserProfile.objects.update_or_create(user=user, defaults={'department': dept})
        user.groups.add(Group.objects.get(name=group))
        return user

    @classmethod
    def book(cls, kind, number, title):
        return Book.objects.create(kind=kind, our_number=number, title=title, created_by=cls.mail,
                                   department=cls.dept)

    @classmethod
    def attachment(cls, book, name):
        return Attachment.objects.create(book=book, file=SimpleUploadedFile(
            name, b'%PDF-1.4 trash identity', content_type='application/pdf'))

    def page(self, user):
        self.client.force_login(user)
        response = self.client.get(reverse('trash_list'))
        self.assertEqual(response.status_code, 200)
        return response.content.decode('utf-8')

    @staticmethod
    def form(html, url):
        """النموذجُ الذي يرسل إلى ``url`` — من وسمه إلى إغلاقه."""
        start = html.rindex('<form', 0, html.index('action="%s"' % url))
        return html[start:html.index('</form>', start)]

    def test_the_admin_purges_through_the_app_dialog_and_restores_without_one(self):
        html = self.page(self.admin)
        self.assertIn('data-lx-page="v2"', html)
        purge = self.form(html, reverse('purge_book', args=[self.outgoing.pk]))
        self.assertIn('class="trash-purge"', purge)
        self.assertIn('data-confirm-title="حذفُ الكتاب 7106 نهائيّاً؟"', purge)
        self.assertIn('data-confirm="يُمحى الكتاب ومرفقاته', purge)
        self.assertIn('data-confirm-ok="احذف نهائيّاً"', purge)
        self.assertNotIn('data-confirm', self.form(html, reverse('restore_book', args=[self.outgoing.pk])))
        self.assertIn('data-confirm="يُمحى الملفّ', self.form(html, reverse('purge_attachment', args=[self.live_att.pk])))

    def test_the_mail_officer_restores_and_is_told_who_purges(self):
        html = self.page(self.mail)
        self.assertIn(reverse('restore_book', args=[self.incoming.pk]), html)
        self.assertNotIn(reverse('purge_book', args=[self.incoming.pk]), html)
        self.assertNotIn('class="trash-purge"', html)
        self.assertIn('والحذفُ النهائيّ لمدير النظام وحده', html)

    def test_an_attachment_of_a_trashed_book_returns_with_its_book(self):
        for user in (self.admin, self.mail):
            with self.subTest(user=user.username):
                html = self.page(user)
                self.assertNotIn(reverse('restore_attachment', args=[self.gone_att.pk]), html)
                self.assertIn(reverse('restore_book', args=[self.incoming.pk]), html)
                self.assertIn(reverse('restore_attachment', args=[self.live_att.pk]), html)
                self.assertEqual(html.count('يعود مع كتابه</span>'), 1)
                self.assertEqual(html.count('class="trash-chip is-tag">في السلّة</span>'), 1)

    def test_whoever_cannot_act_is_told_why(self):
        html = self.page(self.clerk)
        self.assertEqual(html.count('للقسم المالك</span>'), 5)   # ثلاثةُ كتبٍ ومرفقان، ولا زرَّ في أيّها
        self.assertNotIn(reverse('restore_book', args=[self.incoming.pk]), html)
        self.assertNotIn(reverse('purge_book', args=[self.incoming.pk]), html)

    def test_numbers_dates_and_file_names_are_isolated(self):
        html = self.page(self.admin)
        self.assertIn('<bdi dir="ltr" class="trash-no" translate="no">7105</bdi>', html)
        self.assertIn('<td>بلا رقم</td>', html)
        self.assertIn('<time datetime="2026-11-03T14:07', html)
        self.assertIn('<bdi dir="ltr">03/11/2026</bdi>', html)
        att = Attachment.all_objects.get(pk=self.live_att.pk)
        self.assertIn('<bdi dir="auto" translate="no">%s</bdi>' % att.filename, html)
        self.assertNotIn(att.file.name, html)

    def test_the_other_party_is_named(self):
        html = self.page(self.admin)
        self.assertIn('<span class="trash-dir">من</span> وزارةُ المُرسِل الاختباريّة', html)
        self.assertIn('<span class="trash-dir">إلى</span> شركةُ المستلِم الاختباريّة', html)
        self.assertNotIn('مُصدِرُ الصادر الاختباريّ', html)

    def test_an_empty_trash_explains_itself(self):
        html = self.page(self.far_mail)
        self.assertIn('لا كتب محذوفة.', html)
        self.assertIn('لا مرفقات محذوفة.', html)
        self.assertNotIn('class="trash-table', html)
