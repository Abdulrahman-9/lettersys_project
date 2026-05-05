# -*- coding: utf-8 -*-
"""
Dashboard & Reports Views - لوحة التحكم والتقارير
إحصائيات النظام، التقارير، النسخ الاحتياطي، سلة المهملات
"""

import json
import logging
import os
import shutil
import subprocess
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Case, CharField, Count, Q, Value, When
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from ..extraction_kinds import get_kind_label
from ..models import Attachment, AttachmentVersion, Book, BookHistory, Entity
from .helpers import staff_required

logger = logging.getLogger(__name__)


def _build_pg_dump_command(db_config, output_path):
    pg_dump_bin = os.environ.get("PG_DUMP_BIN") or shutil.which("pg_dump")
    if not pg_dump_bin:
        raise FileNotFoundError("pg_dump was not found. Install PostgreSQL client tools or set PG_DUMP_BIN.")

    command = [
        pg_dump_bin,
        "--format=custom",
        "--no-owner",
        "--no-privileges",
        f"--file={output_path}",
    ]
    if db_config.get("HOST"):
        command.append(f"--host={db_config['HOST']}")
    if db_config.get("PORT"):
        command.append(f"--port={db_config['PORT']}")
    if db_config.get("USER"):
        command.append(f"--username={db_config['USER']}")
    command.append(f"--dbname={db_config['NAME']}")
    return command


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

    # استعلام واحد بدلاً من 6 استعلامات منفصلة
    overdue_books = books.filter(
        due_date__lt=today
    ).exclude(final_status__in=["done", "hold"]).count()

    stats = books.aggregate(
        total=Count('id'),
        today_count=Count('id', filter=Q(date=today)),
        week_count=Count('id', filter=Q(date__gte=today - timedelta(days=7))),
        incoming_total=Count('id', filter=Q(kind__startswith='incoming')),
        outgoing_total=Count('id', filter=Q(kind__startswith='outgoing')),
    )

    ctx = {
        "total":          stats['total'],
        "today_count":    stats['today_count'],
        "week_count":     stats['week_count'],
        "overdue":        overdue_books,
        "incoming_total": stats['incoming_total'],
        "outgoing_total": stats['outgoing_total'],
    }
    return render(request, "core/dashboard.html", ctx)


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
    qs = Book.objects.filter(is_deleted=False) if request.user.is_superuser else Book.objects.filter(created_by=request.user, is_deleted=False)
    qs = qs.select_related("created_by").prefetch_related("issuing_entities", "receiving_entities")
    if kind == "incoming":
        qs = qs.filter(kind__startswith="incoming")
    elif kind == "outgoing":
        qs = qs.filter(kind__startswith="outgoing")
    elif kind in ("outgoing_internal", "outgoing_external", "incoming_internal", "incoming_external"):
        qs = qs.filter(kind=kind)

    if kind == "all":
        selected_kind_label = "كل الأنواع"
    elif kind == "incoming":
        selected_kind_label = "كل الوارد"
    elif kind == "outgoing":
        selected_kind_label = "كل الصادر"
    else:
        selected_kind_label = get_kind_label(kind)

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
    
    # المعالجة حسب التصفية الزمنية
    if bucket == "today":
        qs = qs.filter(due_date=today).exclude(final_status__in=["done", "hold"])
    elif bucket == "overdue":
        qs = qs.filter(due_date__lt=today).exclude(final_status__in=["done", "hold"])
    elif bucket == "upcoming":
        qs = qs.filter(due_date__gt=today).exclude(final_status__in=["done", "hold"])
    elif bucket == "completed":
        qs = qs.filter(final_status="done")
    elif bucket == "today_overdue":
        qs = qs.filter(due_date__lte=today).exclude(final_status__in=["done", "hold"])
    else:  # bucket == "all"
        pass  # بدون استثناء أي حالة

    # Annotate time_state at DB level instead of Python loop
    qs = qs.annotate(
        time_state=Case(
            When(final_status__in=("done", "hold"), then=Value("normal")),
            When(due_date__isnull=True, then=Value("normal")),
            When(due_date=today, then=Value("today")),
            When(due_date__gt=today, then=Value("future")),
            When(due_date__lt=today, then=Value("danger")),
            default=Value("normal"),
            output_field=CharField(),
        )
    )

    filtered = list(qs.order_by("due_date", "-date", "-id"))
    # Compute display phrases and stats in a single pass
    time_stats = {"overdue": 0, "today": 0, "future": 0, "normal": 0}
    stats = {"total": 0, "incoming": 0, "outgoing": 0, "pending": 0, "done": 0, "hold": 0}
    incoming = []
    outgoing = []
    ts_map = {"danger": "overdue", "today": "today", "future": "future", "normal": "normal"}
    for b in filtered:
        if b.due_date:
            diff = (b.due_date - today).days
            b.due_phrase = "مستحق اليوم" if diff == 0 else (f"مستحق بعد {diff} يوم" if diff > 0 else f"متأخر منذ {abs(diff)} يوم")
            b.delay_days = abs(diff)
        else:
            b.due_phrase = "-"
            b.delay_days = 0
        time_stats[ts_map.get(b.time_state, "normal")] += 1
        stats["total"] += 1
        if b.final_status in stats:
            stats[b.final_status] += 1
        if b.is_incoming:
            stats["incoming"] += 1
            incoming.append(b)
        elif b.is_outgoing:
            stats["outgoing"] += 1
            outgoing.append(b)
    return render(
        request,
        "core/reports.html",
        {
            "stats": stats,
            "time_stats": time_stats,
            "books": filtered,
            "incoming": incoming,
            "outgoing": outgoing,
            "entities": Entity.objects.filter(is_active=True).order_by("name"),
            "selected_kind": kind,
            "selected_kind_label": selected_kind_label,
            "selected_entity": entity_id or "",
            "bucket": bucket,
            "due_start": due_start or "",
            "due_end": due_end or "",
        },
    )


