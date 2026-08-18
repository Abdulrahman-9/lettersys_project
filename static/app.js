// معالجة فشل تحميل المرفقات (PDF/صور)
document.addEventListener('DOMContentLoaded', function () {
  // معالجة روابط المرفقات المفتوحة في نافذة جديدة
  document.querySelectorAll('.attachments-list a[target="_blank"]').forEach(function(link) {
    link.addEventListener('click', function(e) {
      // محاولة جلب الملف أولاً
      fetch(link.href, {method: 'HEAD'}).then(resp => {
        if (!resp.ok) {
          e.preventDefault();
          showToast('⚠️ الملف غير متوفر أو تم حذفه من الخادم', 'error', 5000);
        }
      }).catch(() => {
        e.preventDefault();
        showToast('⚠️ تعذر الوصول للملف (ربما تم حذفه)', 'error', 5000);
      });
    });
  });

  // معالجة فشل تحميل الصور داخل الصفحة (إن وجدت)
  document.querySelectorAll('.attachments-list img').forEach(function(img) {
    img.onerror = function() {
      this.style.display = 'none';
      showToast('⚠️ تعذر تحميل الصورة (ربما تم حذفها)', 'error', 5000);
    };
  });
  
  // Initialize filter state manager
  FilterStateManager.init();
  
  // معالجة أزرار الحذف عبر AJAX مع undo
  initAjaxDeleteButtons();
});
/**
 * نظام إدارة الكتب - JavaScript الرئيسي
 * يحتوي على جميع الوظائف التفاعلية الحديثة
 */

// ================================
// 1. إعدادات عامة وثوابت
// ================================
const APP = {
  csrfToken: document.querySelector('[name=csrfmiddlewaretoken]')?.value || '',
  debounceDelay: 300,
  animationDuration: 300,
  toastDuration: 3800,
};

// ================================
// 2. مساعدات عامة (Utilities)
// ================================

/**
 * دالة debounce لتأخير تنفيذ الدوال
 */
function debounce(func, wait) {
  let timeout;
  return function executedFunction(...args) {
    const later = () => {
      clearTimeout(timeout);
      func(...args);
    };
    clearTimeout(timeout);
    timeout = setTimeout(later, wait);
  };
}

/**
 * دالة fetch محسّنة مع معالجة الأخطاء
 */
async function fetchJSON(url, options = {}) {
  const defaultOptions = {
    headers: {
      'Content-Type': 'application/json',
      'X-CSRFToken': getCSRFToken(),
      'X-Requested-With': 'XMLHttpRequest',
    },
  };

  try {
    const response = await fetch(url, { ...defaultOptions, ...options });
    
    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }
    
    const contentType = response.headers.get('content-type');
    if (contentType && contentType.includes('application/json')) {
      return await response.json();
    }
    
    return await response.text();
  } catch (error) {
    console.error('Fetch error:', error);
    showToast('حدث خطأ في الاتصال بالخادم', 'error');
    throw error;
  }
}

/**
 * الحصول على CSRF Token بشكل موثوق (من الحقل الخفي أو الكوكيز)
 */
function getCSRFToken() {
  if (APP.csrfToken) return APP.csrfToken;
  const inputToken = document.querySelector('[name=csrfmiddlewaretoken]')?.value;
  if (inputToken) {
    APP.csrfToken = inputToken;
    return APP.csrfToken;
  }
  const cookie = document.cookie.split(';').find(c => c.trim().startsWith('csrftoken='));
  if (cookie) {
    APP.csrfToken = cookie.split('=')[1];
  }
  return APP.csrfToken;
}

/**
 * عرض Toast notification
 */
function showToast(message, type = 'info', duration = APP.toastDuration) {
  const toastCenter = resolveToastCenter();
  if (toastCenter) {
    return toastCenter.show(type, message, { delay: duration });
  }

  console[type === 'error' ? 'error' : 'log'](message);
  return null;
}

/**
 * إنشاء حاوية Toast إذا لم تكن موجودة
 */
function createToastContainer() {
  const existingContainer = document.querySelector('.toast-center');
  if (existingContainer) {
    return existingContainer;
  }

  const container = document.createElement('div');
  container.className = 'toast-container toast-center p-3 toast-stack';
  document.body.appendChild(container);
  return container;
}

function resolveToastCenter() {
  if (window.ToastCenter && typeof window.ToastCenter.show === 'function') {
    return window.ToastCenter;
  }
  return null;
}

/**
 * تأكيد حذف مع تصميم جميل
 */
function confirmDelete(message = 'هل أنت متأكد من الحذف؟') {
  return new Promise((resolve) => {
    const modal = createConfirmModal(message);
    document.body.appendChild(modal);
    
    const bsModal = new bootstrap.Modal(modal);
    bsModal.show();
    
    modal.querySelector('.btn-confirm').addEventListener('click', () => {
      bsModal.hide();
      resolve(true);
    });
    
    modal.querySelector('.btn-cancel').addEventListener('click', () => {
      bsModal.hide();
      resolve(false);
    });
    
    modal.addEventListener('hidden.bs.modal', () => {
      modal.remove();
    });
  });
}

/**
 * إنشاء modal تأكيد
 */
function createConfirmModal(message) {
  const modalHTML = `
    <div class="modal fade" tabindex="-1">
      <div class="modal-dialog modal-dialog-centered">
        <div class="modal-content">
          <div class="modal-header border-0">
            <h5 class="modal-title"><i class="bi bi-question-circle text-warning me-2"></i>تأكيد العملية</h5>
            <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
          </div>
          <div class="modal-body">${message}</div>
          <div class="modal-footer border-0">
            <button type="button" class="btn btn-secondary btn-cancel" data-bs-dismiss="modal">إلغاء</button>
            <button type="button" class="btn btn-danger btn-confirm">تأكيد</button>
          </div>
        </div>
      </div>
    </div>
  `;
  
  const tempDiv = document.createElement('div');
  tempDiv.innerHTML = modalHTML;
  return tempDiv.firstElementChild;
}

// ================================
// 3. البحث المباشر (Live Search)
// ================================

/**
 * تفعيل البحث المباشر
 */
function initLiveSearch() {
  const searchInputs = document.querySelectorAll('[data-live-search]');
  
  searchInputs.forEach(input => {
    const targetSelector = input.dataset.liveSearch;
    const target = document.querySelector(targetSelector);
    
    if (!target) return;
    
    const debouncedSearch = debounce((searchTerm) => {
      performLiveSearch(searchTerm, target, input);
    }, APP.debounceDelay);
    
    input.addEventListener('input', (e) => {
      const searchTerm = e.target.value.trim();
      debouncedSearch(searchTerm);
    });
    
    // إضافة أيقونة loading
    const wrapper = input.parentElement;
    if (!wrapper.querySelector('.search-spinner')) {
      const spinner = document.createElement('div');
      spinner.className = 'search-spinner spinner-border spinner-border-sm position-absolute d-none';
      spinner.style.left = '10px';
      spinner.style.top = '50%';
      spinner.style.transform = 'translateY(-50%)';
      wrapper.style.position = 'relative';
      wrapper.appendChild(spinner);
    }
  });
}

