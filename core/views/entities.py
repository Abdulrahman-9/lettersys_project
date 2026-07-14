# -*- coding: utf-8 -*-
"""
Entities Views - معالجات الجهات
إدارة الجهات (المرسل والمستقبل) مع عمليات CRUD و API
"""

import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Case, Count, IntegerField, OuterRef, Q, Subquery, Value, When
from django.db.models.functions import Coalesce
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods

from ..forms import EntityForm
from ..models import Book, Entity
from .helpers import staff_required

logger = logging.getLogger(__name__)


@login_required
@require_http_methods(["GET"])
def entity_list_api(request):
    """
    API لجلب قائمة الجهات مع أكوادها للاستخدام في الاستخراج الذكي
    يُستخدم للتعرف على الأكواز (ش3, ش4) وتحويلها لأسماء الجهات
    
    Returns:
        JsonResponse: قائمة الجهات النشطة مع البيانات الأساسية
    """
    try:
        entities = Entity.objects.filter(is_active=True).values('id', 'name', 'code', 'etype')
        return JsonResponse({
            'success': True,
            'entities': list(entities)
        })
    except Exception as e:
        logger.error(f'Error loading entity list: {e}', exc_info=True)
        return JsonResponse({
            'success': False,
            'message': 'فشل تحميل قائمة الجهات'
        }, status=500)


@staff_required
def entity_list(request):
    """
    عرض وإدارة قائمة الجهات
    
    يدعم:
    - عرض جميع الجهات النشطة
    - حذف جهة واحدة أو متعدد
    - تعطيل الجهات بدلاً من الحذف النهائي
    
    Args:
        request: HTTP request (GET or POST)
    
    Returns:
        Rendered template with entities list
    """
    # فلتر اللغة (ar/en/all) + بحث server-side + حالة (نشطة/معطّلة)
    lang_filter = (request.GET.get('lang') or 'all').strip()
    search_q = (request.GET.get('q') or '').strip()
    status_filter = (request.GET.get('status') or 'active').strip()
    showing_inactive = status_filter == 'inactive'

    # عدّ كتب كل جهة عبر استعلامين فرعيين مستقلّين بدل ضمّ علاقتَي M2M
    # (issued/received) في استعلام واحد — الضمّ المزدوج يُنتج ضرباً ديكارتياً
    # (I×R صفّاً لكل جهة) كان يستغرق ~17 ثانية. الاستعلام الفرعي يلغي الانفجار.
    _issued_sq = (
        Book.objects
        .filter(issuing_entities=OuterRef('pk'), is_deleted=False)
        .order_by()
        .values('issuing_entities')
        .annotate(c=Count('id'))
        .values('c')
    )
    _received_sq = (
        Book.objects
        .filter(receiving_entities=OuterRef('pk'), is_deleted=False)
        .order_by()
        .values('receiving_entities')
        .annotate(c=Count('id'))
        .values('c')
    )
    entities_qs = (
        Entity.objects
        .filter(is_active=not showing_inactive)
        .annotate(
            issued_count=Coalesce(Subquery(_issued_sq, output_field=IntegerField()), 0),
            received_count=Coalesce(Subquery(_received_sq, output_field=IntegerField()), 0),
        )
    )

    if lang_filter == 'ar':
        entities_qs = entities_qs.filter(name__regex=r'^[؀-ۿ]')
    elif lang_filter == 'en':
        entities_qs = entities_qs.filter(name__regex=r'^[A-Za-z0-9]')

    # ── بحث: name أو code ──
    if search_q:
        entities_qs = entities_qs.filter(
            Q(name__icontains=search_q) | Q(code__icontains=search_q)
        )

    # ترتيب: الجهات المرمّزة أولاً، ثم العربية، ثم الإنجليزية، كل قسم بالاسم.
    # تعليقات ORM بدل .extra() المهجورة.
    _has_code_q = ~Q(code__isnull=True) & ~Q(code='')
    entities_qs = entities_qs.annotate(
        _has_code=Case(When(_has_code_q, then=Value(1)),
                       default=Value(0), output_field=IntegerField()),
        _is_arabic=Case(When(name__regex=r'^[؀-ۿ]', then=Value(1)),
                        default=Value(0), output_field=IntegerField()),
    ).order_by('-_has_code', '-_is_arabic', 'name')
    # Pagination — 100 لكل صفحة (كان 50 صغيراً وضيّعت العربية بعد الإنجليزية)
    from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
    paginator = Paginator(entities_qs, 100)
    page = request.GET.get("page")
    try:
        entities = paginator.page(page)
    except PageNotAnInteger:
        entities = paginator.page(1)
    except EmptyPage:
        entities = paginator.page(paginator.num_pages)

    # كل الإجماليات في استعلام تجميعي واحد (بدل 8 استعلامات count منفصلة)
    viewed = not showing_inactive
    agg = Entity.objects.aggregate(
        active_count=Count('id', filter=Q(is_active=True)),
        inactive_count=Count('id', filter=Q(is_active=False)),
        all=Count('id', filter=Q(is_active=viewed)),
        with_code=Count('id', filter=Q(is_active=viewed) & _has_code_q),
        no_code=Count('id', filter=Q(is_active=viewed) & ~_has_code_q),
        arabic=Count('id', filter=Q(is_active=viewed, name__regex=r'^[؀-ۿ]')),
        english=Count('id', filter=Q(is_active=viewed, name__regex=r'^[A-Za-z0-9]')),
    )
    totals = {
        'all': agg['all'], 'with_code': agg['with_code'], 'no_code': agg['no_code'],
        'arabic': agg['arabic'], 'english': agg['english'],
    }
    active_count = agg['active_count']
    inactive_count = agg['inactive_count']

    return render(
        request,
        "core/entity_list.html",
        {
            "entities": entities,
            "paginator": paginator,
            "totals": totals,
            "lang_filter": lang_filter,
            "search_q": search_q,
            "status_filter": status_filter,
            "showing_inactive": showing_inactive,
            "active_count": active_count,
            "inactive_count": inactive_count,
        },
    )


