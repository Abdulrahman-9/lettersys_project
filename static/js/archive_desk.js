/*
 * طاولةُ الأرشفة — الحفظُ من صفّ الطابور مباشرةً.
 *
 * **لماذا الفعلُ هنا لا في صفحة الكتاب وحدها**: الأرشيفيُّ يمرّ على عشرات
 * الأوراق في الجلسة الواحدة. طاولةٌ تُريه العملَ وتُلزمه فتحَ كلّ كتابٍ ثمّ
 * العودةَ تُحوّل عملَ دقيقةٍ إلى عملِ ساعة — فتُهجَر، ويُهجَر الدورُ معها.
 *
 * **ولا منطقَ عملٍ هنا**: مَن يُؤرشف · متى يُرفض · ماذا يُكتب — كلُّه في
 * `core/archive_service.py`. وهذا يُرسل ويعرض ما يعود، ورسالةُ الخطأ تأتي
 * من الخادم بنصّها العربيّ فلا تُخترع هنا.
 */
(function () {
  'use strict';

  var board = document.querySelector('.queues-page');
  if (!board) return;

  function csrf() {
    var m = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
    if (m) return decodeURIComponent(m[1]);
    var input = document.querySelector('input[name=csrfmiddlewaretoken]');
    return input ? input.value : '';
  }

  function toast(message, ok) {
    if (window.ToastCenter && typeof window.ToastCenter.show === 'function') {
      window.ToastCenter.show(ok ? 'success' : 'error', message);
    }
  }

  function busy(button, on) {
    button.disabled = on;
    button.dataset.label = button.dataset.label || button.textContent;
    button.textContent = on ? 'جارٍ…' : button.dataset.label;
  }

  board.addEventListener('click', function (event) {
    var button = event.target.closest('[data-qb-act]');
    if (!button) return;
    event.preventDefault();

    var bookId = button.dataset.bookId;
    var label = button.dataset.bookLabel || '';
    // موضعُ الحفظ هو الشيءُ الوحيد الذي يُسأل عنه بعد سنة، فيُطلَب دائماً —
    // والإلغاءُ لا يُرسل طلباً فارغاً. والخادمُ يقبل الفراغَ ويُظهره في طابور
    // «حُفظ بلا موضع»، فالكاتبُ حرٌّ أن يمضي بلا رفٍّ ويعود إليه.
    var place = window.prompt('موضعُ حفظ الكتاب ' + label + ' (الرفّ/الصندوق):');
    if (place === null) return;

    busy(button, true);
    fetch('/books/api/book/' + bookId + '/archive/', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': csrf(),
        'X-Requested-With': 'XMLHttpRequest'
      },
      body: JSON.stringify({ place: place })
    }).then(function (res) {
      return res.json().catch(function () { return {}; }).then(function (data) {
        if (!res.ok || !data.success) {
          throw new Error(data.message || ('تعذّرت العمليّة (' + res.status + ')'));
        }
        return data;
      });
    }).then(function (data) {
      // الصفُّ يختفي من طابوره فور نجاحه — والعدّادُ يُنقص معه، وإلّا بدا
      // للكاتب أنّ شيئاً لم يحدث فأعاد الضغط.
      var row = button.closest('.qb-row');
      var card = button.closest('.qb-card');
      if (row) row.remove();
      var count = card && card.querySelector('.qb-count');
      if (count) {
        var left = Math.max(0, parseInt(count.textContent, 10) - 1);
        count.textContent = left;
        if (!left) count.removeAttribute('data-has');
      }
      toast(data.message, true);
    }).catch(function (err) {
      toast(err.message, false);
    }).finally(function () { busy(button, false); });
  });
})();
