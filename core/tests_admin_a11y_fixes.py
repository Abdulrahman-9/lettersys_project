"""حرّاسُ إصلاحات «الحسابات والأدوار والهيكل» قبل إعادة البناء (11-15، تقييمٌ مقيس بأمر المالك).

ما قِيس في المتصفّح ثمّ أُصلح، بلا مساسٍ بنموذج الدور (قرارُ المالك معلّق):
١. **الحواراتُ والدرجُ المغلقة خامدة** (inert): كانت مخفيّةً بالشفافيّة فتقع فيها 38 من 249 ضغطة Tab.
٢. **التركيزُ محبوسٌ في المفتوح ويعود إلى زرّه** بعد الإغلاق (كان يهرب 9 من 14، ويضيع بعد Esc).
٣. **«رجوع» يعيد التبويبَ السابق**: كان replaceState فيُخرج من اللوحة كلّها.
٤. **الرسائلُ تُسمَع**: role="status"/"alert" على شريط اللوحة.
٥. **حقولُ الحوارات بأسماءٍ مقترنة**، و**الصفُّ الموقوفُ مقروء** (كانت الشفافيّة تُسقط تباينه).
٦. **لا ضياعَ صامت**: الصفُّ المعدَّل يُوسَم والمغادرةُ تسأل؛ ونقلُ القسم يُسأل ويُقال ما أُلغي.
٧. **السلطةُ الخفيّة تُعرض** في محرّر الحساب (عضويّةٌ من الخانات لا يعرضها الدور الواحد)، بما يزيلها فعلاً.
٨. **الأساس**: لا نصَّ دون 12px في اللوحة، وظلالُها من الرموز، ولا لونَ دافئاً قديماً في system_admin.css،
   وشريطُ حفظ المصفوفة مقروء.
"""
import re

from django.conf import settings
from django.contrib.auth.models import Group, User
from django.core.cache import cache
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from core.models import Department, UserCapabilityOverride, UserProfile
from core.roles import ARCHIVIST_GROUP_NAME, CONTROLLER_GROUP_NAME

ROOT = settings.BASE_DIR


def _read(rel):
    return (ROOT / rel).read_text(encoding='utf-8')


PANEL = 'templates/core/admin_panel.html'


class PanelDialogsTests(SimpleTestCase):

    def test_closed_dialogs_and_drawer_are_inert_in_the_markup(self):
        src = _read(PANEL)
        for mid in ('depModal', 'depEditModal', 'userModal'):
            with self.subTest(dialog=mid):
                self.assertRegex(src, r'<div class="modal-bd" id="%s"[^>]* inert[ >]' % mid)
        self.assertIn('<aside class="drawer" id="drawer" aria-label="تفاصيل" inert>', src)

    def test_opening_wakes_the_dialog_before_focusing_and_closing_puts_it_back_to_sleep(self):
        src = _read(PANEL)
        opener = src[src.index('function openModal(id){'):src.index('function closeModal(id)')]
        self.assertLess(opener.index('m.inert=false'), opener.index('.focus()'))
        self.assertIn("m.classList.remove('open');m.inert=true;", src)
        closer = src[src.index('function closeAll(){'):]
        closer = closer[:closer.index('\n}') + 2]
        self.assertIn("MODALS.some(m=>m.classList.contains('open'))", closer)
        self.assertIn('m.inert=true', closer)
        self.assertIn('drawer.inert=true', closer)
        self.assertIn("drawer.inert=false;drawer.classList.add('open')", src)

    def test_focus_is_trapped_in_the_open_dialog(self):
        src = _read(PANEL)
        trap = src[src.index("if(e.key!=='Tab')return;"):]
        trap = trap[:trap.index('});')]
        for needle in ("MODALS.find(m=>m.classList.contains('open'))", 'box.contains(cur)', 'last.focus()', 'first.focus()'):
            self.assertIn(needle, trap)

    def test_back_returns_to_the_previous_tab(self):
        src = _read(PANEL)
        self.assertNotIn('history.replaceState', src)
        self.assertIn("history.pushState(null,'','?tab='+TAB_OF[v])", src)
        self.assertIn("addEventListener('popstate'", src)
        # «نظرة عامّة» بلا ?tab ليست تبويباً جديداً، والعودةُ إلى عرضٍ لم يُحمَّل GET لا إعادةُ إرسال (فيبل 11-16)
        self.assertIn("(new URLSearchParams(location.search).get('tab')||'overview')!==TAB_OF[v]", src)
        self.assertIn('location.replace(location.href)', src)
        self.assertNotIn('location.reload()', src)

    def test_messages_are_announced(self):
        self.assertIn('''role="{% if 'error' in message.tags %}alert{% else %}status{% endif %}"''', _read(PANEL))

    def test_every_dialog_field_has_a_paired_label(self):
        src = _read(PANEL)
        for fid in ('depEditName', 'depEditCode', 'um-department', 'um-username', 'um-first', 'um-last',
                    'um-title', 'um-email', 'um-role'):
            with self.subTest(field=fid):
                self.assertIn('<label for="%s">' % fid, src)
                self.assertRegex(src, r'<(input|select)[^>]* id="%s"' % fid)

    def test_a_role_box_is_a_32px_target(self):
        src = _read(PANEL)
        self.assertIn('<label class="role-hit" title="{{ cell.title }}"><input type="checkbox"', src)
        self.assertIn('.role-hit{display:inline-grid;place-items:center;min-width:32px;min-height:32px;', src)
        # زرُّ ✕ في الحوارات كان 26×23
        self.assertIn('display:inline-grid;place-items:center;min-width:32px;min-height:32px;\n'
                      '  padding:.2rem .4rem;border-radius:8px;font-size:1.1rem;', src)

    def test_an_inactive_row_keeps_its_contrast(self):
        src = _read(PANEL)
        self.assertNotIn('opacity:.55', src)
        self.assertIn('class="is-inactive"', src)
        self.assertIn('tr.is-inactive td,.dtree-row.is-inactive{background:var(--lx-surface-2);color:var(--mute)}', src)