/**
 * تنفيذ البحث المباشر
 */
async function performLiveSearch(searchTerm, target, input) {
  const spinner = input.parentElement.querySelector('.search-spinner');
  if (spinner) spinner.classList.remove('d-none');
  
  try {
    const url = new URL(window.location.href);
    url.searchParams.set('q', searchTerm);
    
    const response = await fetch(url.toString(), {
      headers: {
        'X-Requested-With': 'XMLHttpRequest',
      },
    });
    
    const html = await response.text();
    const parser = new DOMParser();
    const doc = parser.parseFromString(html, 'text/html');
    const newContent = doc.querySelector(target.dataset.liveSearch || '#bookTableBody');
    
    if (newContent) {
      target.innerHTML = newContent.innerHTML;
      highlightSearchResults(target, searchTerm);
    }
  } catch (error) {
    console.error('Live search error:', error);
  } finally {
    if (spinner) spinner.classList.add('d-none');
  }
}

/**
 * تمييز نتائج البحث
 */
function highlightSearchResults(container, searchTerm) {
  if (!searchTerm) return;
  
  const regex = new RegExp(`(${searchTerm})`, 'gi');
  const textNodes = getTextNodes(container);
  
  textNodes.forEach(node => {
    const parent = node.parentNode;
    if (parent.tagName === 'SCRIPT' || parent.tagName === 'STYLE') return;
    
    const html = node.textContent.replace(regex, '<mark class="bg-warning">$1</mark>');
    if (html !== node.textContent) {
      const span = document.createElement('span');
      span.innerHTML = html;
      parent.replaceChild(span, node);
    }
  });
}

/**
 * الحصول على جميع text nodes
 */
function getTextNodes(element) {
  const textNodes = [];
  const walk = document.createTreeWalker(element, NodeFilter.SHOW_TEXT, null, false);
  
  let node;
  while (node = walk.nextNode()) {
    if (node.textContent.trim()) {
      textNodes.push(node);
    }
  }
  
  return textNodes;
}

// ================================
// 4. البحث الحي مع Debounce
// ================================
// ⚠️ ملاحظة: تم تعطيل هذا عند وجود #searchInput (يستخدم البحث المحلي في book_list.html)
// هذا موجود للتوافق مع صفحات أخرى قد تستخدم [data-live-search]

function initLiveSearch() {
  const searchInput = document.getElementById('searchInput');
  // تخطي البحث AJAX إذا كان البحث المحلي مفعل (في book_list.html)
  if (searchInput) {
    console.log('[Search] Using local search from book_list.html');
    return;
  }
  
  // للصفحات الأخرى التي قد تستخدم AJAX search
  // (تم إبقاء الكود للتوافق العام)
}

// ================================
// 5. تحديثات AJAX للنماذج
// ================================

/**
 * تفعيل إرسال النماذج عبر AJAX
 */
function initAjaxForms() {
  const ajaxForms = document.querySelectorAll('[data-ajax-form]');
  
  ajaxForms.forEach(form => {
    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      
      const submitBtn = form.querySelector('[type="submit"]');
      const originalText = submitBtn?.textContent;
      
      if (submitBtn) {
        submitBtn.disabled = true;
        submitBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>جاري الحفظ...';
      }
      
      try {
        const formData = new FormData(form);
        const response = await fetch(form.action || window.location.href, {
          method: form.method || 'POST',
          body: formData,
          headers: {
            'X-Requested-With': 'XMLHttpRequest',
            'X-CSRFToken': APP.csrfToken,
          },
        });
        
        if (response.ok) {
          const result = await response.json();
          
          if (result.success) {
            showToast(result.message || 'تم الحفظ بنجاح', 'success');
            
            if (result.redirect) {
              setTimeout(() => {
                window.location.href = result.redirect;
              }, 1000);
            } else if (form.dataset.resetOnSuccess !== 'false') {
              form.reset();
            }
          } else {
            showToast(result.message || 'حدث خطأ أثناء الحفظ', 'error');
          }
        } else {
          throw new Error('Response not OK');
        }
      } catch (error) {
        console.error('Form submission error:', error);
        showToast('حدث خطأ أثناء إرسال البيانات', 'error');
      } finally {
        if (submitBtn) {
          submitBtn.disabled = false;
          submitBtn.textContent = originalText;
        }
      }
    });
  });
}

// ================================
// 5. تحديد الكل (Select All)
// ================================

/**
 * تفعيل وظيفة تحديد الكل
 */
function initSelectAll() {
  const selectAllCheckboxes = document.querySelectorAll('[data-select-all]');
  
  selectAllCheckboxes.forEach(masterCheckbox => {
    const targetSelector = masterCheckbox.dataset.selectAll;
    
    masterCheckbox.addEventListener('change', (e) => {
      const checkboxes = document.querySelectorAll(targetSelector);
      checkboxes.forEach(cb => {
        cb.checked = e.target.checked;
        updateRowSelection(cb);
      });
    });
  });
  
  // تحديث master checkbox عند تغيير أي checkbox
  document.addEventListener('change', (e) => {
    if (e.target.type === 'checkbox' && e.target.name === 'selected') {
      updateRowSelection(e.target);
      updateMasterCheckbox(e.target);
    }
  });
}

/**
 * تحديث تحديد الصف
 */
function updateRowSelection(checkbox) {
  const row = checkbox.closest('tr');
  if (row) {
    row.classList.toggle('table-active', checkbox.checked);
  }
}

/**
 * تحديث master checkbox
 */
function updateMasterCheckbox(checkbox) {
  const form = checkbox.closest('form');
  if (!form) return;
  
  const masterCheckbox = form.querySelector('[data-select-all]');
  if (!masterCheckbox) return;
  
  const allCheckboxes = form.querySelectorAll('input[type="checkbox"][name="selected"]');
  const checkedBoxes = form.querySelectorAll('input[type="checkbox"][name="selected"]:checked');
  
  masterCheckbox.checked = allCheckboxes.length > 0 && allCheckboxes.length === checkedBoxes.length;
  masterCheckbox.indeterminate = checkedBoxes.length > 0 && checkedBoxes.length < allCheckboxes.length;
}

// ================================
// 6. إضافة رسوم متحركة
// ================================

/**
 * إضافة fade-in animation للعناصر
 */
