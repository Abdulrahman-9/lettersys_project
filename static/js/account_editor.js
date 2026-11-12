/* محرّرُ الحساب (ج، الشريحة 2): حوارُ تغيير الدور يسمّي ما يُفقد ويبقى ويُلغى — المعاينةُ من الخادم
 * (system_admin._account_context ⟵ permission_service.role_change_preview) — وتأكيدُ تغيير القسم. */
(function () {
  'use strict';

  var page = document.getElementById('aePage');
  // بعد الإنشاء أو كلمة المرور يبقى العنوانُ عنوانَ الـPOST؛ عنوانُ الحساب يمنع إعادةَ الإرسال عند التحديث.
  if (page && page.dataset.url && window.history.replaceState) window.history.replaceState(null, '', page.dataset.url);
  var dataNode = document.getElementById('aePreviews');
  var previews = {};
  try { previews = JSON.parse(dataNode ? dataNode.textContent : '{}') || {}; } catch (e) { previews = {}; }

  function paragraph(label, items) {
    if (!items || !items.length) return null;
    var p = document.createElement('p');
    var b = document.createElement('b');
    b.textContent = label + ' ';
    p.appendChild(b);
    p.appendChild(document.createTextNode(items.join('، ') + '.'));
    return p;
  }

  var roleSelect = document.getElementById('aeRole');
  var roleForm = document.getElementById('aeRoleForm');
  var dialog = document.getElementById('aeConfirm');
  if (roleSelect && roleForm && dialog && typeof dialog.showModal === 'function') {
    var restore = function () { roleSelect.value = roleSelect.dataset.current; };
    roleSelect.addEventListener('change', function () {
      var info = previews[roleSelect.value];
      if (!info) { restore(); return; }
      var name = page ? page.dataset.name : '';
      document.getElementById('aeConfirmTitle').textContent = 'تغيير دور ' + name + ' إلى ' + info.label;
      var body = document.getElementById('aeConfirmBody');
      body.replaceChildren();
      [paragraph('يفقد:', info.lose), paragraph('يبقى له:', info.keep),
       paragraph('يُلغى من الاستثناءات:', info.cancel)].forEach(function (p) { if (p) body.appendChild(p); });
      var note = document.createElement('p');
      note.textContent = 'ويُسجَّل ذلك في سجلّ الحركات.';
      body.appendChild(note);
      dialog.showModal();
    });
    document.getElementById('aeConfirmNo').addEventListener('click', function () { restore(); dialog.close(); });
    dialog.addEventListener('cancel', restore);
    document.getElementById('aeConfirmYes').addEventListener('click', function () {
      roleForm.querySelector('input[name="confirm"]').value = '1';
      roleForm.submit();
    });
  }

  var account = document.getElementById('aeAccount');
  var department = document.getElementById('aeDepartment');
  if (account && department) {
    account.addEventListener('submit', function (event) {
      if (department.value === department.dataset.initial || account.dataset.confirmed === '1') return;
      event.preventDefault();
      var count = Number(account.dataset.exceptions || 0);
      var message = 'تغيير القسم يحدّد ما يراه الحساب' +
        (count ? '، ويُلغي استثناءاته (' + count + ')' : '') + '. ويُسجَّل ذلك في سجلّ الحركات.';
      var ask = typeof window.confirmDelete === 'function'
        ? window.confirmDelete({ title: 'تغيير القسم', message: message, okText: 'غيّر القسم', danger: false })
        : Promise.resolve(window.confirm(message));
      ask.then(function (ok) {
        if (!ok) return;
        account.querySelector('input[name="confirm_department"]').value = '1';
        account.dataset.confirmed = '1';
        if (typeof account.requestSubmit === 'function') account.requestSubmit(); else account.submit();
      });
    });
  }
}());
