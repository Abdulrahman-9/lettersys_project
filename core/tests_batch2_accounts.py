"""الدفعة 2 (قرارُ المالك 11-16): الحساباتُ قائمةٌ تُقرأ، ومحرّرُ الحساب طريقُ الكتابة الوحيد — ولرئيس القسم بنطاقه.

كلُّ حارسٍ هنا يُطفَّر (قواعدُ الحرفة §9.4).
"""
from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.urls import reverse

from core.models import Department, UserProfile
from core.roles import ENTRY_GROUP_NAME, EXECUTOR_GROUP_NAME


def _person(username, department, *, first='', last='', head=False, staff=False, active=True,
            temp=False, title='', group=None):
    user = User.objects.create_user(username, password=f'{username}-pass-1234', first_name=first,
                                    last_name=last, is_staff=staff, is_active=active)
    UserProfile.objects.create(user=user, department=department, is_department_head=head,
                               must_change_password=temp, job_title=title)
    if group:
        user.groups.add(Group.objects.get_or_create(name=group)[0])
    return user


class AccountsFixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.root = User.objects.create_superuser('b2-root', password='b2-root-pass-1234')
        UserProfile.objects.create(user=cls.root)
        cls.dept = Department.objects.create(name='قسم الاختبار', code='ت-1')
        cls.unit = Department.objects.create(name='وحدة الاختبار', code='ت-1/1', parent=cls.dept, holds_register=False)
        cls.other_dept = Department.objects.create(name='قسم آخر', code='ت-2')
        cls.head = _person('b2-head', cls.dept, first='رئيس', last='الاختبار', head=True)
        cls.clerk = _person('b2-clerk', cls.dept, first='سالم', last='المدخل', title='كاتب الوارد',
                            group=ENTRY_GROUP_NAME)
        cls.executor = _person('b2-exec', cls.unit, first='منفذ', temp=True, group=EXECUTOR_GROUP_NAME)
        cls.unit_head = _person('b2-unit', cls.unit, first='مسؤول', last='الوحدة', head=True)
        cls.off = _person('b2-off', cls.dept, first='موقوف', active=False)
        cls.staff = _person('b2-staff', cls.dept, staff=True)
        cls.outsider = _person('b2-other', cls.other_dept, first='غريب')

    def _list(self, user, **params):
        self.client.force_login(user)
        response = self.client.get(reverse('system_accounts'), params)
        self.assertEqual(response.status_code, 200)
        return response

    @staticmethod
    def _names(response):
        return [row['username'] for row in response.context['rows']]