function initAnimations() {
  const animatedElements = document.querySelectorAll('[data-animate]');
  
  const observer = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
      if (entry.isIntersecting) {
        entry.target.classList.add('animate-fade-in');
        observer.unobserve(entry.target);
      }
    });
  }, {
    threshold: 0.1,
  });
  
  animatedElements.forEach(el => observer.observe(el));
}

// ================================
// 7. تحسين تجربة المستخدم
// ================================

/**
 * تفعيل tooltips
 */
function initTooltips() {
  const tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'));
  tooltipTriggerList.map(function (tooltipTriggerEl) {
    return new bootstrap.Tooltip(tooltipTriggerEl);
  });
}

/**
 * تفعيل popovers
 */
function initPopovers() {
  const popoverTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="popover"]'));
  popoverTriggerList.map(function (popoverTriggerEl) {
    return new bootstrap.Popover(popoverTriggerEl);
  });
}

/**
 * إضافة smooth scroll
 */
function initSmoothScroll() {
  document.querySelectorAll('a[href^="#"]').forEach(anchor => {
    anchor.addEventListener('click', function (e) {
      const targetId = this.getAttribute('href');
      if (targetId === '#') return;
      
      const target = document.querySelector(targetId);
      if (target) {
        e.preventDefault();
        target.scrollIntoView({
          behavior: 'smooth',
          block: 'start',
        });
      }
    });
  });
}

// ================================
// 8. تهيئة جميع الوظائف عند تحميل الصفحة
// ================================

document.addEventListener('DOMContentLoaded', function() {
  // تفعيل جميع الوظائف
  initTooltips();
  initPopovers();
  initLiveSearch();
  initAjaxForms();
  initSelectAll();
  initAnimations();
  initSmoothScroll();
  
  // تفعيل جميع toasts الموجودة
  const toastElList = [].slice.call(document.querySelectorAll('.toast'));
  toastElList.forEach(function (toastEl) {
    const toastObj = new bootstrap.Toast(toastEl);
    toastObj.show();
  });
  
  // إضافة تأثير loading لجميع الأزرار
  // فخّ حرج: تعطيل الزرّ *داخل* معالج submit يُسقط name/value الخاصّ به من الطلب —
  // المتصفّح يبني قائمة الحقول بعد الحدث، والحقل المُعطَّل لا يُرسَل. لذا كانت أزرار
  // مثل name="action" value="restore_from_bak" تصل فارغة للخادم. نؤجّل التعطيل
  // بـ setTimeout(0) ليقع بعد بناء الطلب، ونتخطّاه إن أُلغي الإرسال (confirm) وإلا
  // بقي الزرّ معطّلاً للأبد.
  document.querySelectorAll('button[type="submit"]').forEach(btn => {
    const form = btn.closest('form');
    if (!form || form.hasAttribute('data-ajax-form')) return;
    form.addEventListener('submit', function(e) {
      if (e.defaultPrevented) return;
      const label = btn.textContent;
      setTimeout(() => {
        btn.disabled = true;
        btn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>' + label;
      }, 0);
    });
  });
  
  console.log('✅ نظام إدارة الكتب - تم تحميل جميع الوظائف بنجاح');
});

// ================================
// 9. AJAX Delete with Undo
// ================================

/**
 * نظام حذف ذكي محسّن - يدعم الحذف الفردي والجماعي
 */
const DeleteManager = {
  undoTimeouts: new Map(),
  pendingDeletes: new Set(),
  
  /**
   * تهيئة نظام الحذف
   */
  init() {
    this.initSingleDelete();
    this.initBulkDelete();
  },
  
  /**
   * حذف فردي لكتاب واحد
   */
  initSingleDelete() {
    document.querySelectorAll('.btn-delete-ajax').forEach(btn => {
      // إزالة المستمعات القديمة
      btn.replaceWith(btn.cloneNode(true));
    });
    
    document.querySelectorAll('.btn-delete-ajax').forEach(btn => {
      btn.addEventListener('click', async (e) => {
        e.preventDefault();
        e.stopPropagation();
        
        const bookId = btn.getAttribute('data-book-id');
        const container = btn.closest('tr')
          || btn.closest('.card')
          || btn.closest('[class*="col-"]'); // يدعم بطاقات العرض في الشاشات الصغيرة
        
        if (!bookId) {
          showToast('خطأ: معرف الكتاب غير صحيح', 'error');
          return;
        }
        
        // تعطيل الزر مؤقتاً
        const originalHTML = btn.innerHTML;
        btn.disabled = true;
        btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span>';
        
        try {
          const response = await fetchJSON(`/books/api/book/${bookId}/delete/`, {
            method: 'POST'
          });
          
          if (response.status === 'ok') {
            this.handleSuccessfulDelete(bookId, container, response);
          } else {
            showToast(response.message || 'فشل الحذف', 'error');
            btn.disabled = false;
            btn.innerHTML = originalHTML;
          }
        } catch (error) {
          console.error('Delete error:', error);
          showToast('خطأ في الاتصال بالخادم', 'error');
          btn.disabled = false;
          btn.innerHTML = originalHTML;
        }
      });
    });
  },
  
  /**
   * حذف جماعي للكتب المحددة
   */
  initBulkDelete() {
    const bulkDeleteBtn = document.getElementById('bulk-delete-btn');
    if (!bulkDeleteBtn) return;
    
    bulkDeleteBtn.addEventListener('click', async (e) => {
      e.preventDefault();
      
      const selectedCheckboxes = document.querySelectorAll('#bookTableBody input[type="checkbox"]:checked');
      const bookIds = Array.from(selectedCheckboxes).map(cb => {
        const row = cb.closest('tr');
        const deleteBtn = row?.querySelector('.btn-delete-ajax');
        return deleteBtn?.getAttribute('data-book-id');
      }).filter(Boolean);
      
      if (bookIds.length === 0) {
        showToast('الرجاء تحديد كتاب واحد على الأقل', 'warning');
        return;
      }
      
      if (!confirm(`هل تريد نقل ${bookIds.length} كتاب إلى سلة المهملات؟`)) {
        return;
      }
      
      // تعطيل الزر
      const originalHTML = bulkDeleteBtn.innerHTML;
      bulkDeleteBtn.disabled = true;
      bulkDeleteBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>جاري الحذف...';
      
      try {
        const response = await fetchJSON('/books/api/books/bulk-delete/', {
          method: 'POST',
          body: JSON.stringify({ book_ids: bookIds })
        });
        
        if (response.status === 'ok') {
          // إزالة الصفوف المحذوفة
          response.deleted_ids.forEach(bookId => {
            const row = document.querySelector(`.btn-delete-ajax[data-book-id="${bookId}"]`)?.closest('tr');
            if (row) {
              row.style.opacity = '0';
              row.style.transition = 'opacity 0.3s ease';
              setTimeout(() => row.remove(), 300);
            }
          });
          
          showToast(response.message, 'success', 4000);
          
          // إعادة تعيين العدادات
          const selectAllCheckbox = document.querySelector('.select-all-checkbox');
          if (selectAllCheckbox) {
            selectAllCheckbox.checked = false;
          }
          if (window.updateSelectionCounter) {
            window.updateSelectionCounter();
          }
        } else {
          showToast(response.message || 'فشل الحذف الجماعي', 'error');
        }
      } catch (error) {
        console.error('Bulk delete error:', error);
        showToast('خطأ في الحذف الجماعي', 'error');
      } finally {
        bulkDeleteBtn.disabled = false;
        bulkDeleteBtn.innerHTML = originalHTML;
      }
    });
  },
  
  /**
   * معالجة نجاح الحذف مع Undo
   */
  handleSuccessfulDelete(bookId, container, response) {
    this.pendingDeletes.add(bookId);
    const target = container
      || document.querySelector(`.btn-delete-ajax[data-book-id="${bookId}"]`)?.closest('tr')
      || document.querySelector(`.btn-delete-ajax[data-book-id="${bookId}"]`)?.closest('.card')
      || document.querySelector(`.btn-delete-ajax[data-book-id="${bookId}"]`)?.closest('[class*="col-"]');
    
    // إخفاء العنصر بسلاسة إن وجد
    if (target) {
      target.style.opacity = '0';
      target.style.transition = 'opacity 0.3s ease';
    }
    
    // إنشاء زر التراجع
    const undoBtn = document.createElement('button');
    undoBtn.className = 'btn btn-sm btn-warning ms-2';
    undoBtn.innerHTML = '<i class="bi bi-arrow-counterclockwise me-1"></i>تراجع';
    undoBtn.onclick = (e) => {
      e.preventDefault();
      if (target) {
        this.undoDelete(bookId, target);
      }
    };
    
    showToastWithAction(
      response.message || 'تم الحذف بنجاح',
      'success',
      undoBtn,
      5000
    );
    
    // إزالة العنصر بعد 5 ثواني
    if (target) {
      const timeoutId = setTimeout(() => {
        if (target && target.parentNode) {
          target.remove();
          this.pendingDeletes.delete(bookId);
        }
      }, 5000);
      this.undoTimeouts.set(bookId, timeoutId);
    } else {
      // في حالة عدم وجود عنصر لعرض التغيير، أعد تعيين الحالة مباشرة
      this.pendingDeletes.delete(bookId);
    }
  },
  
  /**
   * التراجع عن الحذف
   */
  async undoDelete(bookId, row) {
    // إلغاء مؤقت الحذف النهائي
    const timeoutId = this.undoTimeouts.get(bookId);
    if (timeoutId) {
      clearTimeout(timeoutId);
      this.undoTimeouts.delete(bookId);
    }
    
    try {
      const response = await fetchJSON(`/books/api/book/${bookId}/undo-delete/`, {
        method: 'POST'
      });
      
      if (response.status === 'ok') {
        // إعادة الصف
        row.style.opacity = '1';
        row.style.transition = 'opacity 0.3s ease';
        this.pendingDeletes.delete(bookId);
        
        showToast(response.message || 'تم التراجع بنجاح', 'success');
      } else {
        showToast(response.message || 'فشل التراجع', 'error');
        // إزالة الصف إذا فشل التراجع
        row.remove();
      }
    } catch (error) {
      console.error('Undo error:', error);
      showToast('خطأ في التراجع عن الحذف', 'error');
      row.remove();
    }
  }
};

