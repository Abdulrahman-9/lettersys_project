# -*- coding: utf-8 -*-
"""
Dashboard & Reports Views - لوحة التحكم والتقارير
إحصائيات النظام، التقارير، النسخ الاحتياطي، سلة المهملات
"""

import json
import logging
import os
from datetime import timedelta
from pathlib import Path
from subprocess import CalledProcessError

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from ..backup_service import create_encrypted_pg_backup, default_backup_dir
from ..extraction.kinds import get_kind_label
from ..models import Attachment, AttachmentVersion, Book, BookHistory, Entity
from .helpers import staff_required

logger = logging.getLogger(__name__)


@login_required
def dashboard(request):
    """
    لوحة تحكم مختصرة تعرض إحصائيات أساسية
    
    المميزات:
    - إجمالي الكتب
    - كتب اليوم والأسبوع
    - الكتب المتأخرة
    - إحصائيات الكتب الواردة والصادرة
    
    Args:
        request: HTTP request
    
    Returns:
        Rendered dashboard template with statistics
    """
    books = Book.objects.filter(is_deleted=False) if request.user.is_superuser else Book.objects.filter(created_by=request.user, is_deleted=False)
    today = timezone.localdate()

    # المنطق الموحَّد: نشط = is_archived=False AND due_date IS NOT NULL
    active_q = Q(is_archived=False, due_date__isnull=False)

    stats = books.aggregate(
        total=Count('id'),
        today_count=Count('id', filter=Q(date=today)),
        week_count=Count('id', filter=Q(date__gte=today - timedelta(days=7))),
        incoming_total=Count('id', filter=Q(kind__startswith='incoming')),
        outgoing_total=Count('id', filter=Q(kind__startswith='outgoing')),
        incoming_active=Count('id', filter=Q(kind__startswith='incoming') & active_q),
        incoming_archived=Count('id', filter=Q(kind__startswith='incoming') & ~active_q),
        outgoing_active=Count('id', filter=Q(kind__startswith='outgoing') & active_q),
        outgoing_archived=Count('id', filter=Q(kind__startswith='outgoing') & ~active_q),
        overdue=Count('id', filter=active_q & Q(due_date__lt=today)),
        due_today=Count('id', filter=active_q & Q(due_date=today)),
        pending=Count('id', filter=active_q & Q(due_date__gt=today)),
    )

    ctx = {
        "total":            stats['total'],
        "today_count":      stats['today_count'],
        "week_count":       stats['week_count'],
        "overdue":          stats['overdue'],
        "due_today":        stats['due_today'],
        "pending":          stats['pending'],
        "incoming_total":   stats['incoming_total'],
        "outgoing_total":   stats['outgoing_total'],
        "incoming_pending": stats['incoming_active'],
        "incoming_done":    stats['incoming_archived'],
        "outgoing_pending": stats['outgoing_active'],
        "outgoing_done":    stats['outgoing_archived'],
    }
    return render(request, "core/dashboard.html", ctx)


@login_required
def followup_activity_report(request):
    """
    تقرير تطوّر حالة المتابعة — يعتمد على BookHistory لمعرفة:
      - الكتب التي انتقلت إلى "متأخر" خلال الفترة
      - الكتب التي أُرشفت يدوياً (إنهاء متابعة)
      - الكتب التي أُعيد فتح متابعتها
    """
    from ..models import BookHistory

    try:
        days = int(request.GET.get('days', '7'))
        days = max(1, min(days, 90))
    except (ValueError, TypeError):
        days = 7

    cutoff = timezone.now() - timedelta(days=days)
    base_history = BookHistory.objects.filter(created_at__gte=cutoff).select_related('book', 'by')

    if not (request.user.is_superuser or request.user.is_staff):
        base_history = base_history.filter(book__created_by=request.user)

    became_overdue = list(
        base_history.filter(action='overdue').order_by('-created_at')[:50]
    )
    manually_archived = list(
        base_history.filter(action='status', notes__icontains='أُرشف').order_by('-created_at')[:50]
    )
    reopened = list(
        base_history.filter(action='status', notes__icontains='أُعيد فتح').order_by('-created_at')[:50]
    )

    stats = {
        'days': days,
        'became_overdue': len(became_overdue),
        'manually_archived': len(manually_archived),
        'reopened': len(reopened),
    }

    return render(request, 'core/followup_activity_report.html', {
        'stats': stats,
        'became_overdue': became_overdue,
        'manually_archived': manually_archived,
        'reopened': reopened,
        'days': days,
        'window_start': cutoff,
    })


