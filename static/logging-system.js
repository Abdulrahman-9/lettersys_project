/**
 * ===================================================
 * نظام التسجيل والمراقبة المتقدم
 * (Logging & Monitoring System)
 * ===================================================
 * 
 * يوفر:
 * - تسجيل شامل لأفعال المستخدم
 * - جمع metrics للأداء
 * - تتبع الأخطاء
 * - تحليلات الاستخدام
 */

class LoggingSystem {
  constructor() {
    this.sessionId = this.generateSessionId();
    this.logs = [];
    this.metrics = {};
    this.startTime = Date.now();
    this.init();
  }
  
  init() {
    // تسجيل بداية الجلسة
    this.logEvent('SESSION_START', {
      timestamp: new Date().toISOString(),
      userAgent: navigator.userAgent,
      screenSize: `${window.screen.width}x${window.screen.height}`,
      viewport: `${window.innerWidth}x${window.innerHeight}`,
      language: navigator.language,
    });
    
    // تسجيل إغلاق الصفحة
    window.addEventListener('beforeunload', () => {
      this.logEvent('SESSION_END', {
        duration: Date.now() - this.startTime,
        logsCount: this.logs.length
      });
      this.flush();
    });
    
    // تسجيل الأخطاء التلقائي
    window.addEventListener('error', (e) => {
      this.logError('JAVASCRIPT_ERROR', {
        message: e.message,
        filename: e.filename,
        lineno: e.lineno,
        colno: e.colno,
        stack: e.error?.stack
      });
    });
    
    // تسجيل أخطاء الشبكة
    window.addEventListener('unhandledrejection', (e) => {
      this.logError('PROMISE_REJECTION', {
        reason: e.reason,
        promise: e.promise
      });
    });
  }
  
  /**
   * تسجيل حدث عام
   */
  logEvent(eventType, data = {}) {
    const log = {
      id: this.generateId(),
      sessionId: this.sessionId,
      type: 'EVENT',
      eventType: eventType,
      timestamp: Date.now(),
      data: data,
      url: window.location.href,
      referrer: document.referrer
    };
    
    this.logs.push(log);
    this.sendToBackend(log);
    
    console.log(`[EVENT] ${eventType}`, data);
  }
  
  /**
   * تسجيل خطأ
   */
  logError(errorType, data = {}) {
    const log = {
      id: this.generateId(),
      sessionId: this.sessionId,
      type: 'ERROR',
      errorType: errorType,
      timestamp: Date.now(),
      data: data,
      url: window.location.href,
      userAgent: navigator.userAgent
    };
    
    this.logs.push(log);
    this.sendToBackend(log, true); // إرسال فوري للأخطاء
    
    console.error(`[ERROR] ${errorType}`, data);
  }
  
  /**
   * تسجيل metric للأداء
   */
  logMetric(metricName, value, unit = '') {
    const metric = {
      name: metricName,
      value: value,
      unit: unit,
      timestamp: Date.now()
    };
    
    if (!this.metrics[metricName]) {
      this.metrics[metricName] = [];
    }
    
    this.metrics[metricName].push(metric);
    
    console.log(`[METRIC] ${metricName}: ${value}${unit}`);
  }
  
  /**
   * تسجيل فعل مستخدم محدد
   */
  logUserAction(action, details = {}) {
    this.logEvent('USER_ACTION', {
      action: action,
      ...details
    });
  }
  