@login_required
def entity_detail(request, pk):
    """
    صفحة تفاصيل الجهة — الكتب المصدرة والمستلمة
    """
    entity = get_object_or_404(Entity, pk=pk, is_active=True)

    issued_books = (
        entity.issued_books
        .select_related("created_by")
        .prefetch_related("receiving_entities")
        .order_by("-date")
    )
    received_books = (
        entity.received_books
        .select_related("created_by")
        .prefetch_related("issuing_entities")
        .order_by("-date")
    )

    from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger

    page_issued = request.GET.get("pi", 1)
    page_received = request.GET.get("pr", 1)

    pag_issued = Paginator(issued_books, 25)
    pag_received = Paginator(received_books, 25)

    try:
        issued_page = pag_issued.page(page_issued)
    except (PageNotAnInteger, EmptyPage):
        issued_page = pag_issued.page(1)

    try:
        received_page = pag_received.page(page_received)
    except (PageNotAnInteger, EmptyPage):
        received_page = pag_received.page(1)

    return render(request, "core/entity_detail.html", {
        "entity": entity,
        "issued_books": issued_page,
        "received_books": received_page,
        "issued_count": pag_issued.count,
        "received_count": pag_received.count,
    })


@staff_required
def entity_create(request):
    """
    إنشاء جهة جديدة (يبقيك في صفحة الإضافة)
    
    Args:
        request: HTTP request (GET or POST)
    
    Returns:
        Rendered template with entity form
    """
    if request.method == "POST":
        form = EntityForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "تم حفظ الجهة بنجاح.")
            return redirect("entity_create")
    else:
        form = EntityForm()
    return render(request, "core/entity_form.html", {"form": form, "is_edit": False})


@staff_required
def entity_edit(request, pk):
    """
    تعديل جهة قائمة (يعيد للقائمة بعد الحفظ)
    
    Args:
        request: HTTP request (GET or POST)
        pk: معرف الجهة
    
    Returns:
        Rendered template with entity edit form and statistics
    """
    entity = get_object_or_404(Entity, pk=pk)
    if request.method == "POST":
        form = EntityForm(request.POST, instance=entity)
        if form.is_valid():
            form.save()
            messages.success(request, "تم تحديث الجهة بنجاح.")
            return redirect("entity_list")
    else:
        form = EntityForm(instance=entity)
    return render(
        request,
        "core/entity_form.html",
        {
            "form": form,
            "is_edit": True,
            "editing_entity": entity,
            "total_entities": Entity.objects.count(),
            "recent_entities": list(Entity.objects.order_by("-id").values_list("name", flat=True)[:5]),
            "suggested_entities": [],
            "type_counts": {
                "issuer": Entity.objects.filter(etype="issuer").count(),
                "receiver": Entity.objects.filter(etype="receiver").count(),
                "both": Entity.objects.filter(etype="both").count(),
            },
        },
    )


@staff_required
@require_http_methods(["POST"])
def entity_delete(request, pk):
    """
    تعطيل جهة واحدة (حذف ناعم): تُضبط is_active=False فتُخفى من القوائم
    وأدوات الاختيار، مع بقاء سجلّها وروابطها بالكتب سليمةً وقابلةً للاسترجاع.
    تُستدعى من نموذج مستقل (mini-form) لكل صف/بطاقة.
    """
    logger.info("entity_delete (soft) POST pk=%s by user=%s", pk, request.user)
    entity = Entity.objects.filter(pk=pk).first()
    if not entity:
        logger.warning("entity_delete: pk=%s NOT FOUND", pk)
        messages.warning(request, "الجهة غير موجودة.")
        return redirect("entity_list")
    if entity.is_active:
        entity.is_active = False
        entity.save(update_fields=["is_active"])
    logger.info("entity_delete: deactivated pk=%s name=%r", pk, entity.name)
    messages.success(
        request,
        f"تم تعطيل الجهة «{entity.name}» — أُخفيت من القوائم مع الحفاظ على سجلّها وروابطها بالكتب.",
    )
    return redirect("entity_list")