// استبدال الدالة القديمة
function initAjaxDeleteButtons() {
  DeleteManager.init();
}

/**
 * عرض Toast مع زر إجراء
 */
function showToastWithAction(message, type = 'info', actionBtn = null, duration = APP.toastDuration) {
  const toastCenter = resolveToastCenter();
  if (!toastCenter) {
    return showToast(message, type, duration);
  }

  const actions = actionBtn ? [legacyActionButtonToToastAction(actionBtn)] : [];
  return toastCenter.action(type, message, actions, {
    delay: duration,
    autohide: actions.length === 0,
  });
}

// ================================
// 10. تصدير للاستخدام العام
// ================================

window.LetterSystem = {
  showToast,
  showToastWithAction,
  confirmDelete,
  fetchJSON,
  debounce,
};

// ================================
// 10. PWA - Service Worker Registration
// ================================

/**
 * تسجيل Service Worker لتفعيل PWA
 */
if ('serviceWorker' in navigator) {
  window.addEventListener('load', async () => {
    try {
      const registration = await navigator.serviceWorker.register('/service-worker.js', {
        scope: '/',
      });
      
      console.log('✅ Service Worker registered successfully:', registration.scope);
      
      // التحقق من التحديثات
      registration.addEventListener('updatefound', () => {
        const newWorker = registration.installing;
        
        newWorker.addEventListener('statechange', () => {
          if (newWorker.state === 'installed' && navigator.serviceWorker.controller) {
            // يوجد تحديث جديد
            showUpdateNotification();
          }
        });
      });
      
      // طلب إذن الإشعارات
      if ('Notification' in window && Notification.permission === 'default') {
        setTimeout(() => {
          requestNotificationPermission();
        }, 5000); // بعد 5 ثوانٍ من تحميل الصفحة
      }
      
    } catch (error) {
      console.error('❌ Service Worker registration failed:', error);
    }
  });
}

/**
 * إظهار إشعار بوجود تحديث
 */
function showUpdateNotification() {
  showUpdatePrompt();
}

/**
 * طلب إذن الإشعارات
 */
async function requestNotificationPermission() {
  if (!('Notification' in window)) {
    console.log('هذا المتصفح لا يدعم الإشعارات');
    return;
  }
  
  try {
    const permission = await Notification.requestPermission();
    
    if (permission === 'granted') {
      console.log('✅ تم منح إذن الإشعارات');
      showToast('تم تفعيل الإشعارات بنجاح', 'success');
      
      // إرسال إشعار تجريبي
      if (navigator.serviceWorker.controller) {
        new Notification('نظام إدارة الكتب', {
          body: 'تم تفعيل الإشعارات بنجاح!',
          icon: '/static/img/icon-192x192.png',
          badge: '/static/img/icon-96x96.png',
        });
      }
    } else {
      console.log('❌ تم رفض إذن الإشعارات');
    }
  } catch (error) {
    console.error('خطأ في طلب إذن الإشعارات:', error);
  }
}

/**
 * إظهار زر التثبيت (Install Prompt)
 */
let deferredPrompt;

window.addEventListener('beforeinstallprompt', (e) => {
  // منع إظهار الإشعار التلقائي
  e.preventDefault();
  deferredPrompt = e;
  
  // إظهار زر التثبيت المخصص
  showInstallButton();
});

/**
 * إظهار زر التثبيت
 */
