# -*- coding: utf-8 -*-
"""تدقيقُ 2026-10-08، مجموعةُ «ملفّ الكتاب» وما خرج منها إلى التطبيق كلّه.

١. **حواريّةُ التأكيد الواحدة**: اثنا عشر `onsubmit/onclick="return confirm(…)"` في
   القوالب صارت `data-confirm` تلتقطه `app.js` بحواريّة التطبيق. وأحدُها كان ثغرة:
   `confirm('حذف القالب «{{ tpl.name }}»؟')` — تهريبُ HTML لا يحمي سلسلةَ JS داخل صفة
   حدث، فالمتصفّحُ يفكّ `&#x27;` قبل التحليل واسمُ القالب يُنفَّذ.
٢. **حواريّتا التفريق والعهدة** كانتا تبقيان «جارٍ التحميل…» إلى الأبد إن سقط طلبُ
   الأهداف، وكان اسمُ القسم يُبنى بـinnerHTML.
٣. **قوالبُ ميّتة**: لا قالبَ في templates/ بلا مرجعٍ خارج الاختبارات.
"""
import re
from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

ROOT = Path(__file__).resolve().parent.parent
User = get_user_model()


class NoInlineNativeConfirmTests(SimpleTestCase):
    """التأكيدُ في القوالب صفةٌ (`data-confirm`) لا سكربتٌ مضمَّن."""

    def test_no_template_carries_an_inline_confirm(self):
        offenders = []
        for path in (ROOT / 'templates').rglob('*.html'):
            text = path.read_text(encoding='utf-8')
            for m in re.finditer(r'on(?:submit|click)="[^"]*\bconfirm\(', text):
                line = text.count('\n', 0, m.start()) + 1
                offenders.append('%s:%d' % (path.relative_to(ROOT).as_posix(), line))
        self.assertEqual(offenders, [])

    def test_signature_forms_ask_through_the_dialog(self):
        src = (ROOT / 'templates' / 'core' / 'book_detail.html').read_text(encoding='utf-8')
        sign = src[src.index("{% url 'sign_attachment'"):]
        sign = sign[:sign.index('</form>')]
        self.assertIn('data-confirm="توقيعُ المستند', sign)
        # التوقيعُ ليس هدماً: زرُّه أساسيٌّ لا أحمر
        self.assertIn('data-confirm-tone="safe"', sign)
        revoke = src[src.index("{% url 'revoke_signature'"):]
        revoke = revoke[:revoke.index('</form>')]
        self.assertIn('data-confirm="إبطالُ التوقيع', revoke)
        self.assertNotIn('data-confirm-tone="safe"', revoke)


class ConfirmDialogScriptTests(SimpleTestCase):
    """`app.js`: الحواريّةُ تكتب نصّاً، وكلُّ إغلاقٍ إلغاء، والإرسالُ يُستأنف بزرّه."""

    def src(self):
        return (ROOT / 'static' / 'app.js').read_text(encoding='utf-8')

    def test_dialog_writes_text_not_html(self):
        src = self.src()
        builder = src[src.index('function createConfirmModal'):]
        builder = builder[:builder.index('\n}\n') if '\n}\n' in builder else len(builder)]
        self.assertIn(".modal-body').textContent = opts.message", builder)
        self.assertNotIn('${message}', builder)
        self.assertNotIn('${opts', builder)

    def test_any_dismissal_resolves_as_cancel(self):
        src = self.src()
        fn = src[src.index('function confirmDelete'):src.index('function createConfirmModal')]
        self.assertRegex(fn, r"hidden\.bs\.modal', \(\) => \{ modal\.remove\(\); resolve\(answer\); \}")

    def test_declarative_hook_intercepts_in_capture_and_keeps_the_submitter(self):
        src = self.src()
        hook = src[src.index("document.addEventListener('submit', function (e) {"):]
        hook = hook[:hook.index('}, true);')]
        self.assertIn('e.stopPropagation();', hook)
        self.assertIn('form.requestSubmit(submitter)', hook)
        self.assertIn("form.dataset.confirmed === '1'", hook)


