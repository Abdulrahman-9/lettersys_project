/* صفحة الدخول — لمساتٌ تمنع الأخطاء الشائعة قبل أن تقع.
 *
 * ١. إظهار/إخفاء كلمة المرور (زرٌّ حقيقيّ بـ aria-pressed؛ autocomplete باقٍ).
 * ٢. تنبيهٌ لطيفٌ إذا كان مفتاحُ الأحرف الكبيرة مفعّلاً أو لوحةُ المفاتيح على
 *    العربيّة — أكثرُ سببين لـ«كلمة المرور غير صحيحة» في مكتبٍ عربيّ.
 * ٣. حالةُ «جارٍ الدخول…» عند الإرسال تمنع النقرَ المزدوج، وتُعاد عند الرجوع
 *    بزرّ المتصفّح (bfcache يُبقي الزرّ معطَّلاً إن لم نُعِده).
 */
(function () {
  'use strict';

  var form = document.getElementById('loginForm');
  if (!form) return;

  var user = document.getElementById('id_username');
  var pass = document.getElementById('id_password');
  var eye = document.getElementById('loginEye');
  var submit = document.getElementById('loginSubmit');
  var ARABIC = /[؀-ۿ]/;

  if (eye && pass) {
    eye.addEventListener('click', function () {
      var show = pass.type === 'password';
      pass.type = show ? 'text' : 'password';
      var label = show ? 'إخفاء كلمة المرور' : 'إظهار كلمة المرور';
      eye.setAttribute('aria-pressed', show ? 'true' : 'false');
      eye.setAttribute('aria-label', label);
      eye.title = label;
      var icon = eye.querySelector('i');
      if (icon) icon.className = 'bi ' + (show ? 'bi-eye-slash' : 'bi-eye');
      pass.focus({ preventScroll: true });
    });
  }

  function hintFor(field) {
    var id = field.getAttribute('aria-describedby');
    return id ? document.getElementById(id) : null;
  }

  function showHint(field, text) {
    var box = hintFor(field);
    if (!box) return;
    var span = box.querySelector('span');
    if (!text) {
      box.hidden = true;
      if (span) span.textContent = '';
      return;
    }
    if (span && span.textContent !== text) span.textContent = text;
    box.hidden = false;
  }

  function check(event, field) {
    var caps = event.getModifierState && event.getModifierState('CapsLock');
    var arabic = ARABIC.test(field.value);
    var text = '';
    if (caps) text = 'مفتاحُ الأحرف الكبيرة (Caps Lock) مفعّل.';
    else if (arabic) text = 'لوحةُ المفاتيح على العربيّة — أسماءُ الدخول وكلماتُ المرور عادةً بالإنكليزيّة.';
    showHint(field, text);
  }

  [user, pass].forEach(function (field) {
    if (!field) return;
    // keyup يقرأ Caps Lock؛ و input يلتقط العربيّة حتّى حين يُدرَج النصّ بلا مفاتيح (لصقٌ أو إكمالٌ تلقائيّ)
    field.addEventListener('keyup', function (event) { check(event, field); });
    field.addEventListener('input', function (event) { check(event, field); });
  });

  form.addEventListener('submit', function () {
    // يصل الحدثُ بعد نجاح تحقّق المتصفّح (required) — فالإرسالُ ماضٍ فعلاً
    submit.classList.add('is-busy');
    submit.setAttribute('aria-busy', 'true');
    submit.disabled = true;
  });

  window.addEventListener('pageshow', function () {
    submit.classList.remove('is-busy');
    submit.removeAttribute('aria-busy');
    submit.disabled = false;
  });
})();
