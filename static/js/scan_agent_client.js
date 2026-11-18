/**
 * عميلُ وكيل المسح المحلّيّ — **مصدرٌ واحد** لصفحة الإدخال ولقسم «الماسح الضوئي» في
 * الإعدادات (كان المسبارُ مكرَّراً في الصفحتين فتباعدتا: إحداهما تعرض مسارَ NAPS2 وفيه
 * اسمُ مستخدم ويندوز، والأخرى لا).
 *
 * الوكيلُ يعمل على **هذا الجهاز** ويستمع على حلقته المحلّيّة وحدَها، فالخادمُ لا يراه:
 * يقول المنفذَ فقط، والمتصفّحُ يسأل الوكيلَ مباشرةً. بلا ترويسةِ توكِن — الوكيلُ يحرس نفسه
 * بـHost وOrigin، وترويسةٌ زائدةٌ تُفشل الطلبَ الاستباقيّ.
 *
 * كلُّ دالّةٍ هنا بلا حالةٍ مخفيّة: المنفذُ والمضيفُ يُمرَّران، فتبقى حالةُ كلّ صفحةٍ في صفحتها.
 */
(function () {
  'use strict';

  const DEFAULT_PORT = 17865;

  /** fetch بمهلة (AbortController): منفذٌ ميّتٌ يُرفَض فوراً، ووكيلٌ عالقٌ لا يُعلِّق الصفحة. */
  async function fetchWithTimeout(url, opts, ms) {
    const ctrl = new AbortController();
    const outer = opts && opts.signal;
    if (outer) {
      if (outer.aborted) ctrl.abort();
      else outer.addEventListener('abort', () => ctrl.abort(), { once: true });
    }
    const timer = setTimeout(() => ctrl.abort(), ms || 8000);
    try {
      return await fetch(url, Object.assign({}, opts, { signal: ctrl.signal }));
    } finally {
      clearTimeout(timer);
    }
  }

  const ScanAgentClient = {
    DEFAULT_PORT,
    fetchWithTimeout,

    /** ‎{agent_url, port, server_can_start}‎ من الخادم. */
    async info(url) {
      const r = await fetchWithTimeout(url || '/books/api/scan/agent-info/', { credentials: 'same-origin' }, 8000);
      return r.json();
    },

    /** منفذُ الوكيل من ردّ `info`، وإلّا الافتراضُ المشحون. */
    port(info) {
      const p = parseInt(info && info.port, 10);
      return (p > 0 && p < 65536) ? p : DEFAULT_PORT;
    },

    /** المضيفان المسموحان في CSP: 127.0.0.1 ثمّ localhost (بروكسي المتصفّح قد يحجب أحدهما). */
    bases(port) {
      return [`http://127.0.0.1:${port}`, `http://localhost:${port}`];
    },

    /** أوّلُ مضيفٍ ردّ بصحّةٍ مقروءة ⟵ ‎{base, data}‎، أو null (غيرُ مشغّل أو لا يثق بأصلنا). */
    async health(bases) {
      for (const base of bases) {
        try {
          const r = await fetchWithTimeout(base + '/agent/health', {}, 2500);
          if (r.ok) return { base, data: await r.json() };
        } catch (_) { /* جرّب المضيف التالي */ }
      }
      return null;
    },

    /**
     * أيستجيب شيءٌ على المنفذ ولو رفض أصلَنا؟ مسبارُ `no-cors`: الاستجابةُ معتمة لكنّ
     * الوعدَ ينجح إن ردّ الطرفُ الآخر — فنفرّق «غير مشغّل» عن «يعمل ولا يثق بهذا العنوان».
     */
    async respondsButRejects(bases) {
      for (const base of bases) {
        try {
          await fetchWithTimeout(base + '/agent/health', { mode: 'no-cors' }, 2500);
          return true;
        } catch (_) { /* جرّب المضيف التالي */ }
      }
      return false;
    },

    /** الماسحاتُ الموصولة (TWAIN ثمّ WIA في الوكيل نفسه): ‎{ok, driver, devices, warning?}‎. */
    async devices(base, ms, signal) {
      const r = await fetchWithTimeout(base + '/agent/devices', { signal }, ms || 20000);
      return r.json();
    },

    /** حالةُ ربط الجهاز (‎registration_required · paired · name · last_contact‎)، أو null. */
    async workstation(base) {
      try {
        const r = await fetchWithTimeout(base + '/agent/workstation', {}, 4000);
        return r.ok ? await r.json() : null;
      } catch (_) {
        return null;
      }
    },

    /** مسحٌ واحدٌ تلقائيّ المصدر ⟵ Response (PDF عند النجاح، JSON عند الفشل). */
    async scan(base, device, signal, ms) {
      return fetchWithTimeout(base + '/agent/scan', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ device_id: device.id, driver: device.driver, mode: 'auto' }),
        signal,
      }, ms || 180000);
    },

    /** ‎version ≥ minimum‎ بمقارنةٍ رقميّة لكلّ مقطع (‎1.10 > 1.9‎). */
    versionAtLeast(version, minimum) {
      const parts = (value) => String(value || '').split('.').map(p => Number.parseInt(p, 10) || 0);
      const current = parts(version);
      const required = parts(minimum);
      const length = Math.max(current.length, required.length);
      for (let i = 0; i < length; i += 1) {
        if ((current[i] || 0) !== (required[i] || 0)) return (current[i] || 0) > (required[i] || 0);
      }
      return true;
    },
  };

  window.ScanAgentClient = Object.freeze(ScanAgentClient);
})();
