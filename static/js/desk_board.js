(function () {
  'use strict';

  var oldQueue = /^#q-([a-z_]+)$/.exec(window.location.hash);
  if (oldQueue && !new URLSearchParams(window.location.search).has('queue')) {
    var queueLink = document.querySelector('[data-desk-queue="' + oldQueue[1] + '"]');
    if (queueLink) {
      window.location.replace(queueLink.href);
      return;
    }
  }

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
    var spinner = node.querySelector('[data-desk-spinner]');
    if (on && !spinner) {
      spinner = document.createElement('span');
      spinner.className = 'spinner-border spinner-border-sm';
      spinner.dataset.deskSpinner = '1';
      spinner.setAttribute('aria-hidden', 'true');
      node.prepend(spinner);
    } else if (!on && spinner) {
      spinner.remove();
    }
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
    var target = button.dataset.deskTarget || 'الجهة المستلمة';
    button.disabled = true;
    var question = {
      title: 'تأكيد وصول الإحالة إلى «' + target + '»',
      message: 'ستتغيّر حالة الإحالة إلى «مستلَم». هذا لا يسجّل توقيعاً ورقياً أو انتقال عهدة.',
      okText: 'تأكيد الوصول',
      danger: false
    };
    var confirmed = typeof window.confirmDelete === 'function'
      ? window.confirmDelete(question)
      : Promise.resolve(window.confirm(question.title + '\n' + question.message));
    confirmed.then(function (answer) {
      if (!answer) return null;
      busy(button, true);
      return postJson(button.dataset.url, { act: button.dataset.deskReferralAct });
    })
      .then(function (data) {
        if (!data) return;
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
