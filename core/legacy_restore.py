# -*- coding: utf-8 -*-
"""
محرّك استعادة البيانات من قاعدة بريد قديمة (نوع ARCHMDOC على SQL Server).

البنية المتوقّعة للمصدر:
  جداول: IIMAIL_YYYY (وارد داخلي)، IOMAIL_YYYY (صادر داخلي)،
         OIMAIL_YYYY (وارد خارجي)، OOMAIL_YYYY (صادر خارجي)
  أعمدة الوارد:  {P}ID {P}WID {P}NUM {P}DATE {P}CND {P}SUB {P}FROM {P}CLAS {P}STAT {P}SUBROOT {P}ACTION {P}NOTE {P}FILE
  أعمدة الصادر:  {P}ID {P}NUM {P}DATE {P}SUB {P}TO {P}CLAS {P}STAT {P}SUBROOT {P}ACTION {P}NOTE {P}FILE

التطبيع المطبَّق (القاعدة كلّها من `core/numbering.py` — المصدر الوحيد):
  - الوارد:  our_number من عمود WID (رقم ختمنا، سلسلةٌ كثيفة مقيسة 1.00)
             sender_number = NUM  — رقمهم (مبعثر، تكرار مقبول)
             receiving_entities = SUBROOT مفصولاً على "+"  — جهة الارتباط
  - صادر داخلي: our_number من عمود NUM (لا عمود WID في جداول الصادر)
  - صادر خارجي: our_number = NUM كما هو — رقم مكتب المدير العام، بلا سلسلة منّا
  والصيغة: سجلّ 2026 فما بعد ⇒ رقم مجرّد؛ 2025 وما قبله ⇒ موسوم بسنة سجلّه.
  - document_type = CLAS، التواريخ من DATE/CND، العنوان من SUB، الجهة المصدرة من FROM (للوارد)
  - المرفق من العمود {P}FILE (varbinary → PDF)
"""
import logging
import os
import re
import unicodedata
from collections import defaultdict
from datetime import date, datetime

from django.db import transaction
from django.utils import timezone

from . import numbering

logger = logging.getLogger(__name__)

# (prefix الجدول, kind, is_outgoing)
TABLE_KINDS = [
    ('II', 'incoming_internal', False),
    ('IO', 'outgoing_internal', True),
    ('OI', 'incoming_external', False),
    ('OO', 'outgoing_external', True),
]

_STATUS_MAP = {
    '':              'pending',
    'حفظ':           'archived',
    'تمت الاجابة':   'done',
    'تمت الإجابة':   'done',
    'قيد المتابعة':  'pending',
    'منجز':          'done',
    'منجزة':         'done',
}

_GARBAGE_RE = re.compile(r'^[\s\d.+\-_]*$|^ا+$|^كوم$')


def _norm_status(raw, book_date=None):
    s = (raw or '').strip()
    if s in _STATUS_MAP:
        return _STATUS_MAP[s]
    # افتراضي: القديم → مؤرشف، الحديث → قيد المتابعة
    cutoff = date(2026, 1, 1)
    if book_date and isinstance(book_date, (date, datetime)):
        d = book_date.date() if isinstance(book_date, datetime) else book_date
        return 'pending' if d >= cutoff else 'archived'
    return 'archived'


def _parse_date(v):
    if not v:
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    for fmt in ('%Y-%m-%d', '%d/%m/%Y', '%Y/%m/%d'):
        try:
            return datetime.strptime(str(v)[:10], fmt).date()
        except ValueError:
            continue
    return None


def _legacy_dates(rd, prefix, is_out):
    """تعيينُ عمودَي التاريخ من سجلّ المصدر ⟵ `(Book.date, Book.sender_date)`.

    **مُصحَّحٌ 2026-08-23 (مؤكَّدٌ عدائيّاً — سجلّ التقييم قسم D):** في سجلّات
    الوارد عمود `DATE` هو **حبرُ الجهة** و`CND` (القيد) هو **تاريخُنا** — عكسُ
    ما يوحي به الاسمان. الأدلّة: رتابةُ سلسلة الختم WID لعمود CND (انقلاب
    0.36%/0.00% في IIMAIL 2025/2026) مقابل بعثرة DATE (~29%)، والجمعةُ صفرٌ
    مطلقٌ في CND (0/11,050 — دوامُنا الرسميّ) مقابل 3.33% عطلاً في DATE،
    والعينُ على القصاصات 5/5. التعيينُ القديم كان معكوساً، وأصلحت الصفوفَ
    المستوردةَ قبله هجرةُ المبادلة 0060.

    الصادر بلا انقلاب: `DATE` تاريخُنا فعلاً (رتيبٌ 2.8–3.5% فقط) ولا `CND`
    معتبرَ فيه (فارغٌ في 2,039/2,041)."""
    if is_out:
        return _parse_date(rd.get(f"{prefix}DATE")), None
    return (_parse_date(rd.get(f"{prefix}CND")),      # تاريخُ قيدنا
            _parse_date(rd.get(f"{prefix}DATE")))     # حبرُ الجهة


def _parse_entity_names(raw):
    """
    يفصل 'شعبة X + سارة' → ['شعبة X', 'سارة'].
    لا يقطع أي حروف من بداية الاسم (تجنّباً لقطع 'و' من 'وحدة').
    يوسّع اختصار 'و.X' → 'وحدة X' فقط (نمط معروف في المصدر).
    """
    if not raw:
        return []
    s = str(raw)
    # الفواصل: + ، , — نتجنّب ' و ' كفاصل لأنها قد تكون جزءاً من اسم ('الفحص و التدقيق')
    for sep in ('،', ','):
        s = s.replace(sep, '+')
    out = []
    for part in s.split('+'):
        part = part.strip()
        # توسيع اختصار "و.التقارير" / "و. اللجان" → "وحدة التقارير"
        if re.match(r'^و\.\s*\S', part):
            part = 'وحدة ' + re.sub(r'^و\.\s*', '', part)
        if part and not _GARBAGE_RE.match(part):
            out.append(part)
    return out


_TITLE_FOLD = str.maketrans('أإآىة', 'ااايه')
_TITLE_MARKS_RE = re.compile(r'[ً-ْـ]')  # تشكيل + تطويل
_WS_RE = re.compile(r'\s+')


def _norm_title(s):
    """يطوي العنوان لمقارنة متسامحة: توحيد الألف/الياء/التاء، وحذف التشكيل والتطويل."""
    s = unicodedata.normalize('NFKC', (s or '')).strip().translate(_TITLE_FOLD)
    return _WS_RE.sub(' ', _TITLE_MARKS_RE.sub('', s)).lower()


def _free_bytes(path):
    """
    المساحة الحرّة على قرص المسار. نقيس عند جذر القرص لا عند المجلّد نفسه، لأنّ
    مجلّد بيانات SQL Server (داخل Program Files) يرفض القراءة من حساب التطبيق
    (WinError 5) بينما جذر القرص مقروء دائماً. None = تعذّر القياس (لا نمنع المحاولة).
    """
    import os, shutil
    root = os.path.splitdrive(os.path.abspath(path))[0]
    try:
        return shutil.disk_usage(root + os.sep if root else path).free
    except OSError:
        return None


def serialize_for_json(obj):
    if isinstance(obj, (date, datetime)):
        return obj.isoformat()
    return str(obj) if obj is not None else None