class LifecycleTargetsFailureTests(SimpleTestCase):
    SRC = ROOT / 'static' / 'js' / 'book_lifecycle.js'

    def test_failed_targets_are_not_cached_and_are_reported(self):
        src = self.SRC.read_text(encoding='utf-8')
        fn = src[src.index('function targets()'):]
        fn = fn[:fn.index('\n  }\n')]
        self.assertIn('throw new Error(TARGETS_FAILED)', fn)
        # الخزنُ بعد التحقّق فقط — وإلّا خُزّن ردُّ خطأٍ فلا تُعاد المحاولة
        self.assertLess(fn.index('throw new Error(TARGETS_FAILED)'), fn.index('targetsCache = data'))
        for modal in ("getElementById('distributeModal')", "getElementById('custodyModal')"):
            with self.subTest(modal=modal):
                block = src[src.index(modal):]
                block = block[block.index("addEventListener('show.bs.modal'"):]
                block = block[:block.index('\n    });\n')]      # معالجُ الفتح وحدَه
                self.assertIn('.catch(function (err)', block)

    def test_department_names_are_text(self):
        src = self.SRC.read_text(encoding='utf-8')
        self.assertIn('label.textContent = d.name;', src)
        self.assertNotRegex(src, r"innerHTML\s*=[^;]*d\.name")


class TemplateNamesAreEscapedTests(TestCase):
    """الاسمُ الذي يكتبه المستخدم يصل صفةَ `data-confirm` مهرَّباً — لا سكربتاً."""

    EVIL = "x');alert(1);('\""

    @classmethod
    def setUpTestData(cls):
        cls.boss = User.objects.create_superuser('boss1008', 'b@x.com', 'pw-boss-1008')

    def setUp(self):
        self.client.force_login(self.boss)

    def test_mail_template_delete_confirm(self):
        from core.models import EmailTemplate

        EmailTemplate.objects.create(name=self.EVIL, slug='evil-1008',
                                     subject_template='s', body_html='b')
        html = self.client.get(reverse('mail_templates')).content.decode('utf-8')
        self.assertIn('data-confirm="حذف القالب «x&#x27;);alert(1);(&#x27;&quot;»؟"', html)
        self.assertNotIn("onsubmit=\"return confirm('حذف القالب", html)

    def test_entity_disable_confirm(self):
        from core.models import Entity

        Entity.objects.create(name='جهة ' + self.EVIL)
        html = self.client.get(reverse('entity_list')).content.decode('utf-8')
        self.assertIn('data-confirm="تعطيل جهة جهة x&#x27;);alert(1);(&#x27;&quot;؟', html)
        # escapejs في صفة HTML كان يُظهر ' حرفيّاً في نصّ السؤال
        self.assertNotIn('\\u0027', html)


class NoDeadTemplatesTests(SimpleTestCase):
    """كلُّ قالبٍ له مرجعٌ خارج الاختبارات — `book_audit` بقي شهراً بعد حذف مساره.

    403/404/500 يحمّلها Django بالاسم ضمناً.
    """

    IMPLICIT = {'403.html', '404.html', '500.html'}

    def test_every_template_is_referenced(self):
        sources = []
        for pattern in ('core/**/*.py', 'lettersys/**/*.py', 'templates/**/*.html', 'static/**/*.js'):
            for path in ROOT.glob(pattern):
                if path.name.startswith('tests'):
                    continue
                sources.append((path, path.read_text(encoding='utf-8', errors='ignore')))
        dead = []
        for tpl in (ROOT / 'templates').rglob('*.html'):
            rel = tpl.relative_to(ROOT / 'templates').as_posix()
            if rel in self.IMPLICIT:
                continue
            if not any(rel in text for path, text in sources if path != tpl):
                dead.append(rel)
        self.assertEqual(dead, [])
