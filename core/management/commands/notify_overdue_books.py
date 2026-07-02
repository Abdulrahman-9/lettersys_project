# -*- coding: utf-8 -*-
"""
notify_overdue_books — يكتشف الكتب التي انتقلت إلى "متأخر" اليوم ويرسل إشعاراً
                       للمدراء/المُنشئ، ويُسجّل الحدث في BookHistory لتفادي التكرار.

التشغيل:
    python manage.py notify_overdue_books
    (يُنصح بجدولته يومياً عبر Celery beat أو cron)

المنطق:
- الكتب المتأخرة الآن = is_archived=False AND due_date < today
- لتفادي إشعار مكرر يومياً: نتحقّق من عدم وجود BookHistory(action='overdue') للكتاب.
"""
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from django.utils import timezone

from core.models import Book, BookHistory, Notification


class Command(BaseCommand):
    help = "اكتشف الكتب المتأخرة اليوم وأرسل إشعارات (مرة واحدة لكل كتاب)."

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', help='عرض ما سيُنفَّذ دون إرسال إشعارات فعلية')

    def handle(self, *args, **options):
        today = timezone.localdate()
        dry_run = options.get('dry_run', False)

        # الكتب المتأخرة حالياً (نشطة + due_date في الماضي)
        overdue_qs = Book.objects.filter(
            is_archived=False,
            due_date__lt=today,
            is_deleted=False,
        ).select_related('created_by')

        # تفادي تكرار التنبيه ضمن نفس دورة المتابعة — لكن السماح به في دورة جديدة:
        # الكتاب «متأخّر جديد» إذا لم يُسجَّل له تأخّر قط، أو أُعيد فتح متابعته بعد آخر تأخّر مُسجَّل
        # (هكذا يُحسب «كم مرة تأخّر» بدقّة عبر الدورات، ولا يُحرَم الكتاب المُعاد فتحه من التنبيه).
        overdue_ids = [b.id for b in overdue_qs]
        last_overdue = {}
        for bid, ts in BookHistory.objects.filter(
            action='overdue', book_id__in=overdue_ids
        ).values_list('book_id', 'created_at'):
            if bid not in last_overdue or ts > last_overdue[bid]:
                last_overdue[bid] = ts
        last_reopen = {}
        for bid, ts in BookHistory.objects.filter(
            action='status', book_id__in=overdue_ids, notes__icontains='فتح'
        ).values_list('book_id', 'created_at'):
            if bid not in last_reopen or ts > last_reopen[bid]:
                last_reopen[bid] = ts

        def _is_new_overdue(b):
            lo = last_overdue.get(b.id)
            if lo is None:
                return True  # لم يُسجَّل تأخّر قط
            lr = last_reopen.get(b.id)
            return lr is not None and lr > lo  # أُعيد الفتح بعد آخر تأخّر ⇒ دورة جديدة

        new_overdue = [b for b in overdue_qs if _is_new_overdue(b)]

        if not new_overdue:
            self.stdout.write(self.style.SUCCESS("لا توجد كتب متأخرة جديدة."))
            return

        admins = list(User.objects.filter(is_superuser=True))
        notified = 0

        for book in new_overdue:
            delay = (today - book.due_date).days
            msg = f"الكتاب رقم {book.our_number} متأخر منذ {delay} يوم (تاريخ الاستحقاق {book.due_date})."

            if dry_run:
                self.stdout.write(f"[DRY] {msg}")
                continue

            # إشعار للمدراء + المُنشئ
            recipients = set(admins)
            if book.created_by:
                recipients.add(book.created_by)
            for user in recipients:
                Notification.objects.create(user=user, message=msg)

            # سجل تاريخي يمنع التكرار في الأيام القادمة
            BookHistory.objects.create(
                book=book, action='overdue', by=None,
                notes=f"تجاوز موعد الاستحقاق منذ {delay} يوم"
            )
            notified += 1

        verb = "سيتم إرسال" if dry_run else "أُرسلت"
        self.stdout.write(self.style.SUCCESS(f"{verb} إشعارات لـ {len(new_overdue)} كتاب متأخر جديد."))
