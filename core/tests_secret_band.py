# -*- coding: utf-8 -*-
"""السرّية بحزام الرأس + افتراضيّ normal (2026-07-22، قرار المالك: بُعدٌ مستقلّ).

  $env:PYTHONIOENCODING="utf-8"; python manage.py test core.tests_secret_band --settings=lettersys.settings_test
"""
from django.test import SimpleTestCase

from core.extraction.matchers.pattern import PatternMatcher


class SecretBandTests(SimpleTestCase):
    def setUp(self):
        self.m = PatternMatcher()

    def test_secret_in_header_band(self):
        """«(سري)» في حزام الى/→م/ ⟵ secret."""
        text = "الى/ قسم حماية المنشآت\n( سري وعاجل )\nم/ احتياجات تدريبية\nتحية طيبة"
        level, conf = self.m.extract_secret_level(text)
        self.assertEqual(level, 'secret')
        self.assertGreaterEqual(conf, 0.9)

    def test_topsecret_in_header(self):
        text = "الى/ الجهة\nسري للغاية\nم/ الموضوع"
        self.assertEqual(self.m.extract_secret_level(text)[0], 'topsecret')

    def test_sri_in_body_only_is_not_secret(self):
        """«سري» في المتن (تحت الموضوع) لا يرفع السرّية — تفادي إيجابيّة المتن."""
        text = "الى/ الجهة\nم/ الموضوع\nاشارة الى الكتاب السري المرقم 55 نأمل..."
        self.assertEqual(self.m.extract_secret_level(text)[0], 'normal')

    def test_default_normal_when_no_marker(self):
        """لا علامة ⟵ normal (لا فارغ) — الانبعاث صادقٌ والأغلبية اعتيادية."""
        level, conf = self.m.extract_secret_level("الى/ الجهة\nم/ الموضوع\nتحية طيبة")
        self.assertEqual(level, 'normal')
        self.assertLess(conf, 0.9)

    def test_explicit_normal_higher_confidence(self):
        level, conf = self.m.extract_secret_level("الى/ الجهة\nاعتيادي\nم/ الموضوع")
        self.assertEqual(level, 'normal')
        self.assertGreaterEqual(conf, 0.9)