@staff_required
@require_http_methods(["POST"])
def entity_bulk_delete(request):
    """
    تعطيل جماعي (حذف ناعم) لجهات محدّدة. يقبل قائمة `selected` من نموذج الجدول.
    """
    selected = request.POST.getlist("selected")
    logger.info("entity_bulk_delete (soft) POST ids=%s by user=%s", selected, request.user)
    if not selected:
        messages.info(request, "لم يتم تحديد أي جهة.")
        return redirect("entity_list")
    count = Entity.objects.filter(id__in=selected, is_active=True).update(is_active=False)
    messages.success(
        request,
        f"تم تعطيل {count} جهة — أُخفيت من القوائم مع الحفاظ على سجلّاتها وروابطها بالكتب.",
    )
    return redirect("entity_list")


@staff_required
@require_http_methods(["POST"])
def entity_restore(request, pk):
    """استرجاع جهة معطّلة — تُضبط is_active=True فتعود للقوائم وأدوات الاختيار."""
    entity = Entity.objects.filter(pk=pk).first()
    if not entity:
        messages.warning(request, "الجهة غير موجودة.")
        return redirect("entity_list")
    if not entity.is_active:
        entity.is_active = True
        entity.save(update_fields=["is_active"])
    logger.info("entity_restore: pk=%s name=%r by user=%s", pk, entity.name, request.user)
    messages.success(request, f"تم استرجاع الجهة «{entity.name}» — عادت للقوائم.")
    return redirect(f"{reverse('entity_list')}?status=inactive")


@staff_required
@require_http_methods(["POST"])
def entity_bulk_restore(request):
    """استرجاع جماعي لجهات معطّلة محدّدة."""
    selected = request.POST.getlist("selected")
    logger.info("entity_bulk_restore POST ids=%s by user=%s", selected, request.user)
    if not selected:
        messages.info(request, "لم يتم تحديد أي جهة.")
        return redirect(f"{reverse('entity_list')}?status=inactive")
    count = Entity.objects.filter(id__in=selected, is_active=False).update(is_active=True)
    messages.success(request, f"تم استرجاع {count} جهة — عادت للقوائم.")
    return redirect(f"{reverse('entity_list')}?status=inactive")


@staff_required
def entity_merge(request):
    """صفحة دمج الجهات المكرّرة — كشف إملائي + **مرشّحات ذكية** (تصحيف/التصاق/
    تشريف) + عنقود يدوي + دمج مؤكَّد. المرشّحات اقتراحٌ للمراجعة لا دمجٌ آلي."""
    from ..entity_dedup import (build_manual_cluster, find_duplicate_clusters,
                                find_semantic_candidates, merge_entities)

    if request.method == "POST":
        canonical_id = (request.POST.get("canonical") or "").strip()
        victim_ids = request.POST.getlist("victim")
        if not canonical_id.isdigit() or not victim_ids:
            messages.warning(request, "اختر الجهة الأمّ وجهةً واحدة على الأقل للدمج.")
            return redirect("entity_merge")
        try:
            result = merge_entities(canonical_id, victim_ids)
        except Entity.DoesNotExist:
            messages.error(request, "تعذّر الدمج — إحدى الجهات غير موجودة.")
            return redirect("entity_merge")
        if result["merged"] == 0:
            messages.info(request, "لم تُحدَّد جهات قابلة للدمج.")
        else:
            logger.info("entity_merge: canonical=%s victims=%s by user=%s",
                        canonical_id, victim_ids, request.user)
            messages.success(
                request,
                f"تم الدمج: استوعبت «{result['canonical'].name}» {result['merged']} "
                f"جهة، ونُقل {result['moved_books']} ربط كتاب.",
            )
        return redirect("entity_merge")

    clusters = find_duplicate_clusters()
    smart_clusters = []
    if request.GET.get("smart") == "1":
        # مسحٌ أثقل (مقارنة أزواج) — يُشغَّل بطلب المستخدم لا في كل تحميل
        smart_clusters = find_semantic_candidates()
    manual_cluster = None
    ids_raw = (request.GET.get("ids") or "").strip()
    if ids_raw:
        ids = [int(x) for x in ids_raw.split(",") if x.strip().isdigit()]
        if len(ids) >= 2:
            manual_cluster = build_manual_cluster(ids)
        if ids_raw and manual_cluster is None:
            messages.info(request, "تعذّر بناء عنقود يدوي — تأكّد من تحديد جهتين نشطتين على الأقل.")
    return render(
        request,
        "core/entity_merge.html",
        {"clusters": clusters, "smart_clusters": smart_clusters,
         "smart_on": request.GET.get("smart") == "1",
         "manual_cluster": manual_cluster},
    )
