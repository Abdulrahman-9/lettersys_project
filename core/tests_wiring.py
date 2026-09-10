"""حارسُ «مبنيٌّ ولا يوصله أحد» (7.4‑هـ §5.1) — ثلاثةُ أشقّاء:

1. عقدُ ``nav_gates``: كلُّ مفتاحٍ تُنتجه الدالّةُ يقرؤه قالبٌ، وكلُّ ``nav.<x>`` في
   القوالب مفتاحٌ حقيقيّ (جانغو يُعيد فراغاً صامتاً لمفتاحٍ مجهول).
   السابقة: ``nav.audit`` حُسب ولم يقرأه أحد — رابطُ سجلّ الحركات غيرَ ظاهر (§7.2).
2. بلوغُ أسماء المسارات: مسارٌ مسمّىً لا يُذكر بالاسم (``{% url %}``/``reverse``/
   ``redirect``) ولا يظهر مقطعُه الأخيرُ مسبوقاً بـ``/`` في أيّ قالبٍ أو JS = مبنيٌّ
   بلا مدخل. **قياسٌ ساكنٌ لا حكمٌ مطلق** (مسارٌ يُبنى ديناميّاً يفلت منه)، لذلك
   يُشحَن بقائمةِ سماحٍ مراجَعةٍ بالعين: يفشل حين يدخلها اسمٌ جديد، ويفشل حين يخرج
   اسمٌ منها بلا تحديث (نظافةُ المحاسبة).
3. صفرُ عرضٍ يتيم: كلُّ ``def x(request, …)`` في ملفّات العرض مذكورةٌ في ``urls.py``.
"""

import re
from pathlib import Path

from django.conf import settings
from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase
from django.urls import get_resolver

from core.context_processors import nav_gates

BASE = Path(settings.BASE_DIR)


def _read_tree(roots, exts, skip=lambda f: False):
    chunks = []
    for r in roots:
        for f in sorted((BASE / r).rglob('*')):
            if f.is_file() and f.suffix in exts and 'node_modules' not in f.parts and not skip(f):
                chunks.append(f.read_text(encoding='utf-8', errors='replace'))
    return '\n'.join(chunks)


def _templates_text():
    return _read_tree(('templates',), {'.html'})


class _Req:
    def __init__(self, user):
        self.user = user


class NavGatesContractTests(TestCase):

    def test_every_gate_has_a_consumer_and_every_consumer_a_gate(self):
        admin = User.objects.create_superuser('wire_boss', 'w@x.com', 'pw-wire-11')
        produced = set(nav_gates(_Req(admin))['nav'].keys())
        self.assertTrue(produced, 'nav_gates لم تُنتج مفتاحاً')
        text = _templates_text()
        for key in produced:
            self.assertRegex(text, r'\bnav\.' + re.escape(key) + r'\b',
                             f'بوّابةٌ مبنيّةٌ بلا مستهلك: nav.{key}')
        # داخل وسوم القالب فقط — `nav.d-flex` في CSS ليست قراءةَ بوّابة.
        tags = ' '.join(re.findall(r'\{[%{].*?[%}]\}', text, re.S))
        consumed = set(re.findall(r'\bnav\.([A-Za-z_][A-Za-z0-9_]*)', tags))
        self.assertEqual(consumed - produced, set(),
                         'قالبٌ يقرأ بوّابةً لا تُنتَج (يعود فراغاً صامتاً)')


