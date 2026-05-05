# إعدادات نظام الدمج الذكي

"""
تكوينات متقدمة لنظام الدمج الذكي
أضف هذه الإعدادات إلى lettersys/settings.py
"""

# ======================================
# إعدادات خدمة الدمج الذكية
# ======================================

# أنواع الملفات المدعومة
SUPPORTED_FILE_TYPES = {
    'pdf': ['application/pdf', 'application/x-pdf'],
    'image': ['image/jpeg', 'image/jpg', 'image/png', 'image/gif', 'image/bmp', 'image/webp'],
}

# الحد الأقصى لحجم الملف (بالميجابايت)
MAX_FILE_SIZE_MB = 50

# عدد الإصدارات المحتفظ بها كحد أقصى (0 = بدون حد)
MAX_VERSIONS_PER_ATTACHMENT = 20

# جودة الصور المدمجة (0-100)
MERGE_IMAGE_QUALITY = 95

# ألوان الخلفية عند دمج الصور بأحجام مختلفة
MERGE_IMAGE_BACKGROUND_COLOR = (255, 255, 255)  # أبيض

# اتجاه الدمج الافتراضي للصور
DEFAULT_MERGE_ORIENTATION = 'vertical'  # vertical أو horizontal

# ======================================
# إعدادات الملفات والتخزين
# ======================================

# مجلد التخزين المؤقت للملفات المدمجة
MERGE_TEMP_DIR = 'temp/merge'

# الاحتفاظ بنسخة احتياطية من الملف الأصلي
KEEP_ORIGINAL_BACKUP = True

# حذف الملفات المؤقتة تلقائياً بعد (ساعات)
AUTO_DELETE_TEMP_FILES_AFTER = 24

# ======================================
# إعدادات الأمان والصلاحيات
# ======================================

# السماح بدمج الملفات من قبل (list)
# 'owner': مالك الكتاب فقط
# 'staff': الموظفون فقط
# 'owner_or_staff': المالك أو الموظفون
# 'all_authenticated': جميع المستخدمين المسجلين
MERGE_PERMISSION_LEVEL = 'owner_or_staff'

# تسجيل عمليات الدمج بشكل تفصيلي
MERGE_DETAILED_LOGGING = True

# إرسال تنبيهات للمسؤولين عند فشل العملية
MERGE_NOTIFY_ON_FAILURE = True

# المسؤولون الذين يتلقون التنبيهات
MERGE_ADMIN_EMAILS = ['admin@example.com']

# ======================================
# إعدادات المراقبة والأداء
# ======================================

# تفعيل التخزين المؤقت (caching) للإصدارات
ENABLE_MERGE_CACHING = True

# مدة التخزين المؤقت (ثواني)
MERGE_CACHE_TIMEOUT = 300

# معالجة غير متزامنة للملفات الكبيرة
ENABLE_ASYNC_MERGE = False

# الحد الأقصى لحجم الملف للمعالجة المتزامنة (ميجابايت)
ASYNC_MERGE_SIZE_THRESHOLD = 10

# ======================================
# إعدادات تحويل الملفات
# ======================================

# تحويل صيغ الملفات تلقائياً إذا لزم الأمر
AUTO_CONVERT_FORMATS = True

# صيغة الملف الافتراضية عند الدمج
DEFAULT_OUTPUT_FORMAT = {
    'pdf': 'pdf',
    'image': 'png',
}

# ======================================
# إعدادات البيانات الوصفية
# ======================================

# حفظ بيانات وصفية مفصلة عن الملفات المدمجة
SAVE_MERGE_METADATA = True

# معلومات البيانات الوصفية المحفوظة
MERGE_METADATA_FIELDS = [
    'source_filename',
    'target_filename',
    'merge_type',
    'file_sizes',
    'page_counts',
    'dimensions',
    'merged_at',
    'merge_duration_seconds',
]

# ======================================
# إعدادات الإشعارات
# ======================================

# إرسال إشعارات عند انتهاء عملية الدمج
SEND_MERGE_NOTIFICATIONS = True

# قنوات الإشعارات
MERGE_NOTIFICATION_CHANNELS = [
    'in_app',  # إشعارات داخل التطبيق
    'email',   # بريد إلكتروني
]

# ======================================
# إعدادات التطوير والاختبار
# ======================================

# تفعيل وضع التصحيح (debug mode)
MERGE_DEBUG_MODE = False

# حفظ السجلات التفصيلية
MERGE_KEEP_DEBUG_LOGS = True

# مجلد السجلات
MERGE_LOG_DIR = 'logs/merge'

# ======================================
# إعدادات التكامل مع Django REST Framework
# ======================================

REST_FRAMEWORK_MERGE_CONFIG = {
    'PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated',
    ],
    'PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 10,
    'THROTTLE_CLASSES': [
        'rest_framework.throttling.AnonRateThrottle',
        'rest_framework.throttling.UserRateThrottle'
    ],
    'THROTTLE_RATES': {
        'anon': '100/hour',
        'user': '1000/hour'
    }
}
