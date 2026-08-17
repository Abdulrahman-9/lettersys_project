# -*- coding: utf-8 -*-
"""
إعادة بناء أرقام القيد على **سلسلة ختم الوارد** — قرار المالك.

القاعدة
-------
  • رقم الكتاب = الرقم المثبَّت في ختم الوارد على الورقة، وهو عمود `{P}WID`
    للوارد و`{P}NUM` للصادر الداخلي في قاعدة المصدر. (مُتحقَّق بالعين: المصدر
    يقول WID=825 والختم الأزرق على المستند مكتوبٌ فيه ٨٢٥.)

  • **سنة 2026 أساس سلسلة لا نهائية**: أرقامها تُخزَّن مجرّدة، ويمضي العدّاد
    منها إلى ما لا نهاية بلا تصفير سنوي. بعد 2432 يأتي 2433 في 2027 وما بعدها.

  • **2025 وما قبلها تُوسَم بسنة إضافتها**: {السنة}{الرقم}. السبب مقيس —
    الأرقام تكرّرت بين السنتين (2,432 رقماً في الوارد الداخلي وحده)، والوسم
    هو ما يفصلها. والسنة سنةُ **السجلّ** (اسم جدول المصدر) لا تاريخ المستند.

  • **الصادر الخارجي بلا سلسلة**: رقمه من مكتب المدير العام، يُخزَّن كما هو.

  • **كتب التدريب** (بلا صفّ في المصدر) تنتقل إلى فضاء `T` المنفصل فلا تستهلك
    السلسلة، وتُحذف كلّها عند التدشين لأن أصلها موجود في النظام القديم.

آمن بالتصميم
------------
  • معاينة افتراضياً؛ لا يكتب شيئاً دون `--yes`.
  • خريطة CSV بكل تغيير (القديم ← الجديد) تُكتب قبل التنفيذ — وهي طريق الرجوع.
  • الرقم القديم يُحفظ في `legacy_number` إن كان فارغاً.
  • كل الكتابة في معاملة واحدة.

    python manage.py rebase_book_numbers --database ARCHMDOC          # معاينة
    python manage.py rebase_book_numbers --database ARCHMDOC --yes    # تنفيذ

ملاحظة ويندوز: صدّر PYTHONIOENCODING=utf-8 قبل التشغيل.
"""
import csv
import os
import re
from collections import Counter, defaultdict

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from core import numbering as N
from core.legacy_restore import TABLE_KINDS, LegacyRestoreEngine
from core.models import Book, BookNumberReservation, BookSequence

#: عمود رقمِنا في كل سجلّ — مُثبَت بالقياس لا بالحدس.
#  الوارد (II/OI): عمودان — `WID` سلسلةٌ كثيفة 1.00 (رقم ختمنا)، و`NUM` مبعثر
#  (0..228836، كثافة 0.02) لأنّه رقم الجهة المرسِلة. الصادر (IO/OO): لا عمود
#  `WID` أصلاً، و`NUM` هو رقمنا — كثيف 1.00 في الصادر الداخلي، ومبعثر 0.00 في
#  الصادر الخارجي لأنّ رقمه من مكتب المدير العام لا من سلسلتنا.
STAMP_COLUMN = {
    'incoming_internal': 'WID',
    'incoming_external': 'WID',
    'outgoing_internal': 'NUM',
    'outgoing_external': 'NUM',
}

#: «بلا رقم» — استثناءٌ معتمَد يكتبه موظّف السجلّ القديم نصّاً. الكاشف في
#: `numbering` وحده كي لا تتباعد قراءته بين المستورد وإعادة البناء والواجهة.
_is_no_number = N.is_no_number


