# -*- coding: utf-8 -*-
"""حرّاسُ نقل صفحات إدارة النظام إلى الهويّة v2 (الدفعة 11-19، وحدة «system»).

الصفحاتُ الثماني (المركز · القسم · التشغيل · الأدوار · الحسابات · حسابٌ جديد · محرّرُ الحساب · الحجوزات) تشترك في
ورقةٍ واحدة (static/css/system_admin.css) يربطها base.html لكلّ صفحات المدير، وتقرأ أصنافَها قائمةُ الكتب والنسخُ
الاحتياطيّ. ما يحرسه هذا الملفّ:
١. **الصفحاتُ منقولة** (data-lx-page="v2") — بدونها لا وضعَ داكناً ولا رموز.
٢. **الورقةُ رموزٌ فقط**: لا لونَ خاماً إلّا الأبيضَ حبراً على التركواز العميق (وصورةُ الحساب الكهرمانيّة في العمود
   المشترك، علامةُ وضع الإدارة — لا رمزَ في theme.css لحبرٍ على الذهب)؛ ولا ‎[data-theme]‎ الميّت ولا تجاوزاتٌ لكلّ وضع.
٣. **لا confirm()/alert() أصليّة** في قوالب الوحدة ولا سكربتاتها.
٤. **الأعطابُ المُصلَحة**: أسطحٌ بيضاءُ ثابتة في الداكن · الأساسيُّ تعبئةٌ بلا حبرها (أبيضُ على تركوازٍ فاتح في الداكن)
   · لوحةُ السجلّ تنقلب فاتحةً بنصٍّ فاتح · خاناتُ المصفوفة الثابتة شفّافةٌ في الداكن تحت المرور · قائمةُ القسم
   بعرض 16rem وحدها في المحرّر · حشوةُ ‎.row‎ من Bootstrap تُزيح صفوف القسم · سلسلةُ !important · أهدافٌ دون 24px
   · حوارٌ أصليٌّ بلا جلد الهويّة · أصولٌ تغيّرت بلا رفع نسخة · أفعالُ رأس القسم مبعثرة · اسمُ الدخول مطلوبٌ بلا علامة.
"""
import re
from pathlib import Path

from django.conf import settings
from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from core.models import Department

ROOT = Path(settings.BASE_DIR)
SHEET = 'static/css/system_admin.css'
UNIT = 'templates/core/system_admin/'
PAGES = ('centre', 'department', 'ops', 'roles', 'accounts', 'account_new', 'account', 'reservations')
SCRIPTS = ('static/js/role_matrix.js', 'static/js/account_editor.js', 'static/js/account_new.js')
V2 = '{% block html_attrs %} data-lx-page="v2"{% endblock %}'
BUMP = '?v=20261119-pages'

# الأبيضُ حبرٌ (أو لوحٌ) على التركواز العميق وحده: اللوحُ النشط في العمود، ورأسُ اللوحة المستقلّة، والقسمُ الحاليّ،
# وشريطُ حفظ المصفوفة. وصورةُ الحساب علامةُ الوضع في العمود المشترك (كلّ صفحات المدير).
DEEP_TEAL = ('.sa-nav a.on', '.top.sa-top', '.sa-tabs a.on', '.rm-bar')
MARKER = ('.is-system-admin .app-sidebar-avatar', {'#d99a1e', '#1c1404'})
RAW = re.compile(r'#[0-9a-fA-F]{3,8}\b|\b(?:rgba?|hsla?|hwb|lab|lch|oklab|oklch)\(\s*[\d.][^)]*\)', re.I)
NAMED = re.compile(r'(?<![-\w])(?:white|black|red|green|blue|gray|grey|orange|yellow|purple|brown|pink|navy|teal|'
                   r'silver|maroon|olive|lime|aqua|fuchsia|beige|ivory|wheat|tan)(?![-\w])', re.I)
