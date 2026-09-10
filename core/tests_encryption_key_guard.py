# -*- coding: utf-8 -*-
"""حارسُ سكّ مفتاح التعمية (Merge9 §10.4 — دَين T10.4).

السكُّ الصامتُ هو الخطرُ الصامت: خادمٌ بلا `.encryption_key` كان يسكّ واحداً عند
أوّل قراءةٍ لـ`EmailSettings`، فيبدو النظامُ سليماً بينما فكُّ الكلمات المشفَّرة
بالمفتاح الأوّل يفشل **بصمت** (`from_db` يبتلع الفشل). هذه الاختباراتُ تثبّت أنّ
الغيابَ يصرخ ولا يسكّ.
"""

import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from django.test import SimpleTestCase

from core import encryption
from core.encryption import ALLOW_CREATE_ENV, EncryptionKeyMissing


class EncryptionKeyMintGuardTests(SimpleTestCase):
    """`get_or_create_encryption_key` — يقرأ الموجود، ولا يسكّ بلا إذن."""

    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.key_path = Path(self._tmp.name) / '.encryption_key'

    def _patch_key_path(self):
        patcher = mock.patch.object(encryption, 'ENCRYPTION_KEY_FILE', self.key_path)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _env(self, allow):
        """بيئةٌ معزولة: العلَمُ مضبوطٌ أو محذوفٌ صراحةً (settings_test يضبطه)."""
        env = dict(os.environ)
        if allow is None:
            env.pop(ALLOW_CREATE_ENV, None)
        else:
            env[ALLOW_CREATE_ENV] = allow
        patcher = mock.patch.dict(os.environ, env, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    # ── القراءة: المفتاحُ الموجودُ يُعاد كما هو ──────────────────────────────
    def test_reads_existing_key_without_minting(self):
        self._patch_key_path()
        self._env(None)
        self.key_path.write_bytes(b'x' * 44)
        mtime = self.key_path.stat().st_mtime_ns

        self.assertEqual(encryption.get_or_create_encryption_key(), b'x' * 44)
        self.assertEqual(self.key_path.stat().st_mtime_ns, mtime)

    # ── الحارس: الغيابُ يصرخ ولا يسكّ ───────────────────────────────────────
    def test_missing_key_raises_and_does_not_mint(self):
        self._patch_key_path()
        self._env(None)

        with self.settings(DEBUG=False):
            with self.assertRaises(EncryptionKeyMissing) as ctx:
                encryption.get_or_create_encryption_key()

        self.assertFalse(self.key_path.exists(), 'سُكَّ مفتاحٌ رغم منع السكّ')
        # الرسالةُ تُسمّي المسارَ (تشخيصٌ) ولا تحمل مفتاحاً.
        self.assertIn(str(self.key_path), str(ctx.exception))

    def test_minting_allowed_is_false_by_default_outside_debug(self):
        """بلا علَمٍ وبلا DEBUG ⟵ لا إذن. (مُشغّلُ الاختبارات يفرض DEBUG=False.)"""
        self._env(None)
        with self.settings(DEBUG=False):
            self.assertFalse(encryption._minting_allowed())

    # ── الإذنان: العلَمُ الصريح، وDEBUG ──────────────────────────────────────
    def test_env_flag_permits_minting(self):
        self._patch_key_path()
        self._env('1')

        key = encryption.get_or_create_encryption_key()

        self.assertTrue(self.key_path.exists())
        self.assertEqual(self.key_path.read_bytes(), key)
        self.assertEqual(len(key), 44)

    def test_debug_permits_minting(self):
        self._patch_key_path()
        self._env(None)
        with self.settings(DEBUG=True):
            self.assertTrue(encryption._minting_allowed())
            encryption.get_or_create_encryption_key()
        self.assertTrue(self.key_path.exists())

    def test_env_flag_must_be_exactly_one(self):
        """قيمةٌ أخرى ليست إذناً — «0» و«true» لا تفتح البابَ سهواً."""
        self._env('0')
        with self.settings(DEBUG=False):
            self.assertFalse(encryption._minting_allowed())
