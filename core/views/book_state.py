# -*- coding: utf-8 -*-
"""حالُ الكتاب في ترويسة صفحته — شريطُ الخطوات والفعلُ الأساسيُّ الواحد وسطرُ الاستشهاد.

**دالّاتٌ خالصة** (لا استعلامَ ولا قالب): تأخذ الكتابَ وما جمعه العرضُ من دورة
حياته، فتُختبر جدولاً، والقالبُ يعرض ولا يقرّر (§9.4: لا شرطَ دورٍ في قالب).
قراراتُ المالك 2026‑09‑29: Q2 الرقمُ في الدائرة وحدها · Q3 فعلٌ أساسيٌّ واحد
سياقيّ (فرِّق… ⟵ سجّل عهدة… ⟵ أنهِ المتابعة) · Q4 حبّةُ المتابعة فعلٌ.
"""
from .filter_helpers import FOLLOWUP_LABELS, followup_phrase

#: الأفعالُ الأساسيّة الثلاثة بترتيب الطريق — والقالبُ يرسمها من هنا لا من شروطه.
PRIMARY_ACTIONS = {
    'distribute': {'label': 'فرِّق…', 'icon': 'bi-arrow-left-right', 'modal': '#distributeModal'},
    'custody': {'label': 'سجّل عهدة…', 'icon': 'bi-person-badge', 'modal': '#custodyModal'},
    'close': {'label': 'أنهِ المتابعة', 'icon': 'bi-check2-circle', 'status': 'archived'},
}


def is_paper(book):
    """منقولٌ من الدفتر الورقيّ (``source_ref``) — لا تسييرَ له ولا عهدةَ تُختلق."""
    return bool(book.source_ref)


def _units_ar(n):
    if n == 1:
        return 'إلى وحدةٍ واحدة'
    if n == 2:
        return 'إلى وحدتين'
    if 3 <= n <= 10:
        return 'إلى %d وحدات' % n
    return 'إلى %d وحدة' % n


def journey(book, *, referrals, today=None):
    """شريطُ الخطوات: ``[{'key', 'label', 'sub', 'state'}]`` — والحالُ done/now/todo/off.

    الوارد: قُيِّد ⟵ فُرِّق ⟵ بالعهدة ⟵ أُنجز · والصادرُ بلا «فُرِّق».
    «أُنجز» **لا يُقاس بـ``is_archived`` وحدها** (افتراضُها True لكلّ كتابٍ بلا موعد):
    إحالاتٌ أُغلقت كلُّها، أو متابعةٌ بموعدٍ أُنهيت. والورقُ المنقول: «قُيِّد» وحدها
    والبقيّةُ مطفأة.
    """
    open_refs = [r for r in referrals if r['is_open']]
    holder = book.current_custody.holder_name if book.current_custody_id else ''
    if book.due_date and not book.is_archived:
        closing_sub = followup_phrase(book, today)
    elif book.due_date or referrals:
        closing_sub = ''
    else:
        closing_sub = 'بلا متابعة'
    steps = [{'key': 'registered', 'label': 'قُيِّد', 'done': True,
              'sub': book.date.strftime('%d/%m') if book.date else ''}]
    if book.is_incoming:
        steps.append({'key': 'distributed', 'label': 'فُرِّق', 'done': bool(referrals),
                      'sub': _units_ar(len(referrals)) if referrals else 'لم يُفرَّق'})
    steps.append({'key': 'custody', 'label': 'بالعهدة', 'done': bool(holder),
                  'sub': holder or 'لم تُسجَّل'})
    steps.append({'key': 'closed', 'label': 'أُنجز',
                  'done': bool((referrals and not open_refs)
                               or (book.due_date and book.is_archived)),
                  'sub': closing_sub})

    paper = is_paper(book)
    current = None if paper else next((s for s in steps if not s['done']), None)
    for step in steps:
        if paper and step['key'] != 'registered':
            step['state'] = 'off'
        elif step['done']:
            step['state'] = 'done'
        else:
            step['state'] = 'now' if step is current else 'todo'
    return steps


def primary_action(book, *, referrals, can_distribute, can_edit):
    """الفعلُ الأساسيُّ الواحد — أو ``None`` (لا أساسيَّ معطَّلاً، Q3).

    الوارد بلا تفريق ⟵ فرِّق… · بلا عهدة ⟵ سجّل عهدة… · متابعةٌ مفتوحةٌ بموعد ⟵
    أنهِ المتابعة. والصادرُ يبدأ من العهدة، والورقُ المنقولُ لا فعلَ أساسيَّ له.
    """
    if is_paper(book):
        return None
    if book.is_incoming and not referrals and can_distribute:
        key = 'distribute'
    elif not book.current_custody_id and can_distribute:
        key = 'custody'
    elif book.due_date and not book.is_archived and can_edit:
        key = 'close'
    else:
        return None
    return {'key': key, **PRIMARY_ACTIONS[key]}


def due_pill(book, today=None):
    """حبّةُ الموعد — ``None`` بلا موعد (كانت «مؤرشف» على كلّ كتابٍ بلا متابعة)."""
    if not book.due_date:
        return None
    state = book.followup_state
    return {
        'state': state,
        'text': followup_phrase(book, today),
        'date': book.due_date,
        'reopen': state == 'archived',
        'label': FOLLOWUP_LABELS[state],
    }


def citation(book):
    """سطرُ الاستشهاد كما يُكتب في المراسلات — قطعٌ ``(نصّ، قيمة؟)``.

    الوارد: «من {الجهة} — كتابهم {رقمهم} في {تاريخهم} · قُيِّد عندنا {رقمنا} في {تاريخنا}».
    الصادر: «إلى {الجهة} — كتابُنا {رقمنا} في {تاريخنا}» (رقمُ الخارجيّ حرفيّ من مكتب المدير).
    والقيمةُ ``True`` تُبرَز في العرض؛ والنسخُ يأخذ النصَّ كلَّه سطراً واحداً.
    """
    def day(d):
        return d.strftime('%d/%m/%Y') if d else ''

    ours = book.our_number_display or 'بلا رقم'
    parts = []
    if book.is_incoming:
        who = book.first_issuing_entity
        if who:
            parts += [('من ', False), (who.name, True)]
        if book.sender_number or book.sender_date:
            parts += [(' — ' if parts else '', False), ('كتابهم ', False)]
            if book.sender_number:
                parts.append((book.sender_number, True))
            if book.sender_date:
                parts += [(' في ' if book.sender_number else 'في ', False), (day(book.sender_date), True)]
        parts += [(' · ' if parts else '', False), ('قُيِّد عندنا ', False), (ours, True)]
    else:
        who = book.first_receiving_entity
        if who:
            parts += [('إلى ', False), (who.name, True), (' — ', False)]
        parts += [('كتابُنا ', False), (ours, True)]
    if book.date:
        parts += [(' في ', False), (day(book.date), True)]
    return [p for p in parts if p[0]]
