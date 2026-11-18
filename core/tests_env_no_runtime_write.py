# -*- coding: utf-8 -*-
"""الحارسُ: **لا مُعالِجَ طلبٍ يكتب في ملفّ البيئة.**

قرارُ المالك (2026-09-24): الموضعان اللذان كانا يكتبان في ``.env`` من مسار
الطلب يُصلَحان **في الكود** لا بتوسيع صلاحيّات الملفّ — فيصير
``.env`` = ``lettersys_svc:R`` خصيصةَ تصميمٍ لا مجازفة.

حارسان: بصمةُ الملفّ قبل/بعد طلبٍ حقيقيّ، وحارسٌ ثابتٌ على المصدر يمنع عودةَ
النمطِ بالنسخ واللصق.
"""
import ast
import base64
import builtins
import hashlib
import json
import pathlib
import shutil
import tempfile

from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from .models import SystemSettings

# كلُّ مُعالِجات مسار الإعدادات/الحجز، لا الموضعان المُصلَحان وحدَهما: النمطُ
# يعود بالنسخِ واللصقِ إلى الجار لا إلى الملفّ نفسِه.
_MODULES_THAT_MUST_NOT_WRITE = (
    'core/devices/views.py',
    'core/views/books_sequence.py',
    'core/views/books_api.py',
    'core/views/settings_hub.py',
    'core/reservation_api.py',
    'core/reservation_service.py',
)

# أيُّ نداءِ كتابةِ ملفّ. **بـAST لا بـregex**: أوّلُ نسخةٍ من هذا الحارس
# استعملت ``open\s*\([^)]*['"][wax]`` وفشلت في إمساك الطفرة
# ``open(os.path.join(BASE_DIR, '.env'), 'a')`` لأنّ ``[^)]*`` يتوقّف عند أوّل
# قوسٍ مغلق — حارسٌ لا يُمسك طفرتَه ليس حارساً.
#
# والنسخةُ الثانيةُ (AST) كانت تُمسك ``open`` باسمٍ مجرّدٍ وحدَه، فتمرّ عليها
# ``pathlib.Path(p).open('w')`` و``io.open`` و``codecs.open`` و``os.open``
# و``dotenv.set_key`` (أقربُ ما يُنسَخ لصقاً) و``shutil.copy`` و``os.replace``
# (مصطلحُ الكتابةِ الذرّيّة). الآن: ``open`` اسماً **أو** صفةً، ونداءاتُ
# ``shutil``/``os`` الكاتبةُ بأسمائها المؤهَّلة، و``set_key`` بأيّ شكل.
_READ_MODES = frozenset({'r', 'rb', 'br', 'rt', 'tr', ''})
_WRITE_ATTRS = frozenset({'write_text', 'write_bytes', 'writelines'})
_DOTENV_FUNCS = frozenset({'set_key', 'unset_key'})
_QUALIFIED_WRITES = {
    'shutil': frozenset({'copy', 'copy2', 'copyfile', 'copytree', 'move'}),
    'os': frozenset({'replace', 'rename', 'remove', 'unlink', 'truncate', 'write'}),
}


def _is_write_open(call: ast.Call, *, method: bool):
    """هل هذا النداءُ فتحاً للكتابة؟ الشكُّ يُحسب كتابةً.

    موضعُ الوضع يختلف: ``open(p, 'w')`` و``io.open(p, 'w')`` يضعانه ثانياً،
    أمّا ``Path(p).open('w')`` فيضعه **أوّلاً** — وهذا بالضبط ما أفلت من
    النسخة السابقة. فنفحص أوّلَ وسيطَين ومُسمّى ``mode``، ونَعُدُّ غيابَ أيّ
    ثابتٍ نصّيٍّ كتابةً (أعلامُ ``os.open`` رقميّة).
    """
    nodes = list(call.args[:2])
    explicit_mode = [kw.value for kw in call.keywords if kw.arg == 'mode']
    nodes.extend(explicit_mode)
    if not method and len(call.args) < 2 and not explicit_mode:
        return False             # ``open(p)`` بلا وضعٍ = قراءة
    literals = [n.value for n in nodes
                if isinstance(n, ast.Constant) and isinstance(n.value, str)]
    if not literals:
        return True              # وضعٌ محسوبٌ أو أعلامٌ رقميّة ⟵ احتياطاً
    return any(m not in _READ_MODES for m in literals)


