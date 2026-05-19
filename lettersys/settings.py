# -*- coding: utf-8 -*-
"""
lettersys/settings.py
=====================
إعدادات Django لمشروع LetterSys.

يقرأ كل القيم الحساسة من متغيّرات البيئة أو ملف .env في جذر المشروع.
لا توجد قيم سرية مشفّرة مباشرة هنا.

لإنشاء .env محلي:
    cp .env.example .env
    # ثم عدّل القيم حسب بيئتك
"""

import os
from pathlib import Path

# ─── المسارات الأساسية ────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent.parent

# ─── تحميل .env إذا وُجد (بدون مكتبة خارجية) ────────────────────────────────
_env_file = BASE_DIR / '.env'
if _env_file.exists():
    with open(_env_file, encoding='utf-8') as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith('#') and '=' in _line:
                _key, _, _val = _line.partition('=')
                os.environ.setdefault(_key.strip(), _val.strip())

# ─── الأمان الجوهري ───────────────────────────────────────────────────────────
SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY', '')
if not SECRET_KEY:
    raise RuntimeError(
        "DJANGO_SECRET_KEY غير محدد. "
        "عرّفه في ملف .env أو كمتغيّر بيئة.\n"
        "توليد سريع:\n"
        "  python -c \"from django.core.management.utils import "
        "get_random_secret_key; print(get_random_secret_key())\""
    )

# DEBUG=False افتراضياً — يجب تعيينه صراحةً في .env لتفعيله
DEBUG = os.environ.get('DEBUG', 'False').lower() in ('true', '1', 'yes')

# ─── المضيفون والـ CSRF ───────────────────────────────────────────────────────
_raw_hosts = os.environ.get('ALLOWED_HOSTS', 'localhost,127.0.0.1')
ALLOWED_HOSTS = [h.strip() for h in _raw_hosts.split(',') if h.strip()]

_raw_origins = os.environ.get(
    'CSRF_TRUSTED_ORIGINS',
    'http://localhost:8000,http://127.0.0.1:8000'
)
CSRF_TRUSTED_ORIGINS = [o.strip() for o in _raw_origins.split(',') if o.strip()]

# ─── التطبيقات المثبّتة ───────────────────────────────────────────────────────
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    # مكتبات خارجية
    'rest_framework',
    # تطبيقات المشروع
    'core.apps.CoreConfig',
]

# ─── الـ Middleware ───────────────────────────────────────────────────────────
MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    # مخصّص
    'core.middleware.csp_middleware.CSPMiddleware',
    'core.middleware.logging_middleware.RequestLoggingMiddleware',
]

ROOT_URLCONF = 'lettersys.urls'

# ─── القوالب ─────────────────────────────────────────────────────────────────
TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                # مخصّص — badge الإشعارات والبريد في الشريط الجانبي
                'core.context_processors.notifications',
                'core.context_processors.mail_unread',
            ],
        },
    },
]

WSGI_APPLICATION = 'lettersys.wsgi.application'

# ─── قاعدة البيانات ───────────────────────────────────────────────────────────
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': os.environ.get('DB_NAME', 'lettersys'),
        'USER': os.environ.get('DB_USER', 'lettersys_user'),
        'PASSWORD': os.environ.get('DB_PASSWORD', ''),
        'HOST': os.environ.get('DB_HOST', 'localhost'),
        'PORT': os.environ.get('DB_PORT', '5432'),
        'OPTIONS': {
            'connect_timeout': 10,
        },
        'CONN_MAX_AGE': 60,  # connection pooling بسيط
    }
}

# ─── الكاش ───────────────────────────────────────────────────────────────────
_redis_cache_url = os.environ.get('REDIS_CACHE_URL', '')

if _redis_cache_url:
    CACHES = {
        'default': {
            'BACKEND': 'django_redis.cache.RedisCache',
            'LOCATION': _redis_cache_url,
            'OPTIONS': {
                'CLIENT_CLASS': 'django_redis.client.DefaultClient',
                'SOCKET_CONNECT_TIMEOUT': 5,
                'SOCKET_TIMEOUT': 5,
                'IGNORE_EXCEPTIONS': True,  # لا يوقف التطبيق عند انقطاع Redis
            },
            'KEY_PREFIX': 'lettersys',
        }
    }
    SESSION_ENGINE = 'django.contrib.sessions.backends.cache'
    SESSION_CACHE_ALIAS = 'default'
