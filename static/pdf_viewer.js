/**
 * PDF Viewer - uses same modal layout as the scanner preview modal
 * يعيد استخدام نفس تصميم مودال السكانر لعرض المرفقات
 */

(function() {
  'use strict';

  const PDFViewer = {
    currentUrl: '',
    fileName: '',
    currentAttachmentId: null,
    currentBookId: null,
    modalEl: null,
    contentEl: null,
    loadingEl: null,
    errorEl: null,
    errorMsgEl: null,
    statusBadge: null,
    nameLabel: null,
    typeLabel: null,
    urlLabel: null,

    init: function() {
      this.ensureModal();
    },

    notify: function(message, type, title) {
      if (window.ToastCenter && typeof window.ToastCenter.show === 'function') {
        window.ToastCenter.show(type || 'error', message, {
          title: title || 'تعذر إكمال العملية',
          delay: (type || 'error') === 'error' ? 6500 : 4000,
        });
        return;
      }

      alert(message);
    },

    ensureModal: function() {
      if (!document.getElementById('pdfViewerModal')) {
        const modalHTML = `
          <div class="modal fade" id="pdfViewerModal" tabindex="-1">
            <div class="modal-dialog modal-dialog-centered" style="max-width: 800px;">
              <div class="modal-content">
                <div class="modal-header">
                  <h5 class="modal-title"><i class="bi bi-file-earmark-check text-info me-2"></i>معاينة المرفق</h5>
                  <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="إغلاق"></button>
                </div>
                <div class="modal-body" style="min-height:500px; padding: 0;">
                  <div class="d-flex flex-column flex-md-row gap-0 align-items-stretch" style="height: 100%;">
                    <div class="flex-grow-1" id="pdfPreviewPane" style="text-align:center; width: 100%;">
                      <div class="text-center py-4" id="pdfLoadingState">
                        <div class="spinner-border spinner-border-sm text-primary" role="status"></div>
                        <div class="mt-2 text-muted">جاري تحميل المعاينة...</div>
                      </div>
                      <div class="d-none" id="pdfErrorState">
                        <div class="text-danger fw-semibold mb-2">تعذر تحميل الملف</div>
                        <div class="text-muted small" id="pdfErrorMessage"></div>
                      </div>
                      <div class="d-none" id="pdfContentState" style="width: 100%; height: 100%;"></div>
                    </div>
                    <div class="border-start p-3 d-none" id="pdfSidebar" style="min-width:200px; background: #f8f9fa; overflow-y: auto;">
                      <div class="d-flex align-items-center justify-content-between mb-2">
                        <span class="badge bg-info" id="pdfStatusBadge">جاهز للمعاينة</span>
                        <i class="bi bi-check-circle text-success"></i>
                      </div>
                      <div class="small text-muted">اسم الملف</div>
                      <div class="fw-semibold mb-2 text-truncate" id="pdfFileNameLabel">—</div>
                      <div class="small text-muted">النوع</div>
                      <div class="fw-semibold mb-2" id="pdfFileType">—</div>
                      <div class="small text-muted">المصدر</div>
                      <div class="fw-semibold text-break small" id="pdfFileUrl">—</div>
                    </div>
                  </div>
                </div>
                <div class="modal-footer d-flex justify-content-between align-items-center flex-wrap gap-2">
                  <div class="small text-muted" id="pdfActionStatus"></div>
                  <div class="d-flex gap-2 flex-wrap">
                    <button type="button" class="btn btn-outline-primary" id="pdfRefreshPreviewBtn">
                      <i class="bi bi-arrow-clockwise me-1"></i>تحديث المعاينة
                    </button>
                    <button type="button" class="btn btn-primary" id="pdfScanAppendBtn">
                      <i class="bi bi-upc-scan me-1"></i>مسح جديد وإلحاق
                    </button>
                    <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">إغلاق</button>
                  </div>
                </div>
              </div>
            </div>
          </div>`;
        document.body.insertAdjacentHTML('beforeend', modalHTML);
      }

      // دائمًا احصل على references جديدة للعناصر
      this.modalEl = document.getElementById('pdfViewerModal');
      this.contentEl = document.getElementById('pdfContentState');
      this.loadingEl = document.getElementById('pdfLoadingState');
      this.errorEl = document.getElementById('pdfErrorState');
      this.errorMsgEl = document.getElementById('pdfErrorMessage');
      this.statusBadge = document.getElementById('pdfStatusBadge');
      this.nameLabel = document.getElementById('pdfFileNameLabel');
      this.typeLabel = document.getElementById('pdfFileType');
      this.urlLabel = document.getElementById('pdfFileUrl');
      this.sidebarEl = document.getElementById('pdfSidebar');
      this.scanBtn = document.getElementById('pdfScanAppendBtn');
      this.refreshBtn = document.getElementById('pdfRefreshPreviewBtn');
      this.actionStatusEl = document.getElementById('pdfActionStatus');

      // ربط الأحداث فقط مرة واحدة
      if (this.modalEl && !this.modalEl.dataset.cleanupBound) {
        this.modalEl.addEventListener('hidden.bs.modal', () => this.cleanup());
        this.modalEl.dataset.cleanupBound = '1';
      }

      // ربط زر المسح
      if (this.scanBtn && !this.scanBtn.dataset.eventBound) {
        this.scanBtn.addEventListener('click', (e) => {
          e.preventDefault();
          e.stopPropagation();
          this.handleScanAndAppend();
        });
        this.scanBtn.dataset.eventBound = 'true';
      }

      // ربط زر التحديث
      if (this.refreshBtn && !this.refreshBtn.dataset.eventBound) {
        this.refreshBtn.addEventListener('click', (e) => {
          e.preventDefault();
          e.stopPropagation();
          this.refreshContent();
        });
        this.refreshBtn.dataset.eventBound = 'true';
      }
    },

    open: function(fileUrl, fileName = '', options = {}) {
      console.log('=== PDFViewer.open() CALLED ===');
      console.log('Arguments:', { fileUrl, fileName, options });
      console.log('options type:', typeof options);
      console.log('options keys:', Object.keys(options));
      
      if (!fileUrl) return;

      this.currentUrl = fileUrl;
      this.fileName = fileName || this.extractFileName(fileUrl);
      const opts = options || {};
      
      this.currentAttachmentId = opts.attachmentId || null;
      this.currentBookId = opts.bookId || null;
      
      console.log('After assignment:');
      console.log('  currentAttachmentId:', this.currentAttachmentId);
      console.log('  currentBookId:', this.currentBookId);
      console.log('  currentUrl:', this.currentUrl);

      this.ensureModal();
      this.updateActionButtons();

      if (this.nameLabel) this.nameLabel.textContent = this.fileName || '—';
      if (this.typeLabel) this.typeLabel.textContent = this.detectType(fileUrl);
      if (this.urlLabel) this.urlLabel.textContent = fileUrl;
      if (this.statusBadge) this.statusBadge.textContent = 'جاري التحميل';

      const modal = bootstrap.Modal.getOrCreateInstance(this.modalEl);
      modal.show();

      this.loadContent();
    },

    toggleSidebar: function() {
      if (this.sidebarEl) {
        this.sidebarEl.classList.toggle('d-none');
      }
    },

    withCacheBuster: function(url) {
      if (!url) return url;
      const sep = url.includes('?') ? '&' : '?';
      return `${url}${sep}v=${Date.now()}`;
    },

    refreshContent: function() {
      if (!this.currentUrl) return;
      // لا نضيف cache buster للـ PDFs لأنها ثابتة
      const isPdf = this.detectType(this.currentUrl) === 'PDF';
      if (!isPdf) {
        this.currentUrl = this.withCacheBuster(this.currentUrl);
      }
      this.loadContent();
      this.setActionStatus('تم تحديث المعاينة', 'success');
    },

    updateActionButtons: function() {
      // الشروط الضرورية
      const hasAttachmentId = Boolean(this.currentAttachmentId);
      const hasBookId = Boolean(this.currentBookId);
      const isPdf = this.detectType(this.currentUrl) === 'PDF';
      const hasCsrf = Boolean(this.getCsrfToken());
      
      console.log('=== updateActionButtons ===');
      console.log('hasAttachmentId:', hasAttachmentId, '(' + this.currentAttachmentId + ')');
      console.log('hasBookId:', hasBookId, '(' + this.currentBookId + ')');
      console.log('isPdf:', isPdf);
      console.log('hasCsrf:', hasCsrf);
      
      const canScan = hasAttachmentId && hasBookId && isPdf && hasCsrf;
      
      if (this.scanBtn) {
        this.scanBtn.disabled = !canScan;
        if (canScan) {
          this.scanBtn.classList.remove('opacity-50');
          this.setActionStatus('✓ جاهز للمسح والإلحاق', 'success');
        } else {
          this.scanBtn.classList.add('opacity-50');
          if (!hasAttachmentId) {
            this.setActionStatus('⚠ معرف المرفق مفقود', 'muted');
          } else if (!hasBookId) {
            this.setActionStatus('⚠ معرف الكتاب مفقود', 'muted');
          } else if (!isPdf) {
            this.setActionStatus('⚠ الملف يجب أن يكون PDF', 'muted');
          } else {
            this.setActionStatus('⚠ تعذر التحقق من الصلاحيات', 'muted');
          }
        }
      }
    },

    setActionStatus: function(message, type = 'info') {
      if (!this.actionStatusEl) return;
      this.actionStatusEl.textContent = message || '';
      this.actionStatusEl.className = 'small';
      if (type === 'success') {
        this.actionStatusEl.classList.add('text-success');
      } else if (type === 'error') {
        this.actionStatusEl.classList.add('text-danger');
      } else {
        this.actionStatusEl.classList.add('text-muted');
      }
    },

    setScanLoading: function(isLoading) {
      if (!this.scanBtn) return;
      if (isLoading) {
        this.scanBtn.dataset.loading = '1';
        this.scanBtn.disabled = true;
        this.scanBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>جارٍ المسح...';
      } else {
        delete this.scanBtn.dataset.loading;
        this.scanBtn.innerHTML = '<i class="bi bi-upc-scan me-1"></i>مسح جديد وإلحاق';
        this.updateActionButtons();
      }
    },

    handleScanAndAppend: async function() {
      console.log('=== handleScanAndAppend START ===');
      console.log('currentAttachmentId:', this.currentAttachmentId);
      console.log('currentBookId:', this.currentBookId);
      console.log('currentUrl:', this.currentUrl);
      
      // فحوصات صارمة
      if (!this.currentAttachmentId) {
        this.notify('معرف المرفق غير محدد.', 'error', 'تعذر إلحاق المسح');
        console.error('Missing attachmentId');
        return;
      }
      if (!this.currentBookId) {
        this.notify('معرف الكتاب غير محدد.', 'error', 'تعذر إلحاق المسح');
        console.error('Missing bookId');
        return;
      }
      if (!this.scanBtn || this.scanBtn.dataset.loading === '1') {
        console.warn('Button not available or already loading');
        return;
      }

      const csrfToken = this.getCsrfToken();
      if (!csrfToken) {
        this.notify('لم يتم العثور على CSRF Token.', 'error', 'تعذر إرسال الطلب');
        console.error('Missing CSRF token');
        return;
      }
      
      console.log('Starting scan via Protocol Handler...');
      this.setScanLoading(true);
      this.setActionStatus('⏳ جارٍ تشغيل الماسح الضوئي...', 'info');

      try {
        const csrfToken = this.getCsrfToken();
        const resp = await fetch('/books/api/scan/launch/', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken },
          credentials: 'same-origin',
        });
        const data = await resp.json();
        if (!data.ok || !data.scan_url) {
          throw new Error(data.error || 'تعذّر تشغيل الماسح — راجع إعدادات الماسح');
        }
        window.location.href = data.scan_url;
        this.setActionStatus('✓ الماسح يعمل — بعد الانتهاء سيفتح النظام صفحة الاستخراج تلقائياً', 'success');
        if (window.ToastCenter) ToastCenter.show('info', 'الماسح يعمل — اضغط Finish عند الانتهاء');
      } catch (err) {
        this.setActionStatus('✗ ' + (err.message || 'تعذر إتمام المسح'), 'error');
        if (window.ToastCenter) ToastCenter.show('error', err.message || 'تعذر إتمام المسح');
      } finally {
        this.setScanLoading(false);
      }
    },

    loadContent: function() {
      if (!this.contentEl) return;

      this.toggleState('loading');
      this.contentEl.innerHTML = '';

      try {
        const isImage = /(\.jpg|\.jpeg|\.png|\.gif|\.bmp|\.webp)$/i.test(this.currentUrl);
        let node;

        if (isImage) {
          const img = document.createElement('img');
          img.src = this.currentUrl;
          img.style.maxWidth = '100%';
          img.style.maxHeight = '500px';
          img.style.objectFit = 'contain';
          img.style.borderRadius = '8px';
          img.alt = this.fileName || 'image';
          node = img;
        } else {
          const frame = document.createElement('iframe');
          frame.src = this.currentUrl;
          frame.style.width = '100%';
          frame.style.height = '500px';
          frame.style.border = '1px solid #dee2e6';
          frame.style.borderRadius = '8px';
          frame.setAttribute('loading', 'lazy');
          frame.setAttribute('allowfullscreen', '');
          node = frame;
        }

        this.contentEl.appendChild(node);

        setTimeout(() => {
          this.toggleState('content');
          if (this.statusBadge) this.statusBadge.textContent = 'جاهز للمعاينة';
        }, 600);
      } catch (err) {
        this.showError(err?.message || 'حدث خطأ غير متوقع');
      }
    },

    toggleState: function(state) {
      if (this.loadingEl) this.loadingEl.classList.toggle('d-none', state !== 'loading');
      if (this.errorEl) this.errorEl.classList.toggle('d-none', state !== 'error');
      if (this.contentEl) this.contentEl.classList.toggle('d-none', state !== 'content');
    },

    showError: function(message) {
      if (this.errorMsgEl) this.errorMsgEl.textContent = message || '';
      if (this.statusBadge) this.statusBadge.textContent = 'خطأ في التحميل';
      this.toggleState('error');
    },

    cleanup: function() {
      if (this.contentEl) {
        const iframe = this.contentEl.querySelector('iframe');
        if (iframe) iframe.src = 'about:blank';
        this.contentEl.innerHTML = '';
      }

      if (this.nameLabel) this.nameLabel.textContent = '—';
      if (this.typeLabel) this.typeLabel.textContent = '—';
      if (this.urlLabel) this.urlLabel.textContent = '—';
      if (this.statusBadge) this.statusBadge.textContent = 'جاهز للمعاينة';

      this.currentUrl = '';
      this.currentAttachmentId = null;
      this.currentBookId = null;
      this.setActionStatus('', 'muted');
      this.updateActionButtons();
      this.toggleState('loading');
    },

    getCsrfToken: function() {
      const tokenEl = document.querySelector('[name=csrfmiddlewaretoken]');
      return tokenEl ? tokenEl.value : '';
    },

    detectType: function(url) {
      const lower = (url || '').toLowerCase();
      if (lower.endsWith('.pdf')) return 'PDF';
      if (/(\.jpg|\.jpeg|\.png|\.gif|\.bmp|\.webp)$/i.test(lower)) return 'صورة';
      return 'ملف';
    },

    extractFileName: function(url) {
      try {
        const parts = url.split('/');
        const filename = parts[parts.length - 1];
        return decodeURIComponent(filename).split('?')[0] || 'ملف';
      } catch (e) {
        return 'ملف';
      }
    }
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => {
      PDFViewer.init();
      window.PDFViewer = PDFViewer;
    });
  } else {
    PDFViewer.init();
    window.PDFViewer = PDFViewer;
  }
})();