class Command(BaseCommand):
    help = 'إعادة بناء أرقام القيد على سلسلة ختم الوارد، وعزل كتب التدريب في فضاء T.'

    def add_arguments(self, parser):
        parser.add_argument('--server', default='localhost')
        parser.add_argument('--database', default='ARCHMDOC')
        parser.add_argument('--user', default='sa')
        parser.add_argument('--password', default=None,
                            help='أو عبر متغيّر البيئة LEGACY_SQL_PASSWORD')
        parser.add_argument('--report', default='var/rebase_book_numbers.csv')
        parser.add_argument('--yes', action='store_true', help='تنفيذ فعلي (بدونه: معاينة)')
        parser.add_argument('--undo', metavar='CSV', default=None,
                            help='إرجاع الأرقام إلى ما قبل إعادة البناء من خريطةٍ سابقة')

    # ── قراءة الأرقام المثبَّتة من المصدر ────────────────────────────────────
    def _stamp_numbers(self, engine, w):
        """source_ref → (سنة السجلّ، الرقم المثبَّت كنصّ)."""
        engine.connect()
        cur = engine._conn.cursor()
        cur.execute("SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_TYPE='BASE TABLE'")
        all_tables = {r[0] for r in cur.fetchall()}
        years = sorted({m.group(2) for t in all_tables
                        if (m := re.match(r'^(II|IO|OI|OO)MAIL_(\d{4})$', t))})

        out = {}
        for prefix, kind, _is_out in TABLE_KINDS:
            col = STAMP_COLUMN[kind]
            for y in years:
                tbl = '%sMAIL_%s' % (prefix, y)
                if tbl not in all_tables:
                    continue
                try:
                    cur.execute('SELECT %sID, %s%s FROM [%s]' % (prefix, prefix, col, tbl))
                except Exception as exc:
                    w('  تخطّي %s: %s' % (tbl, str(exc)[:80]))
                    continue
                for sid, raw in cur.fetchall():
                    out['%s#%s' % (tbl, sid)] = (int(y), str(raw or '').strip())
        engine.close()
        return out

    # ── الرجوع ───────────────────────────────────────────────────────────────
    def _undo(self, path, apply_it):
        """يُعيد كل رقم إلى قيمته قبل إعادة البناء، اعتماداً على خريطة CSV."""
        w = self.stdout.write
        if not os.path.exists(path):
            raise CommandError('لا توجد خريطة: %s' % path)

        with open(path, newline='', encoding='utf-8-sig') as fh:
            rows = list(csv.DictReader(fh))
        w('صفوف الخريطة: %s' % f'{len(rows):,}')

        pending, drifted, missing = [], [], []
        for r in rows:
            bid = int(r['book_id'])
            b = Book.objects.filter(id=bid).first()
            if not b:
                missing.append(bid)
                continue
            if b.our_number != r['new_our_number']:
                # الرقم تغيّر بعد إعادة البناء (تحريرٌ يدويّ؟) — لا نطمسه
                drifted.append((bid, b.our_number, r['new_our_number']))
                continue
            pending.append((b, r['old_our_number'], r['is_training'] == '1'))

        w('سيُرجَع : %s' % f'{len(pending):,}')
        w('مُتغيّر بعد إعادة البناء (لن يُمسّ): %d' % len(drifted))
        for d in drifted[:5]:
            w('   كتاب %-6d الآن %-12s بينما الخريطة تتوقّع %s' % d)
        w('غير موجود: %d' % len(missing))

        if not apply_it:
            w(self.style.WARNING('معاينة رجوع فقط — أضِف --yes للتنفيذ.'))
            return

        with transaction.atomic():
            for b, old, was_training in pending:
                fields = ['our_number']
                b.our_number = old
                if was_training and b.is_training:
                    b.is_training = False
                    fields.append('is_training')
                b.save(update_fields=fields)
        w(self.style.SUCCESS('أُرجع %s رقماً.' % f'{len(pending):,}'))

    def handle(self, *args, **options):
        w = self.stdout.write
        if options['undo']:
            return self._undo(options['undo'], options['yes'])

        password = options['password'] or os.environ.get('LEGACY_SQL_PASSWORD', '')
        if not password:
            raise CommandError('كلمة السرّ مطلوبة: --password أو LEGACY_SQL_PASSWORD.')

        engine = LegacyRestoreEngine(options['server'], options['database'],
                                     options['user'], password)
        w('=' * 78)
        w('جارٍ قراءة الأرقام المثبَّتة من المصدر…')
        try:
            stamps = self._stamp_numbers(engine, w)
        except Exception as exc:
            raise CommandError('تعذّرت قراءة المصدر: %s' % exc)
        w('صفوف المصدر: %s' % f'{len(stamps):,}')

        books = list(Book.objects.order_by('id').values_list(
            'id', 'our_number', 'kind', 'source_ref', 'legacy_number', 'date'))
        w('كتب النظام : %s' % f'{len(books):,}')

        # ── بناء الخطة ──────────────────────────────────────────────────────
        plan = []            # (id, old, new, kind, reason, is_training)
        reasons = Counter()
        train_seq = 0
        tops = defaultdict(int)

        for bid, onum, kind, sref, legacy, d in books:
            stamp = stamps.get(sref) if sref else None

            if not sref:
                # لا صفّ في المصدر ⇒ أُدخل داخل التطبيق أثناء التدريب
                train_seq += 1
                new = N.format_training(train_seq)
                plan.append((bid, onum, new, kind, 'تدريب — فضاء T منفصل', True))
                reasons['تدريب → T'] += 1
                continue

            if stamp is None:
                plan.append((bid, onum, onum, kind, 'صفّ مصدره غير موجود — تُرك', False))
                reasons['بلا صفّ مصدر — تُرك'] += 1
                continue

            ledger_year, raw = stamp

            if kind in N.MANUAL_KINDS:
                # رقم مكتب المدير العام كما هو — لا سلسلة لنا فيه
                new = '' if _is_no_number(raw) else raw
                plan.append((bid, onum, new, kind, 'صادر خارجي — رقم مستقل كما هو', False))
                reasons['صادر خارجي — كما هو'] += 1
                continue

            if _is_no_number(raw):
                # السجلّ القديم نفسه يقول «بلا» — نحفظ الحقيقة لا رقماً مُختلقاً
                plan.append((bid, onum, '', kind, 'السجلّ يقول «بلا رقم» — استثناء معتمَد', False))
                reasons['بلا رقم (نصّ السجلّ: «بلا»)'] += 1
                continue

            if not raw.isdigit():
                plan.append((bid, onum, onum, kind, 'رقم مصدر غير رقمي (%r) — تُرك' % raw, False))
                reasons['رقم مصدر غير رقمي — تُرك'] += 1
                continue

            seq = int(raw)
            new = N.format_for_ledger_year(seq, ledger_year)
            plan.append((bid, onum, new, kind,
                         'من الختم: سجلّ %d رقم %d' % (ledger_year, seq), False))
            reasons['من ختم سجلّ %d' % ledger_year] += 1
            if ledger_year >= N.BASE_YEAR:
                tops[kind] = max(tops[kind], seq)

        changes = [p for p in plan if p[2] != p[1]]

        # ── تقرير المعاينة ─────────────────────────────────────────────────
        w('-' * 78)
        w('كتب سيتغيّر رقمها: %s من %s' % (f'{len(changes):,}', f'{len(books):,}'))
        for r, c in reasons.most_common():
            w('   %6s  %s' % (f'{c:,}', r))

        after = Counter()
        for bid, old, new, kind, reason, is_tr in plan:
            after[N.parse(new).kind_of] += 1
        w('-' * 78)
        w('توزيع الصيغ بعد إعادة البناء:')
        labels = {'series': 'مجرّد (السلسلة الجارية)', 'tagged': 'موسوم بسنته',
                  'training': 'تدريب (T)', 'blank': 'بلا رقم', 'unknown': 'غير معروف'}
        for k, v in after.most_common():
            w('   %6s  %s' % (f'{v:,}', labels.get(k, k)))

        # ── فحص التصادم داخل النطاق المحروس ────────────────────────────────
        guarded = defaultdict(list)
        for bid, old, new, kind, reason, is_tr in plan:
            if not new or kind in N.MANUAL_KINDS:
                continue
            # القيد يحرس الصفوف بلا source_ref فقط؛ لكن نُبلّغ عن أي ازدواج مرئي
            guarded[(kind, new)].append(bid)
        clash = {k: v for k, v in guarded.items() if len(v) > 1}
        w('-' * 78)
        w('أرقام يتشاركها أكثر من كتاب (داخل النوع): %d' % len(clash))
        for (kind, num), ids in list(clash.items())[:10]:
            w('   %-20s %-12s ← %s' % (kind, num, ids))
        if len(clash) > 10:
            w('   … و%d غيرها' % (len(clash) - 10))

        w('-' * 78)
        w('أساس العدّاد بعد إعادة البناء (أعلى رقم في السلسلة الجارية + 1):')
        for kind in N.SERIES_KINDS:
            w('   %-20s %d' % (kind, tops[kind] + 1))

        # ── كتابة الخريطة ──────────────────────────────────────────────────
        path = options['report']
        os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
        with open(path, 'w', newline='', encoding='utf-8-sig') as fh:
            wr = csv.writer(fh)
            wr.writerow(['book_id', 'old_our_number', 'new_our_number', 'kind',
                         'is_training', 'reason'])
            for bid, old, new, kind, reason, is_tr in changes:
                wr.writerow([bid, old, new, kind, int(is_tr), reason])
        w('-' * 78)
        w('خريطة الرجوع: %s' % path)

        w('=' * 78)
        if not options['yes']:
            w(self.style.WARNING('معاينة فقط — لم يُكتب شيء. راجع الخريطة ثم أضِف --yes.'))
            return

        # ── التنفيذ ────────────────────────────────────────────────────────
        applied = trained = 0
        with transaction.atomic():
            for bid, old, new, kind, reason, is_tr in plan:
                fields = []
                b = Book.objects.select_for_update().get(id=bid)
                if new != b.our_number:
                    if not b.legacy_number and b.our_number:
                        b.legacy_number = b.our_number
                        fields.append('legacy_number')
                    b.our_number = new
                    fields.append('our_number')
                    # الصيغة المركّبة انتهت — العرض والبحث يعتمدان legacy_number
                    if b.series_no is not None or b.version is not None:
                        b.series_no = None
                        b.version = None
                        fields += ['series_no', 'version']
                    applied += 1
                if is_tr and not b.is_training:
                    b.is_training = True
                    fields.append('is_training')
                    trained += 1
                if fields:
                    b.save(update_fields=fields)

            # ── الحجوزات ──
            # أرقامها كلّها في فضاء الترقيم المُلغى (بادئة سجلّ + عدّاد قديم)، وهي
            # ما كان يرفع العدّاد فوق أساسه: حجزٌ واحد بالرقم 417 كان يقفز بعدّاد
            # الوارد الخارجي إلى 418 فيبتلع الأرقام 358–417 كلّها. وهي بطبيعتها
            # عابرة (تنتهي أو تُلغى)، فلا معلومة تضيع بحذفها — رقم الكتاب في
            # الكتاب نفسه.
            dropped = BookNumberReservation.objects.all().delete()[0]

            # ── العدّادات ──
            # تُضبَط على الأساس المشتقّ من الورق **ضبطاً** لا رفعاً: قاعدة «لا
            # يُنزَل العدّاد» تحمي حجزاً حيّاً داخل نفس فضاء الترقيم، وقد تبدّل
            # الفضاء كلّه الآن — فإبقاء 4555 كان يعني أن الكتاب التالي يحمل رقماً
            # لا يكمل سلسلة الختم (2433). والحجوزات حُذفت للتوّ فلا حيّ يُحمى.
            for kind in N.SERIES_KINDS:
                target = tops[kind] + 1
                row, created = BookSequence.objects.select_for_update().get_or_create(
                    kind=kind, defaults={'next_number': target,
                                         'year': timezone.localdate().year})
                if not created and row.next_number != target:
                    row.next_number = target
                    row.save(update_fields=['next_number'])

            # الصادر الخارجي لا سلسلة له — رقمه من مكتب السيد المدير العام
            retired = BookSequence.objects.exclude(kind__in=N.SERIES_KINDS).delete()[0]

        w(self.style.SUCCESS(
            'حُذفت %d حجزاً في الفضاء المُلغى، وأُلغي %d عدّاداً لا سلسلة له.'
            % (dropped, retired)))

        w(self.style.SUCCESS(
            'أُعيد بناء %s رقماً، ووُسم %s كتاب تدريب.' % (f'{applied:,}', f'{trained:,}')))
        w('العدّادات: ' + '، '.join(
            '%s=%s' % (s.kind, s.next_number)
            for s in BookSequence.objects.order_by('kind')))
