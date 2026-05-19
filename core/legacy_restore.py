# -*- coding: utf-8 -*-
"""
محرّك استعادة البيانات من قاعدة بريد قديمة (نوع ARCHMDOC على SQL Server).

البنية المتوقّعة للمصدر:
  جداول: IIMAIL_YYYY (وارد داخلي)، IOMAIL_YYYY (صادر داخلي)،
         OIMAIL_YYYY (وارد خارجي)، OOMAIL_YYYY (صادر خارجي)
  أعمدة الوارد:  {P}ID {P}WID {P}NUM {P}DATE {P}CND {P}SUB {P}FROM {P}CLAS {P}STAT {P}SUBROOT {P}ACTION {P}NOTE {P}FILE
  أعمدة الصادر:  {P}ID {P}NUM {P}DATE {P}SUB {P}TO {P}CLAS {P}STAT {P}SUBROOT {P}ACTION {P}NOTE {P}FILE

التطبيع المطبَّق (نفس منطق الترحيل المعتمد):
  - الوارد:  our_number = YYYY{R}{WID:04d}  (R=1 داخلي، 2 خارجي) — معرّفنا الفريد
             sender_number = NUM  — رقمهم (تكرار مقبول)
             receiving_entities = SUBROOT مفصولاً على "+"  — جهة الارتباط
  - صادر داخلي: our_number = YYYY3{NUM:04d}  — تسلسل فريد يمنحه النظام
  - صادر خارجي: our_number = YYYY4{NUM}  — رقم مكتب المدير العام (عشوائي، تكرار مسموح)
  - document_type = CLAS، التواريخ من DATE/CND، العنوان من SUB، الجهة المصدرة من FROM (للوارد)
  - المرفق من العمود {P}FILE (varbinary → PDF)
"""
import re
import logging
from collections import defaultdict
from datetime import date, datetime

from django.core.files.base import ContentFile
from django.db import transaction
from django.utils import timezone

logger = logging.getLogger(__name__)

