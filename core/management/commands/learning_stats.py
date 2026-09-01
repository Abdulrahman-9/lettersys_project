# -*- coding: utf-8 -*-
"""مؤشّراتُ التعلّم المستمرّ — أربعةٌ فقط، كلٌّ منها يقود قراراً مُسجَّلاً.

يحلّ محلّ `ExtractionLearningSystem` (حُذف): ذاك كان يعرض «دقّةً» مقامُها
التصحيحاتُ وحدها و`error_rate` مُثبَّتاً 1.0، وحقولُه الثلاثة الأولى استبعدها
الالتقاطُ عمداً — فالناتج رقمٌ مفبرك، وعرضُ رقمٍ كاذبٍ أسوأ من عرض لا شيء.

التعريفاتُ والعتبات كلّها مُسجَّلةٌ في `docs/EVAL_REGISTRY.md` قسم «حوكمةُ
التعلّم المستمرّ» **قبل** العدّ (وإلّا صار الرقم مطّاطاً). لا تُعدَّل هنا.

    python manage.py learning_stats [--days 30]
"""
from collections import Counter
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from core.models import Book, DataExtractionResult, ExtractionFeedback

_INCOMING = ('incoming_internal', 'incoming_external')
# تطبيعُ الأرقام قبل المقارنة (نظيرُ `capture._same_number`): خطٌّ رقميٌّ مختلف
# ليس تصحيحاً.
_AR_DIGITS = str.maketrans('٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹', '01234567890123456789')

# ── عتباتُ إعادة التدريب (EVAL_REGISTRY §1) ────────────────────────────────
GATE_NUMBER = 500          # زوجاً لقارئ العدد
GATE_NUMBER_HARD = 150     # منها تصحيحاً/مكتوباً بيد (المؤكَّد وحده يُعلّم النسيان)
GATE_DATE = 300            # زوجاً لقارئ التاريخ
GATE_TITLE = 50            # تصحيحاً لجلسة تنقيبِ قواعد (العنوان قواعدُ لا نموذج)

# ثقةُ «العرضِ الواثق»: تصحيحٌ فوقها = بروكسي الإنتاج لـ«واثقٌ‑ومخطئ».
CONF_NUMBER = 0.90
CONF_DATE = 0.98
FREEZE_ALARM = 0.05        # فوقه يُجمَّد الإصدار (EVAL_REGISTRY §3‑ج)

# تغطيةٌ تحتها نقيس عيّنةً منحازة لا الجمهور (الجدوى المسجَّلة 65–84%).
COVERAGE_FLOOR = 0.65

# رايةُ «عُرض على الكاتب فعلاً» (EVAL_REGISTRY §2‑5). لاحقتُها معلَنةٌ في
# `capture_schema.displayed_key`؛ تُقرأ هنا بالاسم لا بالاستيراد كي يبقى الأمر
# قابلاً للتشغيل قبل إيداع المخطّط. والصفوفُ الأقدمُ من الراية بلا مفتاحٍ أصلاً،
# فالسقوطُ إلى استدلال «وُجد اقتراحٌ منطوق» لازمٌ في الحالين.
_DISPLAYED = '%s_displayed'

# ما يُحسب في حصّة الـ150: التصحيحُ والمكتوبُ بيد. المؤكَّدُ المتّفقُ عليه لا
# يُحسب — الحصّةُ موجودةٌ أصلاً لتمنع دفعةً كلُّها اتّفاقٌ (فتُعلّم النموذجَ
# نفسَه). تُذكَر بالاسم لا بالنفي كي لا تبتلعَ وسوماً تُضاف لاحقاً بلا انتباه.
HARD_MIX = ('مُصحَّح', 'مكتوبٌ بيد', 'typed')

_WEEK = timedelta(days=7)


def _txt(v):
    return str(v or '').strip()


def _num(v):
    return _txt(v).translate(_AR_DIGITS)


