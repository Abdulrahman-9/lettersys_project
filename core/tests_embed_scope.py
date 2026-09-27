"""تدقيقُ الانتقالات §ج — التضمينُ لا يبتلع التطبيق.

`base.html` يوسم روابطَ الإطار بـ`embed=1` **داخل نطاقٍ** فقط، وما خرج عنه يُفتح
بـ`target=_top`. هذا الاختبارُ يحرس اتّساقَ النطاق مع تبويبات مركز الإعدادات
(كلُّ ما يُضمَّن داخل النطاق) ومع خروج الصفحات الكبرى منه.
"""

import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase
from django.urls import reverse


def _embed_scope():
    src = (Path(settings.BASE_DIR) / 'templates' / 'base.html').read_text(encoding='utf-8')
    block = re.search(r"var EMBED_SCOPE = \[(.*?)\];", src, re.S).group(1)
    return re.findall(r"'([^']+)'", block)


class EmbedScopeTests(SimpleTestCase):

    def test_every_embedded_tab_lives_inside_the_scope(self):
        scope = _embed_scope()
        hub = (Path(settings.BASE_DIR) / 'templates' / 'core' / 'settings' / 'hub.html').read_text(encoding='utf-8')
        names = re.findall(r"data-embed-url=\"\{% url '([\w\-]+)' %\}", hub)
        self.assertTrue(names)
        for name in names:
            path = reverse(name)
            self.assertTrue(any(path.startswith(p) for p in scope),
                            f'تبويبٌ مضمَّنٌ خارج النطاق فسيُفتح في النافذة العليا: {name} ⟵ {path}')

    def test_the_big_pages_are_outside_the_scope(self):
        scope = _embed_scope()
        for name in ('book_unified', 'extraction-smart-desktop', 'admin_panel', 'mail_inbox', 'dashboard'):
            path = reverse(name)
            self.assertFalse(any(path.startswith(p) for p in scope),
                             f'صفحةٌ كبرى داخل النطاق فستُرسَم داخل لوحة الإعدادات: {name} ⟵ {path}')

    def test_leaving_links_get_target_top(self):
        src = (Path(settings.BASE_DIR) / 'templates' / 'base.html').read_text(encoding='utf-8')
        self.assertIn("a.setAttribute('target', '_top')", src)
        self.assertIn("f.setAttribute('target', '_top')", src)
