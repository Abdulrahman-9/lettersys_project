# -*- coding: utf-8 -*-
"""
core/entity_dedup.py — كشف ودمج الجهات المكرّرة.

الكشف: تجميع الجهات حسب مفتاح تطبيع إملائي عربي مُحافِظ
       (يلتقط التكرارات الإملائية فقط: ة/ه، أ/ا، همزات، مسافات — دقّة عالية).
الدمج: إعادة توجيه روابط الكتب من النسخ إلى الأمّ، نقل بيانات الاتصال
       الناقصة، تعطيل النسخ مع تسجيل merged_into للأثر والتدقيق.
"""
import re
from collections import defaultdict

from django.db import transaction
from django.db.models import Count, IntegerField, OuterRef, Subquery
from django.db.models.functions import Coalesce

from .models import Book, Entity

# الحركات (التشكيل) + تطويل الكشيدة
_TASHKEEL = re.compile(r'[ً-ْٰـ]')
_HAMZA_ALEF = re.compile(r'[إأآ]')

# الحقول التي تُنقل للأمّ إن كانت ناقصة لديها (الأمّ لها الأولوية)
_CARRY_FIELDS = ('code', 'email', 'email_cc', 'phone', 'address', 'contact_person', 'notes')


def norm_key(name):
    """مفتاح تطبيع: يوحّد الفروق الإملائية الشائعة فقط — تجميع مُحافِظ عالي الدقّة."""
    s = (name or '').strip()
    s = _TASHKEEL.sub('', s)
    s = _HAMZA_ALEF.sub('ا', s)                       # توحيد الهمزات على الألف
    s = s.replace('ة', 'ه').replace('ى', 'ي')         # تاء مربوطة/ألف مقصورة
    s = s.replace('ؤ', 'و').replace('ئ', 'ي').replace('ء', '')
    s = re.sub(r'\s+', ' ', s).strip()
    return s.lower()


def correctness_score(entity):
    """درجة صحّة الإملاء — أعلى = أصحّ (ة سليمة، همزات مكتوبة، بلا مسافات زائدة)."""
    n = entity.name or ''
    score = 0
    if 'ة' in n:
        score += 2
    if _HAMZA_ALEF.search(n):
        score += 1
    if n != n.strip() or '  ' in n:
        score -= 2
    return score


def book_count(entity):
    """إجمالي كتب الجهة (مُصدَرة + مستلَمة) — يعتمد على التعليق التوضيحي."""
    return (getattr(entity, 'issued_count', 0) or 0) + (getattr(entity, 'received_count', 0) or 0)


def _canonical_sort_key(entity):
    """ترتيب اختيار الجهة الأمّ: رمز ← أصحّ إملاءً ← أكثر استخداماً ← أقدم."""
    return (
        0 if (entity.code or '').strip() else 1,
        -correctness_score(entity),
        -book_count(entity),
        entity.id,
    )


def annotate_book_counts(qs):
    """يضيف issued_count/received_count لأي queryset جهات
       (استعلامان فرعيان مستقلّان — بلا ضرب ديكارتي)."""
    issued = (Book.objects.filter(issuing_entities=OuterRef('pk'), is_deleted=False)
              .order_by().values('issuing_entities').annotate(c=Count('id')).values('c'))
    received = (Book.objects.filter(receiving_entities=OuterRef('pk'), is_deleted=False)
                .order_by().values('receiving_entities').annotate(c=Count('id')).values('c'))
    return qs.annotate(
        issued_count=Coalesce(Subquery(issued, output_field=IntegerField()), 0),
        received_count=Coalesce(Subquery(received, output_field=IntegerField()), 0),
    )


def find_duplicate_clusters():
    """يُعيد عناقيد التكرار مرتّبةً بالأكبر أولاً.
       كل عنقود: {'key', 'members': [entities مرتّبة، الأمّ أولاً], 'canonical': entity}."""
    groups = defaultdict(list)
    for e in annotate_book_counts(Entity.objects.filter(is_active=True)):
        groups[norm_key(e.name)].append(e)
    clusters = []
    for key, members in groups.items():
        if len(members) < 2:
            continue
        members.sort(key=_canonical_sort_key)
        clusters.append({'key': key, 'members': members, 'canonical': members[0]})
    clusters.sort(key=lambda c: -len(c['members']))
    return clusters


def build_manual_cluster(ids):
    """يبني عنقوداً يدوياً من جهات حدّدها المستخدم بنفسه — تجاوزٌ للكشف الآلي
       (للتكرارات التي لا يلتقطها التطبيع: اختصارات، فروق دلالية، إلخ).
       يُعيد None إذا لم تبقَ جهتان نشطتان على الأقل."""
    members = sorted(
        annotate_book_counts(Entity.objects.filter(id__in=ids, is_active=True)),
        key=_canonical_sort_key,
    )
    if len(members) < 2:
        return None
    return {'key': 'تحديد يدوي', 'members': members,
            'canonical': members[0], 'manual': True}


def _repoint_m2m(through, victim_id, canonical_id):
    """ينقل صفوف جدول M2M الوسيط من النسخة إلى الأمّ، متفادياً ازدواج الربط."""
    canon_books = set(
        through.objects.filter(entity_id=canonical_id).values_list('book_id', flat=True)
    )
    rows = list(through.objects.filter(entity_id=victim_id).values_list('id', 'book_id'))
    move_ids = [rid for rid, bid in rows if bid not in canon_books]
    dup_ids = [rid for rid, bid in rows if bid in canon_books]
    if move_ids:
        through.objects.filter(id__in=move_ids).update(entity_id=canonical_id)
    if dup_ids:
        through.objects.filter(id__in=dup_ids).delete()
    return len(move_ids)


@transaction.atomic
def merge_entities(canonical_id, victim_ids):
    """يدمج الجهات `victim_ids` ضمن `canonical_id` ذرّياً:
       - يُعيد توجيه روابط الكتب (المُصدِرة والمستلِمة) إلى الأمّ.
       - ينقل بيانات الاتصال الناقصة إلى الأمّ دون طمس الموجود.
       - يعطّل كل نسخة ويضبط merged_into = الأمّ.
       يُعيد dict ملخّصاً."""
    canonical_id = int(canonical_id)
    victim_ids = [int(v) for v in victim_ids if int(v) != canonical_id]
    canonical = Entity.objects.select_for_update().get(pk=canonical_id)
    victims = list(Entity.objects.select_for_update().filter(pk__in=victim_ids))
    if not victims:
        return {'canonical': canonical, 'merged': 0, 'moved_books': 0, 'carried': {}}

    issuing_through = Book.issuing_entities.through
    receiving_through = Book.receiving_entities.through
    moved = 0
    carried = {}
    for v in victims:
        moved += _repoint_m2m(issuing_through, v.id, canonical.id)
        moved += _repoint_m2m(receiving_through, v.id, canonical.id)
        # نقل بيانات الاتصال الناقصة فقط — الأمّ لها الأولوية
        for fld in _CARRY_FIELDS:
            if str(getattr(canonical, fld) or '').strip():
                continue
            incoming = getattr(v, fld) or ''
            if str(incoming).strip():
                setattr(canonical, fld, incoming)
                carried[fld] = incoming
                if fld == 'code':
                    v.code = None  # حرّر الرمز الفريد لتأخذه الأمّ دون تعارض
        v.is_active = False
        v.merged_into = canonical
        v.save()
    if carried:
        canonical.save(update_fields=list(carried.keys()))
    return {'canonical': canonical, 'merged': len(victims),
            'moved_books': moved, 'carried': carried}