def _reports_qs(request):
    """يبني queryset التقارير المفلتر والمرتّب حسب فلاتر الصفحة (kind/entity/date/bucket).
    مصدر تصفية واحد مشترك بين عرض التقارير والتصدير (DRY). يُعيد (qs, meta)."""
    qs = Book.objects.filter(is_deleted=False) if request.user.is_superuser else Book.objects.filter(created_by=request.user, is_deleted=False)
    qs = qs.select_related("created_by").prefetch_related("issuing_entities", "receiving_entities")
    kind = request.GET.get("kind", "all")
    if kind == "incoming":
        qs = qs.filter(kind__startswith="incoming")
    elif kind == "outgoing":
        qs = qs.filter(kind__startswith="outgoing")
    elif kind in ("outgoing_internal", "outgoing_external", "incoming_internal", "incoming_external"):
        qs = qs.filter(kind=kind)

    if kind == "all":
        kind_label = "كل الأنواع"
    elif kind == "incoming":
        kind_label = "كل الوارد"
    elif kind == "outgoing":
        kind_label = "كل الصادر"
    else:
        kind_label = get_kind_label(kind)

    entity_id = request.GET.get("entity")
    if entity_id and entity_id.isdigit():
        qs = qs.filter(Q(issuing_entities__id=entity_id) | Q(receiving_entities__id=entity_id)).distinct()

    today = timezone.localdate()
    due_start = request.GET.get("due_start")
    due_end = request.GET.get("due_end")
    start_date = None
    end_date = None
    try:
        if due_start:
            start_date = timezone.datetime.fromisoformat(due_start).date()
        if due_end:
            end_date = timezone.datetime.fromisoformat(due_end).date()
    except ValueError:
        start_date = end_date = None

    if start_date and end_date:
        if start_date > end_date:
            start_date, end_date = end_date, start_date
        qs = qs.filter(due_date__range=(start_date, end_date))
    elif start_date:
        qs = qs.filter(due_date__gte=start_date)
    elif end_date:
        qs = qs.filter(due_date__lte=end_date)

    bucket = request.GET.get("bucket", "") or "today_overdue"
    active_qs = qs.filter(is_archived=False, due_date__isnull=False)
    archived_qs = qs.filter(Q(is_archived=True) | Q(due_date__isnull=True))
    if bucket == "today":
        qs = active_qs.filter(due_date=today)
    elif bucket == "overdue":
        qs = active_qs.filter(due_date__lt=today)
    elif bucket == "upcoming":
        qs = active_qs.filter(due_date__gt=today)
    elif bucket == "completed":
        qs = archived_qs
    elif bucket == "today_overdue":
        qs = active_qs.filter(due_date__lte=today)
    # else: bucket == "all" — لا فلتر إضافي

    qs = qs.order_by("due_date", "-date", "-id")
    return qs, {
        "kind": kind, "kind_label": kind_label,
        "entity_id": entity_id or "", "bucket": bucket,
        "due_start": due_start or "", "due_end": due_end or "", "today": today,
    }