class PanelLogicGuardsTests(SimpleTestCase):

    def test_an_unsaved_row_is_marked_and_leaving_asks(self):
        src = _read(PANEL)
        self.assertIn('<span class="dirty-chip" hidden>غير محفوظ</span>', src)
        guard = src[src.index('const dirtyRows=new Set()'):]
        guard = guard[:guard.index('/* ── نقلُ موظّفٍ')]
        self.assertIn("addEventListener('beforeunload'", guard)
        self.assertIn('id!==submittingId', guard)
        self.assertIn("tr.classList.toggle('is-dirty',dirty)", guard)
        self.assertIn('dirtyRows.delete(f.id)', guard)   # أُعيدت القيمُ ⟵ لا سؤالَ بلا داع
        # الحقولُ وحدها: زرُّ الحفظ المربوط بالنموذج كان يجعل الصفَّ «معدَّلاً» إلى الأبد (قِيس في المتصفّح)
        self.assertIn(':is(input,select,textarea)[form="${f.id}"]', guard)
        self.assertIn('submittingId=null;', guard)

    def test_moving_a_person_or_a_unit_asks_first(self):
        src = _read(PANEL)
        self.assertIn('يُلغي استثناءاتِ حسابه الخاصّة', src)
        self.assertRegex(src, r'sel\.value!==was&&!confirm\(')
        self.assertIn('يغيّر مَن يرى كتبَه ومَن يديره', src)
        self.assertIn("$('#depEditForm')?.addEventListener('submit'", src)

    def test_no_text_under_twelve_pixels_in_the_panel(self):
        style = _read(PANEL)
        style = style[style.index('<style>'):style.index('</style>')]
        sizes = [float(x) for x in re.findall(r'font-size:\s*(\.\d+|0\.\d+)rem', style)]
        self.assertFalse([x for x in sizes if x < .7], sizes)
        self.assertNotIn('font-size:.65rem', _read(PANEL))

    def test_a_dialog_field_stays_in_its_cell(self):
        # قائمةُ «القسم» كانت تتّسع لأطول اسمٍ فتغطّي «اسم المستخدم» (لقطةُ الرفض 11-16)
        src = _read(PANEL)
        self.assertIn('.f-group{display:grid;gap:.25rem;min-width:0}', src)
        self.assertIn('border-radius:10px;background:#fff;font-size:.85rem;width:100%;min-width:0}', src)

    def test_panel_shadows_come_from_the_tokens(self):
        style = _read(PANEL)
        style = style[style.index('<style>'):style.index('</style>')]
        self.assertNotRegex(style, r'box-shadow:0 \d+px \d+px -\d+px color-mix')
        self.assertNotIn('rgba(0,0,0,.35)', style)


