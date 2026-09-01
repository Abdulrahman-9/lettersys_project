/*
 * دورةُ حياة الكتاب — الحواريّات الثلاث وأزرارُ صفوف الإحالة.
 *
 * الجداولُ الخمسةُ وخدماتُها بُنيت في البنود ②③④ ولم تكن هناك يدٌ تُحرّكها.
 * هذا الملفّ هو تلك اليد: تفريقٌ · تسجيلُ عهدة · قيدٌ عندنا · نقلاتُ الحالة.
 *
 * **لا منطقَ عملٍ هنا**: كلُّ تحقّقٍ وحراسةٍ في الخدمات على الخادم، وهذا
 * يُرسل ويعرض ما يعود. رسالةُ الخطأ تأتي من الخادم بنصّها العربيّ — لا
 * تُخترع هنا رسائلُ «نجاح» لا يعرفها.
 */
(function () {
  'use strict';

  var card = document.getElementById('lifecycleCard');
  if (!card) return;

  var bookId = card.dataset.bookId;
  if (!bookId) return;

  var targetsCache = null;

  // ── أدواتٌ صغيرة ──────────────────────────────────────────────────────
  function csrf() {
    var m = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
    if (m) return decodeURIComponent(m[1]);
    var input = document.querySelector('input[name=csrfmiddlewaretoken]');
    return input ? input.value : '';
  }

  function post(url, payload) {
    return fetch(url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': csrf(),
        'X-Requested-With': 'XMLHttpRequest'
      },
      body: JSON.stringify(payload || {})
    }).then(function (res) {
      return res.json().catch(function () { return {}; }).then(function (data) {
        // خطأٌ بلا رسالةٍ من الخادم أسوأُ من خطأٍ برسالة — لا نُخفيه
        if (!res.ok || !data.success) {
          throw new Error(data.message || ('تعذّرت العمليّة (' + res.status + ')'));
        }
        return data;
      });
    });
  }

  function targets() {
    if (targetsCache) return Promise.resolve(targetsCache);
    return fetch('/books/api/lifecycle/targets/', {
      headers: { 'X-Requested-With': 'XMLHttpRequest' }
    }).then(function (r) { return r.json(); }).then(function (data) {
      targetsCache = data;
      return data;
    });
  }

  function notify(message, ok) {
    var box = document.getElementById('lifecycleAlert');
    if (!box) return;
    box.className = 'alert alert-' + (ok ? 'success' : 'danger') + ' py-2 mb-3';
    box.textContent = message;
    box.hidden = false;
    if (ok) setTimeout(function () { window.location.reload(); }, 700);
  }

  function busy(button, on) {
    if (!button) return;
    button.disabled = on;
    button.dataset.label = button.dataset.label || button.innerHTML;
    button.innerHTML = on ? 'جارٍ…' : button.dataset.label;
  }

  function fill(select, items, valueKey, labelKey, placeholder) {
    select.innerHTML = '';
    if (placeholder) {
      var blank = document.createElement('option');
      blank.value = '';
      blank.textContent = placeholder;
      select.appendChild(blank);
    }
    items.forEach(function (item) {
      var option = document.createElement('option');
      option.value = item[valueKey];
      option.textContent = item[labelKey];
      select.appendChild(option);
    });
  }

  // ── حواريّةُ التفريق ──────────────────────────────────────────────────
  var distributeModal = document.getElementById('distributeModal');
  if (distributeModal) {
    distributeModal.addEventListener('show.bs.modal', function () {
      targets().then(function (data) {
        var list = document.getElementById('distTargets');
        list.innerHTML = '';
        data.departments.forEach(function (d) {
          var id = 'dist-dep-' + d.id;
          var wrap = document.createElement('div');
          wrap.className = 'form-check';
          wrap.innerHTML =
            '<input class="form-check-input" type="checkbox" value="dep:' + d.id +
            '" id="' + id + '">' +
            '<label class="form-check-label" for="' + id + '">' +
            d.name + (d.is_mine ? ' <span class="badge text-bg-light border">قسمي</span>' : '') +
            '</label>';
          list.appendChild(wrap);
        });
        fill(document.getElementById('distGroup'), data.groups, 'id', 'name',
             '— لا عنقود —');
        fill(document.getElementById('distAssignee'), data.people, 'id', 'name',
             '— بلا مكلَّف —');
      });
    });

    // عنقودٌ مختارٌ يُلغي الاختيار اليدويّ: هدفان متضاربان يُنتجان تفريقاً مزدوجاً
    var groupSelect = document.getElementById('distGroup');
    groupSelect.addEventListener('change', function () {
      var picked = !!groupSelect.value;
      document.getElementById('distTargets').classList.toggle('opacity-50', picked);
      document.querySelectorAll('#distTargets input').forEach(function (input) {
        input.disabled = picked;
        if (picked) input.checked = false;
      });
    });

    document.getElementById('distSubmit').addEventListener('click', function (event) {
      var button = event.currentTarget;
      var checked = Array.prototype.map.call(
        document.querySelectorAll('#distTargets input:checked'),
        function (input) { return input.value; });

      busy(button, true);
      post('/books/api/book/' + bookId + '/distribute/', {
        group: groupSelect.value || null,
        targets: checked,
        margin: document.getElementById('distMargin').value,
        // القصاصةُ اختياريّة: كتابٌ بلا مرفقٍ لا حقلَ له، فلا تُرسَل مفتاحاً فارغاً.
        margin_crop: (function () {
          var el = document.getElementById('distMarginCrop');
          if (!el || !el.value) return null;
          try { return JSON.parse(el.value); } catch (_) { return null; }
        })(),
        purpose: document.getElementById('distPurpose').value,
        due_date: document.getElementById('distDue').value,
        assignee: document.getElementById('distAssignee').value || null
      }).then(function (data) {
        notify(data.message, true);
      }).catch(function (err) {
        notify(err.message, false);
      }).finally(function () { busy(button, false); });
    });
  }

  // ── حواريّةُ العهدة ───────────────────────────────────────────────────
  var custodyModal = document.getElementById('custodyModal');
  if (custodyModal) {
    custodyModal.addEventListener('show.bs.modal', function () {
      targets().then(function (data) {
        fill(document.getElementById('custEvent'), data.events, 'id', 'label', null);
        fill(document.getElementById('custDepartment'), data.departments, 'id', 'name',
             '— لا قسم —');
        fill(document.getElementById('custUser'), data.people, 'id', 'name',
             '— لا موظّف —');
      });
    });

    document.getElementById('custSubmit').addEventListener('click', function (event) {
      var button = event.currentTarget;
      busy(button, true);
      post('/books/api/book/' + bookId + '/custody/', {
        event: document.getElementById('custEvent').value,
        to_department: document.getElementById('custDepartment').value || null,
        to_user: document.getElementById('custUser').value || null,
        to_name: document.getElementById('custName').value,
        signed_at: document.getElementById('custSignedAt').value,
        note: document.getElementById('custNote').value
      }).then(function (data) {
        notify(data.message, true);
      }).catch(function (err) {
        notify(err.message, false);
      }).finally(function () { busy(button, false); });
    });
  }

  // ── أزرارُ صفوف الإحالة ───────────────────────────────────────────────
  card.addEventListener('click', function (event) {
    var button = event.target.closest('[data-referral-act]');
    if (!button) return;
    event.preventDefault();

    var act = button.dataset.referralAct;
    var referralId = button.dataset.referralId;
    var note = '';
    if (act === 'done' || act === 'returned') {
      note = window.prompt(act === 'done' ? 'ملاحظةُ الإنجاز (اختياريّة):'
                                          : 'سببُ الإعادة (اختياريّ):') || '';
    }

    busy(button, true);
    post('/books/api/book/' + bookId + '/referral/' + referralId + '/act/',
         { act: act, note: note })
      .then(function () { notify('تمّ.', true); })
      .catch(function (err) { notify(err.message, false); })
      .finally(function () { busy(button, false); });
  });

  // ── «قيِّده عندنا» ────────────────────────────────────────────────────
  var registerBtn = document.getElementById('registerHereBtn');
  if (registerBtn) {
    registerBtn.addEventListener('click', function (event) {
      var button = event.currentTarget;
      busy(button, true);
      post('/books/api/book/' + bookId + '/register-here/', {})
        .then(function (data) { notify(data.message, true); })
        .catch(function (err) { notify(err.message, false); })
        .finally(function () { busy(button, false); });
    });
  }
})();
