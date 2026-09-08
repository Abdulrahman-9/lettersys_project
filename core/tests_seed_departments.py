# -*- coding: utf-8 -*-
"""حرّاسُ بذر الأقسام — أخطرُ ما فيه أن يُنشئ وحدةً تنظيميّةً لا وجودَ لها."""

from django.test import TestCase

from core.management.commands.seed_departments import (
    internal_entities, is_internal_code,
)
from core.models import Entity


class InternalEntitySelectionTests(TestCase):
    """اختيارُ الجهات التي تصير أقساماً."""

    def test_merged_entity_is_not_seeded(self):
        """الجهةُ المدموجة صيغةٌ إملائيّةٌ لغيرها — لا وحدةٌ تُبذَر.

        يفشل على الكود السابق: `internal_entities` كانت تتجاهل `is_active`
        فتبذر قسماً لـ«ش ج ادارة الجودة» المدموجة في «ش.ج».
        """
        canonical = Entity.objects.create(name='شعبة ادارة الجودة', code='ش.ج')
        victim = Entity.objects.create(
            name='ادارة الجودة', code='ش ج',
            is_active=False, merged_into=canonical,
        )

        codes = [e.code for e in internal_entities()]

        self.assertIn(canonical.code, codes)
        self.assertNotIn(victim.code, codes)

    def test_deactivated_entity_is_not_seeded(self):
        """المعطَّلةُ بلا دمجٍ تُستثنى أيضاً — «س صادر سري» نوعُ سجلٍّ لا وحدة."""
        Entity.objects.create(name='صادر سري', code='س', is_active=False)

        self.assertNotIn('س', [e.code for e in internal_entities()])

    def test_latin_code_is_external_company(self):
        """الرمزُ اللاتينيّ شركةٌ خارجيّة لا وحدةٌ داخليّة — حدُّ القسم بقرار المالك."""
        self.assertTrue(is_internal_code('ش13'))
        self.assertFalse(is_internal_code('ADE'))
        self.assertFalse(is_internal_code(''))
        self.assertFalse(is_internal_code('a@b.com'))
