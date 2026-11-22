# -*- coding: utf-8 -*-
"""صفحةُ «دمج البيانات من النظام القديم» على الهويّة الموحّدة (11-19) — حرّاسُ الانتقال والأعطابِ المُصلَحة.

١. الانضمامُ إلى v2، وورقتُها (css/data_restore.css) بالرموز وحدها، ولا ‎style=‎ ولا ‎<style>‎ في القالب.
٢. لا نافذةَ أصليّة: التأكيدُ حواريّةُ التطبيق (‎data-confirm‎ للنموذج، و‎ask()‎ في السكربت — احتياطُها
   الأصليُّ الوحيد خلف ‎confirmDelete‎ كما يطلب ‎tests_audit_admin_1008‎).
٣. الأعطابُ المُصلَحة:
   - الخطوةُ «اللاحقة» كانت تُبهَت بشفافيّة ‎.55‎ — نصُّها ≈ 2.4:1 وأزرارُها تعمل؛ الآن ختمٌ ووسمٌ مكتوب.
   - جداولُ السكربت كانت ‎.table‎ فيلصق app.css خليّتَها الأخيرة بخلفيّةٍ بيضاء: أبيضُ على أبيض في الداكن.
   - عناصرُ متصفّح ملفّات الخادم كانت ‎div‎ بنقرٍ وحده — لا تُبلَغ بلوحة المفاتيح.
   - ‎.env‎ و‎.bak‎ تنقلب نقطتُهما (‎env.‎)، ومساراتُ ويندوز في حقلٍ يمينيّ.
   - العناوينُ تقفز h4 ⟵ h6، والأرقامُ بصيغتين (13095 من الخادم و13,095 من السكربت).
   - لا طريقَ رجوع ولا مؤشّرَ مراحل للمسار ذي الخطوات الأربع.
"""
import re
from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / 'templates' / 'core' / 'data_restore.html'
SHEET = ROOT / 'static' / 'css' / 'data_restore.css'
SCRIPT = ROOT / 'static' / 'js' / 'data_restore.js'

COMMENT = re.compile(r'/\*.*?\*/', re.S)
RULE = re.compile(r'([^{}]+)\{([^{}]*)\}')
DECL = re.compile(r'([\w-]+)\s*:\s*([^;{}]+)')
NAMED = ('white', 'black', 'red', 'green', 'blue', 'gray', 'grey', 'orange', 'yellow', 'silver', 'navy')


def _read(path):
    return path.read_text(encoding='utf-8')


def _rules():
    """(المحدِّد، [(الخاصّيّة، القيمة)…]) لكلّ قاعدةٍ في الورقة — التعليقاتُ محذوفة."""
    css = COMMENT.sub(' ', _read(SHEET))
    return [(sel.strip(), DECL.findall(body)) for sel, body in RULE.findall(css)]


def _function(src, head):
    """جسمُ دالّةٍ في السكربت حتى إغلاقها بمسافتين (أسلوبُ الملفّ)."""
    body = src[src.index(head):]
    return body[:body.index('\n  }\n')]


def raw_colours(rules):
    found = []
    for sel, decls in rules:
        for prop, value in decls:
            v = value.strip().lower()
            found += [f'{sel} {{{prop}: {h}}}' for h in re.findall(r'#[0-9a-f]{3,8}\b', v) if h != '#fff']
            if re.search(r'\b(?:rgba?|hsla?)\(\s*[\d.]', v):
                found.append(f'{sel} {{{prop}: {v[:40]}}}')
            found += [f'{sel} {{{prop}: {n}}}' for n in NAMED if re.search(r'(?<![\w-])' + n + r'(?![\w-])', v)]
    return found


