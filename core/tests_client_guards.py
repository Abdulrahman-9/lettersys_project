"""حرّاسُ شيفرة العميل — عطبان على الوسم المنشور لا تلتقطهما حزمةُ بايثون وحدَها.

① **`showToast` تدور على نفسها**: `function showToast` في `static/app.js` تصريحٌ
في سكربتٍ كلاسيكيّ فهو خاصّيّةُ `window` نفسُها، و`window.showToast = function(){
return showToast(...) }` في ذيل الملفّ كان يستبدلها فيُحَلّ النداءُ الداخليُّ إلى
الغلاف ⟵ `RangeError` عند كلّ رسالة، ويتوقّف الفعلُ الذي يليها.

② **بطاقةُ البريد في تفاصيل الكتاب** تبني `innerHTML` من سجلّ الإرسال — وحقولُه
نصٌّ لا وسم، فكلُّها تمرّ من `esc()`.

نصّيّان عمداً: لا محرّكَ JS في الحزمة؛ والنمطُ هنا ضيّقٌ محدَّدُ الموضع فلا يُخطئ
الصياغاتِ كما أخطأها كنسُ الأنماط الواسع.
"""

import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

ROOT = Path(settings.BASE_DIR)

WINDOW_ASSIGN = re.compile(r'window\.showToast\s*=')


class ToastIsNotSelfWrappedTests(SimpleTestCase):

    def test_app_js_still_declares_show_toast(self):
        src = (ROOT / 'static' / 'app.js').read_text(encoding='utf-8')
        self.assertRegex(src, r'(?m)^function showToast\(')

    def test_no_file_reassigns_window_show_toast(self):
        offenders = [
            str(path.relative_to(ROOT))
            for base in ('static', 'templates')
            for path in (ROOT / base).rglob('*')
            if path.suffix in ('.js', '.html')
            and WINDOW_ASSIGN.search(path.read_text(encoding='utf-8', errors='ignore'))
        ]
        self.assertEqual(offenders, [])


class BookMailCardEscapesTests(SimpleTestCase):

    def test_every_log_field_passes_through_esc(self):
        src = (ROOT / 'templates' / 'core' / 'book_detail.html').read_text(encoding='utf-8')
        # `l.status` مسموحٌ في المقارنة وحدَها: يُنتج أسماءَ أصنافٍ ثابتة لا نصّاً.
        raw = re.findall(r'\$\{l\.(?!status\s*===)\w+', src)
        self.assertEqual(raw, [])
        self.assertIn('${esc(l.subject)}', src)
