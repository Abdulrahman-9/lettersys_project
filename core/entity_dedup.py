# -*- coding: utf-8 -*-
"""
core/entity_dedup.py — كشف ودمج الجهات المكرّرة.

الكشف: تجميع الجهات حسب مفتاح تطبيع إملائي عربي مُحافِظ
       (يلتقط التكرارات الإملائية فقط: ة/ه، أ/ا، همزات، مسافات — دقّة عالية).
الدمج: إعادة توجيه روابط الكتب من النسخ إلى الأمّ، نقل بيانات الاتصال
       الناقصة، تعطيل النسخ مع تسجيل merged_into للأثر والتدقيق.
"""
import json
import os
import re
from collections import defaultdict

from django.db import transaction
from django.db.models import Count, IntegerField, OuterRef, Subquery
from django.db.models.functions import Coalesce

from .models import Book, Entity, LetterheadMemory

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


# ============================================================
# الكشف الذكي (الدلالي) — ما يفوت التطبيع الإملائي
# ============================================================
# التطبيع المحافظ يمسك «مديرية/مديريه» فقط. أما تكرارات الواقع فأشيعها:
#   تصحيف حرفٍ واحد («المدبر العام»، «العقزد»، «لجة»)، التصاقُ كلمتين
#   («المديرالعام»)، وبادئاتٌ تشريفية («السيد رئيس…» مقابل «رئيس…»).
# الشرط الصارم: كل رمزٍ في الاسم الأقصر يقابل رمزاً في الأطول بمسافة تحرير ≤1،
# والبقايا تشريفيةٌ فقط — فلا تُدمج فروقٌ دلالية («الفنية»≠«الادارية») ولا
# علاقات تبعية («شعبة X» ليست «قسم X»). الناتج مرشّحات للمراجعة البشرية لا دمجاً.
_HONORIFIC = {'السيد', 'السادة', 'مكتب', 'المحترم', 'المحترمة'}
_GENERIC_WORDS = {'شركة', 'قسم', 'شعبة', 'مديرية', 'دائرة', 'هيئة', 'هيأة', 'هياة',
                  'وزارة', 'لجنة', 'وحدة', 'company', 'limited', 'ltd', 'co', 'corp',
                  'petroleum', 'oil', 'the', 'of', 'and', 'for', 'iraq'}


def _sig_tokens(name):
    """رموز الاسم المميِّزة (بعد التطبيع وإسقاط الكلمات العامة والواو العاطفة)."""
    s = re.sub(r'[^\w\s؀-ۿ]', ' ', norm_key(name))
    out = []
    for t in s.split():
        if t.startswith('و') and len(t) > 3:
            t = t[1:]
        if t in ('و',) or t in _GENERIC_WORDS or len(t) < 2:
            continue
        out.append(t)
    return out


def _within_one_edit(a, b):
    """مسافة تحرير ≤ 1 (إبدال/حذف واحد) — رمزان متقاربان طولاً."""
    if a == b:
        return True
    if abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        return sum(1 for x, y in zip(a, b) if x != y) <= 1
    if len(a) > len(b):
        a, b = b, a
    return any(a == b[:i] + b[i + 1:] for i in range(len(b)))


def _near_duplicate(t1, t2):
    """اسمان مرشّحان للدمج: كل رمزٍ في الأقصر يقابل رمزاً في الأطول (مسافة ≤1،
    أو التصاقٌ بكلمة مجاورة)، والبقايا تشريفيةٌ محضة."""
    if not t1 or not t2:
        return False
    short, long_ = (t1, t2) if len(t1) <= len(t2) else (t2, t1)
    rest = list(long_)
    for tok in short:
        hit = next((r for r in rest if _within_one_edit(tok, r)), None)
        if hit is not None:
            rest.remove(hit)
            continue
        # التصاقُ كلمتين: «المديرالعام» ≡ «المدير» + «العام» — بالاتجاهين
        pair = next(((a, b) for i, a in enumerate(rest) for b in rest[i + 1:]
                     if _within_one_edit(tok, a + b) or _within_one_edit(tok, b + a)), None)
        if pair:
            rest.remove(pair[0])
            rest.remove(pair[1])
            continue
        return False
    return all(r in _HONORIFIC for r in rest)


