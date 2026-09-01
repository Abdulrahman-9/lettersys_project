"""
import_engine.py
================
محرك الاستيراد الذكي - يحوّل بيانات النظام القديم إلى نماذج LetterSys

الاستخدام من Django management command:
    python manage.py import_legacy --file export/sample_data.json --dry-run
    python manage.py import_legacy --file export/sample_data.json --confirm
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from django.contrib.auth.models import User
from django.db import transaction
from django.utils import timezone

from core.models import Book, Entity, BookHistory, Tag

logger = logging.getLogger('lettersys.import')


# ── نتيجة استيراد سجل واحد ────────────────────────────────────
@dataclass
class ImportResult:
    success: bool
    book_id: Optional[int] = None
    our_number: str = ''
    original_number: str = ''
    message: str = ''
    skipped: bool = False
    error: str = ''


# ── ملخص الاستيراد الكلي ──────────────────────────────────────
@dataclass
class ImportSummary:
    total: int = 0
    created: int = 0
    skipped: int = 0
    failed: int = 0
    errors: list = field(default_factory=list)
    entities_created: int = 0

    def print_report(self):
        print("\n" + "="*50)
        print("  تقرير الاستيراد")
        print("="*50)
        print(f"  إجمالي السجلات:    {self.total:>6,}")
        print(f"  ✅ تم إنشاؤها:     {self.created:>6,}")
        print(f"  ⏭️  تم تخطيها:      {self.skipped:>6,}")
        print(f"  ❌ فشل:            {self.failed:>6,}")
        print(f"  🏢 جهات جديدة:     {self.entities_created:>6,}")
        if self.errors:
            print(f"\n  أول {min(5, len(self.errors))} أخطاء:")
            for err in self.errors[:5]:
                print(f"    • {err}")
        print("="*50)


class LegacyImportEngine:
    """
    محرك استيراد البيانات القديمة.

    يقرأ ملف JSON مُصدَّر من SQL Server ويستورده إلى قاعدة بيانات LetterSys.
    يدعم dry_run لمعاينة النتائج قبل التطبيق الفعلي.
    """

    # ── خرائط التحويل ────────────────────────────────────────

    # STATUS_MAP لم يعد مستخدماً (المتابعة موحَّدة الآن).
    # تُرحَّل الحالات القديمة عبر is_archived في import_one.

    KIND_MAP = {
        'incoming': 'incoming_external', 'وارد': 'incoming_external',
        'outgoing': 'outgoing_external', 'صادر': 'outgoing_external',
        'incoming_internal': 'incoming_internal', 'وارد داخلي': 'incoming_internal',
        'incoming_external': 'incoming_external', 'وارد خارجي': 'incoming_external',
        'outgoing_internal': 'outgoing_internal', 'صادر داخلي': 'outgoing_internal',
        'outgoing_external': 'outgoing_external', 'صادر خارجي': 'outgoing_external',
        '1': 'incoming_external', '2': 'outgoing_external',
        '3': 'incoming_internal', '4': 'outgoing_internal',
    }

    SECRET_MAP = {
        'normal': 'normal', 'اعتيادي': 'normal', 'عادي': 'normal', '0': 'normal',
        'secret': 'secret', 'سري': 'secret', '1': 'secret',
        'topsecret': 'topsecret', 'سري للغاية': 'topsecret', '2': 'topsecret',
    }

    def __init__(self, field_map: dict, import_user: User,
                 dry_run: bool = True, number_prefix: str = ''):
        """
        field_map: تعيين أسماء حقول النظام القديم → حقول LetterSys
                   مثال: {'LetterNo': 'our_number', 'Subject': 'title', ...}
        """
        self.field_map = field_map
        self.import_user = import_user
        self.dry_run = dry_run
        self.number_prefix = number_prefix
        self.summary = ImportSummary()
        self._entity_cache: dict[str, Entity] = {}

    # ── الدالة الرئيسية ───────────────────────────────────────

    def import_from_file(self, json_file: Path) -> ImportSummary:
        """يستورد جميع السجلات من ملف JSON."""
        with open(json_file, encoding='utf-8') as f:
            records = json.load(f)

        if isinstance(records, dict):
            # قد يكون المفتاح هو اسم الجدول
            records = list(records.values())[0] if records else []

        logger.info("بدء الاستيراد: %d سجل | dry_run=%s", len(records), self.dry_run)
        self.summary.total = len(records)

        for i, row in enumerate(records, 1):
            try:
                result = self._import_one(row)
                if result.success:
                    if result.skipped:
                        self.summary.skipped += 1
                    else:
                        self.summary.created += 1
                else:
                    self.summary.failed += 1
                    self.summary.errors.append(f"سجل {i}: {result.error}")
            except Exception as e:
                self.summary.failed += 1
                self.summary.errors.append(f"سجل {i}: استثناء غير متوقع — {e}")
                logger.exception("خطأ في سجل %d", i)

            if i % 100 == 0:
                logger.info("تقدم: %d/%d", i, len(records))

        return self.summary

    # ── معالجة سجل واحد ──────────────────────────────────────

    @transaction.atomic
    def _import_one(self, row: dict) -> ImportResult:
        """يستورد سجلاً واحداً مع rollback تلقائي عند الفشل."""
        # 1. استخراج وتحويل الحقول
        our_number = self._get(row, 'our_number', '')
        title = self._get(row, 'title', 'بدون عنوان')
        raw_date = self._get(row, 'date', None)
        raw_sender_date = self._get(row, 'sender_date', None)
        raw_kind = self._get(row, 'kind', 'incoming_external')
        raw_secret = self._get(row, 'secret_level', 'normal')
        margin = self._get(row, 'margin', '')
        sender_number = self._get(row, 'sender_number', '')
        raw_due_date = self._get(row, 'due_date', None)
        raw_archived = self._get(row, 'is_archived', None)  # عَلَم أرشفة صريح من المصدر
        issuing_name = self._get(row, 'issuing_entity', '')
        receiving_name = self._get(row, 'receiving_entity', '')

        # 2. التحقق من المدخلات الإلزامية
        if not title or not title.strip():
            return ImportResult(success=False, error="العنوان فارغ")

        # 3. تحويل أرقام الكتب
        # صفٌّ بلا رقم يبقى **بلا رقم** — استثناءٌ معتمَد في النظام. كان يُسَكّ له
        # `auto-3` وهو رقمٌ مخترع لا يوجد على أي ورقة، وخارج نحو الترقيم
        # (`core/numbering.py`) فلا يُعرض صحيحاً ولا يُوجَد بالبحث ولا يُفرَز.
        original_number = our_number
        if not our_number:
            our_number = ''
        elif Book.objects.filter(our_number=our_number).exists():
            # تعارض: مع بادئة نميّز الرقم، وبلا بادئة (الافتراضي الآن) نتخطّى الموجود
            # (سلوك الاستعادة الآمن — لا نُنشئ نسخة مكرّرة بعلامة).
            our_number = f"{self.number_prefix}{our_number}"
            if not self.number_prefix or Book.objects.filter(our_number=our_number).exists():
                return ImportResult(
                    success=True, skipped=True,
                    message=f"تخطي: الرقم {original_number} موجود مسبقاً"
                )

        # 4. تحويل القيم
        book_date = self._parse_date(raw_date) or date.today()
        sender_date = self._parse_date(raw_sender_date)
        due_date = self._parse_date(raw_due_date)
        kind = self.KIND_MAP.get(str(raw_kind).strip().lower(), 'incoming_external')
        secret_level = self.SECRET_MAP.get(str(raw_secret).strip().lower(), 'normal')
        # المنطق الموحَّد:
        #   - لو المصدر يحدّد is_archived صراحةً ⇒ نأخذه
        #   - وإلا: وجود due_date يعني نشط، فارغ يعني مؤرشف ابتداءً
        if raw_archived is not None:
            archived_str = str(raw_archived).strip().lower()
            is_archived_value = archived_str in ('1', 'true', 'yes', 'on', 'مؤرشف', 'منتهي', 'منتهية')
        else:
            is_archived_value = (due_date is None)

        if self.dry_run:
            return ImportResult(
                success=True,
                our_number=our_number,
                original_number=original_number,
                message=f"[dry_run] سيُنشأ: {our_number} | {title[:40]}"
            )

        # 5. إنشاء الجهات
        issuing_entity = self._get_or_create_entity(issuing_name) if issuing_name else None
        receiving_entity = self._get_or_create_entity(receiving_name) if receiving_name else None

        # 6. إنشاء الكتاب
        book = Book.objects.create(
            our_number=our_number,
            sender_number=sender_number,
            title=title.strip(),
            date=book_date,
            sender_date=sender_date,
            kind=kind,
            secret_level=secret_level,
            margin=(margin or '').strip(),
            is_archived=is_archived_value,
            due_date=due_date,
            created_by=self.import_user,
        )

        if issuing_entity:
            book.issuing_entities.add(issuing_entity)
        if receiving_entity:
            book.receiving_entities.add(receiving_entity)

        # وسم الاستيراد
        tag, _ = Tag.objects.get_or_create(
            slug='legacy-import',
            defaults={'name': 'بيانات مستوردة', 'color': '#ff9800'}
        )
        book.tags.add(tag)

        # 7. سجل تاريخي
        BookHistory.objects.create(
            book=book,
            action='create',
            by=self.import_user,
            notes=f'استورد من النظام القديم — الرقم الأصلي: {original_number}',
        )

        return ImportResult(
            success=True,
            book_id=book.pk,
            our_number=our_number,
            original_number=original_number,
        )

    # ── دوال مساعدة ──────────────────────────────────────────

    def _get(self, row: dict, lettersys_field: str, default):
        """يُرجع قيمة الحقل من السجل القديم باستخدام field_map."""
        old_key = self.field_map.get(lettersys_field, lettersys_field)
        # بحث غير حساس لحالة الأحرف
        for k, v in row.items():
            if k.lower() == old_key.lower():
                return v
        return default

    def _get_or_create_entity(self, name: str) -> Optional[Entity]:
        """يجلب أو ينشئ جهة بالاسم مع caching."""
        name = name.strip()
        if not name:
            return None
        if name in self._entity_cache:
            return self._entity_cache[name]
        entity, created = Entity.objects.get_or_create(
            name=name,
            defaults={'etype': 'both', 'is_active': True}
        )
        if created:
            self.summary.entities_created += 1
            logger.info("جهة جديدة: %s", name)
        self._entity_cache[name] = entity
        return entity

    @staticmethod
    def _parse_date(value) -> Optional[date]:
        """يحاول تحويل قيمة متعددة الأشكال إلى date."""
        if not value:
            return None
        if isinstance(value, date):
            return value
        value = str(value).strip()
        formats = [
            '%Y-%m-%d', '%d/%m/%Y', '%d-%m-%Y',
            '%Y/%m/%d', '%Y-%m-%dT%H:%M:%S',
            '%Y-%m-%d %H:%M:%S',
        ]
        for fmt in formats:
            try:
                return datetime.strptime(value, fmt).date()
            except ValueError:
                continue
        # احتياط: التقط بادئة التاريخ ISO من سلاسل datetime غير المتوقّعة
        # (microseconds/منطقة زمنية لا تطابق أي صيغة أعلاه)
        try:
            return datetime.strptime(value[:10], '%Y-%m-%d').date()
        except ValueError:
            return None
