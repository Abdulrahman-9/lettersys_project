/**
 * انضمامُ هذا الجهاز (اللوحةُ المعتمدة Join): الكود ⟵ الاسم ⟵ الفحص ⟵ جاهز.
 * الكودُ حقلٌ واحدٌ حقيقيّ (لصقٌ وإكمالٌ تلقائيّ وأرقامٌ عربيّة) فوق خمس خاناتٍ مرسومة.
 * الفحصُ يجري هنا في المتصفّح ويُبلَّغ الخادمُ بنتيجته؛ ولا نافذةَ أصليّة.
 */
(function () {
  'use strict';

  const root = document.getElementById('deviceJoin');
  const L = window.LxDevices;
  if (!root || !L) return;
  L.bindDeclare();
  if (root.dataset.registered === '1' || root.dataset.server !== '1') return;

  const cfg = root.dataset;
  const $ = (id) => document.getElementById(id);
  const el = (tag, cls, text) => {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined && text !== null) n.textContent = text;
    return n;
  };

  const panes = ['dvjPaneCode', 'dvjPaneName', 'dvjPaneChecks', 'dvjPaneDone'];
  let step = 1;
  let accepted = '';

  function go(n) {
    step = n;
    panes.forEach((id, i) => { $(id).hidden = i !== n - 1; });
    $('dvjStepLabel').textContent = `الخطوة ${n} من 4`;
    [...$('dvjSteps').children].forEach((li, i) => {
      if (i + 1 === n) li.setAttribute('aria-current', 'step'); else li.removeAttribute('aria-current');
      if (i + 1 < n) li.dataset.state = 'done'; else delete li.dataset.state;
    });
  }

  // ── ما نعرفه عن هذا الجهاز ──
  (function facts() {
    const ua = navigator.userAgent;
    const browser = /Edg\//.test(ua) ? 'Edge' : /Firefox\//.test(ua) ? 'Firefox' : /Chrome\//.test(ua) ? 'Chrome' : 'متصفّح';
    const system = /Windows/.test(ua) ? 'Windows' : /Android/.test(ua) ? 'Android' : /iPhone|iPad/.test(ua) ? 'iOS' : 'نظامٌ آخر';
    const zone = Intl.DateTimeFormat().resolvedOptions().timeZone || '';
    const chips = [
      [`${system} · ${browser}`, ''],
      [`الشاشة ${window.screen.width}×${window.screen.height}`, ''],
      [zone === 'Asia/Baghdad' ? 'بتوقيت بغداد ✓' : `المنطقة الزمنية: ${zone || 'غير معروفة'}`, zone === 'Asia/Baghdad' ? 'done' : 'wait'],
    ];
    if (cfg.approvedOrigin) {
      const okOrigin = cfg.approvedOrigin === window.location.origin;
      chips.push([okOrigin ? 'الرابط المعتمد ✓' : `الرابط المعتمد ${cfg.approvedOrigin}`, okOrigin ? 'done' : 'wait']);
    }
    $('dvjFacts').replaceChildren(...chips.map(([text, tone]) => {
      const p = el('span', 'dvs-pill', text);
      if (tone) p.dataset.tone = tone;
      return p;
    }));
  })();

  // ── الخطوة 1: الكود ──
  const otp = $('dvjOtp');
  const input = $('dvjCode');
  const cells = [...otp.querySelectorAll('.dvj-cell')];
  const connect = $('dvjConnect');

  function syncCells() {
    const v = L.digitsOnly(input.value).slice(0, 5);
    if (input.value !== v) input.value = v;
    const focused = document.activeElement === input;
    cells.forEach((c, i) => {
      c.textContent = v[i] || '';
      if (v[i]) c.dataset.filled = '1'; else delete c.dataset.filled;
      if (focused && i === Math.min(v.length, 4) && !input.disabled) c.dataset.active = '1'; else delete c.dataset.active;
    });
    connect.disabled = v.length !== 5 || input.disabled;
  }
  function codeError(msg) {
    $('dvjCodeErrText').textContent = msg || '';
    $('dvjCodeErrBox').hidden = !msg;
    if (msg) {
      otp.dataset.error = '1';
      input.setAttribute('aria-invalid', 'true');
    } else {
      delete otp.dataset.error;
      input.removeAttribute('aria-invalid');
    }
  }
  ['input', 'focus', 'blur'].forEach((ev) => input.addEventListener(ev, () => {
    if (ev === 'input') codeError('');
    syncCells();
  }));

  $('dvjPaneCode').addEventListener('submit', async (ev) => {
    ev.preventDefault();
    const code = L.digitsOnly(input.value);
    if (code.length !== 5) return;
    connect.disabled = true;
    try {
      const res = await L.api(cfg.checkUrl, { method: 'POST', body: { code } });
      if (res.ok) {
        accepted = code;
        codeError('');
        go(2);
        $('dvjName').focus();
        return;
      }
      failCode(res);
    } catch (_) {
      codeError('انقطع الاتّصال بالخادم. أعد المحاولة.');
    } finally {
      syncCells();
    }
  });

  function failCode(res) {
    const d = res.data || {};
    if (d.error === 'locked') {
      input.disabled = true;
      codeError(d.message);
      L.toast('danger', d.message, 'توقّف إدخال الكود', 9000);
    } else if (d.error === 'bad_code') {
      codeError(`${d.message}${typeof d.left === 'number' ? ` بقيت ${L.attempts(d.left)}.` : ''}`);
    } else {
      codeError(d.message || 'تعذّر التحقّق من الكود.');
    }
    input.value = '';
    // إعادةُ تشغيل الاهتزاز في كلّ خطأ
    otp.querySelector('.dvj-cells').style.animation = 'none';
    void otp.offsetWidth;
    otp.querySelector('.dvj-cells').style.animation = '';
    input.focus();
  }

  $('dvjRequest').addEventListener('click', async () => {
    const btn = $('dvjRequest');
    btn.disabled = true;
    const res = await L.api(cfg.requestUrl, { method: 'POST', body: {} }).catch(() => null);
    btn.disabled = false;
    if (!res || !res.ok) { L.toast('danger', (res && res.data.message) || 'تعذّر إرسال الطلب.'); return; }
    btn.hidden = true;
    $('dvjRequested').hidden = false;
    L.toast('info', 'ظهر جهازك للمسؤول الآن. اطلب منه الكود واكتبه هنا.', 'أُرسل طلبك');
  });

  // ── الخطوة 2: الاسم ──
  function nameError(msg) {
    $('dvjNameErrText').textContent = msg || '';
    $('dvjNameErrBox').hidden = !msg;
    if (msg) $('dvjName').setAttribute('aria-invalid', 'true'); else $('dvjName').removeAttribute('aria-invalid');
  }
  $('dvjBack').addEventListener('click', () => { go(1); input.focus(); syncCells(); });
  $('dvjName').addEventListener('input', () => nameError(''));

  let hasScanner = true;
  let joinedName = '';
  $('dvjPaneName').addEventListener('submit', async (ev) => {
    ev.preventDefault();
    const name = $('dvjName').value.trim();
    if (!name) { nameError('اكتب اسماً للجهاز.'); $('dvjName').focus(); return; }
    hasScanner = document.querySelector('input[name=has_scanner]:checked').value === '1';
    const btn = $('dvjFinish');
    btn.disabled = true;
    try {
      const res = await L.api(cfg.finishUrl, { method: 'POST', body: { code: accepted, name, has_scanner: hasScanner } });
      if (res.ok) {
        joinedName = res.data.name;
        L.toast('success', `«${joinedName}» مسجّلٌ الآن. نفحص ملحقاته.`, 'انضمّ الجهاز');
        go(3);
        runChecks();
        return;
      }
      const d = res.data || {};
      if (d.error === 'name_taken' || d.error === 'bad_name') { nameError(d.message); $('dvjName').focus(); return; }
      go(1);
      failCode(res);
    } catch (_) {
      nameError('انقطع الاتّصال بالخادم. أعد المحاولة.');
    } finally {
      btn.disabled = false;
    }
  });

  // ── الخطوة 3: الفحص ──
  const checks = [
    { key: 'server', title: 'الاتّصال بالخادم' },
    { key: 'origin', title: 'الرابط والشهادة' },
    { key: 'clock', title: 'ساعة الجهاز' },
    { key: 'agent', title: 'وكيل المسح' },
    { key: 'scanner', title: 'الماسح' },
  ];
  const glyph = { ok: '✓', warn: '!', busy: '…', wait: '', skip: '–' };

  function drawChecks() {
    $('dvjChecks').replaceChildren(...checks.map((c) => {
      const li = el('li', 'dvj-check');
      li.dataset.key = c.key;
      li.dataset.state = 'wait';
      const ico = el('span', 'dvj-check-ico', '');
      ico.setAttribute('aria-hidden', 'true');
      const text = el('div', 'dvj-check-text');
      text.append(el('b', '', c.title), el('span', '', 'بالانتظار'));
      li.append(ico, text);
      return li;
    }));
  }
  function mark(key, state, detail) {
    const li = $('dvjChecks').querySelector(`[data-key="${key}"]`);
    li.dataset.state = state;
    li.querySelector('.dvj-check-ico').textContent = glyph[state] || '';
    li.querySelector('.dvj-check-text span').textContent = detail;
  }

  async function runChecks() {
    drawChecks();
    $('dvjDone').disabled = true;
    $('dvjProgress').textContent = '';
    mark('server', 'busy', 'يُفحص الآن…');
    const skew = await L.clockSkew(cfg.meUrl).catch(() => null);
    mark('server', skew ? 'ok' : 'warn', skew ? `${window.location.hostname} يردّ خلال ${skew.rtt} ms` : 'لا يردّ الآن. تحقّق من الشبكة ثمّ أعد الفحص.');

    const approved = cfg.approvedOrigin;
    const origin = window.location.origin;
    if (window.location.protocol !== 'https:') {
      mark('origin', 'warn', approved ? `اتّصالٌ غير مشفّر. افتح النظام من ${approved}.` : 'اتّصالٌ غير مشفّر (http)، ولم يُضبط رابطٌ معتمد بعد.');
    } else if (!approved || approved === origin) {
      mark('origin', 'ok', `${origin} بشهادةٍ موثوقة على هذا الجهاز`);
    } else {
      mark('origin', 'warn', `تفتح من ${origin}، والمعتمد ${approved}. افتحه من المعتمد.`);
    }

    const zone = Intl.DateTimeFormat().resolvedOptions().timeZone || '';
    if (skew) {
      const secs = Math.round(Math.abs(skew.ms) / 1000);
      const okClock = secs < 60 && zone === 'Asia/Baghdad';
      mark('clock', okClock ? 'ok' : 'warn',
        `${zone === 'Asia/Baghdad' ? 'بتوقيت بغداد' : `المنطقة الزمنية ${zone || 'غير معروفة'} ليست بغداد`} · الفرق عن الخادم ${secs >= 120 ? `${Math.round(secs / 60)} دقائق` : `${secs} ثانية`}`);
    } else {
      mark('clock', 'skip', 'تُفحص حين يردّ الخادم.');
    }

    if (!hasScanner) {
      mark('agent', 'skip', 'غيرُ مطلوب: هذا الجهاز لا يمسح.');
      mark('scanner', 'skip', 'لا يمسح.');
      finish();
      return;
    }
    mark('agent', 'busy', 'نسأل وكيل المسح على هذا الجهاز…');
    const agent = await L.agentState(cfg.infoUrl);
    const report = { agent_version: agent.version || '', scanner_state: 'off', scanner_label: '' };
    if (agent.state !== 'ok') {
      mark('agent', 'warn', agent.state === 'untrusted'
        ? 'يعمل ولا يثق بهذا العنوان. شغّل LetterSys-Setup من المجلّد المشترك مرّةً ثمّ «أعد الفحص».'
        : 'غيرُ موجود. شغّل LetterSys-Setup من المجلّد المشترك مرّةً واحدة ثمّ «أعد الفحص».');
      mark('scanner', 'skip', 'يُفحص بعد الوكيل.');
    } else {
      const old = L.olderThan(agent.version, cfg.kitVersion);
      mark('agent', old ? 'warn' : 'ok', old
        ? `الإصدار ${agent.version} أقدم من نسخة الخادم ${cfg.kitVersion}. حدّثه من «هذا الجهاز».`
        : `الإصدار ${agent.version} يعمل${agent.naps2 ? '' : ' · برنامج المسح ناقص'}`);
      mark('scanner', 'busy', 'نبحث عن الماسح الموصول… قد يستغرق دقيقة.');
      try {
        const list = await window.ScanAgentClient.devices(agent.base, 70000);
        const names = (list.devices || []).map((d) => String(d.name || ''));
        if (names.length) {
          report.scanner_state = 'ok';
          report.scanner_label = names[0];
          mark('scanner', 'ok', names.length === 1 ? `${names[0]} اكتُشف` : `${names.length} ماسحات · أوّلها ${names[0]}`);
        } else {
          report.scanner_state = 'none';
          mark('scanner', 'warn', 'لم يُعثر على ماسح. شغّله وصِل كبله ثمّ «أعد الفحص».');
        }
      } catch (_) {
        report.scanner_state = 'error';
        mark('scanner', 'warn', 'لم يُكمل الوكيلُ البحث. أغلق برامج المسح الأخرى ثمّ «أعد الفحص».');
      }
    }
    L.api(cfg.reportUrl, { method: 'POST', body: report }).catch(() => null);
    finish();
  }

  function finish() {
    const warn = $('dvjChecks').querySelectorAll('[data-state="warn"]').length;
    $('dvjDone').disabled = false;
    $('dvjProgress').textContent = warn ? `${warn === 1 ? 'سطرٌ واحد يحتاج' : `${warn} أسطر تحتاج`} انتباهاً — يمكنك الإنهاء والعودة إليه من «هذا الجهاز».` : 'كلُّ شيءٍ سليم.';
  }

  $('dvjRecheck').addEventListener('click', runChecks);
  $('dvjDone').addEventListener('click', () => {
    $('dvjDoneTitle').textContent = `«${joinedName}» جاهز`;
    $('dvjDoneText').textContent = hasScanner
      ? 'مسجّلٌ باسمك، ويظهر الآن عند المسؤول في «الأجهزة المسجّلة». الماسحُ يُختار من صفحة الإدخال أو قسم الماسح.'
      : 'مسجّلٌ باسمك ويعمل بلا ماسح. يظهر الآن عند المسؤول في «الأجهزة المسجّلة».';
    go(4);
    $('dvjDoneTitle').focus();
  });

  go(1);
  syncCells();
})();