else:
    # تطوير محلي بدون Redis
    CACHES = {
        'default': {
            'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
            'LOCATION': 'lettersys-dev',
        }
    }

# ─── الجلسات ─────────────────────────────────────────────────────────────────
SESSION_COOKIE_AGE = 86400          # يوم واحد افتراضياً
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'
SESSION_SAVE_EVERY_REQUEST = False
# تُعيَّن مدة 30 يوم في auth_views عند تفعيل "تذكرني"

# ─── المصادقة ─────────────────────────────────────────────────────────────────
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
     'OPTIONS': {'min_length': 8}},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LOGIN_URL = '/login/'
LOGIN_REDIRECT_URL = '/'
LOGOUT_REDIRECT_URL = '/login/'

# ─── التدويل ─────────────────────────────────────────────────────────────────
LANGUAGE_CODE = 'ar'
TIME_ZONE = 'Asia/Baghdad'
USE_I18N = True
USE_TZ = True

# ─── الملفات الساكنة والوسائط ────────────────────────────────────────────────
STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'

MEDIA_URL = '/media/'
# MEDIA_ROOT يمكن نقله خارج المشروع عبر متغير البيئة MEDIA_ROOT
_media_root_env = os.environ.get('MEDIA_ROOT', '')
MEDIA_ROOT = _media_root_env if _media_root_env else (BASE_DIR / 'media')

# ─── حدود رفع الملفات (منع ابتلاع RAM بملفات PDF كبيرة) ─────────────────────
# ملفات أكبر من 5 MB تُكتب على القرص مؤقتاً بدل بقائها في الذاكرة
DATA_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024   # 10 MB
FILE_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024    # 5 MB
DATA_UPLOAD_MAX_NUMBER_FIELDS = 2000

# ─── نوع المفتاح الافتراضي ────────────────────────────────────────────────────
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# ─── Django REST Framework ───────────────────────────────────────────────────
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework.authentication.SessionAuthentication',
    ],
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated',
    ],
    'DEFAULT_RENDERER_CLASSES': [
        'rest_framework.renderers.JSONRenderer',
    ],
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 50,
}

# ─── البريد الإلكتروني ────────────────────────────────────────────────────────
if DEBUG:
    EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'
else:
    EMAIL_BACKEND = os.environ.get(
        'EMAIL_BACKEND',
        'django.core.mail.backends.smtp.EmailBackend'
    )

EMAIL_HOST = os.environ.get('EMAIL_HOST', 'smtp.gmail.com')
EMAIL_PORT = int(os.environ.get('EMAIL_PORT', '587'))
EMAIL_USE_TLS = os.environ.get('EMAIL_USE_TLS', 'True').lower() in ('true', '1')
EMAIL_USE_SSL = os.environ.get('EMAIL_USE_SSL', 'False').lower() in ('true', '1')
EMAIL_HOST_USER = os.environ.get('EMAIL_HOST_USER', '')
EMAIL_HOST_PASSWORD = os.environ.get('EMAIL_HOST_PASSWORD', '')
DEFAULT_FROM_EMAIL = os.environ.get('DEFAULT_FROM_EMAIL', 'noreply@lettersys.local')

# ─── Celery ───────────────────────────────────────────────────────────────────
CELERY_BROKER_URL = os.environ.get('CELERY_BROKER_URL', 'redis://localhost:6379/0')
CELERY_RESULT_BACKEND = os.environ.get('CELERY_RESULT_BACKEND', 'redis://localhost:6379/0')
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TIMEZONE = TIME_ZONE
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_TIME_LIMIT = 300          # 5 دقائق حد أقصى للمهمة
CELERY_WORKER_MAX_TASKS_PER_CHILD = 50  # استعادة ذاكرة الـ OCR دورياً

