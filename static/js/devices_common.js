/**
 * ما تتشاركه صفحتا «الشبكة والأجهزة» و«انضمام هذا الجهاز»: النداءُ بـCSRF، والتوست، والنسخ،
 * وحواريّةُ إعلان الخادم، وفحصُ وكيل المسح على هذا الجهاز. كلُّ نصٍّ جاء من الخادم أو الوكيل
 * يُكتب textContent وحدَه.
 */
(function () {
  'use strict';

  function csrfToken() {
    const field = document.querySelector('[name=csrfmiddlewaretoken]');
    if (field && field.value) return field.value;
    const m = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
    return m ? decodeURIComponent(m[1]) : '';
  }

  /** نداءُ JSON ⟵ ‎{ok, status, data}‎. لا يرمي إلّا على انقطاع الشبكة. */
  async function api(url, opts) {
    const options = opts || {};
    const headers = { Accept: 'application/json' };
    let body;
    if (options.body !== undefined) {
      headers['Content-Type'] = 'application/json';
      body = JSON.stringify(options.body);
    }
    if ((options.method || 'GET') !== 'GET') headers['X-CSRFToken'] = csrfToken();
    const r = await fetch(url, {
      method: options.method || 'GET', headers, body, credentials: 'same-origin', cache: 'no-store',
    });
    let data = {};
    try { data = await r.json(); } catch (_) { data = {}; }
    return { ok: r.ok && data.ok !== false, status: r.status, data };
  }

  function toast(type, message, title, delay) {
    if (window.ToastCenter && typeof window.ToastCenter.show === 'function') {
      const opts = {};
      if (title) opts.title = title;
      if (delay) opts.delay = delay;
      window.ToastCenter.show(type, message, opts);
    }
  }

  function actionToast(type, message, actions, title) {
    if (window.ToastCenter && typeof window.ToastCenter.action === 'function') {
      return window.ToastCenter.action(type, message, actions, title ? { title } : {});
    }
    toast(type, message, title);
    return null;
  }

  async function copy(text, label) {
    try {
      await navigator.clipboard.writeText(text);
      toast('success', `نُسخ ${label || 'النصّ'}.`);
    } catch (_) {
      toast('warning', `تعذّر النسخ تلقائيّاً. انسخ ${label || 'النصّ'} يدويّاً: ${text}`, null, 9000);
    }
  }

  /** الأرقامُ وحدها، والعربيّةُ والفارسيّةُ تُقبل. */
  function digitsOnly(raw) {
    return String(raw || '')
      .replace(/[٠-٩]/g, (d) => String(d.charCodeAt(0) - 0x0660))
      .replace(/[۰-۹]/g, (d) => String(d.charCodeAt(0) - 0x06F0))
      .replace(/\D/g, '');
  }

  function attempts(n) {
    if (n === 1) return 'محاولةٌ واحدة';
    if (n === 2) return 'محاولتان';
    return `${n} محاولات`;
  }

  /** حالُ وكيل المسح على هذا الجهاز ⟵ ‎{state: ok|untrusted|off|none, version, naps2, base}‎. */
  async function agentState(infoUrl) {
    const Agent = window.ScanAgentClient;
    if (!Agent) return { state: 'none' };
    let port = Agent.DEFAULT_PORT;
    try { port = Agent.port(await Agent.info(infoUrl)); } catch (_) { /* المنفذُ الافتراضيّ */ }
    const bases = Agent.bases(port);
    const health = await Agent.health(bases);
    if (!health) return { state: (await Agent.respondsButRejects(bases)) ? 'untrusted' : 'off' };
    const d = health.data || {};
    return { state: 'ok', base: health.base, version: String(d.version || ''), naps2: !!d.naps2_available,
             configError: d.config_error || '' };
  }

  function olderThan(version, kit) {
    const Agent = window.ScanAgentClient;
    return !!(Agent && version && kit && !Agent.versionAtLeast(version, kit));
  }

  /** فارقُ ساعة هذا الجهاز عن الخادم (من نقطة JSON لا من ترويسة Date) ⟵ ‎{ms, rtt}‎. */
  async function clockSkew(meUrl) {
    const t0 = Date.now();
    const res = await api(meUrl);
    const t1 = Date.now();
    if (!res.ok || !res.data.server_time) return null;
    const middle = t0 + (t1 - t0) / 2;
    return { ms: middle - res.data.server_time, rtt: t1 - t0, data: res.data };
  }

  /** حواريّةُ إعلان الخادم (للمدير العامّ؛ القالبُ لا يرسمها لغيره). */
  function bindDeclare() {
    const modalEl = document.getElementById('dvsDeclareModal');
    if (!modalEl || !window.bootstrap) return;
    const modal = window.bootstrap.Modal.getOrCreateInstance(modalEl);
    const form = document.getElementById('dvsDeclareForm');
    const codeInput = document.getElementById('dvsDeclareCode');
    const nameInput = document.getElementById('dvsDeclareName');
    const errBox = document.getElementById('dvsDeclareErr');
    const startBtn = document.getElementById('dvsDeclareStart');
    const submitBtn = document.getElementById('dvsDeclareSubmit');
    const showError = (msg) => { errBox.textContent = msg || ''; errBox.hidden = !msg; };

    document.querySelectorAll('[data-declare-open]').forEach((btn) => {
      btn.addEventListener('click', () => { showError(''); codeInput.value = ''; modal.show(); });
    });
    startBtn.addEventListener('click', async () => {
      startBtn.disabled = true;
      try {
        const res = await api(modalEl.dataset.startUrl, { method: 'POST', body: {} });
        if (!res.ok) { showError(res.data.message || 'تعذّر كتابة الكود على قرص الخادم.'); return; }
        toast('info', 'كُتب الكودُ في الملفّ على قرص الخادم. افتحه واكتب الأرقام الثمانية.', 'كودُ الخادم', 8000);
        codeInput.focus();
      } catch (_) {
        showError('انقطع الاتّصال بالخادم. أعد المحاولة.');
      } finally {
        startBtn.disabled = false;
      }
    });
    form.addEventListener('submit', async (ev) => {
      ev.preventDefault();
      const code = digitsOnly(codeInput.value);
      if (code.length !== 8) { showError('الكودُ ثمانيةُ أرقام.'); codeInput.focus(); return; }
      submitBtn.disabled = true;
      try {
        const res = await api(modalEl.dataset.finishUrl, { method: 'POST', body: { code, name: nameInput.value } });
        if (!res.ok) {
          const left = res.data.left;
          showError((res.data.message || 'تعذّر الإعلان.') + (typeof left === 'number' && left > 0 ? ` بقيت ${attempts(left)}.` : ''));
          return;
        }
        modal.hide();
        toast('success', `صار «${res.data.name}» جهازَ الخادم. تصدر الأكوادُ وتصل الطلباتُ إليه الآن.`, 'أُعلن الخادم');
        setTimeout(() => window.location.reload(), 900);
      } catch (_) {
        showError('انقطع الاتّصال بالخادم. أعد المحاولة.');
      } finally {
        submitBtn.disabled = false;
      }
    });
  }

  function bindCopy(root) {
    (root || document).querySelectorAll('[data-copy]').forEach((btn) => {
      btn.addEventListener('click', () => copy(btn.dataset.copy, btn.dataset.copyLabel));
    });
  }

  window.LxDevices = Object.freeze({ api, toast, actionToast, copy, digitsOnly, attempts, agentState, olderThan,
                                     clockSkew, bindDeclare, bindCopy });
})();
