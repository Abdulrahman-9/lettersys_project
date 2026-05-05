/**
 * ===================================================
 * نظام رموز الأخطاء الموحد (Error Codes System)
 * ===================================================
 * 
 * Format: ERR-CATEGORY-NUMBER
 * Example: ERR-FORM-001
 * 
 * Categories:
 * - FORM: أخطاء النماذج
 * - AUTH: أخطاء التحقق والمصادقة
 * - FILE: أخطاء الملفات
 * - DB: أخطاء قاعدة البيانات
 * - API: أخطاء API
 * - SYS: أخطاء النظام
 */

const ERROR_CODES = {
  // ===== Form Errors (ERR-FORM-XXX) =====
  FORM: {
    VALIDATION_FAILED: {
      code: 'ERR-FORM-001',
      message: 'فشل التحقق من صحة البيانات',
      messageEn: 'Validation failed',
      severity: 'warning',
      action: 'يرجى مراجعة الحقول الموضحة بالأحمر'
    },
    REQUIRED_FIELD: {
      code: 'ERR-FORM-002',
      message: 'حقل مطلوب غير مملوء',
      messageEn: 'Required field is empty',
      severity: 'warning',
      action: 'يرجى ملء جميع الحقول المطلوبة (المحددة بـ *)'
    },
    INVALID_FORMAT: {
      code: 'ERR-FORM-003',
      message: 'تنسيق البيانات غير صحيح',
      messageEn: 'Invalid data format',
      severity: 'warning',
      action: 'تحقق من تنسيق البيانات المدخلة'
    },
    MAX_LENGTH_EXCEEDED: {
      code: 'ERR-FORM-004',
      message: 'تم تجاوز الحد الأقصى للأحرف',
      messageEn: 'Maximum length exceeded',
      severity: 'warning',
      action: 'يرجى تقليل عدد الأحرف'
    },
    MIN_LENGTH_NOT_MET: {
      code: 'ERR-FORM-005',
      message: 'لم يتم الوصول للحد الأدنى من الأحرف',
      messageEn: 'Minimum length not met',
      severity: 'warning',
      action: 'يرجى إدخال المزيد من الأحرف'
    },
    CSRF_TOKEN_MISSING: {
      code: 'ERR-FORM-006',
      message: 'رمز الأمان (CSRF) مفقود',
      messageEn: 'CSRF token missing',
      severity: 'error',
      action: 'يرجى تحديث الصفحة والمحاولة مرة أخرى'
    },
  },

  // ===== File Errors (ERR-FILE-XXX) =====
  FILE: {
    INVALID_TYPE: {
      code: 'ERR-FILE-001',
      message: 'نوع الملف غير مسموح',
      messageEn: 'Invalid file type',
      severity: 'error',
      action: 'يُسمح فقط بملفات PDF, JPG, PNG'
    },
    SIZE_EXCEEDED: {
      code: 'ERR-FILE-002',
      message: 'حجم الملف كبير جداً',
      messageEn: 'File size exceeded',
      severity: 'error',
      action: 'الحد الأقصى للحجم: 10MB'
    },
    UPLOAD_FAILED: {
      code: 'ERR-FILE-003',
      message: 'فشل رفع الملف',
      messageEn: 'File upload failed',
      severity: 'error',
      action: 'يرجى المحاولة مرة أخرى أو التحقق من الاتصال'
    },
    NOT_FOUND: {
      code: 'ERR-FILE-004',
      message: 'الملف غير موجود',
      messageEn: 'File not found',
      severity: 'error',
      action: 'الملف قد يكون محذوفاً أو مفقوداً'
    },
    CORRUPTED: {
      code: 'ERR-FILE-005',
      message: 'الملف تالف أو غير قابل للقراءة',
      messageEn: 'File corrupted',
      severity: 'error',
      action: 'يرجى رفع ملف صحيح'
    },
  },

  // ===== Scanner Errors (ERR-SCAN-XXX) =====
  SCANNER: {
    NO_FILE_FOUND: {
      code: 'ERR-SCAN-001',
      message: 'لم يتم العثور على ملف ممسوح جديد',
      messageEn: 'No scanned file found',
      severity: 'warning',
      action: 'تأكد من وضع الملف في السكانر والمسح'
    },
    RATE_LIMIT: {
      code: 'ERR-SCAN-002',
      message: 'تم تجاوز عدد محاولات المسح المسموحة',
      messageEn: 'Scan rate limit exceeded',
      severity: 'warning',
      action: 'يرجى الانتظار 5 ثوان قبل المحاولة مرة أخرى'
    },
    CONNECTION_FAILED: {
      code: 'ERR-SCAN-003',
      message: 'فشل الاتصال بالسكانر',
      messageEn: 'Scanner connection failed',
      severity: 'error',
      action: 'تحقق من توصيل السكانر والتشغيل'
    },
    TIMEOUT: {
      code: 'ERR-SCAN-004',
      message: 'انتهت مهلة انتظار السكانر',
      messageEn: 'Scanner timeout',
      severity: 'warning',
      action: 'السكانر لم يستجب في الوقت المحدد'
    },
  },

  // ===== Authentication Errors (ERR-AUTH-XXX) =====
  AUTH: {
    UNAUTHORIZED: {
      code: 'ERR-AUTH-001',
      message: 'غير مصرح لك بهذا الإجراء',
      messageEn: 'Unauthorized action',
      severity: 'error',
      action: 'يرجى تسجيل الدخول أولاً'
    },
    FORBIDDEN: {
      code: 'ERR-AUTH-002',
      message: 'ليس لديك صلاحيات كافية',
      messageEn: 'Forbidden - insufficient permissions',
      severity: 'error',
      action: 'تحتاج صلاحيات أعلى لهذا الإجراء'
    },
    SESSION_EXPIRED: {
      code: 'ERR-AUTH-003',
      message: 'انتهت صلاحية الجلسة',
      messageEn: 'Session expired',
      severity: 'warning',
      action: 'يرجى تسجيل الدخول مرة أخرى'
    },
  },

  // ===== Network Errors (ERR-NET-XXX) =====
  NETWORK: {
    TIMEOUT: {
      code: 'ERR-NET-001',
      message: 'انتهت مهلة الانتظار',
      messageEn: 'Request timeout',
      severity: 'error',
      action: 'تحقق من اتصالك بالإنترنت'
    },
    NO_CONNECTION: {
      code: 'ERR-NET-002',
      message: 'لا يوجد اتصال بالإنترنت',
      messageEn: 'No internet connection',
      severity: 'error',
      action: 'يرجى التحقق من اتصال الشبكة'
    },
    SERVER_ERROR: {
      code: 'ERR-NET-003',
      message: 'خطأ في الخادم',
      messageEn: 'Server error',
      severity: 'error',
      action: 'يرجى المحاولة لاحقاً أو الاتصال بالدعم'
    },
  },

  // ===== Database Errors (ERR-DB-XXX) =====
  DATABASE: {
    SAVE_FAILED: {
      code: 'ERR-DB-001',
      message: 'فشل حفظ البيانات',
      messageEn: 'Failed to save data',
      severity: 'error',
      action: 'يرجى المحاولة مرة أخرى'
    },
    DUPLICATE_ENTRY: {
      code: 'ERR-DB-002',
      message: 'البيانات موجودة مسبقاً',
      messageEn: 'Duplicate entry',
      severity: 'warning',
      action: 'هذا السجل مكرر'
    },
    NOT_FOUND: {
      code: 'ERR-DB-003',
      message: 'السجل غير موجود',
      messageEn: 'Record not found',
      severity: 'error',
      action: 'السجل قد يكون محذوفاً'
    },
  },

  // ===== System Errors (ERR-SYS-XXX) =====
  SYSTEM: {
    UNKNOWN: {
      code: 'ERR-SYS-001',
      message: 'خطأ غير معروف',
      messageEn: 'Unknown error',
      severity: 'error',
      action: 'يرجى المحاولة مرة أخرى أو الاتصال بالدعم'
    },
    MAINTENANCE: {
      code: 'ERR-SYS-002',
      message: 'النظام تحت الصيانة',
      messageEn: 'System under maintenance',
      severity: 'info',
      action: 'يرجى المحاولة بعد قليل'
    },
  }
};

