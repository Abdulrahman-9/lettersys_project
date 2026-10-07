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

  // المنطقةُ الثابتة التي تُعاد رسمُ محتوياتها بعد الفعل (البطاقةُ تُستبدل، هي لا)
  var region = document.getElementById('lifecycleRegion') || card.parentNode;

  var targetsCache = null;

  // ── أدواتٌ صغيرة ──────────────────────────────────────────────────────
  function csrf() {
    var m = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
    if (m) return decodeURIComponent(m[1]);
    var input = document.querySelector('input[name=csrfmiddlewaretoken]');
    return input ? input.value : '';
  }

  // ── حواريّةُ السؤال الواحدة (تدقيقُ نيلسن B#4/B#6) ─────────────────────────
  // بدل prompt()/confirm() الأصليّتين: عنوانٌ يسمّي الوحدةَ أو الدفتر، وملاحظةٌ
  // اختياريّةٌ حقلٌ فيها، وزرّان مسمّيان. تُعيد Promise بالملاحظة (نصّاً، وقد يكون
  // فارغاً) أو null عند الإلغاء — فالإلغاءُ تراجعٌ لا «ملاحظةٌ فارغة».
  function ask(opts) {
    if (!(window.bootstrap && window.bootstrap.Modal)) {
      // احتياطٌ بلا Bootstrap: السلوكُ القديم نفسُه
      if (opts.noteLabel) return Promise.resolve(window.prompt(opts.title + ' — ' + opts.noteLabel));
      return Promise.resolve(window.confirm(opts.title) ? '' : null);
    }
    var el = document.createElement('div');
    el.className = 'modal fade';
    el.tabIndex = -1;
    el.setAttribute('aria-labelledby', 'lcAskTitle');
    el.innerHTML =
      '<div class="modal-dialog modal-dialog-centered"><div class="modal-content">' +
      '<div class="modal-header"><h2 class="modal-title fs-6 fw-bold" id="lcAskTitle"></h2>' +
      '<button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="إغلاق"></button></div>' +
      '<div class="modal-body"><p class="mb-2 lc-ask-body"></p>' +
      '<label class="form-label small lc-ask-label" for="lcAskNote"></label>' +
      '<textarea class="form-control form-control-sm" id="lcAskNote" rows="2" maxlength="500"></textarea></div>' +
      '<div class="modal-footer"><button type="button" class="btn btn-sm btn-outline-secondary" data-bs-dismiss="modal">إلغاء</button>' +
      '<button type="button" class="btn btn-sm lc-ask-ok"></button></div></div></div>';
    el.querySelector('#lcAskTitle').textContent = opts.title;
    var body = el.querySelector('.lc-ask-body');
    if (opts.body) body.textContent = opts.body; else body.remove();
    var label = el.querySelector('.lc-ask-label');
    var note = el.querySelector('#lcAskNote');
    if (opts.noteLabel) { label.textContent = opts.noteLabel; } else { label.remove(); note.remove(); }
    var ok = el.querySelector('.lc-ask-ok');
    ok.textContent = opts.okText || 'تأكيد';
    ok.classList.add(opts.danger ? 'btn-danger' : 'btn-primary');
    document.body.appendChild(el);
    var modal = new window.bootstrap.Modal(el);
    return new Promise(function (resolve) {
      var answer = null;
      ok.addEventListener('click', function () { answer = note.isConnected ? note.value.trim() : ''; modal.hide(); });
      el.addEventListener('shown.bs.modal', function () { (note.isConnected ? note : ok).focus(); });
      el.addEventListener('hidden.bs.modal', function () { el.remove(); resolve(answer); });
      modal.show();
    });
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

  // مفتاحُ الرسالة التي تعبر إعادةَ التحميل — انظر `notify`.
  var PENDING_TOAST = 'lifecycleToast';

  function toast(message, ok) {
    // **لهجةٌ واحدةٌ للإشعار**: التطبيقُ له مركزٌ موحّد (`ToastCenter` في
    // `static/app.js`، مُحمَّلٌ في كلّ صفحة) يستعمله البحثُ الموحّد ومدير
    // المستندات. وكانت حواريّاتُ دورة الحياة وحدَها تكتب تنبيهاً مضمَّناً —
    // لهجةً خامسةً لشيءٍ واحد. والمضمَّنُ يبقى **سقوطاً احتياطيّاً** لا بديلاً.
    if (window.ToastCenter && typeof window.ToastCenter.show === 'function') {
      window.ToastCenter.show(ok ? 'success' : 'error', message);
      return true;
    }
    var box = document.getElementById('lifecycleAlert');
    if (!box) return false;
    box.className = 'alert alert-' + (ok ? 'success' : 'danger') + ' py-2 mb-3';
    box.textContent = message;
    box.hidden = false;
    return true;
  }

  // ── إعادةُ الرسم في المكان (ح1 في تدقيق الانتقالات) ─────────────────
  // كانت كلُّ نقلةٍ تُعيد تحميلَ الصفحة كاملةً فتفقد التمريرَ وتُبطئ. الآن تُجلب
  // الصفحةُ نفسُها في الخلفيّة وتُستبدل **المناطقُ الموسومة** `data-lifecycle-refresh`
  // فقط (لوحةُ التسيير، شارةُ الحالة، سجلُّ المتابعة) — الخادمُ يبقى مصدرَ الحقيقة
  // بلا مسارٍ جديدٍ ولا قالبٍ مكرَّر. وإن أخفق الجلبُ سقطنا إلى إعادة التحميل.
  function closeOpenModal() {
    var open = document.querySelector('.modal.show');
    if (!open || !window.bootstrap || !window.bootstrap.Modal) return;
    var inst = window.bootstrap.Modal.getInstance(open);
    if (inst) inst.hide();
  }

  function refreshInPlace() {
    return fetch(window.location.href, {
      headers: { 'X-Requested-With': 'XMLHttpRequest' },
      credentials: 'same-origin',
      cache: 'no-store'
    }).then(function (res) {
      if (!res.ok) throw new Error('refresh ' + res.status);
      return res.text();
    }).then(function (html) {
      var fresh = new DOMParser().parseFromString(html, 'text/html');
      var swapped = 0;
      document.querySelectorAll('[data-lifecycle-refresh]').forEach(function (el) {
        if (!el.id) return;
        var next = fresh.getElementById(el.id);
        if (next) { el.innerHTML = next.innerHTML; swapped++; }
      });
      if (!swapped) throw new Error('nothing to swap');
      // البطاقةُ الجديدة تحمل المعرّفَ نفسَه؛ المعالجُ مفوَّضٌ على المنطقة فلا يُعاد ربطُه
      card = document.getElementById('lifecycleCard') || card;
    });
  }

  function notify(message, ok) {
    if (!ok) { toast(message, false); return; }
    closeOpenModal();
    refreshInPlace().then(function () {
      toast(message, true);
    }).catch(function () {
      // سقوطٌ احتياطيّ: الرسالةُ تعبر إعادةَ التحميل
      try { window.sessionStorage.setItem(PENDING_TOAST, message); } catch (e) { toast(message, true); }
      setTimeout(function () { window.location.reload(); }, 250);
    });
  }

  (function showWhatSurvivedTheReload() {
    try {
      var pending = window.sessionStorage.getItem(PENDING_TOAST);
      if (!pending) return;
      window.sessionStorage.removeItem(PENDING_TOAST);
      toast(pending, true);
    } catch (e) { /* تخزينٌ محجوب — والأثرُ ظاهرٌ في الصفحة على أيّ حال */ }
  })();

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
             '— بلا قائمة —');
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

    // «للتنفيذ» بلا موعدٍ لا يتأخّر أبداً فلا يُطارَد — الموعدُ مطلوبٌ معه، كما
    // يرفضه «فعِّل متابعة» (تدقيقُ نيلسن B#5).
    var purposeSelect = document.getElementById('distPurpose');
    var dueInput = document.getElementById('distDue');
    function syncDueRequired() {
      var needed = purposeSelect.value === 'action';
      dueInput.required = needed;
      dueInput.setAttribute('aria-required', needed ? 'true' : 'false');
      var mark = document.getElementById('distDueRequired');
      if (mark) mark.hidden = !needed;
    }
    purposeSelect.addEventListener('change', syncDueRequired);
    syncDueRequired();

    document.getElementById('distSubmit').addEventListener('click', function (event) {
      var button = event.currentTarget;
      if (purposeSelect.value === 'action' && !dueInput.value) {
        dueInput.classList.add('is-invalid');
        dueInput.focus();
        notify('«للتنفيذ» يحتاج موعدَ إنجاز — حدّده، أو اختر «للعلم».', false);
        return;
      }
      dueInput.classList.remove('is-invalid');
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
        syncHolder();
      });
    });

    // الحاملُ واحدٌ من ثلاثة («أو»): ملءُ أحدها يعطّل الآخرَين، كالعنقود مع الاختيار
    // اليدويّ في التفريق (تدقيقُ نيلسن B#9).
    var holderFields = ['custDepartment', 'custUser', 'custName'].map(function (id) {
      return document.getElementById(id);
    }).filter(Boolean);
    function syncHolder() {
      var filled = holderFields.filter(function (f) { return (f.value || '').trim(); })[0];
      holderFields.forEach(function (f) { f.disabled = !!filled && f !== filled; });
    }
    holderFields.forEach(function (f) {
      f.addEventListener('input', syncHolder);
      f.addEventListener('change', syncHolder);
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

  // ── أزرارُ صفوف الإحالة (تفويضٌ على المنطقة الثابتة لا البطاقة المُستبدَلة) ──
  region.addEventListener('click', function (event) {
    var button = event.target.closest('[data-referral-act]');
    if (!button) return;
    event.preventDefault();

    var act = button.dataset.referralAct;
    var referralId = button.dataset.referralId;
    var unit = button.dataset.referralTarget || 'الوحدة';
    // «أُنجز/أُعيد» يُقفلان الالتزامَ ولا فعلَ يعيد فتحه — فلا يمضيان بنقرةٍ واحدة.
    var asked = Promise.resolve('');
    if (act === 'done') {
      asked = ask({ title: 'أُنجز ما وُجّه إلى «' + unit + '»؟',
                    body: 'يُقفَل التزامُ الوحدة ولا يُعاد فتحُه من هنا.',
                    noteLabel: 'ملاحظةُ الإنجاز (اختياريّة)', okText: 'أُنجز' });
    } else if (act === 'returned') {
      asked = ask({ title: 'أُعيد إلى «' + unit + '» بلا إنجاز؟',
                    body: 'يُقفَل التزامُ الوحدة ولا يُعاد فتحُه من هنا.',
                    noteLabel: 'سببُ الإعادة (اختياريّ)', okText: 'أُعيد', danger: true });
    }

    asked.then(function (note) {
      if (note === null) return;
      busy(button, true);
      post('/books/api/book/' + bookId + '/referral/' + referralId + '/act/',
           { act: act, note: note })
        .then(function () { notify('تمّ.', true); })
        .catch(function (err) { notify(err.message, false); })
        .finally(function () { busy(button, false); });
    });
  });

  // ── فعِّل متابعة (§5.2): زرُّ الصفّ يفتح الحواريّةَ الصغيرة، وإرسالُها act=activate ──
  region.addEventListener('click', function (event) {
    var button = event.target.closest('[data-followup-activate]');
    if (!button) return;
    event.preventDefault();
    document.getElementById('followupReferralId').value = button.dataset.followupActivate;
    document.getElementById('followupTarget').textContent = button.dataset.followupTarget || '';
    document.getElementById('followupDue').value = '';
    document.getElementById('followupMargin').value = '';
    var modalEl = document.getElementById('followupModal');
    if (modalEl && window.bootstrap && window.bootstrap.Modal) {
      window.bootstrap.Modal.getOrCreateInstance(modalEl).show();
    }
  });
  var followupSubmit = document.getElementById('followupSubmit');
  if (followupSubmit) {
    followupSubmit.addEventListener('click', function (event) {
      var button = event.currentTarget;
      var referralId = document.getElementById('followupReferralId').value;
      var due = document.getElementById('followupDue').value;
      if (!due) { toast('حدّد موعدَ الإنجاز.', false); return; }
      busy(button, true);
      post('/books/api/book/' + bookId + '/referral/' + referralId + '/act/',
           { act: 'activate', due_date: due, margin: document.getElementById('followupMargin').value })
        .then(function () { notify('فُعِّلت المتابعة.', true); })
        .catch(function (err) { notify(err.message, false); })
        .finally(function () { busy(button, false); });
    });
  }

  // (أُزيلت معالجاتُ «تمام الأرشفة» و«فتح المؤرشَف» — قراراتُ الدورة §6)

  // ── «قيِّده عندنا» ────────────────────────────────────────────────────
  // **تفويضٌ على المستند لا ربطٌ بالزرّ**: الزرُّ يسكن قائمةَ «⋯» في الترويسة
  // (`bookActions`) التي يستبدلها `refreshInPlace` بعد كلّ فعل — فالربطُ المباشر
  // كان يموت بعد أوّل تفريقٍ أو عهدة. والضغطةُ تستهلك رقماً حقيقيّاً من عدّاد
  // القسم لا يُستردّ، فلا تمضي بلا تأكيدٍ يسمّي الدفتر.
  document.addEventListener('click', function (event) {
    var button = event.target.closest('#registerHereBtn');
    if (!button) return;
    event.preventDefault();
    var ledger = button.dataset.ledger || 'قسمي';
    ask({ title: 'قيّده في دفتر «' + ledger + '»؟',
          body: 'سيُمنح الكتابُ رقمَ واردٍ جديداً من هذا الدفتر — والرقمُ لا يُستردّ.',
          okText: 'قيّده' }).then(function (answer) {
      if (answer === null) return;
      busy(button, true);
      post('/books/api/book/' + bookId + '/register-here/', {})
        .then(function (data) { notify(data.message, true); })
        .catch(function (err) { notify(err.message, false); })
        .finally(function () { busy(button, false); });
    });
  });
})();