class RestoreIdentitySourceTests(SimpleTestCase):

    def test_the_page_opts_into_the_identity(self):
        tpl = _read(TEMPLATE)
        self.assertIn('{% block html_attrs %} data-lx-page="v2"{% endblock %}', tpl)

    def test_the_sheet_speaks_tokens_only(self):
        rules = _rules()
        self.assertGreater(len(rules), 40)
        self.assertEqual(raw_colours(rules), [])
        self.assertNotRegex(_read(SHEET), r'(?<![\w-])data-theme\b')

    def test_the_template_carries_no_inline_paint(self):
        tpl = _read(TEMPLATE)
        self.assertEqual(re.findall(r'\sstyle\s*=', tpl), [])
        self.assertNotIn('<style', tpl)
        self.assertNotRegex(tpl, r'(?<![\w-])data-theme\b')
        # مكوّناتُ «البرتقاليّ» القديمة بخلفيّةٍ بيضاء صريحة لا تعرف الداكن
        self.assertNotIn('field-brand', tpl)
        self.assertNotIn('btn-brand', tpl)

    def test_no_native_dialog(self):
        src = _read(SCRIPT)
        self.assertEqual(re.findall(r'(?<![\w.])(?:alert|confirm|prompt)\(', src), [])
        self.assertEqual(re.findall(r'window\.(?:alert|prompt)\(', src), [])
        # الاحتياطُ الأصليُّ الوحيد داخل ask() وخلف حواريّة التطبيق
        self.assertEqual(src.count('window.confirm('), 1)
        ask = _function(src, 'function ask(opts)')
        self.assertIn('window.confirmDelete ? window.confirmDelete(opts)', ask)
        self.assertIn('window.confirm(', ask)
        tpl = _read(TEMPLATE)
        self.assertNotRegex(tpl, r'(?<![\w.-])(?:alert|confirm|prompt)\(')
        self.assertNotRegex(tpl, r'\son[a-z]+\s*=')
        self.assertRegex(tpl, r'<form method="post" class="rs-bak"\s+data-confirm="')

    def test_a_later_step_is_not_faded(self):
        dimmed = [f'{sel} {{{prop}: {value.strip()}}}' for sel, decls in _rules()
                  if 'rs-step' in sel or 'blocked' in sel
                  for prop, value in decls if prop == 'opacity']
        self.assertEqual(dimmed, [])

    def test_script_tables_and_chips_are_the_pages_own(self):
        src = _read(SCRIPT)
        self.assertIn('<table class="rs-table">', src)
        self.assertNotRegex(src, r'class="table\b')
        for legacy in ('table-responsive', 'table-warning', 'text-bg-', 'btn-light', 'style="'):
            with self.subTest(legacy=legacy):
                self.assertNotIn(legacy, src)

    def test_the_file_browser_is_reachable_by_keyboard(self):
        fn = _read(SCRIPT)
        fn = fn[fn.index('function initBrowser()'):]
        for hook in ('bak-nav', 'bak-pick'):
            with self.subTest(hook=hook):
                self.assertRegex(fn, r'<button type="button" class="rs-(?:entry|quick) ' + hook)
        self.assertNotRegex(fn, r'<div[^>]*bak-(?:nav|pick)')

    def test_the_track_mirrors_the_steps_and_leads_back_to_them(self):
        tpl = _read(TEMPLATE)
        self.assertIn('<nav class="rs-track" aria-label="مراحل الدمج">', tpl)
        for n in '1234':
            with self.subTest(step=n):
                self.assertIn(f'id="rsStep{n}" data-step="{n}"', tpl)
                self.assertRegex(tpl, rf'<li data-step="{n}" data-state="\w+">\s*<a href="#rsStep{n}"')
        src = _read(SCRIPT)
        self.assertIn('syncTrack();', _function(src, 'function setStep('))
        self.assertIn("link.setAttribute('aria-current', 'step')", _function(src, 'function syncTrack()'))

    def test_the_back_path_leads_to_the_backups(self):
        crumbs = re.search(r'<nav class="rs-crumbs" aria-label="[^"]+">(.*?)</nav>', _read(TEMPLATE), re.S)
        self.assertIsNotNone(crumbs)
        self.assertIn('<a href="{% url \'backup_database\' %}">', crumbs.group(1))
        self.assertIn('aria-current="page"', crumbs.group(1))

    def test_numbers_paths_and_code_are_isolated(self):
        code_rules = [dict(decls) for sel, decls in _rules() if re.search(r'(?<![\w-])code\b', sel)]
        self.assertTrue(any(d.get('direction', '').strip() == 'ltr' and d.get('unicode-bidi', '').strip() == 'isolate'
                            for d in code_rules))
        tpl = _read(TEMPLATE)
        for field in ('rsServer', 'rsDatabase', 'rsUser', 'bakPathInput', 'bakServer', 'bakUser', 'bakWorkDir',
                      'bakCurPath'):
            with self.subTest(field=field):
                self.assertRegex(tpl, rf'id="{field}"[^>]*\sdir="ltr"')
        for stat in ('books', 'stamped', 'unstamped', 'attachments'):
            with self.subTest(stat=stat):
                self.assertIn(f'<bdi dir="ltr" data-stat="{stat}">', tpl)
        # «.env» داخل العنصر النائب (لا وسمَ فيه) بعزلٍ يونيكوديّ LRI…PDI
        self.assertEqual(tpl.count('&#x2066;.env&#x2069;'), 2)

    def test_one_heading_per_level(self):
        tpl = _read(TEMPLATE)
        self.assertEqual(len(re.findall(r'<h1\b', tpl)), 1)
        self.assertEqual(len(re.findall(r'<h2 class="rs-step__t"', tpl)), 4)
        self.assertEqual(re.findall(r'<h[3-6]\b', tpl), [])

    def test_numbers_share_one_format(self):
        tpl = _read(TEMPLATE)
        for stat in ('books', 'stamped', 'unstamped', 'attachments'):
            with self.subTest(stat=stat):
                self.assertIn(f'data-stat="{stat}">{{{{ state.{stat}|grouped }}}}</bdi>', tpl)
        self.assertIn("toLocaleString('en-US')", _read(SCRIPT))

    def test_the_assets_are_cache_busted(self):
        tpl = _read(TEMPLATE)
        self.assertIn("{% static 'css/data_restore.css' %}?v=20261119-pages", tpl)
        self.assertIn("{% static 'js/data_restore.js' %}?v=20261119-pages", tpl)


