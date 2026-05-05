from django.core.management.base import BaseCommand
from django.utils import timezone
from django.contrib.auth.models import User
from django.db import models

from core.models import Book, BookHistory, Notification

class Command(BaseCommand):
    help = "✅ ACTIVE: Recalculate overdue state and notify admins when books become overdue."
    # This command should be scheduled to run daily (e.g., via Celery beat or cron).
    # It marks books as overdue when due_date < today and final_status is still pending/hold.

    def handle(self, *args, **kwargs):
        today = timezone.localdate()

        # المرشحون للتأخير: غير منجزة ولديهم موعد استحقاق في الماضي
        overdue_qs = Book.objects.filter(
            final_status__in=["pending", "hold"],
            due_date__lt=today,
        )

        # المرشحون لإزالة التأخير: إما منجزة أو لم يحن موعدها بعد
        clear_qs = Book.objects.filter(
            models.Q(final_status="done") | models.Q(due_date__gte=today) | models.Q(due_date__isnull=True),
            is_overdue=True,
        )

        promoted = 0  # أصبحت متأخرة الآن
        cleared = 0   # تمت إزالة التأخير

        # علّم المتأخرة وأرسل إشعاراً عند الانتقال فقط
        admins = list(User.objects.filter(is_superuser=True))
        for book in overdue_qs:
            if not book.is_overdue:
                book.is_overdue = True
                book.save(update_fields=["is_overdue", "updated_at"])
                BookHistory.objects.create(book=book, action="overdue", by=None, notes="تجاوز موعد الاستحقاق")
                for admin in admins:
                    Notification.objects.create(
                        user=admin,
                        message=f"الكتاب رقم {book.our_number} متأخر (تاريخ الاستحقاق {book.due_date}).",
                    )
                promoted += 1

        # أزل علامة التأخير عندما تصبح منجزة أو عاد موعدها صالحاً
        for book in clear_qs:
            book.is_overdue = False
            book.save(update_fields=["is_overdue", "updated_at"])
            cleared += 1

        self.stdout.write(self.style.SUCCESS(f"Overdue promoted: {promoted}, cleared: {cleared}"))
