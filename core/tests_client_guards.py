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


class UnifiedListKeepsFollowupTests(SimpleTestCase):
    """q3 طرفاً إلى طرف: رابطُ اللوحة `?followup=active` يبقى بعد أوّل نقرةٍ في القائمة.

    كانت القائمةُ تقرأ `status`/`due_status` وحدَهما من العنوان فتُسقط `followup`
    عند أوّل ترقيمٍ أو فرز، وكانت رقاقتا «قيد المتابعة» و«مستحق اليوم» لا تُرسلان شيئاً.
    """

    def test_ajax_manager_reads_and_writes_followup(self):
        src = (ROOT / 'static' / 'js' / 'book_unified_ajax_manager.js').read_text(encoding='utf-8')
        for needle in ("p.get('followup')", 'params.followup'):
            self.assertTrue(needle in src, needle)

    def test_pill_click_moves_aria_pressed_with_active(self):
        """الخادمُ يرسم aria-pressed؛ النقرةُ تنقله مع .active وإلّا بقيت الرقاقةُ «مضغوطةً» سمعاً."""
        src = (ROOT / 'static' / 'js' / 'book_unified_ajax_manager.js').read_text(encoding='utf-8')
        self.assertRegex(src, r"setAttribute\('aria-pressed', p === pill \? 'true' : 'false'\)")

    def test_asset_versions_bumped(self):
        """فخُّ الـPWA: بلا `?v=` و`CACHE_VERSION` جديدَين لا يصل التعديلُ إلى المتصفّح.

        يثبّت الثابتَ لا قيمةَ اليوم: «لا أقدمَ من هذا الإيداع» — فرفعُ الدمج
        القادم مع `feat/scan-lan` (v112) أو أيُّ رفعٍ لاحق يبقى أخضر.
        """
        assets = (
            ('templates/core/dashboard.html', 'css/dashboard_roles.css'),
            ('templates/base.html', 'design-system.css'),
            ('templates/base.html', 'app.css'),
            ('templates/core/book_unified.html', 'js/book_unified_ajax_manager.js'),
        )
        for rel, asset in assets:
            with self.subTest(file=rel, asset=asset):
                src = (ROOT / rel).read_text(encoding='utf-8')
                m = re.search(r"\{% static '" + re.escape(asset) + r"' %\}\?v=(\d{8})", src)
                self.assertIsNotNone(m, f'{asset}: لا ?v= بتاريخ')
                self.assertGreaterEqual(int(m.group(1)), 20260927, asset)
        sw = (ROOT / 'static' / 'service-worker.js').read_text(encoding='utf-8')
        m = re.search(r"CACHE_VERSION = 'v(\d+)-", sw)
        self.assertIsNotNone(m, 'CACHE_VERSION')
        self.assertGreaterEqual(int(m.group(1)), 111)
