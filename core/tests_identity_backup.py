"""حرّاسُ صفحة النسخ الاحتياطي على الهويّة الموحّدة (v2، 2026-11-19).

١. **الصفحةُ منقولة** (‎data-lx-page="v2"‎) بورقتها ‎css/backup.css‎، ولا تعتمد على ‎system_admin.css‎ (ورقةُ وحدة
   «النظام» التي تتغيّر معها): لا صنفَ ‎sa-*‎ في القالب ولا رابطَ لتلك الورقة.
٢. **ورقتُها رموزٌ وحدها**: لا لونَ صريحاً، ولا ‎[data-theme="dark"]‎ الميّت، ولا قاعدةً لكلّ وضع — الرموزُ تتبدّل.
٣. **لا ‎confirm()‎/‎alert()‎ أصليّ** ولا معالجَ حدثٍ مضمَّن ولا لونَ مضمَّن في القالب.
٤. **حالةُ النسخ بكلمةٍ وأيقونة** لا باللون وحده — في الحالات الثلاث (سليمة · متأخّرة · غير مراقَبة).
٥. **التاريخُ أوّلاً في كلّ ملفّ**، والأرقامُ والتواريخُ وأسماءُ الملفّات معزولة، والأحدثُ موسومٌ وحده (كانت الأسماءُ
   تتكسّر في عمود الجدول ثلاثَ قطعٍ على الهاتف).
٦. **المجلّدُ الفارغ يقول ما العمل**.
٧. **الحقولُ للّمس**: 16px (لا تكبيرَ على الهاتف) و44px، وحدُّها مزيجُ رموزٍ يقيس ≥3:1 (‎--lx-line-strong‎ يقيس 1.4:1).
٨. **الفعلُ الأساسيّ مملوءٌ بالتعبئة وحبرها**، وإطارُ التركيز صريحٌ على الزرّين (Bootstrap يمحوه).
٩. **عقدُ النموذجين كما كان**: الطريقةُ ووجهةُ الإرسال والأسماء — ومربّعُ التفعيل وتسميتُه هدفٌ واحد.
"""
import re
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from core.tests_list_identity import DECL, _read, _strip

TEMPLATE = 'templates/core/backup.html'
SHEET = 'static/css/backup.css'


def _rule(css, head):
    block = css[css.index(head + ' {'):]
    return block[:block.index('}')]


def _backups(n):
    """ملفّاتٌ وهميّة الأحدثُ أوّلاً — كما تعيدها ‎list_db_backups‎."""
    return [{'name': f'pg_backup_202611{19 - i:02d}_0900.dump.enc', 'size_mb': 6.5,
             'modified': datetime(2026, 11, 19 - i, 9, 0)} for i in range(n)]


class BackupSourceTests(SimpleTestCase):

    def test_the_page_is_migrated_with_its_own_sheet(self):
        src = _read(TEMPLATE)
        self.assertIn('{% block html_attrs %} data-lx-page="v2"{% endblock %}', src)
        self.assertIn("{% static 'css/backup.css' %}?v=20261119-pages", src)

    def test_the_page_does_not_lean_on_the_system_sheet(self):
        src = _read(TEMPLATE)
        # الرابطُ لا الاسم: تعليقُ القالب يذكر الورقةَ ليشرح لماذا لا تُربط
        self.assertNotIn('css/system_admin.css', src)
        self.assertEqual(re.findall(r'class="[^"]*(?<![\w-])sa-[\w-]+', src), [])

    def test_the_sheet_speaks_tokens(self):
        css = _strip(_read(SHEET))
        values = ' '.join(m.group(2) for m in DECL.finditer(css))
        self.assertLessEqual({h.lower() for h in re.findall(r'#[0-9a-fA-F]{3,8}\b', values)}, {'#fff'})
        self.assertNotRegex(values, r'\b(?:rgba?|hsla?)\(|\b(?:white|black)\b')
        for dead in ('data-theme', 'data-bs-theme', 'prefers-color-scheme'):
            with self.subTest(selector=dead):
                self.assertNotIn(dead, css)

    def test_no_native_dialog_inline_handler_or_inline_colour(self):
        src = _read(TEMPLATE)
        self.assertNotRegex(src, r'(?<![\w.])(?:confirm|alert)\(|window\.(?:confirm|alert)')
        self.assertNotRegex(src, r'\son[a-z]+=')
        self.assertNotIn('style="', src)

    def test_fields_are_sized_for_touch_and_bounded_at_three_to_one(self):
        css = _read(SHEET)
        rule = _rule(css, '.bk-control:is(.form-control, .form-select)')
        for decl in ('min-height: 2.75rem;', 'font-size: 1rem;', 'border-color: var(--bk-field-line);'):
            with self.subTest(decl=decl):
                self.assertIn(decl, rule)
        self.assertIn('--bk-field-line: color-mix(in srgb, var(--lx-mute) 75%, var(--lx-surface));', css)
        self.assertIn('.bk-page .bk-check .form-check-input { border-color: var(--bk-field-line); }', css)

    def test_the_primary_action_is_filled_with_its_ink_and_focus_is_drawn(self):
        css = _read(SHEET)
        self.assertIn('.bk-page .btn.bk-btn-fill { background: var(--lx-pri-fill);', css)
        ink = css[css.index('.bk-page .btn.bk-btn-fill,'):]
        self.assertIn('{ color: var(--lx-pri-fill-ink); }', ink[:ink.index('}') + 1])
        self.assertIn('.bk-page .btn.bk-btn:focus-visible { outline: 2px solid var(--lx-pri);', css)