@login_required
def reports(request):
    """
    تقارير الكتب المستحقة مع فلاتر وتصدير/طباعة
    
    الفلاتر المتاحة:
    - النوع (وارد/صادر)
    - الجهة
    - نطاق تاريخ الاستحقاق
    - التصنيف الزمني (اليوم، متأخر، قادم، مكتمل)
    
    Args:
        request: HTTP request with filter parameters
    
    Returns:
        Rendered reports template with filtered books and statistics
    """
    qs, _m = _reports_qs(request)
    kind = _m["kind"]
    selected_kind_label = _m["kind_label"]
    entity_id = _m["entity_id"]
    bucket = _m["bucket"]
    due_start = _m["due_start"]
    due_end = _m["due_end"]
    today = _m["today"]

    # ── إحصاءات عبر تجميع DB (بلا تحميل كل الصفوف في الذاكرة) ──
    active = Q(is_archived=False, due_date__isnull=False)
    agg = qs.aggregate(
        total=Count("id"),
        incoming=Count("id", filter=Q(kind__startswith="incoming")),
        outgoing=Count("id", filter=Q(kind__startswith="outgoing")),
        overdue=Count("id", filter=active & Q(due_date__lt=today)),
        due_today=Count("id", filter=active & Q(due_date=today)),
        pending=Count("id", filter=active & Q(due_date__gt=today)),
        archived=Count("id", filter=Q(is_archived=True) | Q(due_date__isnull=True)),
    )
    stats = {k: (v or 0) for k, v in agg.items()}
    time_stats = {key: stats.get(key, 0) for key in ("overdue", "due_today", "pending", "archived")}

    # ── ترقيم العرض: يمنع تحميل آلاف الكتب دفعةً (مهمّ على ذاكرة محدودة) ──
    page_obj = Paginator(qs, 200).get_page(request.GET.get("page"))
    books = list(page_obj.object_list)
    for b in books:
        if b.due_date:
            diff = (b.due_date - today).days
            b.due_phrase = "مستحق اليوم" if diff == 0 else (f"مستحق بعد {diff} يوم" if diff > 0 else f"متأخر منذ {abs(diff)} يوم")
        else:
            b.due_phrase = "-"

    # الحفاظ على فلاتر الاستعلام عند تنقّل الصفحات
    page_params = request.GET.copy()
    page_params.pop("page", None)

    # هوية المؤسسة + ملخّص الفلاتر لترويسة الطباعة الاحترافية
    from ..models import EmailSettings
    org = EmailSettings.get()
    selected_entity_name = ""
    if entity_id and entity_id.isdigit():
        _e = Entity.objects.filter(pk=entity_id).only("name").first()
        selected_entity_name = _e.name if _e else ""
    bucket_labels = {
        "all": "كل الحالات", "today_overdue": "المتأخرة والمستحقة اليوم",
        "overdue": "المتأخرة فقط", "today": "مستحقة اليوم",
        "upcoming": "مستحقة للفترة القادمة", "completed": "المؤرشفة (انتهت المتابعة)",
    }

    return render(
        request,
        "core/reports.html",
        {
            "stats": stats,
            "time_stats": time_stats,
            "books": books,
            "page_obj": page_obj,
            "total": stats["total"],
            "querystring": page_params.urlencode(),
            "entities": Entity.objects.filter(is_active=True).order_by("name"),
            "selected_kind": kind,
            "selected_kind_label": selected_kind_label,
            "selected_entity": entity_id or "",
            "selected_entity_name": selected_entity_name,
            "bucket": bucket,
            "bucket_label": bucket_labels.get(bucket, bucket),
            "due_start": due_start or "",
            "due_end": due_end or "",
            "org": org,
        },
    )


@login_required
def reports_export(request):
    """تصدير نتائج التقرير المفلترة كملف CSV (يفتح مباشرة في Excel) — نفس فلاتر صفحة التقارير.
    يبثّ الصفوف تدريجياً فيبقى خفيفاً على الذاكرة مهما كبر العدد."""
    import csv
    import io
    from django.http import StreamingHttpResponse

    qs, meta = _reports_qs(request)
    status_labels = {"pending": "قيد المتابعة", "due_today": "مستحق اليوم",
                     "overdue": "متأخر", "archived": "مؤرشف"}
    # أعمدة تطابق جدول الصفحة الرسمي: تاريخا الكتاب (قيدنا + كتاب الجهة رقماً
    # وتاريخاً) حاضران، ولا معرّفات قاعدة بيانات داخلية في مخرجات رسمية.
    HEADERS = ["رقم القيد", "تاريخ القيد", "العنوان", "النوع",
               "الجهة المُصدِرة", "الجهة المستقبِلة",
               "رقم كتاب الجهة", "تاريخ كتاب الجهة", "تاريخ الإدخال",
               "تاريخ الاستحقاق", "الحالة", "الملاحظات"]

    def _rows():
        buf = io.StringIO()
        buf.write("﻿")  # BOM (يُكتب صراحةً) كي يعرض Excel العربية بلا تشويش
        csv.writer(buf).writerow(HEADERS)
        yield buf.getvalue()
        for b in qs.iterator(chunk_size=500):
            buf = io.StringIO()
            issuing = "، ".join(e.name for e in b.issuing_entities.all())
            receiving = "، ".join(e.name for e in b.receiving_entities.all())
            csv.writer(buf).writerow([
                b.our_number or "",
                b.date.isoformat() if b.date else "",
                b.title or "",
                b.kind_label,
                issuing,
                receiving,
                b.sender_number or "",
                b.sender_date.isoformat() if b.sender_date else "",
                b.created_at.date().isoformat() if b.created_at else "",
                b.due_date.isoformat() if b.due_date else "",
                status_labels.get(b.followup_state, b.followup_state or ""),
                b.margin or "",
            ])
            yield buf.getvalue()

    resp = StreamingHttpResponse(_rows(), content_type="text/csv; charset=utf-8")
    resp["Content-Disposition"] = 'attachment; filename="report_%s.csv"' % meta["today"].isoformat()
    return resp


