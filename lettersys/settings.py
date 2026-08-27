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
    'daphne',   # يجب أن يسبق staticfiles ليرقّي runserver إلى ASGI (WebSocket)
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    # مكتبات خارجية
    'rest_framework',
    'channels',
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
                # مخصّص — هوية التطبيق المعروضة (اسم النظام + سطر الوصف)
                'core.context_processors.system_settings',
                # مخصّص — وضع التضمين (?embed=1) لمركز الإعدادات
                'core.context_processors.embed_mode',
            ],
        },
    },
]

WSGI_APPLICATION = 'lettersys.wsgi.application'
ASGI_APPLICATION = 'lettersys.asgi.application'

# ─── Channels (حضور الحجز اللحظيّ عبر WebSocket) ──────────────────────────────
# التطوير (عملية runserver واحدة): طبقة في الذاكرة — خفيفة وبلا Redis (تليق بجهاز 8GB).
# الإنتاج متعدّد العمّال: بدّلها إلى channels_redis عبر ضبط CHANNELS_REDIS_URL.
_CHANNELS_REDIS_URL = os.environ.get('CHANNELS_REDIS_URL', '')
if _CHANNELS_REDIS_URL:
    CHANNEL_LAYERS = {
        'default': {
            'BACKEND': 'channels_redis.core.RedisChannelLayer',
            'CONFIG': {'hosts': [_CHANNELS_REDIS_URL]},
        }
    }
else:
    CHANNEL_LAYERS = {'default': {'BACKEND': 'channels.layers.InMemoryChannelLayer'}}

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
DATA_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024   # 10 MB (لا يشمل ملفات multipart)
FILE_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024    # 5 MB (عتبة التخزين المؤقت لا حدّ)
DATA_UPLOAD_MAX_NUMBER_FIELDS = 2000
# الحدّ الأقصى الموحّد لحجم أي ملف مرفق (يطابق حدّ مسار المسح) —
# يفرضه core.attachment_service.validate_attachment_file عبر كل مسارات الرفع.
ATTACHMENT_MAX_UPLOAD_BYTES = int(os.environ.get('ATTACHMENT_MAX_UPLOAD_BYTES', str(50 * 1024 * 1024)))

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

# جدولة المهام الدورية (تتطلّب تشغيل `celery -A lettersys beat`)
from celery.schedules import crontab  # noqa: E402
CELERY_BEAT_SCHEDULE = {
    # يُشغَّل كل ساعة عند الدقيقة 0؛ المهمة نفسها تقرّر التنفيذ من BackupSettings.
    'scheduled-backup-hourly': {
        'task': 'core.tasks.scheduled_backup',
        'schedule': crontab(minute=0),
    },
    # جلب الردود الواردة. كانت المهمّة موجودة في core/tasks.py لكنها **غير مجدولة**
    # إطلاقاً — فكان مفتاح «المزامنة التلقائية» وعداً بلا جدول. المهمّة نفسها تحترم
    # imap_sync_enabled، وسقف الرسائل، وبوّابة الصلة.
    # ملاحظة: يتطلّب Redis + worker + beat. حيث لا يتوفّر ذلك، تتكفّل المزامنة
    # عند فتح صفحة الوارد (core.messaging.views.ui._autosync_inbox_if_due).
    'sync-inbox-every-10-minutes': {
        'task': 'core.tasks.sync_inbox_task',
        'schedule': crontab(minute='*/10'),
    },
}

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

# محرّك OCR المحلّي: 'tesseract' (افتراضي — خفيف/سريع بلا PyTorch) أو 'easyocr' (احتياطي).
AI_OFFLINE_ENGINE = os.environ.get('AI_OFFLINE_ENGINE', 'tesseract').lower()
# إعداد Tesseract (يُقرأ عند AI_OFFLINE_ENGINE='tesseract'):
#   TESSERACT_CMD          مسار tesseract.exe — فارغ = اكتشاف تلقائي (يشمل نسخة NAPS2).
#   TESSERACT_TESSDATA_DIR مجلّد *.traineddata — لازم لتحميل العربية (ara). فارغ = افتراضي tesseract.
#   TESSERACT_LANG         'ara+eng' إلزامي للمستندات المختلطة (ara وحده يُفسد الأرقام/الإنجليزي).
TESSERACT_CMD = os.environ.get('TESSERACT_CMD', '')
TESSERACT_TESSDATA_DIR = os.environ.get('TESSERACT_TESSDATA_DIR', '')
TESSERACT_LANG = os.environ.get('TESSERACT_LANG', 'ara+eng')
TESSERACT_PSM = os.environ.get('TESSERACT_PSM', '3')
# تصعيد تكيّفي: عند ثقة OCR < العتبة، يُجرَّب تحويل ثنائي (adaptive) ويُحتفَظ بالأعلى
# ثقةً. 0 = تعطيل. القيمة مُثبَتة على عيّنة قاعدة البيانات الحقيقية.
TESSERACT_ADAPTIVE_THRESHOLD = float(os.environ.get('TESSERACT_ADAPTIVE_THRESHOLD', '0.75'))