class AccountsListTests(AccountsFixture):
    def test_the_system_admin_sees_every_account(self):
        names = self._names(self._list(self.root))
        for user in (self.root, self.head, self.clerk, self.executor, self.unit_head, self.off,
                     self.staff, self.outsider):
            self.assertIn(user.username, names)

    def test_a_head_sees_his_tree_without_administrative_accounts(self):
        names = set(self._names(self._list(self.head)))
        self.assertEqual(names, {'b2-head', 'b2-clerk', 'b2-exec', 'b2-unit', 'b2-off'})

    def test_whoever_manages_nobody_is_refused(self):
        self.client.force_login(self.clerk)
        self.assertEqual(self.client.get(reverse('system_accounts')).status_code, 403)

    def test_it_is_never_cached(self):
        self.assertIn('no-store', self._list(self.head)['Cache-Control'])

    def test_the_table_is_read_only(self):
        """القائمةُ تُقرأ والمحرّرُ يكتب — لا حقلَ ولا نموذجَ POST في الصفحة."""
        body = self._list(self.root).content.decode()
        for field in ('name="job_title"', 'type="checkbox"', 'name="is_active"', 'method="post" action="/books/admin/'):
            with self.subTest(field=field):
                self.assertNotIn(field, body)

    def test_rows_link_to_the_editor_only_when_the_viewer_manages_them(self):
        response = self._list(self.head)
        rows = {row['username']: row for row in response.context['rows']}
        self.assertTrue(rows['b2-clerk']['can_edit'])
        self.assertTrue(rows['b2-unit']['can_edit'])
        self.assertFalse(rows['b2-head']['can_edit'])
        self.assertEqual(rows['b2-head']['note'], 'حسابك')
        self.assertContains(response, 'href="%s"' % reverse('system_account', args=[self.clerk.pk]))
        self.assertNotContains(response, 'href="%s"' % reverse('system_account', args=[self.head.pk]))

    def test_each_row_says_one_role_in_words(self):
        rows = {row['username']: row for row in self._list(self.root).context['rows']}
        self.assertEqual(rows['b2-clerk']['role_label'], 'مدخل')
        self.assertEqual(rows['b2-root']['role_label'], 'مدير النظام')
        self.assertEqual(rows['b2-exec']['role'], 'executor')

    def test_search_reads_name_username_and_title(self):
        for query, expected in (('سالم', 'b2-clerk'), ('B2-EXEC', 'b2-exec'), ('الوارد', 'b2-clerk')):
            with self.subTest(query=query):
                self.assertEqual(self._names(self._list(self.head, q=query)), [expected])

    def test_status_chips_count_before_their_own_filter(self):
        response = self._list(self.head, status='inactive')
        counts = {s['key']: s['count'] for s in response.context['statuses']}
        # «حسّاس» = يفتح السرّيّ أو يدير غيرَه: الرئيسُ ومسؤولُ الوحدة
        self.assertEqual(counts, {'all': 5, 'active': 4, 'inactive': 1, 'password': 1, 'sensitive': 2})
        self.assertEqual(self._names(response), ['b2-off'])
        self.assertEqual(self._names(self._list(self.head, status='password')), ['b2-exec'])

    def test_role_and_department_filters(self):
        self.assertEqual(self._names(self._list(self.head, role='executor')), ['b2-exec'])
        # القسمُ يشمل ما يتبعه
        self.assertEqual(set(self._names(self._list(self.head, department=self.dept.pk))),
                         {'b2-head', 'b2-clerk', 'b2-exec', 'b2-unit', 'b2-off'})
        self.assertEqual(set(self._names(self._list(self.head, department=self.unit.pk))), {'b2-exec', 'b2-unit'})

    def test_a_department_outside_the_scope_is_ignored(self):
        response = self._list(self.head, department=self.other_dept.pk)
        self.assertIsNone(response.context['department'])
        self.assertNotIn('b2-other', self._names(response))

    def test_unknown_parameters_fall_back(self):
        response = self._list(self.head, role='bogus', department='²', status='x', sort='y', dir='z', page='99')
        self.assertEqual((response.context['role'], response.context['department'], response.context['status'],
                          response.context['sort'], response.context['dir']), ('', None, 'all', 'name', 'asc'))

    def test_sorting_is_announced_and_reversible(self):
        response = self._list(self.head)
        aria = {c['key']: c['aria'] for c in response.context['columns']}
        self.assertEqual(aria['name'], 'ascending')
        self.assertContains(response, 'aria-sort="ascending"', count=1)
        by_role = self._list(self.head, sort='role', dir='desc')
        self.assertContains(by_role, 'aria-sort="descending"', count=1)
        self.assertEqual({c['key']: c['aria'] for c in by_role.context['columns']}['role'], 'descending')
        # الرأسُ الحاليّ يعكس الاتّجاه، وغيرُه يبدأ تصاعديّاً
        urls = {c['key']: c['url'] for c in response.context['columns']}
        self.assertIn('dir=desc', urls['name'])
        self.assertNotIn('dir=', urls['role'])

    def test_role_sort_puts_heads_before_readers(self):
        names = self._names(self._list(self.head, sort='role'))
        self.assertLess(names.index('b2-head'), names.index('b2-off'))

    def test_pages_of_fifty(self):
        for i in range(52):
            _person(f'b2-bulk-{i:02d}', self.other_dept)
        first = self._list(self.root)
        self.assertEqual(len(first.context['rows']), 50)
        self.assertTrue(first.context['next_url'])
        second = self.client.get(first.context['next_url'])
        self.assertEqual(len(second.context['rows']), self._list(self.root).context['page_obj'].paginator.count - 50)

    def test_an_empty_result_says_what_did_not_match_and_offers_a_way_back(self):
        response = self._list(self.head, q='لا أحد بهذا الاسم', status='inactive')
        self.assertContains(response, 'لا حساب يطابق البحث «لا أحد بهذا الاسم»، والحالة «موقوف»')
        self.assertContains(response, 'href="%s">مسح التصفية' % reverse('system_accounts'))

    def test_the_head_is_told_his_scope(self):
        self.assertContains(self._list(self.head), 'نطاقك: <b>قسم الاختبار وما يتبعه</b>')
        self.assertNotContains(self._list(self.root), 'نطاقك:')

    def test_new_account_is_offered_to_whoever_can_grant(self):
        for user in (self.root, self.head, self.unit_head):
            with self.subTest(user=user.username):
                self.assertContains(self._list(user), 'href="%s"' % reverse('system_account_new'))