@login_required
@require_POST
def restore_book(request, pk):
    """
    استعادة كتاب محذوف من سلة المهملات (POST فقط — يُعدّل الحالة فلا يُسمح بـ GET)
    
    Args:
        request: HTTP request
        pk: معرف الكتاب
    
    Returns:
        Redirect to trash list with success message
    """
    book = get_object_or_404(Book, pk=pk, is_deleted=True)
    if not (request.user.is_superuser or request.user.is_staff or book.created_by == request.user):
        messages.error(request, "غير مصرح بالاستعادة.")
        return redirect("trash_list")
    book.is_deleted = False
    book.deleted_at = None
    book.deleted_by = None
    book.save(update_fields=["is_deleted", "deleted_at", "deleted_by"])
    Attachment.objects.filter(book=book, is_deleted=True).update(is_deleted=False, deleted_at=None, deleted_by=None)
    BookHistory.objects.create(book=book, action="restore", by=request.user)
    messages.success(request, "تمت استعادة الكتاب من سلة المهملات.")
    return redirect("trash_list")


@login_required
def purge_book(request, pk):
    """
    حذف كتاب نهائياً من قاعدة البيانات (لا يمكن الاستعادة)
    
    Args:
        request: HTTP POST request
        pk: معرف الكتاب
    
    Returns:
        Redirect to trash list with success message
    """
    book = get_object_or_404(Book, pk=pk)
    if not (request.user.is_superuser or request.user.is_staff):
        messages.error(request, "غير مصرح بالحذف النهائي.")
        return redirect("trash_list")
    if request.method != "POST":
        return redirect("trash_list")
    for att in book.attachments.all():
        for v in att.versions.all():
            try:
                v.file.delete(save=False)
            except Exception:
                pass
            v.delete()
        try:
            att.file.delete(save=False)
        except Exception:
            pass
        att.delete()
    book.delete()
    messages.success(request, "تم حذف الكتاب نهائياً.")
    return redirect("trash_list")


@login_required
@require_POST
def restore_attachment(request, attachment_id):
    """
    استعادة مرفق محذوف (POST فقط — يُعدّل الحالة فلا يُسمح بـ GET)
    
    Args:
        request: HTTP request
        attachment_id: معرف المرفق
    
    Returns:
        Redirect to trash list with success message
    """
    att = get_object_or_404(Attachment, id=attachment_id, is_deleted=True)
    if att.book.is_deleted:
        messages.error(request, "لا يمكن استعادة مرفق لكتاب محذوف.")
        return redirect("trash_list")
    if not (request.user.is_superuser or request.user.is_staff or att.book.created_by == request.user):
        messages.error(request, "غير مصرح بالاستعادة.")
        return redirect("trash_list")
    att.is_deleted = False
    att.deleted_at = None
    att.deleted_by = None
    att.save(update_fields=["is_deleted", "deleted_at", "deleted_by"])
    BookHistory.objects.create(book=att.book, action="restore-attachment", by=request.user, attachment=att)
    messages.success(request, "تمت استعادة المرفق.")
    return redirect("trash_list")


@login_required
def purge_attachment(request, attachment_id):
    """
    حذف مرفق نهائياً من قاعدة البيانات
    
    Args:
        request: HTTP POST request
        attachment_id: معرف المرفق
    
    Returns:
        Redirect to trash list with success message
    """
    att = get_object_or_404(Attachment, id=attachment_id)
    if not (request.user.is_superuser or request.user.is_staff):
        messages.error(request, "غير مصرح بالحذف النهائي.")
        return redirect("trash_list")
    if request.method != "POST":
        return redirect("trash_list")
    for v in att.versions.all():
        try:
            v.file.delete(save=False)
        except Exception:
            pass
        v.delete()
    try:
        att.file.delete(save=False)
    except Exception:
        pass
    att.delete()
    messages.success(request, "تم حذف المرفق نهائياً.")
    return redirect("trash_list")


