/* ============================================================
   number_hint.js — إظهار/إخفاء التنبيه المؤقّت لتركيبة رقم القيد.

   يظهر حتى يُغلقه المستخدم، ثم لا يعود. الإغلاق مربوط بمفتاح نسخة
   (data-hint-key)، فتغيير قواعد الترقيم لاحقاً يُعيد إظهاره للجميع.
   يفشل بصمت إن تعذّر الوصول إلى localStorage (وضع التصفّح الخاص).
   ============================================================ */
(function () {
  'use strict';

  var PREFIX = 'ls.hint.dismissed.';

  function dismissed(key) {
    try { return window.localStorage.getItem(PREFIX + key) === '1'; }
    catch (e) { return false; }
  }

  function remember(key) {
    try { window.localStorage.setItem(PREFIX + key, '1'); } catch (e) { /* لا بأس */ }
  }

  function init() {
    var boxes = document.querySelectorAll('.num-hint[data-hint-key]');
    Array.prototype.forEach.call(boxes, function (box) {
      var key = box.getAttribute('data-hint-key');
      if (dismissed(key)) { box.remove(); return; }

      box.classList.remove('d-none');
      var close = box.querySelector('.num-hint__close');
      if (close) {
        close.addEventListener('click', function () {
          remember(key);
          box.remove();
        });
      }
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