REGISTER_CODES = {
    'incoming_internal': '1',
    'incoming_external': '2',
    'outgoing_internal': '3',
    'outgoing_external': '4',
}

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
        self._entity_cache = {}

    # ── الاستعادة من ملف باكاب (.bak أو مضغوط) ──────────────────────────────
    @classmethod
    def restore_from_bak(cls, bak_path, sql_server='localhost', admin_user='sa', admin_password='',
                         created_by=None, restore_files=True, mode='skip_existing', progress_cb=None):
        """
        يستعيد .bak إلى قاعدة SQL Server مؤقتة محلية ثم يستورد منها — دون لمس القاعدة الأصلية.
        - مضغوط (.zip / .7z / .tar.gz): يُفَكّ تلقائياً ويُبحَث عن أول .bak داخله.
        - غير مضغوط (.bak): يُستعمَل مباشرة.
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
            admin_cs = (
                f"DRIVER={{ODBC Driver 17 for SQL Server}};SERVER={sql_server};DATABASE=master;"
                f"UID={admin_user};PWD={admin_password};TrustServerCertificate=yes;Connection Timeout=30;"
            )
            conn = pyodbc.connect(admin_cs, autocommit=True)
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

            # مسار بيانات SQL Server الافتراضي (قابل للكتابة من حساب الخدمة)
            try:
                cur.execute("SELECT CAST(SERVERPROPERTY('InstanceDefaultDataPath') AS NVARCHAR(512))")
                data_dir = (cur.fetchone()[0] or '').strip()
            except Exception:
                data_dir = ''
            if not data_dir:
                data_dir = os.path.dirname(actual_bak)

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
    def _conn_str(self):
        return (
            f"DRIVER={{ODBC Driver 17 for SQL Server}};"
            f"SERVER={self.server};DATABASE={self.database};"
            f"UID={self.username};PWD={self.password};"
            f"TrustServerCertificate=yes;Connection Timeout=15;"
        )

    def connect(self):
        import pyodbc
        self._conn = pyodbc.connect(self._conn_str())
        return self._conn

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
    def _get_entity(self, name):
        from .models import Entity
        name = (name or '').strip()
        if not name or _GARBAGE_RE.match(name):
            return None
        key = name.lower()
        if key in self._entity_cache:
            return self._entity_cache[key]
        e = Entity.objects.filter(name__iexact=name).first()
        if not e:
            e = Entity.objects.create(name=name, etype='both', is_active=True)
        self._entity_cache[key] = e
        return e

    # ── التشغيل (دمج ذكي — لا يحذف شيئاً) ────────────────────────────────
    def run(self, created_by, restore_files=True, mode='skip_existing', progress_cb=None):
        """
        ينفّذ الاستعادة بمنطق upsert.
        mode:
          'fresh'           — مسموح فقط إن كان النظام فارغاً → ينشئ كل شيء.
          'skip_existing'   — يُنشئ الجديد، يتخطّى ما له source_ref موجود (الافتراضي الآمن).
          'update_existing' — يُنشئ الجديد، ويُحدّث حقول الموجود من المصدر.
        لا يحذف أي كتاب أبداً. الكتب المُضافة داخل التطبيق (source_ref فارغ ولا تطابق) لا تُلمَس.
        """
        from .models import Book

        if mode == 'fresh' and Book.objects.exists():
            return {'aborted': True, 'reason': 'وضع "نظام جديد" لا يعمل والنظام يحوي كتباً. استخدم "تخطّي الموجود" أو "تحديث الموجود".'}

        self.connect()
        cur = self._conn.cursor()
        cur.execute("SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_TYPE='BASE TABLE'")
        all_tables = {r[0] for r in cur.fetchall()}
        years = sorted({m.group(2) for t in all_tables if (m := re.match(r'^(II|IO|OI|OO)MAIL_(\d{4})$', t))})
        if self.years:
            years = [y for y in years if y in self.years]

        # فهارس المطابقة:
        #  1) source_ref → book.id  (الكتب المُستورَدة سابقاً بهذا المحرّك)
        #  2) (kind, legacy_number) → [book.ids بدون source_ref]  (تبنّي الكتب المُستورَدة قديماً)
        by_sref = dict(Book.objects.exclude(source_ref='').values_list('source_ref', 'id'))
        by_legacy_orphan = defaultdict(list)
        for bid, k, ln in Book.objects.filter(source_ref='').exclude(legacy_number='').values_list('id', 'kind', 'legacy_number'):
            by_legacy_orphan[(k, ln)].append(bid)
        adopted = set()

        summary = defaultdict(int)

        for prefix, kind, is_out in TABLE_KINDS:
            reg = REGISTER_CODES[kind]
            for y in years:
                tbl = f"{prefix}MAIL_{y}"
                if tbl not in all_tables:
                    continue
                if is_out:
                    cols = [f"{prefix}ID", f"{prefix}NUM", f"{prefix}DATE", f"{prefix}SUB",
                            f"{prefix}TO", f"{prefix}CLAS", f"{prefix}STAT", f"{prefix}SUBROOT",
                            f"{prefix}ACTION", f"{prefix}NOTE"]
                else:
                    cols = [f"{prefix}ID", f"{prefix}WID", f"{prefix}NUM", f"{prefix}DATE", f"{prefix}CND",
                            f"{prefix}SUB", f"{prefix}FROM", f"{prefix}CLAS", f"{prefix}STAT", f"{prefix}SUBROOT",
                            f"{prefix}ACTION", f"{prefix}NOTE"]
                if restore_files:
                    cols.append(f"{prefix}FILE")
                try:
                    cur.execute(f"SELECT {', '.join(cols)} FROM [{tbl}] ORDER BY {prefix}ID")
                except Exception as e:
                    logger.warning("legacy_restore: skip %s: %s", tbl, e)
                    continue
                colnames = [d[0] for d in cur.description]
                rows = cur.fetchall()
                for row in rows:
                    rd = dict(zip(colnames, row))
                    src_id = rd.get(f"{prefix}ID")
                    source_ref = f"{tbl}#{src_id}"
                    self._upsert_row(rd, prefix, kind, is_out, reg, int(y), created_by,
                                     restore_files, mode, source_ref, by_sref,
                                     by_legacy_orphan, adopted, summary)
                if progress_cb:
                    progress_cb(f"{tbl}: {len(rows)} صف")

        # فك التكرارات داخل السجل الواحد (تكرارات WID/NUM)
        self._dedup_within_register(summary)
        self.close()
        return dict(summary)

    def _upsert_row(self, rd, prefix, kind, is_out, reg, year, created_by, restore_files,
                    mode, source_ref, by_sref, by_legacy_orphan, adopted, summary):
        from .models import Book, Attachment

        num = str(rd.get(f"{prefix}NUM") or '').strip()
        title = (rd.get(f"{prefix}SUB") or '').strip() or 'بدون عنوان'
        bdate = _parse_date(rd.get(f"{prefix}DATE"))
        sdate = _parse_date(rd.get(f"{prefix}CND")) if not is_out else None
        clas = (rd.get(f"{prefix}CLAS") or '').strip()
        stat = rd.get(f"{prefix}STAT")
        note = (rd.get(f"{prefix}NOTE") or '').strip()
        action = (rd.get(f"{prefix}ACTION") or '').strip()
        margin = ' | '.join(p for p in (note, (f"الإجراء: {action}" if action else '')) if p)
        subroot = rd.get(f"{prefix}SUBROOT")

        # رقم القيد
        if not is_out:
            wid_s = str(rd.get(f"{prefix}WID") or '').strip()
            our_number = f"{year}{reg}{int(wid_s):04d}" if wid_s.isdigit() else ''
            sender_number = num
            from_name = (rd.get(f"{prefix}FROM") or '').strip()
        else:
            if kind == 'outgoing_internal':
                our_number = f"{year}{reg}{int(num):04d}" if num.isdigit() else ''
            else:
                our_number = f"{year}{reg}{num}" if num.isdigit() else ((f"{year}{reg}" + re.sub(r'\D', '', num)) if num else '')
            sender_number = ''
            from_name = ''

        # المنطق الموحَّد: 'pending' من المصدر القديم ⇒ نشط (is_archived=False)، غيره ⇒ مؤرشف
        legacy_status = _norm_status(stat, bdate)
        is_archived_value = (legacy_status != 'pending')

        # ── إيجاد كتاب موجود ──
        existing = None
        bid = by_sref.get(source_ref)
        if bid:
            existing = Book.objects.filter(id=bid).first()
        if existing is None:
            # تبنّي كتاب مُستورَد قديماً بنفس (kind, legacy_number==num) ولم يُتبنّى بعد
            for cand_id in by_legacy_orphan.get((kind, num), []):
                if cand_id in adopted:
                    continue
                cb = Book.objects.filter(id=cand_id).first()
                if cb and (not title or (cb.title or '').strip()[:30] == title.strip()[:30] or True):
                    existing = cb
                    adopted.add(cand_id)
                    break

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
                self._fill_missing(existing, is_out, from_name, subroot, rd, prefix, restore_files, our_number, summary)
                summary['skipped'] += 1
                return
            # mode == 'update_existing' → تحديث الحقول الأساسية (نحترم: لا نطمس what app added نصاً حراً مثل margin إن كان أطول)
            with transaction.atomic():
                existing.source_ref = source_ref
                if our_number:
                    existing.our_number = our_number
                    existing.series_no = None
                    existing.version = None
                existing.sender_number = sender_number or existing.sender_number
                existing.title = title or existing.title
                existing.document_type = clas or existing.document_type
                if bdate:
                    existing.date = bdate
                if sdate:
                    existing.sender_date = sdate
                if 'سري' in (clas or ''):
                    existing.secret_level = 'secret'
                existing.is_archived = is_archived_value
                # margin: ندمج (لا نطمس) — نضيف ما في المصدر إن لم يكن موجوداً
                if margin and margin not in (existing.margin or ''):
                    existing.margin = (existing.margin + ' | ' + margin).strip(' |') if existing.margin else margin
                existing.save()
                # جهات: نُعيد ضبط المستلمة من المصدر، ونضيف المصدِّرة
                self._set_entities(existing, is_out, from_name, subroot, rd, prefix, replace_receiving=True)
                self._attach_if_missing(existing, rd, prefix, restore_files, our_number, summary)
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
            self._attach_if_missing(book, rd, prefix, restore_files, our_number, summary)
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

    def _fill_missing(self, book, is_out, from_name, subroot, rd, prefix, restore_files, our_number, summary):
        if not book.issuing_entities.exists() or not book.receiving_entities.exists():
            self._set_entities(book, is_out, from_name, subroot, rd, prefix,
                               replace_receiving=not book.receiving_entities.exists())
        self._attach_if_missing(book, rd, prefix, restore_files, our_number, summary)

    def _attach_if_missing(self, book, rd, prefix, restore_files, our_number, summary):
        from .models import Attachment
        if not restore_files:
            return
        if Attachment.objects.filter(book=book, is_deleted=False).exists():
            return
        blob = rd.get(f"{prefix}FILE")
        if not blob:
            return
        try:
            fname = f"{our_number or 'book'}_{book.id}.pdf"
            att = Attachment(book=book)
            att.file.save(fname, ContentFile(bytes(blob)), save=True)
            summary['files'] += 1
        except Exception as e:
            logger.warning("legacy_restore: file save failed for book %s: %s", book.id, e)

    def _dedup_within_register(self, summary):
        """يحوّل تكرارات our_number (داخل السجل، ليس الخارجي) إلى صيغة مركّبة فريدة."""
        from .models import Book
        from django.db.models import Count
        dups = (Book.objects.values('our_number').annotate(c=Count('id'))
                .filter(c__gt=1).exclude(our_number='').order_by('-c'))
        for d in dups:
            onum = d['our_number']
            sample = Book.objects.filter(our_number=onum).first()
            if sample and sample.kind == 'outgoing_external':
                continue
            bs = list(Book.objects.filter(our_number=onum).order_by('date', 'id'))
            if len(bs) < 2 or len(onum) < 9 or not onum[:4].isdigit():
                continue
            year, regc, base = onum[:4], onum[4], onum[5:9]
            if not base.isdigit():
                continue
            base_i = int(base)
            v = 1
            for i, bk in enumerate(bs):
                if i == 0:
                    continue
                while Book.objects.filter(our_number=f"{year}{regc}{base_i:04d}{v:02d}").exists():
                    v += 1
                bk.our_number = f"{year}{regc}{base_i:04d}{v:02d}"
                bk.series_no = base_i
                bk.version = v
                bk.save(update_fields=['our_number', 'series_no', 'version'])
                v += 1
                summary['dedup_fixed'] += 1