WHITE = re.compile(r'^(?:#fff|#ffffff|rgba?\(\s*255\s*,\s*255\s*,\s*255\b.*)$', re.I)
NATIVE = re.compile(r'(?<![\w.])(?:window\.)?(?:confirm|alert)\s*\(')


def _read(rel):
    return (ROOT / rel).read_text(encoding='utf-8')


def _css():
    return re.sub(r'/\*.*?\*/', '', _read(SHEET), flags=re.S)


def _rule(selector):
    """جسمُ القاعدة الأولى التي يبدأ بها سطرٌ بهذا المحدِّد (كحرّاس الدفعة 3أ)."""
    match = re.search(r'(?m)^' + re.escape(selector) + r' \{([^}]*)\}', _read(SHEET))
    if match is None:
        raise AssertionError('لا قاعدة «%s» في الورقة' % selector)
    return match.group(1)


def _px(value):
    number, unit = re.fullmatch(r'([\d.]+)(rem|px)', value).groups()
    return float(number) * (16 if unit == 'rem' else 1)


class PagesOptInTests(SimpleTestCase):

    def test_every_page_of_the_unit_opts_into_v2(self):
        missing = [name for name in PAGES if V2 not in _read(UNIT + name + '.html')]
        self.assertEqual(missing, [], 'صفحاتٌ بلا data-lx-page="v2" (لا داكنَ ولا رموز): %s' % missing)


class SheetTokensTests(SimpleTestCase):

    def test_the_sheet_speaks_tokens_only(self):
        offences = []
        for selector, body in re.findall(r'([^{}]+)\{([^{}]*)\}', _css()):
            selector = ' '.join(selector.split())
            found = [m.group(0) for m in RAW.finditer(body)] + [m.group(0) for m in NAMED.finditer(body)]
            for colour in found:
                if WHITE.match(colour) and any(ctx in selector for ctx in DEEP_TEAL):
                    continue
                if selector == MARKER[0] and colour.lower() in MARKER[1]:
                    continue
                offences.append('%s → %s' % (selector[-60:], colour))
        self.assertEqual(offences, [], 'ألوانٌ خامٌ خارج الرموز (أو أبيضُ خارج التركواز العميق): %s' % offences)

    def test_no_dead_theme_attribute_and_no_per_mode_overrides(self):
        css = _css()
        self.assertNotIn('data-theme', css.replace('data-bs-theme', ''), '‎[data-theme]‎ ميّتٌ منذ الهويّة')
        self.assertNotIn('data-bs-theme', css, 'الرموزُ تنقلب وحدها: لا تجاوزاتٍ لكلّ وضع في الورقة')
        for name in PAGES + ('_role_row',):
            with self.subTest(template=name):
                self.assertNotIn('data-theme=', _read(UNIT + name + '.html'))

    def test_no_important_chain_is_left(self):
        # ‎:where(.sa-page) a‎ بلا وزن: كان ‎.sa-page a‎ يغلب الأزرارَ فتردّه كلٌّ منها بـ!important
        self.assertNotIn('!important', _css(), 'عادت سلسلةُ !important: الرابطُ العامّ صار له وزن؟')
        self.assertIn(':where(.sa-page) a {', _read(SHEET))


