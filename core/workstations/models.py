import uuid
from datetime import timedelta

from django.conf import settings
from django.db import models
from django.db.models.functions import Lower
from django.utils import timezone

HEARTBEAT_INTERVAL = 30
ONLINE_TTL = 90
SCANNER_TTL = 600
TOKEN_LIFETIME = timedelta(days=90)
PAIRING_TTL = timedelta(minutes=10)


class Workstation(models.Model):
    class State(models.TextChoices):
        PAIRING = 'pairing', 'بانتظار اكتمال الربط'
        ACTIVE = 'active', 'مفعّل'
        REVOKED = 'revoked', 'موقوف'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    client_uuid = models.UUIDField(unique=True)
    name = models.CharField(max_length=80)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    machine_name = models.CharField(max_length=100, blank=True)
    state = models.CharField(max_length=10, choices=State.choices, default=State.PAIRING)
    blocked_by_admin = models.BooleanField(default=False)
    token_hash = models.CharField(max_length=64, unique=True)
    token_issued_at = models.DateTimeField()
    expires_at = models.DateTimeField()
    last_seen = models.DateTimeField(null=True, blank=True)
    agent_version = models.CharField(max_length=20, blank=True)
    naps2_available = models.BooleanField(default=False)
    scanner_state = models.CharField(max_length=16, default='unknown')
    scanner_names = models.JSONField(default=list)
    scanner_checked_at = models.DateTimeField(null=True, blank=True)
    registered_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']
        constraints = [
            models.UniqueConstraint(Lower('name'), name='workstations_unique_name_ci'),
        ]

    @property
    def connection_state(self):
        now = timezone.now()
        if self.state == self.State.REVOKED or not self.owner.is_active:
            return 'revoked'
        if self.expires_at <= now:
            return 'expired'
        if self.state == self.State.PAIRING:
            return 'pairing'
        if self.last_seen and (now - self.last_seen).total_seconds() <= ONLINE_TTL:
            return 'online'
        return 'offline'

    @property
    def current_scanner_state(self):
        if self.connection_state != 'online':
            return 'unknown'
        if not self.naps2_available:
            return 'missing_naps2'
        if not self.scanner_checked_at or (
            timezone.now() - self.scanner_checked_at
        ).total_seconds() > SCANNER_TTL:
            return 'unknown'
        return self.scanner_state
