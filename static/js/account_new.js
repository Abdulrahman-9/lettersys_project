/* حسابٌ جديد (ج، الشريحة 3): الأدوارُ تتبع القسمَ المختار (roles_for_department) والملخّصُ من مصفوفة الأدوار.
 * الخادمُ يعيد الفحصَ نفسَه عند الإنشاء (system_admin.system_account_new_view)؛ هذا عرضٌ لا حارس. */
(function () {
  'use strict';

  function readJson(id) {
    var node = document.getElementById(id);
    try { return JSON.parse(node ? node.textContent : '{}') || {}; } catch (e) { return {}; }
  }

  var meta = readJson('anRolesMeta');
  var deptRoles = readJson('anDeptRoles');
  var dept = document.getElementById('anDept');
  var choices = Array.prototype.slice.call(document.querySelectorAll('#anRoles .ae-choice'));
  var unitNote = document.getElementById('anUnitNote');
  var canNode = document.getElementById('anCan');
  var cannotNode = document.getElementById('anCannot');
  if (!dept || !choices.length) return;

  function checked() {
    return choices.map(function (c) { return c.querySelector('input'); })
      .filter(function (i) { return i.checked && !i.disabled; })[0] || null;
  }

  function summarise() {
    var input = checked();
    var role = input ? meta[input.value] : null;
    if (canNode) canNode.textContent = role && role.can.length ? role.can.join('، ') + '.' : '—';
    if (cannotNode) cannotNode.textContent = role && role.cannot.length ? role.cannot.join('، ') + '.' : '—';
  }

  function follow() {
    var info = deptRoles[dept.value] || { roles: [], register: true };
    choices.forEach(function (choice) {
      var input = choice.querySelector('input');
      var allowed = info.roles.indexOf(choice.dataset.role) !== -1;
      choice.hidden = !allowed;
      input.disabled = !allowed;
      if (!allowed) input.checked = false;
    });
    if (!checked()) {
      var first = choices.filter(function (c) { return !c.hidden; })[0];
      if (first) first.querySelector('input').checked = true;
    }
    if (unitNote) unitNote.hidden = info.register !== false;
    summarise();
  }

  dept.addEventListener('change', follow);
  choices.forEach(function (choice) { choice.querySelector('input').addEventListener('change', summarise); });
  follow();
})();