class SheetDefectTests(SimpleTestCase):

    def test_surfaces_follow_the_mode(self):
        # كانت كلُّها ‎#fff‎ ثابتاً: بطاقاتٌ بيضاءُ في الداكن
        for selector in ('.sa-card', '.sa-btn', '.sa-sysbar', '.sa-seg', '.sa-kpi', '.sa-job', '.sa-select', '.sa-input',
                         '.sa-tabs', '.rm-chip', '.rm-note', '.rm-frame', '.rm thead th', '.rm tbody th', '.rm-cell',
                         '.ae-choice'):
            with self.subTest(selector=selector):
                self.assertRegex(_rule(selector), r'background(?:-color)?: var\(--lx-surface\)',
                                 'سطحُ «%s» ليس ‎--lx-surface‎' % selector)

    def test_the_primary_is_a_fill_with_its_ink(self):
        # كان ‎--lx-pri‎ بحبرٍ أبيض: في الداكن تركوازٌ فاتحٌ تحت الأبيض (1.9:1)
        body = _rule('.sa-btn.pri')
        self.assertIn('background: var(--lx-pri-fill)', body, 'الأساسيُّ ليس تعبئةَ الفعل')
        self.assertIn('color: var(--lx-pri-fill-ink)', body, 'التعبئةُ بلا حبرها')
        self.assertIn('color: var(--lx-pri-fill-ink)', _rule('.sa-btn.pri:hover'), 'المرورُ يفقد حبرَ التعبئة')

    def test_the_log_follows_the_mode(self):
        # كانت لوحةً بلون ‎--lx-ink‎ وحبرٍ فاتحٍ ثابت: في الداكن ينقلب الحبرُ فاتحاً تحت نصٍّ فاتح
        body = _rule('.sa-log')
        self.assertNotIn('background: var(--lx-ink)', body, 'لوحةُ السجلّ بلون الحبر: تنقلب فاتحةً في الداكن')
        self.assertIn('background: var(--lx-surface-2)', body)
        self.assertIn('var(--lx-late)', _rule('.sa-log .e'))
        self.assertIn('var(--lx-wait)', _rule('.sa-log .w'))

    def test_sticky_matrix_cells_stay_opaque_under_the_pointer(self):
        # ‎--lx-pri-soft‎ شفّافٌ في الداكن: كانت الخاناتُ تظهر من خلال العمود الثابت عند المرور
        for selector in ('.rm tbody tr:not(.rm-group):hover > *', '.rm .rm-col-on'):
            with self.subTest(selector=selector):
                body = _rule(selector)
                self.assertIn('color-mix(', body)
                self.assertIn('var(--lx-surface))', body, 'المزجُ ليس فوق السطح: شفّافٌ في الداكن')
                self.assertNotIn('--lx-pri-soft', body, 'لونٌ شفّافٌ في الداكن على خانةٍ ثابتة')
        self.assertIn('var(--lx-surface)', _rule('.rm-cell.pending .rm-tag'), '«لم تُحفظ» شفّافةٌ في الداكن')

    def test_the_editor_select_spans_its_field(self):
        # حدُّ ‎.sa-select‎ (16rem) كان يُقصّر قائمةَ القسم وحدها بين حقول المحرّر وحسابٍ جديد
        self.assertIn('max-width: none', _rule('.ae-field .sa-select'), 'قائمةُ القسم أقصرُ من حقلها')

    def test_bootstrap_row_gutters_do_not_shift_the_rows(self):
        # ‎.row > *‎ في Bootstrap يحشو الأبناءَ 0.75rem — صفوفُ «نشاط القسم» و«الموظّفون» كانت مُزاحة
        self.assertIn('padding-inline: 0', _rule('.sa-rows > .row > *'), 'حشوةُ Bootstrap عادت إلى صفوف القسم')

    def test_small_actions_are_real_targets(self):
        floors = {'.ae-act': 32, '.sa-btn.sm': 32, '.rm-reset': 24, '.rm-ex': 24, '.sa-crumb a': 24, '.sa-sort': 24,
                  '.sa-card-head a': 32, '.rm-jump a': 32}
        for selector, floor in floors.items():
            with self.subTest(selector=selector):
                found = re.search(r'min-height: ([\d.]+(?:rem|px))', _rule(selector))
                self.assertIsNotNone(found, '«%s» بلا ارتفاعٍ أدنى (هدفٌ دون 24px)' % selector)
                self.assertGreaterEqual(_px(found.group(1)), floor, '«%s» أصغرُ من %spx' % (selector, floor))

    def test_the_native_dialog_wears_the_identity(self):
        # ‎<dialog>‎ بلا خلفيّة يرسمه المتصفّح بلونه (Canvas) وخلفيّتُه رماديّةٌ لا تتبع الوضع
        body = _rule('.rm-dialog')
        self.assertIn('background: var(--lx-surface)', body, 'الحوارُ بلا سطح الهويّة')
        self.assertIn('color: var(--lx-ink)', body)
        backdrop = _rule('.rm-dialog::backdrop')
        self.assertIn('color-mix(', backdrop)
        self.assertIn('var(--lx-hero-b)', backdrop, 'خلفيّةُ الحوار ليست تركوازَ القيادة')