# ── الشقّ الثاني ────────────────────────────────────────────────────────────
#: مراجَعةٌ بالعين 2026‑09‑10 — كلُّ سطرٍ بسببه. إضافةُ اسمٍ هنا قرارٌ لا تسكين.
KNOWN_UNWIRED = {
    'dev_login':                'أداةُ تطويرٍ تُفتح بالمسار عمداً',
    'followup_activity_report': 'مسارٌ وعرضٌ وقالبٌ كاملٌ بلا رابطٍ واحد (§7.2) — قرارُ مالك',
    'legacy_import':            'صفحةُ الاستيراد من الورق بلا مدخل — تُفتح بالمسار بعد الترحيل',
    'entity_stats':             'API إحصاءٍ بلا مستهلك',
    'search_titles':            'API بحثٍ بلا مستهلك (title_autocomplete يستعمل مساراً آخر)',
    'ai_extraction_statistics': 'API إحصاءٍ للاستخراج بلا مستهلك',
    'mail-api-stats':           'API إحصاءِ بريدٍ بلا مستهلك',
    'mail-api-bulk-send':       'إرسالٌ جماعيٌّ بلا واجهة',
    'email-test-smtp':          'الصفحةُ تستعمل mail-api-test-smtp لا هذا',
    'email-settings':           'واجهةُ إعداداتٍ قديمة؛ الحيّةُ mail_settings',
    'entity-email-info':        'واجهةٌ قديمةٌ لبريد الجهة بلا مستهلك',
    'api_remove_link':          'إزالةُ الربط بلا زرّ (link_picker يضيف ولا يزيل)',
    'network-ping':             'المفردُ بلا مستهلك؛ الجارُ network-ping-all موصول',
    'extraction-quick-start':   'مدخلٌ قديمٌ يُعيد التوجيه — يبقى للروابط المحفوظة',
    'extraction-wizard':        'مدخلٌ قديمٌ يُعيد التوجيه — يبقى للروابط المحفوظة',
    'extraction-results-ui':    'صفحةُ نتائجٍ قديمة بلا مدخل (الحيُّ سطحُ الاستخراج الذكيّ)',
    'media':                    'يُطلَب بمسار الملفّ (attachment.file.url) لا بالاسم — بحكم طبيعته',
}


def _named_routes():
    routes = {}

    def walk(patterns, prefix='', ns=None):
        for p in patterns:
            pat = str(p.pattern)
            if hasattr(p, 'url_patterns'):
                walk(p.url_patterns, prefix + pat, p.namespace or ns)
            elif p.name:
                routes[(ns + ':' + p.name) if ns else p.name] = prefix + pat
    walk(get_resolver().url_patterns)
    return routes


def _unwired_routes():
    routes = _named_routes()
    py = _read_tree(('core', 'lettersys', 'scan_agent'), {'.py'},
                    skip=lambda f: f.name == 'urls.py' or f.name.startswith('tests'))
    ui = _read_tree(('templates', 'static', 'core'), {'.html', '.js'})
    found = set()
    for name, path in routes.items():
        if name.startswith('admin:') or name == 'api-root':
            continue
        q = re.escape(name)
        by_name = (re.search(r"\{%\s*url\s+['\"]" + q + r"['\"]", ui)
                   or re.search(r"(reverse|reverse_lazy|redirect)\(\s*['\"]" + q + r"['\"]", py)
                   or re.search(r"pattern_name\s*=\s*['\"]" + q + r"['\"]", py))
        if by_name:
            continue
        segs = [s for s in path.split('/')
                if s and not s.startswith('<') and not s.startswith('^') and not s.startswith('(')]
        last = segs[-1] if segs else ''
        if last and re.search(r"/" + re.escape(last) + r"(/|['\"`?])", ui):
            continue
        found.add(name)
    return found


class RouteReachabilityTests(SimpleTestCase):

    def test_no_new_unwired_route_and_the_allow_list_is_current(self):
        found = _unwired_routes()
        new = found - set(KNOWN_UNWIRED)
        self.assertEqual(new, set(), f'مسارٌ مبنيٌّ بلا مدخل (لم يُراجَع): {sorted(new)}')
        stale = set(KNOWN_UNWIRED) - found
        self.assertEqual(stale, set(),
                         f'اسمٌ في قائمة السماح صار موصولاً أو حُذف — حدِّث القائمة: {sorted(stale)}')


class NoOrphanViewTests(SimpleTestCase):

    #: دوالُّ مساعدةٍ تأخذ request ولا تُسجَّل كعروض (مقيس 2026‑09‑10).
    KNOWN_HELPERS = {'collect_filters', 'is_ajax'}

    def test_every_view_function_is_routed(self):
        urls = _read_tree(('core', 'lettersys'), {'.py'}, skip=lambda f: f.name != 'urls.py')
        orphans = set()
        for f in sorted((BASE / 'core' / 'views').glob('*.py')):
            src = f.read_text(encoding='utf-8')
            for m in re.finditer(r'^def (\w+)\(request\b', src, re.M):
                fn = m.group(1)
                if fn.startswith('_') or fn in self.KNOWN_HELPERS:
                    continue
                if not re.search(r'\b' + re.escape(fn) + r'\b', urls):
                    orphans.add(f'{f.name}:{fn}')
        self.assertEqual(orphans, set(), f'عرضٌ يتيم بلا مسار: {sorted(orphans)}')
