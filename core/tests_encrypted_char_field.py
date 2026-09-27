"""8.6‑أ — ``EncryptedCharField``: الحرّاسُ الخمسة المطلوبون في Merge9 §8.6‑أ.

1. ``dumpdata``/المُسلسِل لا يحوي الصريح (``value_to_string`` ⟵ ``enc::``).
2. ``loaddata`` لصريحٍ يُخزَّن مشفَّراً (``raw=True`` يمرّ بـ``get_prep_value``).
3. لا تشفيرَ مضاعفاً لقيمةٍ ``enc::``.
4. ``QuerySet.update()`` يشفّر.
5. مفتاحٌ مبدَّل: القيمةُ تبقى ``enc::`` في الذاكرة وفي القاعدة، بلا استثناءٍ وبلا سكّ.
"""

import io
import json
from unittest import mock

from django.core import serializers
from django.core.management import call_command
from django.db import connection
from django.test import TestCase

from core import encryption
from core.encryption import encrypt_text, is_encrypted
from core.models import AIIntegrationSettings, EmailSettings

PLAIN = 'Sekret-Pass-2026!'


def _raw(table, column, pk):
    with connection.cursor() as cursor:
        cursor.execute(f'SELECT {column} FROM {table} WHERE id = %s', [pk])
        return cursor.fetchone()[0]


class EncryptedCharFieldGuardTests(TestCase):

    def setUp(self):
        self.row = EmailSettings.get()
        self.row.smtp_password = PLAIN
        self.row.save()

    def test_1_serializer_emits_enc_prefix_never_plaintext(self):
        out = serializers.serialize('json', [EmailSettings.objects.get(pk=self.row.pk)])
        self.assertNotIn(PLAIN, out)
        self.assertIn('"smtp_password": "enc::', out)

    def test_2_loaddata_of_plaintext_is_stored_encrypted(self):
        payload = [{
            'model': 'core.aiintegrationsettings',
            'pk': 9901,
            'fields': {'provider': 'azure', 'azure_key': PLAIN,
                       'updated_at': '2026-09-10T00:00:00Z'},
        }]
        with mock.patch('sys.stdin', io.StringIO(json.dumps(payload))):
            call_command('loaddata', '-', '--format=json', verbosity=0)
        raw = _raw('core_aiintegrationsettings', 'azure_key', 9901)
        self.assertTrue(is_encrypted(raw), 'loaddata كتب المفتاحَ صريحاً (raw=True تخطّى التشفير)')
        self.assertEqual(AIIntegrationSettings.objects.get(pk=9901).azure_key, PLAIN)

    def test_3_no_double_encryption(self):
        token = encrypt_text(PLAIN)
        self.row.smtp_password = token          # قيمةٌ مشفَّرةٌ سلفاً تُسنَد كما هي
        self.row.save()
        self.assertEqual(_raw('core_emailsettings', 'smtp_password', self.row.pk), token)
        self.assertEqual(EmailSettings.objects.get(pk=self.row.pk).smtp_password, PLAIN)

    def test_4_queryset_update_encrypts(self):
        EmailSettings.objects.filter(pk=self.row.pk).update(imap_password=PLAIN)
        raw = _raw('core_emailsettings', 'imap_password', self.row.pk)
        self.assertTrue(is_encrypted(raw), 'update() كتب الصريح')
        self.assertNotEqual(raw, PLAIN)
        self.assertEqual(EmailSettings.objects.get(pk=self.row.pk).imap_password, PLAIN)

    def test_5_rotated_key_leaves_enc_untouched_without_raising(self):
        stored = _raw('core_emailsettings', 'smtp_password', self.row.pk)
        self.assertTrue(is_encrypted(stored))
        with mock.patch.object(encryption, 'decrypt_text', side_effect=ValueError('bad key')):
            loaded = EmailSettings.objects.get(pk=self.row.pk)
            self.assertEqual(loaded.smtp_password, stored, 'القيمةُ لم تبقَ enc:: عند فشل الفكّ')
            loaded.save()                       # إعادةُ الحفظ لا تشفّر ثانيةً ولا تصرخ
        self.assertEqual(_raw('core_emailsettings', 'smtp_password', self.row.pk), stored)

    def test_values_and_values_list_are_decrypted_too(self):
        """المحوّلاتُ تسري على values() — كان المزيجُ القديم يفكّ الكائنَ وحدَه."""
        self.assertEqual(
            EmailSettings.objects.filter(pk=self.row.pk).values_list('smtp_password', flat=True).get(),
            PLAIN)

    def test_mixin_is_gone_so_there_is_one_path(self):
        from core import models
        self.assertFalse(hasattr(models, 'EncryptedFieldsMixin'))
        self.assertFalse(hasattr(EmailSettings, 'ENCRYPTED_FIELDS'))