/**
 * Helper function لعرض خطأ مع رمزه
 * @param {string} category - فئة الخطأ (FORM, FILE, etc.)
 * @param {string} errorType - نوع الخطأ
 * @param {object} customData - بيانات إضافية
 */
function showError(category, errorType, customData = {}) {
  const error = ERROR_CODES[category]?.[errorType];
  
  if (!error) {
    console.error(`خطأ غير معرف: ${category}.${errorType}`);
    return;
  }
  
  const errorMessage = `[${error.code}] ${error.message}`;
  const fullMessage = `${errorMessage}\n${error.action}`;
  
  // Log للمطورين
  console.error('Error Details:', {
    code: error.code,
    message: error.message,
    messageEn: error.messageEn,
    severity: error.severity,
    customData: customData
  });
  
  // عرض للمستخدم
  const severityIcons = {
    error: '❌',
    warning: '⚠️',
    info: 'ℹ️'
  };
  
  if (window.ToastCenter && typeof window.ToastCenter.show === 'function') {
    const toastType = error.severity === 'warning' ? 'warning' : (error.severity === 'info' ? 'info' : 'error');
    window.ToastCenter.show(toastType, fullMessage, {
      title: error.code,
      delay: toastType === 'error' ? 7000 : 5000,
    });
  } else {
    alert(`${severityIcons[error.severity]} ${fullMessage}`);
  }
  
  // تسجيل في Analytics (سيتم تطبيقه لاحقاً)
  if (window.Analytics) {
    window.Analytics.trackError(error.code, error.message, customData);
  }
}

/**
 * Helper function لمعالجة أخطاء HTTP
 * @param {Response} response - استجابة HTTP
 */
function handleHTTPError(response) {
  const statusErrors = {
    400: { category: 'FORM', type: 'VALIDATION_FAILED' },
    401: { category: 'AUTH', type: 'UNAUTHORIZED' },
    403: { category: 'AUTH', type: 'FORBIDDEN' },
    404: { category: 'DATABASE', type: 'NOT_FOUND' },
    408: { category: 'NETWORK', type: 'TIMEOUT' },
    500: { category: 'NETWORK', type: 'SERVER_ERROR' },
  };
  
  const error = statusErrors[response.status] || { category: 'SYSTEM', type: 'UNKNOWN' };
  showError(error.category, error.type, { 
    status: response.status,
    url: response.url 
  });
}

// Export for use in other files
if (typeof module !== 'undefined' && module.exports) {
  module.exports = { ERROR_CODES, showError, handleHTTPError };
}
