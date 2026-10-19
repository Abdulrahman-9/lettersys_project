(() => {
  'use strict';
  const root = document.getElementById('deviceEnrollment');
  if (!root) return;
  const form = document.getElementById('deviceEnrollmentForm');
  const name = document.getElementById('workstationName');
  const consent = document.getElementById('workstationConsent');
  const button = document.getElementById('pairWorkstation');
  const result = document.getElementById('workstationPairResult');
  let local = null;
  let base = null;
  let registered = false;
  let pairing = false;

  function status(tone, message) {
    result.className = `alert alert-${tone} mt-3`;
    result.textContent = message;
  }

  async function json(url, options = {}) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 12000);
    try {
      const response = await fetch(url, { cache: 'no-store', ...options, signal: controller.signal });
      const data = await response.json();
      if (!response.ok || data.ok !== true) {
        throw new Error(data.message || data.error || `HTTP ${response.status}`);
      }
      return data;
    } finally {
      clearTimeout(timer);
    }
  }

  document.addEventListener('lettersys:agent-detected', async event => {
    if (pairing) return;
    root.hidden = false;
    button.disabled = true;
    local = null;
    registered = false;
    base = event.detail.base;
    const version = String(event.detail.agent.version).split('.').map(Number);
    if (version[0] === 1 && version[1] < 1) {
      status('warning', 'تسجيل اسم الجهاز يحتاج حزمة الأدوات الجديدة. حدّث الحزمة ثم أعد الفحص.');
      return;
    }
    status('info', 'جارٍ قراءة هوية الجهاز والتحقق من ربط حسابك…');
    try {
      const identity = await json(`${base}/agent/workstation`);
      if (!identity.client_uuid || !identity.pair_nonce || typeof identity.paired !== 'boolean') {
        throw new Error('استجابة هوية الجهاز غير صالحة.');
      }
      const mine = await json(root.dataset.mineUrl);
      if (!Array.isArray(mine.devices)) throw new Error('تعذّر التحقق من الأجهزة المسجلة.');
      const existing = mine.devices.find(d => d.client_uuid === identity.client_uuid);
      if (existing && existing.blocked) {
        status('danger', 'المسؤول أوقف هذا الجهاز. اطلب منه رفع الإيقاف قبل تجديد الربط.');
        return;
      }
      registered = Boolean(existing);
      local = identity;
      if (!name.value) name.value = identity.name || identity.machine_name || '';
      consent.checked = false;
      button.textContent = registered ? 'حفظ الاسم وتجديد الربط' : 'حفظ الاسم وتفعيل الربط';
      status(existing && existing.connection === 'online' ? 'success' : 'info',
        registered
          ? `الجهاز «${existing.name}» مسجّل لحسابك. تجديد الربط يلغي مفتاحه القديم فوراً؛ وافق فقط عند تغيير الاسم أو إصلاح الربط.`
          : 'اختر اسماً واضحاً، ثم وافق واحفظ. لا تحتاج موافقة المسؤول على جهاز جديد.');
      button.disabled = false;
    } catch (error) {
      console.error('Workstation identity check failed:', error);
      status('danger', `تعذّر قراءة ربط الجهاز: ${error.message}. أعد الفحص أو حدّث حزمة الأدوات.`);
    }
  });

  form.addEventListener('submit', async event => {
    event.preventDefault();
    if (pairing || !local || !consent.checked || !form.reportValidity()) return;
    pairing = true;
    button.disabled = true;
    const originalLabel = button.textContent;
    button.textContent = 'جارٍ حفظ الاسم وربط الجهاز…';
    status('info', 'جارٍ التسجيل في الخادم ثم حفظ الربط المحمي على هذا الجهاز…');
    try {
      const csrf = form.querySelector('[name=csrfmiddlewaretoken]').value;
      const enrollment = await json(root.dataset.enrollUrl, {
        method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf },
        body: JSON.stringify({
          client_uuid: local.client_uuid, name: name.value.trim(),
          machine_name: local.machine_name || '', replace: registered
        })
      });
      registered = true;
      await json(`${base}/agent/workstation/pair`, {
        method: 'POST', headers: { 'Content-Type': 'application/json', 'X-LetterSys-Pairing': '1' },
        body: JSON.stringify({
          client_uuid: local.client_uuid, server_origin: location.origin,
          name: enrollment.device.name, token: enrollment.token, pair_nonce: local.pair_nonce
        })
      });
      local = await json(`${base}/agent/workstation`);
      if (!local.paired || local.error || !local.last_contact) {
        throw new Error('لم يؤكد الوكيل اتصال الجهاز بالخادم.');
      }
      consent.checked = false;
      status('success', `تم ربط «${enrollment.device.name}» بحسابك. تُتابع حالته تلقائياً كل 30 ثانية عند تشغيل أدواته. افحص ورقة من صفحة الإدخال للتحقق من المسح الحقيقي.`);
    } catch (error) {
      console.error('Workstation pairing failed:', error);
      local = null;
      status('danger', `لم يكتمل الربط: ${error.message}. اضغط «فحص هذا الجهاز» مجدداً قبل إعادة الربط. لا نعدّه جاهزاً بعد.`);
    } finally {
      pairing = false;
      button.disabled = !local;
      button.textContent = registered ? 'حفظ الاسم وتجديد الربط' : originalLabel;
    }
  });
})();
