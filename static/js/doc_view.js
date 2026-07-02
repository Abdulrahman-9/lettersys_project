/**
 * doc_view.js — عرض المستندات الموحّد (مصدر واحد)
 * - DocView.fileKind(url)            → 'pdf' | 'image' | 'other'
 * - DocView.buildNode(opts)          → عنصر DOM آمن (iframe/img/رابط)
 * - DocView.open(url, title)         → يفتح الحوار المنبثق #docPreviewModal
 * يستبدل ثلاث نسخ متكرّرة كانت في: document_preview_modal، book_preview_modal، book_detail.js
 */
(function () {
  'use strict';

  var IMAGE_EXTS = ['.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp', '.tif', '.tiff'];
  var SAFE_URL = /^(https?:\/\/|\/)/i;

  function fileKind(url) {
    var path = (url || '').toLowerCase().split('?')[0];
    if (path.endsWith('.pdf')) return 'pdf';
    for (var i = 0; i < IMAGE_EXTS.length; i++) {
      if (path.endsWith(IMAGE_EXTS[i])) return 'image';
    }
    return 'other';
  }

  /**
   * بناء عنصر عرض المستند عبر DOM (لا HTML parsing) — يُحيّد XSS عبر الرابط/الاسم.
   * opts: { url, name?, kind?, frameClass?, imgClass?, linkClass? }
   */
  function buildNode(opts) {
    opts = opts || {};
    var url = opts.url || '';
    var name = opts.name || 'مستند';
    var kind = opts.kind || fileKind(url);
    var safe = SAFE_URL.test(url) ? url : '';

    if (!safe) {
      var err = document.createElement('div');
      err.className = 'text-muted small p-4 text-center';
      err.textContent = 'تعذّر عرض هذا الملف';
      return err;
    }
    if (kind === 'pdf') {
      var frame = document.createElement('iframe');
      frame.src = safe;
      frame.title = name;
      frame.className = opts.frameClass || 'bp-doc-frame';
      return frame;
    }
    if (kind === 'image') {
      var img = document.createElement('img');
      img.src = safe;
      img.alt = name;
      img.className = opts.imgClass || 'bp-doc-img';
      return img;
    }
    var link = document.createElement('a');
    link.href = safe;
    link.target = '_blank';
    link.rel = 'noopener';
    link.className = opts.linkClass || 'btn btn-sm btn-outline-primary m-4';
    var icon = document.createElement('i');
    icon.className = 'bi bi-box-arrow-up-right me-1';
    link.appendChild(icon);
    link.appendChild(document.createTextNode('فتح الملف'));
    return link;
  }

  // ── الحوار المنبثق (#docPreviewModal) ──
  var modalInstance = null;

  function getModal() {
    if (!modalInstance) {
      var el = document.getElementById('docPreviewModal');
      if (el && window.bootstrap) {
        modalInstance = new bootstrap.Modal(el);
        // تفريغ المحتوى عند الإغلاق حتى لا يبقى PDF محمّلاً في الخلفية
        el.addEventListener('hidden.bs.modal', function () {
          var b = document.getElementById('docPreviewBody');
          if (b) b.innerHTML = '';
        });
      }
    }
    return modalInstance;
  }

  function open(url, title) {
    var modal = getModal();
    if (!modal) return;
    var body = document.getElementById('docPreviewBody');
    var nameEl = document.getElementById('docPreviewName');
    var openEl = document.getElementById('docPreviewOpen');

    if (nameEl) nameEl.textContent = title || 'معاينة المستند';
    if (body) {
      body.innerHTML = '';
      body.appendChild(buildNode({
        url: url,
        name: title,
        frameClass: 'doc-preview-frame',
        imgClass: 'doc-preview-img',
      }));
    }
    if (openEl) openEl.href = SAFE_URL.test(url || '') ? url : '#';
    modal.show();
  }

  // أي عنصر يحمل data-doc-preview + data-doc-url (+ data-doc-title) يفتح الحوار
  document.addEventListener('click', function (e) {
    var trigger = e.target.closest('[data-doc-preview]');
    if (!trigger) return;
    e.preventDefault();
    open(trigger.getAttribute('data-doc-url'), trigger.getAttribute('data-doc-title'));
  });

  window.DocView = { fileKind: fileKind, buildNode: buildNode, open: open };
})();