# ─── إعدادات OCR والاستخراج ──────────────────────────────────────────────────
# تحميل نموذج EasyOCR مسبقاً عند بدء Django (يمنع التأخير في أول طلب)
AI_PRELOAD_OCR = os.environ.get('AI_PRELOAD_OCR', 'False').lower() in ('true', '1')
# الحد الزمني الأقصى لعملية الاستخراج الكاملة (ثوانٍ)
AI_EXTRACTION_TIMEOUT = int(os.environ.get('AI_EXTRACTION_TIMEOUT', '120'))
# تشغيل OCR تلقائياً عند رفع/مسح مستند. مؤجَّل افتراضياً: EasyOCR ثقيل وقد يتعطّل
# أصلياً على الأجهزة محدودة الذاكرة — حتى يجهز عامل OCR المقيم نلتقط المستند فقط
# ونترك الإدخال يدوياً. فعّله بـ SCAN_AUTO_OCR=True عند توفّر الموارد/العامل المقيم.
SCAN_AUTO_OCR = os.environ.get('SCAN_AUTO_OCR', 'False').lower() in ('true', '1')

# إزالة الصفحات الفارغة تلقائياً بعد المسح (مسح مزدوج لمستند أحادي → ظهور فارغة).
# المقياس عدد البكسلات الداكنة المطلق (لا نسبة المساحة): صفحة فيها أي محتوى حقيقي —
# حتى رقم صفحة/ختم صغير — تُبقى؛ تُحذف فقط شبه الخالية تماماً (< 10 بكسل عند 72DPI).
# ارفع القيمة لحذف أعنف، أو عطّل كلياً بـ SCAN_TRIM_BLANK_PAGES=False.
SCAN_TRIM_BLANK_PAGES = os.environ.get('SCAN_TRIM_BLANK_PAGES', 'True').lower() in ('true', '1')
SCAN_BLANK_PAGE_MAX_DARK_PX = int(os.environ.get('SCAN_BLANK_PAGE_MAX_DARK_PX', '10'))

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
# وكيل المسح المحلي يعمل على منفذ خاص (افتراضياً 17865) — يجب السماح للصفحة بالاتصال به.
# نقرأ نفس متغيّر البيئة الذي يستخدمه الوكيل وعرض Django كي لا تنحرف القيم.
_AGENT_PORT = os.environ.get('LETTERSYS_AGENT_PORT', '17865')
_AGENT_ORIGINS = f"http://127.0.0.1:{_AGENT_PORT} http://localhost:{_AGENT_PORT}"
SECURE_CONTENT_SECURITY_POLICY = (
    "default-src 'self'; "
    # صفر CDN: كل الأصول محليّة (static/vendor) — أيّ مصدرٍ خارجيٍّ هنا سماحٌ ميت
    # يوسّع سطح الهجوم بلا مقابل. 'unsafe-inline' باقٍ لأنّ base.html يحمل سكربتاً
    # مضمَّناً فعلاً؛ إسقاطه يحتاج ورشة nonce مستقلّة.
    "script-src 'self' 'unsafe-inline'; "
    "style-src 'self' 'unsafe-inline'; "
    "font-src 'self' data:; "
    "img-src 'self' data: blob:; "
    f"connect-src 'self' {_AGENT_ORIGINS}; "
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


# ─── كاشف صندوق «العدد» (ONNX، CPU) ──────────────────────────────────────────
# yolov8n مُدرَّبٌ على 1,024 صندوقاً متحقَّقاً بتّيّاً. mAP50 0.830 · بوّابة M1
# (مركزٌ داخل الصندوق الصحيح) 96% على 165 صورة تحقّق · تطابق ONNX/torch 98.2%.
# 0.4s للصفحة و~350MB على CPU. الملفّ **ليس في git** (12.7MB ثنائيّ) — يُنشر
# مع الإصدار إلى المسار أدناه، وغيابه يُصمِت الكاشف بلا كسر أيّ استخراج.
NUMBER_DETECTOR_ONNX = os.environ.get(
    'NUMBER_DETECTOR_ONNX', str(BASE_DIR / 'var' / 'models' / 'number_detector.onnx'))
