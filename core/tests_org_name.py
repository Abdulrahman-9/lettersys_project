# -*- coding: utf-8 -*-
"""اسمُ الشركة على الورق من مصدرٍ واحد — ``core.branding.org_name``.

كان يُقرأ في ثلاثة مواضع بثلاثة احتياطيّات؛ الآن دالّةٌ واحدة باحتياطيٍّ واحد
(«شركة نفط الوسط»، قرارُ المالك ق‑7) تخدم الصفحاتِ الأربع المطبوعة.
(خطّةُ فيبل 2026‑09‑29 §4.)
"""
from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.urls import reverse

from core.branding import DEFAULT_ORG_NAME, org_name
from core.models import Department, EmailSettings, Entity, UserProfile
from core.roles import CONTROLLER_GROUP_NAME


class OrgNameSourceTests(TestCase):

    def test_empty_falls_back_to_the_company(self):
        for blank in ('', '   '):
            with self.subTest(blank=repr(blank)):
                EmailSettings.objects.update_or_create(singleton=1, defaults={'org_name': blank})
                self.assertEqual(org_name(), 'شركة نفط الوسط')
        self.assertEqual(DEFAULT_ORG_NAME, 'شركة نفط الوسط')

    def test_the_setting_wins(self):
        EmailSettings.objects.update_or_create(singleton=1, defaults={'org_name': '  مؤسّسةٌ مضبوطة '})
        self.assertEqual(org_name(), 'مؤسّسةٌ مضبوطة')


class PrintedPagesCarryItTests(TestCase):
    """التقاريرُ والأضبارةُ وكشفُ التسليم ودفترُ الوارد — كلُّها تطبع ``org_name()``."""

    @classmethod
    def setUpTestData(cls):
        cls.dept = Department.objects.create(name='قسمُ الاسم', code='س.ق')
        cls.officer = User.objects.create_user('nofficer', password='pw-nofficer-1111')
        UserProfile.objects.update_or_create(user=cls.officer, defaults={'department': cls.dept})
        cls.officer.groups.add(Group.objects.get_or_create(name=CONTROLLER_GROUP_NAME)[0])
        cls.admin = User.objects.create_superuser('nadmin', 'n@x.co', 'pw-nadmin-1111')
        cls.entity = Entity.objects.create(name='جهةُ الأضبارة للاسم')

    def _pages(self):
        return ((self.admin, reverse('reports')),
                (self.admin, reverse('dossier_report', args=[self.entity.pk])),
                (self.officer, reverse('desk_handover')),
                (self.officer, reverse('desk_ledger')))

    def test_the_default_on_every_sheet(self):
        EmailSettings.objects.update_or_create(singleton=1, defaults={'org_name': ''})
        for user, url in self._pages():
            with self.subTest(url=url):
                self.client.force_login(user)
                resp = self.client.get(url)
                self.assertEqual(resp.status_code, 200)
                self.assertContains(resp, DEFAULT_ORG_NAME)
                self.assertEqual(resp.context['org_name'], DEFAULT_ORG_NAME)

    def test_the_setting_on_every_sheet(self):
        EmailSettings.objects.update_or_create(singleton=1, defaults={'org_name': 'مؤسّسةُ الاختبار'})
        for user, url in self._pages():
            with self.subTest(url=url):
                self.client.force_login(user)
                resp = self.client.get(url)
                self.assertContains(resp, 'مؤسّسةُ الاختبار')
                self.assertNotContains(resp, DEFAULT_ORG_NAME)