def _f(v):
    try:
        return float(v or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _pct(n, d):
    return '—' if not d else '%.1f%%' % (100.0 * n / d)


def _shown(ad, field, fallback):
    """هل عُرض اقتراحُ هذا الحقل على الكاتب؟ الرايةُ إن وُجدت، وإلّا الاستدلال."""
    flag = ad.get(_DISPLAYED % field)
    return bool(flag) if flag is not None else fallback


class Command(BaseCommand):
    help = 'مؤشّراتُ التعلّم المستمرّ الأربعة (أزواج/واثقٌ‑ومصحَّح/تغطية/متأخّرة)'

    def add_arguments(self, parser):
        parser.add_argument('--days', type=int, default=30,
                            help='طولُ المدّة بالأيّام (افتراضي 30)')

    # ── جمعُ البيانات ──────────────────────────────────────────────────────
    def _collect(self, cutoff, now, nweeks):
        """يمرّ مرّةً واحدةً على سجلّات الالتقاط ويبني كلّ العدّادات."""
        rows = list(DataExtractionResult.objects
                    .filter(created_at__gte=cutoff)
                    .values('id', 'created_at', 'book_id', 'additional_data'))

        # التصحيحاتُ المسجَّلة على نفس السجلّات (لا على تاريخ الملاحظة: الملاحظة
        # تُولد لحظةَ الالتقاط، فالمحاذاةُ بالسجلّ أصدق).
        fb_ids, fb_total = {}, Counter()
        for ex_id, field in (ExtractionFeedback.objects
                             .filter(extraction__created_at__gte=cutoff)
                             .values_list('extraction_id', 'field_name')):
            fb_ids.setdefault(field, set()).add(ex_id)
            fb_total[field] += 1

        # قيمُ الكتب **الحيّة** الآن — أساسُ المؤشّر الرابع.
        live = {b[0]: (b[1], b[2]) for b in Book.objects.filter(
            id__in=[r['book_id'] for r in rows if r['book_id']]
        ).values_list('id', 'sender_number', 'sender_date')}

        d = {
            'captures': 0,
            'pairs': Counter(), 'mix': {'sender_number': Counter(), 'sender_date': Counter()},
            'partial': Counter(),          # (field, 'box') صندوقٌ بلا قيمة · (field,'val') العكس
            'shown': Counter(), 'shown_fixed': Counter(),
            'late_seen': Counter(), 'late_diff': Counter(),
            'week_cap': Counter(), 'week_pair': Counter(),
        }
        for r in rows:
            ad = r['additional_data']
            if not isinstance(ad, dict):
                continue
            d['captures'] += 1
            wk = min(int((now - r['created_at']).total_seconds() // _WEEK.total_seconds()), nweeks - 1)
            d['week_cap'][wk] += 1
            if _txt(ad.get('book_kind')) not in _INCOMING:
                continue   # الصادر: لا عدد جهةٍ ولا تاريخَ جهةٍ يُستخرَجان

            # ① زوجُ العدد = صندوقٌ + قيمةٌ نهائيّة (نفسُ تعريف `capture_stats`).
            self._field(d, r, wk, 'sender_number',
                        box=ad.get('sender_number_bbox'),
                        final=_txt(ad.get('sender_number_final')),
                        sug=_txt(ad.get('sender_number_suggested')),
                        conf=_f(ad.get('sender_number_confidence')),
                        prov=_txt(ad.get('sender_number_provenance')),
                        fb_ids=fb_ids, conf_gate=CONF_NUMBER,
                        shown=_shown(ad, 'sender_number',
                                     bool(_txt(ad.get('sender_number_suggested')))))
            self._field(d, r, wk, 'sender_date',
                        box=ad.get('sender_date_bbox'),
                        final=_txt(ad.get('sender_date_final')),
                        sug=_txt(ad.get('sender_date_suggested_iso')),
                        conf=_f(ad.get('sender_date_confidence')),
                        prov=_txt(ad.get('sender_date_provenance')),
                        fb_ids=fb_ids, conf_gate=CONF_DATE,
                        shown=_shown(ad, 'sender_date',
                                     _txt(ad.get('sender_date_parse')) == 'ok'))

            # ④ التصحيحُ المتأخّر: الملتقَطُ يخالف قيمة الكتاب الحيّة الآن.
            b = live.get(r['book_id'])
            if b is None:
                continue
            for field, cap, now_val in (
                ('sender_number', _txt(ad.get('sender_number_final')), _txt(b[0])),
                ('sender_date', _txt(ad.get('sender_date_final')), (b[1].isoformat() if b[1] else '')),
            ):
                if not cap:
                    continue
                d['late_seen'][field] += 1
                same = (_num(cap) == _num(now_val)) if field == 'sender_number' else (cap == now_val)
                if not same:
                    d['late_diff'][field] += 1
        d['fb_total'] = fb_total
        return d

    @staticmethod
    def _field(d, r, wk, field, *, box, final, sug, conf, prov, fb_ids, conf_gate, shown):
        corrected = r['id'] in fb_ids.get(field, ())
        if box and final:
            d['pairs'][field] += 1
            d['week_pair'][(field, wk)] += 1
            # الخليط: التصحيحُ والمكتوبُ بيدٍ يُوزنان ×2–3، والمؤكَّدُ ≤20% بوزن ×1،
            # و`autofilled` يُستبعَد كلّيّاً (EVAL_REGISTRY §2‑1/2).
            d['mix'][field][prov or ('مُصحَّح' if corrected else
                                     'مكتوبٌ بيد' if not sug else 'متّفقٌ عليه')] += 1
        elif box:
            d['partial'][(field, 'box')] += 1
        elif final:
            d['partial'][(field, 'val')] += 1
        # ② المقام: ما **عُرض** بثقةٍ عالية. البسط: ما صُحّح منه.
        if shown and conf >= conf_gate:
            d['shown'][field] += 1
            if corrected:
                d['shown_fixed'][field] += 1

    # ── الطباعة ────────────────────────────────────────────────────────────
    def handle(self, *args, **opts):
        days = max(int(opts['days']), 1)
        now = timezone.now()
        cutoff = now - timedelta(days=days)
        nweeks = max((days + 6) // 7, 1)
        w = self.stdout.write

        d = self._collect(cutoff, now, nweeks)
        n_pairs, dt_pairs = d['pairs']['sender_number'], d['pairs']['sender_date']
        n_hard = sum(v for k, v in d['mix']['sender_number'].items() if k in HARD_MIX)
        t_fix = d['fb_total'].get('title', 0)

        # حفظاتُ الوارد: المستوردُ من الورق ليس حفظاً (`source_ref` غيرُ فارغ) —
        # إدخالُه في المقام يخفي التغطية الحقيقيّة تحت 11 ألف صفٍّ دفعةً واحدة.
        saved_all = Book.objects.filter(created_at__gte=cutoff, kind__in=_INCOMING)
        app_saved = saved_all.filter(source_ref='')   # الحقل غيرُ قابلٍ للعدم (default='')
        saved = app_saved.count()
        imported = saved_all.count() - saved
        week_saved = Counter()
        for ca in app_saved.values_list('created_at', flat=True):
            week_saved[min(int((now - ca).total_seconds() // _WEEK.total_seconds()), nweeks - 1)] += 1

        cc_n = d['shown_fixed']['sender_number'] + d['shown_fixed']['sender_date']
        cc_d = d['shown']['sender_number'] + d['shown']['sender_date']
        cc_hot = bool(cc_d) and (cc_n / cc_d) > FREEZE_ALARM

        # ── الرأس: سطران ────────────────────────────────────────────────────
        w('═══ مؤشّراتُ التعلّم المستمرّ — آخر %d يوماً (منذ %s) ═══'
          % (days, cutoff.date().isoformat()))
        w('البوّابات : عدد %d/%d · تاريخ %d/%d · عنوان %d/%d — %s'
          % (n_pairs, GATE_NUMBER, dt_pairs, GATE_DATE, t_fix, GATE_TITLE,
             'مفتوحةٌ بوّابةٌ أو أكثر' if (n_pairs >= GATE_NUMBER or dt_pairs >= GATE_DATE
                                          or t_fix >= GATE_TITLE) else 'كلُّها مغلقة'))
        w('الصحّة    : واثقٌ‑ومصحَّح %s · تغطية %s · متأخّرة %d'
          % (_pct(cc_n, cc_d), _pct(d['captures'], saved),
             sum(d['late_diff'].values())))
        w('')

        # ── ① الأزواج والخليط ───────────────────────────────────────────────
        w('① أزواجٌ لكلّ حقل + خليطُ المصدر   ⟵ القرار: متى تُفتح بوّابةُ إعادة التدريب')
        for label, field, gate in (('العدد  ', 'sender_number', GATE_NUMBER),
                                   ('التاريخ', 'sender_date', GATE_DATE)):
            got = d['pairs'][field]
            w('   %s : %d / %d زوجاً — %s' % (
                label, got, gate,
                'البوّابة مفتوحة' if got >= gate else 'يتبقّى %d' % (gate - got)))
            w('             الخليط: %s' % (' · '.join(
                '%s %d' % (k, v) for k, v in d['mix'][field].most_common()) or '—'))
            w('             ناقصٌ: صندوقٌ بلا قيمة %d · قيمةٌ بلا صندوق %d'
              % (d['partial'][(field, 'box')], d['partial'][(field, 'val')]))
        w('   %s : منها تصحيحٌ/مكتوبٌ بيد %d / %d — %s' % (
            'العدد  ', n_hard, GATE_NUMBER_HARD,
            'مستوفى' if n_hard >= GATE_NUMBER_HARD else 'يتبقّى %d' % (GATE_NUMBER_HARD - n_hard)))
        w('   %s : %d / %d تصحيحاً (قواعدُ لا نموذج) — %s' % (
            'العنوان', t_fix, GATE_TITLE,
            'تُجدوَل جلسةُ تنقيب' if t_fix >= GATE_TITLE else 'يتبقّى %d' % (GATE_TITLE - t_fix)))
        if d['mix']['sender_number'] and not any(
                k in ('typed', 'confirmed', 'autofilled') for k in d['mix']['sender_number']):
            w(self.style.WARNING(
                '   ⚠ لا وسمَ provenance للعدد بعدُ (ثغرةُ EVAL_REGISTRY §2‑1): «متّفقٌ عليه»\n'
                '     يخلط confirmed بـautofilled — والثاني يُستبعَد من التدريب كلّيّاً.'))
        w('')

        # ── ② واثقٌ‑ومصحَّح ─────────────────────────────────────────────────
        w('② معدّل «واثقٌ‑ومصحَّح»            ⟵ القرار: فوق %d%% يُجمَّد الإصدار'
          % int(FREEZE_ALARM * 100))
        for label, field, gate in (('العدد  ', 'sender_number', CONF_NUMBER),
                                   ('التاريخ', 'sender_date', CONF_DATE)):
            w('   %s (عُرض بثقة ≥%.2f) : %d / %d = %s' % (
                label, gate, d['shown_fixed'][field], d['shown'][field],
                _pct(d['shown_fixed'][field], d['shown'][field])))
        if cc_hot:
            w(self.style.ERROR(
                '   ⛔ %s فوق الحدّ — بروكسيُّ «واثقٌ‑ومخطئ» في الإنتاج: لا إصدارَ جديد'
                % _pct(cc_n, cc_d)))
        elif cc_d:
            w(self.style.SUCCESS('   ✓ تحت الحدّ.'))
        else:
            w('   لا اقتراحَ عُرض بثقةٍ عالية في المدّة — المؤشّر بلا مقام.')
        w('')

        # ── ③ التغطية ───────────────────────────────────────────────────────
        w('③ تغطيةُ الالتقاط                 ⟵ القرار: أنقيسُ الجمهورَ أم عيّنةً منحازة؟')
        w('   حفظاتُ وارد (بالتطبيق) %d · سجلّاتُ التقاط %d ⟵ %s'
          % (saved, d['captures'], _pct(d['captures'], saved)))
        if imported:
            w('   (+ %d صفّاً مستورداً من الورق — لا يُحسب حفظاً ولا يمرّ بالمسح)' % imported)
        if saved and d['captures'] / saved < COVERAGE_FLOOR:
            w(self.style.WARNING(
                '   ⚠ تحت %d%%: الإدخالُ بلا مسحٍ لا يُلتقَط، فالمقيسُ عيّنةٌ منحازة'
                % int(COVERAGE_FLOOR * 100)))
        w('')

        # ── ④ التصحيحاتُ المتأخّرة ──────────────────────────────────────────
        w('④ التصحيحاتُ المتأخّرة              ⟵ القرار: معدّلُ الختم-بلا-تدقيق المقيس')
        for label, field in (('العدد  ', 'sender_number'), ('التاريخ', 'sender_date')):
            w('   %s : %d / %d صفّاً تخالف قيمتُه الملتقَطة قيمةَ الكتاب الحيّة = %s'
              % (label, d['late_diff'][field], d['late_seen'][field],
                 _pct(d['late_diff'][field], d['late_seen'][field])))
        w('   (الزوجُ المختلف يُسقَط عند الحصاد — مصفاةُ التباعد، EVAL_REGISTRY §2‑4)')
        w('')

        # ── نبضُ الحياة ─────────────────────────────────────────────────────
        w('نبضُ الحياة (أسبوعاً بأسبوع)')
        w('   المدى            حفظاتُ وارد  التقاط  عدد  تاريخ')
        dead = []
        for i in range(nweeks - 1, -1, -1):
            end, start = now - i * _WEEK, max(now - (i + 1) * _WEEK, cutoff)
            w('   %s ⟵ %s %9d %8d %5d %5d' % (
                start.date().isoformat(), end.date().isoformat(),
                week_saved[i], d['week_cap'][i],
                d['week_pair'][('sender_number', i)], d['week_pair'][('sender_date', i)]))
            if week_saved[i] and not d['week_cap'][i]:
                dead.append('%s⟵%s' % (start.date().isoformat(), end.date().isoformat()))
        if dead:
            w(self.style.ERROR(
                '   ⛔ صفرُ التقاطٍ في أسبوعٍ نشط (%s) — الحلقةُ مقطوعة لا بطيئة.'
                % '، '.join(dead)))
        elif not d['captures']:
            w('   لا التقاطَ ولا حفظاتِ واردٍ في المدّة — لا حكم.')