function showInstallButton() {
  const installBanner = document.createElement('div');
  installBanner.className = 'position-fixed bottom-0 start-0 end-0 p-3 animate-slide-up';
  installBanner.style.zIndex = '9999';
  installBanner.id = 'installBanner';
  installBanner.innerHTML = `
    <div class="alert alert-success d-flex justify-content-between align-items-center shadow-lg glass-effect" role="alert">
      <div class="d-flex align-items-center gap-2">
        <i class="bi bi-download fs-4"></i>
        <span>ثبّت التطبيق على جهازك للوصول السريع</span>
      </div>
      <div class="d-flex gap-2">
        <button class="btn btn-sm btn-success" id="installButton">
          <i class="bi bi-plus-circle me-1"></i>تثبيت
        </button>
        <button class="btn btn-sm btn-outline-secondary" id="dismissInstall">
          <i class="bi bi-x"></i>
        </button>
      </div>
    </div>
  `;
  
  document.body.appendChild(installBanner);
  
  // معالج زر التثبيت
  document.getElementById('installButton').addEventListener('click', async () => {
    if (!deferredPrompt) return;
    
    deferredPrompt.prompt();
    const { outcome } = await deferredPrompt.userChoice;
    
    console.log(`User response: ${outcome}`);
    
    if (outcome === 'accepted') {
      showToast('تم تثبيت التطبيق بنجاح!', 'success');
    }
    
    deferredPrompt = null;
    document.getElementById('installBanner')?.remove();
  });
  
  // معالج زر الإغلاق
  document.getElementById('dismissInstall').addEventListener('click', () => {
    document.getElementById('installBanner')?.remove();
  });
}

/**
 * معالجة حالة الاتصال بالإنترنت
 */
window.addEventListener('online', () => {
  showToast('تم الاتصال بالإنترنت', 'success');
  document.body.classList.remove('offline-mode');
});

window.addEventListener('offline', () => {
  showToast('لا يوجد اتصال بالإنترنت - يعمل النظام في وضع عدم الاتصال', 'warning', 5000);
  document.body.classList.add('offline-mode');
});

// ================================
// 11. Dark Mode Support
// ================================

/**
 * إدارة الوضع الليلي
 */

// ================================
// Filter State Manager (localStorage)
// ================================
const FilterStateManager = {
  // List of filter fields to persist
  filterFields: [
    'q',           // search query
    'kind',        // kind filter
    'status',      // status filter
    'date_from',   // date range start
    'date_to',     // date range end
    'due_status',  // due date status
    'entity_id',   // entity filter
    'sort',        // sort by
    'sort_dir'     // sort direction
  ],
  
  storageKey: 'bookListFilters',
  
  init() {
    // Restore filters from localStorage on page load
    this.restoreFilters();
    
    // Save filters whenever form changes
    const filterForm = document.querySelector('form[method="get"]');
    if (filterForm) {
      // Save on input/change events
      filterForm.querySelectorAll('input, select').forEach(input => {
        input.addEventListener('change', () => this.saveFilters());
      });
      
      // Also save on form submit
      filterForm.addEventListener('submit', () => this.saveFilters());
    }
  },
  
  saveFilters() {
    const filterForm = document.querySelector('form[method="get"]');
    if (!filterForm) return;
    
    const filters = {};
    this.filterFields.forEach(field => {
      const input = filterForm.querySelector(`[name="${field}"]`);
      if (input) {
        filters[field] = input.value;
      }
    });
    
    // Save to localStorage
    try {
      localStorage.setItem(this.storageKey, JSON.stringify(filters));
    } catch (e) {
      console.warn('Failed to save filters to localStorage:', e);
    }
  },
  
  saveFilterState() {
    return this.saveFilters();
  },
  
  restoreFilters() {
    try {
      const saved = localStorage.getItem(this.storageKey);
      if (!saved) return;
      
      const filters = JSON.parse(saved);
      const filterForm = document.querySelector('form[method="get"]');
      if (!filterForm) return;
      
      // Restore each filter field (except if URL already has values)
      this.filterFields.forEach(field => {
        const urlParam = new URLSearchParams(window.location.search).get(field);
        if (urlParam === null && filters[field]) {
          const input = filterForm.querySelector(`[name="${field}"]`);
          if (input) {
            input.value = filters[field];
          }
        }
      });
    } catch (e) {
      console.warn('Failed to restore filters from localStorage:', e);
    }
  },
  
  loadFilterState() {
    return this.restoreFilters();
  },
  
  clearFilters() {
    try {
      localStorage.removeItem(this.storageKey);
    } catch (e) {
      console.warn('Failed to clear filters from localStorage:', e);
    }
  }
};

function updateSelectionCounter() {
  const allCheckboxes = document.querySelectorAll('.row-checkbox');
  const selectedCheckboxes = document.querySelectorAll('.row-checkbox:checked');
  const totalCount = allCheckboxes.length;
  const selectedCount = selectedCheckboxes.length;
  
  // Update counter in button
  const countSpan = document.getElementById('selectedCount');
  if (countSpan) {
    countSpan.textContent = selectedCount;
  }
  
  // Update selection info
  const selectionInfo = document.getElementById('selectionInfo');
  if (selectionInfo) {
    if (selectedCount > 0) {
      selectionInfo.textContent = `${selectedCount} من ${totalCount} محدد`;
    } else {
      selectionInfo.textContent = '';
    }
  }
  
  // Enable/disable bulk delete button
  const deleteBtn = document.querySelector('.bulk-delete-btn');
  if (deleteBtn) {
    deleteBtn.disabled = selectedCount === 0;
  }
  
  // Update select-all checkbox state
  const selectAllCheckbox = document.querySelector('.select-all-checkbox');
  if (selectAllCheckbox) {
    selectAllCheckbox.checked = selectedCount > 0 && selectedCount === totalCount;
    selectAllCheckbox.indeterminate = selectedCount > 0 && selectedCount < totalCount;
  }
}

// Initialize selection counter on page load
document.addEventListener('DOMContentLoaded', () => {
  updateSelectionCounter();
  
  // Attach event listeners to checkboxes for future AJAX updates
  document.querySelectorAll('.row-checkbox').forEach(cb => {
    cb.addEventListener('change', updateSelectionCounter);
  });
});