  /**
   * إرسال السجلات للخادم
   */
  sendToBackend(log, immediate = false) {
    // يمكن تفعيل هذا لاحقاً
    if (window.LOGGING_ENABLED !== true) return;
    
    const endpoint = '/api/logs/';
    const data = JSON.stringify(log);
    
    if (immediate) {
      // إرسال فوري للأخطاء
      fetch(endpoint, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': this.getCsrfToken()
        },
        body: data,
        keepalive: true
      }).catch(err => console.error('فشل إرسال السجل:', err));
    } else {
      // تجميع وإرسال دفعات
      if (!this.sendQueue) this.sendQueue = [];
      this.sendQueue.push(log);
      
      if (this.sendQueue.length >= 10) {
        this.flush();
      }
    }
  }
  
  /**
   * إرسال جميع السجلات المتراكمة
   */
  flush() {
    if (!this.sendQueue || this.sendQueue.length === 0) return;
    
    const endpoint = '/api/logs/batch/';
    const data = JSON.stringify(this.sendQueue);
    
    fetch(endpoint, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': this.getCsrfToken()
      },
      body: data,
      keepalive: true
    }).catch(err => console.error('فشل إرسال السجلات:', err));
    
    this.sendQueue = [];
  }
  
  /**
   * جمع وإرسال تقرير الأداء
   */
  collectPerformanceMetrics() {
    if (!window.performance) return;
    
    const perfData = performance.getEntriesByType('navigation')[0];
    
    if (perfData) {
      this.logMetric('page_load_time', Math.round(perfData.loadEventEnd - perfData.fetchStart), 'ms');
      this.logMetric('dom_content_loaded', Math.round(perfData.domContentLoadedEventEnd - perfData.fetchStart), 'ms');
      this.logMetric('dns_lookup', Math.round(perfData.domainLookupEnd - perfData.domainLookupStart), 'ms');
      this.logMetric('tcp_connection', Math.round(perfData.connectEnd - perfData.connectStart), 'ms');
      this.logMetric('server_response', Math.round(perfData.responseEnd - perfData.requestStart), 'ms');
    }
    
    // جمع معلومات الذاكرة
    if (performance.memory) {
      this.logMetric('memory_used', Math.round(performance.memory.usedJSHeapSize / 1048576), 'MB');
      this.logMetric('memory_total', Math.round(performance.memory.totalJSHeapSize / 1048576), 'MB');
    }
  }
  
  /**
   * إنشاء معرف فريد
   */
  generateId() {
    return `${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;
  }
  
  /**
   * إنشاء معرف جلسة
   */
  generateSessionId() {
    const stored = sessionStorage.getItem('logging_session_id');
    if (stored) return stored;
    
    const newId = this.generateId();
    sessionStorage.setItem('logging_session_id', newId);
    return newId;
  }
  
  /**
   * الحصول على CSRF token
   */
  getCsrfToken() {
    return document.querySelector('[name=csrfmiddlewaretoken]')?.value || '';
  }
  
  /**
   * تصدير السجلات للتحميل (للتشخيص)
   */
  export() {
    const exportData = {
      sessionId: this.sessionId,
      startTime: new Date(this.startTime).toISOString(),
      endTime: new Date().toISOString(),
      duration: Date.now() - this.startTime,
      logs: this.logs,
      metrics: this.metrics,
      userAgent: navigator.userAgent,
      url: window.location.href
    };
    
    const blob = new Blob([JSON.stringify(exportData, null, 2)], { 
      type: 'application/json' 
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `logs-${this.sessionId}.json`;
    a.click();
    URL.revokeObjectURL(url);
  }
}

/**
 * ===================================================
 * نظام تحليل الاستخدام (Analytics)
 * ===================================================
 */
class AnalyticsSystem {
  constructor(loggingSystem) {
    this.logger = loggingSystem;
    this.pageViews = 0;
    this.interactions = {};
    this.timers = {};
  }
  
  /**
   * تتبع زيارة صفحة
   */
  trackPageView(pageName) {
    this.pageViews++;
    this.logger.logEvent('PAGE_VIEW', {
      page: pageName || document.title,
      url: window.location.href,
      viewNumber: this.pageViews
    });
  }
  
  /**
   * تتبع نقرة على عنصر
   */
  trackClick(elementName, elementType = 'button') {
    if (!this.interactions[elementName]) {
      this.interactions[elementName] = 0;
    }
    this.interactions[elementName]++;
    
    this.logger.logUserAction('CLICK', {
      element: elementName,
      type: elementType,
      count: this.interactions[elementName]
    });
  }
  
  /**
   * تتبع فتح نموذج
   */
  trackFormStart(formName) {
    this.timers[formName] = Date.now();
    this.logger.logUserAction('FORM_START', {
      form: formName
    });
  }
  
  /**
   * تتبع إرسال نموذج
   */
  trackFormSubmit(formName, success = true) {
    const startTime = this.timers[formName];
    const duration = startTime ? Date.now() - startTime : 0;
    
    this.logger.logUserAction('FORM_SUBMIT', {
      form: formName,
      success: success,
      duration: duration
    });
    
    this.logger.logMetric(`form_${formName}_duration`, duration, 'ms');
    
    delete this.timers[formName];
  }
  
  /**
   * تتبع استخدام ميزة معينة
   */
  trackFeatureUsage(featureName, metadata = {}) {
    this.logger.logEvent('FEATURE_USAGE', {
      feature: featureName,
      ...metadata
    });
  }
  
  /**
   * تتبع خطأ
   */
  trackError(errorCode, errorMessage, metadata = {}) {
    this.logger.logError('USER_ERROR', {
      code: errorCode,
      message: errorMessage,
      ...metadata
    });
  }
  
  /**
   * تتبع استخدام البحث
   */
  trackSearch(query, resultsCount) {
    this.logger.logUserAction('SEARCH', {
      query: query,
      resultsCount: resultsCount,
      hasResults: resultsCount > 0
    });
  }
  
  /**
   * تتبع استخدام السكانر
   */
  trackScannerUsage(action, duration = 0, success = true) {
    this.logger.logUserAction('SCANNER', {
      action: action,
      duration: duration,
      success: success
    });
    
    if (duration > 0) {
      this.logger.logMetric('scanner_duration', duration, 'ms');
    }
  }
  
  /**
   * الحصول على تقرير الاستخدام
   */
  getUsageReport() {
    return {
      pageViews: this.pageViews,
      interactions: this.interactions,
      totalInteractions: Object.values(this.interactions).reduce((a, b) => a + b, 0),
      activeForms: Object.keys(this.timers),
      sessionDuration: Date.now() - this.logger.startTime
    };
  }
}

// Initialize systems
const Logger = new LoggingSystem();
const Analytics = new AnalyticsSystem(Logger);

// جمع metrics الأداء عند تحميل الصفحة
window.addEventListener('load', () => {
  setTimeout(() => {
    Logger.collectPerformanceMetrics();
  }, 1000);
});

// Export for global use
window.Logger = Logger;
window.Analytics = Analytics;

// تسجيل PageView تلقائي
document.addEventListener('DOMContentLoaded', () => {
  Analytics.trackPageView();
});

// Expose debug function
window.exportLogs = () => Logger.export();

console.log('✅ Logging & Analytics System initialized');
console.log('📊 Session ID:', Logger.sessionId);
console.log('💡 Tip: Use window.exportLogs() to download logs');