@staff_required
def backup_database(request):
    """
    تنفيذ نسخة احتياطية من PostgreSQL باستخدام pg_dump مع التشفير
    
    المميزات:
    - إنشاء dump منطقي من PostgreSQL
    - تشفير النسخة الاحتياطية لحماية البيانات
    - عرض النسخ الاحتياطية الموجودة
    
    Args:
        request: HTTP request (GET or POST)
    
    Returns:
        Rendered backup template or redirect after backup creation
    """
    db_config = settings.DATABASES["default"]
    default_dir = default_backup_dir()
    suggested_name = f"pg_backup_{timezone.now().strftime('%Y%m%d_%H%M')}.dump"

    if request.method == "POST":
        target_directory = request.POST.get("target_directory") or default_dir
        file_name = request.POST.get("file_name") or suggested_name
        try:
            encrypted_path = create_encrypted_pg_backup(target_directory, file_name)
            messages.success(request, f"تم إنشاء نسخة PostgreSQL احتياطية مشفرة: {encrypted_path}")
        except FileNotFoundError as exc:
            logger.error("pg_dump executable is unavailable: %s", exc, exc_info=True)
            messages.error(request, "تعذر العثور على pg_dump. ثبّت أدوات PostgreSQL أو عيّن PG_DUMP_BIN.")
        except CalledProcessError as exc:
            logger.error("pg_dump failed: %s", exc.stderr, exc_info=True)
            messages.error(request, "فشل pg_dump أثناء إنشاء النسخة الاحتياطية. راجع إعدادات اتصال PostgreSQL.")
        except OSError as exc:
            logger.error("Backup file operation failed: %s", exc, exc_info=True)
            messages.error(request, "تعذر كتابة أو تشفير النسخة الاحتياطية في المسار المحدد.")
        return redirect("backup_database")

    backups = []
    if default_dir.exists():
        for f in default_dir.glob("*.dump.enc"):
            backups.append({"name": f.name, "size_mb": round(f.stat().st_size / (1024 * 1024), 2), "modified": timezone.datetime.fromtimestamp(f.stat().st_mtime)})
        backups = sorted(backups, key=lambda x: x["modified"], reverse=True)

    return render(
        request,
            "core/backup.html",
        {
            "database_name": db_config["NAME"],
            "database_host": db_config.get("HOST") or "localhost",
            "database_port": db_config.get("PORT") or "5432",
            "default_directory": default_dir,
            "suggested_name": suggested_name,
            "existing_backups": backups,
        },
    )


# ══════════════════════════════════════════════════════════════════
#  استعادة البيانات من قاعدة قديمة (SQL Server نوع ARCHMDOC)
# ══════════════════════════════════════════════════════════════════