class EditorForHeadsTests(AccountsFixture):
    """محرّرُ الحساب لرئيس القسم بنطاقه (قرارُ المالك 11-16) — وملاحظاتُ فيبل على خطّة الدفعة."""

    def _editor(self, viewer, target):
        self.client.force_login(viewer)
        return self.client.get(reverse('system_account', args=[target.pk]))

    def test_the_gate_hides_what_the_viewer_does_not_manage(self):
        """غيرُ المُدار كغير الموجود (404) — رفضٌ مختلف يكشف أيّ المعرّفات قائمة."""
        self.assertEqual(self._editor(self.head, self.clerk).status_code, 200)
        for target in (self.outsider, self.head, self.staff):
            with self.subTest(target=target.username):
                self.assertEqual(self._editor(self.head, target).status_code, 404)
        self.assertEqual(self.client.get(reverse('system_account', args=[99999])).status_code, 404)
        self.assertEqual(self._editor(self.clerk, self.off).status_code, 403)   # لا يدير أحداً أصلاً

    def test_a_head_is_offered_only_the_roles_he_grants_in_that_department(self):
        roles = dict(self._editor(self.head, self.clerk).context['role_options'])
        self.assertEqual(set(roles), {'mail', 'archivist', 'entry', 'reader'})   # لا رئاسة
        roles = dict(self._editor(self.head, self.executor).context['role_options'])
        self.assertEqual(set(roles), {'executor', 'reader'})   # وحدةٌ لا تمسك سجلّاً، ولا «مسؤول»
        self.assertEqual(set(dict(self._editor(self.root, self.executor).context['role_options'])),
                         {'unit', 'executor', 'reader'})

    def test_a_role_the_head_cannot_grant_is_shown_with_its_reason(self):
        response = self._editor(self.head, self.unit_head)
        self.assertIn('يمنحه مدير النظام', response.context['role_block'])
        self.assertNotContains(response, 'id="aeRole"')
        self.assertContains(response, 'id="aeRoleBlock"')
        self.assertIn('نقلُ الرئيس أو المسؤول', response.context['move_block'])
        self.assertContains(response, 'id="aeDepartment" name="department" data-initial="%d" disabled' % self.unit.pk)

    def test_the_head_changes_a_role_he_grants_and_nothing_above_it(self):
        from django.core.exceptions import PermissionDenied
        from django.test import RequestFactory

        from core.permission_service import set_user_role
        from core.scoping import role_of

        request = RequestFactory().post('/')
        request.user = self.head
        self.assertTrue(set_user_role(request, self.clerk, 'archivist'))
        self.assertEqual(role_of(User.objects.get(pk=self.clerk.pk)), 'archivist')
        for target, role in ((self.clerk, 'head'), (self.unit_head, 'reader')):
            with self.subTest(target=target.username, role=role), self.assertRaises(PermissionDenied):
                set_user_role(request, User.objects.get(pk=target.pk), role)
        request.user = self.unit_head   # مسؤولُ الوحدة يمنح التنفيذَ والقارئ في وحدته
        self.assertTrue(set_user_role(request, self.executor, 'reader'))

    def test_an_exception_the_head_cannot_edit_blocks_role_change_and_move(self):
        """فيبل 11-16: الدورُ والنقلُ يُلغيان الاستثناءات — فلا يُلغي بهما مَن لا يملك إلغاءها بيده."""
        from django.core.exceptions import PermissionDenied
        from django.test import RequestFactory

        from core.admin_service import assign_user
        from core.models import UserCapabilityOverride
        from core.permission_service import set_user_role
        from core.scoping import CAPABILITIES, ROLE_HEAD, WIRED_CAPABILITIES, role_capability

        key = next((k for k, c in CAPABILITIES.items()
                    if k in WIRED_CAPABILITIES and not c.locked and not role_capability(ROLE_HEAD, k)), None)
        self.assertIsNotNone(key, 'لا صلاحيّةَ موصولةً خارج دور الرئيس — غيّر الاختبار')
        UserCapabilityOverride.objects.create(user=self.clerk, capability=key, allowed=False, changed_by=self.root)
        response = self._editor(self.head, self.clerk)
        self.assertIn(CAPABILITIES[key].label, response.context['role_block'])
        self.assertIn(CAPABILITIES[key].label, response.context['move_block'])
        # والاستثناءُ نفسُه لا يُعدَّل بيده — صفُّه بلا زرّ، لا زرٌّ يُرفض عند الضغط
        self.assertFalse(response.context['exceptions'][0]['editable'])
        rows = {row['key']: row for group in response.context['groups'] for row in group['rows']}
        self.assertFalse(rows[key]['editable'])
        request = RequestFactory().post('/')
        request.user = self.head
        with self.assertRaises(PermissionDenied):
            set_user_role(request, self.clerk, 'reader')
        with self.assertRaises(PermissionDenied):
            assign_user(self.clerk, by=self.head, department=self.unit)
        self.assertTrue(UserCapabilityOverride.objects.filter(user=self.clerk, capability=key).exists())
        # ومديرُ النظام يملكه كلَّه
        request.user = self.root
        self.assertTrue(set_user_role(request, self.clerk, 'reader'))
        self.assertFalse(UserCapabilityOverride.objects.filter(user=self.clerk).exists())

    def test_the_admin_changes_a_role_over_locked_and_orphan_exceptions(self):
        """مديرُ النظام يملك الاستثناءاتِ كلَّها — والمقفلُ واليتيمُ لا يمنعانه (يُلغيهما ``cancel_exceptions`` بأثر)."""
        from django.test import RequestFactory

        from core.models import UserCapabilityOverride
        from core.permission_service import set_user_role
        from core.scoping import CAPABILITIES, foreign_exceptions

        locked = next(key for key, capability in CAPABILITIES.items() if capability.locked)
        for key in (locked, 'gone.from.the.registry'):
            UserCapabilityOverride.objects.create(user=self.clerk, capability=key, allowed=True, changed_by=self.root)
        self.assertEqual(foreign_exceptions(self.root, self.clerk), [])
        self.assertEqual(self._editor(self.root, self.clerk).context['role_block'], '')
        request = RequestFactory().post('/')
        request.user = self.root
        self.assertTrue(set_user_role(request, self.clerk, 'reader'))
        self.assertFalse(UserCapabilityOverride.objects.filter(user=self.clerk).exists())

    def test_a_flag_is_guarded_when_it_changes_not_when_it_stays(self):
        """``set_user_role`` يمرّر الأعلامَ الستّة — والعلَمُ الثابتُ لا يُرفض به منحٌ مسموح؛ وما لا يمنحه لا ينزعه."""
        from django.core.exceptions import PermissionDenied

        from core.admin_service import assign_user
        from core.roles import CONTROLLER_GROUP_NAME

        assign_user(self.executor, by=self.unit_head, is_company_archivist=False, is_controller=False)
        legacy = _person('b2-legacy', self.unit, group=CONTROLLER_GROUP_NAME)
        with self.assertRaises(PermissionDenied):
            assign_user(legacy, by=self.unit_head, is_controller=False)
        self.assertTrue(legacy.groups.filter(name=CONTROLLER_GROUP_NAME).exists())

    def test_the_head_sees_his_tree_and_not_the_admins_name(self):
        from core.models import UserCapabilityOverride
        from core.scoping import CAPABILITIES

        key = next(iter(CAPABILITIES))
        UserCapabilityOverride.objects.create(user=self.clerk, capability=key, allowed=True, changed_by=self.root)
        response = self._editor(self.head, self.clerk)
        self.assertEqual({d.pk for d in response.context['departments']}, {self.dept.pk, self.unit.pk})
        self.assertNotContains(response, '<option value="">بلا قسم</option>')
        self.assertEqual(response.context['exceptions'][0]['by'], 'مدير النظام')
        self.assertNotContains(response, 'b2-root')
        self.assertEqual(self._editor(self.root, self.clerk).context['exceptions'][0]['by'], 'b2-root')

    def test_delete_is_the_admins_and_the_breadcrumb_leads_to_the_list(self):
        response = self._editor(self.head, self.clerk)
        self.assertNotContains(response, 'name="action" value="delete"')
        self.assertContains(response, 'href="%s">الحسابات والأدوار</a>' % reverse('system_accounts'))
        self.assertNotContains(response, '?tab=users')
        self.assertContains(self._editor(self.root, self.clerk), 'name="action" value="delete"')

    def test_the_audit_link_follows_the_viewers_own_key(self):
        from core.models import UserCapabilityOverride

        self.assertTrue(self._editor(self.head, self.clerk).context['audit_url'])
        UserCapabilityOverride.objects.create(user=self.head, capability='audit.view', allowed=False,
                                              changed_by=self.root)
        from core.scoping import clear_capability_cache
        clear_capability_cache(self.head)
        response = self._editor(self.head, self.clerk)
        self.assertEqual(response.context['audit_url'], '')
        self.assertNotContains(response, 'سجلّ حركاته')

    def test_a_system_admin_without_the_staff_flag_stays_out_of_a_heads_list(self):
        """فيبل 11-16: النطاقُ كان يُسقط is_staff وحده — ومديرُ نظامٍ في قسمٍ بلا العلَم كان يظهر للرئيس."""
        quiet = User.objects.create_superuser('b2-quiet', password='b2-quiet-pass-1234')
        User.objects.filter(pk=quiet.pk).update(is_staff=False)
        UserProfile.objects.create(user=quiet, department=self.dept)
        self.assertNotIn('b2-quiet', self._names(self._list(self.head)))
        self.assertIn('b2-quiet', self._names(self._list(self.root)))

    def test_the_unit_head_creates_only_in_his_unit_and_only_basic_roles(self):
        self.client.force_login(self.unit_head)
        page = self.client.get(reverse('system_account_new'))
        self.assertEqual([d.pk for d in page.context['departments']], [self.unit.pk])
        self.assertEqual(page.context['department_roles'][str(self.unit.pk)]['roles'], ['executor', 'reader'])

    def test_the_head_finds_his_accounts_in_the_sidebar(self):
        self.client.force_login(self.head)
        self.assertContains(self.client.get(reverse('dashboard')), 'href="%s"' % reverse('system_accounts'))
        page = self.client.get(reverse('system_accounts'))
        self.assertContains(page, 'class="app-sidebar-link active" href="%s"' % reverse('system_accounts'))
        self.assertContains(page, 'system_admin.css')   # أنماطُ صفحات النظام لمن لا يُحمَّل له شريطُها