const DarkMode = {
  init() {
    // قراءة الإعداد المحفوظ
    const savedTheme = localStorage.getItem('theme') || 'light';
    this.setTheme(savedTheme);
    
    // إضافة زر التبديل
    this.createToggleButton();
  },
  
  setTheme(theme) {
    document.documentElement.setAttribute('data-theme', theme);
    localStorage.setItem('theme', theme);
    
    // تحديث أيقونة الزر
    const icon = document.querySelector('#darkModeToggle i');
    if (icon) {
      icon.className = theme === 'dark' ? 'bi bi-sun-fill' : 'bi bi-moon-fill';
    }
  },
  
  toggle() {
    const currentTheme = document.documentElement.getAttribute('data-theme') || 'light';
    const newTheme = currentTheme === 'light' ? 'dark' : 'light';
    this.setTheme(newTheme);
    
    showToast(
      newTheme === 'dark' ? 'تم تفعيل الوضع الليلي' : 'تم تفعيل الوضع النهاري',
      'info'
    );
  },
  
  createToggleButton() {
    // البحث عن navbar
    const navbar = document.querySelector('.navbar-nav');
    if (!navbar) return;
    
    // إنشاء زر التبديل
    const toggleLi = document.createElement('li');
    toggleLi.className = 'nav-item';
    toggleLi.innerHTML = `
      <button class="btn btn-sm btn-outline-secondary rounded-pill" id="darkModeToggle" title="تبديل الوضع الليلي">
        <i class="bi bi-moon-fill"></i>
      </button>
    `;
    
    // إضافة الزر قبل آخر عنصر
    const lastItem = navbar.lastElementChild;
    navbar.insertBefore(toggleLi, lastItem);
    
    // ربط الحدث
    document.getElementById('darkModeToggle').addEventListener('click', () => {
      this.toggle();
    });
  },
};

// ================================
// Moderate Improvements - Advanced Features
// ================================

// ✨ Back-to-Top Button
class BackToTopButton {
  constructor() {
    this.button = null;
    this.init();
  }
  
  init() {
    // Create button
    this.button = document.createElement('button');
    this.button.className = 'back-to-top';
    this.button.innerHTML = '<i class="bi bi-arrow-up"></i>';
    this.button.title = 'العودة للأعلى (Home)';
    document.body.appendChild(this.button);
    
    // Show/Hide on scroll
    window.addEventListener('scroll', () => this.updateVisibility());
    
    // Scroll on click
    this.button.addEventListener('click', () => this.scrollToTop());
    
    // Keyboard shortcut (Home key)
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Home') {
        e.preventDefault();
        this.scrollToTop();
      }
    });
  }
  
  updateVisibility() {
    if (window.scrollY > 300) {
      if (!this.button.classList.contains('show')) {
        this.button.classList.add('show', 'animate-pop');
      }
    } else {
      this.button.classList.remove('show');
    }
  }
  
  scrollToTop() {
    window.scrollTo({
      top: 0,
      behavior: 'smooth'
    });
  }
}

// ✨ Breadcrumbs Navigation
// ✨ Advanced Keyboard Shortcuts System
class KeyboardShortcutsManager {
  constructor() {
    this.shortcuts = {
      '?': { description: 'عرض قائمة الاختصارات', action: () => this.showShortcutsHelp() },
      'Escape': { description: 'إغلاق الـ Modals', action: () => this.closeAllModals() },
      'g-l': { description: 'الذهاب إلى قائمة الكتب', action: () => this.navigateTo('/books/') },
      'g-d': { description: 'الذهاب إلى لوحة التحكم', action: () => this.navigateTo('/') },
      'n': { description: 'إضافة كتاب جديد', action: () => this.navigateTo('/books/extract/smart-desktop/') },
      's': { description: 'التركيز على حقل البحث', action: () => this.focusSearch() },
    };
    
    this.init();
  }
  
  init() {
    document.addEventListener('keydown', (e) => {
      // تجاهل إذا كان المستخدم يكتب في input
      if (e.target.matches('input, textarea')) return;
      
      if (e.key === '?') {
        e.preventDefault();
        this.showShortcutsHelp();
      }
      
      if (e.key === 'Escape') {
        this.closeAllModals();
      }
    });
    
    // Sequence shortcuts (مثل g-l)
    let lastKey = '';
    document.addEventListener('keydown', (e) => {
      if (e.target.matches('input, textarea')) return;
      
      if (e.key === 'g') {
        lastKey = 'g';
        setTimeout(() => { lastKey = ''; }, 1000);
        return;
      }
      
      if (lastKey === 'g') {
        if (e.key === 'l') this.navigateTo('/books/');
        if (e.key === 'd') this.navigateTo('/');
        lastKey = '';
      }
    });
  }
  
  showShortcutsHelp() {
    const modal = document.createElement('div');
    modal.className = 'modal fade';
    modal.id = 'shortcutsHelpModal';
    modal.innerHTML = `
      <div class="modal-dialog modal-lg">
        <div class="modal-content shortcuts-modal">
          <div class="modal-header">
            <h5 class="modal-title"><i class="bi bi-keyboard me-2"></i>اختصارات لوحة المفاتيح</h5>
            <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
          </div>
          <div class="modal-body">
            <table class="table table-sm">
              <thead>
                <tr>
                  <th>الاختصار</th>
                  <th>الوصف</th>
                </tr>
              </thead>
              <tbody>
                ${Object.entries(this.shortcuts).map(([key, info]) => `
                  <tr>
                    <td><span class="shortcut-key">${key}</span></td>
                    <td>${info.description}</td>
                  </tr>
                `).join('')}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    `;
    
    document.body.appendChild(modal);
    new bootstrap.Modal(modal).show();
    modal.addEventListener('hidden.bs.modal', () => modal.remove());
  }
  
  closeAllModals() {
    document.querySelectorAll('.modal.show').forEach(modal => {
      bootstrap.Modal.getInstance(modal)?.hide();
    });
  }
  
  navigateTo(url) {
    window.location.href = url;
  }
  
  focusSearch() {
    const searchInput = document.getElementById('searchInput');
    if (searchInput) {
      searchInput.focus();
      searchInput.select();
    }
  }
}

// ✨ Lazy Loading for Images
class LazyLoadingManager {
  constructor(options = {}) {
    this.options = {
      threshold: 0.1,
      rootMargin: '50px',
      ...options
    };
    this.init();
  }
  
  init() {
    // Check if Intersection Observer is supported
    if (!('IntersectionObserver' in window)) {
      this.loadAllImages();
      return;
    }
    
    // Create observer
    const observer = new IntersectionObserver((entries) => {
      entries.forEach(entry => {
        if (entry.isIntersecting) {
          this.loadImage(entry.target);
          observer.unobserve(entry.target);
        }
      });
    }, this.options);
    
    // Observe all lazy images
    document.querySelectorAll('img[data-src]').forEach(img => {
      observer.observe(img);
    });
  }
  
  loadImage(img) {
    const src = img.getAttribute('data-src');
    if (!src) return;
    
    img.src = src;
    img.classList.add('lazy-loaded');
    img.removeAttribute('data-src');
    
    // Optional: add fade-in animation
    img.style.animation = 'fadeIn 0.3s ease-in';
  }
  
  loadAllImages() {
    document.querySelectorAll('img[data-src]').forEach(img => {
      this.loadImage(img);
    });
  }
}

