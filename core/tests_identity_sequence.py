"""حرّاسُ «العدّادات التسلسلية» على الهويّة الموحّدة (2026-11-19، دفعةُ الصفحات).

١. **الصفحةُ منقولة** (v2) في الإطار وفي التضمين داخل مركز الإعدادات، وورقتُها على الرموز وحدها،
   والقالبُ بلا نمطٍ مضمَّن ولا حوارٍ أصليّ.
٢. **الأرقامُ قلبُ الصفحة**: كلُّ رقمٍ معزولٌ يسارَ‑يمين، و«الرقمُ كما سيُختم» من core/numbering.py
   (يمرّره الـview) لا من القالب — والرقمُ الخامُ قيمةُ الحقل وحدَها. وفتحُ الصفحة لا يمسّ عدّاداً.
٣. **ترتيبُ صفحة الإدخال** (أزرارُ الأنواع هناك تقود إلى هنا): الوارد ثمّ الصادر، والداخليّ قبل الخارجيّ.
٤. **ما أُصلح لا يعود**: وعدُ «البادئة» الملغاة، والرموزُ التعبيريّة أيقوناتٍ، و«إلغاء» بتباين 4.27:1.
٥. **عقدُ النموذج كما كان** (الأسماء والهدف)، وعلامةُ «تغيّر ولم يُحفظ» تقرأ النموذجَ ولا تمسّه.
"""
import re
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from django.utils.html import escape

from core.models import BookSequence, Department

ROOT = Path(settings.BASE_DIR)
TEMPLATE = 'templates/core/sequence_settings.html'
SHEET = 'static/css/sequence.css'
COMMENT = re.compile(r'/\*.*?\*/', re.S)
DECL = re.compile(r'([\w-]+)\s*:\s*([^;{}]+)')
#: ترتيبُ أزرار الأنواع في صفحة الإدخال
KINDS = ('incoming_internal', 'incoming_external', 'outgoing_internal', 'outgoing_external')


def _read(rel):
    return (ROOT / rel).read_text(encoding='utf-8')


def _page(html):
    """محتوى الصفحة وحدَه — لا القشرةُ المشتركة حولها."""
    start = html.index('<div class="sq">')
    return html[start:html.index('</form>', start)]


class SequenceSourceTests(SimpleTestCase):

    def test_the_sheet_speaks_tokens_only(self):
        """لا لونَ صريحاً إلّا الأبيضَ حبراً فوق تركواز القيادة، ولا صفةَ الوضع القديم الميّتة."""
        css = COMMENT.sub('', _read(SHEET))
        values = ' '.join(m.group(2) for m in DECL.finditer(css))
        hexes = {h.lower() for h in re.findall(r'#[0-9a-fA-F]{3,8}\b', values)}
        self.assertLessEqual(hexes, {'#fff'}, 'لونٌ صريحٌ في sequence.css')
        self.assertNotRegex(values, r'\b(?:rgba?|hsla?)\(|\b(?:white|black)\b', 'لونٌ صريحٌ بالاسم أو الدالّة')
        self.assertNotIn('[data-theme', css, 'صفةُ الوضع القديم الميّتة — الداكنُ [data-bs-theme] والرموزُ تتبدّل وحدها')

    def test_the_template_carries_no_inline_style(self):
        self.assertNotIn('style="', _read(TEMPLATE), 'نمطٌ مضمَّن في القالب — مكانُه sequence.css على الرموز')

    def test_no_native_dialog(self):
        self.assertNotRegex(_read(TEMPLATE), r'(?<![\w$])(?:window\.)?(?:confirm|alert)\s*\(',
                            'confirm()/alert() أصليّ — الحوارُ data-confirm / confirmDelete')

    def test_the_stamp_number_comes_from_numbering_not_the_template(self):
        src = _read(TEMPLATE)
        self.assertIn('<bdi dir="ltr" class="sq-stamp-n">{{ seq.formatted }}</bdi>', src)
        # الرقمُ الخامُ قيمةُ الحقل وحدَها — لا يُعرض نصّاً يُنسَّق في القالب
        self.assertEqual(re.findall(r'\{\{\s*seq\.obj\.next_number\s*\}\}', src), ['{{ seq.obj.next_number }}'],
                         'الرقمُ الخامُ يُعرض نصّاً — العرضُ من seq.formatted (core/numbering.py)')
        self.assertIn('value="{{ seq.obj.next_number }}"', src)

    def test_the_secondary_button_reads_in_both_themes(self):
        """«إلغاء» كان رماديَّ Bootstrap ‎#6c757d‎ بتباين 4.27:1 على أرضيّة الفاتح (مقيسٌ قبل النقل)."""
        # المصدرُ الواحد في الملفّ المشترك (حارسُه tests_identity_pages_batch) — النسخةُ المحلّيّة لا تعود
        self.assertNotIn('.btn-outline-secondary', _read(SHEET))

    def test_the_unsaved_mark_only_reads_the_form(self):
        script = _read(TEMPLATE).split('{% block extra_js %}', 1)[1]
        self.assertIn('defaultValue', script)
        for verb in ('preventDefault', '.submit(', 'requestSubmit', '.value =', 'fetch(', 'XMLHttpRequest'):
            self.assertNotIn(verb, script, f'علامةُ «تغيّر» تمسّ النموذج: {verb}')


class SequencePageTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.admin = get_user_model().objects.create_superuser('sqid', 'sqid@example.com', 'pw-sqid-1111111')
        cls.ledger = BookSequence.resolve_department() or Department.objects.create(
            name='دفترُ الحرّاس', code='ح.س', holds_register=True)
        for kind, number in zip(KINDS, (3918, 605, 715, 34)):
            BookSequence.objects.update_or_create(kind=kind, department=cls.ledger,
                                                  defaults={'next_number': number})

    def setUp(self):
        self.client.force_login(self.admin)

    def get(self, query=''):
        resp = self.client.get(reverse('sequence_settings') + query)
        self.assertEqual(resp.status_code, 200)
        return resp

    def test_the_page_is_migrated_framed_and_embedded(self):
        for query in ('', '?embed=1'):
            with self.subTest(query=query):
                html = self.get(query).content.decode('utf-8')
                self.assertIn('data-lx-page="v2"', html, 'الصفحةُ لم تعلن v2 — لا داكنَ ولا رموز')
                self.assertIn('css/sequence.css?v=20261119-pages', html)

    def test_every_number_is_isolated_and_formatted_by_numbering(self):
        resp = self.get()
        html = resp.content.decode('utf-8')
        for seq in resp.context['sequences']:
            with self.subTest(kind=seq['kind']):
                self.assertEqual(seq['formatted'], BookSequence.format_number(seq['kind'], seq['obj'].next_number))
                self.assertIn('<bdi dir="ltr" class="sq-stamp-n">%s</bdi>' % seq['formatted'], html,
                              'رقمُ الختم غيرُ معزولٍ يسارَ‑يمين')
        inputs = re.findall(r'<input\b[^>]*type="number"[^>]*>', html)
        self.assertEqual(len(inputs), 5)
        for tag in inputs:
            self.assertIn('dir="ltr"', tag)
        self.assertEqual(len(re.findall(r'<bdi dir="ltr" class="sq-num">\d+</bdi>', html)), 4)

    def test_opening_the_page_never_moves_a_counter(self):
        before = dict(BookSequence.objects.values_list('pk', 'next_number'))
        self.get()
        self.get('?embed=1')
        self.assertEqual(dict(BookSequence.objects.values_list('pk', 'next_number')), before,
                         'فتحُ الصفحة غيّر عدّاداً — العرضُ قراءةٌ وحدها')

    def test_the_counters_follow_the_entry_pages_order(self):
        html = self.get().content.decode('utf-8')
        spots = [html.index('id="next_%s"' % kind) for kind in KINDS]
        self.assertEqual(spots, sorted(spots), 'الترتيبُ ليس ترتيبَ أزرار الأنواع في صفحة الإدخال')
        self.assertEqual(re.findall(r'class="sq-counter" data-dir="(in|out)"', html), ['in', 'in', 'out', 'out'])

    def test_the_ledger_of_the_shown_counters_is_named(self):
        html = self.get().content.decode('utf-8')
        self.assertIn('دفتر %s' % escape(self.ledger.name), html, 'الصفحةُ لا تقول دفترَ أيّ قسمٍ تعرض')

    def test_the_fixed_copy_stays_fixed(self):
        page = _page(self.get().content.decode('utf-8'))
        self.assertNotIn('البادئة', page, 'الصفحةُ تَعِد بالبادئة الملغاة (core/numbering.py)')
        for emoji in ('⚙', '🌐', '🔒', '📡', '🛡'):
            self.assertNotIn(emoji, page, 'رمزٌ تعبيريّ في مكان أيقونة')
        self.assertIn('بعد آخر رقمٍ صدر', page, 'قاعدةُ الخادم لا تُقال قبل الكتابة')

    def test_the_form_contract_is_unchanged(self):
        page = _page(self.get().content.decode('utf-8'))
        form = re.search(r'<form method="post"([^>]*)>', page)
        self.assertIsNotNone(form)
        self.assertNotIn('action=', form.group(1), 'النموذجُ يُرسَل إلى صفحته كما كان')
        names = sorted(re.findall(r'\bname="([^"]+)"', page))
        self.assertEqual(names, sorted(['csrfmiddlewaretoken', 'reservation_expire_minutes']
                                       + ['next_number_%s' % kind for kind in KINDS]))
