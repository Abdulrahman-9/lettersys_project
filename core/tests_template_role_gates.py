"""حارسُ «لا شرطَ دورٍ في قالب» (7.4‑هـ §5.2 · قاعدةُ §7.6).

القالبُ يقرأ بوّاباتٍ محسوبةً في بايثون (``nav.*`` · ``can_*`` · ``comment.can_edit``)
ولا يحمل ``is_staff``/``is_superuser``/``has_perm``/``.groups`` داخل ``{% if %}``.
المقصورُ على ``{% if %}``/``{% elif %}`` مقصود: تمريرُ ``is_superuser`` كسمةِ ``data-``
إلى JS ليس بوّابةَ عرض. ``ALLOWED`` تحمل **عرضَ حقيقةٍ** لا بوّابة — كلُّ سطرٍ بسببه.
"""

import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

PATTERN = re.compile(
    r"\{%\s*(?:if|elif)\b[^%]*\b(?:is_staff|is_superuser|has_perm|perms\.|\.groups)\b")

#: (الملفّ نسبةً إلى templates/، نصُّ السطر بعد strip) ⟵ السبب.
ALLOWED = {
    ('core/admin_panel.html', '{% if row.user.is_superuser %}'):
        'شارةُ «مدير نظام» بجانب الاسم — عرضُ حقيقةٍ لا حراسةُ فعلٍ أو تنقّل',
}


def _role_conditions():
    root = Path(settings.BASE_DIR) / 'templates'
    found = set()
    for f in sorted(root.rglob('*.html')):
        for no, line in enumerate(f.read_text(encoding='utf-8', errors='replace').splitlines(), 1):
            if PATTERN.search(line):
                found.add((str(f.relative_to(root)).replace('\\', '/'), line.strip(), no))
    return found


class NoRoleConditionInTemplatesTests(SimpleTestCase):

    def test_templates_carry_no_role_condition_outside_the_allow_list(self):
        found = _role_conditions()
        keyed = {(f, text): no for f, text, no in found}
        unexpected = {f'{f}:{no} {text}' for (f, text), no in keyed.items()
                      if (f, text) not in ALLOWED}
        self.assertEqual(unexpected, set(),
                         'شرطُ دورٍ في قالب — يُحسَب في العرض أو في nav_gates، لا يُوسَّع ALLOWED')

    def test_allow_list_has_no_stale_entry(self):
        present = {(f, text) for f, text, _ in _role_conditions()}
        stale = set(ALLOWED) - present
        self.assertEqual(stale, set(), f'سطرٌ في ALLOWED لم يعد موجوداً — احذفه: {sorted(stale)}')
