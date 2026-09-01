# -*- coding: utf-8 -*-
"""عقدُ مسار خطّ اليد حين تغيب الأوزان — تدهورٌ رشيق، لا انهيارُ مستند.

**العطبُ الذي تقفله**: `_read_handwritten_sender_number` كان يعيد **ثنائيّةً**
عند غياب القارئ بينما النداءُ يفكّ **رباعيّة**، فيرتفع `ValueError` يبتلعه
`except` العامّ ويعود المستندُ كلُّه `status='failed'` — بلا حقلٍ واحد. عاش منذ
توصيل قارئ التاريخ (`c961ed3`، 2026-08-26) بلا اختبارٍ أحمر لأنّه لا يُطلَق
إلّا حين **تغيب الأوزان**: وهي حاضرةٌ دائماً على جهاز التطوير.

**ولماذا يهمّ في الإنتاج**: مسارُ الأوزان **نسبيٌّ لمجلّد العمل**
(`os.path.join('var', 'models', …)`)، ومجلّد `var/` خارج git — فخدمةٌ تُقلَع من
مجلّدٍ آخر، أو نسخةٌ جديدةٌ بلا أوزان، تُسقط الاستخراجَ كلَّه لا القراءةَ اليدويّة
وحدَها. مُثبَتٌ بالتشغيل: نفسُ الاختبارات من مجلّدٍ آخر ⟵ `failed`.
"""
import ast
import os

from django.conf import settings
from django.test import SimpleTestCase


class _UnavailableReader:
    available = False


class HandwritingPathContractTests(SimpleTestCase):

    def test_unavailable_reader_returns_the_four_tuple(self):
        from core.extraction.pipeline import AIExtractionService
        svc = AIExtractionService()
        svc._hw_reader = _UnavailableReader()
        got = svc._read_handwritten_sender_number('x.jpg', None, want_date_crop=True)
        self.assertEqual(len(got), 4)
        # نفسُ فكّ النداء — لو عادت ثنائيّةً لارتفع ValueError هنا كما في الإنتاج
        num_res, date_crop, date_suggestion, (det_box, w, h) = got
        self.assertIsNone(num_res)
        self.assertIsNone(date_crop)
        self.assertIsNone(date_suggestion)
        self.assertIsNone(det_box)

    def test_every_return_in_the_pass_yields_four_values(self):
        """حرزٌ بنيويّ: أيُّ مخرجٍ جديدٍ بعرضٍ مختلف يفشل هنا لا في مستندِ كاتب."""
        path = os.path.join(settings.BASE_DIR, 'core', 'extraction', 'pipeline.py')
        with open(path, encoding='utf-8') as f:
            tree = ast.parse(f.read())
        fn = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.FunctionDef)
                  and n.name == '_read_handwritten_sender_number')
        returns = [n for n in ast.walk(fn) if isinstance(n, ast.Return) and n.value is not None]
        self.assertGreaterEqual(len(returns), 2)
        for r in returns:
            self.assertIsInstance(r.value, ast.Tuple, ast.dump(r))
            self.assertEqual(len(r.value.elts), 4,
                             'مخرجٌ بعرضٍ %d عند السطر %d — النداءُ يفكّ أربعة'
                             % (len(r.value.elts), r.lineno))
