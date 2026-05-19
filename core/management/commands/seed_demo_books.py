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

        def make_book(kind: str, days_ago: int, due_offset, archived: bool, numtag: str):
            """
            due_offset: None ⇒ بلا متابعة (مؤرشف ابتداءً) | int ⇒ أيام من اليوم (سالب=متأخر، 0=اليوم، موجب=قيد المتابعة)
            archived:   True يفرض الأرشفة حتى لو كان due_offset موجباً (محاكاة إنهاء المتابعة يدوياً)
            """
            date = today - timedelta(days=days_ago)
            due_date = (today + timedelta(days=due_offset)) if due_offset is not None else None
            tag = "ARCH" if archived else (f"DUE{due_offset}" if due_offset is not None else "NODUE")
            bn = f"DEMO-{kind}-{tag}-{days_ago}-{numtag}"
            b, created = Book.objects.get_or_create(
                our_number=bn,
                defaults={
                    'sender_number': f"IN-{days_ago}-{numtag}" if kind == 'incoming' else '',
                    'title': f"سجل تجريبي ({'صادر' if kind=='outgoing' else 'وارد'})",
                    'secret_level': 'normal',
                    'date': date,
                    'margin': '',
                    'due_date': due_date,
                    'is_archived': archived or due_date is None,
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
                b.due_date = due_date
                b.is_archived = archived or due_date is None
                b.kind = kind
                b.title = f"سجل تجريبي ({'صادر' if kind=='outgoing' else 'وارد'})"
                b.save()
            return b

        # وارد: 4 حالات
        make_book('incoming', 0, 5,    False, 'A')   # قيد المتابعة (5 أيام بعد)
        make_book('incoming', 2, 0,    False, 'B')   # مستحق اليوم
        make_book('incoming', 9, -3,   False, 'D')   # متأخر (3 أيام)
        make_book('incoming', 1, None, True,  'C')   # مؤرشف (بلا متابعة)
        make_book('incoming', 10, 7,   True,  'E')   # مؤرشف يدوياً مع وجود due_date سابق

        # صادر: 4 حالات
        make_book('outgoing', 0, 7,    False, 'O1')  # قيد المتابعة
        make_book('outgoing', 5, 0,    False, 'O2')  # مستحق اليوم
        make_book('outgoing', 9, -5,   False, 'O3')  # متأخر
        make_book('outgoing', 3, None, True,  'O4')  # مؤرشف

        self.stdout.write(self.style.SUCCESS("Seeded demo books successfully. افتح /books/ وشاهد جميع الحالات."))

