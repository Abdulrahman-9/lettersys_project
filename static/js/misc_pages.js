/* صفحاتُ وحدة «misc» على الهويّة v2 (11-19).
 *
 * ١. تغييرُ كلمة المرور (#pwForm) — لمساتٌ تمنع الخطأ قبل أن يقع، على نهج صفحة الدخول (login.js):
 *    • زرُّ إظهارٍ لكلّ حقل (aria-pressed واسمٌ ثابت كما في أنماط APG)، ويعود كلُّ حقلٍ مخفيّاً قبل
 *      الإرسال فلا يحفظ المتصفّحُ كلمةَ مرورٍ في سجلّ حقول النصّ.
 *    • تنبيهُ Caps Lock ولوحةِ المفاتيح العربيّة تحت الحقل.
 *    • شرطُ الطول يُعلَّم وأنت تكتب، والتطابقُ يُقال حين يكتمل التأكيد أو يغادره المؤشّر.
 *    • «جارٍ الحفظ…» يمنع النقرَ المزدوج، ويعود الزرُّ مع الرجوع بزرّ المتصفّح (bfcache).
 *    لا شيءَ هنا يمنع الإرسال: الخادمُ يحكم (novalidate) ورسائلُه تحت حقولها.
 * ٢. «العودة» ([data-error-back] في 403/404، و[data-back] في «إلغاء») إلى الصفحة الداخليّة السابقة
 *    إن وُجدت — وإلّا بقي الرابطُ على الرئيسة؛ و«الرئيسة» ([data-home-alt]) تظهر حين يُستعمل المُحيل.
 */
(function () {
  'use strict';

  var form = document.getElementById('pwForm');
  if (!form) return;

  var ARABIC = /[؀-ۿ]/;
  var fields = Array.prototype.slice.call(form.querySelectorAll('input[type="password"]'));
  var capsOn = false;

  function eyeFor(input) {
    return form.querySelector('.misc-eye[aria-controls="' + input.id + '"]');
  }

  function setShown(input, shown) {
    input.type = shown ? 'text' : 'password';
    var eye = eyeFor(input);
    if (!eye) return;
    eye.setAttribute('aria-pressed', shown ? 'true' : 'false');
    var icon = eye.querySelector('i');
    if (icon) icon.className = 'bi ' + (shown ? 'bi-eye-slash' : 'bi-eye');
  }

  function showHint(input) {
    var box = document.getElementById(input.getAttribute('data-keyhint'));
    if (!box) return;
    var text = '';
    if (capsOn) text = 'مفتاحُ الأحرف الكبيرة (Caps Lock) مفعّل.';
    else if (ARABIC.test(input.value)) text = 'لوحةُ المفاتيح على العربيّة — كلماتُ المرور عادةً بالإنكليزيّة.';
    var span = box.querySelector('span');
    if (span && span.textContent !== text) span.textContent = text;
    box.hidden = !text;
  }

  fields.forEach(function (input) {
    var eye = eyeFor(input);
    if (eye) {
      eye.addEventListener('click', function () {
        setShown(input, input.type === 'password');
        input.focus({ preventScroll: true });
      });
    }
    // Caps Lock يُقرأ من أحداث المفاتيح وحدها؛ والعربيّةُ من القيمة (لصقٌ أو إكمالٌ بلا مفاتيح أيضاً)
    ['keydown', 'keyup'].forEach(function (type) {
      input.addEventListener(type, function (event) {
        if (event.getModifierState) capsOn = event.getModifierState('CapsLock');
        showHint(input);
      });
    });
    input.addEventListener('input', function () { showHint(input); });
  });

  var newPass = document.getElementById('id_new_password1');
  var confirmPass = document.getElementById('id_new_password2');
  var rule = document.getElementById('pwRuleLen');
  var match = document.getElementById('pwMatch');

  function updateRule() {
    if (!rule || !newPass) return;
    var min = parseInt(newPass.getAttribute('minlength'), 10) || 1;
    var met = newPass.value.length >= min;
    rule.classList.toggle('is-met', met);
    var icon = rule.querySelector('i');
    if (icon) icon.className = 'bi ' + (met ? 'bi-check-circle-fill' : 'bi-circle');
    var state = rule.querySelector('[data-rule-state]');
    if (state) state.textContent = met ? ' — متحقّق' : '';
  }

  function updateMatch(finished) {
    if (!match || !newPass || !confirmPass) return;
    var a = newPass.value;
    var b = confirmPass.value;
    // لا حكمَ والتأكيدُ فارغ أو ما زال أقصرَ من الجديدة وأنت تكتب
    if (!b || (!finished && b.length < a.length)) {
      match.hidden = true;
      return;
    }
    var ok = a === b;
    match.classList.toggle('is-ok', ok);
    match.classList.toggle('is-bad', !ok);
    match.querySelector('i').className = 'bi ' + (ok ? 'bi-check-circle-fill' : 'bi-x-circle-fill');
    match.querySelector('span').textContent = ok ? 'الكلمتان متطابقتان.' : 'الكلمتان غير متطابقتين.';
    match.hidden = false;
  }

  if (newPass) newPass.addEventListener('input', function () { updateRule(); updateMatch(false); });
  if (confirmPass) {
    confirmPass.addEventListener('input', function () { updateMatch(false); });
    confirmPass.addEventListener('blur', function () { updateMatch(true); });
  }

  var submit = document.getElementById('pwSubmit');
  form.addEventListener('submit', function () {
    fields.forEach(function (input) { setShown(input, false); });
    if (!submit) return;
    submit.classList.add('is-busy');
    submit.setAttribute('aria-busy', 'true');
    submit.disabled = true;
  });

  window.addEventListener('pageshow', function () {
    if (!submit) return;
    submit.classList.remove('is-busy');
    submit.removeAttribute('aria-busy');
    submit.disabled = false;
  });
})();

(function () {
  'use strict';

  var links = document.querySelectorAll('[data-error-back], [data-back]');
  if (!links.length) return;
  var target = null;
  try {
    var ref = new URL(document.referrer);
    if (ref.origin === window.location.origin && ref.pathname !== window.location.pathname
        && ref.pathname.indexOf('/login') !== 0) {
      target = ref.href;
    }
  } catch (e) { /* لا مُحيل: يبقى الرابطُ على الرئيسة */ }
  if (!target) return;
  Array.prototype.forEach.call(links, function (a) { a.setAttribute('href', target); });
  var home = document.querySelector('[data-home-alt]');
  if (home) home.hidden = false;
})();
