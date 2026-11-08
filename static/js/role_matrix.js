// مصفوفة الأدوار: النقرةُ تقلب الخليّة ولا تحفظ، والشريطُ يقول ما سيتغيّر وعلى كم موظّفاً،
// والحفظُ طلبٌ واحد. بلا هذا السكربت تبقى كلُّ خليّة زرَّ حفظٍ لنفسها.
(function () {
  'use strict';
  const form = document.getElementById('rmForm');
  if (!form) return;
  const bar = document.getElementById('rmBar');
  const barText = document.getElementById('rmBarText');
  const save = document.getElementById('rmSave');
  const dialog = document.getElementById('rmConfirm');
  const dialogText = document.getElementById('rmConfirmText');
  const roles = {};
  form.querySelectorAll('th[data-role]').forEach(function (th) {
    roles[th.dataset.role] = { label: th.dataset.label, n: Number(th.dataset.n) };
  });
  const pending = new Set();
  let leaving = false;
  let lastCell = null;
  let resetValue = '';

  // العددُ والمعدود بقاعدة العربيّة، كـ count_ar في الخادم.
  function countAr(n, one, two, few, many) {
    if (n === 1) return one;
    if (n === 2) return two;
    return n + ' ' + (n >= 3 && n <= 10 ? few : many);
  }
  const peopleAr = function (n) { return countAr(n, 'موظّف واحد', 'موظّفَين', 'موظّفين', 'موظّفاً'); };
  const isOn = function (cell) { return cell.getAttribute('aria-pressed') === 'true'; };

  function paint(cell) {
    const on = isOn(cell);
    cell.classList.toggle('on', on);
    cell.classList.toggle('pending', pending.has(cell));
    cell.querySelector('i').className = 'bi ' + (on ? 'bi-check-lg' : 'bi-dash');
  }

  function touchedRoles() {
    return Array.from(new Set(Array.from(pending, function (cell) { return cell.dataset.role; })));
  }

  function update() {
    bar.hidden = pending.size === 0;
    if (!pending.size) return;
    const touched = touchedRoles();
    const n = touched.reduce(function (sum, role) { return sum + roles[role].n; }, 0);
    let what;
    if (pending.size === 1) {
      const cell = pending.values().next().value;
      what = '«' + cell.closest('tr').dataset.label + '» لدور ' + roles[cell.dataset.role].label + ': '
        + (isOn(cell) ? 'يستطيع' : 'لا يستطيع') + '.';
    } else {
      what = countAr(pending.size, 'تغيير واحد', 'تغييران', 'تغييرات', 'تغييراً') + ' في '
        + countAr(touched.length, 'دور واحد', 'دورين', 'أدوار', 'دوراً') + '.';
    }
    const head = document.createElement('b');
    head.textContent = 'لم يُحفظ بعد:';
    const nobody = touched.length === 1 ? 'الدورَ' : touched.length === 2 ? 'هذين الدورين' : 'هذه الأدوارَ';
    const reach = n ? ' سيسري على ' + peopleAr(n) + '.' : ' ولا يحمل ' + nobody + ' أحدٌ الآن.';
    barText.replaceChildren(head, document.createTextNode(' ' + what + reach));
    save.textContent = n ? 'احفظ وطبّق على ' + peopleAr(n) : 'احفظ';
  }

  function flip(cell) {
    cell.setAttribute('aria-pressed', String(!isOn(cell)));
    if ((isOn(cell) ? '1' : '0') === cell.dataset.saved) pending.delete(cell);
    else pending.add(cell);
    lastCell = cell;
    paint(cell);
    update();
  }

  function discard() {
    pending.forEach(function (cell) {
      cell.setAttribute('aria-pressed', String(cell.dataset.saved === '1'));
    });
    const cells = Array.from(pending);
    pending.clear();
    cells.forEach(paint);
    update();
    if (lastCell) lastCell.focus();
  }

  function addHidden(name, value) {
    const input = document.createElement('input');
    input.type = 'hidden';
    input.name = name;
    input.value = value;
    form.appendChild(input);
  }

  form.addEventListener('click', function (event) {
    const cell = event.target.closest('button[name="change"]');
    if (!cell) return;
    event.preventDefault();
    flip(cell);
  });

  form.addEventListener('submit', function (event) {
    const by = event.submitter;
    if (by === save) {
      pending.forEach(function (cell) {
        const parts = cell.value.split(':');
        addHidden('change', parts[0] + ':' + parts[1] + ':' + (isOn(cell) ? '1' : '0'));
      });
      leaving = true;
      setTimeout(function () { save.disabled = true; }, 0);
      return;
    }
    if (!by || !by.dataset.rmReset) return;
    const all = by.value === 'all';
    if (!all && !pending.size) { leaving = true; return; }
    event.preventDefault();
    resetValue = by.value;
    const count = Number(by.dataset.rmCount);
    let text = all
      ? 'ستعود ' + countAr(count, 'خليّة واحدة معدَّلة', 'خليّتان معدَّلتان', 'خلايا معدَّلة', 'خليّة معدَّلة')
        + ' إلى المصفوفة المعتمدة، ' + (count === 1 ? 'ويُسجَّل ذلك' : 'وتُسجَّل كلٌّ منها') + ' في سجلّ الحركات.'
      : 'سيعود صفّ «' + by.dataset.rmReset + '» إلى المعتمد.';
    if (pending.size) {
      text += ' ويُتجاهل ' + countAr(pending.size, 'تغييرُك غير المحفوظ', 'تغييراك غير المحفوظَين',
        'تغييرات غير محفوظة', 'تغييراً غير محفوظ') + '.';
    }
    dialogText.textContent = text;
    dialog.showModal();
  });

  document.getElementById('rmDiscard').addEventListener('click', discard);
  document.getElementById('rmConfirmNo').addEventListener('click', function () { dialog.close(); });
  document.getElementById('rmConfirmYes').addEventListener('click', function () {
    leaving = true;
    addHidden('reset', resetValue);
    dialog.close();
    form.submit();
  });

  window.addEventListener('beforeunload', function (event) {
    if (pending.size && !leaving) {
      event.preventDefault();
      event.returnValue = '';
    }
  });
})();
