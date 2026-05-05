# -*- coding: utf-8 -*-
"""
lettersys/settings_test.py
===========================
إعدادات Django مخصصة لبيئة الاختبار.

تُستخدم بدلاً من settings.py عند تشغيل الاختبارات لتجنب الحاجة
لصلاحية CREATEDB على PostgreSQL.

الاستخدام:
    # مع django test runner:
    python manage.py test --settings=lettersys.settings_test

    # مع pytest (عبر conftest.py):
    pytest  # يُعيَّن تلقائياً من conftest.py
"""

import os
from pathlib import Path

# اجلب كل الإعدادات الأساسية من settings.py
# (يقرأ .env تلقائياً إن وُجد)
from lettersys.settings import *  # noqa: F401, F403

# ─── تجاوز: SQLite للاختبارات ───────────────────────────────────────────────
# لا نحتاج CREATEDB على PostgreSQL؛ SQLite يُنشئ قاعدة اختبار في الذاكرة.
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': ':memory:',
    }
}

# ─── تجاوز: كاش LocMemCache معزول لكل عملية اختبار ─────────────────────────
# يمنع تسرّب الكاش بين الاختبارات ويضمن العزل الكامل.
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        'LOCATION': 'lettersys-test',
    }
}
SESSION_ENGINE = 'django.contrib.sessions.backends.db'

# ─── تجاوز: Celery بدون broker — مزامنة للاختبارات ──────────────────────────
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True

# ─── تجاوز: بريد في الذاكرة ─────────────────────────────────────────────────
EMAIL_BACKEND = 'django.core.mail.backends.locmem.EmailBackend'

# ─── تجاوز: ملفات الوسائط في مجلد مؤقت ────────────────────────────────────
import tempfile
MEDIA_ROOT = Path(tempfile.mkdtemp())

# ─── تجاوز: كلمة مرور بسيطة مسموح بها للاختبارات ─────────────────────────
AUTH_PASSWORD_VALIDATORS = []

# ─── تجاوز: تسريع hash للاختبارات ────────────────────────────────────────
PASSWORD_HASHERS = [
    'django.contrib.auth.hashers.MD5PasswordHasher',
]

# ─── تجاوز: تعطيل CSP في الاختبارات ──────────────────────────────────────
SECURE_CONTENT_SECURITY_POLICY = None

# ─── تجاوز: DEBUG=True للاختبارات ────────────────────────────────────────
DEBUG = True

# ─── تجاوز: السماح بـ testserver (العميل الافتراضي لـ Django TestCase) ──────
ALLOWED_HOSTS = ['*', 'testserver', 'localhost', '127.0.0.1']

# ─── تجاوز: تعطيل إعادة توجيه SSL في الاختبارات ─────────────────────────
# settings.py يضبطها True عندما DEBUG=False — نُلغيها هنا لمنع 301
SECURE_SSL_REDIRECT = False
SECURE_HSTS_SECONDS = 0
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