class RestorePageRenderTests(TestCase):
    """العرضُ وحده تغيّر: المعرّفاتُ التي يقرؤها السكربت وأسماءُ حقول نموذج الباكاب وهدفُه كما هي."""

    HOOKS = ('rsServer', 'rsDatabase', 'rsUser', 'rsPass', 'rsProbeBtn', 'rsProbeOut', 'rsReconcilePreview',
             'rsReconcileApply', 'rsVerify', 'rsReconcileOut', 'rsDeltaBtn', 'rsDeltaOut', 'rsMergeForm', 'rsModeSkip',
             'rsModeUpdate', 'rsFiles', 'rsMergeBtn', 'rsJobPanel', 'rsJobSpin', 'rsJobId', 'rsJobStatus',
             'rsJobCancel', 'rsJobBar', 'rsJobPhase', 'rsJobOut', 'rsMergeOut', 'rsState', 'bakBrowseModal',
             'bakUpBtn', 'bakCurPath', 'bakQuick', 'bakBrowseList', 'bakPathInput')
    FIELDS = ('bak_path', 'bak_server', 'bak_user', 'bak_password', 'bak_work_dir', 'merge_mode', 'restore_files',
              'dry_run', 'include_held')

    @classmethod
    def setUpTestData(cls):
        cls.boss = get_user_model().objects.create_superuser('restore_boss', 'rb@x.co', 'pw-restore-boss-1')

    def test_the_page_renders_on_the_identity_with_its_contract(self):
        self.client.force_login(self.boss)
        resp = self.client.get(reverse('data_restore'))
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode('utf-8')
        self.assertIn('data-lx-page="v2"', html)
        self.assertIn('css/data_restore.css?v=20261119-pages', html)
        for hook in self.HOOKS:
            with self.subTest(hook=hook):
                self.assertEqual(html.count(f'id="{hook}"'), 1)
        for name in self.FIELDS:
            with self.subTest(field=name):
                self.assertIn(f'name="{name}"', html)
        self.assertIn('name="action" value="restore_from_bak"', html)
        for n in '1234':
            self.assertIn(f'class="rs-step" id="rsStep{n}" data-step="{n}"', html)
        self.assertEqual(html.count('data-stat="'), 4)
        self.assertIn('window.RESTORE_URLS', html)
