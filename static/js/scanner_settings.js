/**
 * قسمُ «الماسح الضوئي» ودليلُ تجهيزه (التصميمُ المعتمد 2026-11-18).
 *
 * كلُّ فحصٍ يجري هنا في المتصفّح على وكيل **هذا الجهاز** عبر ScanAgentClient (المصدرُ الواحد
 * مع صفحة الإدخال)، وكلُّ إصلاحٍ زرّ. قواعدُ مراجعة فيبل:
 *  - لا «جاهز» قبل مسحٍ ناجح: الاكتشافُ لا يعني أنّ الماسح يمسح (العنوانُ «الماسح متّصل»).
 *  - المسحُ التجريبيّ يسحب ورقة ⟵ تأكيدٌ قبله، والناتجُ يُعرض ثمّ يُحذف ولا يُرفع.
 *  - إعادةُ البحث في المعالج طلبٌ واحدٌ طائر، والتالي بعد انتهائه بفواصل 5 ⟵ 10 ⟵ 20 ث حتّى
 *    دقيقتين، ويتوقّف عند إخفاء الصفحة وأثناء المسح (السردُ قد يدوم دقيقتين ويقفل الماسح).
 *  - التقريرُ قائمةٌ بيضاء تُعرض قبل النسخ: لا مسارَ NAPS2 (فيه اسمُ مستخدم ويندوز) ولا رقمَ
 *    عمليّة ولا معرّفَ جهاز ولا رمزَ ربط.
 *  - الجهازُ غيرُ المُدار يمسح بلا ربط ⟵ «غير مطلوب» وتُتخطّى خطوتُه.
 * كلُّ نصٍّ جاء من الوكيل (أسماءُ الماسحات) يُكتب textContent وحدَه.
 */