@staff_required
def data_restore(request):
    """
    استعادة البيانات من قاعدة بريد قديمة عبر اتصال SQL Server.
    GET: نموذج الإدخال.
    POST action=discover: يتصل ويعرض جداول البريد وأعدادها.
    POST action=import:   ينفّذ الاستعادة الكاملة (كتب + جهات + مرفقات) بالتطبيع الصحيح.
    """
    from ..legacy_restore import LegacyRestoreEngine

    ctx = {
        'form': {
            'server': request.POST.get('server', 'localhost'),
            'database': request.POST.get('database', ''),
            'username': request.POST.get('username', 'sa'),
        },
        'book_count': Book.objects.count(),
    }

    if request.method == 'POST':
        action = request.POST.get('action', '')

        # ── طريقة 2: استعادة من ملف باكاب (.bak أو مضغوط) ──
        if action == 'restore_from_bak':
            bak_path = (request.POST.get('bak_path') or '').strip()
            bak_server = (request.POST.get('bak_server') or 'localhost').strip()
            bak_user = (request.POST.get('bak_user') or 'sa').strip()
            bak_pass = request.POST.get('bak_password') or ''
            restore_files = request.POST.get('restore_files') == 'on'
            mode = request.POST.get('merge_mode') or 'skip_existing'
            if mode not in ('fresh', 'skip_existing', 'update_existing'):
                mode = 'skip_existing'
            ctx['form']['bak_path'] = bak_path
            ctx['form']['bak_server'] = bak_server
            ctx['form']['bak_user'] = bak_user
            if not bak_path:
                messages.error(request, 'مسار ملف الباكاب مطلوب.')
                return render(request, 'core/data_restore.html', ctx)
            try:
                summary = LegacyRestoreEngine.restore_from_bak(
                    bak_path, sql_server=bak_server, admin_user=bak_user, admin_password=bak_pass,
                    created_by=request.user, restore_files=restore_files, mode=mode,
                )
                if summary.get('aborted'):
                    messages.warning(request, summary.get('reason', 'تم الإيقاف.'))
                else:
                    ctx['summary'] = summary
                    parts = []
                    if summary.get('books'):   parts.append(f"{summary['books']:,} كتاب جديد")
                    if summary.get('updated'): parts.append(f"{summary['updated']:,} مُحدَّث")
                    if summary.get('skipped'): parts.append(f"{summary['skipped']:,} متخطّى")
                    if restore_files and summary.get('files'): parts.append(f"{summary['files']:,} مرفق")
                    if summary.get('dedup_fixed'): parts.append(f"فُكّ {summary['dedup_fixed']} تكرار")
                    messages.success(request, "تمت الاستعادة من الملف: " + ("، ".join(parts) if parts else "لا تغييرات"))
                    _reseed_book_sequences()
            except Exception as e:
                logger.exception('restore_from_bak failed')
                messages.error(request, f'فشل أثناء الاستعادة من الملف: {e}')
            ctx['book_count'] = Book.objects.count()
            return render(request, 'core/data_restore.html', ctx)

        # ── طريقة 1: اتصال مباشر بقاعدة حية ──
        server = (request.POST.get('server') or 'localhost').strip()
        database = (request.POST.get('database') or '').strip()
        username = (request.POST.get('username') or 'sa').strip()
        password = request.POST.get('password') or ''

        if not database:
            messages.error(request, 'اسم قاعدة البيانات مطلوب.')
            return render(request, 'core/data_restore.html', ctx)

        engine = LegacyRestoreEngine(server, database, username, password)

        if action == 'discover':
            try:
                info = engine.discover()
                ctx['discovery'] = info
                if not info['tables']:
                    messages.warning(request, 'لم يُعثر على جداول بريد (IIMAIL_YYYY ...) في هذه القاعدة.')
                else:
                    total = sum(t['rows'] for t in info['tables'])
                    messages.success(request, f"اتصال ناجح — {len(info['tables'])} جدول، {total:,} سجل، السنوات: {', '.join(info['years'])}")
            except Exception as e:
                logger.exception('data_restore discover failed')
                messages.error(request, f'فشل الاتصال أو الاكتشاف: {e}')
            return render(request, 'core/data_restore.html', ctx)

        if action == 'import':
            restore_files = request.POST.get('restore_files') == 'on'
            mode = request.POST.get('merge_mode') or 'skip_existing'
            if mode not in ('fresh', 'skip_existing', 'update_existing'):
                mode = 'skip_existing'
            try:
                summary = engine.run(
                    created_by=request.user,
                    restore_files=restore_files,
                    mode=mode,
                )
                if summary.get('aborted'):
                    messages.warning(request, summary.get('reason', 'تم الإيقاف.'))
                else:
                    ctx['summary'] = summary
                    parts = []
                    if summary.get('books'):   parts.append(f"{summary['books']:,} كتاب جديد")
                    if summary.get('updated'): parts.append(f"{summary['updated']:,} مُحدَّث")
                    if summary.get('skipped'): parts.append(f"{summary['skipped']:,} متخطّى")
                    if restore_files and summary.get('files'): parts.append(f"{summary['files']:,} مرفق")
                    if summary.get('dedup_fixed'): parts.append(f"فُكّ {summary['dedup_fixed']} تكرار")
                    messages.success(request, "تمت الاستعادة: " + ("، ".join(parts) if parts else "لا تغييرات"))
                    _reseed_book_sequences()
            except Exception as e:
                logger.exception('data_restore import failed')
                messages.error(request, f'فشل أثناء الاستعادة: {e}')
            ctx['book_count'] = Book.objects.count()
            return render(request, 'core/data_restore.html', ctx)

    return render(request, 'core/data_restore.html', ctx)


