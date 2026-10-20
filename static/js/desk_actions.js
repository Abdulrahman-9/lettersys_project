/* Desk sheets: never print a sheet that no longer matches the filter on screen. */
(function () {
  'use strict';
  var form = document.querySelector('[data-desk-filter-form]');
  var bar = document.querySelector('[data-desk-output]');
  if (!form || !bar) return;

  var printBtn = bar.querySelector('[data-desk-print]');
  var fresh = bar.querySelector('[data-desk-fresh]');
  var stale = bar.querySelector('[data-desk-stale]');

  function snapshot() {
    return new URLSearchParams(new FormData(form)).toString();
  }

  var applied = snapshot();

  function sync() {
    var changed = snapshot() !== applied;
    bar.classList.toggle('is-stale', changed);
    fresh.hidden = changed;
    stale.hidden = !changed;
    printBtn.disabled = changed;
    printBtn.title = changed ? 'طبّق التصفية أولاً' : '';
  }

  form.addEventListener('input', sync);
  form.addEventListener('change', sync);
})();
