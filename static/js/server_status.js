/* «حالة الخادم»: تحديثٌ كلّ 30 ثانية، ونسخ، وحفظُ جهة التبليغ.
   البطاقاتُ تأتي مصيَّرةً من القالب نفسه (لا عرضَ مكرّراً هنا)، ومنطقةُ الحالة تعلن التغيّرَ وحده. */
(function () {
  'use strict';
  var page = document.querySelector('.ss-page[data-api-url]');
  if (!page) return;

  var REFRESH_MS = 30000;
  var apiUrl = page.getAttribute('data-api-url');
  var contactUrl = page.getAttribute('data-contact-url');
  var announceEl = page.querySelector('[data-announce]');
  var checkedEl = page.querySelector('[data-checked]');
  var headlineEl = page.querySelector('[data-summary-headline]');
  var summaryEl = page.querySelector('.ss-summary');
  var cardsEl = page.querySelector('[data-cards]');
  var firstRunEl = page.querySelector('.ss-firstrun');
  var lastChecked = Date.now();
  var busy = false;

  function announce(text) {
    if (!announceEl) return;
    announceEl.textContent = '';
    window.setTimeout(function () { announceEl.textContent = text; }, 60);
  }

  function unit(n, one, two, few, many) {
    if (n === 1) return one;
    if (n === 2) return two;
    return n + ' ' + (n % 100 >= 3 && n % 100 <= 10 ? few : many);
  }

  function showAgo() {
    if (!checkedEl || busy) return;
    var s = Math.round((Date.now() - lastChecked) / 1000);
    if (s < 5) { checkedEl.textContent = 'آخرُ فحص: الآن'; return; }
    checkedEl.textContent = s < 60
      ? 'آخرُ فحص: قبل ' + unit(s, 'ثانية', 'ثانيتين', 'ثوانٍ', 'ثانية')
      : 'آخرُ فحص: قبل ' + unit(Math.round(s / 60), 'دقيقة', 'دقيقتين', 'دقائق', 'دقيقة');
  }

  function refresh(manual) {
    if (busy) return Promise.resolve();
    busy = true;
    if (checkedEl) checkedEl.textContent = 'يُفحص الآن…';
    return fetch(apiUrl, { credentials: 'same-origin', cache: 'no-store', headers: { Accept: 'application/json' } })
      .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, d: d }; }); })
      .then(function (res) {
        if (!res.ok || !res.d.ok) throw new Error((res.d && res.d.message) || '');
        var d = res.d;
        if (cardsEl) cardsEl.innerHTML = d.cards_html;
        if (summaryEl) {
          summaryEl.setAttribute('data-state', d.summary.state);
          var ico = summaryEl.querySelector('.ss-summary-ico');
          if (ico) ico.setAttribute('data-state', d.summary.state);
        }
        var changed = headlineEl && headlineEl.textContent !== d.summary.headline;
        if (changed) headlineEl.textContent = d.summary.headline;
        if (firstRunEl && d.autostart_state === 'ok') {
          firstRunEl.hidden = true;
          announce('التشغيلُ مع الحاسوب مضبوط.');
        } else if (changed) {
          announce(d.summary.headline);
        } else if (manual) {
          announce('فُحص الآن: ' + d.summary.headline);
        }
        lastChecked = Date.now();
      })
      .catch(function () {
        if (checkedEl) checkedEl.textContent = 'تعذّر الفحص الآن — يُحاول بعد قليل';
      })
      .then(function () { busy = false; showAgo(); });
  }

  function copyText(text, onDone, onFail) {
    if (navigator.clipboard && window.isSecureContext) {
      navigator.clipboard.writeText(text).then(onDone, fallback);
    } else {
      fallback();
    }
    function fallback() {
      // على http:// يحجب المتصفّحُ واجهةَ الحافظة، فيُنسخ من حقلٍ مخفيّ
      var area = document.createElement('textarea');
      area.value = text;
      area.setAttribute('readonly', '');
      area.className = 'visually-hidden';
      document.body.appendChild(area);
      area.select();
      var ok = false;
      try { ok = document.execCommand('copy'); } catch (err) { ok = false; }
      area.remove();
      (ok ? onDone : onFail)();
    }
  }

  page.addEventListener('click', function (event) {
    var copyBtn = event.target.closest('[data-copy]');
    if (copyBtn) {
      var label = copyBtn.querySelector('[data-copy-label]');
      copyText(copyBtn.getAttribute('data-copy'), function () {
        copyBtn.classList.add('is-done');
        if (label) label.textContent = 'نُسخ ✓';
        announce('نُسخ.');
        window.setTimeout(function () {
          copyBtn.classList.remove('is-done');
          if (label) label.textContent = 'نسخ';
        }, 2000);
      }, function () {
        announce('تعذّر النسخ؛ حدّد النصّ وانسخه يدويّاً.');
      });
      return;
    }
    var refreshBtn = event.target.closest('[data-refresh]');
    if (refreshBtn) {
      var refreshLabel = refreshBtn.querySelector('[data-refresh-label]');
      refreshBtn.disabled = true;
      refreshBtn.setAttribute('aria-busy', 'true');
      if (refreshLabel) refreshLabel.textContent = 'يُفحص…';
      refresh(true).then(function () {
        refreshBtn.disabled = false;
        refreshBtn.removeAttribute('aria-busy');
        if (refreshLabel) refreshLabel.textContent = 'أعِد الفحص';
      });
    }
  });

  var form = page.querySelector('[data-contact-form]');
  if (form) {
    form.addEventListener('submit', function (event) {
      event.preventDefault();
      var button = form.querySelector('[data-contact-save]');
      var msg = form.querySelector('[data-contact-msg]');
      var token = form.querySelector('input[name="csrfmiddlewaretoken"]');
      var original = button.textContent;
      button.disabled = true;
      button.setAttribute('aria-busy', 'true');
      button.textContent = 'يُحفظ…';
      msg.textContent = '';
      fetch(contactUrl, {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json', Accept: 'application/json',
                   'X-CSRFToken': token ? token.value : '' },
        body: JSON.stringify({
          name: form.elements.namedItem('name').value,
          phone: form.elements.namedItem('phone').value
        })
      })
        .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, d: d }; }); })
        .then(function (res) {
          if (!res.ok || !res.d.ok) throw new Error(res.d && res.d.message);
          // حُفظ في القاعدة، وقد لا تُكتب نسخةُ الدليل على القرص: الخادمُ يقول ذلك فيُقال كما هو
          var partial = res.d.guide_written === false;
          msg.setAttribute('data-tone', partial ? 'warn' : 'ok');
          msg.textContent = partial ? res.d.message : 'حُفظ ✓';
        })
        .catch(function (err) {
          msg.setAttribute('data-tone', 'bad');
          msg.textContent = (err && err.message) || 'تعذّر الحفظ. حاول مرّةً أخرى.';
        })
        .then(function () {
          button.disabled = false;
          button.removeAttribute('aria-busy');
          button.textContent = original;
        });
    });
  }

  window.setInterval(function () { if (!document.hidden) refresh(false); }, REFRESH_MS);
  window.setInterval(showAgo, 5000);
  document.addEventListener('visibilitychange', function () {
    if (!document.hidden && Date.now() - lastChecked > REFRESH_MS) refresh(false);
  });
})();