class PanelRedirectTests(AccountsFixture):
    def test_the_old_tab_leads_everyone_who_opens_the_panel_to_the_list_with_its_filter(self):
        for user in (self.root, self.head):
            with self.subTest(user=user.username):
                self.client.force_login(user)
                response = self.client.get(reverse('admin_panel'), {'tab': 'users', 'status': 'sensitive'})
                self.assertEqual(response['Location'], reverse('system_accounts') + '?status=sensitive')
        self.assertEqual(self.client.get(reverse('admin_panel'), {'tab': 'users', 'dept': self.unit.pk})['Location'],
                         reverse('system_accounts') + '?department=%d' % self.unit.pk)
        self.assertEqual(self.client.get(reverse('admin_panel'), {'tab': 'users', 'status': '<x>', 'dept': '²'})['Location'],
                         reverse('system_accounts'))

    def test_the_admin_filters_accounts_without_a_department(self):
        lost = User.objects.create_user('b2-lost', password='b2-lost-pass-1234')
        UserProfile.objects.create(user=lost)
        names = self._names(self._list(self.root, department='none'))
        self.assertIn('b2-lost', names)
        self.assertNotIn('b2-clerk', names)
        self.assertIsNone(self._list(self.head, department='none').context['department'])
        self.assertFalse(self._list(self.head, department='none').context['no_department'])


