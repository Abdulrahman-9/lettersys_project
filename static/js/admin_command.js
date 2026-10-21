/* إدارة النظام — تصفيةٌ حيّةٌ للجداول، ودرجُ تفاصيل العقدة، وعدّاداتٌ متحرّكة.
   لا شيءَ هنا يكتب: كلُّ فعلٍ يمرّ من نماذج الصفحة القائمة. */
(function () {
  'use strict';
  var reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var params = new URLSearchParams(window.location.search);

  function norm(s) {
    return (s || '').toLowerCase()
      .replace(/[\u064B-\u0652\u0640]/g, '')
      .replace(/[أإآ]/g, 'ا').replace(/ى/g, 'ي').replace(/ة/g, 'ه')
      .replace(/\s+/g, ' ').trim();
  }

  document.querySelectorAll('[data-filter-for]').forEach(function (bar) {
    var table = document.getElementById(bar.getAttribute('data-filter-for'));
    if (!table) return;
    var q = bar.querySelector('[data-filter-q]');
    var status = bar.querySelector('[data-filter-status]');
    var count = bar.querySelector('[data-filter-count]');
    var rows = Array.prototype.slice.call(table.querySelectorAll('[data-filter-row]'));
    var empty = table.querySelector('[data-filter-empty]');
    rows.forEach(function (row) { row._s = norm(row.getAttribute('data-search')); });

    function apply() {
      var needle = norm(q.value);
      var want = status.value;
      var shown = 0;
      rows.forEach(function (row) {
        var ok = (!needle || row._s.indexOf(needle) !== -1) &&
          (!want || (' ' + row.getAttribute('data-status') + ' ').indexOf(' ' + want + ' ') !== -1);
        row.hidden = !ok;
        if (ok) shown += 1;
      });
      if (empty) empty.hidden = shown !== 0 || rows.length === 0;
      count.textContent = (needle || want) ? shown + ' من ' + rows.length : '';
    }

    if (params.get('q')) q.value = params.get('q');
    if (params.get('status') && status.querySelector('option[value="' + params.get('status') + '"]')) {
      status.value = params.get('status');
    }
    q.addEventListener('input', apply);
    status.addEventListener('change', apply);
    apply();
  });

  var target = window.location.hash && document.getElementById(window.location.hash.slice(1));
  if (target && target.matches('tr[id^="dep-row-"]')) {
    var details = target.querySelector('details');
    if (details) details.open = true;
  }

  var drawer = document.getElementById('adm-node-drawer');
  var urls = document.getElementById('adm-urls');
  if (drawer) {
    drawer.addEventListener('show.bs.offcanvas', function (event) {
      var node = event.relatedTarget;
      if (!node) return;
      var d = node.dataset;
      var slot = function (name) { return drawer.querySelector('[data-slot="' + name + '"]'); };
      slot('level').textContent = d.level;
      slot('name').textContent = d.name;
      slot('code').textContent = d.code;
      slot('parent').textContent = d.parent ? 'يتبع: ' + d.parent : 'مستوى أعلى في النطاق';
      slot('active-members').textContent = d.activeMembers;
      slot('members').textContent = d.members;
      slot('books').textContent = d.books;
      slot('overdue').textContent = d.overdue;
      slot('children').textContent = d.children;
      slot('status').textContent = d.active === '1' ? 'نشط' : 'معطّل';
      drawer.querySelector('[data-href="edit"]').href = '?tab=departments#dep-row-' + d.id;
      drawer.querySelector('[data-href="users"]').href = '?tab=users&q=' + encodeURIComponent(d.name);
      var overdue = drawer.querySelector('[data-href="overdue"]');
      overdue.hidden = d.overdue === '0';
      overdue.href = urls.getAttribute('data-reports') + '?dept=' + d.id + '&bucket=overdue';
    });
  }

  document.querySelectorAll('.adm-org-grid > li').forEach(function (li, i) {
    li.style.setProperty('--i', Math.min(i, 24));
  });

  if (!reduce) {
    document.querySelectorAll('.adm-kpis .fs-4').forEach(function (el) {
      var end = parseInt(el.textContent, 10);
      if (!(end > 0)) return;
      var start = performance.now();
      var dur = Math.min(900, 300 + end * 15);
      el.textContent = '0';
      (function tick(now) {
        var t = Math.min(1, (now - start) / dur);
        el.textContent = String(Math.round(end * (1 - Math.pow(1 - t, 3))));
        if (t < 1) requestAnimationFrame(tick);
      })(start);
    });
  }
})();
