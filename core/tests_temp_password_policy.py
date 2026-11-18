"""قرارُ المالك 11-18 (توصيةُ فيبل): الكلمةُ المؤقّتة لا تصير مفتاحاً لما لا يملكه رئيسُ القسم.

رئيسُ القسم يرى الكلمةَ المؤقّتة لمن يعيد كلمتَه أو يُنشئه. فإن رفعه بعدها إلى دورٍ أو استثناءٍ يفتح السرّيّ أو
يدير غيرَه، تُبطَل الكلمةُ ما دامت لم تُغيَّر، ومديرُ النظام يصدر التالية. والحسابُ الحسّاس الذي يُنشئه غيرُ المدير
يولد بلا كلمةٍ صالحة. كلُّ حارسٍ هنا يُطفَّر.
"""
from django.contrib.auth.models import Group, User
from django.test import RequestFactory, TestCase
from django.urls import reverse

from core.admin_service import create_department_user, reset_department_user_password
from core.logging_models import UserActivityLog
from core.models import Department, UserPassword, UserProfile
from core.permission_service import set_user_override, set_user_role
from core.roles import ENTRY_GROUP_NAME
from core.scoping import CAPABILITIES, ROLE_HEAD, WIRED_CAPABILITIES, role_capability


def _person(username, department, *, head=False, group=None):
    user = User.objects.create_user(username, password=f'{username}-pass-1234')
    UserProfile.objects.create(user=user, department=department, is_department_head=head)
    if group:
        user.groups.add(Group.objects.get_or_create(name=group)[0])
    return user


class TempPasswordPolicyTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.root = User.objects.create_superuser('tp-root', password='tp-root-pass-1234')
        UserProfile.objects.create(user=cls.root)
        cls.dept = Department.objects.create(name='قسم الكلمات', code='كل-1')
        cls.head = _person('tp-head', cls.dept, head=True)
        cls.reader = _person('tp-reader', cls.dept)

    def _request(self, user):
        request = RequestFactory().post('/')
        request.user = user
        return request

    def _fresh(self, user):
        return User.objects.get(pk=user.pk)

    def test_reset_then_promote_voids_the_password_the_head_saw(self):
        temporary = reset_department_user_password(by=self.head, user=self.reader)
        self.assertTrue(self._fresh(self.reader).check_password(temporary))
        set_user_role(self._request(self.head), self._fresh(self.reader), 'mail')
        fresh = self._fresh(self.reader)
        self.assertFalse(fresh.check_password(temporary))
        self.assertFalse(fresh.has_usable_password())
        self.assertFalse(UserPassword.objects.filter(user=fresh).exists())
        self.assertTrue(UserActivityLog.objects.filter(action='PASSWORD_RESET', metadata__voided=True,
                                                       metadata__user='tp-reader').exists())
        # ومديرُ النظام يصدر التالية
        issued = reset_department_user_password(by=self.root, user=fresh)
        self.assertTrue(self._fresh(self.reader).check_password(issued))

    def test_a_password_its_owner_already_changed_is_left_alone(self):
        UserProfile.objects.filter(user=self.reader).update(must_change_password=False)
        set_user_role(self._request(self.head), self._fresh(self.reader), 'mail')
        self.assertTrue(self._fresh(self.reader).check_password('tp-reader-pass-1234'))

    def test_a_promotion_to_what_opens_nothing_keeps_the_password(self):
        temporary = reset_department_user_password(by=self.head, user=self.reader)
        set_user_role(self._request(self.head), self._fresh(self.reader), 'entry')
        self.assertTrue(self._fresh(self.reader).check_password(temporary))

    def test_the_admin_promoting_voids_nothing(self):
        temporary = reset_department_user_password(by=self.root, user=self.reader)
        set_user_role(self._request(self.root), self._fresh(self.reader), 'mail')
        self.assertTrue(self._fresh(self.reader).check_password(temporary))

    def test_a_positive_exception_from_the_head_voids_it_and_a_block_does_not(self):
        clerk = _person('tp-clerk', self.dept, group=ENTRY_GROUP_NAME)

        def editable(clerk_has):
            return next((k for k, c in CAPABILITIES.items() if k in WIRED_CAPABILITIES and not c.locked
                         and role_capability(ROLE_HEAD, k) and role_capability('entry', k) == clerk_has), None)
        owned, extra = editable(True), editable(False)
        self.assertIsNotNone(owned, 'لا صلاحيّةَ يملكها المدخل ويعدّلها الرئيس — غيّر الاختبار')
        self.assertIsNotNone(extra, 'لا صلاحيّةَ فوق المدخل يملكها الرئيس — غيّر الاختبار')
        temporary = reset_department_user_password(by=self.head, user=clerk)
        # حجبٌ حقيقيّ لما يملكه المدخل: لا يفتح شيئاً، فالكلمةُ باقية
        self.assertTrue(set_user_override(self._request(self.head), self._fresh(clerk), owned, False))
        self.assertTrue(self._fresh(clerk).check_password(temporary))
        # وإضافةُ ما فوق دوره تجعله حسّاساً — فتُبطَل
        self.assertTrue(set_user_override(self._request(self.head), self._fresh(clerk), extra, True))
        self.assertFalse(self._fresh(clerk).has_usable_password())

    def test_a_sensitive_account_the_head_creates_is_born_without_a_password(self):
        officer, password = create_department_user(by=self.head, department=self.dept, username='tp-officer',
                                                   role='controller')
        self.assertIsNone(password)
        self.assertFalse(officer.has_usable_password())
        self.assertFalse(UserPassword.objects.filter(user=officer).exists())
        clerk, password = create_department_user(by=self.head, department=self.dept, username='tp-clerk', role='entry')
        self.assertTrue(clerk.check_password(password))
        self.assertTrue(clerk.groups.filter(name=ENTRY_GROUP_NAME).exists())
        admin_made, password = create_department_user(by=self.root, department=self.dept, username='tp-admin-made',
                                                      role='controller')
        self.assertTrue(admin_made.check_password(password))

    def test_the_pages_say_who_issues_the_first_password(self):
        self.client.force_login(self.head)
        response = self.client.post(reverse('system_account_new'), {
            'name': 'مختصّ', 'username': 'tp-page-officer', 'department': self.dept.pk, 'role': 'mail'})
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'class="ae-secret"')   # صندوقُ الكلمة (ae-secret.own معرّفُ صلاحيّة)
        self.assertContains(response, 'فكلمتُه الأولى يصدرها مدير النظام')
        self.assertContains(response, 'id="aeNoPassword"')
        officer = User.objects.get(username='tp-page-officer')
        self.client.force_login(self.root)
        editor = self.client.get(reverse('system_account', args=[officer.pk]))
        self.assertContains(editor, 'أصدرها بزرّ «كلمة مرور مؤقّتة»')
        self.assertContains(editor, 'name="action" value="password"')
