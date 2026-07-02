/**
 * document_manager.js — لوحة إدارة مستندات الكتاب (مكان واحد لكل العمليات).
 *
 * مساحة عمل احترافية تُركَّب في صفحة التعديل (وضع التعديل) وتوحّد:
 *   معاينة · استبدال · دمج صفحات · حذف صفحات · حذف · إرفاق ملحق
 * تجلب المرفقات من api_book_detail_json وتنفّذ كل عملية عبر AJAX (دون إعادة تحميل)،
 * بحالات تحميل سلسة وإشعارات وتأكيدات أنيقة.
 *
 * الاستخدام:
 *   const dm = new DocumentManager({ bookId, mount, onPreview });
 *   dm.refresh();
 */
(function () {
  'use strict';

  const SAFE_URL = /^(https?:\/\/|\/)/i;

  function csrf() {
    const m = document.cookie.match(/csrftoken=([^;]+)/);
    return m ? m[1] : '';
  }

  function fmtSize(bytes) {
    if (!bytes && bytes !== 0) return '';
    const u = ['B', 'KB', 'MB', 'GB'];
    let i = 0, n = bytes;
    while (n >= 1024 && i < u.length - 1) { n /= 1024; i++; }
    return (i === 0 ? n : n.toFixed(1)) + ' ' + u[i];
  }

  function el(tag, cls, attrs) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (attrs) for (const k in attrs) {
      if (k === 'text') e.textContent = attrs[k];
      else if (k === 'html') e.innerHTML = attrs[k];
      else e.setAttribute(k, attrs[k]);
    }
    return e;
  }

  class DocumentManager {
    /**
     * @param {Object} o
     * @param {number|string} o.bookId
     * @param {HTMLElement} o.mount  حاوية التركيب
     * @param {function(Object)=} o.onPreview  نداء عند طلب معاينة مرفق (يتلقّى {url,name,kind})
     */
    constructor(o) {
      this.bookId = o.bookId;
      this.mount = o.mount;
      this.onPreview = o.onPreview || null;
      this.onAfterMutate = o.onAfterMutate || null;  // يُستدعى بعد كل عملية (لإبطال معاينة العارض)
      this.base = '/books';
      this.attachments = [];
      this.busy = false;
      this._build();
    }

    // ── الهيكل الثابت ──────────────────────────────────────────────────────────
    _build() {
      this.root = el('div', 'docman');
      this.root.innerHTML =
        '<div class="docman-head">' +
        '  <div class="docman-title"><i class="bi bi-folder2-open"></i><span>مستندات الكتاب</span>' +
        '    <span class="docman-count" data-count>0</span></div>' +
        '  <button type="button" class="docman-add" data-add>' +
        '    <i class="bi bi-plus-lg"></i> إرفاق مستند</button>' +
        '</div>' +
        '<div class="docman-body" data-body>' +
        '  <div class="docman-loading"><span class="spinner-border spinner-border-sm"></span> جارٍ التحميل…</div>' +
        '</div>';
      this.bodyEl = this.root.querySelector('[data-body]');
      this.countEl = this.root.querySelector('[data-count]');
      this.root.querySelector('[data-add]').addEventListener('click', () => this._addAnnex());
      this.mount.appendChild(this.root);
    }

    // ── جلب وعرض ───────────────────────────────────────────────────────────────
    async refresh() {
      try {
        const r = await fetch(`${this.base}/api/book/${this.bookId}/preview/`, {
          headers: { 'X-Requested-With': 'XMLHttpRequest' },
        });
        if (!r.ok) throw new Error('تعذّر تحميل المرفقات');
        const d = await r.json();
        this.attachments = (d.attachments || []).filter(a => a.url);
        this._render();
      } catch (e) {
        this.bodyEl.innerHTML = '';
        this.bodyEl.appendChild(el('div', 'docman-empty', { text: 'تعذّر تحميل المرفقات.' }));
      }
    }

    _render() {
      this.countEl.textContent = String(this.attachments.length);
      this.bodyEl.innerHTML = '';
      if (!this.attachments.length) {
        const empty = el('div', 'docman-empty');
        empty.innerHTML = '<i class="bi bi-inbox"></i><div>لا توجد مستندات بعد — استخدم «إرفاق مستند» أو امسح من السكانر.</div>';
        this.bodyEl.appendChild(empty);
        return;
      }
      this.attachments.forEach(att => this.bodyEl.appendChild(this._card(att)));
    }

    _kind(att) {
      if (att.is_pdf) return 'pdf';
      if (att.is_image) return 'image';
      return 'other';
    }

    _card(att) {
      const kind = this._kind(att);
      const card = el('div', 'docman-card');

      const icon = el('div', 'docman-ic docman-ic-' + kind);
      icon.innerHTML = kind === 'pdf' ? '<i class="bi bi-file-earmark-pdf"></i>'
        : kind === 'image' ? '<i class="bi bi-file-earmark-image"></i>'
        : '<i class="bi bi-file-earmark"></i>';

      const meta = el('div', 'docman-meta');
      const nameRow = el('div', 'docman-name', { title: att.name || 'مستند', text: att.name || 'مستند' });
      if (att.is_primary) nameRow.appendChild(el('span', 'docman-badge', { text: 'أساسي' }));
      const sub = el('div', 'docman-sub', { text: [fmtSize(att.size), kind === 'pdf' ? 'PDF' : (kind === 'image' ? 'صورة' : '')].filter(Boolean).join(' · ') });
      meta.appendChild(nameRow);
      meta.appendChild(sub);

      const acts = el('div', 'docman-acts');
      acts.appendChild(this._actBtn('معاينة', 'bi-eye', 'view', () => this._preview(att)));
      acts.appendChild(this._actBtn('استبدال', 'bi-arrow-repeat', '', () => this._replace(att)));
      if (kind === 'pdf') {
        // المستند الأساسي: مسح/رفع وإلحاق «بالتجهيز» داخل المعاينة (تمييز الجديد + الحفظ يثبّت).
        // غير الأساسي: يبقى الدمج الفوري (حالة نادرة متعدّدة المرفقات).
        if (att.is_primary && window.extractionSystem) {
          acts.appendChild(this._actBtn('مسح وإلحاق', 'bi-upc-scan', 'accent', () => window.extractionSystem.scanAndAppend()));
          acts.appendChild(this._actBtn('رفع وإلحاق', 'bi-file-earmark-plus', '', () => this._uploadAndAppend()));
        } else {
          acts.appendChild(this._actBtn('دمج صفحات', 'bi-layers', '', () => this._merge(att)));
        }
        acts.appendChild(this._actBtn('حذف صفحات', 'bi-scissors', '', () => this._removePages(att)));
      }
      acts.appendChild(this._actBtn('حذف', 'bi-trash3', 'danger', () => this._delete(att)));

      card.appendChild(icon);
      card.appendChild(meta);
      card.appendChild(acts);
      return card;
    }

    _actBtn(label, icon, variant, onClick) {
      const b = el('button', 'docman-btn' + (variant ? ' docman-btn-' + variant : ''), { type: 'button', title: label });
      b.innerHTML = `<i class="bi ${icon}"></i><span>${label}</span>`;
      b.addEventListener('click', onClick);
      return b;
    }

    // ── العمليات ───────────────────────────────────────────────────────────────
    _preview(att) {
      const payload = { url: att.url, name: att.name, kind: this._kind(att) };
      if (this.onPreview) { this.onPreview(payload); return; }
      if (window.DocView && window.DocView.open) { window.DocView.open(att.url, att.name); return; }
      if (SAFE_URL.test(att.url)) window.open(att.url, '_blank', 'noopener');
    }

    async _replace(att) {
      const file = await this._pickFile('application/pdf,image/*', false);
      if (!file) return;
      const fd = new FormData(); fd.append('file', file);
      await this._run(`${this.base}/attachment/${att.id}/replace/`, fd, 'جارٍ الاستبدال…');
    }

    async _delete(att) {
      const ok = await this._confirm('حذف المستند', `سيُنقل «${att.name || 'مستند'}» إلى سلة المهملات. متابعة؟`, 'حذف', 'danger');
      if (!ok) return;
      await this._run(`${this.base}/attachment/${att.id}/delete/`, new FormData(), 'جارٍ الحذف…');
    }

    async _merge(att) {
      const files = await this._pickFile('application/pdf', true);
      if (!files || !files.length) return;
      const ok = await this._confirm('دمج صفحات', `سيُدمج ${files.length} ملف PDF في نهاية «${att.name || 'المستند'}». متابعة؟`, 'دمج');
      if (!ok) return;
      const fd = new FormData();
      Array.from(files).forEach(f => fd.append('merge_files', f));
      await this._run(`${this.base}/attachment/${att.id}/merge/`, fd, 'جارٍ الدمج…');
    }

    // رفع وإلحاق (تجهيز في المعاينة): يعيد استخدام أنبوب الإلحاق في ExtractionSmartSystem —
    // الصفحات تظهر مميَّزة بالمعاينة و«الحفظ» يثبّتها (لا التزام فوري)، اتّساقاً مع «مسح وإلحاق».
    async _uploadAndAppend() {
      if (!window.extractionSystem || !window.extractionSystem.appendUploadedFile) {
        this._toast('error', 'تعذّر بدء الإلحاق — أعد تحميل الصفحة');
        return;
      }
      const files = await this._pickFile('application/pdf,image/*', true);
      if (!files || !files.length) return;
      for (const f of Array.from(files)) {
        await window.extractionSystem.appendUploadedFile(f);
      }
    }

    async _removePages(att) {
      const pages = await this._prompt('حذف صفحات', 'حدّد الصفحات المراد حذفها (مثال: 1,3-5):', '1,3-5');
      if (!pages) return;
      const fd = new FormData(); fd.append('pages_to_remove', pages);
      await this._run(`${this.base}/attachment/${att.id}/remove-pages/`, fd, 'جارٍ حذف الصفحات…');
    }

    async _addAnnex() {
      const file = await this._pickFile('application/pdf,image/*', false);
      if (!file) return;
      const fd = new FormData(); fd.append('file', file);
      // إرفاق ملحق = إضافة مرفق جديد دون حذف الحالي (نقطة رفع الكتاب AJAX)
      await this._run(`${this.base}/${this.bookId}/`, fd, 'جارٍ الإرفاق…');
    }

    // ── منفّذ موحّد: POST + حالة انشغال + إشعار + تحديث ──────────────────────────
    async _run(url, formData, busyMsg) {
      if (this.busy) return;
      this.busy = true;
      this._overlay(busyMsg || 'جارٍ التنفيذ…');
      try {
        const r = await fetch(url, {
          method: 'POST',
          headers: { 'X-CSRFToken': csrf(), 'X-Requested-With': 'XMLHttpRequest' },
          body: formData,
        });
        let p = {};
        try { p = await r.json(); } catch (e) { /* قد لا تكون JSON */ }
        if (!r.ok || p.success === false) throw new Error(p.message || `خطأ ${r.status}`);
        this._toast('success', p.message || 'تمّت العملية');
        await this.refresh();
        if (this.onAfterMutate) { try { this.onAfterMutate(); } catch (_e) { /* تجاهل */ } }
      } catch (e) {
        this._toast('error', e.message || 'تعذّر إتمام العملية');
      } finally {
        this.busy = false;
        this._overlay(null);
      }
    }

    _overlay(msg) {
      let ov = this.root.querySelector('.docman-overlay');
      if (!msg) { if (ov) ov.remove(); return; }
      if (!ov) { ov = el('div', 'docman-overlay'); this.root.appendChild(ov); }
      ov.innerHTML = `<span class="spinner-border spinner-border-sm"></span> ${msg}`;
    }

    _toast(type, msg) {
      if (window.ToastCenter && window.ToastCenter.show) {
        window.ToastCenter.show(type === 'error' ? 'error' : type, msg);
        return;
      }
      const t = el('div', 'docman-toast docman-toast-' + type, { text: msg });
      this.root.appendChild(t);
      setTimeout(() => t.classList.add('show'), 10);
      setTimeout(() => { t.classList.remove('show'); setTimeout(() => t.remove(), 250); }, 3200);
    }

    // ── أدوات الإدخال (ملف / تأكيد / نصّ) — حوارات أنيقة داخل المكوّن ─────────────
    _pickFile(accept, multiple) {
      return new Promise(resolve => {
        const inp = el('input', null, { type: 'file', accept: accept, style: 'display:none' });
        if (multiple) inp.multiple = true;
        inp.addEventListener('change', () => { resolve(multiple ? inp.files : inp.files[0]); inp.remove(); });
        document.body.appendChild(inp);
        inp.click();
      });
    }

    _modal(title, bodyNode, confirmLabel, variant) {
      return new Promise(resolve => {
        const back = el('div', 'docman-modal-back');
        const box = el('div', 'docman-modal');
        const head = el('div', 'docman-modal-head', { text: title });
        const body = el('div', 'docman-modal-body');
        body.appendChild(bodyNode);
        const foot = el('div', 'docman-modal-foot');
        const cancel = el('button', 'docman-btn', { type: 'button', text: 'إلغاء' });
        const confirm = el('button', 'docman-btn docman-btn-' + (variant === 'danger' ? 'danger' : 'primary') + ' docman-btn-solid', { type: 'button', text: confirmLabel || 'تأكيد' });
        foot.appendChild(cancel); foot.appendChild(confirm);
        box.appendChild(head); box.appendChild(body); box.appendChild(foot);
        back.appendChild(box);
        const close = (val) => { back.classList.remove('show'); setTimeout(() => back.remove(), 200); resolve(val); };
        cancel.addEventListener('click', () => close(null));
        confirm.addEventListener('click', () => close(box._value !== undefined ? box._value : true));
        back.addEventListener('click', e => { if (e.target === back) close(null); });
        document.body.appendChild(back);
        requestAnimationFrame(() => back.classList.add('show'));
        box._confirmBtn = confirm;
        this._activeBox = box;
      });
    }

    _confirm(title, message, confirmLabel, variant) {
      return this._modal(title, el('div', 'docman-modal-msg', { text: message }), confirmLabel, variant);
    }

    _prompt(title, message, placeholder) {
      const wrap = el('div');
      wrap.appendChild(el('div', 'docman-modal-msg', { text: message }));
      const input = el('input', 'docman-input', { type: 'text', placeholder: placeholder || '' });
      wrap.appendChild(input);
      const pr = this._modal(title, wrap, 'تنفيذ');
      // اربط قيمة الإدخال بزر التأكيد
      const box = this._activeBox;
      const sync = () => { box._value = input.value.trim() || null; };
      input.addEventListener('input', sync);
      input.addEventListener('keydown', e => { if (e.key === 'Enter') { sync(); box._confirmBtn.click(); } });
      setTimeout(() => input.focus(), 50);
      return pr;
    }
  }

  window.DocumentManager = DocumentManager;
})();
