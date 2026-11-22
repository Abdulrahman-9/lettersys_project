"""حرّاسُ صفحة الإدخال الذكيّ على الهويّة الموحّدة v2 (2026-11-19).

١. الصفحةُ منقولة: ‎data-lx-page="v2"‎ — وبدونه لا وضعَ داكناً ولا رموز.
٢. أوراقُها الثلاث رموزٌ وحدَها: لا لونَ صريحاً إلّا الأبيضَ حبراً على التركواز العميق وسِتارَ حوارات الهويّة،
   ولا ‎[data-theme="dark"]‎ (صفةُ الوضع القديم)، ولا ‎<style>‎ ولا لونَ في ‎style="…"‎ في القالب، ولا لونَ صريحاً
   في خطّافات الألوان التي يكتبها السكربت.
٣. لا ‎alert()‎، وكلُّ ‎confirm()‎ أصليّة احتياطٌ خلف حواريّة التطبيق (confirmDelete/ToastCenter) لا يُبلغ.
٤. العطوبُ التي أُصلحت: قواعدُ ‎.modal-*‎ كانت عامّةً فتطلي حواراتِ Bootstrap كلَّها في الصفحة (رأسٌ تركوازيّ
   وجسمٌ فاتحٌ بمؤشّر يد)؛ نقطةُ الثقة كانت خضراءَ مثبّتةً حتّى على شارةٍ حمراء؛ التلميحاتُ ‎#94a3b8‎ (2.56:1)؛
   ‎text-dark‎ على زرّ التحذير (حبرٌ داكنٌ على سطحٍ داكن)؛ لا زرَّ وضعٍ على المكتب (الشريطُ العلويّ مخفيٌّ هنا).
"""
import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

ROOT = Path(settings.BASE_DIR)
TEMPLATE = 'templates/core/extraction_smart_desktop.html'
SHEETS = ('static/extraction_smart.css', 'static/css/doc_canvas.css', 'static/css/document_manager.css')
JS = ('static/extraction_smart.js', 'static/title_autocomplete.js', 'static/js/document_manager.js',
      'static/js/date_dmy.js', 'static/js/extraction_progress.js', 'static/js/subject_locate.js')

COLOR = re.compile(r'#[0-9a-fA-F]{3,8}\b|rgba?\([^)]*\)|(?<![\w-])(?:white|black)(?![\w-])')
# الأبيضُ حبرٌ على التركواز العميق (رأسُ المعاينة واللوح)، والسِّتارُ لونُ خلفيّة حوارات الهويّة (components.css)
ALLOWED = re.compile(r'#fff\b|rgba\(\s*255,\s*255,\s*255,\s*[.\d]+\s*\)|rgba\(\s*4,\s*33,\s*30,\s*[.\d]+\s*\)|rgba\(var\(--lx-[a-z-]+-rgb\)')
WHITE_ON_TEAL = re.compile(r'\.active|modal-header|preview-scan-status|pager|xp-fly|xp-fill|thumb-num')


def _read(rel):
    return (ROOT / rel).read_text(encoding='utf-8')


def _code(src):
    """النصُّ بلا تعليقات (JS وCSS وDjango وHTML) — التعليقاتُ تذكر ‎#1d4ed8‎ و‎confirm()‎ تاريخاً لا شيفرة."""
    src = re.sub(r'/\*.*?\*/|<!--.*?-->|\{% comment %\}.*?\{% endcomment %\}|\{#.*?#\}', '', src, flags=re.S)
    return re.sub(r'(?<![:\'"\w])//[^\n]*', '', src)


def _rules(css):
    css = re.sub(r'/\*.*?\*/', '', css, flags=re.S)
    return [(m.group(1).strip(), m.group(2)) for m in re.finditer(r'([^{}]+)\{([^{}]*)\}', css)]


