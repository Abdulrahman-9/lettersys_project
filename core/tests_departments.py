"""بُعدُ القسم — المرحلة أ، الخطوة الأولى (نماذج وبذر)."""

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase
from io import StringIO

from core.models import Department, Entity, SystemSettings, UserProfile
from core.management.commands.seed_departments import is_internal_code


class InternalCodeTests(TestCase):
    """حدُّ القسم: رمزٌ عربيّ = وحدةٌ داخليّة."""

    def test_arabic_codes_are_internal(self):
        for code in ('ش13', 'ش.م.د', 'د', 'ل.ن.خ', 'ت.م'):
            self.assertTrue(is_internal_code(code), code)

    def test_latin_codes_are_foreign_companies(self):
        for code in ('ADE', 'ebs', 'kar', 'sh54', 'nk'):
            self.assertFalse(is_internal_code(code), code)

    def test_email_anomaly_is_excluded(self):
        """شذوذٌ مقيس: جهةٌ حقلُ code فيها بريدٌ إلكترونيّ."""
        self.assertFalse(is_internal_code('الادارة@example.com'))

    def test_empty_is_not_a_department(self):
        for code in ('', None, '   '):
            self.assertFalse(is_internal_code(code))


class SeedDepartmentsTests(TestCase):

    def setUp(self):
        self.before = Department.objects.count()
        Entity.objects.create(name='قسم المتابعة', code='ش13')
        Entity.objects.create(name='قسم العقود', code='ش5')
        Entity.objects.create(name='شركة أجنبية', code='ADE')
        Entity.objects.create(name='جهة بلا رمز')

    def _run(self, *args):
        out = StringIO()
        call_command('seed_departments', *args, stdout=out)
        return out.getvalue()

    def test_dry_run_writes_nothing(self):
        output = self._run()
        self.assertIn('عرضٌ فقط', output)
        # الهجرة تُنشئ القسم الافتراضيّ — فالتحقّق أنّ الجافّ لم يزد عليه.
        self.assertEqual(Department.objects.count(), self.before)

    def test_apply_creates_only_internal_units(self):
        self._run('--apply')
        codes = set(Department.objects.values_list('code', flat=True))
        self.assertEqual(codes, {'ش13', 'ش5'})

    def test_department_links_its_entity(self):
        self._run('--apply')
        dept = Department.objects.get(code='ش13')
        self.assertEqual(dept.entity.name, 'قسم المتابعة')
        self.assertEqual(dept.entity.department, dept)

    def test_rerun_is_idempotent(self):
        self._run('--apply')
        self._run('--apply')
        self.assertEqual(Department.objects.count(), 2)

    def test_default_department_created_when_absent(self):
        Entity.objects.filter(code='ش13').delete()
        self._run('--apply')
        self.assertTrue(Department.objects.filter(code='ش13').exists())


class UserProfileTests(TestCase):

    def test_profile_links_user_to_department(self):
        dept = Department.objects.create(name='وحدة اختبار', code='ش99')
        user = User.objects.create_user('emp', password='pw-emp-1111')
        profile = UserProfile.objects.create(user=user, department=dept)
        self.assertEqual(user.profile.department, dept)
        self.assertIn(profile, dept.members.all())

    def test_department_is_protected_from_deletion(self):
        from django.db.models import ProtectedError

        dept = Department.objects.create(name='وحدة اختبار', code='ش98')
        UserProfile.objects.create(
            user=User.objects.create_user('emp2', password='pw-emp-2222'), department=dept)
        with self.assertRaises(ProtectedError):
            dept.delete()


class DeploymentProfileTests(TestCase):
    """وضعُ التشغيل: تنصيبُ قسمٍ واحد لا يرى تعقيد الأقسام."""

    def test_defaults_to_single_department(self):
        self.assertEqual(SystemSettings.get().deployment_profile, SystemSettings.PROFILE_SINGLE)

    def test_can_switch_to_company(self):
        cfg = SystemSettings.get()
        cfg.deployment_profile = SystemSettings.PROFILE_COMPANY
        cfg.save()
        self.assertEqual(SystemSettings.get().deployment_profile, 'company')


class EnsureProfileTests(TestCase):
    """المستخدم الجديد بعد الهجرة كان يبقى بلا ملفّ فيسقط إلى «كتبي أنا»."""

    def test_single_mode_joins_the_default_department(self):
        from core.scoping import ensure_profile

        user = User.objects.create_user('newbie', password='pw-newbie-1')
        profile = ensure_profile(user)
        self.assertIsNotNone(profile.department, 'الموظّف الجديد بقي بلا قسم')

    def test_company_mode_leaves_department_unset(self):
        """لا نُخمّن القسم حين تتعدّد الأقسام — إسنادٌ خاطئٌ صامت أسوأ من مؤجَّل."""
        from core.scoping import ensure_profile

        cfg = SystemSettings.get()
        cfg.deployment_profile = SystemSettings.PROFILE_COMPANY
        cfg.save()
        user = User.objects.create_user('newbie2', password='pw-newbie-2')
        self.assertIsNone(ensure_profile(user).department)

    def test_is_idempotent(self):
        from core.scoping import ensure_profile

        user = User.objects.create_user('newbie3', password='pw-newbie-3')
        self.assertEqual(ensure_profile(user).pk, ensure_profile(user).pk)