@login_required
def restore_book(request, pk):
    """
    استعادة كتاب محذوف من سلة المهملات
    
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
def restore_attachment(request, attachment_id):
    """
    استعادة مرفق محذوف
    
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
    from ..encryption import encrypt_file
    
    db_config = settings.DATABASES["default"]
    default_dir = Path("D:/trackbackup")
    if not default_dir.exists():
        default_dir = settings.BASE_DIR / "backups"
    default_dir.mkdir(parents=True, exist_ok=True)
    suggested_name = f"pg_backup_{timezone.now().strftime('%Y%m%d_%H%M')}.dump"

    if request.method == "POST":
        target_directory = Path(request.POST.get("target_directory") or default_dir)
        file_name = Path(request.POST.get("file_name") or suggested_name).name
        if not file_name.endswith(".dump"):
            file_name += ".dump"
        target_directory.mkdir(parents=True, exist_ok=True)
        target_path = target_directory / file_name
        try:
            env = os.environ.copy()
            if db_config.get("PASSWORD"):
                env["PGPASSWORD"] = str(db_config["PASSWORD"])
            subprocess.run(
                _build_pg_dump_command(db_config, target_path),
                check=True,
                capture_output=True,
                text=True,
                env=env,
            )
            encrypted_path = encrypt_file(target_path)
            messages.success(request, f"تم إنشاء نسخة PostgreSQL احتياطية مشفرة: {encrypted_path}")
        except FileNotFoundError as exc:
            logger.error("pg_dump executable is unavailable: %s", exc, exc_info=True)
            messages.error(request, "تعذر العثور على pg_dump. ثبّت أدوات PostgreSQL أو عيّن PG_DUMP_BIN.")
        except subprocess.CalledProcessError as exc:
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
        prefix     = request.POST.get("prefix", "قديم-")

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