class FableCodeReviewTests(AccountsFixture):
    """مراجعةُ فيبل لكود الدفعة 2 (11-16): القسمُ المعطَّل · طريقُ الأعلام الواحد · الفرز · البحث · ما يُحسب مرّة."""

    def _editor(self, viewer, target):
        self.client.force_login(viewer)
        return self.client.get(reverse('system_account', args=[target.pk]))

    def test_a_closed_current_department_stays_selected_and_named(self):
        """غيابُه يجعل المتصفّحَ يختار الأوّل، فيصير كلُّ حفظٍ «نقلاً» يُلغي الاستثناءات."""
        Department.objects.filter(pk=self.unit.pk).update(is_active=False)
        for viewer in (self.root, self.head):
            with self.subTest(viewer=viewer.username):
                response = self._editor(viewer, self.executor)
                self.assertIn(self.unit.pk, [d.pk for d in response.context['departments']])
                self.assertContains(response, '<option value="%d" selected>' % self.unit.pk)
                self.assertContains(response, '— معطَّل</option>')

    def test_only_set_user_role_passes_role_flags_to_assign_user(self):
        """``assign_user`` يقلب الأعلامَ ولا يقرأ ``role_change_block`` — فطريقُها الوحيد ``set_user_role``."""
        import ast
        from pathlib import Path

        from django.conf import settings

        from core.permission_service import ROLE_FLAG_NAMES

        callers = []
        for path in Path(settings.BASE_DIR, 'core').rglob('*.py'):
            if path.name.startswith('tests') or 'migrations' in path.parts:
                continue
            for node in ast.walk(ast.parse(path.read_text(encoding='utf-8-sig'))):
                name = getattr(node, 'func', None)
                name = getattr(name, 'id', None) or getattr(name, 'attr', None)
                if isinstance(node, ast.Call) and name == 'assign_user':
                    words = {keyword.arg for keyword in node.keywords}
                    if None in words or words & set(ROLE_FLAG_NAMES):
                        callers.append(path.relative_to(settings.BASE_DIR).as_posix())
        self.assertEqual(callers, ['core/permission_service.py'])

    def test_who_never_logged_in_stays_last_both_ways(self):
        from django.utils import timezone

        now = timezone.now()
        User.objects.filter(pk=self.clerk.pk).update(last_login=now)
        User.objects.filter(pk=self.off.pk).update(last_login=now - timezone.timedelta(days=30))
        for direction in ('asc', 'desc'):
            with self.subTest(direction=direction):
                names = self._names(self._list(self.head, sort='login', dir=direction))
                # الاتّجاهُ يحكم مَن دخل، ومَن لم يدخل قطّ آخرَ القائمة في الاتّجاهين
                earlier, later = names.index('b2-off'), names.index('b2-clerk')
                self.assertTrue(earlier < later if direction == 'asc' else later < earlier)
                self.assertEqual(set(names[-2:]), {'b2-exec', 'b2-unit'})

    def test_search_does_not_match_the_email_it_never_shows(self):
        User.objects.filter(pk=self.clerk.pk).update(email='hidden-match@example.invalid')
        self.assertEqual(self._names(self._list(self.head, q='hidden-match')), [])

    def test_a_unit_head_edits_no_exception_at_all(self):
        """مسؤولُ الوحدة مغلقٌ عن الاستثناءات (قرارُ المالك 11-03) — والدورُ يُحسب مرّةً للصفحة لا لكلّ مفتاح."""
        response = self._editor(self.unit_head, self.executor)
        rows = [row for group in response.context['groups'] for row in group['rows']]
        self.assertTrue(rows)
        self.assertFalse([row['key'] for row in rows if row['editable']])
