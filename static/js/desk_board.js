(function () {
  'use strict';

  var region = document.getElementById('recent-books');
  if (!region) return;

  var statusBox = document.getElementById('deskActionStatus');
  var csrfSource = document.querySelector('#deskCsrfForm [name=csrfmiddlewaretoken]');

  function csrf() {
    var cookie = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
    if (cookie) return decodeURIComponent(cookie[1]);
    return csrfSource ? csrfSource.value : '';
  }

  function show(message, ok) {
    if (window.ToastCenter && typeof window.ToastCenter.show === 'function') {
      window.ToastCenter.show(ok ? 'success' : 'error', message);
    }
    if (!statusBox) return;
    statusBox.hidden = false;
    statusBox.className = 'alert alert-' + (ok ? 'success' : 'danger') + ' py-2 mb-3';
    statusBox.textContent = message;
  }

  function busy(node, on) {
    if (!node) return;
    node.disabled = !!on;
    node.setAttribute('aria-busy', on ? 'true' : 'false');
  }

  function postJson(url, payload) {
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
        if (!res.ok || !data.success) {
          throw new Error(data.message || ('تعذّرت العملية (' + res.status + ')'));
        }
        return data;
      });
    });
  }

  function refresh() {
    window.location.hash = 'recent-books';
    window.location.reload();
  }

  region.addEventListener('click', function (event) {
    var button = event.target.closest('[data-desk-referral-act]');
    if (!button) return;
    event.preventDefault();
    busy(button, true);
    postJson(button.dataset.url, { act: button.dataset.deskReferralAct })
      .then(function (data) {
        show(data.message || 'تمّ تحديث الإحالة.', true);
        refresh();
      })
      .catch(function (err) {
        show(err.message, false);
      })
      .finally(function () {
        busy(button, false);
      });
  });

  region.addEventListener('submit', function (event) {
    var form = event.target.closest('[data-desk-followup-form]');
    if (!form) return;
    event.preventDefault();
    var submit = form.querySelector('button[type=submit]');
    var dueInput = form.querySelector('input[name=due_date]');
    if (!dueInput || !dueInput.value) {
      show('حدّد موعدَ الإنجاز أولاً.', false);
      return;
    }
    busy(submit, true);
    postJson(form.dataset.url, { act: 'activate', due_date: dueInput.value })
      .then(function (data) {
        show(data.message || 'تمّ تحديث موعد المتابعة.', true);
        refresh();
      })
      .catch(function (err) {
        show(err.message, false);
      })
      .finally(function () {
        busy(submit, false);
      });
  });
})();
