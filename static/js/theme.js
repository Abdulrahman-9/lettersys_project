/* LetterSys — زرُّ الوضع الفاتح/الداكن.
 *
 * الكاتبُ الوحيد لـ data-bs-theme هو سكربتُ الرأس في base.html (window.lxTheme)؛
 * هذا الملفّ يربط الأزرار [data-theme-toggle] به فقط، فلا يعمل إلّا في الصفحات
 * المنقولة إلى الهويّة الموحّدة (حيث يُعرَّف lxTheme).
 *
 * الانتقال: دائرةٌ تتّسع من الزرّ نفسه (View Transitions)، ويُلغى لمن طلب تقليل
 * الحركة أو في متصفّحٍ لا يدعمه — فيتبدّل الوضعُ فوراً بلا خسارة.
 */
(function () {
  'use strict';

  var api = window.lxTheme;
  if (!api) return;

  function reduceMotion() {
    return !!(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);
  }

  function sync() {
    var dark = api.get() === 'dark';
    var label = dark ? 'الوضع الفاتح' : 'الوضع الداكن';
    document.querySelectorAll('[data-theme-toggle]').forEach(function (button) {
      button.setAttribute('aria-pressed', dark ? 'true' : 'false');
      button.setAttribute('aria-label', label);
      button.title = label;
    });
  }

  function flip(button) {
    var next = api.get() === 'dark' ? 'light' : 'dark';
    var apply = function () { api.set(next); sync(); };

    if (reduceMotion() || typeof document.startViewTransition !== 'function') {
      apply();
      return;
    }

    var box = button.getBoundingClientRect();
    var x = box.left + box.width / 2;
    var y = box.top + box.height / 2;
    var radius = Math.hypot(Math.max(x, window.innerWidth - x), Math.max(y, window.innerHeight - y));
    var transition = document.startViewTransition(apply);
    transition.ready.then(function () {
      document.documentElement.animate(
        { clipPath: ['circle(0px at ' + x + 'px ' + y + 'px)', 'circle(' + radius + 'px at ' + x + 'px ' + y + 'px)'] },
        { duration: 560, easing: 'cubic-bezier(.2, .8, .2, 1)', pseudoElement: '::view-transition-new(root)' }
      );
    }).catch(function () { /* انتقالٌ أُلغي: الوضعُ نفسُه طُبّق في apply */ });
  }

  document.addEventListener('click', function (event) {
    var button = event.target.closest && event.target.closest('[data-theme-toggle]');
    if (button) flip(button);
  });
  document.addEventListener('lx-theme-change', sync);
  sync();
})();
