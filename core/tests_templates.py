# -*- coding: utf-8 -*-
"""
حراسة صنفٍ من أخطاء القوالب يصعب ملاحظته بالعين.

`{# … #}` في Django تعليقٌ **لسطر واحد**: `tag_re` لا يضبط `DOTALL`، فأي `{#`
لا يُغلَق في سطره ليس تعليقاً — نصّه يُعرض للمستخدم، وأي وسم بداخله يُنفَّذ.
وقعت هذه العلّة ثلاث مرّات في هذا المستودع، إحداها جعلت قالباً يُضمّن نفسه
فأسقط الصفحة بـ RecursionError.

البديل الصحيح: {% comment %} … {% endcomment %}.
"""
import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

_OPEN = re.compile(r'\{#')


def _template_dirs():
    dirs = []
    for engine in settings.TEMPLATES:
        dirs.extend(Path(d) for d in engine.get('DIRS', []))
    base = Path(settings.BASE_DIR)
    if not dirs:
        dirs = [base / 'templates']
    return [d for d in dirs if d.is_dir()]


class UnterminatedTemplateCommentTests(SimpleTestCase):
    """لا يجوز أن يبقى `{#` بلا `#}` في سطره."""

    def test_no_multiline_hash_comments(self):
        offenders = []
        for root in _template_dirs():
            for path in root.rglob('*.html'):
                text = path.read_text(encoding='utf-8')
                for match in _OPEN.finditer(text):
                    eol = text.find('\n', match.start())
                    line = text[match.start(): eol if eol != -1 else len(text)]
                    if '#}' not in line:
                        lineno = text.count('\n', 0, match.start()) + 1
                        offenders.append(f'{path}:{lineno}')

        self.assertEqual(
            offenders, [],
            'تعليق {# … #} يمتدّ لأكثر من سطر — ليس تعليقاً في Django: نصّه يُعرض '
            'وأي وسم بداخله يُنفَّذ. استعمل {% comment %} … {% endcomment %} في:\n  '
            + '\n  '.join(offenders))