# ─── إعدادات الذكاء الاصطناعي والاستخراج ────────────────────────────────────
AI_PROVIDER = os.environ.get('AI_PROVIDER', 'offline')
AI_FALLBACK_ON_LOW_CONFIDENCE = os.environ.get(
    'AI_FALLBACK_ON_LOW_CONFIDENCE', 'True').lower() in ('true', '1')
AI_LOW_CONFIDENCE_THRESHOLD = float(
    os.environ.get('AI_LOW_CONFIDENCE_THRESHOLD', '0.4'))
AI_ALLOW_MOCK_EXTRACTION = os.environ.get(
    'AI_ALLOW_MOCK_EXTRACTION', 'False').lower() in ('true', '1')
AI_AZURE_ENDPOINT = os.environ.get('AI_AZURE_ENDPOINT', '')
AI_AZURE_KEY = os.environ.get('AI_AZURE_KEY', '')

# ─── إعدادات OCR والاستخراج ──────────────────────────────────────────────────
# تحميل نموذج EasyOCR مسبقاً عند بدء Django (يمنع التأخير في أول طلب)
AI_PRELOAD_OCR = os.environ.get('AI_PRELOAD_OCR', 'False').lower() in ('true', '1')
# الحد الزمني الأقصى لعملية الاستخراج الكاملة (ثوانٍ)
AI_EXTRACTION_TIMEOUT = int(os.environ.get('AI_EXTRACTION_TIMEOUT', '120'))

# ─── Hot Folder Watcher (مراقب مجلد المسح الضوئي) ────────────────────────────
# المجلد الذي يحفظ فيه CaptureOnTouch الملفات الممسوحة
SCAN_WATCH_FOLDER = os.environ.get('SCAN_WATCH_FOLDER', '')
# عنوان Django المحلي — يُستخدم لفتح المتصفح بعد المعالجة
SCAN_API_URL = os.environ.get('SCAN_API_URL', 'http://localhost:8000')

# ─── الماسح الضوئي (simulator) ────────────────────────────────────────────────
SCAN_SIMULATOR_MODE = os.environ.get('SCAN_SIMULATOR_MODE', 'False').lower() in ('true', '1')
SCAN_SIMULATOR_DELAY = int(os.environ.get('SCAN_SIMULATOR_DELAY', '3'))

X_FRAME_OPTIONS = 'SAMEORIGIN'

# ─── الأمان في الإنتاج (DEBUG=False) ─────────────────────────────────────────
if not DEBUG:
    SECURE_SSL_REDIRECT = os.environ.get('SECURE_SSL_REDIRECT', 'True').lower() in ('true', '1')
    SECURE_HSTS_SECONDS = int(os.environ.get('SECURE_HSTS_SECONDS', '31536000'))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_BROWSER_XSS_FILTER = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True

# ─── Content Security Policy (يطبّقها CSPMiddleware) ─────────────────────────
SECURE_CONTENT_SECURITY_POLICY = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
    "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://fonts.googleapis.com; "
    "font-src 'self' https://fonts.gstatic.com https://cdn.jsdelivr.net data:; "
    "img-src 'self' data: blob:; "
    "connect-src 'self'; "
    "worker-src 'self' blob:; "
    "manifest-src 'self';"
)

# ─── السجلّات (Logging) ───────────────────────────────────────────────────────
_log_level = 'DEBUG' if DEBUG else 'INFO'
_logs_dir = BASE_DIR / 'logs'
_logs_dir.mkdir(exist_ok=True)

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '[{asctime}] {levelname} {name} {message}',
            'style': '{',
        },
        'simple': {
            'format': '{levelname} {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'simple',
        },
        'file': {
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': _logs_dir / 'lettersys.log',
            'maxBytes': 10 * 1024 * 1024,  # 10 MB
            'backupCount': 5,
            'formatter': 'verbose',
            'encoding': 'utf-8',
        },
    },
    'loggers': {
        'lettersys': {
            'handlers': ['console', 'file'],
            'level': _log_level,
            'propagate': False,
        },
        'django': {
            'handlers': ['console', 'file'],
            'level': 'WARNING',
            'propagate': False,
        },
        'django.request': {
            'handlers': ['file'],
            'level': 'ERROR',
            'propagate': False,
        },
    },
}
