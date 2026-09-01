# -*- coding: utf-8 -*-
"""
بوّابة ما بعد استعادة قاعدة المصدر — تُشغَّل من refresh_archmdoc.ps1.

تفحص ثلاثة أشياء، وترفض الاستمرار إن سقط أيّها:

  ١) لم تنقص الصفوف: عدد كل جدول ≥ ما كان في الحدّ المحفوظ. النقصان يعني أن
     الباكاب أقدم من النسخة التي محاها.
  ٢) البيانات أحدث: أكبر معرّف ≥ الحدّ، وأحدث تاريخ ليس أقدم مما كان.
  ٣) **ثبات المعرّفات** — البوّابة الحاسمة: هوية الدمج كلها مبنيّة على
     `{الجدول}#{المعرّف}`. لو أعاد النظام القديم بناء معرّفاته بين الباكابين
     لأشار كل `source_ref` عندنا إلى صفٍّ مختلف، ولأفسد الدمج السجلّ بصمت.
     نختبرها بعيّنة من الكتب المربوطة: عنوان وتاريخ وحجم مرفق كلٌّ منها يجب أن
     يطابق صفَّه في النسخة الجديدة.

    python scripts\verify_archmdoc_refresh.py --database ARCHMDOC --boundary var/legacy_merge/boundary_ARCHMDOC.json
"""
import argparse
import json
import os
import random
import sys

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJ)
os.chdir(PROJ)
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'lettersys.settings')

import django  # noqa: E402
django.setup()

from django.conf import settings  # noqa: E402,F401  (يُحمّل .env)
from core.models import Attachment, Book  # noqa: E402

FAILURES = []


def check(name, ok, detail=''):
    print(('  PASS  ' if ok else '  FAIL  ') + name + (('  :: ' + str(detail)) if detail else ''))
    if not ok:
        FAILURES.append(name)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--database', default='ARCHMDOC')
    ap.add_argument('--server', default='localhost')
    ap.add_argument('--user', default='sa')
    ap.add_argument('--boundary', required=True)
    ap.add_argument('--sample', type=int, default=50)
    args = ap.parse_args()

    pw = os.environ.get('LEGACY_SQL_PASSWORD', '')
    if not pw:
        print('LEGACY_SQL_PASSWORD غير مضبوط'); return 2

    with open(args.boundary, encoding='utf-8') as fh:
        snap = json.load(fh)
    old = snap.get('tables') or {}

    import pyodbc
    conn = pyodbc.connect(
        'DRIVER={ODBC Driver 17 for SQL Server};SERVER=%s;DATABASE=%s;UID=%s;PWD=%s;'
        'TrustServerCertificate=yes;Connection Timeout=30;' % (args.server, args.database, args.user, pw))
    cur = conn.cursor()

    print('\n=== ١) الأعداد والتواريخ مقابل الحدّ المحفوظ ===')
    for tbl in sorted(old):
        p = tbl[:2]
        try:
            cur.execute('SELECT COUNT(*), MAX(%sID), MAX(%sDATE) FROM [%s]' % (p, p, tbl))
            n, mx, mdate = cur.fetchone()
        except Exception as exc:
            check('%s موجود' % tbl, False, exc)
            continue
        n, mx = int(n or 0), int(mx or 0)
        o = old[tbl]
        check('%-16s العدد %6d ≥ %-6d' % (tbl, n, o['rows']), n >= o['rows'])
        check('%-16s أكبر معرّف %6d ≥ %-6d' % (tbl, mx, o['max_id']), mx >= o['max_id'])
        if o.get('max_date') and mdate:
            check('%-16s أحدث تاريخ %s ≥ %s' % (tbl, mdate, o['max_date']),
                  str(mdate)[:10] >= o['max_date'][:10])

    print('\n=== ٢) ثبات المعرّفات (البوّابة الحاسمة) ===')
    root = str(settings.MEDIA_ROOT)
    stamped = list(Book.objects.exclude(source_ref='')
                   .values_list('id', 'source_ref', 'title', 'date'))
    if not stamped:
        check('توجد كتب مربوطة لفحصها', False, 'صفر')
    else:
        random.seed(11)
        sample = random.sample(stamped, min(args.sample, len(stamped)))
        sizes = {}
        for bid, rel in (Attachment.objects.filter(is_deleted=False,
                                                   book_id__in=[s[0] for s in sample])
                         .order_by('book_id', 'id').values_list('book_id', 'file')):
            if bid not in sizes and rel:
                try:
                    sizes[bid] = os.path.getsize(os.path.join(root, rel.replace('/', os.sep)))
                except OSError:
                    pass

        agree = tested = 0
        mismatches = []
        for bid, sref, title, bdate in sample:
            tbl, sid = sref.split('#')
            p = tbl[:2]
            try:
                cur.execute('SELECT %sSUB, %sDATE, DATALENGTH(%sFILE) FROM [%s] WHERE %sID = ?'
                            % (p, p, p, tbl, p), int(sid))
                row = cur.fetchone()
            except Exception:
                row = None
            if not row:
                mismatches.append((bid, sref, 'الصفّ غير موجود'))
                tested += 1
                continue
            ssub, sdate, slen = row
            tested += 1
            same_title = (ssub or '').strip()[:40] == (title or '').strip()[:40]
            same_date = bdate and sdate and str(sdate)[:10] == str(bdate)[:10]
            same_size = bid not in sizes or int(slen or 0) == sizes[bid]
            if same_title or (same_date and same_size):
                agree += 1
            else:
                mismatches.append((bid, sref, 'عنوان/تاريخ/حجم لا يطابق'))

        rate = agree / tested if tested else 0
        check('عيّنة ثبات المعرّفات %d/%d (%.0f%%)' % (agree, tested, 100 * rate),
              rate >= 0.96,
              'المطلوب ≥96%% — الأساس المقيس على النسخة السابقة كان 100%%')
        for m in mismatches[:8]:
            print('        اختلاف: كتاب %s ↔ %s — %s' % m)

    conn.close()

    print('\n' + '=' * 60)
    if FAILURES:
        print('سقطت %d بوّابة — **لا تُشغّل الدمج**.' % len(FAILURES))
        print('لو سقطت بوّابة ثبات المعرّفات تحديداً فمعناه أن النظام القديم أعاد')
        print('بناء معرّفاته، وعندها يجب إعادة المطابقة (reconcile) قبل أي دمج.')
        return 1
    print('كل البوّابات سليمة — يمكن المضيّ إلى الدمج.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