(function () {
  'use strict';

  const root = document.getElementById('scannerSettings');
  const Agent = window.ScanAgentClient;
  if (!root || !Agent) return;

  const MIN_VERSION = '1.0.1';
  const DEVICE_KEY = 'lettersys_scan_device';       // نفسُ مفتاح صفحة الإدخال: الاختيارُ يسري هناك
  const LAST_SCAN_KEY = 'lettersys_last_scan_ok';   // تكتبه صفحةُ الإدخال والمسحُ التجريبيّ عند النجاح
  const RETRY_FIRST_MS = 5000;
  const RETRY_MAX_MS = 120000;
  const LIST_TIMEOUT_MS = 130000;                    // TWAIN ثمّ WIA في الوكيل: حتّى 60 ث لكلٍّ منهما
  const CHECK_KEYS = ['agent', 'trust', 'naps2', 'scanner', 'pairing'];
  const LABELS = {
    agent: 'وكيل المسح', trust: 'ثقة الوكيل بالعنوان', naps2: 'برنامج المسح',
    scanner: 'الماسح', pairing: 'ربط الجهاز',
  };
  const SCAN_ERRORS = {
    no_pages: 'لم يُلتقط شيء. ضع ورقةً في المُغذّي أو على الزجاج ثمّ أعد المحاولة.',
    scan_timeout: 'لم يكتمل المسح ضمن المهلة. تحقّق من الماسح والورق ثمّ أعد المحاولة.',
    device_not_ready: 'الماسح غير جاهز أو يستعمله برنامجٌ آخر. أغلق برامج المسح الأخرى ثمّ أعد المحاولة.',
    scan_failed: 'تعذّر تنفيذ المسح. تحقّق من اتّصال الماسح وتعريفه ثمّ أعد المحاولة.',
    server_unavailable: 'هذا جهازٌ مُدار ولا يمسح قبل ربطه بالشركة. افتح «تجهيز هذا الجهاز» ووافق على الربط.',
    config_error: 'ملفُّ إعداد وكيل المسح لا يحدّد وضعَ الجهاز. أعد تشغيل مُثبِّت LetterSys على هذا الجهاز.',
  };

  const cfg = {
    infoUrl: root.dataset.infoUrl,
    deviceSetupUrl: root.dataset.deviceSetupUrl || '',
    approvedOrigin: root.dataset.approvedOrigin || '',
    packageUrl: root.dataset.packageUrl || '',
    entryUrl: root.dataset.entryUrl || '',
  };
  const $ = (id) => document.getElementById(id);
  const store = {
    get(k) { try { return window.localStorage.getItem(k); } catch (_) { return null; } },
    set(k, v) { try { window.localStorage.setItem(k, v); } catch (_) { /* تخزينٌ محجوب: الاختيارُ لهذه الجلسة */ } },
  };
  const toast = (type, message, title, delay) => {
    if (window.ToastCenter && typeof window.ToastCenter.show === 'function') {
      const opts = {};
      if (title) opts.title = title;
      if (delay) opts.delay = delay;
      window.ToastCenter.show(type, message, opts);
    }
  };
  const confirmApp = (opts) => (typeof window.confirmDelete === 'function'
    ? window.confirmDelete(opts) : Promise.resolve(window.confirm(opts.message)));

  /** عنصرٌ بخصائصه ونصِّه (textContent) وأبنائه — لا innerHTML في هذا الملفّ. */
  function el(tag, props, children) {
    const node = document.createElement(tag);
    Object.entries(props || {}).forEach(([k, v]) => {
      if (v === undefined || v === null) return;
      if (k === 'text') node.textContent = v;
      else if (k === 'class') node.className = v;
      else if (k === 'role' || k.startsWith('data-') || k.startsWith('aria-')) node.setAttribute(k, v);
      else node[k] = v;
    });
    (children || []).forEach((c) => { if (c) node.appendChild(c); });
    return node;
  }
  const spinner = () => el('span', { class: 'scs-spin', 'aria-hidden': 'true' });
  const icon = (name) => el('i', { class: 'bi ' + name, 'aria-hidden': 'true' });

  /** «ثانية» بعدد: 1 ثانية · 2 ثانيتان · 3–10 ثوانٍ · 11+ ثانية. */
  function seconds(n) {
    if (n === 1) return 'ثانية واحدة';
    if (n === 2) return 'ثانيتين';
    return n + (n >= 3 && n <= 10 ? ' ثوانٍ' : ' ثانية');
  }

  function formatWhen(ts) {
    const d = new Date(ts);
    const now = new Date();
    const hm = String(d.getHours()).padStart(2, '0') + ':' + String(d.getMinutes()).padStart(2, '0');
    const sameDay = (a, b) => a.toDateString() === b.toDateString();
    if (sameDay(d, now)) return 'اليوم ' + hm;
    const y = new Date(now); y.setDate(now.getDate() - 1);
    if (sameDay(d, y)) return 'أمس ' + hm;
    return d.getDate() + '/' + (d.getMonth() + 1) + '/' + d.getFullYear() + ' ' + hm;
  }

  // ════════════ الحالة والفحص ════════════
  const st = {
    info: null, base: null, health: null, rejects: false,
    devices: null, devicesFailed: false, driver: '',
    ws: null, checking: false, checkedAt: 0, scanning: false,
    probing: null, discovering: null,
  };

  const agentUsable = () => !!(st.health && Agent.versionAtLeast(st.health.version, MIN_VERSION)
                                && st.health.naps2_available);

  async function probe() {
    if (st.probing) return st.probing;
    // الوكيلُ بلا قفلٍ بين السرد والمسح (scan_agent/server.py): لا فحصَ يسرد أثناء مسحٍ جارٍ.
    if (st.scanning) return null;
    st.checking = true;
    Object.assign(st, { health: null, rejects: false, devices: null, devicesFailed: false, ws: null, driver: '' });
    render();
    st.probing = (async () => {
      try { st.info = await Agent.info(cfg.infoUrl); } catch (_) { st.info = null; /* المنفذُ الافتراضيّ */ }
      const bases = Agent.bases(Agent.port(st.info));
      const hit = await Agent.health(bases);
      st.base = hit ? hit.base : null;
      st.health = hit ? hit.data : null;
      if (!hit) st.rejects = await Agent.respondsButRejects(bases);
      render();
      if (agentUsable()) {
        st.ws = await Agent.workstation(st.base);
        render();
        await discover();
      }
    })();
    try {
      await st.probing;
    } finally {
      st.probing = null;
      st.checking = false;
      st.checkedAt = Date.now();
      render();
      // السردُ داخل الفحص انتهى و«الفحصُ جارٍ» ما زال قائماً فلم يُجدوِل؛ نجدول هنا بعد انتهائه
      // (من يفتح الدليلَ بـ?wizard=1 ويبلغ خطوةَ الماسح قبل انتهاء السرد كان يقرأ «نعيد البحث» بلا مؤقّت).
      maybeScheduleRetry();
    }
  }

  /** سردُ الماسحات — طلبٌ واحدٌ طائر: نقرةٌ ثانيةٌ أو إعادةُ المعالج تنتظر الأوّل ولا تكدّس NAPS2. */
  async function discover() {
    if (!st.base || st.scanning) return null;
    if (st.discovering) return st.discovering;
    st.devices = null;
    st.devicesFailed = false;
    render();
    st.discovering = (async () => {
      try {
        const dd = await Agent.devices(st.base, LIST_TIMEOUT_MS);
        st.devices = Array.isArray(dd.devices) ? dd.devices : [];
        st.driver = typeof dd.driver === 'string' ? dd.driver : '';
        st.devicesFailed = !dd.ok || !!dd.warning;
      } catch (_) {
        st.devices = [];
        st.devicesFailed = true;
      }
    })();
    try {
      await st.discovering;
    } finally {
      st.discovering = null;
      render();
      maybeScheduleRetry();
    }
    return null;
  }

  function chosenDevice() {
    const list = st.devices || [];
    const saved = store.get(DEVICE_KEY);
    return list.find((d) => d.id === saved) || list[0] || null;
  }

  // ════════════ الإصلاحات: لكلّ عطلٍ زرُّه ════════════
  const recheckAction = () => ({ label: 'أعد الفحص', onClick: () => probe() });
  const packageAction = () => (cfg.packageUrl ? { label: 'تنزيل مُثبِّت الجهاز', href: cfg.packageUrl } : null);
  const INSTALL_STEP = 'من مجلّد إعداد LetterSys المشترك افتح 3_Scan_Agent وانقر مرّتين على INSTALL.bat — نقراً عاديّاً — واكتب y للموافقة.';

  function fixStart() {
    return {
      title: 'وكيل المسح متوقّف على هذا الجهاز',
      text: 'شغّل «LetterSys Scan Agent» من قائمة ابدأ، أو سجّل الدخول إلى Windows من جديد فيبدأ وحده. إن لم يكن مثبَّتاً: ' + INSTALL_STEP,
      actions: [packageAction(), recheckAction()],
    };
  }

  function fixOutdated(version) {
    return {
      title: 'نسخةُ وكيل المسح قديمة',
      text: 'الإصدار ' + (version || '؟') + ' أقدم من المطلوب. ' + INSTALL_STEP,
      actions: [packageAction(), recheckAction()],
    };
  }

  function fixTrust() {
    const here = window.location.origin;
    if (cfg.approvedOrigin && cfg.approvedOrigin !== here) {
      return {
        title: 'تفتح النظام من عنوانٍ غير معتمد',
        text: 'وكيلُ المسح يثق بعنوان النظام المعتمد. افتح هذه الصفحة منه ثمّ تابع.',
        actions: [{ label: 'افتح من العنوان المعتمد', href: cfg.approvedOrigin + window.location.pathname + window.location.search, primary: true },
                  recheckAction()],
      };
    }
    return {
      title: 'الوكيل لا يثق بعنوان النظام',
      text: INSTALL_STEP + ' المُثبِّتُ يضيف العنوان، ثمّ اضغط «أعد الفحص» — لا حاجة لإعادة تشغيل شيء.',
      actions: [packageAction(), recheckAction()],
    };
  }

  function fixNaps2() {
    return {
      title: 'برنامج المسح NAPS2 غير مثبّت',
      text: 'ثبّته من مجلّد إعداد LetterSys المشترك (2_NAPS2)، أو أعد تشغيل مُثبِّت الجهاز، ثمّ أعد الفحص.',
      actions: [recheckAction()],
    };
  }

  function fixScanner() {
    return {
      title: 'لم يُكتشف ماسح',
      text: 'اتبع خطوات «الماسح لا يظهر؟» ثمّ ابحث من جديد.',
      actions: [{ label: 'اكتشاف من جديد', onClick: () => discover(), primary: true }],
    };
  }

  function fixPairing() {
    return {
      title: 'هذا جهازٌ مُدار ولا يمسح قبل ربطه',
      text: 'افتح «تجهيز هذا الجهاز»، وسمِّ الجهاز، ووافق على ربطه بالشركة، ثمّ ارجع وأعد الفحص.',
      actions: [cfg.deviceSetupUrl ? { label: 'افتح «تجهيز هذا الجهاز»', href: cfg.deviceSetupUrl + '#deviceEnrollment', primary: true } : null,
                recheckAction()],
    };
  }

  // ════════════ الفحوص الخمسة ════════════
  const row = (tone, pill, detail, fix) => ({ tone, pill, detail, fix: fix || null });

  function checks() {
    const here = window.location.origin;
    const waiting = st.checking && !st.health && !st.rejects;
    const unknown = () => (waiting ? row('busy', 'يُفحص', 'جارٍ الفحص…') : row('idle', 'غير معروف', 'يُعرف حين يعمل الوكيل'));
    const c = {};

    if (waiting) c.agent = row('busy', 'يُفحص', 'جارٍ الفحص…');
    else if (st.health) {
      c.agent = Agent.versionAtLeast(st.health.version, MIN_VERSION)
        ? row('ok', 'يعمل', 'يعمل · الإصدار ' + (st.health.version || '؟'))
        : row('warn', 'قديم', 'الإصدار ' + (st.health.version || '؟') + ' أقدم من المطلوب', fixOutdated(st.health.version));
    } else if (st.rejects) c.agent = row('ok', 'يعمل', 'يستجيب على هذا الجهاز');
    else c.agent = row('bad', 'متوقّف', 'لا يستجيب على هذا الجهاز', fixStart());

    if (st.health) c.trust = row('ok', 'موثوق', here + ' من العناوين الموثوقة');
    else if (st.rejects) c.trust = row('bad', 'لا يثق', 'لا يقبل الصفحات القادمة من ' + here, fixTrust());
    else c.trust = unknown();

    if (st.health) {
      c.naps2 = st.health.naps2_available
        ? row('ok', 'مثبّت', 'برنامج المسح جاهز على هذا الجهاز')
        : row('bad', 'غير مثبّت', 'لا يجد الوكيلُ برنامجَ المسح', fixNaps2());
    } else c.naps2 = unknown();

    if (!agentUsable()) c.scanner = unknown();
    else if (st.devices === null) c.scanner = row('busy', 'يبحث', 'يبحث عن الماسحات الموصولة…');
    else if (st.devices.length) {
      const d = chosenDevice();
      c.scanner = row('ok', 'مكتشَف', d.name + ' · ' + String(d.driver || st.driver || '').toUpperCase() + ' · اكتُشف تلقائيّاً');
    } else if (st.devicesFailed) c.scanner = row('warn', 'تعذّر البحث', 'لم يُكمل الوكيلُ البحثَ عن الماسحات', fixScanner());
    else c.scanner = row('warn', 'لا ماسح', 'لم يُكتشف ماسحٌ موصولٌ بهذا الجهاز', fixScanner());

    if (!agentUsable()) c.pairing = unknown();
    else if (!st.ws) c.pairing = st.checking ? row('busy', 'يُفحص', 'جارٍ الفحص…') : row('idle', 'غير معروف', 'لا يُبلغ هذا الإصدارُ حالةَ الربط');
    else if (st.ws.registration_required) c.pairing = row('warn', 'غير مربوط', 'جهازٌ مُدار لا يمسح قبل ربطه بالشركة', fixPairing());
    else if (st.ws.paired) c.pairing = row('ok', 'مربوط', st.ws.name ? 'مربوط باسم «' + st.ws.name + '»' : 'مربوط بالشركة');
    else c.pairing = row('idle', 'غير مطلوب', 'تثبيتٌ عاديّ يمسح بلا ربط.');
    c.pairing.required = !!(st.ws && (st.ws.registration_required || st.ws.paired));
    return c;
  }

  // ════════════ الرسم ════════════
  function render() {
    const c = checks();
    CHECK_KEYS.forEach((key) => {
      const li = root.querySelector('[data-check="' + key + '"]');
      if (!li) return;
      li.querySelector('.scs-row-detail').textContent = c[key].detail;
      const pill = li.querySelector('.scs-pill');
      pill.textContent = c[key].pill;
      pill.dataset.tone = c[key].tone;
    });
    renderSummary(c);
    renderFix(c);
    renderDevices($('scsDevices'), 'scsDevice');
    // لا سردَ أثناء المسح ولا مسحَ أثناء السرد: الوكيلُ لا يقفل بينهما والماسحُ واحد.
    const listing = !!st.discovering || st.checking;
    $('scsRecheck').disabled = st.scanning;
    $('scsRediscover').disabled = st.scanning || listing;
    $('scsRediscover2').disabled = st.scanning || listing;
    const testBtn = $('scsTestScan');
    testBtn.disabled = st.scanning || listing || !(agentUsable() && st.devices && st.devices.length);
    testBtn.replaceChildren(...(st.scanning ? [spinner(), document.createTextNode(' يمسح…')]
                                            : [document.createTextNode('مسح صفحة تجريبيّة (يسحب ورقة)')]));
    if (wiz.open) renderWizard(c);
  }

  function renderSummary(c) {
    const keys = ['agent', 'trust', 'naps2', 'scanner'].concat(c.pairing.required ? ['pairing'] : []);
    const busy = st.checking || keys.some((k) => c[k].tone === 'busy');
    const okCount = keys.filter((k) => c[k].tone === 'ok').length;
    let state; let title; let sub; let ico;
    if (busy) {
      state = 'checking'; title = 'جارٍ الفحص…'; ico = 'bi-hourglass-split';
      sub = 'نسأل وكيل المسح على هذا الجهاز.';
    } else if (okCount === keys.length) {
      state = 'ok'; title = 'الماسح متّصل'; ico = 'bi-check-lg';
      const last = Number(store.get(LAST_SCAN_KEY)) || 0;
      const d = chosenDevice();
      sub = okCount + ' فحوص من ' + keys.length + ' سليمة · '
        + (last ? 'آخر مسحٍ ناجح من هذا الجهاز ' + formatWhen(last) : 'لم يُجرَّب مسحٌ من هذا الجهاز بعد — جرّب مسح صفحة')
        + (d ? ' · الافتراضي: ' + d.name : '');
    } else {
      const first = keys.find((k) => c[k].tone !== 'ok');
      const blocking = c.agent.tone === 'bad' || c.trust.tone === 'bad';
      state = blocking ? 'bad' : 'warn';
      title = blocking ? 'المسح متوقّف على هذا الجهاز' : 'يحتاج خطوة';
      ico = blocking ? 'bi-x-lg' : 'bi-exclamation-lg';
      sub = okCount + ' من ' + keys.length + ' فحوص سليمة — ' + LABELS[first] + ': ' + c[first].pill;
    }
    $('scsSummary').dataset.state = state;
    $('scsTitle').textContent = title;
    $('scsSub').textContent = sub;
    $('scsIcon').className = 'bi ' + ico;
  }

  function actionNode(a, small) {
    const cls = 'btn ' + (small ? 'btn-sm ' : '') + (a.primary ? 'btn-primary' : 'btn-outline-secondary');
    if (a.href) return el('a', { class: cls, href: a.href, text: a.label });
    const b = el('button', { type: 'button', class: cls, text: a.label });
    b.addEventListener('click', a.onClick);
    return b;
  }

  function renderFix(c) {
    const box = $('scsFix');
    const key = CHECK_KEYS.find((k) => c[k].fix && c[k].tone !== 'busy');
    if (!key) { box.hidden = true; return; }
    const f = c[key].fix;
    box.hidden = false;
    box.dataset.tone = c[key].tone === 'bad' ? 'bad' : 'warn';
    $('scsFixTitle').textContent = f.title;
    $('scsFixText').textContent = f.text;
    $('scsFixActions').replaceChildren(...f.actions.filter(Boolean).map((a) => actionNode(a, true)));
  }

  /** قائمةُ الماسحات (البطاقةُ والمعالجُ يرسمانها بالدالّة نفسها) — الاختيارُ يُحفظ لهذا الجهاز. */
  function renderDevices(box, name) {
    if (!box) return;
    // لا يُعاد رسمُ القائمة إن لم يتغيّر فيها شيء: إعادةُ الرسم كانت تُسقط تركيزَ لوحة المفاتيح عن الاختيار.
    const picked = chosenDevice();
    const sig = JSON.stringify([agentUsable(), st.checking, st.devices && st.devices.map((d) => d.id),
                                st.devicesFailed, picked && picked.id]);
    if (box.dataset.sig === sig) return;
    box.dataset.sig = sig;
    box.replaceChildren();
    if (!agentUsable()) {
      box.appendChild(st.checking ? el('div', { class: 'scs-empty' }, [spinner(), el('span', { text: 'يبحث عن الماسحات…' })])
                                  : el('div', { class: 'scs-empty', text: 'يظهر هنا ما يُكتشف حين يعمل الوكيل.' }));
      return;
    }
    if (st.devices === null) {
      box.appendChild(el('div', { class: 'scs-empty' }, [spinner(), el('span', { text: 'يبحث عن الماسحات… (TWAIN ثمّ WIA)' })]));
      return;
    }
    if (!st.devices.length) {
      box.appendChild(el('div', { class: 'scs-empty', text: st.devicesFailed
        ? 'تعذّر البحث عن الماسحات — اتبع خطوات «الماسح لا يظهر؟» ثمّ اكتشف من جديد.'
        : 'لم يُكتشف ماسح.' }));
      return;
    }
    const chosen = chosenDevice();
    st.devices.forEach((d) => {
      const input = el('input', { type: 'radio', name, value: d.id, className: 'form-check-input' });
      input.checked = !!chosen && d.id === chosen.id;
      input.addEventListener('change', () => {
        store.set(DEVICE_KEY, d.id);
        toast('success', 'صار «' + d.name + '» الماسحَ الافتراضيّ لهذا الجهاز، ويُستعمل في صفحة الإدخال.', 'حُفظ الاختيار');
        render();
      });
      box.appendChild(el('label', { class: 'scs-device' }, [
        input,
        el('span', { class: 'scs-device-name', text: d.name }),
        el('span', { class: 'scs-device-note', text: String(d.driver || '').toUpperCase() }),
      ]));
    });
  }

  // ════════════ المسحُ التجريبيّ: تأكيدٌ قبل سحب الورقة، والناتجُ لا يُرفع ════════════
  async function testScan() {
    const d = chosenDevice();
    if (!d || st.scanning || !agentUsable()) return false;
    if (st.discovering || st.checking) {
      toast('info', 'ننتظر انتهاء البحث عن الماسحات أوّلاً — أعد المحاولة بعد لحظات.', 'البحث جارٍ', 5000);
      return false;
    }
    const ok = await confirmApp({
      title: 'مسح صفحة تجريبيّة',
      message: 'سيسحب «' + d.name + '» ورقةً واحدة من المُغذّي، أو يمسح ما على الزجاج. ضع ورقةً لا تحتاجها ثمّ اضغط «امسح الآن».\nالناتجُ يُعرض لك ثمّ يُحذف، ولا يُرفع إلى النظام.',
      okText: 'امسح الآن',
      danger: false,
    });
    if (!ok) return false;
    st.scanning = true;
    clearRetry();
    render();
    try {
      const r = await Agent.scan(st.base, d);
      if (!r.ok) {
        let e = {};
        try { e = await r.json(); } catch (_) { /* جسمٌ غيرُ JSON */ }
        toast('error', SCAN_ERRORS[e.code] || SCAN_ERRORS.scan_failed, 'لم يكتمل المسح التجريبيّ', 8000);
        return false;
      }
      // الناتجُ يُفتح في أصل التطبيق: لا يُوثَق بنوعٍ أعلنه الطرفُ الآخر (برنامجٌ يحتلّ المنفذ ويردّ
      // text/html كان سيُنفَّذ بجلسة الموظّف). PDF حقيقيٌّ وحدَه، وبنوعٍ نفرضه نحن.
      const buf = await r.arrayBuffer();
      const head = new TextDecoder('latin1').decode(new Uint8Array(buf.slice(0, 5)));
      if (head !== '%PDF-') {
        toast('error', 'ردّ الوكيلُ بملفٍّ ليس PDF فلم يُعرض. أعد المسح، وإن تكرّر فأرسل تقرير الفحص لمسؤول النظام.', 'لم يُعرض الناتج', 9000);
        return false;
      }
      store.set(LAST_SCAN_KEY, String(Date.now()));
      showScanResult(new Blob([buf], { type: 'application/pdf' }), Number(r.headers.get('X-Scan-Pages')) || 1);
      return true;
    } catch (_) {
      toast('error', 'انقطع الاتّصال بالماسح أثناء المسح. تأكّد أنه متّصل ويعمل ثمّ أعد المحاولة.', 'لم يكتمل المسح التجريبيّ', 8000);
      return false;
    } finally {
      st.scanning = false;
      render();
      maybeScheduleRetry();
    }
  }

  function showScanResult(blob, pages) {
    const url = URL.createObjectURL(blob);
    let alive = true;
    setTimeout(() => { alive = false; URL.revokeObjectURL(url); }, 120000);   // يُحذف بعد دقيقتين — لم يُرفع شيء
    const message = 'التُقطت ' + (pages === 1 ? 'صفحةٌ واحدة' : pages + ' صفحات') + ' — المسحُ يعمل من هذا الجهاز. الناتجُ لم يُرفع إلى النظام ويُحذف بعد دقيقتين.';
    if (window.ToastCenter && typeof window.ToastCenter.action === 'function') {
      window.ToastCenter.action('success', message, [
        { label: 'عرض الصفحة الممسوحة', className: 'btn btn-sm btn-success fw-semibold',
          onClick: () => {
            if (!alive) {
              toast('info', 'حُذف الناتجُ بعد دقيقتين كما وُعد — أعد المسح التجريبيّ إن احتجت رؤيته.', 'حُذف الناتج', 5000);
              return;
            }
            window.open(url, '_blank', 'noopener');
          } },
      ], { title: 'نجح المسح التجريبيّ', delay: 0, autohide: false });
    } else {
      toast('success', message, 'نجح المسح التجريبيّ');
    }
  }

  // ════════════ التقرير: قائمةٌ بيضاء تُعرض قبل النسخ ════════════
  function reportText() {
    const c = checks();
    const lines = [
      'LetterSys — تقرير فحص الماسح',
      'الوقت: ' + formatWhen(Date.now()),
      'عنوان الصفحة: ' + window.location.origin,
      'وكيل المسح: ' + c.agent.pill + (st.health ? ' · الإصدار ' + (st.health.version || '؟') : ''),
      'خطأ إعداد الوكيل: ' + ((st.health && st.health.config_error) || 'لا يوجد'),
      'ثقة الوكيل بالعنوان: ' + c.trust.pill,
      'NAPS2: ' + c.naps2.pill,
      'السائق: ' + (st.driver ? st.driver.toUpperCase() : '—'),
      'الماسحات: ' + ((st.devices && st.devices.length) ? st.devices.map((d) => d.name).join('، ') : 'لا شيء'),
      'ربط الجهاز: ' + c.pairing.pill,
    ];
    return lines.join('\n');
  }

  function openReport() {
    $('scsReportText').textContent = reportText();
    window.bootstrap.Modal.getOrCreateInstance($('scsReportModal')).show();
  }

  async function copyReport() {
    const text = $('scsReportText').textContent;
    try {
      await navigator.clipboard.writeText(text);
      toast('success', 'نُسخ التقرير — الصقه في رسالتك لمسؤول النظام.', 'نُسخ', 4000);
    } catch (_) {
      const range = document.createRange();
      range.selectNodeContents($('scsReportText'));
      const sel = window.getSelection();
      sel.removeAllRanges();
      sel.addRange(range);
      toast('info', 'حُدِّد التقرير — انسخه بـCtrl+C.', 'انسخ يدويّاً', 5000);
    }
  }

  // ════════════ دليلُ التجهيز ════════════
  const STEPS = [
    { key: 'agent', label: 'الوكيل' },
    { key: 'trust', label: 'العنوان' },
    { key: 'scanner', label: 'الماسح' },
    { key: 'pairing', label: 'الربط' },
    { key: 'test', label: 'مسح تجريبي (اختياري)' },
  ];
  const wiz = { open: false, i: 0, timer: null, delay: RETRY_FIRST_MS, nextAt: 0, tested: false, checks: new Set() };

  function stepState(key, c) {
    if (key === 'agent') {
      if (c.agent.tone === 'busy') return 'busy';
      return c.agent.tone === 'ok' && c.naps2.tone !== 'bad' ? 'ok' : 'fail';
    }
    if (key === 'trust') return c.trust.tone === 'busy' ? 'busy' : (c.trust.tone === 'ok' ? 'ok' : 'fail');
    if (key === 'scanner') return c.scanner.tone === 'busy' ? 'busy' : (c.scanner.tone === 'ok' ? 'ok' : 'fail');
    if (key === 'pairing') {
      if (c.pairing.tone === 'busy') return 'busy';
      if (!c.pairing.required) return 'skip';
      return c.pairing.tone === 'ok' ? 'ok' : 'fail';
    }
    return wiz.tested ? 'ok' : 'optional';
  }

  const stepIndex = (from, dir, states) => {
    for (let j = from + dir; j >= 0 && j < STEPS.length; j += dir) if (states[j] !== 'skip') return j;
    return -1;
  };

  function stepBody(key, state, c) {
    const nodes = [];
    const title = (text, tone) => el('h3', { class: 'scs-wiz-title', text, 'data-tone': tone || '' });
    const sub = (text) => el('p', { class: 'scs-wiz-sub', text });
    const live = (text) => el('div', { class: 'scs-wiz-live' }, [spinner(), el('span', { text })]);
    const actions = (list) => el('div', { class: 'scs-actions' }, list.filter(Boolean).map((a) => actionNode(a, false)));
    const fixOf = (k) => c[k].fix;

    if (state === 'busy') {
      nodes.push(title(key === 'scanner' ? 'نبحث عن الماسحات الموصولة…' : 'نفحص هذه الخطوة…'));
      nodes.push(live(key === 'scanner' ? 'TWAIN ثمّ WIA — قد يستغرق ذلك دقيقة.' : 'لحظات…'));
      return nodes;
    }
    if (key === 'agent') {
      if (state === 'ok') {
        nodes.push(title('وكيل المسح يعمل على هذا الجهاز', 'ok'));
        nodes.push(sub(st.health ? 'الإصدار ' + (st.health.version || '؟') + ' · برنامج المسح جاهز.' : 'يستجيب على هذا الجهاز.'));
      } else {
        const f = fixOf('naps2') && c.naps2.tone === 'bad' ? fixOf('naps2') : fixOf('agent');
        nodes.push(title(f.title, 'warn'), sub(f.text), actions(f.actions));
      }
    } else if (key === 'trust') {
      if (state === 'ok') nodes.push(title('الوكيل يثق بعنوان النظام', 'ok'), sub(window.location.origin));
      else {
        const f = fixOf('trust') || fixStart();
        nodes.push(title(f.title, 'warn'), sub(f.text), actions(f.actions));
      }
    } else if (key === 'scanner') {
      if (state === 'ok') {
        const n = st.devices.length;
        nodes.push(title(n === 1 ? 'وجدنا ماسحاً موصولاً بهذا الجهاز' : 'وجدنا ' + n + ' ماسحات موصولة بهذا الجهاز', 'ok'));
        nodes.push(sub('اخترنا الذي استعملتَه آخر مرّة، أو الأوّل. وافق عليه أو اختر غيره.'));
        const list = el('div', { class: 'scs-devices', role: 'radiogroup', 'aria-label': 'الماسحات المكتشفة' });
        renderDevices(list, 'scsWizDevice');
        nodes.push(list);
      } else {
        nodes.push(title('لم نجد ماسحاً موصولاً بعد', 'warn'));
        nodes.push(sub('جرّبنا TWAIN ثمّ WIA. نعيد البحث تلقائيّاً بعد انتهاء كلّ محاولة، بفواصل تتباعد من 5 ثوانٍ حتّى دقيقتين، ويتوقّف إن أخفيت الصفحة.'));
        ['الماسح يعمل وضوؤه ثابت', 'كبل USB موصول بالجهاز مباشرةً', 'تعريف الماسح مثبّت من المجلد المشترك (1_Scanner_Driver)',
         'لا يعمل برنامج مسحٍ آخر الآن'].forEach((t) => {
          // علاماتُ الموظّف تبقى عبر إعادة الرسم (كلُّ بحثٍ يعيد رسمَ الخطوة)
          const box = el('input', { type: 'checkbox', className: 'form-check-input' });
          box.checked = wiz.checks.has(t);
          box.addEventListener('change', () => { if (box.checked) wiz.checks.add(t); else wiz.checks.delete(t); });
          nodes.push(el('label', { class: 'scs-check' }, [box, el('span', { text: t })]));
        });
        if (st.discovering) nodes.push(live('يبحث الآن…'));
        else if (wiz.timer) nodes.push(el('div', { class: 'scs-wiz-live', text: 'نعيد البحث بعد ' + seconds(Math.max(1, Math.round((wiz.nextAt - Date.now()) / 1000))) + '.' }));
        nodes.push(actions([{ label: 'ابحث من جديد', onClick: () => { clearRetry(); discover(); }, primary: true }]));
      }
    } else if (key === 'pairing') {
      if (state === 'ok') nodes.push(title('الجهاز مربوط بالشركة', 'ok'), sub(c.pairing.detail));
      else {
        const f = fixOf('pairing') || fixPairing();
        nodes.push(title(f.title, 'warn'), sub(f.text), actions(f.actions));
      }
    } else if (key === 'test') {
      const d = agentUsable() && st.devices && st.devices.length ? chosenDevice() : null;
      if (wiz.tested) {
        nodes.push(title('نجح المسح التجريبيّ — الماسح جاهز', 'ok'));
        nodes.push(sub('ابدأ المسح من صفحة الإدخال متى شئت.'));
        if (cfg.entryUrl) nodes.push(actions([{ label: 'افتح صفحة الإدخال', href: cfg.entryUrl, primary: true }]));
      } else if (!d) {
        nodes.push(title('لا ماسح لتجربته'), sub('أكمل خطوة الماسح أوّلاً، أو أنهِ الدليل وجرّب لاحقاً.'));
      } else {
        nodes.push(title('مسح صفحة تجريبيّة (اختياري)'));
        nodes.push(sub('يسحب «' + d.name + '» ورقةً واحدة ليتأكّد أنّ المسح يعمل من هذا الجهاز. الناتجُ يُعرض ثمّ يُحذف ولا يُرفع.'));
        nodes.push(actions([{ label: st.scanning ? 'يمسح…' : 'امسح صفحة الآن', primary: true,
                              onClick: async () => { if (await testScan()) { wiz.tested = true; render(); } } }]));
      }
    }
    return nodes;
  }

  function renderWizard(c) {
    c = c || checks();
    const states = STEPS.map((s) => stepState(s.key, c));
    if (states[wiz.i] === 'skip') wiz.i = Math.max(0, stepIndex(wiz.i, 1, states));
    const visible = STEPS.map((s, j) => j).filter((j) => states[j] !== 'skip');

    $('scsWizSteps').replaceChildren(...STEPS.map((s, j) => {
      let mark;
      if (states[j] === 'skip') mark = 'skip';
      else if (j === wiz.i) mark = states[j] === 'fail' ? 'fail' : 'current';
      else mark = states[j] === 'ok' ? 'done' : 'todo';
      const dotText = mark === 'done' ? '✓' : (mark === 'fail' ? '!' : (mark === 'skip' ? '–' : String(visible.indexOf(j) + 1)));
      const li = el('li', { 'data-st': mark }, [
        el('span', { class: 'scs-wiz-dot', text: dotText, 'aria-hidden': 'true' }),
        el('span', { text: s.key === 'pairing' && mark === 'skip' ? 'الربط · غير مطلوب' : s.label }),
      ]);
      if (j === wiz.i) li.setAttribute('aria-current', 'step');
      return li;
    }));

    // محتوى الخطوة يُعاد بناؤه حين تتغيّر حالتُها وحدَها — إعادةُ البناء مع كلّ رسمٍ كانت تُسقط
    // تركيزَ لوحة المفاتيح عن الاختيار.
    const picked = chosenDevice();
    const bodySig = JSON.stringify([wiz.i, states, CHECK_KEYS.map((k) => c[k].tone),
                                    (st.devices || []).map((d) => d.id), picked && picked.id, !!st.discovering,
                                    wiz.timer ? wiz.nextAt : 0, wiz.tested, st.scanning]);
    const body = $('scsWizBody');
    if (body.dataset.sig !== bodySig) {
      body.dataset.sig = bodySig;
      body.replaceChildren(...stepBody(STEPS[wiz.i].key, states[wiz.i], c));
    }

    const back = stepIndex(wiz.i, -1, states);
    const next = stepIndex(wiz.i, 1, states);
    const cur = states[wiz.i];
    $('scsWizCount').textContent = 'الخطوة ' + (visible.indexOf(wiz.i) + 1) + ' من ' + visible.length;
    $('scsWizBack').disabled = back < 0;
    const nextBtn = $('scsWizNext');
    nextBtn.textContent = next < 0 ? 'إنهاء' : 'موافق، التالي';
    nextBtn.disabled = !(next < 0 || cur === 'ok' || cur === 'optional');
    $('scsWizSkip').hidden = !(STEPS[wiz.i].key === 'scanner' && cur === 'fail' && next >= 0);
  }

  function go(dir) {
    const states = STEPS.map((s) => stepState(s.key, checks()));
    const j = stepIndex(wiz.i, dir, states);
    if (j < 0) {
      if (dir > 0) finishWizard();
      return;
    }
    wiz.i = j;
    clearRetry();
    render();
    maybeScheduleRetry();
    $('scsWizBody').focus({ preventScroll: true });
  }

  function finishWizard() {
    window.bootstrap.Modal.getOrCreateInstance($('scsWizard')).hide();
    const c = checks();
    const ready = ['agent', 'trust', 'naps2', 'scanner'].every((k) => c[k].tone === 'ok');
    toast(ready ? 'success' : 'warning',
          ready ? 'انتهى التجهيز — ابدأ المسح من صفحة الإدخال.' : 'بقيت خطوةٌ لم تكتمل — تجدها في «حالة الاتصال» بزرّها.',
          ready ? 'الماسح متّصل' : 'التجهيز غير مكتمل', 6000);
  }

  // ── إعادةُ البحث في خطوة الماسح: طلبٌ واحدٌ طائر، بتراجعٍ أُسّيّ، ويتوقّف حين لا يُرى ──
  function clearRetry() {
    clearTimeout(wiz.timer);
    wiz.timer = null;
  }

  function maybeScheduleRetry() {
    if (wiz.timer || !wiz.open || document.hidden || st.scanning || st.discovering || st.checking) return;
    if (STEPS[wiz.i].key !== 'scanner' || !agentUsable() || !st.devices || st.devices.length) {
      if (st.devices && st.devices.length) wiz.delay = RETRY_FIRST_MS;
      return;
    }
    wiz.nextAt = Date.now() + wiz.delay;
    wiz.timer = setTimeout(async () => {
      wiz.timer = null;
      if (!wiz.open || document.hidden || st.scanning) return;
      wiz.delay = Math.min(wiz.delay * 2, RETRY_MAX_MS);   // التالي أبعد إن لم يُعثر على شيء
      await discover();                                       // discover يعيد الجدولة عند انتهائه
    }, wiz.delay);
    render();
  }

  function openWizard() {
    wiz.open = true;
    wiz.i = 0;
    wiz.delay = RETRY_FIRST_MS;
    window.bootstrap.Modal.getOrCreateInstance($('scsWizard')).show();
    if (!st.checking && Date.now() - st.checkedAt > 10000) probe();
    render();
  }

  // ════════════ الربط ════════════
  $('scsRecheck').addEventListener('click', () => probe());
  ['scsRediscover', 'scsRediscover2'].forEach((id) => {
    $(id).addEventListener('click', () => (agentUsable() ? discover() : probe()));
  });
  $('scsTestScan').addEventListener('click', () => testScan());
  $('scsWizardOpen').addEventListener('click', openWizard);
  $('scsReport').addEventListener('click', openReport);
  $('scsReportCopy').addEventListener('click', copyReport);
  $('scsWizNext').addEventListener('click', () => go(1));
  $('scsWizBack').addEventListener('click', () => go(-1));
  $('scsWizSkip').addEventListener('click', () => go(1));
  $('scsWizBody').tabIndex = -1;
  $('scsWizard').addEventListener('hidden.bs.modal', () => { wiz.open = false; clearRetry(); });
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) clearRetry();
    else maybeScheduleRetry();
  });

  probe();
  if (new URLSearchParams(window.location.search).get('wizard') === '1') openWizard();
})();
