/**
 * «الشبكة والأجهزة» (التصميمُ المعتمد 2026-11-18).
 *  - المديرُ العامّ: السجلُّ والطلباتُ تُرسم من بيانات الخادم وتتحدّث كلَّ 10 ث ما دامت الصفحةُ ظاهرة؛
 *    والكودُ يُصدر ويُراقَب كلَّ ثانيتين حتّى يُستعمل أو ينتهي. الأفعالُ من جهاز الخادم وحده (الخادمُ يرفض غيرَه).
 *  - غيرُه: «هذا الجهاز» — الخادمُ والرابطُ والساعةُ ووكيلُ المسح تُفحص هنا في المتصفّح.
 * كلُّ نصٍّ جاء من الخادم أو الوكيل يُكتب textContent وحدَه، ولا نافذةَ أصليّة (alert/confirm).
 */
(function () {
  'use strict';

  const root = document.getElementById('devicesPage');
  const L = window.LxDevices;
  if (!root || !L) return;

  const cfg = root.dataset;
  const $ = (id) => document.getElementById(id);
  const el = (tag, cls, text) => {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined && text !== null) n.textContent = text;
    return n;
  };
  const icon = (name) => { const i = el('i', `bi ${name}`); i.setAttribute('aria-hidden', 'true'); return i; };

  L.bindCopy(document);
  L.bindDeclare();

  if (cfg.admin === '1') admin();
  else thisDevice();

  // ═══════════════════════════ المسؤول ═══════════════════════════
  function admin() {
    const canApprove = cfg.canApprove === '1';
    const POLL_MS = 10000;
    let board = JSON.parse(($('dvsBoardData') || {}).textContent || '{}');
    let filter = 'all';
    let query = '';
    let pollTimer = null;
    let knownRequests = new Set((board.requests || []).map((r) => r.id));

    const tests = {
      all: () => true,
      now: (r) => r.seen_now,
      attention: (r) => r.attention,
      scan: (r) => r.has_scanner,
    };

    function pill(text, tone) {
      const p = el('span', 'dvs-pill', text);
      if (tone && tone !== 'mute') p.dataset.tone = tone;
      return p;
    }

    function renderCounts() {
      const c = board.counts || {};
      $('dvsCountRegistered').textContent = c.registered ?? 0;
      $('dvsCountNow').textContent = c.now ?? 0;
      $('dvsCountAttention').textContent = c.attention ?? 0;
      $('dvsCountScanners').textContent = c.scanners ?? 0;
      $('dvsReqCount').textContent = c.requests ?? 0;
      const rows = board.rows || [];
      document.querySelectorAll('[data-count]').forEach((n) => {
        n.textContent = rows.filter(tests[n.dataset.count]).length;
      });
    }

    function requestItem(r, seen) {
      const li = el('li', 'dvs-req');
      if (seen) li.dataset.seen = '1';
      const ico = el('span', 'dvs-ico');
      if (!seen) ico.dataset.tone = 'wait';
      ico.appendChild(icon(r.is_phone ? 'bi-phone' : 'bi-display'));
      const text = el('div', 'dvs-req-text');
      text.appendChild(el('span', 'dvs-req-title', r.title));
      text.appendChild(el('span', 'dvs-req-meta',
        `${seen ? 'ظهر' : 'طلب'} · ${r.who} · من ${r.ip} · ${r.when}`));
      li.append(ico, text);
      if (canApprove) {
        const issue = el('button', `btn btn-sm ${seen ? 'btn-outline-primary' : 'btn-primary'}`, 'أصدر كوداً لهذا الجهاز');
        issue.type = 'button';
        issue.addEventListener('click', () => openCode(r.id, `${r.who} · ${r.title}`));
        const dismiss = el('button', 'btn btn-sm btn-outline-secondary', 'تجاهل');
        dismiss.type = 'button';
        dismiss.addEventListener('click', () => act(r.id, 'dismiss', {}, 'أُخفي الطلب. يعود إن طلب الجهازُ من جديد.'));
        li.append(issue, dismiss);
      }
      return li;
    }

    function renderRequests() {
      const list = $('dvsRequests');
      list.replaceChildren();
      (board.requests || []).forEach((r) => list.appendChild(requestItem(r, false)));
      const seen = board.seen || [];
      if (seen.length) {
        list.appendChild(el('li', 'dvs-subhead', 'ظهرت ولم تطلب بعد'));
        seen.forEach((r) => list.appendChild(requestItem(r, true)));
      }
      $('dvsRequestsEmpty').hidden = list.children.length > 0;
    }

    function rowMenu(r) {
      const wrap = el('div', 'dropdown dvs-menu');
      const btn = el('button', 'dvs-icon-btn');
      btn.type = 'button';
      btn.setAttribute('data-bs-toggle', 'dropdown');
      btn.setAttribute('aria-expanded', 'false');
      btn.setAttribute('aria-label', `إجراءات ${r.name}`);
      btn.appendChild(icon('bi-three-dots-vertical'));
      const menu = el('ul', 'dropdown-menu dropdown-menu-end');
      const item = (label, handler, danger) => {
        const li = el('li');
        const b = el('button', `dropdown-item${danger ? ' text-danger' : ''}`, label);
        b.type = 'button';
        b.addEventListener('click', handler);
        li.appendChild(b);
        menu.appendChild(li);
      };
      item('إعادة التسمية', () => openRename(r));
      if (!r.is_server) item('إلغاء التسجيل', () => revoke(r), true);
      wrap.append(btn, menu);
      return wrap;
    }

    function renderRows() {
      const body = $('dvsRows');
      body.replaceChildren();
      const q = query.trim();
      const rows = (board.rows || []).filter((r) => tests[filter](r)
        && (!q || r.name.includes(q) || r.users.includes(q) || r.platform.toLowerCase().includes(q.toLowerCase())));
      rows.forEach((r) => {
        const tr = el('tr');
        const devCell = el('td');
        const dev = el('div', 'dvs-dev');
        const ico = el('span', 'dvs-ico');
        ico.appendChild(icon(r.is_server ? 'bi-hdd-rack' : (r.is_phone ? 'bi-phone' : 'bi-display')));
        const names = el('div');
        const nameLine = el('div', 'dvs-dev-name', r.name);
        if (r.is_server) nameLine.appendChild(pill('هذا الخادم', 'prog'));
        if (r.is_here && !r.is_server) nameLine.appendChild(pill('جهازك', 'prog'));
        if (r.shared) nameLine.appendChild(pill('مشترك', 'prog'));
        names.append(nameLine, el('div', 'dvs-dev-meta', r.platform || '—'));
        dev.append(ico, names);
        devCell.appendChild(dev);

        const seen = el('span', 'dvs-seen');
        if (r.seen_now) seen.dataset.now = '1';
        const dot = el('span', 'dvs-dot');
        dot.setAttribute('aria-hidden', 'true');
        seen.append(dot, document.createTextNode(r.seen));

        const ipCell = el('td');
        ipCell.appendChild(el('span', 'dvs-mono', r.ip));
        const seenCell = el('td');
        seenCell.appendChild(seen);
        const scanCell = el('td');
        scanCell.appendChild(pill(r.scanner, r.scanner_tone));
        const kitCell = el('td');
        kitCell.appendChild(pill(r.kit, r.kit_tone));
        const menuCell = el('td');
        if (canApprove) menuCell.appendChild(rowMenu(r));
        tr.append(devCell, el('td', '', r.users), ipCell, seenCell, scanCell, kitCell, menuCell);
        body.appendChild(tr);
      });
      const empty = $('dvsRowsEmpty');
      empty.hidden = rows.length > 0;
      $('dvsRowsEmptyText').textContent = (board.rows || []).length
        ? 'لا جهاز يطابق البحث أو التصفية.' : 'لا أجهزةَ مسجّلةً بعد. أصدر كوداً من «إضافة جهاز».';
      $('dvsShowAll').hidden = !(board.rows || []).length;
    }

    function render() { renderCounts(); renderRequests(); renderRows(); }

    async function refresh(announce) {
      try {
        const res = await L.api(cfg.boardUrl);
        if (!res.ok) throw new Error(String(res.status));
        const fresh = (res.data.requests || []).filter((r) => !knownRequests.has(r.id));
        board = res.data;
        knownRequests = new Set((board.requests || []).map((r) => r.id));
        render();
        setLive(true);
        if (announce && canApprove) fresh.forEach(announceRequest);
      } catch (_) {
        setLive(false);
      }
    }

    function announceRequest(r) {
      L.actionToast('warning', `${r.who} من ${r.title.split(' — ').pop()} · ${r.ip}`, [
        { label: 'أصدر كوداً', className: 'btn btn-sm btn-primary', onClick: () => openCode(r.id, `${r.who} · ${r.title}`) },
        { label: 'لاحقاً', className: 'btn btn-sm btn-outline-secondary' },
      ], 'جهازٌ غير مسجّل يطلب الانضمام');
    }

    function setLive(ok) {
      const live = $('dvsLive');
      if (!live) return;
      live.dataset.state = ok && !document.hidden ? 'live' : 'paused';
      $('dvsLiveText').textContent = ok ? (document.hidden ? 'متوقّفٌ مؤقّتاً' : 'مباشر · يتحدّث وحده') : 'تعذّر التحديث · نحاول';
    }

    function schedule() {
      clearTimeout(pollTimer);
      if (document.hidden) { setLive(true); return; }
      pollTimer = setTimeout(async () => { await refresh(true); schedule(); }, POLL_MS);
    }
    document.addEventListener('visibilitychange', () => {
      if (!document.hidden) refresh(true);
      schedule();
    });

    $('dvsFilters').addEventListener('click', (ev) => {
      const btn = ev.target.closest('[data-filter]');
      if (!btn) return;
      filter = btn.dataset.filter;
      document.querySelectorAll('[data-filter]').forEach((b) => b.setAttribute('aria-pressed', String(b === btn)));
      renderRows();
    });
    $('dvsSearch').addEventListener('input', (ev) => { query = ev.target.value; renderRows(); });
    $('dvsShowAll').addEventListener('click', () => {
      filter = 'all'; query = ''; $('dvsSearch').value = '';
      document.querySelectorAll('[data-filter]').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.filter === 'all')));
      renderRows();
    });

    async function act(id, action, body, done) {
      const url = cfg.actionUrl.replace('00000000-0000-0000-0000-000000000000', id).replace(/dismiss\/$/, `${action}/`);
      const res = await L.api(url, { method: 'POST', body: body || {} });
      if (!res.ok) { L.toast('danger', res.data.message || 'تعذّر تنفيذ الإجراء.'); return false; }
      if (done) L.toast('success', done);
      await refresh(false);
      return true;
    }

    async function revoke(r) {
      const ok = await window.confirmDelete({
        title: `إلغاء تسجيل «${r.name}»`,
        message: 'يعود الجهازُ غيرَ مسجّل، ويحتاج كوداً جديداً لينضمّ من جديد.',
        okText: 'ألغِ التسجيل', danger: true,
      });
      if (ok) act(r.id, 'revoke', {}, `أُلغي تسجيلُ «${r.name}».`);
    }

    // ── إعادة التسمية ──
    const renameModalEl = $('dvsRenameModal');
    let renaming = null;
    function openRename(r) {
      renaming = r;
      $('dvsRenameInput').value = r.name;
      $('dvsRenameErr').textContent = '';
      window.bootstrap.Modal.getOrCreateInstance(renameModalEl).show();
    }
    renameModalEl.addEventListener('shown.bs.modal', () => $('dvsRenameInput').select());
    $('dvsRenameForm').addEventListener('submit', async (ev) => {
      ev.preventDefault();
      const name = $('dvsRenameInput').value.trim();
      if (!name) { $('dvsRenameErr').textContent = 'اكتب اسماً للجهاز.'; return; }
      const url = cfg.actionUrl.replace('00000000-0000-0000-0000-000000000000', renaming.id).replace(/dismiss\/$/, 'rename/');
      const res = await L.api(url, { method: 'POST', body: { name } });
      if (!res.ok) { $('dvsRenameErr').textContent = res.data.message || 'تعذّر الحفظ.'; return; }
      window.bootstrap.Modal.getOrCreateInstance(renameModalEl).hide();
      L.toast('success', `صار اسمُه «${name}».`);
      refresh(false);
    });

    // ── وضعُ البوّابة ──
    $('dvsModes').addEventListener('change', async (ev) => {
      const input = ev.target.closest('input[name=dvsMode]');
      if (!input) return;
      const previous = board.mode;
      if (input.value === 'only') {
        const ok = await window.confirmDelete({
          title: 'المسجّلة فقط',
          message: 'الجهازُ غيرُ المسجّل لن يرى إلّا صفحة الدخول وإدخال الكود. تأكّد أنّ الموظّفين انضمّوا أوّلاً.',
          okText: 'فعّله', danger: false,
        });
        if (!ok) { restoreMode(previous); return; }
      }
      const res = await L.api(cfg.modeUrl, { method: 'POST', body: { mode: input.value } });
      if (!res.ok) { restoreMode(previous); L.toast('danger', res.data.message || 'تعذّر تغيير الوضع.'); return; }
      board.mode = res.data.mode;
      L.toast('success', `الوضعُ الآن: ${input.closest('label').querySelector('b').textContent}.`);
    });
    function restoreMode(mode) {
      const r = document.querySelector(`input[name=dvsMode][value="${mode}"]`);
      if (r) r.checked = true;
    }

    // ── كودُ الانضمام ──
    const codeModalEl = $('dvsCodeModal');
    let code = null;
    let tick = null;
    let watch = null;

    function stopCode() { clearInterval(tick); clearTimeout(watch); tick = null; watch = null; }
    codeModalEl.addEventListener('hidden.bs.modal', () => { stopCode(); refresh(false); });

    async function openCode(deviceId, forLabel) {
      stopCode();
      const res = await L.api(cfg.codeUrl, { method: 'POST', body: deviceId ? { device: deviceId } : {} });
      if (!res.ok) { L.toast('warning', res.data.message || 'تعذّر إصدار كود.', 'كودُ الانضمام'); return; }
      code = { id: res.data.id, digits: res.data.code, ttl: res.data.ttl, until: Date.now() + res.data.seconds_left * 1000 };
      $('dvsCodeFor').textContent = forLabel ? `للطلب: ${forLabel}` : 'إضافةٌ مباشرة: يصلح لأوّل جهازٍ يكتبه.';
      const digitsEl = $('dvsDigits');
      digitsEl.replaceChildren(...code.digits.split('').map((d) => el('span', 'dvs-digit', d)));
      digitsEl.setAttribute('aria-label', `الكود: ${code.digits.split('').join(' ')}`);
      setCodeState('waiting');
      window.bootstrap.Modal.getOrCreateInstance(codeModalEl).show();
      tickClock();
      tick = setInterval(tickClock, 1000);
      pollCode();
    }

    function tickClock() {
      const left = Math.max(0, Math.round((code.until - Date.now()) / 1000));
      $('dvsClock').textContent = `${Math.floor(left / 60)}:${String(left % 60).padStart(2, '0')}`;
      $('dvsBar').style.transform = `scaleX(${Math.max(0, left / code.ttl)})`;
      if (left <= 0) { stopCode(); setCodeState('expired'); }
    }

    async function pollCode() {
      const res = await L.api(cfg.codeStateUrl.replace('/0/', `/${code.id}/`)).catch(() => null);
      const state = res && res.ok ? res.data.state : 'waiting';
      if (state === 'used') {
        stopCode();
        setCodeState('used', res.data);
        L.toast('success', `«${res.data.device}» دخل بالكود ${code.digits} · ${res.data.user}`, 'انضمّ جهازٌ جديد');
        refresh(false);
        return;
      }
      if (state === 'expired' || state === 'cancelled') { stopCode(); setCodeState(state); return; }
      watch = setTimeout(pollCode, 2000);
    }

    function setCodeState(state, data) {
      $('dvsCodeBox').dataset.state = state;
      const waiting = state === 'waiting';
      $('dvsTimer').hidden = !waiting;
      $('dvsWaiting').hidden = !waiting;
      $('dvsReadout').hidden = !waiting;
      $('dvsCodeCopy').hidden = !waiting;
      $('dvsCodeCancel').hidden = !waiting;
      $('dvsCodeAnother').hidden = waiting;
      $('dvsJoined').hidden = state !== 'used';
      const over = $('dvsCodeOver');
      over.hidden = !(state === 'expired' || state === 'cancelled');
      if (state === 'expired') over.textContent = 'انتهت مدّةُ الكود دون أن يُستعمل، فأُلغي. أصدر كوداً جديداً إن احتجت.';
      if (state === 'cancelled') over.textContent = 'أُلغي الكود، ولن يقبله النظام.';
      if (state === 'used' && data) {
        $('dvsJoinedName').textContent = `انضمّ «${data.device}»`;
        $('dvsJoinedMeta').textContent = `${data.user} · الآن. الكود استُعمل وانتهى.`;
      }
    }

    $('dvsCodeCopy').addEventListener('click', () => code && L.copy(code.digits, 'الكود'));
    $('dvsCodeCancel').addEventListener('click', async () => {
      if (!code) return;
      const res = await L.api(cfg.codeCancelUrl.replace('/0/', `/${code.id}/`), { method: 'POST', body: {} });
      stopCode();
      setCodeState(res.ok && res.data.ok ? 'cancelled' : 'expired');
    });
    $('dvsCodeAnother').addEventListener('click', () => openCode(null, ''));
    const addBtn = $('dvsAddDevice');
    if (addBtn) addBtn.addEventListener('click', () => openCode(null, ''));

    render();
    setLive(true);
    schedule();
    if (cfg.addressNote) {
      let seen = false;
      try { seen = window.sessionStorage.getItem('lettersys_address_note') === cfg.addressNote; } catch (_) { seen = false; }
      if (!seen) {
        L.toast('info', cfg.addressNote, 'تغيّر عنوان الخادم', 9000);
        try { window.sessionStorage.setItem('lettersys_address_note', cfg.addressNote); } catch (_) { /* يظهر مرّةً أخرى فقط */ }
      }
    }
  }

  // ═══════════════════════════ هذا الجهاز ═══════════════════════════
  function thisDevice() {
    const me = $('dvsMe');
    if (!me) return;
    const phone = me.dataset.phone === '1';

    function setCheck(list, key, tone, detail, label) {
      const row = document.querySelector(`#${list} [data-check="${key}"]`);
      if (!row) return;
      row.querySelector('[data-detail]').textContent = detail;
      const p = row.querySelector('[data-pill]');
      if (p) {
        p.textContent = label;
        if (tone && tone !== 'mute') p.dataset.tone = tone; else delete p.dataset.tone;
      }
    }

    async function run() {
      const skew = await L.clockSkew(cfg.meUrl).catch(() => null);
      if (!skew) {
        setCheck('dvsLinkChecks', 'server', 'late', 'لا يردّ الآن. تحقّق من الشبكة ثمّ أعد الفحص.', 'منقطع');
      } else {
        setCheck('dvsLinkChecks', 'server', 'done', `${window.location.hostname} يردّ خلال ${skew.rtt} ms`, 'متّصل');
      }
      const approved = cfg.approvedOrigin;
      const origin = window.location.origin;
      if (window.location.protocol !== 'https:') {
        setCheck('dvsLinkChecks', 'origin', 'wait',
          approved ? `اتّصالٌ غير مشفّر. افتح النظام من ${approved}.` : 'اتّصالٌ غير مشفّر (http)، ولم يُضبط رابطٌ معتمد بعد.', 'غير مشفّر');
      } else if (!approved || approved === origin) {
        setCheck('dvsLinkChecks', 'origin', 'done', `تفتح النظام من ${origin} بشهادةٍ موثوقة`, 'معتمد');
      } else {
        setCheck('dvsLinkChecks', 'origin', 'wait', `تفتح من ${origin}، والمعتمد ${approved}. افتحه من المعتمد.`, 'غير معتمد');
      }

      const zone = (Intl.DateTimeFormat().resolvedOptions().timeZone || '');
      const baghdad = zone === 'Asia/Baghdad';
      if (skew) {
        const secs = Math.round(Math.abs(skew.ms) / 1000);
        const off = secs >= 60;
        const amount = secs >= 120 ? `${Math.round(secs / 60)} دقائق` : `${secs} ثانية`;
        const detail = `${baghdad ? 'بتوقيت بغداد' : `المنطقة الزمنية ${zone || 'غير معروفة'} — ليست بغداد`} · الفرق عن الخادم ${amount}`;
        setCheck('dvsLinkChecks', 'clock', off || !baghdad ? 'wait' : 'done', detail, off || !baghdad ? 'تحتاج ضبطاً' : 'مضبوطة');
        if (off) L.toast('warning', 'التواريخُ تُختم بساعة الخادم، لكنّ مؤقّتات هذا الجهاز قد تخطئ. اضبط الساعة تلقائيّاً من إعدادات ويندوز.', `ساعة هذا الجهاز ${skew.ms < 0 ? 'متأخّرة' : 'متقدّمة'} ${amount}`, 9000);
      } else {
        setCheck('dvsLinkChecks', 'clock', 'mute', 'تُفحص حين يردّ الخادم.', '—');
      }
      const standalone = window.matchMedia && window.matchMedia('(display-mode: standalone)').matches;
      setCheck('dvsLinkChecks', 'app', standalone ? 'done' : 'mute',
        standalone ? 'مفتوحٌ الآن كتطبيقٍ في نافذته.' : 'مفتوحٌ الآن في نافذة متصفّح. يمكن تثبيتُه تطبيقاً من قائمة المتصفّح.',
        standalone ? 'كتطبيق' : 'في المتصفّح');

      $('dvsPhoneNote').hidden = !phone;
      $('dvsKitChecks').hidden = phone;
      if (phone) return;
      const agent = await L.agentState(cfg.infoUrl);
      let outdated = false;
      if (agent.state === 'ok') {
        outdated = L.olderThan(agent.version, cfg.kitVersion);
        setCheck('dvsKitChecks', 'agent', outdated ? 'wait' : 'done',
          outdated ? `الإصدار ${agent.version} · نسخةٌ أحدث ${cfg.kitVersion} على الخادم` : `الإصدار ${agent.version} يعمل`,
          outdated ? 'تحديثٌ متاح' : 'يعمل');
        setCheck('dvsKitChecks', 'naps2', agent.naps2 ? 'done' : 'wait',
          agent.naps2 ? 'مثبّتٌ ضمن حزمة LetterSys' : 'غيرُ موجود: أعد تشغيل LetterSys-Setup', agent.naps2 ? 'مثبّت' : 'ناقص');
        if (me.dataset.registered === '1') {
          L.api(cfg.reportUrl, { method: 'POST', body: { agent_version: agent.version } }).catch(() => null);
        }
      } else {
        const text = agent.state === 'untrusted'
          ? 'يعمل ولا يثق بعنوان هذه الصفحة. افتح النظام من الرابط المعتمد، أو شغّل LetterSys-Setup من جديد.'
          : 'غيرُ مثبّت على هذا الجهاز أو متوقّف. يلزم فقط لمن يمسح.';
        setCheck('dvsKitChecks', 'agent', agent.state === 'untrusted' ? 'wait' : 'mute', text,
          agent.state === 'untrusted' ? 'لا يثق' : 'غير موجود');
        setCheck('dvsKitChecks', 'naps2', 'mute', 'يُفحص مع الوكيل.', '—');
      }
      $('dvsUpdateRow').hidden = !(outdated || agent.state === 'untrusted');
    }

    $('dvsRecheck').addEventListener('click', run);
    run();
  }
})();
