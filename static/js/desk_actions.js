/* Desk sheets: quick date ranges — one click fills both dates and applies; the pressed one clears them. */
(function () {
  'use strict';
  var form = document.querySelector('[data-desk-filter-form]');
  var box = form && form.querySelector('[data-desk-presets]');
  var from = form && form.elements.date_from;
  var to = form && form.elements.date_to;
  if (!box || !from || !to) return;

  function iso(d) {
    return d.getFullYear() + '-' + ('0' + (d.getMonth() + 1)).slice(-2) + '-' + ('0' + d.getDate()).slice(-2);
  }

  function range(kind) {
    var start = new Date();
    if (kind === 'week') start.setDate(start.getDate() - 6);
    if (kind === 'month') start.setDate(1);
    return [iso(start), iso(new Date())];
  }

  box.querySelectorAll('[data-desk-preset]').forEach(function (btn) {
    var r = range(btn.getAttribute('data-desk-preset'));
    var on = from.value === r[0] && to.value === r[1];
    btn.setAttribute('aria-pressed', String(on));
    btn.addEventListener('click', function () {
      from.value = on ? '' : r[0];
      to.value = on ? '' : r[1];
      btn.setAttribute('aria-pressed', String(!on));
      if (form.requestSubmit) form.requestSubmit(); else form.submit();
    });
  });
  box.hidden = false;
})();

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