class TemplatesAndScriptsTests(SimpleTestCase):

    def test_no_native_confirm_or_alert(self):
        sources = [UNIT + name + '.html' for name in PAGES + ('_role_row',)] + list(SCRIPTS)
        found = [rel for rel in sources if NATIVE.search(_read(rel))]
        self.assertEqual(found, [], 'confirm()/alert() أصليّة (حواريّةُ التطبيق confirmDelete وحدها): %s' % found)

    def test_changed_assets_are_cache_busted_in_the_units_templates(self):
        for name in ('accounts', 'account', 'account_new'):
            with self.subTest(template=name):
                src = _read(UNIT + name + '.html')
                self.assertIn("{% static 'css/system_admin.css' %}" + BUMP, src, 'ورقةٌ تغيّرت بلا رفع نسخة')
                self.assertNotIn('20261118-batch3a', src)
        self.assertIn("{% static 'js/account_editor.js' %}" + BUMP, _read(UNIT + 'account.html'),
                      'سكربتُ المحرّر تغيّر بلا رفع نسخة')

    def test_the_department_head_keeps_its_actions_together(self):
        src = _read(UNIT + 'department.html')
        self.assertIn('<div class="sa-head-actions">', src, 'أفعالُ رأس القسم عادت مبعثرةً بين سطرين')
        group = src[src.index('<div class="sa-head-actions">'):]
        group = group[:group.index('\n    </div>')]
        self.assertIn('class="sa-jump"', group)
        # الروابطُ كما هي — حارسُ tests_system_admin يبحث عنها بهذا النصّ
        self.assertIn('href="{% url \'desk_board\' %}"><i class="bi bi-inbox"', group)
        self.assertIn("?department={{ unit.id }}", group)
        self.assertIn('flex: 1 1 100%', _rule('.sa-head-actions'))

    def test_the_required_username_is_marked_in_words(self):
        src = _read(UNIT + 'account_new.html')
        self.assertIn('<label for="anUser">اسم الدخول (مطلوب)</label>', src, 'حقلٌ مطلوبٌ بلا علامة')
        self.assertNotIn('style="', src, 'نمطٌ مضمَّنٌ في القالب (مكانُه الورقة)')


class RenderedPagesTests(TestCase):
    """الصفحاتُ تُرسم منقولةً فعلاً: الصفةُ على ‎<html>‎ نفسِه (لا نصٌّ في الصفحة)، ولا تأكيدَ أصليّاً في المرسوم."""

    @classmethod
    def setUpTestData(cls):
        cls.dept = Department.objects.create(name='قسم حرّاس الهويّة', code='هـ1')
        cls.admin = User.objects.create_superuser('identity_root', password='pw-identity-1111')
        cls.member = User.objects.create_user('identity_member', password='pw-identity-2222')

    def test_the_pages_render_as_v2_for_the_system_admin(self):
        self.client.force_login(self.admin)
        urls = [reverse('system_centre'), reverse('system_department', args=[self.dept.pk]), reverse('system_ops'),
                reverse('system_roles'), reverse('system_accounts'), reverse('system_account_new'),
                reverse('system_account', args=[self.member.pk]), reverse('system_reservations')]
        for url in urls:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, '<html lang="ar" dir="rtl" data-lx-page="v2">')
                self.assertNotRegex(response.content.decode('utf-8'), r'onsubmit="return confirm\(')