@patch('core.views.dashboard.default_backup_dir', return_value=Path('X:/bk-guard-not-touched'))
class BackupPageTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.admin = get_user_model().objects.create_user(
            username='bk_guard', password='pw-bk-guard-1234', is_staff=True, is_superuser=True)

    def setUp(self):
        self.client.force_login(self.admin)

    def page(self, backups=(), state='ok', note='آخر نسخة قبل ساعتين · الحدّ 26 ساعة'):
        job = {'key': 'backup', 'name': 'النسخ الاحتياطيّ', 'state': state, 'note': note, 'age': 2, 'next_step': ''}
        with patch('core.views.dashboard.list_db_backups', return_value=list(backups)), \
                patch('core.system_ops.job_statuses', return_value=[job]):
            response = self.client.get(reverse('backup_database'))
        self.assertEqual(response.status_code, 200)
        return response.content.decode('utf-8')

    def test_the_rendered_page_opts_in(self, _dir):
        html = self.page()
        self.assertIn('<html lang="ar" dir="rtl" data-lx-page="v2">', html)
        self.assertIn('css/backup.css?v=', html)   # الرقمُ نفسُه حارسُ المصدر
        self.assertIn('<code class="bk-db bk-mono" dir="ltr" translate="no">', html)

    def test_the_status_speaks_in_words_and_icons(self, _dir):
        for state, tone, icon, words in (('ok', 'is-ok', 'bi-shield-check', 'النسخ سليمة'),
                                         ('stale', 'is-bad', 'bi-shield-exclamation', 'النسخ متأخّرة'),
                                         ('unknown', 'is-warn', 'bi-shield-slash', 'النسخ غير مراقَبة')):
            with self.subTest(state=state):
                html = self.page(state=state, note=f'ملاحظة-{state}')
                band = re.search(r'<section class="bk-status ([\w-]+)" aria-labelledby="bkStatus">(.*?)</section>', html, re.S)
                self.assertIsNotNone(band)
                self.assertEqual(band.group(1), tone)
                self.assertIn(f'<i class="bi {icon}"></i>', band.group(2))
                self.assertIn(f'<h2 id="bkStatus">{words}</h2>', band.group(2))
                self.assertIn(f'<p>ملاحظة-{state}</p>', band.group(2))

    def test_each_file_leads_with_its_date_and_isolates_numbers_and_names(self, _dir):
        html = self.page(backups=_backups(14))
        files = html.split('<ol class="bk-files">', 1)[1].split('</ol>', 1)[0]
        rows = re.findall(r'<li class="bk-file[^"]*">(.*?)</li>', files, re.S)
        self.assertEqual(len(rows), 12)
        first = rows[0]
        when = '<time dir="ltr" datetime="2026-11-19 09:00">19/11/2026 09:00</time>'
        name = '<bdi class="bk-mono" dir="ltr" translate="no">pg_backup_20261119_0900.dump.enc</bdi>'
        self.assertIn(when, first)
        self.assertIn(name, first)
        self.assertLess(first.index(when), first.index(name))
        self.assertRegex(first, r'<span class="bk-file-size"><bdi dir="ltr">[\d.,]+</bdi>&nbsp;م\.ب</span>')
        self.assertEqual(files.count('class="bk-file is-newest"'), 1)
        self.assertEqual(files.count('<span class="bk-tag">الأحدث</span>'), 1)
        self.assertIn('الأحدث', first)
        self.assertIn('<span class="bk-count">14</span>', html)
        self.assertIn('<p class="bk-more">وأقدم منها 2 في المجلّد نفسه.</p>', html)

    def test_an_empty_folder_says_what_to_do(self, _dir):
        html = self.page(backups=[])
        self.assertIn('<p class="bk-empty">', html)
        self.assertIn('أنشئ أوّل نسخة من «نسخة يدويّة الآن».', html)
        self.assertNotIn('<ol class="bk-files">', html)
        self.assertNotIn('class="bk-count"', html)

    def test_the_two_forms_keep_their_contract(self, _dir):
        html = self.page()
        schedule = re.search(r'<form method="post" action="([^"]+)" class="bk-form">(.*?)</form>', html, re.S)
        now = re.search(r'<form method="post" class="bk-form">(.*?)</form>', html, re.S)
        self.assertEqual(schedule.group(1), reverse('settings_backup_save'))
        for name in ('enabled', 'frequency', 'hour', 'retention_days'):
            with self.subTest(form='schedule', name=name):
                self.assertRegex(schedule.group(2), r'<(?:input|select)\b[^>]*\bname="%s"' % name)
        for name in ('target_directory', 'file_name'):
            with self.subTest(form='now', name=name):
                self.assertRegex(now.group(1), r'<input\b[^>]*\bname="%s"' % name)
        # المربّعُ داخل تسميته: هدفٌ واحدٌ بلا منطقةٍ ميّتة بينهما
        self.assertIn('<label class="bk-check" for="bkEnabled"><input type="checkbox" class="form-check-input" '
                      'id="bkEnabled" name="enabled"', schedule.group(2))
        # الاستعادةُ (روابطُ قصيرة) قبل قائمة الملفّات الطويلة — على الهاتف لا تُدفن تحت اثني عشر سطراً
        self.assertLess(html.index('id="bkRestore"'), html.index('id="bkList"'))
        self.assertIn(f'<a class="bk-link" href="{reverse("data_restore")}">', html)