class EntryIdentityTests(SimpleTestCase):

    def test_page_opts_into_v2(self):
        self.assertIn('{% block html_attrs %} data-lx-page="v2"{% endblock %}', _read(TEMPLATE))

    def test_sheets_are_tokens_only(self):
        for rel in SHEETS:
            css = re.sub(r'/\*.*?\*/', '', _read(rel), flags=re.S)
            with self.subTest(sheet=rel):
                self.assertNotIn('data-theme=', css)
                raw = [c for c in COLOR.findall(css) if not ALLOWED.match(c)]
                self.assertEqual(raw, [], 'لونٌ صريحٌ خارج الرموز')
                for head, body in _rules(css):
                    if re.search(r'#fff\b|rgba\(\s*255,', body):
                        self.assertRegex(head, WHITE_ON_TEAL, 'الأبيضُ حبرٌ على التركواز العميق وحده')

    def test_template_and_script_hooks_carry_no_raw_colour(self):
        tpl = _read(TEMPLATE)
        self.assertNotIn('<style', tpl)
        self.assertEqual(re.findall(r'style="[^"]*(?:color|background)[^"]*"', tpl), [])
        self.assertNotIn('style.cssText', tpl)
        for rel in ('static/extraction_smart.js', 'static/title_autocomplete.js'):
            with self.subTest(js=rel):
                self.assertEqual(re.findall(r'#[0-9a-fA-F]{6}\b|#[0-9a-fA-F]{3}\b(?![\w-])', _code(_read(rel))), [])

    def test_no_native_dialogs(self):
        for rel in JS + (TEMPLATE,):
            src = _code(_read(rel))
            with self.subTest(file=rel):
                self.assertEqual(re.findall(r'(?<![\w.])alert\(', src), [])
                self.assertEqual(re.findall(r'(?<![\w.$])confirm\(', src), [])
                for m in re.finditer(r'window\.confirm\(', src):
                    before = src[max(0, m.start() - 320):m.start()]
                    self.assertRegex(before, r'confirmDelete|ToastCenter\.action',
                                     'confirm() أصليّة ليست احتياطاً خلف حواريّة التطبيق')

    def test_dialog_rules_are_scoped_to_the_preview_panel(self):
        for head, _ in _rules(_read('static/extraction_smart.css')):
            for sel in head.split(','):
                if re.search(r'\.modal-(?:header|body|footer)(?![\w-])', sel) and not sel.strip().startswith('@'):
                    with self.subTest(selector=sel.strip()):
                        self.assertRegex(sel, r'\.extraction-preview-modal|:has\(#previewPager|\.extraction-container:',
                                         'قاعدةٌ عامّة تطلي حواراتِ Bootstrap في الصفحة')

    def test_confidence_dot_follows_the_badge_and_hints_read(self):
        self.assertIn('<span class="confidence-indicator" aria-hidden="true"></span>', _read(TEMPLATE))
        rules = dict(_rules(_read('static/extraction_smart.css')))
        self.assertIn('background: currentColor', rules['.confidence-indicator'])
        self.assertIn('color: var(--lx-mute)', rules['.input-hint'])

    def test_warning_buttons_keep_their_identity_ink(self):
        self.assertNotIn('btn-warning text-dark', _read('static/extraction_smart.js'))
        self.assertNotIn('bg-light text-dark', _read('static/extraction_smart.js'))

    def test_desktop_header_carries_the_mode_toggle(self):
        tpl = _read(TEMPLATE)
        header = tpl[tpl.index('<div class="app-page-header">'):tpl.index('<div\n    class="extraction-container"')]
        self.assertRegex(header, r'<button[^>]*class="lx-theme-toggle app-page-theme"[^>]*data-theme-toggle')
        self.assertIn("badge.className = 'edit-mode-badge';", tpl)

    def test_saving_without_a_file_asks_through_the_app_dialog(self):
        # «حفظ بلا ملف؟» سؤالٌ يوقف الحفظ: حواريّةُ التطبيق لا توستٌ في الزاوية (11-22)
        src = _read('static/extraction_smart.js')
        fn = src[src.index('async confirmSaveWithoutFile()'):]
        fn = fn[:fn.index('\n    }\n')]
        self.assertIn('window.confirmDelete(question)', fn)
        self.assertIn("cancelText: 'عُد لإرفاق ملف', danger: false", fn)
        self.assertNotIn('ToastCenter', fn)
        app = _read('static/app.js')
        self.assertIn("if (opts.cancelText) modal.querySelector('.btn-cancel').textContent = opts.cancelText;", app)
