# -*- coding: utf-8 -*-
"""افتراضُ القسم لجهة الصادر — الصادرُ مُصدِرُه وحدةٌ من قسم الكاتب المسجِّل.

مقيسٌ (2026-09-08، ترك‑واحد على 2,896 صادراً داخليّاً): الوحداتُ الشقيقة تتقاسم
ترويسةً واحدة فتتعادل عند الذاكرة (32%)، بينما تواترُ (القسم، النوع) يعطي
top‑1 41.9% · top‑3 66.5% · top‑5 86.9%. الحرّاسُ الثلاثة تُطفَّر هنا: الوارد لا
يُمسّ، القسمُ الآخر لا يُحسب، والفراغُ لا يُحفَظ في الكاش.
"""
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from core.extraction import pipeline as P
from core.models import Book, Department, Entity, UserProfile

import base64

PNG_1x1 = base64.b64decode(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==')


class DepartmentPriorTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user('kaatib_dp', password='pw-dp-123')
        cls.e_dept = Entity.objects.create(name='قسم المتابعة (اختبار)', code='ش77', etype='both')
        cls.e1 = Entity.objects.create(name='وحدة التقارير (اختبار)', code='و.ت7', etype='both')
        cls.e2 = Entity.objects.create(name='اللجان (اختبار)', code='ل7', etype='both')
        cls.dept = Department.objects.create(name='قسم المتابعة (اختبار)', code='ش77', entity=cls.e_dept)
        cls.other = Department.objects.create(name='قسم آخر (اختبار)', code='ش98')
        profile, _ = UserProfile.objects.get_or_create(user=cls.user)
        profile.department = cls.dept
        profile.save()

        def mk(kind, ent, dept, n):
            for i in range(n):
                b = Book.objects.create(title='ت%d' % i, kind=kind, created_by=cls.user, department=dept)
                b.issuing_entities.add(ent)
        mk('outgoing_internal', cls.e1, cls.dept, 3)
        mk('outgoing_internal', cls.e2, cls.dept, 1)
        mk('incoming_internal', cls.e2, cls.dept, 5)     # الواردُ لا يُحسب
        mk('outgoing_internal', cls.e2, cls.other, 4)    # قسمٌ آخر لا يُحسب

    def setUp(self):
        P._DOMINANT_ISS_CACHE.clear()

    def test_prior_orders_units_by_frequency_within_department_and_kind(self):
        rows = P.dominant_issuing_entities(self.dept.id, 'outgoing_internal')
        self.assertEqual([(r[0], r[2]) for r in rows], [(self.e1.id, 3), (self.e2.id, 1)])

    def test_prior_empty_is_not_cached_and_needs_both_keys(self):
        self.assertEqual(P.dominant_issuing_entities(self.other.id, 'incoming_external'), [])
        self.assertEqual(P.dominant_issuing_entities(None, 'outgoing_internal'), [])
        self.assertEqual(P.dominant_issuing_entities(self.dept.id, ''), [])
        self.assertEqual(P._DOMINANT_ISS_CACHE, {})

    def test_resolver_leads_with_prior_for_outgoing_issuer_only(self):
        svc = P.AIExtractionService()
        out = svc.resolve_entity_candidates('issuer', '', 'outgoing_internal', '', '', [],
                                            department_id=self.dept.id)
        self.assertEqual(out[0]['match_type'], 'department_prior')
        self.assertEqual(out[0]['entity_id'], self.e1.id)
        self.assertEqual(out[1]['entity_id'], self.e2.id)
        for etype, kind in (('issuer', 'incoming_internal'), ('receiver', 'outgoing_internal')):
            got = svc.resolve_entity_candidates(etype, '', kind, '', '', [], department_id=self.dept.id)
            self.assertNotIn('department_prior', [m['match_type'] for m in got], (etype, kind))
        got = svc.resolve_entity_candidates('issuer', '', 'outgoing_internal', '', '', [], department_id=None)
        self.assertNotIn('department_prior', [m['match_type'] for m in got])

    def test_register_code_precedes_prior(self):
        svc = P.AIExtractionService()
        out = svc.resolve_entity_candidates('issuer', '', 'outgoing_internal', '', 'ش77', [],
                                            department_id=self.dept.id)
        self.assertEqual(out[0]['entity_id'], self.e_dept.id)
        self.assertNotEqual(out[0]['match_type'], 'department_prior')
        self.assertIn('department_prior', [m['match_type'] for m in out[1:]])

    def test_endpoint_passes_user_department(self):
        self.client.login(username='kaatib_dp', password='pw-dp-123')
        with patch('core.extraction.api.endpoints.AIExtractionService') as svc_cls:
            svc_cls.return_value.process_image.side_effect = RuntimeError('stop')
            self.client.post('/books/api/extract/smart/', {
                'file': SimpleUploadedFile('a.png', PNG_1x1, content_type='image/png'),
                'book_kind': 'outgoing_internal'})
        kwargs = svc_cls.return_value.process_image.call_args.kwargs
        self.assertEqual(kwargs.get('department_id'), self.dept.id)
        self.assertEqual(kwargs.get('book_kind'), 'outgoing_internal')
