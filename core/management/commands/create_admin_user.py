from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
import os

class Command(BaseCommand):
    help = 'Create a superuser — credentials must be supplied via environment variables'

    def handle(self, *args, **options):
        username = os.environ.get('ADMIN_USERNAME', '').strip()
        password = os.environ.get('ADMIN_PASSWORD', '').strip()
        email    = os.environ.get('ADMIN_EMAIL', '').strip()

        if not username or not password:
            raise CommandError(
                'Set ADMIN_USERNAME and ADMIN_PASSWORD environment variables before running this command.\n'
                'Example: ADMIN_USERNAME=admin ADMIN_PASSWORD=s3cur3P@ss python manage.py create_admin_user'
            )

        if len(password) < 12:
            raise CommandError('ADMIN_PASSWORD must be at least 12 characters.')

        User = get_user_model()
        if not User.objects.filter(username=username).exists():
            User.objects.create_superuser(username=username, password=password, email=email)
            self.stdout.write(self.style.SUCCESS(f'Superuser "{username}" created.'))
        else:
            self.stdout.write(self.style.WARNING(f'User "{username}" already exists.'))