def find_semantic_candidates(limit=200):
    """مرشّحات دمجٍ ذكية (تصحيف/التصاق/تشريف) — للمراجعة البشرية في الواجهة.
    يُعيد عناقيد بنفس شكل find_duplicate_clusters (الأمّ أولاً)."""
    ents = list(annotate_book_counts(Entity.objects.filter(is_active=True)))
    toks = {e.id: _sig_tokens(e.name) for e in ents}
    parent = {e.id: e.id for e in ents}

    def _root(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    ortho = {e.id for c in find_duplicate_clusters() for e in c['members']}
    for i in range(len(ents)):
        for j in range(i + 1, len(ents)):
            a, b = ents[i], ents[j]
            if a.id in ortho and b.id in ortho:
                continue                       # يمسكه الكشف الإملائي أصلاً
            if _near_duplicate(toks[a.id], toks[b.id]):
                parent[_root(a.id)] = _root(b.id)

    groups = defaultdict(list)
    for e in ents:
        groups[_root(e.id)].append(e)
    clusters = []
    for members in groups.values():
        if len(members) < 2:
            continue
        members.sort(key=_canonical_sort_key)
        clusters.append({'key': 'مرشّح ذكي', 'members': members,
                         'canonical': members[0], 'smart': True})
    clusters.sort(key=lambda c: -sum(book_count(m) for m in c['members']))
    return clusters[:limit]


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
    moved_memory = 0
    carried = {}
    for v in victims:
        moved += _repoint_m2m(issuing_through, v.id, canonical.id)
        moved += _repoint_m2m(receiving_through, v.id, canonical.id)
        # إعادة توجيه ذاكرة الترويسة أيضاً — وإلا تبقى الإشارة مُشظّاة على النسخة المُعطّلة
        # (فهرس match_from_memory يقرأ issuing/receiving_entity مباشرةً).
        moved_memory += LetterheadMemory.objects.filter(issuing_entity_id=v.id).update(issuing_entity=canonical)
        moved_memory += LetterheadMemory.objects.filter(receiving_entity_id=v.id).update(receiving_entity=canonical)
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
            'moved_books': moved, 'moved_memory': moved_memory, 'carried': carried}


# ============================================================
# خطة الدمج المُخلَّدة — قرارات دمج مُراجَعة بشرياً تُعاد عند كل استعادة
# ============================================================
# الخطة بالأسماء لا المعرّفات، فتصلح لأي استعادة نسخة احتياطية أو قاعدة جديدة
# تحمل التسميات ذاتها. التطبيق عبر: python manage.py prepare_entities
# (تقرير = موافقة المستخدم أولاً، ثم --apply للتنفيذ).

PLAN_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         'data', 'entity_merge_plan.json')


def export_merge_plan():
    """يستخرج الخطة من تاريخ الدمج الفعلي (merged_into) — يتبع سلاسل الدمج
       حتى الأمّ النشطة، ويُسقط أسماء المبادلة المؤقتة."""
    clusters = defaultdict(set)
    victims = Entity.objects.filter(is_active=False, merged_into__isnull=False)
    for v in victims.select_related('merged_into'):
        canon, hops = v.merged_into, 0
        while canon and not canon.is_active and canon.merged_into_id and hops < 10:
            canon, hops = canon.merged_into, hops + 1
        if canon and canon.is_active and not v.name.startswith('~'):
            clusters[canon.name].add(v.name)
    return [{'canonical': name, 'variants': sorted(vs - {name})}
            for name, vs in sorted(clusters.items()) if vs - {name}]


def save_merge_plan(plan, path=PLAN_PATH):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(plan, f, ensure_ascii=False, indent=1)


def load_merge_plan(path=PLAN_PATH):
    if not os.path.exists(path):
        return []
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def plan_actions(plan):
    """يحلّ الخطة على القاعدة الحالية → إجراءات {'canonical','target','victims'}.
       الهدف: الجهة النشطة باسم الأمّ إن وُجدت، وإلا أفضل النسخ (وتُعاد تسميتها)."""
    actions = []
    for c in plan:
        names = [c['canonical']] + list(c.get('variants', []))
        found = list(annotate_book_counts(
            Entity.objects.filter(is_active=True, name__in=names)))
        if not found:
            continue
        target = next((e for e in found if e.name == c['canonical']), None) \
            or sorted(found, key=_canonical_sort_key)[0]
        victims = [e for e in found if e.id != target.id]
        if not victims and target.name == c['canonical']:
            continue  # مُطبَّقة سلفاً
        actions.append({'canonical': c['canonical'], 'target': target,
                        'victims': victims})
    return actions


def _claim_name(entity, name):
    """يمنح الجهة الاسم الموحَّد؛ إن حجزته نسخة معطَّلة يبادل الاسمين
       (قيد الفرادة الشامل) — يرفض فقط إن كان لجهة نشطة أخرى."""
    holder = Entity.objects.filter(name=name).exclude(id=entity.id).first()
    if holder and holder.is_active:
        return False
    old = entity.name
    if holder:
        entity.name = f'~swap-{entity.id}~'
        entity.save(update_fields=['name'])
        holder.name = old
        holder.save(update_fields=['name'])
    entity.name = name
    entity.save(update_fields=['name'])
    return True


@transaction.atomic
def apply_plan_action(action):
    """ينفّذ إجراء خطة واحداً ذرّياً: دمج النسخ ثم توحيد اسم الأمّ."""
    target, victims = action['target'], action['victims']
    if victims:
        r = merge_entities(target.id, [v.id for v in victims])
    else:
        r = {'canonical': target, 'merged': 0, 'moved_books': 0,
             'moved_memory': 0, 'carried': {}}
    if target.name != action['canonical']:
        target.refresh_from_db()
        r['renamed'] = _claim_name(target, action['canonical'])
    return r
