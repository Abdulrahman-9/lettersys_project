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

  /* ── عارضُ الصور: تكبيرٌ وتدويرٌ وسحب (قرارُ المالك 2026‑09‑13) ──────────
     الصورةُ كانت ثابتةً بحجم الحوار فلا تُقرأ الترويسةُ الدقيقة، وكثيرٌ من المسح
     يأتي مقلوباً. العرضُ هنا بصريٌّ فقط — لا يُعدَّل الملفُّ على القرص. */
  var view = { zoom: 1, rot: 0, x: 0, y: 0, img: null, stage: null };

  function applyView() {
    if (!view.img) return;
    view.img.style.transform = 'translate(' + view.x + 'px,' + view.y + 'px) ' +
      'rotate(' + view.rot + 'deg) scale(' + view.zoom + ')';
    if (view.stage) view.stage.classList.toggle('is-grab', view.zoom > 1);
  }
  function resetView() { view.zoom = 1; view.rot = 0; view.x = 0; view.y = 0; applyView(); }
  function zoomBy(f) {
    view.zoom = Math.min(6, Math.max(0.4, Math.round(view.zoom * f * 100) / 100));
    if (view.zoom <= 1) { view.x = 0; view.y = 0; }
    applyView();
  }
  function rotate90() { view.rot = (view.rot + 90) % 360; view.x = 0; view.y = 0; applyView(); }

  function mountImage(node, body) {
    var stage = document.createElement('div');
    stage.className = 'doc-stage';
    stage.appendChild(node);
    body.appendChild(stage);
    view.img = node; view.stage = stage; resetView();
    stage.addEventListener('wheel', function (e) {
      if (!e.ctrlKey && Math.abs(e.deltaY) < 2) return;
      e.preventDefault(); zoomBy(e.deltaY < 0 ? 1.15 : 1 / 1.15);
    }, { passive: false });
    var drag = null;
    function pos(e) { var p = e.touches ? e.touches[0] : e; return { x: p.clientX, y: p.clientY }; }
    stage.addEventListener('mousedown', function (e) { if (view.zoom <= 1) return; drag = pos(e); stage.classList.add('is-grabbing'); e.preventDefault(); });
    stage.addEventListener('touchstart', function (e) { if (view.zoom <= 1) return; drag = pos(e); }, { passive: true });
    function move(e) {
      if (!drag) return;
      var p = pos(e);
      view.x += p.x - drag.x; view.y += p.y - drag.y; drag = p; applyView();
      if (e.cancelable) e.preventDefault();
    }
    stage.addEventListener('mousemove', move);
    stage.addEventListener('touchmove', move, { passive: false });
    function end() { drag = null; stage.classList.remove('is-grabbing'); }
    window.addEventListener('mouseup', end); stage.addEventListener('touchend', end);
    node.addEventListener('dblclick', function () { view.zoom > 1 ? resetView() : zoomBy(2); });
  }

  /* ── التنقّل بين مرفقات الكتاب داخل الحوار ── */
  var series = { items: [], index: 0, title: '' };
  function showSeries(i) {
    if (!series.items.length) return;
    series.index = (i + series.items.length) % series.items.length;
    var it = series.items[series.index];
    open(it.url, it.name || series.title, {
      pages: it.page_count, lastBy: it.last_by, lastAdded: it.last_added,
      reportUrl: series.reportUrl, _series: true,
    });
  }
  function bindTools() {
    var map = { docPreviewZoomIn: function () { zoomBy(1.25); }, docPreviewZoomOut: function () { zoomBy(1 / 1.25); },
                docPreviewRotate: rotate90, docPreviewReset: resetView,
                docPreviewPrev: function () { showSeries(series.index - 1); },
                docPreviewNext: function () { showSeries(series.index + 1); } };
    Object.keys(map).forEach(function (id) {
      var el = document.getElementById(id);
      if (el && !el.dataset.bound) { el.addEventListener('click', map[id]); el.dataset.bound = '1'; }
    });
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
      var node = buildNode({
        url: url,
        name: title,
        frameClass: 'doc-preview-frame',
        imgClass: 'doc-preview-img',
      });
      var isImage = node.tagName === 'IMG';
      if (isImage) { mountImage(node, body); } else { body.appendChild(node); }
      var tools = document.getElementById('docPreviewImgTools');
      if (tools) tools.className = isImage ? 'd-flex align-items-center gap-1' : 'd-none';
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

    if (!opts._series) { series.items = []; series.index = 0; }
    var navEl = document.getElementById('docPreviewNav');
    var counter = document.getElementById('docPreviewCounter');
    var many = series.items.length > 1;
    if (navEl) navEl.className = many ? 'd-flex align-items-center gap-1' : 'd-none';
    if (counter && many) counter.textContent = (series.index + 1) + ' من ' + series.items.length;
    bindTools();
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

  /** يفتح مرفقات كتابٍ سلسلةً قابلةً للتنقّل: ``openSeries(items, i, {reportUrl})``. */
  function openSeries(items, index, opts) {
    opts = opts || {};
    series.items = (items || []).filter(function (it) { return it && it.url; });
    series.reportUrl = opts.reportUrl || '';
    series.title = opts.title || '';
    if (!series.items.length) return;
    showSeries(index || 0);
  }

  window.DocView = { fileKind: fileKind, buildNode: buildNode, open: open,
                     print: printCurrent, openSeries: openSeries };
})();
