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

        # استثناء الكتب التي صُدر لها إشعار overdue من قبل (مهما كان تاريخه)
        already_notified = set(
            BookHistory.objects.filter(action='overdue').values_list('book_id', flat=True)
        )

        new_overdue = [b for b in overdue_qs if b.id not in already_notified]

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
