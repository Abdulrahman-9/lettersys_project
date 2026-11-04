/* حقول التاريخ في صفحة الإدخال بصيغة يوم/شهر/سنة (04/11/2026).
 *
 * `type=date` يتبع لغة المتصفّح فيعرض عند كثيرين شهر/يوم/سنة، ولا تغيّره سمةٌ في الصفحة. فيصير
 * الحقل نصّيّاً في مظهره، وتبقى خاصّية `value` بصيغة ISO لكلّ كود الصفحة والخادم كما كانت.
 * بلا JS يبقى الحقل `type=date` كما في القالب.
 */
(function () {
  'use strict';

  const FIELD_IDS = ['date', 'senderDate', 'dueDate'];
  const nativeValue = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value');
  const pad = (n) => String(n).padStart(2, '0');

  function dmyToIso(text) {
    const m = /^\s*(\d{1,2})\s*[/\-.]\s*(\d{1,2})\s*[/\-.]\s*(\d{4})\s*$/.exec(text || '');
    if (!m) return '';
    const day = Number(m[1]), month = Number(m[2]), year = Number(m[3]);
    const probe = new Date(Date.UTC(year, month - 1, day));
    if (probe.getUTCMonth() !== month - 1 || probe.getUTCDate() !== day) return '';   // 31/02 ليس تاريخاً
    return `${year}-${pad(month)}-${pad(day)}`;
  }

  function isoToDmy(iso) {
    const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(iso || ''));
    return m ? `${m[3]}/${m[2]}/${m[1]}` : '';
  }

  /** يضيف الفاصل أثناء الكتابة: 04 ⟵ 04/ ، و04/11 ⟵ 04/11/ ، ولصقُ 04112026 ⟵ 04/11/2026. */
  function maskTyping(text) {
    const value = text.replace(/[-.\s]/g, '/').replace(/[^\d/]/g, '').replace(/\/{2,}/g, '/');
    if (/^\d{8}$/.test(value)) return `${value.slice(0, 2)}/${value.slice(2, 4)}/${value.slice(4)}`;
    return /^\d{2}$/.test(value) || /^\d{1,2}\/\d{2}$/.test(value) ? `${value}/` : value;
  }

  function enhance(input) {
    const initial = nativeValue.get.call(input);
    input.type = 'text';
    input.dir = 'ltr';
    input.inputMode = 'numeric';
    input.autocomplete = 'off';
    input.maxLength = 10;
    input.placeholder = 'يوم/شهر/سنة';
    Object.defineProperty(input, 'value', {
      configurable: true,
      get() { return dmyToIso(nativeValue.get.call(input)); },
      set(iso) { nativeValue.set.call(input, isoToDmy(iso)); input.classList.remove('date-dmy-invalid'); },
    });
    input.value = initial;

    input.addEventListener('input', (e) => {
      if (String(e.inputType || '').startsWith('delete') || !e.inputType) return;
      nativeValue.set.call(input, maskTyping(nativeValue.get.call(input)));
      input.classList.remove('date-dmy-invalid');
    });
    input.addEventListener('blur', () => {
      const raw = nativeValue.get.call(input).trim();
      const iso = dmyToIso(raw);
      if (iso) nativeValue.set.call(input, isoToDmy(iso));
      input.classList.toggle('date-dmy-invalid', !!raw && !iso);
    });

    const wrap = document.createElement('span');
    wrap.className = 'date-dmy';
    input.parentNode.insertBefore(wrap, input);
    wrap.appendChild(input);

    const picker = document.createElement('input');
    picker.type = 'date';
    picker.className = 'date-dmy__native';
    picker.tabIndex = -1;
    picker.setAttribute('aria-hidden', 'true');
    picker.addEventListener('change', () => {
      input.value = picker.value;
      input.dispatchEvent(new Event('input', { bubbles: true }));
      input.dispatchEvent(new Event('change', { bubbles: true }));
      input.focus();
    });

    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'date-dmy__pick';
    button.tabIndex = -1;
    button.title = 'اختيار من التقويم';
    button.setAttribute('aria-label', 'اختيار من التقويم');
    button.innerHTML = '<i class="bi bi-calendar3" aria-hidden="true"></i>';
    button.addEventListener('click', () => {
      picker.value = input.value;
      try { picker.showPicker(); } catch (_) { input.focus(); }
    });
    wrap.append(button, picker);
  }

  FIELD_IDS.forEach((id) => {
    const input = document.getElementById(id);
    if (input) enhance(input);
  });
})();