class LegacyRestoreEngine:
    """يستعيد البيانات من قاعدة SQL Server قديمة إلى نماذج LetterSys."""

    def __init__(self, server, database, username, password, years=None):
        self.server = server
        self.database = database
        self.username = username
        self.password = password
        self.years = years  # None = اكتشاف تلقائي
        self._conn = None
        self._entity_cache = {}       # norm_key → Entity (لهذا التشغيل)
        self._entity_by_key = None    # خريطة كل الجهات، تُبنى عند أول حاجة
        self._created_entities = []   # أسماء أُنشئت فعلاً — تُعرض للمراجعة

    # ── الاستعادة من ملف باكاب (.bak أو مضغوط) ──────────────────────────────
    @classmethod
    def restore_from_bak(cls, bak_path, sql_server='localhost', admin_user='sa', admin_password='',
                         created_by=None, restore_files=True, mode='skip_existing', progress_cb=None,
                         work_dir=None):
        """
        يستعيد .bak إلى قاعدة SQL Server مؤقتة محلية ثم يستورد منها — دون لمس القاعدة الأصلية.
        - مضغوط (.zip / .7z / .tar.gz): يُفَكّ تلقائياً ويُبحَث عن أول .bak داخله.
        - غير مضغوط (.bak): يُستعمَل مباشرة.
        - work_dir: مجلّد ملفات القاعدة المؤقتة. فارغ = تلقائي (مجلّد بيانات SQL Server،
          فإن ضاقت مساحته فمجلّد ملف الباكاب نفسه).
        بعد الاستيراد: تُحذف القاعدة المؤقتة وملفاتها والمستخرجات.
        """
        import os, time, shutil, tempfile
        bak_path = os.path.abspath(os.path.expanduser(bak_path))
        if not os.path.exists(bak_path):
            return {'aborted': True, 'reason': f'الملف غير موجود: {bak_path}'}

        try:
            import pyodbc
        except ImportError:
            return {'aborted': True, 'reason': 'مكتبة pyodbc غير مثبّتة على الخادم.'}

        tmp_extract = None
        actual_bak = bak_path
        low = bak_path.lower()
        try:
            # ── فكّ الضغط إن لزم — نستخرج بجانب الملف الأصلي (نفس القرص ليصله SQL Server) ──
            if low.endswith('.zip') or low.endswith('.7z') or low.endswith('.tar.gz') or low.endswith('.tgz'):
                tmp_extract = os.path.join(os.path.dirname(bak_path), f"_legacy_restore_tmp_{int(time.time())}")
                os.makedirs(tmp_extract, exist_ok=True)
                if progress_cb: progress_cb('جارٍ فكّ الضغط...')
                if low.endswith('.zip'):
                    import zipfile
                    with zipfile.ZipFile(bak_path) as zf:
                        zf.extractall(tmp_extract)
                elif low.endswith('.7z'):
                    try:
                        import py7zr
                    except ImportError:
                        return {'aborted': True, 'reason': 'ملف 7z يتطلب مكتبة py7zr. استخرجه يدوياً أو حوّله إلى zip، ثم زوّد مسار .bak مباشرة.'}
                    with py7zr.SevenZipFile(bak_path) as zf:
                        zf.extractall(tmp_extract)
                else:  # tar.gz / tgz
                    import tarfile
                    with tarfile.open(bak_path) as tf:
                        tf.extractall(tmp_extract)
                # ابحث عن أول .bak
                found = None
                for root, _dirs, files in os.walk(tmp_extract):
                    for f in files:
                        if f.lower().endswith('.bak'):
                            found = os.path.join(root, f); break
                    if found: break
                if not found:
                    return {'aborted': True, 'reason': 'لم يُعثر على ملف .bak داخل الأرشيف.'}
                actual_bak = found
            elif low.endswith('.rar'):
                return {'aborted': True, 'reason': 'ملفات RAR غير مدعومة آلياً — استخرجه يدوياً وزوّد مسار ملف .bak مباشرة.'}
            elif not low.endswith('.bak'):
                return {'aborted': True, 'reason': 'الامتداد غير معروف — المتوقَّع .bak أو أرشيف يحوي .bak.'}

            # ── الاتصال كأدمن (autocommit لازم لـ RESTORE/DROP) ──
            # نفس بديل TCP المستعمل في connect(): الذاكرة المشتركة تفشل تحت الضغط
            def _admin_cs(srv):
                return (f"DRIVER={{ODBC Driver 17 for SQL Server}};SERVER={srv};DATABASE=master;"
                        f"UID={admin_user};PWD={admin_password};"
                        f"TrustServerCertificate=yes;Connection Timeout=30;")
            _srvs = [sql_server]
            if (sql_server or '').strip().lower() in ('', '.', '(local)', 'localhost', '127.0.0.1'):
                _srvs.append('tcp:127.0.0.1,1433')
            conn = None
            for _s in _srvs:
                try:
                    conn = pyodbc.connect(_admin_cs(_s), autocommit=True)
                    admin_cs = _admin_cs(_s)
                    break
                except Exception as _e:
                    logger.warning('restore_from_bak: connect via %r failed: %s', _s, str(_e)[:160])
            if conn is None:
                return {'aborted': True, 'reason': 'تعذّر الاتصال بـ SQL Server (جُرّب الاسم وTCP).'}
            cur = conn.cursor()
            esc_bak = actual_bak.replace("'", "''")

            # بنية ملفات الباكاب
            cur.execute(f"RESTORE FILELISTONLY FROM DISK = N'{esc_bak}'")
            cols = [d[0] for d in cur.description]
            files_info = [dict(zip(cols, r)) for r in cur.fetchall()]
            data_logical = next((f.get('LogicalName') for f in files_info if (f.get('Type') or '').upper() == 'D'), None)
            log_logical  = next((f.get('LogicalName') for f in files_info if (f.get('Type') or '').upper() == 'L'), None)
            extra_data   = [f.get('LogicalName') for f in files_info if (f.get('Type') or '').upper() == 'D'][1:]
            if not data_logical:
                conn.close()
                return {'aborted': True, 'reason': 'تعذّر قراءة بنية ملف الباكاب (RESTORE FILELISTONLY).'}

            # ── مجلّد ملفات القاعدة المؤقتة ──
            # الاستعادة تكتب ملف البيانات وملف السجلّ بحجمهما الأصلي: باكاب 16 ج.ب قد
            # يحتاج 36 ج.ب على القرص. مجلّد SQL Server الافتراضي على C: غالباً أضيق من
            # ذلك، لذا نقيس المساحة ونسقط إلى قرص ملف الباكاب بدل الفشل بعد نصف ساعة.
            needed = int(sum(float(f.get('Size') or 0) for f in files_info) * 1.05)
            try:
                cur.execute("SELECT CAST(SERVERPROPERTY('InstanceDefaultDataPath') AS NVARCHAR(512))")
                default_dir = (cur.fetchone()[0] or '').strip()
            except Exception:
                default_dir = ''

            if work_dir:
                if not os.path.isdir(work_dir):
                    conn.close()
                    return {'aborted': True, 'reason': f'مجلّد العمل غير موجود: {work_dir}'}
                candidates = [work_dir]
            else:
                candidates = [d for d in (default_dir, os.path.dirname(actual_bak)) if d]

            # قياس المساحة يقيس **جهاز جانغو**، وهو نفس جهاز SQL Server فقط حين
            # يكون الخادم محلياً. مع خادمٍ بعيد المسارات تخصّه هو، فقياسنا بلا معنى
            # وقد يرفض مجلّداً سليماً أو يقبل مجلّداً لا يستطيع الخادم الكتابة فيه.
            # في تلك الحالة نمضي بلا فحص ونترك SQL Server يُبلّغ بخطئه الصريح.
            host = (sql_server or '').split('\\')[0].split(',')[0].strip().lower()
            server_is_local = host in ('', '.', '(local)', 'localhost', '127.0.0.1', '::1')

            data_dir, tried = None, []
            for cand in candidates:
                free = _free_bytes(cand) if server_is_local else None
                if free is None or free >= needed:
                    data_dir = cand
                    break
                tried.append(f"{cand} — {free / 2**30:.1f} ج.ب حرّة")
            if not data_dir:
                conn.close()
                return {'aborted': True, 'reason': (
                    f"المساحة لا تكفي: الاستعادة المؤقتة تحتاج ~{needed / 2**30:.1f} ج.ب "
                    f"(بيانات + سجلّ). جُرِّب: {'، '.join(tried)}. "
                    f"حدّد «مجلّد العمل» على قرص فيه مساحة كافية.")}

            temp_db = f"LEGACYRESTORE_{int(time.time())}"
            def _p(name, suffix): return os.path.join(data_dir, f"{temp_db}_{name}{suffix}").replace("'", "''")
            moves = [f"MOVE N'{data_logical}' TO N'{_p('data', '.mdf')}'"]
            for i, ed in enumerate(extra_data):
                moves.append(f"MOVE N'{ed}' TO N'{_p('data%d' % (i+2), '.ndf')}'")
            if log_logical:
                moves.append(f"MOVE N'{log_logical}' TO N'{_p('log', '.ldf')}'")
            restore_sql = (f"RESTORE DATABASE [{temp_db}] FROM DISK = N'{esc_bak}' "
                           f"WITH {', '.join(moves)}, REPLACE, RECOVERY")

            if progress_cb: progress_cb(f'جارٍ استعادة الباكاب إلى قاعدة مؤقتة [{temp_db}] (قد يستغرق دقائق)...')
            cur.execute(restore_sql)
            # استهلاك رسائل تقدّم RESTORE إن وُجدت
            try:
                while cur.nextset():
                    pass
            except Exception:
                pass
            conn.close()

            # ── الاستيراد من القاعدة المؤقتة ──
            try:
                if progress_cb: progress_cb('جارٍ استيراد البيانات من القاعدة المؤقتة...')
                engine = cls(sql_server, temp_db, admin_user, admin_password)
                summary = engine.run(created_by=created_by, restore_files=restore_files,
                                     mode=mode, progress_cb=progress_cb)
            finally:
                # إسقاط القاعدة المؤقتة
                try:
                    c2 = pyodbc.connect(admin_cs, autocommit=True).cursor()
                    c2.execute(f"ALTER DATABASE [{temp_db}] SET SINGLE_USER WITH ROLLBACK IMMEDIATE")
                    c2.execute(f"DROP DATABASE [{temp_db}]")
                    c2.connection.close()
                except Exception as e:
                    logger.warning("legacy_restore: drop temp db %s failed: %s", temp_db, e)
            return summary
        finally:
            if tmp_extract and os.path.isdir(tmp_extract):
                shutil.rmtree(tmp_extract, ignore_errors=True)

    # ── الاتصال ────────────────────────────────────────────────────────────
    def _conn_str(self, server=None):
        return (
            f"DRIVER={{ODBC Driver 17 for SQL Server}};"
            f"SERVER={server or self.server};DATABASE={self.database};"
            f"UID={self.username};PWD={self.password};"
            f"TrustServerCertificate=yes;Connection Timeout=15;"
        )

    def _server_candidates(self):
        """
        اسم الخادم كما كتبه المستخدم، ثم بديلٌ يفرض TCP إن كان محلياً.

        السبب مقيس على هذا الجهاز: مع `SERVER=localhost` يجرّب ODBC **الذاكرة
        المشتركة** أوّلاً، وهي تفشل تحت ضغط الذاكرة برسالة مضلّلة
        («No process is on the other end of the pipe») رغم أن الخدمة تعمل
        والمنفذ 1433 مفتوح. فرض TCP ينجح في نفس اللحظة. لا نجعل TCP الافتراضَ
        كي لا نكسر إعداداً يعتمد اسم نسخةٍ مسمّاة.
        """
        first = (self.server or 'localhost').strip()
        out = [first]
        low = first.lower()
        if '\\' not in first and not low.startswith('tcp:') and \
                low in ('', '.', '(local)', 'localhost', '127.0.0.1'):
            out.append('tcp:127.0.0.1,1433')
        return out

    def connect(self):
        import pyodbc
        last = None
        for server in self._server_candidates():
            try:
                self._conn = pyodbc.connect(self._conn_str(server))
                return self._conn
            except Exception as exc:
                last = exc
                logger.warning('legacy_restore: connect via %r failed: %s', server, str(exc)[:160])
        raise last

    def close(self):
        if self._conn:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None

    # ── الاكتشاف ───────────────────────────────────────────────────────────
    def discover(self):
        """يُعيد قائمة جداول البريد مع أعداد الصفوف. (يفتح اتصالاً مؤقتاً)"""
        self.connect()
        cur = self._conn.cursor()
        # كل الجداول
        cur.execute("SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_TYPE='BASE TABLE'")
        all_tables = {r[0] for r in cur.fetchall()}
        result = []
        # اكتشف السنوات من أسماء الجداول
        years = set()
        for t in all_tables:
            m = re.match(r'^(II|IO|OI|OO)MAIL_(\d{4})$', t)
            if m:
                years.add(m.group(2))
        years = sorted(years)
        if self.years:
            years = [y for y in years if y in self.years]
        for prefix, kind, is_out in TABLE_KINDS:
            for y in years:
                tbl = f"{prefix}MAIL_{y}"
                if tbl not in all_tables:
                    continue
                cur.execute(f"SELECT COUNT(*) FROM [{tbl}]")
                n = cur.fetchone()[0]
                with_file = 0
                try:
                    cur.execute(f"SELECT COUNT(CASE WHEN {prefix}FILE IS NOT NULL AND DATALENGTH({prefix}FILE)>0 THEN 1 END) FROM [{tbl}]")
                    with_file = cur.fetchone()[0]
                except Exception:
                    pass
                result.append({'table': tbl, 'kind': kind, 'year': y, 'rows': n, 'with_file': with_file})
        self.close()
        return {'years': years, 'tables': result}

    # ── جهات ───────────────────────────────────────────────────────────────
    @staticmethod
    def _canonical_entity(entity):
        """يتبع سلسلة `merged_into` إلى الجهة التي بقيت بعد الدمج."""
        seen = set()
        while entity is not None and entity.merged_into_id and entity.id not in seen:
            seen.add(entity.id)
            entity = entity.merged_into
        return entity

    def _get_entity(self, name):
        """
        يُرجع الجهة المطابقة للاسم، أو يُنشئها.

        نقطتان تعلّمناهما من بيانات هذا النظام (638 جهة، منها 196 مدموجة و261
        غير نشطة):
          • المطابقة بـ`name__iexact` وحدها تلتقط جهةً **دُمجت** يدوياً في أخرى،
            فيُعاد ربط الكتب بها ويُبطَل دمجٌ راجعه إنسان. لذا نتبع `merged_into`.
          • مفتاح الذاكرة المؤقّتة بـ`lower()` يعتبر «وزارة النفط» و«وزاره النفط»
            اسمين مختلفين فيُنشئ نسخة ثانية. نستعمل `norm_key` — نفس المُطبِّع
            الذي يعتمده كاشف التكرار — فلا نصنع له عملاً جديداً.
        """
        from .entity_dedup import norm_key
        from .models import Entity

        name = (name or '').strip()
        if not name or _GARBAGE_RE.match(name):
            return None

        key = norm_key(name)
        if key in self._entity_cache:
            return self._entity_cache[key]

        # تُبنى خريطة الأسماء المُطبَّعة مرّة واحدة (بضع مئات من الجهات)، فالبحث
        # عن كل اسم جديد يصير قاموسياً بدل مسحٍ خطّي على الجدول لكل اسم.
        if self._entity_by_key is None:
            self._entity_by_key = {}
            for cand in Entity.objects.select_related('merged_into').only(
                    'id', 'name', 'is_active', 'merged_into'):
                k = norm_key(cand.name)
                canon = self._canonical_entity(cand)
                # النشطة تفوز على المدموجة/المعطّلة عند تساوي المفتاح
                if k not in self._entity_by_key or (canon and canon.is_active):
                    self._entity_by_key[k] = canon

        e = self._entity_by_key.get(key)
        if e is None:
            e = Entity.objects.create(name=name, etype='both', is_active=True)
            self._created_entities.append(name)
            self._entity_by_key[key] = e

        self._entity_cache[key] = e
        return e

    # ── المطابقة: ختم source_ref على ما استُورد سابقاً ─────────────────────
    def _source_index(self, cur, all_tables, years):
        """
        يمسح جداول البريد ويُعيد صفوف المصدر خفيفةً: بلا نقل أي مرفق.
        نطلب DATALENGTH({P}FILE) لا {P}FILE — الخادم يحسب الطول من الميتاداتا،
        فلا يعبر البايتات الشبكةَ ولا الذاكرة.
        """
        rows = []
        for prefix, kind, _is_out in TABLE_KINDS:
            for y in years:
                tbl = f"{prefix}MAIL_{y}"
                if tbl not in all_tables:
                    continue
                try:
                    cur.execute(
                        f"SELECT {prefix}ID, {prefix}DATE, {prefix}SUB, "
                        f"DATALENGTH({prefix}FILE) FROM [{tbl}]"
                    )
                except Exception as e:
                    logger.warning("reconcile: skip %s: %s", tbl, e)
                    continue
                for sid, sdate, ssub, slen in cur.fetchall():
                    rows.append((f"{tbl}#{sid}", kind, _parse_date(sdate),
                                 ssub, int(slen or 0)))
        return rows

    @staticmethod
    def _attachment_sizes(book_ids=None):
        """
        book_id → حجم أوّل مرفق حيّ بالبايت (stat فقط، لا قراءة محتوى).

        `book_ids` يقصر المسح على الكتب التي تهمّ المطابقة (غير المربوطة). بدونه
        كانت كل ضغطة معاينة تستعلم حالة ١١ ألف ملف على قرصٍ بطيء بلا داعٍ —
        والمربوط منها لا يدخل المطابقة أصلاً.
        """
        import os
        from django.conf import settings
        from .models import Attachment
        root = str(settings.MEDIA_ROOT)
        qs = Attachment.objects.filter(is_deleted=False)
        if book_ids is not None:
            qs = qs.filter(book_id__in=list(book_ids))
        out = {}
        for bid, rel in qs.order_by('book_id', 'id').values_list('book_id', 'file'):
            if bid in out or not rel:
                continue
            try:
                out[bid] = os.path.getsize(os.path.join(root, rel.replace('/', os.sep)))
            except OSError:
                continue
        return out

    def reconcile(self, apply=False, progress_cb=None, verify_bytes=0):
        """
        يربط الكتب الموجودة بصفوفها الأصلية في المصدر ويختم `source_ref`.

        لماذا: `source_ref` هو مفتاح الدمج الوحيد الدقيق، وهو فارغ في كل الكتب
        المستوردة بالأدوات السابقة. بدونه يسقط الدمج على مطابقة
        (kind, legacy_number) الملتبسة، فيربط الصفّ بكتابٍ خاطئ أو يُكرّره.

        المفتاح المُعتمَد — مقيسٌ على البيانات الحقيقية:
          م١  (النوع، التاريخ، حجم المرفق بالبايت)  → مطابقة فريدة بصفر التباس
          م٢  (النوع، التاريخ، العنوان المطوي)       → لالتقاط الصفوف بلا مرفق
        كل صفّ مصدر يُطالَب مرّة واحدة فقط، وكل كتاب يُربط مرّة واحدة فقط.

        لا يكتب إلا `source_ref`، ولا يلمس كتاباً له `source_ref` أصلاً.
        `apply=False` (الافتراضي) = معاينة تُحصي ولا تكتب.
        `verify_bytes=N` = يسحب مرفق N زوجاً مطابقاً ويقارن بصمته بالملف المحلي.
        """
        import hashlib
        import os
        from django.conf import settings
        from .models import Attachment, Book

        self.connect()
        cur = self._conn.cursor()
        cur.execute("SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_TYPE='BASE TABLE'")
        all_tables = {r[0] for r in cur.fetchall()}
        years = sorted({m.group(2) for t in all_tables
                        if (m := re.match(r'^(II|IO|OI|OO)MAIL_(\d{4})$', t))})
        if self.years:
            years = [y for y in years if y in self.years]

        if progress_cb:
            progress_cb('جارٍ مسح صفوف المصدر (بلا مرفقات)...')
        src = self._source_index(cur, all_tables, years)

        # صفوف مطلوبة سلفاً من كتب مختومة — لا نمنحها لكتابٍ آخر
        claimed = set(Book.objects.exclude(source_ref='').values_list('source_ref', flat=True))

        if progress_cb:
            progress_cb('جارٍ فهرسة الكتب الحالية...')
        # ترتيب ثابت (id) كي تكون نتيجة المطابقة قابلة لإعادة الإنتاج: حين يتشارك
        # كتابان مفتاحاً واحداً مع صفٍّ واحد، لا نريد أن يقرّر ترتيب القاموس.
        unstamped = list(Book.objects.filter(source_ref='')
                         .order_by('id').values_list('id', 'kind', 'date', 'title'))
        sizes = self._attachment_sizes({row[0] for row in unstamped})
        targets = [(bid, kind, d, title, sizes.get(bid, 0))
                   for bid, kind, d, title in unstamped]

        by_size, by_title = defaultdict(list), defaultdict(list)
        for sref, kind, sdate, ssub, slen in src:
            if sref in claimed:
                continue
            if slen and sdate:
                by_size[(kind, sdate, slen)].append(sref)
            nt = _norm_title(ssub)
            if sdate and nt:
                by_title[(kind, sdate, nt)].append(sref)

        def _title_key(t):
            nt = _norm_title(t[3])
            return (t[1], t[2], nt) if t[2] and nt else None

        assign = {}
        method = {}          # book_id → 'size' أو 'title' — أيّ مفتاحٍ ربطه
        ambiguous = 0
        for name, index, keyer in (
            ('size', by_size,
             lambda t: (t[1], t[2], t[4]) if t[4] and t[2] else None),
            ('title', by_title, _title_key),
        ):
            for t in targets:
                if t[0] in assign:
                    continue
                key = keyer(t)
                if key is None:
                    continue
                cands = [c for c in index.get(key, ()) if c not in claimed]
                if len(cands) == 1:
                    assign[t[0]] = cands[0]
                    method[t[0]] = name
                    claimed.add(cands[0])
                elif len(cands) > 1:
                    ambiguous += 1

        report = {
            'source_rows': len(src),
            'books_without_ref': len(targets),
            'matched': len(assign),
            'ambiguous': ambiguous,
            'unmatched_books': len(targets) - len(assign),
            'unclaimed_source_rows': sum(1 for s in src if s[0] not in claimed),
            'matched_by_size': sum(1 for m in method.values() if m == 'size'),
            'matched_by_title': sum(1 for m in method.values() if m == 'title'),
            'applied': False,
            'verified_bytes': 0,
            'unverifiable': 0,
            'verify_mismatches': [],
            'attention': [],
        }

        # ── تحقّق بالبايتات: هل الملف المحلي هو فعلاً مرفق ذلك الصفّ؟ ──
        if verify_bytes and assign:
            root = str(settings.MEDIA_ROOT)
            att_of = {}
            for bid, rel in (Attachment.objects.filter(is_deleted=False, book_id__in=list(assign))
                             .order_by('book_id', 'id').values_list('book_id', 'file')):
                att_of.setdefault(bid, rel)

            # البصمة تُفحَص على مطابقات **الحجم** وحدها: هناك الحجمان متطابقان،
            # فاتّفاق البصمة يُثبت أن الملف المحلي هو ذاته مرفق الصفّ.
            # مطابقات العنوان مستثناة بحكم تعريفها: هي التي لم يتطابق حجمها،
            # فبصمتها ستختلف حتماً ومقارنتها تُنتج إنذاراً كاذباً يُلغي كل الختم.
            # تُدرَج بدل ذلك في قائمة «تحتاج نظرك» بحجمَيها للمقارنة اليدوية.
            size_matched = [b for b in assign if method.get(b) == 'size']

            checked = 0
            for bid in size_matched:
                sref = assign[bid]
                if checked >= verify_bytes:
                    break
                rel = att_of.get(bid)
                if not rel:
                    report['unverifiable'] += 1
                    continue
                tbl, sid = sref.split('#')
                prefix = tbl[:2]
                try:
                    cur.execute(f"SELECT {prefix}FILE FROM [{tbl}] WHERE {prefix}ID = ?", int(sid))
                    row = cur.fetchone()
                except Exception as e:
                    logger.warning('reconcile verify: %s: %s', sref, e)
                    continue
                if not row or not row[0]:
                    continue
                src_digest = hashlib.sha256(bytes(row[0])).hexdigest()
                try:
                    h = hashlib.sha256()
                    with open(os.path.join(root, rel.replace('/', os.sep)), 'rb') as fh:
                        for chunk in iter(lambda: fh.read(1 << 20), b''):
                            h.update(chunk)
                except OSError:
                    continue
                checked += 1
                if h.hexdigest() != src_digest:
                    report['verify_mismatches'].append((bid, sref))
            report['verified_bytes'] = checked

        # الكتب المربوطة بالعنوان: مفتاحها لا يشمل الحجم، فنُظهر الفارق ليقرّره المالك.
        if assign:
            src_len = {s[0]: s[4] for s in src}
            for bid in assign:
                if method.get(bid) != 'title':
                    continue
                report['attention'].append({
                    'book': bid, 'source_ref': assign[bid],
                    'local_bytes': sizes.get(bid, 0),
                    'source_bytes': src_len.get(assign[bid], 0),
                })

        # بصمة واحدة مختلفة تعني أن المفتاح يربط كتاباً بصفٍّ ليس له — لا نختم شيئاً.
        if apply and report['verify_mismatches']:
            report['aborted'] = 'اختلفت بصمات المرفقات في عيّنة التحقّق — أُلغي الختم كلّه.'
            self.close()
            return report

        if apply and assign:
            books = list(Book.objects.filter(id__in=list(assign)).only('id', 'source_ref'))
            for b in books:
                b.source_ref = assign[b.id]
            Book.objects.bulk_update(books, ['source_ref'], batch_size=500)
            report['applied'] = True

        self.close()
        return report

    # حجم دفعة الحقول النصّية. صغيرٌ عمداً: الجهاز ضيّق الذاكرة، وحدّ معاملات
    # SQL Server 2100 يمنع دفعاتٍ أكبر بكثير على أي حال.
    SCALAR_BATCH = 200
    # ٤ م.ب لكل قراءة: بـ١ م.ب كان المرفق الواحد يحتاج عشرات الاستعلامات و١٣ ج.ب
    # من المرفقات تعني ~13,400 استعلاماً، كلفتها في الذهاب والإياب أكبر من النقل
    # نفسه. الذروة تبقى ٤ م.ب — آمنة على جهازٍ ضيّق الذاكرة.
    BLOB_CHUNK = 4 << 20

    @staticmethod
    def _blob_tmp_dir():
        """
        مجلّد مؤقّت **داخل** قرص الوسائط.

        السبب: تخزين Django ينقل الملف بـrename إن كان على نفس القرص، وينسخه
        بايتاً بايتاً إن كان على قرصٍ آخر. المجلّد المؤقّت الافتراضي على C:
        والوسائط على D:، فكان كل مرفق يُكتب مرّتين — ١٣ ج.ب تتحوّل إلى ~٣٩ ج.ب
        من الإدخال/الإخراج على قرصٍ بطيء.
        """
        import os
        from django.conf import settings
        d = os.path.join(str(settings.MEDIA_ROOT), 'tmp')
        os.makedirs(d, exist_ok=True)
        return d

    @classmethod
    def _stream_blob(cls, cur, tbl, prefix, src_id, total=None):
        """
        يسحب مرفق صفٍّ واحد إلى ملفٍ مؤقّت على القرص، مقطّعاً بـ SUBSTRING.

        pyodbc لا يوفّر بثّاً للحقول الكبيرة، فقراءة العمود دفعةً واحدة تعني
        حجز حجم الـPDF كاملاً في الذاكرة (وبعضها يتجاوز ١٠٠ م.ب). SUBSTRING
        على الخادم هي السبيل الوحيد لقراءةٍ محدودة الذاكرة.

        `total` = طول المرفق إن كان معروفاً سلفاً (مرحلة التعداد تقرأه مجّاناً)،
        فنوفّر استعلام DATALENGTH لكل صفّ.

        يُعيد مسار ملفٍ مؤقّت (على المستدعي حذفه) أو None إن لا مرفق.
        """
        import tempfile
        if total is None:
            cur.execute(f"SELECT DATALENGTH({prefix}FILE) FROM [{tbl}] WHERE {prefix}ID = ?", src_id)
            row = cur.fetchone()
            total = int((row and row[0]) or 0)
        if total <= 0:
            return None

        fd, path = tempfile.mkstemp(prefix='legacy_blob_', suffix='.bin', dir=cls._blob_tmp_dir())
        try:
            with os.fdopen(fd, 'wb') as fh:
                off = 1                       # SUBSTRING في SQL Server يبدأ من ١
                while off <= total:
                    cur.execute(
                        f"SELECT SUBSTRING({prefix}FILE, ?, ?) FROM [{tbl}] WHERE {prefix}ID = ?",
                        off, cls.BLOB_CHUNK, src_id)
                    part = cur.fetchone()
                    if not part or not part[0]:
                        break
                    fh.write(bytes(part[0]))
                    off += cls.BLOB_CHUNK
        except Exception:
            try:
                os.unlink(path)
            except OSError:
                pass
            raise
        return path

    # ── معاينة الفرق (رخيصة: ميتاداتا فقط، لا مرفق يعبر الشبكة) ────────────
    BOUNDARY_DIR = 'var/legacy_merge'

    @classmethod
    def boundary_path(cls, database):
        """مسار ملفّ حدّ قاعدةٍ بعينها — الحدود لا تُشارَك بين قواعد مختلفة."""
        import os
        from django.conf import settings
        # النقطة مستبعَدة عمداً: اسم القاعدة يأتي من نموذج المستخدم، والإبقاء على
        # النقاط يسمح بأسماء مثل «..» تُربك القراءة وإن لم تخرج من المجلّد.
        safe = re.sub(r'[^A-Za-z0-9_-]', '_', (database or 'source').strip()) or 'source'
        return os.path.join(str(settings.BASE_DIR), *cls.BOUNDARY_DIR.split('/'),
                            f'boundary_{safe}.json')

    @classmethod
    def load_boundary(cls, database, path=None):
        """
        «حدّ» كل جدول: أكبر معرّف كان موجوداً في نسخة المصدر السابقة.

        بدونه لا يمكن تمييز صفٍّ **استجدّ فعلاً** عن صفٍّ **قديم لم يُستورد قطّ**
        (مثل تعميم مكرَّر تُرك عمداً). الأول يُضاف، والثاني يجب أن يراه المالك
        قبل أن يُنشئ نسخةً ثانيةً من كتابٍ عنده. يُلتقَط قبل أي استعادة تمحو النسخة.

        يُعيد None إن لم يوجد ملفّ لهذه القاعدة — وعندها لا وجود لـ«مزامنة سابقة»
        نقيس عليها، فكل صفٍّ غير مطالَب **جديد** (حالة الاستيراد الأوّل).
        """
        import json
        p = path or cls.boundary_path(database)
        try:
            with open(p, encoding='utf-8') as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            return None
        tables = data.get('tables') or {}
        return {t: int(v.get('max_id') or 0) for t, v in tables.items()}

    def capture_boundary(self, note='', path=None):
        """
        يلتقط حدّ كل جدول في المصدر **الحالي** ويكتبه إلى القرص.

        يُشغَّل بعد كل مزامنة ناجحة: عندها يصبح «كل ما في المصدر الآن مستوردٌ
        عندي»، فأي معرّف أكبر لاحقاً هو مستجدٌّ يقيناً. والأهمّ أن يُشغَّل **قبل**
        أي `RESTORE ... WITH REPLACE` تمحو النسخة التي يُقاس عليها.

        بلا هذه الدالة كان الحدّ يُكتب يدوياً — أي لا يُعاد توليده، وحدٌّ لا
        يُعاد توليده أسوأ من غيابه لأن الدمج يثق برقمٍ قد يكون بائتاً.
        """
        import json
        import os
        from datetime import date, datetime

        from .models import Book

        self.connect()
        cur = self._conn.cursor()
        cur.execute("SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_TYPE='BASE TABLE'")
        all_tables = sorted(t for (t,) in cur.fetchall()
                            if re.match(r'^(II|IO|OI|OO)MAIL_\d{4}$', t))

        snap = {}
        for tbl in all_tables:
            p = tbl[:2]
            cur.execute(f"SELECT COUNT(*), MAX({p}ID), MIN({p}ID), MAX({p}DATE) FROM [{tbl}]")
            n, mx, mn, mdate = cur.fetchone()
            snap[tbl] = {
                'rows': int(n or 0),
                'max_id': int(mx) if mx is not None else 0,
                'min_id': int(mn) if mn is not None else 0,
                'max_date': mdate.isoformat() if isinstance(mdate, (date, datetime)) else None,
            }
        self.close()

        payload = {
            'database': self.database,
            'captured_at': timezone.now().isoformat(),
            'note': note,
            'tables': snap,
            'source_rows_total': sum(v['rows'] for v in snap.values()),
            'books_in_lettersys': Book.objects.count(),
            'books_stamped': Book.objects.exclude(source_ref='').count(),
        }

        out = path or self.boundary_path(self.database)
        os.makedirs(os.path.dirname(out), exist_ok=True)
        # كتابة ذرّية: قارئٌ متزامن (معاينة الفرق مثلاً) كان قد يقرأ ملفاً منقوصاً
        # فتُفقَد بعض الجداول من الخريطة، فتنقلب صفوفها من «موقوف» إلى «جديد».
        # نكتب إلى ملفٍ جانبي ثم نستبدل — os.replace ذرّية على ويندوز ولينكس.
        tmp = out + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, out)
        payload['path'] = out
        return payload

    def delta(self, progress_cb=None, boundary=None):
        """
        يُجيب «ما الجديد في المصدر؟» دون نقل بايت واحد من المرفقات.

        يعتمد `source_ref` المختوم على الكتب الحالية: كل صفّ مصدر معرّفه
        `{الجدول}#{ID}`، فالمقارنة مجرّد فرق مجموعتين. التكلفة استعلام
        `SELECT {P}ID, DATALENGTH({P}FILE)` لكل جدول — يجيبه الخادم من الميتاداتا.

        الصفوف غير المطالَبة تُقسَم قسمين بحسب الحدّ المحفوظ:
          • معرّفه > الحدّ  ⇒ **جديد**    — استجدّ بعد آخر مزامنة، يُضاف بثقة.
          • معرّفه ≤ الحدّ  ⇒ **موقوف**   — كان موجوداً ولم يُستورد، يحتاج قراراً.
        بلا ملف حدّ (استيراد أوّل، أو قاعدة مصدر جديدة): لا مزامنة سابقة نقيس
        عليها، فكل غير المطالَب **جديد** — وهو ما ينفّذه `run()` أيضاً، فلا
        تتناقض المعاينة مع التنفيذ.
        """
        from .models import Book

        self.connect()
        cur = self._conn.cursor()
        cur.execute("SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_TYPE='BASE TABLE'")
        all_tables = {r[0] for r in cur.fetchall()}
        years = sorted({m.group(2) for t in all_tables
                        if (m := re.match(r'^(II|IO|OI|OO)MAIL_(\d{4})$', t))})
        if self.years:
            years = [y for y in years if y in self.years]

        known = set(Book.objects.exclude(source_ref='').values_list('source_ref', flat=True))
        if boundary is None:
            boundary = self.load_boundary(self.database)
        has_boundary = boundary is not None

        tables, totals = [], defaultdict(int)
        for prefix, kind, _is_out in TABLE_KINDS:
            for y in years:
                tbl = f"{prefix}MAIL_{y}"
                if tbl not in all_tables:
                    continue
                if progress_cb:
                    progress_cb(f'فحص {tbl}…')
                try:
                    cur.execute(f"SELECT {prefix}ID, DATALENGTH({prefix}FILE) FROM [{tbl}]")
                except Exception as e:
                    logger.warning('delta: skip %s: %s', tbl, e)
                    continue
                rows = cur.fetchall()
                # بلا حدّ محفوظ: لا مزامنة سابقة ⇒ كل غير مطالَب جديد (الحدّ = صفر)
                limit = boundary.get(tbl, 0) if has_boundary else 0

                new_ids, new_bytes = [], 0
                held_ids, held_bytes = [], 0
                for sid, blen in rows:
                    if f"{tbl}#{sid}" in known:
                        continue
                    if sid > limit:
                        new_ids.append(sid)
                        new_bytes += int(blen or 0)
                    else:
                        held_ids.append(sid)
                        held_bytes += int(blen or 0)

                if not rows:
                    continue
                tables.append({
                    'table': tbl, 'kind': kind, 'year': y,
                    'rows': len(rows),
                    'known': len(rows) - len(new_ids) - len(held_ids),
                    'new': len(new_ids), 'new_bytes': new_bytes,
                    'held': len(held_ids), 'held_bytes': held_bytes,
                    'boundary_id': limit,
                    'first_new_id': min(new_ids) if new_ids else None,
                    'last_new_id': max(new_ids) if new_ids else None,
                })
                totals['rows'] += len(rows)
                totals['known'] += len(rows) - len(new_ids) - len(held_ids)
                totals['new'] += len(new_ids)
                totals['new_bytes'] += new_bytes
                totals['held'] += len(held_ids)
                totals['held_bytes'] += held_bytes

        # كتب عندنا بلا نظير في المصدر (ما أدخلتَه داخل التطبيق) — للعلم فقط، لا تُمسّ
        totals['app_only'] = Book.objects.filter(source_ref='').count()
        self.close()
        return {'years': years, 'tables': tables, 'totals': dict(totals),
                'has_boundary': has_boundary}

    # ── التشغيل (دمج ذكي — لا يحذف شيئاً) ────────────────────────────────
    def run(self, created_by, restore_files=True, mode='skip_existing', progress_cb=None,
            boundary=None, include_held=False):
        """
        ينفّذ الاستعادة بمنطق upsert.
        mode:
          'fresh'           — مسموح فقط إن كان النظام فارغاً → ينشئ كل شيء.
          'skip_existing'   — يُنشئ الجديد، يتخطّى ما له source_ref موجود (الافتراضي الآمن).
          'update_existing' — يُنشئ الجديد، ويُحدّث حقول الموجود من المصدر.

        الصفوف «الموقوفة» (غير مطالَبة ومعرّفها ≤ حدّ المصدر المحفوظ) **لا تُستورَد**
        افتراضياً: وجودها قديم وعدم استيرادها سابقاً مقصود غالباً، فإضافتها تلقائياً
        تُنشئ نسخةً ثانية من كتابٍ موجود. `include_held=True` يتجاوز ذلك بقرارٍ صريح.

        لا يحذف أي كتاب أبداً. الكتب المُضافة داخل التطبيق (source_ref فارغ) لا تُلمَس.
        """
        from .models import Book

        if mode == 'fresh' and Book.objects.exists():
            return {'aborted': True, 'reason': 'وضع "نظام جديد" لا يعمل والنظام يحوي كتباً. استخدم "تخطّي الموجود" أو "تحديث الموجود".'}

        # وضع «نظام جديد» يستورد كل شيء بحكم تعريفه: لا مزامنة سابقة ليُقاس عليها
        # حدّ، وتطبيقُه هنا كان يوقف كل صفٍّ معرّفه ≤ الحدّ فيُنتج استيراداً فارغاً.
        if mode == 'fresh':
            boundary = None
        elif boundary is None:
            boundary = self.load_boundary(self.database)

        self.connect()
        cur = self._conn.cursor()
        cur.execute("SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_TYPE='BASE TABLE'")
        all_tables = {r[0] for r in cur.fetchall()}
        years = sorted({m.group(2) for t in all_tables if (m := re.match(r'^(II|IO|OI|OO)MAIL_(\d{4})$', t))})
        if self.years:
            years = [y for y in years if y in self.years]

        # فهرس المطابقة الوحيد: source_ref → book.id.
        # كان هنا فهرس ثانٍ يتبنّى الكتب بمفتاح (kind, legacy_number). حُذف عمداً:
        # `legacy_number` للوارد هو رقم الجهة المرسِلة لا رقمنا، وهو مكرَّر بطبيعته —
        # قياساً على البيانات الفعلية كان ملتبساً في 27.6% من الكتب، فيربط الصفّ
        # بكتابٍ خاطئ ربطاً صامتاً. البديل الرصين: أمر `reconcile_legacy_source`
        # يختم source_ref مرّةً واحدة بمفتاحٍ فريد ومُتحقَّق منه بالبصمات.
        by_sref = dict(Book.objects.exclude(source_ref='').values_list('source_ref', 'id'))

        summary = defaultdict(int)

        # الكتب المختومة التي لا مرفق لها — لملء الناقص دون جرّ بقيّة الجداول.
        # `with_file` يُمرَّر للأسفل ليُغني عن استعلام exists() لكل صفّ (١١ ألف
        # استعلام) — نفس الحقيقة، استعلامٌ واحد.
        need_file, with_file = set(), set()
        if restore_files:
            from .models import Attachment
            with_file = set(Attachment.objects.filter(is_deleted=False)
                            .values_list('book_id', flat=True))
            need_file = {sref for sref, bid in by_sref.items() if bid not in with_file}

        blob_cur = self._conn.cursor()   # مؤشّر مستقلّ لسحب المرفق مقطّعاً

        for prefix, kind, is_out in TABLE_KINDS:
            for y in years:
                tbl = f"{prefix}MAIL_{y}"
                if tbl not in all_tables:
                    continue

                # ── المرحلة ١: المعرّفات وأطوال المرفقات فقط ──
                # DATALENGTH يجيبه الخادم من الميتاداتا بلا نقل بايت، وأخذُه هنا
                # يوفّر استعلاماً لكل صفّ لاحقاً، ويكشف الصفوف الفارغة فلا نستدعي
                # لها مسار المرفق أصلاً.
                try:
                    cur.execute(f"SELECT {prefix}ID, DATALENGTH({prefix}FILE) "
                                f"FROM [{tbl}] ORDER BY {prefix}ID")
                except Exception as e:
                    logger.warning("legacy_restore: skip %s: %s", tbl, e)
                    continue
                blob_len = {r[0]: int(r[1] or 0) for r in cur.fetchall()}
                limit = None if boundary is None else int(boundary.get(tbl, 0))

                todo = []
                for sid in blob_len:
                    sref = f"{tbl}#{sid}"
                    if sref in by_sref:
                        if mode == 'update_existing' or sref in need_file:
                            todo.append(sid)
                        else:
                            summary['skipped'] += 1
                        continue
                    if limit is not None and not include_held and sid <= limit:
                        summary['held'] += 1
                        continue
                    todo.append(sid)

                if progress_cb:
                    progress_cb(f"{tbl}: {len(blob_len)} صفّاً، {len(todo)} يحتاج معالجة")
                if not todo:
                    continue

                # ── المرحلة ٢: الحقول النصّية للمطلوب فقط، دفعاتٍ صغيرة ──
                if is_out:
                    cols = [f"{prefix}ID", f"{prefix}NUM", f"{prefix}DATE", f"{prefix}SUB",
                            f"{prefix}TO", f"{prefix}CLAS", f"{prefix}STAT", f"{prefix}SUBROOT",
                            f"{prefix}ACTION", f"{prefix}NOTE"]
                else:
                    cols = [f"{prefix}ID", f"{prefix}WID", f"{prefix}NUM", f"{prefix}DATE", f"{prefix}CND",
                            f"{prefix}SUB", f"{prefix}FROM", f"{prefix}CLAS", f"{prefix}STAT", f"{prefix}SUBROOT",
                            f"{prefix}ACTION", f"{prefix}NOTE"]
                # {P}FILE لا يُطلَب هنا أبداً — يُسحب مقطّعاً عند الحاجة فقط.

                done = 0
                for i in range(0, len(todo), self.SCALAR_BATCH):
                    chunk = todo[i:i + self.SCALAR_BATCH]
                    marks = ','.join('?' * len(chunk))
                    cur.execute(
                        f"SELECT {', '.join(cols)} FROM [{tbl}] "
                        f"WHERE {prefix}ID IN ({marks}) ORDER BY {prefix}ID", *chunk)
                    colnames = [d[0] for d in cur.description]
                    for row in cur.fetchall():
                        rd = dict(zip(colnames, row))
                        src_id = rd.get(f"{prefix}ID")
                        n = blob_len.get(src_id, 0)
                        rd['_blob'] = (
                            (lambda t=tbl, p=prefix, i=src_id, ln=n:
                             self._stream_blob(blob_cur, t, p, i, total=ln))
                            if n else None)
                        self._upsert_row(rd, prefix, kind, is_out, int(y), created_by,
                                         restore_files, mode, f"{tbl}#{src_id}", by_sref,
                                         summary, has_file=with_file)
                    done += len(chunk)
                    if progress_cb:
                        progress_cb(f"{tbl}: {done}/{len(todo)}")

        # لا مرحلة «فكّ تكرارات» بعد الاستيراد: كانت تمسح كل الكتب لا المستوردة فقط،
        # فتُعيد ترقيم كتبٍ أدخلها المستخدم بيده. التفرّد تحرسه قيود قاعدة البيانات،
        # وإعادة البناء على سلسلة الختم عمل أمرٍ مستقلّ يُعايَن ثم يُعتمَد
        # (`rebase_book_numbers`، معاينةٌ افتراضاً وله مسار `--undo`).
        self.close()
        return dict(summary)

    def _upsert_row(self, rd, prefix, kind, is_out, year, created_by, restore_files,
                    mode, source_ref, by_sref, summary, has_file=None):
        from .models import Book, Attachment

        num = str(rd.get(f"{prefix}NUM") or '').strip()
        title = (rd.get(f"{prefix}SUB") or '').strip() or 'بدون عنوان'
        bdate, sdate = _legacy_dates(rd, prefix, is_out)
        clas = (rd.get(f"{prefix}CLAS") or '').strip()
        stat = rd.get(f"{prefix}STAT")
        note = (rd.get(f"{prefix}NOTE") or '').strip()
        action = (rd.get(f"{prefix}ACTION") or '').strip()
        margin = ' | '.join(p for p in (note, (f"الإجراء: {action}" if action else '')) if p)
        subroot = rd.get(f"{prefix}SUBROOT")

        # ── رقم القيد ──
        # مصدر رقمنا مُثبَت بالقياس: الوارد فيه عمودان — `WID` سلسلةٌ كثيفة
        # (رقم ختمنا) و`NUM` مبعثر لأنّه رقم الجهة المرسِلة؛ والصادر بلا عمود
        # `WID` أصلاً فرقمنا في `NUM`. والصيغة من `numbering`: سجلّ 2026 فما بعد
        # ⇒ رقم مجرّد يمضي في السلسلة اللانهائية، وما قبله ⇒ موسوم بسنة سجلّه.
        if not is_out:
            wid_s = str(rd.get(f"{prefix}WID") or '').strip()
            our_number = ('' if numbering.is_no_number(wid_s) or not wid_s.isdigit()
                          else numbering.format_for_ledger_year(int(wid_s), year))
            sender_number = num
            from_name = (rd.get(f"{prefix}FROM") or '').strip()
        elif kind == 'outgoing_internal':
            our_number = ('' if numbering.is_no_number(num) or not num.isdigit()
                          else numbering.format_for_ledger_year(int(num), year))
            sender_number = ''
            from_name = ''
        else:
            # الصادر الخارجي: رقمه من مكتب السيد المدير العام — يُخزَّن كما هو
            # بلا سنةٍ ولا بادئة، ولا سلسلة لنا فيه، ويجوز تكراره.
            our_number = '' if numbering.is_no_number(num) else num
            sender_number = ''
            from_name = ''

        # المنطق الموحَّد: 'pending' من المصدر القديم ⇒ نشط (is_archived=False)، غيره ⇒ مؤرشف
        legacy_status = _norm_status(stat, bdate)
        is_archived_value = (legacy_status != 'pending')

        # ── إيجاد كتاب موجود: بمرجع المصدر وحده ──
        # لا تبنّي تخميني. صفٌّ بلا source_ref مطابق = صفٌّ جديد، والكتب التي لا
        # يعرفها المصدر تبقى كما هي. شغّل `reconcile_legacy_source` قبل الدمج
        # ليُختَم المرجع على ما استُورد سابقاً.
        existing = None
        bid = by_sref.get(source_ref)
        if bid:
            existing = Book.objects.filter(id=bid).first()

        if existing is not None:
            if mode == 'skip_existing':
                # فقط نضمن أن source_ref مضبوط (تبنّي)، ونملأ الناقص فقط — لا نطمس
                changed = []
                if not existing.source_ref:
                    existing.source_ref = source_ref; changed.append('source_ref')
                if not existing.sender_number and sender_number:
                    existing.sender_number = sender_number; changed.append('sender_number')
                if not existing.document_type and clas:
                    existing.document_type = clas; changed.append('document_type')
                if changed:
                    existing.save(update_fields=changed)
                # جهات/مرفق ناقصة فقط
                self._fill_missing(existing, is_out, from_name, subroot, rd, prefix, restore_files,
                                   our_number, summary, has_file)
                summary['skipped'] += 1
                return
            # mode == 'update_existing' → تحديث الحقول الأساسية (نحترم: لا نطمس what app added نصاً حراً مثل margin إن كان أطول)
            with transaction.atomic():
                existing.source_ref = source_ref
                # رقم القيد لا يُعاد كتابته من المصدر أبداً: النظام هو مرجع الترقيم،
                # والمصدر لا يعرف الصيغة الدائمة. إعادة الكتابة كانت تصطدم بقيد
                # التفرّد وتُبطل عمل توحيد الترقيم.
                existing.sender_number = sender_number or existing.sender_number
                existing.title = title or existing.title
                existing.document_type = clas or existing.document_type
                if bdate:
                    existing.date = bdate
                if sdate:
                    existing.sender_date = sdate
                if 'سري' in (clas or ''):
                    existing.secret_level = 'secret'
                # حالة الأرشفة لا تُؤخَذ من المصدر: عمود STAT القديم إشارة ميتة
                # (Book.save يحسم is_archived من due_date)، وكتابتها كانت تُلغي
                # متابعةً فعّالة أنشأها المستخدم داخل التطبيق.
                # margin: ندمج (لا نطمس) — نضيف ما في المصدر إن لم يكن موجوداً
                if margin and margin not in (existing.margin or ''):
                    existing.margin = (existing.margin + ' | ' + margin).strip(' |') if existing.margin else margin
                existing.save()
                # جهات: نُعيد ضبط المستلمة من المصدر، ونضيف المصدِّرة
                self._set_entities(existing, is_out, from_name, subroot, rd, prefix, replace_receiving=True)
                self._attach_if_missing(existing, rd, prefix, restore_files, our_number, summary, has_file)
            summary['updated'] += 1
            return

        # ── إنشاء جديد ──
        with transaction.atomic():
            book = Book.objects.create(
                our_number=our_number,
                sender_number=sender_number,
                title=title,
                document_type=clas,
                date=bdate or timezone.localdate(),
                sender_date=sdate,
                secret_level='secret' if 'سري' in (clas or '') else 'normal',
                kind=kind,
                margin=margin,
                is_archived=is_archived_value,
                created_by=created_by,
                legacy_number=num,
                source_ref=source_ref,
            )
            self._set_entities(book, is_out, from_name, subroot, rd, prefix, replace_receiving=True)
            self._attach_if_missing(book, rd, prefix, restore_files, our_number, summary, has_file)
        summary['books'] += 1
        summary[f'books_{kind}'] += 1

    # ── مساعدات الجهات والمرفقات ───────────────────────────────────────────
    def _set_entities(self, book, is_out, from_name, subroot, rd, prefix, replace_receiving=True):
        """
        الوارد:  issuing  = FROM (المرسِل)        |  receiving = SUBROOT (الارتباط — جهتنا المستلمة)
        الصادر:  receiving = TO   (المُرسَل إليه)  |  issuing   = SUBROOT (الارتباط — جهتنا المُعِدّة)
        """
        def ents_of(names):
            return [x for x in (self._get_entity(n) for n in names) if x]

        if not is_out:
            e = self._get_entity(from_name)
            if e:
                book.issuing_entities.add(e)
            recv = ents_of(_parse_entity_names(subroot))
        else:
            recv = ents_of(_parse_entity_names(rd.get(f"{prefix}TO")))
            link = ents_of(_parse_entity_names(subroot))
            if link:
                book.issuing_entities.add(*link)
        if recv:
            if replace_receiving:
                book.receiving_entities.set(recv)
            else:
                book.receiving_entities.add(*recv)

    def _fill_missing(self, book, is_out, from_name, subroot, rd, prefix, restore_files,
                      our_number, summary, has_file=None):
        if not book.issuing_entities.exists() or not book.receiving_entities.exists():
            self._set_entities(book, is_out, from_name, subroot, rd, prefix,
                               replace_receiving=not book.receiving_entities.exists())
        self._attach_if_missing(book, rd, prefix, restore_files, our_number, summary, has_file)

    def _attach_if_missing(self, book, rd, prefix, restore_files, our_number, summary, has_file=None):
        """
        يُضيف مرفق الصفّ إن كان الكتاب بلا مرفق. لا يستبدل مرفقاً موجوداً أبداً.

        المرفق يصل عبر `rd['_blob']` — دالةٌ تسحبه إلى ملفٍ مؤقّت مقطّعاً، فلا
        يُحجَز حجم الـPDF في الذاكرة. الملف المؤقّت يُحذف دائماً.

        `has_file` = مجموعة معرّفات الكتب التي لها مرفق، محسوبة باستعلامٍ واحد في
        `run()`. تمريرها يُغني عن استعلام exists() لكل صفّ (١١ ألف استعلام).
        """
        from django.core.files import File

        from .models import Attachment
        if not restore_files:
            return

        if has_file is not None:
            if book.id in has_file:
                return
        elif Attachment.objects.filter(book=book, is_deleted=False).exists():
            return

        fetch = rd.get('_blob')
        if not callable(fetch):
            return

        from .attachment_service import _sniff_document_kind

        tmp_path = None
        try:
            tmp_path = fetch()
            if not tmp_path:
                return

            # الامتداد من **توقيع البايتات** لا من الافتراض: عمود {P}FILE قد يحوي
            # صورة ممسوحة (TIFF/JPEG) لا PDF، وتسميتها .pdf تُنتج ملفاً لا يفتحه
            # العارض. نستعمل نفس المُستشعر الذي تعتمده بوّابة الرفع.
            with open(tmp_path, 'rb') as fh:
                kind = _sniff_document_kind(fh.read(32))
            if kind is None:
                logger.warning('legacy_restore: unrecognised blob for book %s — skipped', book.id)
                summary['file_unknown_type'] += 1
                return

            src = rd.get(f"{prefix}ID")
            fname = f"{our_number or 'book'}_{prefix}{src}.{kind}"
            att = Attachment(book=book)
            with open(tmp_path, 'rb') as fh:
                att.file.save(fname, File(fh), save=True)
            summary['files'] += 1
            if kind != 'pdf':
                summary['files_non_pdf'] += 1
            if has_file is not None:
                has_file.add(book.id)   # الكتاب صار له مرفق — لا تُعِد المحاولة
        except Exception as e:
            logger.warning("legacy_restore: file save failed for book %s: %s", book.id, e)
            summary['file_errors'] += 1
        finally:
            if tmp_path:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