// ✨ Performance Optimization - Request Animation Frame
class PerformanceOptimizer {
  constructor() {
    this.init();
  }
  
  init() {
    // Smooth scrolling optimization
    this.optimizeSmoothScroll();
    
    // Debounce resize events
    this.optimizeResizeEvents();
    
    // Lazy load inline content
    this.lazyLoadInlineContent();
  }
  
  optimizeSmoothScroll() {
    document.querySelectorAll('a[href^="#"]').forEach(link => {
      link.addEventListener('click', (e) => {
        const target = document.querySelector(link.getAttribute('href'));
        if (target) {
          e.preventDefault();
          target.scrollIntoView({ behavior: 'smooth', block: 'start' });
        }
      });
    });
  }
  
  optimizeResizeEvents() {
    let resizeTimer;
    window.addEventListener('resize', () => {
      clearTimeout(resizeTimer);
      resizeTimer = setTimeout(() => {
        // Trigger resize handlers
        window.dispatchEvent(new Event('optimized-resize'));
      }, 300);
    });
  }
  
  lazyLoadInlineContent() {
    const contentBlocks = document.querySelectorAll('[data-lazy-content]');
    if (!contentBlocks.length) return;
    
    const observer = new IntersectionObserver((entries) => {
      entries.forEach(entry => {
        if (entry.isIntersecting) {
          this.loadInlineContent(entry.target);
          observer.unobserve(entry.target);
        }
      });
    }, { threshold: 0.1 });
    
    contentBlocks.forEach(block => observer.observe(block));
  }
  
  loadInlineContent(element) {
    const html = element.getAttribute('data-lazy-content');
    if (html) {
      element.innerHTML = html;
      element.removeAttribute('data-lazy-content');
      element.classList.add('lazy-loaded');
    }
  }
}

// تفعيل Dark Mode
document.addEventListener('DOMContentLoaded', () => {
  DarkMode.init();
  
  // Initialize Moderate Improvements
  new BackToTopButton();
  // BreadcrumbManager - disabled
  new KeyboardShortcutsManager();
  new LazyLoadingManager();
  new PerformanceOptimizer();
});

// ===================== ToastCenter (Centered toasts with icons) =====================
function initBootstrapToastsCenter() {
  var container = document.querySelector('.toast-center');
  if (!container) return;
  container.querySelectorAll('.toast').forEach(function(el){
    try {
      var t = new bootstrap.Toast(el);
      setTimeout(function(){ t.show(); }, 200);
      el.addEventListener('hidden.bs.toast', function(){ t.dispose(); });
    } catch (_) {}
  });
}

function getToastMeta(type) {
  var palette = {
    success: {
      accent: 'bg-success',
      icon: 'bi-check-circle-fill',
      iconClass: 'text-success',
      title: 'تمت العملية بنجاح',
      delay: 3800,
    },
    warning: {
      accent: 'bg-warning',
      icon: 'bi-exclamation-triangle-fill',
      iconClass: 'text-warning',
      title: 'تنبيه',
      delay: 5000,
    },
    error: {
      accent: 'bg-danger',
      icon: 'bi-x-circle-fill',
      iconClass: 'text-danger',
      title: 'تعذر إكمال العملية',
      delay: 6000,
    },
    info: {
      accent: 'bg-primary',
      icon: 'bi-info-circle-fill',
      iconClass: 'text-primary',
      title: 'معلومة',
      delay: 3800,
    }
  };

  return palette[type] || palette.info;
}

function legacyActionButtonToToastAction(actionBtn) {
  return {
    html: actionBtn.innerHTML,
    className: actionBtn.className || 'btn btn-sm btn-outline-primary',
    onClick: function(event) {
      if (typeof actionBtn.onclick === 'function') {
        actionBtn.onclick.call(actionBtn, event);
        return;
      }

      actionBtn.dispatchEvent(new MouseEvent('click', {
        bubbles: true,
        cancelable: true,
        view: window,
      }));
    },
  };
}

function normalizeToastActions(actions) {
  if (!Array.isArray(actions)) {
    return [];
  }

  return actions.filter(Boolean).map(function(action) {
    if (typeof action === 'string') {
      return { label: action };
    }
    return action;
  });
}

function buildToastActionButton(action, toastApi) {
  var button = document.createElement('button');
  button.type = 'button';
  button.className = action.className || 'btn btn-sm btn-outline-secondary';

  if (action.html) {
    button.innerHTML = action.html;
  } else {
    button.textContent = action.label || 'إجراء';
  }

  if (action.title) {
    button.title = action.title;
  }

  button.addEventListener('click', function(event) {
    var result;
    if (typeof action.onClick === 'function') {
      result = action.onClick(event, toastApi);
    }

    if (action.dismiss === false) {
      return;
    }

    if (result && typeof result.then === 'function') {
      button.disabled = true;
      Promise.resolve(result)
        .catch(function(error) {
          console.error('Toast action failed:', error);
        })
        .finally(function() {
          button.disabled = false;
          toastApi.hide();
        });
      return;
    }

    toastApi.hide();
  });

  return button;
}

