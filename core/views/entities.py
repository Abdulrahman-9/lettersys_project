# -*- coding: utf-8 -*-
"""
Entities Views - معالجات الجهات
إدارة الجهات (المرسل والمستقبل) مع عمليات CRUD و API
"""

import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from ..forms import EntityForm
from ..models import Book, Entity
from .helpers import staff_required

logger = logging.getLogger(__name__)


def _archive_entity_name_on_books(entity):
    """
    قبل حذف الجهة نهائياً، يُلصَق اسمها كنصّ في حقول الأرشيف JSON
    لكل كتاب مرتبط بها (مُصدِراً أو مستلِماً)، ليبقى السجل التاريخي مقروءاً.
    لا يلمس قائمة الكتب من حيث الوجود؛ فقط M2M المرتبط سيُقطع تلقائياً عند الحذف.
    """
    name = (entity.name or "").strip()
    if not name:
        return
    issued_qs = Book.objects.filter(issuing_entities=entity)
    for book in issued_qs.only("id", "archived_issuing_names"):
        names = list(book.archived_issuing_names or [])
        if name not in names:
            names.append(name)
            Book.objects.filter(pk=book.pk).update(archived_issuing_names=names)
    received_qs = Book.objects.filter(receiving_entities=entity)
    for book in received_qs.only("id", "archived_receiving_names"):
        names = list(book.archived_receiving_names or [])
        if name not in names:
            names.append(name)
            Book.objects.filter(pk=book.pk).update(archived_receiving_names=names)


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
    entities_qs = (
        Entity.objects
        .filter(is_active=True)
        .annotate(
            issued_count=Count(
                'issued_books',
                filter=Q(issued_books__is_deleted=False),
                distinct=True,
            ),
            received_count=Count(
                'received_books',
                filter=Q(received_books__is_deleted=False),
                distinct=True,
            ),
        )
        .order_by("name")
    )
    if request.method == "POST":
        # ── حذف مفرد عبر النموذج المحلّي للجدول/البطاقة ──
        if "delete_single" in request.POST:
            eid = request.POST.get("delete_single")
            logger.info("entity_list POST delete_single id=%r by user=%s", eid, request.user)
            entity = Entity.objects.filter(id=eid).first()
            if entity:
                name = entity.name
                _archive_entity_name_on_books(entity)
                entity.delete()
                messages.success(
                    request,
                    f"تم حذف الجهة '{name}' نهائياً (وتم حفظ اسمها كنصّ في الكتب المرتبطة بها).",
                )
            else:
                logger.warning("entity_list delete_single: id=%r NOT FOUND", eid)
                messages.warning(request, "الجهة غير موجودة (قد تكون محذوفة مسبقاً).")
            return redirect("entity_list")

        # ── حذف جماعي ──
        if request.POST.get("delete_selected"):
            selected = request.POST.getlist("selected")
            logger.info("entity_list POST delete_selected ids=%s by user=%s", selected, request.user)
            if selected:
                qs = Entity.objects.filter(id__in=selected)
                count = 0
                for entity in list(qs):
                    _archive_entity_name_on_books(entity)
                    entity.delete()
                    count += 1
                messages.success(
                    request,
                    f"تم حذف {count} جهة نهائياً (مع حفظ أسمائها كنصّ في الكتب).",
                )
            else:
                messages.info(request, "لم يتم تحديد أي جهة.")
            return redirect("entity_list")

        logger.warning(
            "entity_list POST without recognized action; keys=%s",
            list(request.POST.keys()),
        )

    # Pagination
    from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
    paginator = Paginator(entities_qs, 50)
    page = request.GET.get("page")
    try:
        entities = paginator.page(page)
    except PageNotAnInteger:
        entities = paginator.page(1)
    except EmptyPage:
        entities = paginator.page(paginator.num_pages)

    # إجماليات بسيطة (تشمل كل الصفحات لا الصفحة الحالية فقط)
    totals = {
        'all': entities_qs.count(),
        'issuer': entities_qs.filter(etype='issuer').count(),
        'receiver': entities_qs.filter(etype='receiver').count(),
        'both': entities_qs.filter(etype='both').count(),
    }

    return render(
        request,
        "core/entity_list.html",
        {
            "entities": entities,
            "paginator": paginator,
            "totals": totals,
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
    نقطة نهاية مخصّصة لحذف جهة واحدة نهائياً.
    تُستدعى من نموذج مستقل (mini-form) لكل صف/بطاقة.
    """
    logger.info("entity_delete POST pk=%s by user=%s", pk, request.user)
    entity = Entity.objects.filter(pk=pk).first()
    if not entity:
        logger.warning("entity_delete: pk=%s NOT FOUND", pk)
        messages.warning(request, "الجهة غير موجودة (قد تكون محذوفة مسبقاً).")
        return redirect("entity_list")
    name = entity.name
    _archive_entity_name_on_books(entity)
    entity.delete()
    logger.info("entity_delete: deleted pk=%s name=%r", pk, name)
    messages.success(
        request,
        f"تم حذف الجهة '{name}' نهائياً (وتم حفظ اسمها كنصّ في الكتب المرتبطة بها).",
    )
    return redirect("entity_list")


@staff_required
@require_http_methods(["POST"])
def entity_bulk_delete(request):
    """
    حذف جماعي لجهات محدّدة. يقبل قائمة `selected` من نموذج الجدول.
    """
    selected = request.POST.getlist("selected")
    logger.info("entity_bulk_delete POST ids=%s by user=%s", selected, request.user)
    if not selected:
        messages.info(request, "لم يتم تحديد أي جهة للحذف.")
        return redirect("entity_list")
    qs = Entity.objects.filter(id__in=selected)
    count = 0
    for entity in list(qs):
        _archive_entity_name_on_books(entity)
        entity.delete()
        count += 1
    messages.success(request, f"تم حذف {count} جهة نهائياً (مع حفظ أسمائها كنصّ في الكتب).")
    return redirect("entity_list")
