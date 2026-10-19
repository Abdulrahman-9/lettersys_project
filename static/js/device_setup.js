(() => {
  'use strict';
  const root = document.getElementById('deviceSetup');
  if (!root) return;
  const connection = document.getElementById('setupConnection');
  const result = document.getElementById('deviceCheckResult');
  const button = document.getElementById('checkDevice');
  const spinner = document.getElementById('deviceCheckSpinner');
  const label = document.getElementById('deviceCheckLabel');
  const help = document.getElementById('deviceSetupHelp');
  const download = document.getElementById('downloadSetup');
  const port = Number(root.dataset.agentPort);

  function reveal(panel, trigger) {
    panel.hidden = false;
    if (trigger) trigger.setAttribute('aria-expanded', 'true');
    panel.querySelector('h2')?.focus();
    panel.scrollIntoView({ block: 'nearest', behavior: 'auto' });
  }

  for (const [triggerId, panelId] of [
    ['showTrustHelp', 'trustSetupHelp'],
    ['showSetupHelp', 'deviceSetupHelp'],
    ['showScannerHelp', 'scannerSetupHelp'],
  ]) {
    const trigger = document.getElementById(triggerId);
    trigger.addEventListener('click', () => reveal(document.getElementById(panelId), trigger));
  }
  document.getElementById('retryConnection').addEventListener('click', async event => {
    event.currentTarget.disabled = true;
    try { await checkConnection(); }
    finally { event.currentTarget.disabled = false; }
  });
  for (const id of ['recheckAfterSetup', 'recheckScanner']) {
    document.getElementById(id).addEventListener('click', () => {
      if (!button.disabled) button.click();
    });
  }
  document.getElementById('goEnrollment').addEventListener('click', () => {
    const enrollment = document.getElementById('deviceEnrollment');
    if (enrollment.hidden) {
      status(result, 'info', 'اضغط «فحص هذا الجهاز» أولاً. بعد اكتشاف أدواته تظهر حقول الاسم والموافقة هنا؛ لا تحتاج كتابة أوامر.');
      button.focus();
    } else {
      reveal(enrollment);
      document.getElementById('workstationName').focus();
    }
  });
  document.getElementById('installSetupApp').addEventListener('click', async event => {
    const installResult = document.getElementById('setupInstallResult');
    if (!window.isSecureContext || location.protocol !== 'https:') {
      installResult.textContent = 'أكمل الاتصال الآمن أولاً؛ زر شهادة الثقة في الخطوة الأولى يشرح الطريقة.';
      return;
    }
    if (typeof window.isInstalledApp === 'function' && window.isInstalledApp()) {
      installResult.textContent = 'البرنامج مفتوح كتطبيق بالفعل؛ لا تحتاج تثبيته مرة أخرى.';
      return;
    }
    const outcome = typeof window.promptAppInstall === 'function'
      ? await window.promptAppInstall(event.currentTarget) : 'unavailable';
    installResult.textContent = outcome === 'accepted'
      ? 'وافق المتصفح على الطلب؛ أكمل نافذة التثبيت. لم نعدّ التثبيت منجزاً حتى يؤكده المتصفح.'
      : 'إن لم تظهر نافذة التثبيت، استخدم خيار تثبيت الموقع من قائمة المتصفح كما هو موضح أدناه. عدم ظهورها لا يعني أن النظام لا يعمل.';
  });

  function status(element, tone, message) {
    element.className = `alert alert-${tone} mt-3`;
    element.textContent = message;
  }

  async function fetchJSON(url, timeout) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeout);
    try {
      const response = await fetch(url, { signal: controller.signal, cache: 'no-store' });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return await response.json();
    } finally {
      clearTimeout(timer);
    }
  }

  async function checkConnection() {
    try {
      const health = await fetchJSON(root.dataset.healthUrl, 5000);
      if (health.ok !== true) throw new Error('Invalid server health response');
      if (!window.isSecureContext || location.protocol !== 'https:') {
        status(connection, 'warning', 'النظام متصل، لكن هذا العنوان غير آمن للتجهيز. اطلب حزمة شهادة الثقة وعنوان HTTPS من المسؤول، ثم افتح الرابط الآمن. لا تتجاوز تحذير الشهادة.');
        if (download) download.hidden = true;
        return false;
      }
      status(connection, 'success', 'اتصال النظام جاهز وآمن. يمكنك إضافة أيقونة البرنامج، أو فحص الماسح إن كان هذا الجهاز متصلاً به.');
      return true;
    } catch (error) {
      console.error('Device setup server health check failed:', error);
      status(connection, 'danger', 'تعذّر الاتصال بالنظام أو انتهت جلسة الدخول. أعد فتح النظام وتسجيل الدخول، ثم حاول مجدداً. لا تغلق المتصفح أثناء تجهيز الجهاز.');
      return false;
    }
  }

  button.addEventListener('click', async () => {
    button.disabled = true;
    spinner.classList.remove('d-none');
    label.textContent = 'فحص هذا الجهاز — جارٍ الفحص…';
    help.hidden = true;
    document.getElementById('showSetupHelp').setAttribute('aria-expanded', 'false');
    status(result, 'info', 'جارٍ فحص أدوات المسح على هذا الجهاز…');
    try {
      if (!await checkConnection()) {
        status(result, 'warning', 'أكمل تجهيز الاتصال الآمن أولاً، ثم أعد فحص الجهاز.');
        return;
      }
      if (!Number.isInteger(port) || port < 1 || port > 65535) {
        throw new Error('Invalid scanner agent port');
      }
      let agent = null;
      let base = null;
      for (const host of ['127.0.0.1', 'localhost']) {
        try {
          const url = `http://${host}:${port}`;
          const health = await fetchJSON(`${url}/agent/health`, 3500);
          if (health.ok !== true || typeof health.naps2_available !== 'boolean') {
            throw new Error('Invalid scanner health response');
          }
          agent = health;
          base = url;
          break;
        } catch (error) {
          console.warn(`Device setup agent probe failed (${host}):`, error);
        }
      }
      if (!agent) {
        status(result, 'warning', 'لم نتمكن من الوصول لأدوات المسح على هذا الجهاز. إن ظهر طلب السماح بالأجهزة المحلية فاختر «سماح» ثم أعد الفحص؛ وإلا نفّذ خطوة التجهيز أدناه. قد يكون الوكيل متوقفاً أو لا يسمح بعنوان النظام.');
        help.hidden = false;
        return;
      }
      const version = String(agent.version || '').split('.').map(Number);
      if (version.length < 3 || version.some(n => !Number.isInteger(n) || n < 0) ||
          (version[0] === 1 && version[1] === 0 && version[2] < 1) || version[0] < 1) {
        status(result, 'warning', 'أدوات المسح تحتاج تحديثاً. شغّل حزمة التجهيز أدناه ثم أعد الفحص.');
        help.hidden = false;
        return;
      }
      document.dispatchEvent(new CustomEvent('lettersys:agent-detected', { detail: { base, agent } }));
      if (!agent.naps2_available) {
        status(result, 'warning', 'الوكيل متصل، لكن أداة المسح NAPS2 غير جاهزة. شغّل حزمة التجهيز أدناه ثم أعد الفحص.');
        help.hidden = false;
        return;
      }
      status(result, 'info', 'الأدوات متصلة. جارٍ البحث عن الماسح؛ قد يستغرق ذلك قليلاً…');
      const devices = await fetchJSON(`${base}/agent/devices`, 130000);
      if (devices.ok !== true || !Array.isArray(devices.devices) || devices.warning ||
          devices.devices.some(d => !d || typeof d.name !== 'string' || !d.name.trim())) {
        throw new Error(devices.warning || 'Invalid scanner device response');
      }
      if (!devices.devices.length) {
        status(result, 'warning', 'أدوات المسح جاهزة، لكن لم يظهر ماسح. شغّل الماسح ووصل الكابل وأغلق برامج المسح الأخرى ثم أعد الفحص. إذا بقي غير ظاهر، اطلب من المسؤول فحص تعريف الجهاز.');
        return;
      }
      status(result, 'success', `تم العثور على: ${devices.devices.map(d => d.name).join('، ')}. اكتمل فحص الاتصال؛ جرّب ورقة من صفحة الإدخال للتأكد من المسح الفعلي.`);
    } catch (error) {
      console.error('Device setup scanner check failed:', error);
      status(result, 'danger', 'تعذّر إكمال فحص الماسح؛ لا نعدّه جاهزاً بعد. أغلق برامج المسح الأخرى وأعد الفحص. إذا استمر الخطأ، اطلب مساعدة المسؤول.');
      help.hidden = false;
    } finally {
      button.disabled = false;
      document.getElementById('showSetupHelp').setAttribute('aria-expanded', String(!help.hidden));
      spinner.classList.add('d-none');
      label.textContent = 'فحص هذا الجهاز';
    }
  });

  window.addEventListener('online', checkConnection);
  window.addEventListener('offline', () => {
    status(connection, 'warning', 'يبدو الاتصال منقطعاً. تحقق من الشبكة، ثم أعد الفحص؛ تجهيز الجهاز يحتاج الوصول لخادم النظام.');
  });
  checkConnection();
})();