window.ToastCenter = {
  show: function(type, message, opts) {
    type = type || 'info';
    opts = opts || {};

    var container = createToastContainer();
    if (!container || typeof bootstrap === 'undefined' || !bootstrap.Toast) {
      console.warn('ToastCenter unavailable:', message);
      return null;
    }

    var meta = getToastMeta(type);
    var actions = normalizeToastActions(opts.actions);
    var autohide = opts.autohide != null ? opts.autohide : actions.length === 0;
    var delay = opts.delay != null ? opts.delay : (autohide ? meta.delay : 0);
    var titleText = opts.title === false ? '' : (opts.title || meta.title);
    var bodyText = message == null ? '' : String(message);
    var iconClass = opts.iconClass || meta.icon;
    var iconToneClass = opts.iconToneClass || meta.iconClass;

    var toastEl = document.createElement('div');
    toastEl.className = 'toast fancy-toast unified-toast';
    toastEl.setAttribute('role', type === 'error' ? 'alert' : 'status');
    toastEl.setAttribute('aria-live', type === 'error' ? 'assertive' : 'polite');
    toastEl.setAttribute('aria-atomic', 'true');
    toastEl.dataset.bsAutohide = autohide ? 'true' : 'false';
    toastEl.dataset.bsDelay = String(delay);

    var shell = document.createElement('div');
    shell.className = 'd-flex align-items-start position-relative';

    var accent = document.createElement('div');
    accent.className = 'toast-accent ' + meta.accent;
    shell.appendChild(accent);

    var body = document.createElement('div');
    body.className = 'toast-body d-flex align-items-start gap-3 w-100';

    var iconWrap = document.createElement('div');
    iconWrap.className = 'pt-1';
    var icon = document.createElement('i');
    icon.className = 'bi ' + iconClass + ' fs-4 ' + iconToneClass;
    iconWrap.appendChild(icon);
    body.appendChild(iconWrap);

    var copy = document.createElement('div');
    copy.className = 'flex-grow-1';

    if (titleText) {
      var titleEl = document.createElement('div');
      titleEl.className = 'fw-semibold text-dark mb-1';
      titleEl.textContent = titleText;
      copy.appendChild(titleEl);
    }

    if (bodyText) {
      var messageEl = document.createElement('div');
      messageEl.className = titleText ? 'text-muted small' : 'fw-semibold text-dark';
      messageEl.textContent = bodyText;
      copy.appendChild(messageEl);
    }

    body.appendChild(copy);

    if (opts.closeButton !== false) {
      var closeBtn = document.createElement('button');
      closeBtn.type = 'button';
      closeBtn.className = 'btn-close ms-2 mt-1';
      closeBtn.setAttribute('data-bs-dismiss', 'toast');
      closeBtn.setAttribute('aria-label', 'إغلاق');
      body.appendChild(closeBtn);
    }

    shell.appendChild(body);
    toastEl.appendChild(shell);
    container.appendChild(toastEl);

    var toast = bootstrap.Toast.getOrCreateInstance(toastEl, {
      autohide: autohide,
      delay: delay,
    });
    var toastApi = {
      element: toastEl,
      instance: toast,
      hide: function() {
        toast.hide();
      },
    };

    if (actions.length) {
      var actionsWrap = document.createElement('div');
      actionsWrap.className = 'd-flex flex-wrap gap-2 mt-3';
      copy.appendChild(actionsWrap);
      actions.forEach(function(action) {
        actionsWrap.appendChild(buildToastActionButton(action, toastApi));
      });
    }

    if (typeof opts.onShown === 'function') {
      toastEl.addEventListener('shown.bs.toast', function() {
        opts.onShown(toastApi);
      }, { once: true });
    }

    toastEl.addEventListener('hidden.bs.toast', function() {
      toast.dispose();
      toastEl.remove();
      if (typeof opts.onHidden === 'function') {
        opts.onHidden(toastApi);
      }
    }, { once: true });

    toast.show();
    return toastApi;
  },

  action: function(type, message, actions, opts) {
    opts = opts || {};
    opts.actions = actions || opts.actions || [];
    if (opts.autohide == null) {
      opts.autohide = false;
    }
    var toastApi = this.show(type, message, opts);
    if (!toastApi && typeof opts.onUnavailable === 'function') {
      opts.onUnavailable();
    }
    return toastApi;
  },

  confirm: function(opts) {
    opts = opts || {};
    var self = this;

    return new Promise(function(resolve) {
      var settled = false;
      function finish(value) {
        if (settled) {
          return;
        }
        settled = true;
        resolve(value);
      }

      var title = opts.title || 'تأكيد العملية';
      var message = opts.message || 'هل تريد المتابعة؟';
      var fallbackMessage = opts.fallbackMessage || (title + '\n\n' + message);

      var toastApi = self.action(opts.type || 'warning', message, [
        {
          label: opts.cancelLabel || 'إلغاء',
          className: opts.cancelClassName || 'btn btn-sm btn-outline-secondary',
          onClick: function() {
            finish(false);
          },
        },
        {
          label: opts.confirmLabel || 'متابعة',
          className: opts.confirmClassName || 'btn btn-sm btn-primary',
          onClick: function() {
            finish(true);
          },
        }
      ], {
        title: title,
        delay: opts.delay != null ? opts.delay : 0,
        autohide: false,
        iconClass: opts.iconClass,
        iconToneClass: opts.iconToneClass,
        onHidden: function() {
          finish(false);
        },
      });

      if (!toastApi) {
        finish(window.confirm(fallbackMessage));
      }
    });
  },
};

if (window.LetterSystem) {
  window.LetterSystem.toast = window.ToastCenter;
}

// Backward-compatible wrapper for legacy showToast calls
window.showToast = function(message, type, delay) {
  return showToast(message, type, delay);
};

document.addEventListener('DOMContentLoaded', function(){
  initBootstrapToastsCenter();
  initUpdateNotification();
});

// ===== PWA Update Notification System =====
function initUpdateNotification() {
  if (!('serviceWorker' in navigator)) return;

  // Listen for update messages from service worker
  navigator.serviceWorker.addEventListener('message', (event) => {
    if (event.data.type === 'UPDATE_AVAILABLE') {
      showUpdatePrompt();
    }
  });

  // Check for updates periodically (every 10 minutes)
  setInterval(() => {
    navigator.serviceWorker.getRegistrations().then((registrations) => {
      registrations.forEach((registration) => {
        registration.update();
      });
    });
  }, 10 * 60 * 1000);

  // Check for updates when page becomes visible
  document.addEventListener('visibilitychange', () => {
    if (!document.hidden) {
      navigator.serviceWorker.getRegistrations().then((registrations) => {
        registrations.forEach((registration) => {
          registration.update();
        });
      });
    }
  });
}

function showUpdatePrompt() {
  if (!window.ToastCenter) {
    return;
  }

  const promptToast = window.ToastCenter.action('info', 'نسخة جديدة من التطبيق متاحة الآن', [
    {
      label: 'تحديث الآن',
      className: 'btn btn-sm btn-primary',
      onClick: function() {
        performUpdate();
      },
    },
    {
      label: 'لاحقاً',
      className: 'btn btn-sm btn-outline-secondary',
    }
  ], {
    title: 'تحديث متوفر',
    iconClass: 'bi-download',
    iconToneClass: 'text-primary',
    delay: 0,
    autohide: false,
  });

  if (!promptToast && window.confirm('تحديث متوفر\n\nنسخة جديدة من التطبيق متاحة الآن. هل تريد التحديث الآن؟')) {
    performUpdate();
  }
}

function performUpdate() {
  // Show loading toast
  ToastCenter.show('info', 'جاري تحديث التطبيق... يرجى الانتظار');
  
  navigator.serviceWorker.getRegistrations().then((registrations) => {
    registrations.forEach((registration) => {
      if (registration.waiting) {
        // Send message to waiting service worker to activate immediately
        registration.waiting.postMessage({ type: 'SKIP_WAITING' });
        
        // Listen for the controlled event to reload
        let refreshing = false;
        navigator.serviceWorker.oncontrollerchange = () => {
          if (!refreshing) {
            refreshing = true;
            // Small delay for visual feedback
            setTimeout(() => {
              window.location.reload();
            }, 1000);
          }
        };
      } else if (registration.installing) {
        // If still installing, wait for it to become waiting
        registration.installing.addEventListener('statechange', () => {
          if (registration.waiting && !navigator.serviceWorker.controller) {
            performUpdate();
          }
        });
      }
    });
  });
}