@staff_required
def bak_browse(request):
    """
    متصفّح ملفات على جهاز الخادم لاختيار ملف باكاب — للقراءة فقط، يعرض المجلدات
    وملفات النسخ الاحتياطي فقط (.bak / .zip / .7z / .tar.gz). يُستخدَم من صفحة الاستعادة.
    """
    import os
    BACKUP_EXTS = ('.bak', '.zip', '.7z', '.tar.gz', '.tgz', '.gz')
    raw = (request.GET.get('path') or '').strip()

    # المستوى الأعلى: الأقراص + مجلدات سريعة
    if not raw or raw in ('/', '\\'):
        roots = []
        for letter in 'CDEFGHIJ':
            d = f"{letter}:\\"
            if os.path.isdir(d):
                roots.append(d)
        quick = []
        for q in ('D:\\Abdulrhman Backup', 'D:\\trackbackup', 'D:\\backups',
                  str(settings.BASE_DIR / 'backups'), os.path.expanduser('~\\Desktop'),
                  os.path.expanduser('~\\Downloads')):
            if os.path.isdir(q):
                quick.append(q)
        return JsonResponse({'is_root': True, 'path': '', 'parent': None, 'dirs': roots, 'quick': quick, 'files': []})

    path = os.path.abspath(raw)
    if not os.path.isdir(path):
        return JsonResponse({'error': 'المسار ليس مجلداً موجوداً.'}, status=400)
    try:
        entries = list(os.scandir(path))
    except PermissionError:
        return JsonResponse({'error': 'لا صلاحية وصول لهذا المجلد.'}, status=403)
    except OSError as e:
        return JsonResponse({'error': f'تعذّر الوصول: {e}'}, status=400)

    dirs, files = [], []
    for e in entries:
        try:
            if e.is_dir():
                dirs.append(e.name)
            elif e.is_file() and e.name.lower().endswith(BACKUP_EXTS):
                files.append({'name': e.name, 'size_mb': round(e.stat().st_size / (1024 * 1024), 1)})
        except OSError:
            continue
    dirs.sort(key=str.lower)
    files.sort(key=lambda x: x['name'].lower())

    # الأب: لو كنا في جذر قرص (مثل D:\) فالأب هو قائمة الأقراص
    norm = path.rstrip('\\/')
    if len(norm) == 2 and norm[1] == ':':       # "D:" → جذر القرص
        parent = ''
    else:
        parent = os.path.dirname(norm)
        if len(parent) == 2 and parent[1] == ':':
            parent = parent + '\\'
    return JsonResponse({'is_root': False, 'path': path, 'parent': parent, 'dirs': dirs, 'files': files})


def _reseed_book_sequences():
    """يضبط BookSequence.next_number لكل سجل على (أكبر تسلسل دائم موجود + 1).
    الترقيم دائم بلا سنة: يُحتسب فقط الأرقام بصيغة {R}{NNNN} (رقمية، أول خانة = رمز
    السجل، بلا بادئة سنة). الأرقام التاريخية YYYY{R}{NNNN} تُستبعَد — ليست في فضاء
    الترقيم الدائم. يُستدعى بعد الاستعادة كي لا تصطدم الأرقام الجديدة بالموجود."""
    from ..models import BookSequence
    for kind, reg in BookSequence.REGISTER_CODES.items():
        max_seq = 0
        for onum in Book.objects.filter(
            kind=kind, our_number__startswith=reg
        ).values_list('our_number', flat=True):
            if not onum.isdigit():
                continue
            # استبعاد التاريخي (يبدأ بسنة 2020-2099 وطوله ≥ 8)
            if len(onum) >= 8 and onum[:4].isdigit() and 2020 <= int(onum[:4]) <= 2099:
                continue
            seq_part = onum[len(reg):]
            if seq_part.isdigit():
                max_seq = max(max_seq, int(seq_part))
        obj, _c = BookSequence.objects.get_or_create(
            kind=kind, defaults={'next_number': 1, 'year': timezone.now().year}
        )
        obj.next_number = max_seq + 1 if max_seq else 1
        obj.save(update_fields=['next_number', 'updated_at'])


# ══════════════════════════════════════════════════════════════════
#  استيراد البيانات القديمة — Legacy Import
# ══════════════════════════════════════════════════════════════════

