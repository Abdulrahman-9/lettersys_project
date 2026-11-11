# -*- coding: utf-8 -*-
"""صفحةُ مصفوفة الأدوار: البوّابة، والعرض، والحفظ في معاملةٍ واحدة، والرجوع إلى المعتمد، والأثر."""
from django.contrib.auth.models import Group, User
from django.contrib.messages import get_messages
from django.core.exceptions import PermissionDenied
from django.db import connection
from django.test import RequestFactory, TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from core import permission_service as svc
from core.logging_models import UserActivityLog
from core.models import Department, RoleCapabilityOverride, UserProfile
from core.scoping import CAPABILITIES, WIRED_CAPABILITIES
from core.roles import CONTROLLER_GROUP_NAME, ENTRY_GROUP_NAME, EXECUTOR_GROUP_NAME

URL = reverse('system_roles')


class RolesPageCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.dept = Department.objects.create(name='قسم المصفوفة', code='م1')
        cls.unit = Department.objects.create(name='وحدة المصفوفة', code='م1و', parent=cls.dept, holds_register=False)
        cls.admin = User.objects.create_superuser('m_root', password='x', first_name='مدير', last_name='النظام')
        cls.head = cls.person('m_head', cls.dept, head=True)
        cls.entries = [cls.person(f'm_entry{i}', cls.dept, ENTRY_GROUP_NAME) for i in range(3)]
        cls.mail = cls.person('m_mail', cls.dept, CONTROLLER_GROUP_NAME)
        cls.executor = cls.person('m_exec', cls.unit, EXECUTOR_GROUP_NAME)
        gone = cls.person('m_gone', cls.dept, ENTRY_GROUP_NAME)
        gone.is_active = False
        gone.save(update_fields=['is_active'])

    @classmethod
    def person(cls, name, dept, group=None, head=False):
        user = User.objects.create_user(name, password='x')
        UserProfile.objects.update_or_create(user=user, defaults={'department': dept, 'is_department_head': head})
        if group:
            user.groups.add(Group.objects.get_or_create(name=group)[0])
        return user

    def post(self, **data):
        self.client.force_login(self.admin)
        return self.client.post(URL, data)

    def traces(self):
        return UserActivityLog.objects.filter(action='EDIT_PERMISSIONS')


class GateTests(RolesPageCase):
    def test_only_the_system_admin_opens_it(self):
        self.assertEqual(self.client.get(URL).status_code, 302)
        for user in (self.head, self.mail, self.entries[0]):
            self.client.force_login(user)
            with self.subTest(user=user.username):
                self.assertEqual(self.client.get(URL).status_code, 403)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(URL).status_code, 200)

    def test_a_head_cannot_write_through_it(self):
        self.client.force_login(self.head)
        self.assertEqual(self.client.post(URL, {'change': 'entry:referral.receive:1'}).status_code, 403)
        self.assertFalse(RoleCapabilityOverride.objects.exists())
        self.assertFalse(self.traces().exists())


class ShowTests(RolesPageCase):
    def page(self):
        self.client.force_login(self.admin)
        return self.client.get(URL)

    def test_columns_count_active_holders_by_role(self):
        admins, holders = svc.role_holders()
        self.assertEqual(admins, 1)
        self.assertEqual((holders['entry'], holders['head'], holders['mail'], holders['executor']), (3, 1, 1, 1))
        body = self.page().content.decode()
        self.assertIn('3 موظّفين', body)
        self.assertIn('حساب واحد', body)

    def test_the_desk_rows_follow_the_registry_and_my_today_is_gone(self):
        body = self.page().content.decode()
        for label in ('طاولة البريد', 'الدفتر وكشف التسليم', 'طاولتي'):
            self.assertIn(label, body)
        self.assertNotIn('ما يخصّني', body)
        self.assertNotIn('مستنتَجة', body)

    def test_locked_and_frozen_cells_are_not_buttons(self):
        body = self.page().content.decode()
        self.assertNotIn('value="head:book.sign:', body)
        self.assertNotIn('value="reader:book.edit:', body)
        self.assertIn('value="entry:referral.receive:1"', body)
        self.assertIn('value="head:referral.send:0"', body)

    def test_a_changed_cell_says_so_and_names_who_changed_it(self):
        self.post(change='entry:referral.receive:1')
        body = self.page().content.decode()
        self.assertIn('class="rm-cell on mod" data-role="entry"', body)
        self.assertIn('استلام المُحال وإنجازه لدور مدخل، معدَّلة عن المعتمد"', body)
        self.assertIn('عدّلها مدير النظام اليوم', body)
        self.assertIn('name="reset" value="referral.receive"', body)
        self.assertIn('name="reset" value="all"', body)

    def test_nothing_changed_offers_no_reset(self):
        body = self.page().content.decode()
        self.assertNotIn('name="reset"', body)
        self.assertNotIn(' mod" data-role', body)
        self.assertNotIn('عن المعتمد"', body)

    def test_the_accounts_link_is_lit_on_this_page(self):
        body = self.page().content.decode()
        self.assertRegex(body, r'class="on" href="[^"]*\?tab=users"')

    def test_holders_are_counted_without_a_query_per_person(self):
        for i in range(12):
            self.person(f'm_more{i}', self.dept, ENTRY_GROUP_NAME)
        self.client.force_login(self.admin)
        self.client.get(URL)  # الطلبُ الأوّل يملأ كاشات الإعدادات
        with CaptureQueriesContext(connection) as few:
            self.client.get(URL)
        for i in range(12, 24):
            self.person(f'm_more{i}', self.dept, ENTRY_GROUP_NAME)
        with CaptureQueriesContext(connection) as more:
            self.client.get(URL)
        self.assertEqual(len(few), len(more))


