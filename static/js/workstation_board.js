(() => {
  'use strict';
  const root = document.getElementById('workstationBoard');
  if (!root) return;
  const rows = document.getElementById('workstationRows');
  const status = document.getElementById('workstationBoardStatus');
  const refresh = document.getElementById('refreshWorkstations');
  const csrf = document.querySelector('#workstationBoardCsrf [name=csrfmiddlewaretoken]').value;
  const connections = {
    online: ['متصل', 'success'], offline: ['غير متصل', 'secondary'],
    pairing: ['الربط لم يكتمل', 'warning'], revoked: ['موقوف', 'danger'],
    expired: ['يحتاج تجديد الربط', 'warning']
  };
  const scanners = {
    ready: 'ظهر ماسح في الفحص', no_device: 'لم يظهر ماسح', error: 'تعذّر الفحص',
    unknown: 'يحتاج فحصاً حديثاً', missing_naps2: 'NAPS2 غير جاهز'
  };
  let busy = false;

  function empty(message) {
    rows.replaceChildren();
    const cell = document.createElement('td');
    cell.colSpan = 7;
    cell.textContent = message;
    const row = document.createElement('tr');
    row.append(cell);
    rows.append(row);
  }

  async function json(url, options = {}) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 8000);
    try {
      const response = await fetch(url, { cache: 'no-store', ...options, signal: controller.signal });
      const data = await response.json();
      if (!response.ok || data.ok !== true) throw new Error(data.error || `HTTP ${response.status}`);
      return data;
    } finally {
      clearTimeout(timer);
    }
  }

  function render(devices) {
    rows.replaceChildren();
    if (!devices.length) return empty('لم يُربط أي جهاز بعد. أرسل حزمة التجهيز للموظفين عبر وسيلة موثوقة.');
    for (const device of devices) {
      const connection = connections[device.connection];
      if (!connection || !scanners[device.scanner] || !Array.isArray(device.scanner_names) ||
          !/^[0-9a-f-]{36}$/.test(device.id)) throw new Error('Invalid device status');
      const row = document.createElement('tr');
      for (const text of [device.name, device.owner]) {
        const cell = document.createElement('td');
        cell.textContent = text;
        row.append(cell);
      }
      const state = document.createElement('td');
      const badge = document.createElement('span');
      badge.className = `badge text-bg-${connection[1]}`;
      badge.textContent = connection[0];
      state.append(badge);
      row.append(state);
      for (const text of [
        device.scanner_names.length ? device.scanner_names.join('، ') : scanners[device.scanner],
        device.last_seen ? new Date(device.last_seen).toLocaleString('ar-IQ') : 'لم يتواصل بعد',
        device.agent_version || 'لم يُرسل بعد'
      ]) {
        const cell = document.createElement('td');
        cell.textContent = text;
        row.append(cell);
      }
      const action = document.createElement('td');
      const button = document.createElement('button');
      button.type = 'button';
      button.className = `btn btn-sm btn-outline-${device.blocked ? 'primary' : 'danger'}`;
      button.textContent = device.blocked ? 'رفع الإيقاف' : 'إيقاف الربط';
      button.setAttribute('aria-label', `${button.textContent}: ${device.name}`);
      button.addEventListener('click', async () => {
        const message = device.blocked
          ? `رفع إيقاف «${device.name}» والسماح للموظف بتجديد ربطه؟`
          : `إيقاف ربط «${device.name}»؟ لن تسحب أدواته ورقاً جديداً حتى رفع الإيقاف وتجديد الربط.`;
        if (!window.confirm(message)) return;
        button.disabled = true;
        try {
          await json(`${root.dataset.apiBase}${device.id}/${device.blocked ? 'unblock' : 'revoke'}/`, {
            method: 'POST', headers: { 'X-CSRFToken': csrf }
          });
          await load();
        } catch (error) {
          console.error('Device administration failed:', error);
          status.className = 'alert alert-danger';
          status.textContent = 'تعذّر تغيير ربط الجهاز. أعد تحديث الحالة؛ لم نؤكد نجاح العملية.';
          button.disabled = false;
        }
      });
      action.append(button);
      row.append(action);
      rows.append(row);
    }
  }

  async function load() {
    if (busy) return;
    busy = true;
    refresh.disabled = true;
    try {
      const data = await json(root.dataset.statusUrl);
      if (!Array.isArray(data.devices)) throw new Error('Invalid device list');
      render(data.devices);
      status.className = 'alert alert-success';
      status.textContent = 'تم تحديث الحالة. تُتابع تلقائياً أثناء بقاء هذه الصفحة مفتوحة.';
    } catch (error) {
      console.error('Workstation status load failed:', error);
      empty('تعذّر تحديث حالة الأجهزة. لا نعتمد الحالة القديمة دليلاً على الاتصال.');
      status.className = 'alert alert-danger';
      status.textContent = 'تعذّر الاتصال أو انتهت جلسة الدخول. أعد تسجيل الدخول ثم حدّث الحالة.';
    } finally {
      busy = false;
      refresh.disabled = false;
    }
  }

  refresh.addEventListener('click', load);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) load(); });
  setInterval(() => { if (!document.hidden) load(); }, 20000);
  load();
})();
