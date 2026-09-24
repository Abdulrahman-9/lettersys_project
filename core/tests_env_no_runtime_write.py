# -*- coding: utf-8 -*-
"""الحارسُ: **لا مُعالِجَ طلبٍ يكتب في ملفّ البيئة.**

قرارُ المالك (2026-09-24): الموضعان اللذان كانا يكتبان في ``.env`` من مسار
الطلب يُصلَحان **في الكود** لا بتوسيع صلاحيّات الملفّ — فيصير
``.env`` = ``lettersys_svc:R`` خصيصةَ تصميمٍ لا مجازفة.

حارسان: بصمةُ الملفّ قبل/بعد طلبٍ حقيقيّ، وحارسٌ ثابتٌ على المصدر يمنع عودةَ
النمطِ بالنسخ واللصق.
"""
import ast
import hashlib
import json
import pathlib
import tempfile

from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from .models import NetworkSettings, SystemSettings

_MODULES_THAT_MUST_NOT_WRITE = (
    'core/network_views.py',
    'core/views/books_sequence.py',
)

# أيُّ نداءِ كتابةِ ملفّ. **بـAST لا بـregex**: أوّلُ نسخةٍ من هذا الحارس
# استعملت ``open\s*\([^)]*['"][wax]`` وفشلت في إمساك الطفرة
# ``open(os.path.join(BASE_DIR, '.env'), 'a')`` لأنّ ``[^)]*`` يتوقّف عند أوّل
# قوسٍ مغلق — حارسٌ لا يُمسك طفرتَه ليس حارساً.
_READ_MODES = frozenset({'r', 'rb', 'br', 'rt', 'tr', ''})
_WRITE_ATTRS = frozenset({'write_text', 'write_bytes', 'writelines'})


def _mode_of(call: ast.Call):
    """وضعُ الفتح كما هو مكتوبٌ نصّاً، أو None إن لم يكن ثابتاً نصّيّاً."""
    node = None
    if len(call.args) >= 2:
        node = call.args[1]
    for kw in call.keywords:
        if kw.arg == 'mode':
            node = kw.value
    if node is None:
        return ''
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None          # وضعٌ محسوب ⟵ يُعدّ كتابةً احتياطاً


def find_file_writes(source: str):
    """أسماءُ نداءاتِ كتابةِ الملفّات في هذا المصدر (قائمةٌ فارغةٌ = نظيف)."""
    found = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name) and func.id == 'open':
            mode = _mode_of(node)
            if mode is None or mode not in _READ_MODES:
                found.append(f'open(..., mode={mode!r}) @ line {node.lineno}')
        elif isinstance(func, ast.Attribute) and func.attr in _WRITE_ATTRS:
            found.append(f'.{func.attr}() @ line {node.lineno}')
    return found


class NoEnvWriteFromRequestTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user('boss2', password='p', is_staff=True)
        self.c = Client()
        self.c.force_login(self.staff)
        self.tmp = pathlib.Path(tempfile.mkdtemp())
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
        with override_settings(BASE_DIR=self.tmp):
            resp = self.c.post(reverse('sequence_settings'),
                               {'reservation_expire_minutes': '99'})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(self._digest(), before, 'ملفُّ البيئة تغيّر!')
        self.assertEqual(self._env_like_files(), ['.env'])
        # والقيمةُ حُفظت فعلاً — في القاعدة.
        self.assertEqual(SystemSettings.reservation_ttl(), 99)

    def test_network_save_config_does_not_touch_the_env_file(self):
        before = self._digest()
        secret = 'Passw0rd-not-in-any-file'
        payload = {
            'role': 'slave',
            'device_name': 'x',
            'master_host': '172.16.2.99',
            'master_db_port': 5432,
            'master_db_name': 'lettersys',
            'master_db_user': 'lettersys_user',
            'master_db_password': secret,
        }
        with override_settings(BASE_DIR=self.tmp):
            resp = self.c.post(reverse('network-save-config'),
                               data=json.dumps(payload),
                               content_type='application/json')
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(self._digest(), before, 'ملفُّ البيئة تغيّر!')
        self.assertEqual(self._env_like_files(), ['.env'])
        # الكاتبُ الثالثُ داخل ``BASE_DIR`` — ``core/device_identity.py`` يكتب
        # ``.device_identity.json`` وقتَ التشغيل. خارجُ نطاق هذه الرقعة عمداً،
        # ويُثبَّت هنا كي لا يُنسى: ACL الإنتاج **يجب** أن يُبقيه قابلاً
        # للكتابة، وإلّا سقط بصمتٍ وعاد اسمُ الجهاز إلى اسم المضيف.
        self.assertIn('.device_identity.json',
                      [q.name for q in self.tmp.iterdir()])

        body = resp.json()
        self.assertTrue(body['needs_admin_env'])
        self.assertEqual(
            body['env_lines'][:4],
            ['DB_HOST=172.16.2.99', 'DB_PORT=5432',
             'DB_NAME=lettersys', 'DB_USER=lettersys_user'],
        )
        # الكلمةُ لا تُصدَّر بأيّ صورة
        self.assertNotIn(secret, resp.content.decode('utf-8'))
        # وهي مخزَّنةٌ مشفَّرةً في القاعدة
        cfg = NetworkSettings.get()
        self.assertNotEqual(cfg.master_db_password_enc, secret)
        self.assertEqual(cfg.get_db_password(), secret)

    def test_standalone_role_promises_nothing(self):
        with override_settings(BASE_DIR=self.tmp):
            resp = self.c.post(reverse('network-save-config'),
                               data=json.dumps({'role': 'standalone'}),
                               content_type='application/json')
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertFalse(body['needs_admin_env'])
        self.assertEqual(body['env_lines'], [])

    def test_non_staff_cannot_save_network_config(self):
        plain = Client()
        plain.force_login(User.objects.create_user('nobody', password='p'))
        resp = plain.post(reverse('network-save-config'),
                          data=json.dumps({'role': 'slave'}),
                          content_type='application/json')
        self.assertIn(resp.status_code, (302, 403))
        self.assertFalse(NetworkSettings.objects.filter(is_configured=True).exists())


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

        الأشكالُ الثلاثةُ التي أخطأتها نسخةُ الـregex الأولى.
        """
        self.assertTrue(find_file_writes(
            "open(os.path.join(B, '.env'), 'a').write(x)"))
        self.assertTrue(find_file_writes("open(p, mode='w')"))
        self.assertTrue(find_file_writes("pathlib.Path(p).write_text(s)"))
        self.assertEqual(find_file_writes("open(p).read()"), [])
        self.assertEqual(find_file_writes("open(p, 'r', encoding='utf-8')"), [])