class SaveTests(RolesPageCase):
    def test_a_change_writes_a_row_and_a_trace_and_says_whom_it_reaches(self):
        response = self.post(change='entry:referral.receive:1')
        self.assertEqual(response['Location'], URL + '#cap-referral.receive')  # يعود إلى صفّه لا إلى رأس الصفحة
        row = RoleCapabilityOverride.objects.get()
        self.assertEqual((row.role, row.capability, row.allowed, row.changed_by), ('entry', 'referral.receive', True, self.admin))
        self.assertEqual(self.traces().count(), 1)
        self.assertEqual([str(m) for m in get_messages(response.wsgi_request)],
                         ['حُفظت خليّة واحدة، ويسري الآن على 3 موظّفين.'])

    def test_several_changes_are_saved_together(self):
        response = self.post(change=['entry:referral.receive:1', 'executor:referral.send:1', 'head:referral.send:0'])
        self.assertEqual(response['Location'], URL + '#cap-referral.send')  # أعلى صفٍّ مسّه الحفظ
        self.assertEqual(RoleCapabilityOverride.objects.count(), 3)
        self.assertEqual(self.traces().count(), 3)

    def test_a_locked_cell_in_the_request_drops_all_of_it(self):
        for bad in ('head:book.sign:0', 'reader:book.edit:1', 'executor:book.enter:1'):
            with self.subTest(bad=bad):
                response = self.post(change=['entry:referral.receive:1', bad])
                self.assertEqual(response.status_code, 403)
                self.assertFalse(RoleCapabilityOverride.objects.exists())
                self.assertFalse(self.traces().exists())

    def test_what_is_not_understood_is_refused(self):
        cases = ({'change': 'ghost:book.restore:1'}, {'change': 'entry:ghost:1'}, {'change': 'entry:book.restore:2'},
                 {'change': 'entry:book.restore'}, {'change': ['entry:book.restore:1', 'entry:book.restore:0']},
                 {'change': 'entry:book.restore:1', 'reset': 'all'}, {}, {'reset': 'ghost'})
        for data in cases:
            with self.subTest(data=data):
                self.assertEqual(self.post(**data).status_code, 400)
        self.assertFalse(RoleCapabilityOverride.objects.exists())

    def test_saving_what_is_already_there_changes_nothing(self):
        response = self.post(change='head:referral.send:1')
        self.assertFalse(self.traces().exists())
        self.assertEqual([str(m) for m in get_messages(response.wsgi_request)],
                         ['لم يتغيّر شيء: الخلايا على ما كانت عليه.'])

    def test_a_role_nobody_holds_says_so(self):
        response = self.post(change='archivist:referral.receive:1')
        self.assertEqual([str(m) for m in get_messages(response.wsgi_request)],
                         ['حُفظت خليّة واحدة، ولا يحمل الدورَ أحدٌ الآن.'])
        response = self.post(change=['archivist:referral.send:1', 'reader:referral.receive:1'])
        self.assertEqual([str(m) for m in get_messages(response.wsgi_request)][-1],
                         'حُفظت خليّتان، ولا يحمل هذين الدورين أحدٌ الآن.')


