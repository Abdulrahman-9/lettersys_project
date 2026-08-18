/* ============================================================
   تحجيم أعمدة جدول الكتب يدوياً + حفظ الإعدادات (localStorage)
   - سحب حدّ الترويسة يغيّر عرض العمود (RTL-aware).
   - نقر مزدوج على المقبض يُعيد العمود لعرضه الافتراضي.
   - resetBookColumns() يُعيد الكل.
   - الإعدادات تبقى محفوظة على المتصفّح حتى لو خرج المستخدم، إلى أن يغيّرها بنفسه.
   ملاحظة: الترويسة تبقى ثابتة عبر تحديث الـAJAX (يُحدَّث الجسم فقط)، فالمقابض
   والعروض المحفوظة لا تُفقَد إلا عند إعادة تحميل الصفحة كاملةً (حينها تُستعاد).
   ============================================================ */
(function () {
  'use strict';

  var STORAGE_KEY = 'lettersys.book.colWidths.v1';
  var TABLE_ID = 'bookUnifiedTable';
  // أعمدة قابلة للتحجيم (نستثني الاختيار والإجراءات — عرضهما ثابت وظيفيّ)
  var RESIZABLE = [
    'col-our-number', 'col-date', 'col-sender-number',
    'col-sender-date', 'col-title', 'col-entity', 'col-status'
  ];
  // حدّ أدنى لكل عمود — الأرقام والتواريخ لا تُضغط لدرجة الإخفاء
  var MIN = {
    'default': 60,
    'col-our-number': 82, 'col-sender-number': 92,
    'col-date': 78, 'col-sender-date': 78, 'col-status': 96
  };

  function colKey(th) {
    var cls = th.className.split(/\s+/);
    for (var i = 0; i < cls.length; i++) {
      if (cls[i].indexOf('col-') === 0) return cls[i];
    }
    return null;
  }
  function loadWidths() {
    try { return JSON.parse(localStorage.getItem(STORAGE_KEY)) || {}; }
    catch (e) { return {}; }
  }
  function saveWidths(w) {
    try { localStorage.setItem(STORAGE_KEY, JSON.stringify(w)); } catch (e) {}
  }
  function isRtl() {
    var d = document.documentElement.getAttribute('dir') ||
            document.body.getAttribute('dir') || 'rtl';
    return d === 'rtl';
  }

  function applyWidths() {
    var table = document.getElementById(TABLE_ID);
    if (!table) return;
    var widths = loadWidths();
    var ths = table.querySelectorAll('thead th');
    for (var i = 0; i < ths.length; i++) {
      var key = colKey(ths[i]);
      if (key && widths[key]) ths[i].style.width = widths[key] + 'px';
    }
  }

  function attachResizer(th, key) {
    if (th.querySelector('.col-resizer')) return;   // مرّة واحدة
    var handle = document.createElement('span');
    handle.className = 'col-resizer';
    handle.title = 'اسحب لتغيير عرض العمود — نقر مزدوج لإعادة الضبط';
    th.appendChild(handle);

    var startX = 0, startW = 0, dragging = false;
    var min = MIN[key] || MIN['default'];

    function onMove(ev) {
      if (!dragging) return;
      var x = (ev.touches ? ev.touches[0].clientX : ev.clientX);
      var delta = isRtl() ? (startX - x) : (x - startX);
      th.style.width = Math.max(min, startW + delta) + 'px';
    }
    function onUp() {
      if (!dragging) return;
      dragging = false;
      document.body.classList.remove('col-resizing');
      document.removeEventListener('mousemove', onMove);
      document.removeEventListener('mouseup', onUp);
      document.removeEventListener('touchmove', onMove);
      document.removeEventListener('touchend', onUp);
      var widths = loadWidths();
      widths[key] = th.offsetWidth;
      saveWidths(widths);
    }
    function onDown(ev) {
      ev.preventDefault();
      ev.stopPropagation();   // لا يُفعّل فرز العمود
      dragging = true;
      startX = (ev.touches ? ev.touches[0].clientX : ev.clientX);
      startW = th.offsetWidth;
      document.body.classList.add('col-resizing');
      document.addEventListener('mousemove', onMove);
      document.addEventListener('mouseup', onUp);
      document.addEventListener('touchmove', onMove, { passive: false });
      document.addEventListener('touchend', onUp);
    }
    handle.addEventListener('mousedown', onDown);
    handle.addEventListener('touchstart', onDown, { passive: false });
    handle.addEventListener('dblclick', function (ev) {
      ev.preventDefault();
      ev.stopPropagation();
      th.style.width = '';                 // يعود للعرض الافتراضي من CSS
      var widths = loadWidths();
      delete widths[key];
      saveWidths(widths);
    });
  }

  function initResizers() {
    var table = document.getElementById(TABLE_ID);
    if (!table) return;
    var ths = table.querySelectorAll('thead th');
    for (var i = 0; i < ths.length; i++) {
      var key = colKey(ths[i]);
      if (key && RESIZABLE.indexOf(key) !== -1) attachResizer(ths[i], key);
    }
  }

  function resetAll() {
    saveWidths({});
    var table = document.getElementById(TABLE_ID);
    if (!table) return;
    var ths = table.querySelectorAll('thead th');
    for (var i = 0; i < ths.length; i++) ths[i].style.width = '';
  }
  window.resetBookColumns = resetAll;

  function boot() { applyWidths(); initResizers(); }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }
})();
