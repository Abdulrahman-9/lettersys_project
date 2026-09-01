/**
 * network_settings.js
 * ─────────────────────────────────────────────────────────────────────────────
 * منطق صفحة إعدادات الربط الشبكي.
 *  - اختيار دور الجهاز (مستقل / ماستر / تابع)
 *  - اكتشاف IP تلقائياً
 *  - فحص الاتصال بـ PostgreSQL
 *  - فحص الاتصال بجهاز LetterSys آخر
 *  - مسح الشبكة الفرعية
 *  - إدارة جدول الأجهزة (تحديث، فحص الكل، حذف)
 *  - حفظ الإعدادات
 */

(function () {
  'use strict';

  // ─── حالة ────────────────────────────────────────────────────────────────────
  const urls  = window.NS_URLS  || {};
  const csrf  = window.NS_CSRF  || '';
  const cfg   = window.NS_CFG   || {};

  // ─── مساعدات عامة ────────────────────────────────────────────────────────────
  function el(id) { return document.getElementById(id); }

  function post(url, body) {
    return fetch(url, {
      method:  'POST',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf },
      body:    JSON.stringify(body),
    }).then(r => r.json());
  }

  function get(url) {
    return fetch(url, {
      headers: { 'X-Requested-With': 'XMLHttpRequest' }
    }).then(r => r.json());
  }

  function showAlert(container, msg, type = 'info') {
    container.style.display = 'block';
    container.className     = `ns-alert ns-alert-${type}`;
    container.innerHTML     = msg;
  }

  function setBusy(btn, busy, icon, label) {
    btn.disabled = busy;
    btn.innerHTML = busy
      ? '<span class="spinner-border spinner-border-sm me-1"></span> جارٍ…'
      : `<i class="${icon} me-1"></i>${label}`;
  }

  function timeSince(isoStr) {
    if (!isoStr) return '—';
    const diff = Math.round((Date.now() - new Date(isoStr)) / 1000);
    if (diff < 60)  return 'منذ لحظات';
    if (diff < 3600) return `منذ ${Math.floor(diff / 60)} دق`;
    return `منذ ${Math.floor(diff / 3600)} ساعة`;
  }

  function pingBadge(ms) {
    if (!ms) return '—';
    const cls = ms < 50 ? 'ns-ping-good' : ms < 200 ? 'ns-ping-ok' : 'ns-ping-slow';
    return `<span class="ns-ping-badge ${cls}">${ms}ms</span>`;
  }

  // ─── اختيار الدور ────────────────────────────────────────────────────────────
  const roleCards = document.querySelectorAll('.ns-role-card');

  function setRole(role) {
    roleCards.forEach(card => {
      const r = card.dataset.role;
      card.classList.toggle('ns-role-active', r === role);
      card.querySelector('input[type=radio]').checked = r === role;
    });
    const panels = { master: el('panelMaster'), slave: el('panelSlave') };
    Object.entries(panels).forEach(([r, p]) => {
      if (p) p.style.display = role === r ? '' : 'none';
    });
    // تحديث عرض IP الماستر
    if (role === 'master') syncMasterIpDisplay();
  }

  roleCards.forEach(card => {
    card.addEventListener('click', () => setRole(card.dataset.role));
  });

  // ─── مزامنة عرض IP الماستر ───────────────────────────────────────────────────
  function syncMasterIpDisplay() {
    const disp = el('masterIpDisplay');
    if (disp) {
      const ip = (el('thisHost')?.value?.trim()) || cfg.localIp || '—';
      disp.textContent = ip;
    }
  }

  el('thisHost')?.addEventListener('input', syncMasterIpDisplay);

  // ─── اكتشاف IP تلقائياً ──────────────────────────────────────────────────────
  el('detectIpBtn')?.addEventListener('click', async () => {
    const btn = el('detectIpBtn');
    setBusy(btn, true, '', '');
    try {
      const data = await get(urls.localIp);
      if (data.ip) {
        el('thisHost').value = data.ip;
        syncMasterIpDisplay();
        if (data.hostname && el('deviceName') && !el('deviceName').value) {
          el('deviceName').value = data.hostname;
        }
      }
    } catch (e) {
      console.warn('IP detect failed:', e);
    } finally {
      setBusy(btn, false, 'bi-wifi', '');
    }
  });

  // ─── إظهار / إخفاء كلمة المرور ──────────────────────────────────────────────
  el('togglePwBtn')?.addEventListener('click', () => {
    const pw  = el('masterDbPassword');
    const ico = el('togglePwBtn').querySelector('i');
    if (pw.type === 'password') {
      pw.type = 'text';
      ico.className = 'bi bi-eye-slash';
    } else {
      pw.type = 'password';
      ico.className = 'bi bi-eye';
    }
  });

  // ─── نسخ إعدادات الماستر ─────────────────────────────────────────────────────
  el('copyMasterConfig')?.addEventListener('click', () => {
    const box = el('masterInfoBox');
    const rows = box.querySelectorAll('.ns-info-row');
    let text = '';
    rows.forEach(r => {
      const k = r.querySelector('.ns-info-key')?.textContent?.trim() || '';
      const v = r.querySelector('.ns-info-val')?.textContent?.trim() || '';
      if (!v.includes('•')) text += `${k}=${v}\n`;
    });
    navigator.clipboard.writeText(text).then(() => {
      el('copyMasterConfig').innerHTML = '<i class="bi bi-check-lg me-1"></i>تم النسخ!';
      setTimeout(() => {
        el('copyMasterConfig').innerHTML = '<i class="bi bi-clipboard me-1"></i>نسخ للحافظة';
      }, 2000);
    }).catch(() => alert(text));
  });

  // ─── فحص الاتصال بالماستر (HTTP ping) ───────────────────────────────────────
  el('pingMasterBtn')?.addEventListener('click', async () => {
    const ip   = el('masterHost')?.value?.trim();
    const port = el('appPort')?.value || 8000;
    const res  = el('pingMasterResult');
    if (!ip) { res.innerHTML = '<span class="text-danger">أدخل IP الماستر أولاً</span>'; return; }

    res.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span> جارٍ الفحص…';
    try {
      const data = await post(urls.testPing, { ip, port: parseInt(port) });
      if (data.ok) {
        res.innerHTML = `<span class="text-success"><i class="bi bi-check-circle-fill me-1"></i>
          متصل — ${data.data?.name || ip} (${data.data?.ping_ms || '?'}ms) — نسخة ${data.data?.version || '?'}</span>`;
      } else {
        res.innerHTML = `<span class="text-danger"><i class="bi bi-x-circle-fill me-1"></i>${data.error}</span>`;
      }
    } catch (e) {
      res.innerHTML = '<span class="text-danger">خطأ في الشبكة</span>';
    }
  });

  // ─── اختبار اتصال قاعدة البيانات ─────────────────────────────────────────────
  el('testDbBtn')?.addEventListener('click', async () => {
    const btn = el('testDbBtn');
    const res = el('testDbResult');
    setBusy(btn, true, 'bi-database-check', 'اختبار الاتصال');

    const payload = {
      host:     el('masterHost')?.value?.trim(),
      port:     parseInt(el('masterDbPort')?.value || 5432),
      db_name:  el('masterDbName')?.value?.trim(),
      user:     el('masterDbUser')?.value?.trim(),
      password: el('masterDbPassword')?.value,
    };

    try {
      const data = await post(urls.testDb, payload);
      if (data.ok) {
        showAlert(res,
          `<i class="bi bi-check-circle-fill me-2"></i><strong>اتصال ناجح</strong> — ${data.message}`,
          'success');
      } else {
        showAlert(res,
          `<i class="bi bi-x-circle-fill me-2"></i>${data.message || data.error}`,
          'error');
      }
    } catch (e) {
      showAlert(res, '<i class="bi bi-x-circle-fill me-2"></i>خطأ في الشبكة', 'error');
    } finally {
      setBusy(btn, false, 'bi-database-check', 'اختبار الاتصال');
    }
  });

  // ─── حفظ الإعدادات ───────────────────────────────────────────────────────────
  el('saveConfigBtn')?.addEventListener('click', async () => {
    const btn = el('saveConfigBtn');
    const res = el('saveResult');
    const role = document.querySelector('input[name=deviceRole]:checked')?.value || 'standalone';
    setBusy(btn, true, 'bi-floppy', 'حفظ الإعدادات');

    const payload = {
      role,
      device_name: el('deviceName')?.value?.trim() || '',
      this_host:   el('thisHost')?.value?.trim()   || '',
      app_port:    parseInt(el('appPort')?.value   || 8000),
    };

    if (role === 'slave') {
      Object.assign(payload, {
        master_host:        el('masterHost')?.value?.trim()     || '',
        master_db_port:     parseInt(el('masterDbPort')?.value  || 5432),
        master_db_name:     el('masterDbName')?.value?.trim()   || 'lettersys',
        master_db_user:     el('masterDbUser')?.value?.trim()   || '',
        master_db_password: el('masterDbPassword')?.value       || '',
      });
    }

    try {
      const data = await post(urls.saveConfig, payload);
      if (data.ok) {
        res.style.display = 'inline-block';
        res.innerHTML = `<span class="text-success"><i class="bi bi-check-circle-fill me-1"></i>${data.message}</span>`;
        if (data.needs_restart) {
          el('restartBanner').style.display = 'block';
        }
        // تحديث قائمة الأجهزة
        loadDevices();
      } else {
        res.style.display = 'inline-block';
        res.innerHTML = `<span class="text-danger"><i class="bi bi-x-circle me-1"></i>${data.error || 'فشل الحفظ'}</span>`;
      }
    } catch (e) {
      res.style.display = 'inline-block';
      res.innerHTML = '<span class="text-danger">خطأ في الاتصال</span>';
    } finally {
      setBusy(btn, false, 'bi-floppy', 'حفظ الإعدادات');
    }
  });

  // ─── جدول الأجهزة ────────────────────────────────────────────────────────────

  function buildNodeRow(n) {
    const roleBadge = n.role === 'master'
      ? '<span class="badge" style="background:#0369a1;font-size:.72rem;">ماستر</span>'
      : '<span class="badge" style="background:#16a34a;font-size:.72rem;">تابع</span>';
    const statusHtml = n.is_online
      ? '<span class="ns-online-dot"></span> متصل'
      : '<span class="ns-offline-dot"></span> غير متصل';
    const currentBadge = n.is_current
      ? '<span class="badge bg-primary ms-1" style="font-size:.7rem;">أنا</span>' : '';
    const icon = n.is_current
      ? '<i class="bi bi-pc-display text-primary" title="هذا الجهاز"></i>'
      : '<i class="bi bi-display text-muted"></i>';
    const deleteBtn = n.is_current ? '' :
      `<button class="btn btn-xs ns-btn-delete" data-node-id="${n.id}" title="حذف"><i class="bi bi-trash3"></i></button>`;

    return `
      <tr data-node-id="${n.id}">
        <td>${icon}</td>
        <td>${n.name}${currentBadge}</td>
        <td><code>${n.ip}:${n.port}</code></td>
        <td>${roleBadge}</td>
        <td>${statusHtml}</td>
        <td class="text-muted" style="font-size:.8rem;">${timeSince(n.last_seen)}</td>
        <td>${pingBadge(n.ping_ms)}</td>
        <td>${deleteBtn}</td>
      </tr>`;
  }

  async function loadDevices() {
    try {
      const data = await get(urls.devices);
      if (!data.ok) return;

      const tbody = el('devicesTableBody');
      if (!tbody) return;

      if (!data.devices.length) {
        tbody.innerHTML = `
          <tr id="emptyDevicesRow">
            <td colspan="8" class="text-center text-muted py-4" style="font-size:.9rem;">
              <i class="bi bi-diagram-3 me-2"></i>لا توجد أجهزة مسجّلة
            </td>
          </tr>`;
      } else {
        tbody.innerHTML = data.devices.map(buildNodeRow).join('');
        bindDeleteButtons();
      }

      // تحديث عداد المستخدمين
      const uc = el('activeUsersCount');
      if (uc) uc.textContent = data.active_users;

      // تحديث حالة DB
      updateDbStatusChip(data.devices);
    } catch (e) {
      console.warn('loadDevices error:', e);
    }
  }

  function updateDbStatusChip(devices) {
    const chip = el('dbStatusChip');
    if (!chip) return;
    const onlineMaster = devices.find(d => d.role === 'master' && d.is_online);
    const isConnected  = onlineMaster || cfg.localIp === el('currentDbHost')?.textContent;
    const dot = chip.querySelector('.ns-dot');
    if (isConnected) {
      dot.className = 'ns-dot online';
      chip.innerHTML = `<span class="ns-dot online"></span> قاعدة البيانات متصلة`;
    } else {
      dot.className = 'ns-dot offline';
      chip.innerHTML = `<span class="ns-dot offline"></span> تحقق من الاتصال`;
    }
  }

  function bindDeleteButtons() {
    document.querySelectorAll('.ns-btn-delete').forEach(btn => {
      btn.addEventListener('click', async () => {
        const pk = btn.dataset.nodeId;
        if (!confirm('هل تريد حذف هذا الجهاز من السجل؟')) return;
        const url  = urls.deleteDevice.replace('{pk}', pk);
        const data = await post(url, {});
        if (data.ok) {
          btn.closest('tr').remove();
        } else {
          alert(data.error || 'تعذّر الحذف');
        }
      });
    });
  }

  el('refreshDevicesBtn')?.addEventListener('click', loadDevices);

  // ─── فحص جميع الأجهزة ────────────────────────────────────────────────────────
  el('pingAllBtn')?.addEventListener('click', async () => {
    const btn = el('pingAllBtn');
    setBusy(btn, true, 'bi-broadcast', 'فحص الكل');
    try {
      await post(urls.pingAll, {});
      await loadDevices();
    } catch (e) {
      console.warn('pingAll error:', e);
    } finally {
      setBusy(btn, false, 'bi-broadcast', 'فحص الكل');
    }
  });

  // ─── مسح الشبكة ──────────────────────────────────────────────────────────────
  el('scanSubnetBtn')?.addEventListener('click', async () => {
    const btn      = el('scanSubnetBtn');
    const progress = el('scanProgress');
    const subnetEl = el('scanSubnet');
    const port     = parseInt(el('appPort')?.value || 8000);

    setBusy(btn, true, 'bi-radar', 'مسح الشبكة تلقائياً');
    if (progress) progress.style.display = 'block';

    try {
      const data = await post(urls.scanSubnet, { port });
      if (subnetEl) subnetEl.textContent = data.subnet || '';
      if (data.ok) {
        await loadDevices();
        if (data.count === 0) {
          alert('لم يُعثر على أجهزة LetterSys أخرى على الشبكة.');
        }
      }
    } catch (e) {
      alert('خطأ أثناء مسح الشبكة');
    } finally {
      setBusy(btn, false, 'bi-radar', 'مسح الشبكة تلقائياً');
      if (progress) progress.style.display = 'none';
    }
  });

  // ─── إضافة يدوية ─────────────────────────────────────────────────────────────
  el('addDeviceBtn')?.addEventListener('click', () => {
    const form = el('addDeviceForm');
    if (form) form.style.display = form.style.display === 'none' ? '' : 'none';
  });

  el('cancelAddDevice')?.addEventListener('click', () => {
    const form = el('addDeviceForm');
    if (form) form.style.display = 'none';
  });

  el('pingNewDeviceBtn')?.addEventListener('click', async () => {
    const ip   = el('newDeviceIp')?.value?.trim();
    const port = parseInt(el('newDevicePort')?.value || 8000);
    const res  = el('addDeviceResult');
    if (!ip) { res.innerHTML = '<span class="text-danger">أدخل عنوان IP</span>'; return; }

    res.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span> جارٍ الفحص…';
    try {
      const data = await post(urls.testPing, { ip, port });
      if (data.ok) {
        res.innerHTML = `<span class="text-success"><i class="bi bi-check-circle-fill me-1"></i>
          تم إضافة ${data.data?.name || ip} بنجاح</span>`;
        el('newDeviceIp').value  = '';
        el('addDeviceForm').style.display = 'none';
        await loadDevices();
      } else {
        res.innerHTML = `<span class="text-danger"><i class="bi bi-x-circle-fill me-1"></i>${data.error}</span>`;
      }
    } catch (e) {
      res.innerHTML = '<span class="text-danger">خطأ في الشبكة</span>';
    }
  });

  // ─── ربط أزرار الحذف الأولية ─────────────────────────────────────────────────
  bindDeleteButtons();

  // ─── تهيئة الدور الأولي ──────────────────────────────────────────────────────
  setRole(cfg.role || 'standalone');

  // تحميل جدول الأجهزة فور فتح الصفحة
  loadDevices();

  // ─── اكتشاف IP عند التحميل إذا لم يكن محفوظاً ───────────────────────────────
  if (!el('thisHost')?.value?.trim()) {
    get(urls.localIp).then(d => {
      if (d.ip && el('thisHost')) {
        el('thisHost').value = d.ip;
        syncMasterIpDisplay();
      }
      if (d.hostname && el('deviceName') && !el('deviceName').value) {
        el('deviceName').value = d.hostname;
      }
    }).catch(() => {});
  }

  // ─── تحديث فوري بـ SSE مع fallback للـ polling ──────────────────────────────
  let _sseActive = false;

  function startSSE() {
    if (!urls.devicesStream || !window.EventSource) return false;
    try {
      const sse = new EventSource(urls.devicesStream);

      sse.onmessage = (e) => {
        try {
          const msg = JSON.parse(e.data);
          if (msg.type === 'refresh') loadDevices();
        } catch (_) {}
      };

      sse.onopen = () => {
        _sseActive = true;
        // إيقاف polling إن كان يعمل
        if (window._nsPollingTimer) {
          clearInterval(window._nsPollingTimer);
          window._nsPollingTimer = null;
        }
      };

      sse.onerror = () => {
        _sseActive = false;
        sse.close();
        // تشغيل polling كاحتياطي إذا انقطع SSE
        if (!window._nsPollingTimer) {
          window._nsPollingTimer = setInterval(loadDevices, 15000);
        }
        // محاولة إعادة الاتصال SSE بعد 20 ثانية
        setTimeout(startSSE, 20000);
      };

      return true;
    } catch (_) {
      return false;
    }
  }

  // تشغيل SSE أو polling احتياطي
  if (!startSSE()) {
    window._nsPollingTimer = setInterval(loadDevices, 30000);
  }

})();