def _root_name(func: ast.AST):
    """الاسمُ الأيسرُ في ``a.b.c`` — ``'a'``؛ أو None."""
    while isinstance(func, ast.Attribute):
        func = func.value
    return func.id if isinstance(func, ast.Name) else None


def find_file_writes(source: str):
    """أسماءُ نداءاتِ كتابةِ الملفّات في هذا المصدر (قائمةٌ فارغةٌ = نظيف)."""
    found = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name):
            name = func.id
        elif isinstance(func, ast.Attribute):
            name = func.attr
        else:
            continue
        if name == 'open':
            if _is_write_open(node, method=isinstance(func, ast.Attribute)):
                found.append(f'open(...) for write @ line {node.lineno}')
        elif name in _WRITE_ATTRS or name in _DOTENV_FUNCS:
            found.append(f'{name}() @ line {node.lineno}')
        elif isinstance(func, ast.Attribute):
            root = _root_name(func)
            if root in _QUALIFIED_WRITES and name in _QUALIFIED_WRITES[root]:
                found.append(f'{root}.{name}() @ line {node.lineno}')
    return found


class _WriteSpy:
    """يرصد كلَّ كتابةِ ملفٍّ فعليّة داخل ``root`` أثناء الطلب.

    الحارسُ الثابت يفحص وحدتَين معلومتَين؛ هذا يفحص **كلَّ** ما يُنفَّذ في سلسلة
    النداء — أيَّ وحدةٍ، وأيَّ شكلِ كتابةٍ، وأيَّ مسار. فلو نُقلت الكتابةُ إلى
    مساعدٍ في وحدةٍ ثالثة لَظهرت هنا.
    """

    def __init__(self, root: pathlib.Path):
        self.root = root.resolve()
        self.writes = []          # أسماءُ الملفّات المكتوبة (بلا تكرار، مرتَّبة)
        self.details = []         # ``how:name`` لرسالة الفشل
        self._patches = []

    def _note(self, target, how):
        try:
            resolved = pathlib.Path(target).resolve()
            resolved.relative_to(self.root)
        except (ValueError, OSError, TypeError):
            return
        # ``write_text`` ينادي ``Path.open`` داخليّاً فيُرصَد مرّتين — الاسمُ هو
        # الحكم، لا عددُ الطبقات.
        self.details.append(f'{how}:{resolved.name}')
        if resolved.name not in self.writes:
            self.writes.append(resolved.name)
            self.writes.sort()

    def __enter__(self):
        spy = self
        real_open, real_wt = builtins.open, pathlib.Path.write_text
        real_wb, real_popen = pathlib.Path.write_bytes, pathlib.Path.open

        def open_(file, mode='r', *a, **k):
            if set(str(mode)) & set('wax+'):
                spy._note(file, 'open')
            return real_open(file, mode, *a, **k)

        def path_open(self_, mode='r', *a, **k):
            if set(str(mode)) & set('wax+'):
                spy._note(self_, 'Path.open')
            return real_popen(self_, mode, *a, **k)

        def write_text(self_, *a, **k):
            spy._note(self_, 'write_text')
            return real_wt(self_, *a, **k)

        def write_bytes(self_, *a, **k):
            spy._note(self_, 'write_bytes')
            return real_wb(self_, *a, **k)

        self._patches = [(builtins, 'open', real_open),
                         (pathlib.Path, 'write_text', real_wt),
                         (pathlib.Path, 'write_bytes', real_wb),
                         (pathlib.Path, 'open', real_popen)]
        builtins.open = open_
        pathlib.Path.write_text = write_text
        pathlib.Path.write_bytes = write_bytes
        pathlib.Path.open = path_open
        return self

    def __exit__(self, *exc):
        for obj, name, original in self._patches:
            setattr(obj, name, original)
        return False


class NoEnvWriteFromRequestTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user('boss2', password='p', is_staff=True)
        self.c = Client()
        self.c.force_login(self.staff)
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        # ولا نُخلّف مجلّداً في ``%TEMP%`` لكلّ اختبارٍ في كلّ تشغيل.
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.env = self.tmp / '.env'
        self.env.write_text(
            'DJANGO_SECRET_KEY=x\nDB_HOST=localhost\nDB_PORT=5432\n',
            encoding='utf-8',
        )

    def _digest(self):
        return hashlib.sha256(self.env.read_bytes()).hexdigest()

    def _env_like_files(self):
        """كلُّ ما يشبه ملفَّ بيئةٍ في ``BASE_DIR`` — لا ملفَّ جديداً يُسمح به."""
        return sorted(q.name for q in self.tmp.iterdir()
                      if q.name.startswith('.env'))

    def test_sequence_settings_does_not_touch_the_env_file(self):
        before = self._digest()
        with override_settings(BASE_DIR=self.tmp), _WriteSpy(self.tmp) as spy:
            resp = self.c.post(reverse('sequence_settings'),
                               {'reservation_expire_minutes': '99'})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(self._digest(), before, 'ملفُّ البيئة تغيّر!')
        self.assertEqual(self._env_like_files(), ['.env'])
        self.assertEqual(spy.writes, [], f'كتابةُ ملفٍّ في المشروع: {spy.details}')
        # والقيمةُ حُفظت فعلاً — في القاعدة.
        self.assertEqual(SystemSettings.reservation_ttl(), 99)


class NoFileWriteInSourceTests(TestCase):
    """حارسٌ ثابت: لا كتابةَ ملفٍّ في هذين المُعالِجين، ولا عودةَ الدالّتين."""

    def test_the_two_views_contain_no_file_write_and_no_old_helpers(self):
        from django.conf import settings
        for rel in _MODULES_THAT_MUST_NOT_WRITE:
            src = (pathlib.Path(settings.BASE_DIR) / rel).read_text(encoding='utf-8')
            self.assertEqual(
                find_file_writes(src), [],
                f'{rel}: كتابةُ ملفٍّ عادت إلى مُعالِج طلب')
            self.assertNotIn('_write_env_value', src, rel)
            self.assertNotIn('_write_reservation_expire_setting', src, rel)

    def test_the_guard_itself_catches_a_write(self):
        """تطفيرُ الحارس: لولا هذا لَما عرفنا أنّه يُمسك شيئاً.

        الثلاثةُ الأولى ما أخطأته نسخةُ الـregex؛ والبقيّةُ ما أخطأته نسخةُ
        الـAST الأولى (``open`` باسمٍ مجرّدٍ وحدَه).
        """
        for src in (
            "open(os.path.join(B, '.env'), 'a').write(x)",
            "open(p, mode='w')",
            "pathlib.Path(p).write_text(s)",
            "pathlib.Path(p).open('w')",
            "io.open(p, 'w')",
            "codecs.open(p, 'w', 'utf-8')",
            "os.open(p, os.O_WRONLY)",
            "dotenv.set_key(path, k, v)",
            "set_key(path, k, v)",
            "dotenv.unset_key(path, k)",
            "shutil.copy(src, dst)",
            "shutil.copyfile(src, dst)",
            "shutil.move(src, dst)",
            "os.replace(tmp, target)",
            "os.rename(tmp, target)",
            "f.writelines(lines)",
            "pathlib.Path(p).write_bytes(b)",
        ):
            self.assertTrue(find_file_writes(src), f'مرّت من الحارس: {src}')
        # وما يجب أن يمرّ: قراءةٌ، ونسخُ قاموسٍ (``QueryDict.copy`` ليس shutil).
        for src in (
            "open(p).read()",
            "open(p, 'r', encoding='utf-8')",
            "pathlib.Path(p).read_text()",
            "request.GET.copy()",
            "params.copy()",
            "d.move_to_end(k)",
        ):
            self.assertEqual(find_file_writes(src), [], f'إنذارٌ كاذب: {src}')

    def test_the_runtime_spy_itself_catches_a_write(self):
        """تطفيرُ الجاسوس: كتابةٌ حقيقيّةٌ داخل الجذر يجب أن تُرصَد بكلّ شكل."""
        root = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        with _WriteSpy(root) as spy:
            (root / '.env').write_text('x', encoding='utf-8')
            with open(root / 'a.txt', 'w', encoding='utf-8') as fh:
                fh.write('y')
            with (root / 'b.txt').open('w', encoding='utf-8') as fh:
                fh.write('z')
            (root / 'c.bin').write_bytes(b'q')
            (root / '.env').read_text(encoding='utf-8')          # قراءةٌ: لا تُرصَد
            outside = pathlib.Path(tempfile.mkdtemp())
            self.addCleanup(shutil.rmtree, outside, ignore_errors=True)
            (outside / 'd.txt').write_text('w', encoding='utf-8')  # خارجُ الجذر
        self.assertEqual(spy.writes, ['.env', 'a.txt', 'b.txt', 'c.bin'])
