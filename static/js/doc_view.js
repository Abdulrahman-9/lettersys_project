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

  /* ── الطباعة (قرارُ المالك 2026‑09‑13) ──────────────────────────────
     خياران صريحان: «كما مُسحت» هنا، و«تقريرُ البيانات» رابطٌ إلى صفحة التقرير.
     PDF: يُطبع من داخل الإطار — فيظهر حوارُ المتصفّح **بمدى الصفحات** جاهزاً،
     فلا نبني منتقيَ صفحاتٍ خاصّاً بنا (ازدواجٌ أضعفُ ممّا في المتصفّح).
     الصورة: نافذةٌ نظيفةٌ فيها الصورةُ وحدَها مضبوطةً على الورقة — لأنّ وسم img
     داخل حوارٍ لا يطبع إلّا الصفحةَ التي خلفه.
     وإن منع المتصفّحُ الطباعةَ من الإطار (سفاري/الهاتف) سقطنا إلى فتح تبويب. */
  function printCurrent(url, title) {
    var kind = fileKind(url);
    if (kind === 'pdf') {
      var frame = document.querySelector('#docPreviewBody iframe');
      try {
        if (frame && frame.contentWindow) {
          frame.contentWindow.focus();
          frame.contentWindow.print();
          return;
        }
      } catch (err) { /* أصلٌ مختلف أو منعٌ — السقوطُ أدناه */ }
      window.open(url, '_blank', 'noopener');
      return;
    }
    var w = window.open('', '_blank');
    if (!w) { window.open(url, '_blank', 'noopener'); return; }
    var doc = w.document;
    doc.write('<!DOCTYPE html><html lang="ar" dir="rtl"><head><meta charset="utf-8"><title>' +
      (title || 'مستند').replace(/[<>]/g, '') + '</title><style>' +
      '@page{margin:8mm}body{margin:0;display:flex;align-items:center;justify-content:center}' +
      'img{max-width:100%;max-height:100vh}</style></head><body><img alt=""></body></html>');
    doc.close();
    var img = doc.querySelector('img');
    img.onload = function () { w.focus(); w.print(); };
    img.src = url;
  }

  function open(url, title, opts) {
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

    opts = opts || {};
    var pagesEl = document.getElementById('docPreviewPages');
    if (pagesEl) {
      var bits = [];
      if (opts.pages) bits.push(opts.pages + ' ' + (opts.pages === 1 ? 'ورقة' : 'ورقات'));
      if (opts.lastBy) bits.push('آخرُ إلحاق: ' + opts.lastBy + (opts.lastAdded ? ' (+' + opts.lastAdded + ')' : ''));
      pagesEl.textContent = bits.join(' · ');
    }
    var reportEl = document.getElementById('docPreviewReport');
    if (reportEl) {
      reportEl.hidden = !opts.reportUrl;
      reportEl.href = opts.reportUrl || '#';
      reportEl.target = '_blank';
    }
    var printEl = document.getElementById('docPreviewPrint');
    if (printEl) printEl.onclick = function () { printCurrent(url, title); };
    modal.show();
  }

  // أي عنصر يحمل data-doc-preview + data-doc-url (+ data-doc-title) يفتح الحوار
  document.addEventListener('click', function (e) {
    var trigger = e.target.closest('[data-doc-preview]');
    if (!trigger) return;
    e.preventDefault();
    open(trigger.getAttribute('data-doc-url'), trigger.getAttribute('data-doc-title'), {
      pages: parseInt(trigger.getAttribute('data-doc-pages') || '', 10) || 0,
      lastBy: trigger.getAttribute('data-doc-last-by') || '',
      lastAdded: parseInt(trigger.getAttribute('data-doc-last-added') || '', 10) || 0,
      reportUrl: trigger.getAttribute('data-doc-report') || '',
    });
  });

  window.DocView = { fileKind: fileKind, buildNode: buildNode, open: open, print: printCurrent };
})();