class ResetTests(RolesPageCase):
    def setUp(self):
        self.post(change=['entry:referral.receive:1', 'executor:referral.send:1', 'mail:referral.receive:0'])

    def test_a_row_returns_alone(self):
        response = self.post(reset='referral.receive')
        self.assertEqual(set(RoleCapabilityOverride.objects.values_list('role', 'capability')), {('executor', 'referral.send')})
        self.assertEqual(self.traces().count(), 5)
        self.assertEqual([str(m) for m in get_messages(response.wsgi_request)][-1],
                         'عادت إلى المعتمد خليّتان، ويسري الآن على 4 موظّفين.')

    def test_everything_returns(self):
        self.assertEqual(self.post(reset='all')['Location'], URL)
        self.assertFalse(RoleCapabilityOverride.objects.exists())
        self.assertEqual(self.traces().count(), 6)

    def test_a_row_reset_comes_back_to_its_row(self):
        self.assertEqual(self.post(reset='referral.receive')['Location'], URL + '#cap-referral.receive')
        # ولو لم يكن فيه ما يعود
        self.assertEqual(self.post(reset='book.edit')['Location'], URL + '#cap-book.edit')

    def test_a_row_planted_on_a_locked_cell_is_left_alone(self):
        RoleCapabilityOverride.objects.create(role='head', capability='book.sign', allowed=False)
        self.post(reset='all')
        self.assertEqual(list(RoleCapabilityOverride.objects.values_list('role', 'capability')), [('head', 'book.sign')])

    def test_only_the_system_admin_resets(self):
        self.client.force_login(self.head)
        self.assertEqual(self.client.post(URL, {'reset': 'all'}).status_code, 403)
        self.assertEqual(RoleCapabilityOverride.objects.count(), 3)

    def test_the_service_refuses_others_even_with_nothing_to_reset(self):
        request = RequestFactory().post(URL)
        request.user = self.head
        with self.assertRaises(PermissionDenied):
            svc.reset_role_overrides(request, 'book.sign')


class MatrixShapeTests(RolesPageCase):
    def test_a_changed_row_keeps_its_latest_change(self):
        self.post(change=['entry:referral.receive:1', 'mail:referral.receive:0'])
        rows = {r['key']: r for g in svc.role_matrix()['groups'] for r in g['rows']}
        self.assertEqual(rows['referral.receive']['changed'], 2)
        self.assertEqual(rows['referral.receive']['last'].changed_by, self.admin)
        self.assertEqual(rows['book.edit']['changed'], 0)
        self.assertIsNone(rows['book.edit']['last'])

    def test_groups_keep_the_registry_order(self):
        names = [g['name'] for g in svc.role_matrix()['groups']]
        self.assertEqual(names, ['الكتب', 'الإحالة والإنجاز', 'الطاولات', 'الرقابة', 'البريد', 'الإدارة'])


class AccountsLinkTests(RolesPageCase):
    def test_the_accounts_tab_links_here_for_the_system_admin_only(self):
        self.client.force_login(self.admin)
        self.assertContains(self.client.get(reverse('admin_panel') + '?tab=users'), URL)
        self.client.force_login(self.head)
        self.assertNotContains(self.client.get(reverse('admin_panel') + '?tab=users'), URL)


class WiredOnlyTests(RolesPageCase):
    """صفحةٌ تقول «يسري الآن» لا تقبل إلّا ما يسري فعلاً (11-11: 26 من 28 لم يُربط حارسها)."""

    def test_an_unwired_capability_is_refused_without_a_row(self):
        for cell in ('entry:book.restore:1', 'mail:report.view:1', 'unit:desk.mine:0'):
            with self.subTest(cell=cell):
                self.assertEqual(self.post(change=cell).status_code, 403)
        self.assertEqual(self.post(change=['entry:referral.receive:1', 'entry:book.restore:1']).status_code, 403)
        self.assertFalse(RoleCapabilityOverride.objects.exists())
        self.assertFalse(self.traces().exists())

    def test_unwired_rows_are_shown_not_offered(self):
        self.client.force_login(self.admin)
        body = self.client.get(URL).content.decode()
        self.assertNotIn('value="entry:book.restore:', body)
        self.assertIn('الاسترجاع من السلّة لدور مدخل: لا يستطيع، لم يُربط حارسها بعد"', body)
        self.assertIn('«الإحالة» و«استلام المُحال وإنجازه»', body)

    def test_the_wired_set_is_what_the_code_reads(self):
        """كلُّ مفتاحٍ يقرؤه حارسٌ في الكود مسجَّلٌ مربوطاً، ولا مفتاحَ مربوطاً بلا قارئ."""
        import re
        from pathlib import Path

        root = Path(__file__).resolve().parent
        read = set()
        for source in root.rglob('*.py'):
            if source.name.startswith('tests') or 'migrations' in source.parts:
                continue
            read |= set(re.findall(r"has_capability\([^,()]+,\s*'([a-z_.]+)'\)", source.read_text(encoding='utf-8')))
        self.assertEqual(read, set(WIRED_CAPABILITIES))
        self.assertLessEqual(set(WIRED_CAPABILITIES), set(CAPABILITIES))
