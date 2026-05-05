from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.utils import timezone
from datetime import timedelta

from core.models import Entity, Book


class Command(BaseCommand):
    help = "[DEV-ONLY] Seed demo books to showcase all incoming/outgoing states and stages."
    # ⚠️ DEV-ONLY: This command creates test/demo data for development and testing.
    # Do NOT run in production. Use --reset flag to clean up previously seeded data.

    def add_arguments(self, parser):
        parser.add_argument('--user', dest='username', help='Username to assign as created_by')
        parser.add_argument('--reset', action='store_true', help='Delete previously seeded DEMO books before seeding')

    def handle(self, *args, **options):
        User = get_user_model()
        username = options.get('username')
        user = None

        if username:
            try:
                user = User.objects.get(username=username)
            except User.DoesNotExist:
                self.stderr.write(self.style.ERROR(f"User '{username}' not found."))
                return
        else:
            user = User.objects.filter(is_superuser=True).first() or User.objects.first()
            if not user:
                user = User.objects.create_user('demo', password='demo1234')
                self.stdout.write(self.style.WARNING("No users found. Created demo user: demo / demo1234"))

        if options.get('reset'):
            deleted, _ = Book.objects.filter(our_number__startswith='DEMO-').delete()
            self.stdout.write(self.style.WARNING(f"Reset: deleted {deleted} DEMO rows"))

        # Entities
        issuer, _ = Entity.objects.get_or_create(name='قسم الصادرة', defaults={'etype': 'issuer'})
        receiver, _ = Entity.objects.get_or_create(name='قسم الواردة', defaults={'etype': 'receiver'})
        partner, _ = Entity.objects.get_or_create(name='شركة النفط', defaults={'etype': 'both'})

        today = timezone.localdate()

        def make_book(kind: str, days_ago: int, final_status: str, numtag: str):
            date = today - timedelta(days=days_ago)
            bn = f"DEMO-{kind}-{final_status}-{days_ago}-{numtag}"
            b, created = Book.objects.get_or_create(
                our_number=bn,
                defaults={
                    'sender_number': f"IN-{days_ago}-{numtag}" if kind == 'incoming' else '',
                    'title': f"سجل تجريبي ({'صادر' if kind=='outgoing' else 'وارد'})",
                    'secret_level': 'normal',
                    'date': date,
                    'margin': '',
                    'final_status': final_status,
                    'created_by': user,
                    'kind': kind,
                }
            )
            if created:
                if kind == 'outgoing':
                    b.issuing_entities.add(issuer)
                    b.receiving_entities.add(partner)
                else:
                    b.issuing_entities.add(partner)
                    b.receiving_entities.add(receiver)
            else:
                b.date = date
                b.final_status = final_status
                b.kind = kind
                b.title = f"سجل تجريبي ({'صادر' if kind=='outgoing' else 'وارد'})"
                b.save()
            return b

        # Incoming: pending/done/hold (recent + overdue)
        make_book('incoming', 0, 'pending', 'A')      # قيد المتابعة حديث
        make_book('incoming', 2, 'hold', 'B')         # الحفظ حديث
        make_book('incoming', 1, 'done', 'C')         # منجز حديث
        make_book('incoming', 9, 'pending', 'D')      # قيد المتابعة متأخر (>7)
        make_book('incoming', 10, 'hold', 'E')        # الحفظ متأخر (>7)

        # Outgoing: stages based on date (pending = قيد الإرسال/معلق/متأخر), done = مجاب
        make_book('outgoing', 0, 'pending', 'O1')     # قيد الإرسال (≤ 4)
        make_book('outgoing', 5, 'pending', 'O2')     # معلق (5–7)
        make_book('outgoing', 9, 'pending', 'O3')     # متأخر (>7)
        make_book('outgoing', 3, 'done', 'O4')        # مجاب

        self.stdout.write(self.style.SUCCESS("Seeded demo books successfully. افتح /books/ وشاهد جميع الحالات."))