class FoundationTests(SimpleTestCase):

    def test_the_system_admin_sheet_has_no_old_warm_literals(self):
        css = _read('static/css/system_admin.css')
        for warm in ('#fffaf3', '#2b170d', '#22130b', '#faf8f5', '#fef6f6', '#eef2f7', '#b91c1c', '#dc2626', '#d97706'):
            with self.subTest(colour=warm):
                self.assertNotIn(warm, css)

    def test_the_role_matrix_save_bar_reads(self):
        css = _read('static/css/system_admin.css')
        bar = css[css.index('.rm-bar {'):]
        bar = bar[:bar.index('}')]
        self.assertIn('background: var(--lx-hero-b)', bar)
        self.assertIn('color: rgba(255, 255, 255, .92)', bar)


class HiddenAuthorityTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.dept = Department.objects.create(name='قسم الحرّاس', code='حر1')
        cls.dept2 = Department.objects.create(name='قسم النقل', code='حر2')
        cls.root = User.objects.create_superuser('a11y_root', password='pw-a11y-1111')

    def setUp(self):
        cache.clear()
        self.client.force_login(self.root)

    def _person(self, name, *groups):
        user = User.objects.create_user(name, password='pw-a11y-1111')
        UserProfile.objects.update_or_create(user=user, defaults={'department': self.dept})
        for g in groups:
            user.groups.add(Group.objects.get_or_create(name=g)[0])
        return user

    def test_the_editor_names_a_membership_the_single_role_hides(self):
        two = self._person('a11y_two', CONTROLLER_GROUP_NAME, ARCHIVIST_GROUP_NAME)
        html = self.client.get(reverse('system_account', args=[two.pk])).content.decode('utf-8')
        self.assertIn('class="ae-extra"', html)
        self.assertIn('«%s»' % ARCHIVIST_GROUP_NAME, html)
        self.assertIn('تغييرُ دوره هنا يضبط عضويّاتِه على الدور الجديد', html)
        self.assertIn('أزِل خانتَها في جدول الحسابات', html)
        self.assertNotIn('حفظُ دورٍ هنا يزيلها', html)   # كان خطأً: حفظُ الدور نفسِه لا يغيّر شيئاً (فيبل 11-16)

    def test_a_single_role_shows_no_warning(self):
        one = self._person('a11y_one', CONTROLLER_GROUP_NAME)
        html = self.client.get(reverse('system_account', args=[one.pk])).content.decode('utf-8')
        self.assertNotIn('class="ae-extra"', html)

    def test_saving_a_move_in_the_panel_says_what_was_cancelled(self):
        person = self._person('a11y_move')
        UserCapabilityOverride.objects.create(user=person, capability='book.enter', allowed=True, changed_by=self.root)
        resp = self.client.post(reverse('admin_panel'), {'action': 'assign_user', 'tab': 'users', 'user_id': person.pk,
                                                         'department': self.dept2.pk, 'job_title': ''}, follow=True)
        self.assertContains(resp, 'وأُلغيت استثناءاتُه (1)')
        self.assertFalse(UserCapabilityOverride.objects.filter(user=person).exists())

    def test_a_rejected_new_account_explains_itself_inside_the_dialog(self):
        """الحوارُ يحبس التركيز — فالسببُ داخله لا في شريط الصفحة (فيبل 11-16)."""
        resp = self.client.post(reverse('admin_panel'), {'action': 'create_department_user', 'tab': 'users',
                                                         'username': 'a11y_nodept', 'role': 'viewer'})
        html = resp.content.decode('utf-8')
        self.assertIn('aria-describedby="umError"', html)
        self.assertRegex(html, r'<div class="sys-msg error" role="alert" id="umError">[^<]*<i[^>]*></i> اختر قسمَ الحساب الجديد')
        self.assertEqual(html.count('اختر قسمَ الحساب الجديد'), 1)   # لا شريطَ ثانٍ خارج الحوار
        self.assertIn('value="a11y_nodept"', html)

    def test_saving_without_a_move_says_nothing_extra(self):
        person = self._person('a11y_stay')
        UserCapabilityOverride.objects.create(user=person, capability='book.enter', allowed=True, changed_by=self.root)
        resp = self.client.post(reverse('admin_panel'), {'action': 'assign_user', 'tab': 'users', 'user_id': person.pk,
                                                         'department': self.dept.pk, 'job_title': 'باقٍ'}, follow=True)
        self.assertContains(resp, 'حُدِّث حساب «a11y_stay».')
        self.assertNotContains(resp, 'أُلغيت استثناءاتُه')
