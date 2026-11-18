"""الطريقُ من الخادم نفسه حين تُغلق البوّابةُ على المدير، أو يضيع كوكي جهاز الخادم.

    python manage.py devices_gate                   # الحالُ: الوضع والخادم والأكواد السارية
    python manage.py devices_gate --mode remind     # open | remind | only
    python manage.py devices_gate --declare-code    # كودُ إعلان الخادم (8 أرقام، 5 دقائق)
    python manage.py devices_gate --prune           # يحذف غيرَ المسجّل الذي لم يظهر 30 يوماً

مَن يشغّله جالسٌ على الخادم بصلاحيّة ملفّاته — فهو إثباتُ «أنا على الخادم» بلا متصفّح.
"""
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from core.devices import service
from core.devices.models import DevicePolicy, PairingCode


class Command(BaseCommand):
    help = 'حالُ بوّابة الأجهزة، وتغييرُ وضعها، وكودُ إعلان الخادم من الكونسول.'

    def add_arguments(self, parser):
        parser.add_argument('--mode', choices=[m for m, _ in DevicePolicy.MODE_CHOICES])
        parser.add_argument('--declare-code', action='store_true')
        parser.add_argument('--prune', action='store_true')

    def handle(self, *args, **opts):
        pol = service.policy()
        if opts['mode']:
            old = pol.mode
            pol.mode = opts['mode']
            pol.save(update_fields=['mode', 'updated_at'])
            self.stdout.write(f'mode: {old} -> {pol.mode}')
        if opts['declare_code']:
            code = service.issue_declare_code_console()
            self.stdout.write(f'server code: {code} (valid {int(service.DECLARE_TTL.total_seconds() // 60)} '
                              'minutes; type it on the Network and devices page of the server browser)')
        if opts['prune']:
            self.stdout.write(f'pruned: {service.prune()}')
        server = service.server_device(pol)
        open_codes = PairingCode.objects.filter(used_at__isnull=True, cancelled_at__isnull=True,
                                                expires_at__gt=timezone.now()).count()
        self.stdout.write(f'mode={pol.mode} server={server or "-"} open_codes={open_codes}')
        if pol.mode == DevicePolicy.MODE_ONLY and server is None:
            raise CommandError('mode is "only" but no server device is declared: run --mode remind')