@login_required
@staff_required
def legacy_import_page(request):
    """صفحة استيراد البيانات القديمة — عرض الحالة وبدء الاستيراد."""
    export_dir = settings.BASE_DIR / "scripts" / "legacy_import" / "export"
    log_file   = export_dir / "restore.log"
    schema_file   = export_dir / "schema.json"
    counts_file   = export_dir / "row_counts.json"
    tables_file   = export_dir / "tables_list.json"
    sample_file   = export_dir / "sample_data.json"
    config_file   = export_dir / "import_config.json"

    # حالة الاستعادة
    restore_log   = log_file.read_text(encoding="utf-8") if log_file.exists() else ""
    restore_done  = schema_file.exists() and counts_file.exists()

    # بيانات الاستعداد للاستيراد
    schema  = json.loads(schema_file.read_text(encoding="utf-8"))   if schema_file.exists()  else []
    counts  = json.loads(counts_file.read_text(encoding="utf-8"))   if counts_file.exists()  else {}
    tables  = json.loads(tables_file.read_text(encoding="utf-8"))   if tables_file.exists()  else []
    config  = json.loads(config_file.read_text(encoding="utf-8"))   if config_file.exists()  else {}

    # مجموعة الأعمدة مرتبة حسب الجدول
    schema_by_table = {}
    for col in schema:
        schema_by_table.setdefault(col["table"], []).append(col)

    return render(request, "core/legacy_import.html", {
        "restore_done":    restore_done,
        "restore_log":     restore_log,
        "tables":          tables,
        "counts":          counts,
        "schema_by_table": schema_by_table,
        "config":          config,
        "total_records":   sum(v for v in counts.values() if isinstance(v, int)),
    })


@login_required
@staff_required
@require_POST
def legacy_import_run(request):
    """
    تشغيل الاستيراد الفعلي — يقبل POST مع:
      field_map  : JSON خريطة الحقول (old_name → lettersys_field)
      dry_run    : '1' للمعاينة، '0' للتطبيق
      table_name : اسم الجدول المراد استيراده
    """
    from ..import_engine import LegacyImportEngine

    export_dir   = settings.BASE_DIR / "scripts" / "legacy_import" / "export"
    sample_file  = export_dir / "sample_data.json"

    if not sample_file.exists():
        return JsonResponse({"ok": False, "error": "بيانات النظام القديم غير متوفرة — شغّل الاستعادة أولاً"}, status=400)

    try:
        field_map  = json.loads(request.POST.get("field_map", "{}"))
        dry_run    = request.POST.get("dry_run", "1") == "1"
        table_name = request.POST.get("table_name", "")
        prefix     = request.POST.get("prefix", "")

        all_data = json.loads(sample_file.read_text(encoding="utf-8"))
        records  = all_data.get(table_name, []) if table_name else []
        if not records:
            # محاولة بأول جدول متاح
            records = next(iter(all_data.values()), [])

        # حفظ بيانات العينة في ملف مؤقت
        import tempfile
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json",
                                         delete=False, encoding="utf-8") as tf:
            json.dump(records, tf, ensure_ascii=False)
            tmp_path = Path(tf.name)

        engine  = LegacyImportEngine(
            field_map=field_map,
            import_user=request.user,
            dry_run=dry_run,
            number_prefix=prefix,
        )
        summary = engine.import_from_file(tmp_path)
        tmp_path.unlink(missing_ok=True)

        return JsonResponse({
            "ok":      True,
            "dry_run": dry_run,
            "total":   summary.total,
            "created": summary.created,
            "skipped": summary.skipped,
            "failed":  summary.failed,
            "entities_created": summary.entities_created,
            "errors":  summary.errors[:10],
        })

    except Exception as e:
        logger.exception("legacy_import_run error")
        return JsonResponse({"ok": False, "error": str(e)}, status=500)


@login_required
@staff_required
def legacy_import_status(request):
    """API: حالة الاستعادة (يُستدعى بـ AJAX كل 5 ثوانٍ)."""
    export_dir = settings.BASE_DIR / "scripts" / "legacy_import" / "export"
    log_file   = export_dir / "restore.log"
    done       = (export_dir / "sample_data.json").exists()
    log_text   = ""
    if log_file.exists():
        lines    = log_file.read_text(encoding="utf-8").splitlines()
        log_text = "\n".join(lines[-20:])   # آخر 20 سطر فقط
    return JsonResponse({"done": done, "log": log_text})
