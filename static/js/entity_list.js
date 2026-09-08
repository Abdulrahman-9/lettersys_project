/* =====================================================
   صفحة الجهات — تبديل العرض + التحديد الجماعي + دمج المحدد
   مستخرج من entity_list.html. البحث وفلتر اللغة server-side.
   ===================================================== */
(function () {
  'use strict';

  const tableView   = document.getElementById('entitiesTableView');
  const cardsView   = document.getElementById('entitiesGrid');
  const tableToggle = document.getElementById('viewToggleTable');
  const cardsToggle = document.getElementById('viewToggleCards');
  const deleteBtn   = document.getElementById('deleteSelectedBtn');
  const selectedCountSpan = document.getElementById('selectedCount');
  const selectAllRows = document.getElementById('selectAllRows');
  const mergeBtn    = document.getElementById('mergeSelectedBtn');
  const mergeCountSpan = document.getElementById('mergeCount');
  const kindMoveGroup = document.getElementById('kindMoveGroup');

  // ── تبديل العرض (جدول / بطاقات) ──
  function setView(mode) {
    if (!tableView || !cardsView) return;
    const cards = mode === 'cards';
    tableView.classList.toggle('d-none', cards);
    cardsView.classList.toggle('d-none', !cards);
    tableToggle?.classList.toggle('active', !cards);
    cardsToggle?.classList.toggle('active', cards);
    // عطّل صناديق التحديد في العرض المخفي حتى لا تُرسَل قيم مكرّرة عند الإرسال
    const activeRoot = cards ? cardsView : tableView;
    const hiddenRoot = cards ? tableView : cardsView;
    activeRoot?.querySelectorAll('.row-check').forEach(cb => { cb.disabled = false; });
    hiddenRoot?.querySelectorAll('.row-check').forEach(cb => { cb.disabled = true; cb.checked = false; });
    try { localStorage.setItem('entitiesViewMode', mode); } catch (_) {}
    refreshSelection();
  }
  tableToggle?.addEventListener('click', () => setView('table'));
  cardsToggle?.addEventListener('click', () => setView('cards'));

  let savedMode = 'table';
  try { savedMode = localStorage.getItem('entitiesViewMode') || 'table'; } catch (_) {}
  setView(savedMode);

  // ── تحديد الصفوف + إبراز أزرار الإجراء الجماعي ──
  function refreshSelection() {
    document.querySelectorAll('.entities-table tbody tr.entity-item').forEach(tr => {
      const cb = tr.querySelector('.row-check');
      tr.classList.toggle('is-selected', !!(cb && cb.checked));
    });
    const checked = document.querySelectorAll(
      '.entities-table .row-check:checked, #entitiesGrid .row-check:checked'
    ).length;
    if (selectedCountSpan) selectedCountSpan.textContent = checked;
    if (deleteBtn) deleteBtn.style.display = checked > 0 ? 'inline-block' : 'none';
    // زر "دمج المحدد" — يلزمه جهتان على الأقل
    if (mergeBtn) mergeBtn.style.display = checked >= 2 ? 'inline-block' : 'none';
    if (mergeCountSpan) mergeCountSpan.textContent = checked;
    // نقلُ التبويب — واحدةٌ تكفي، بخلاف الدمج الذي يلزمه اثنتان.
    if (kindMoveGroup) kindMoveGroup.style.display = checked > 0 ? 'inline-flex' : 'none';
  }
  document.addEventListener('change', e => {
    if (e.target && e.target.classList && e.target.classList.contains('row-check')) {
      refreshSelection();
    }
  });
  selectAllRows?.addEventListener('change', () => {
    tableView?.querySelectorAll('tbody .row-check').forEach(cb => {
      if (cb.closest('tr.entity-item')) cb.checked = selectAllRows.checked;
    });
    refreshSelection();
  });

  // ── "دمج المحدد": ينقل الجهات المحدّدة إلى صفحة الدمج كعنقود يدوي ──
  mergeBtn?.addEventListener('click', () => {
    const ids = [...document.querySelectorAll(
      '.entities-table .row-check:checked, #entitiesGrid .row-check:checked'
    )].map(cb => cb.value);
    if (ids.length < 2) {
      alert('اختر جهتين على الأقل للدمج.');
      return;
    }
    const url = mergeBtn.dataset.mergeUrl || '';
    window.location.href = url + '?ids=' + ids.join(',');
  });

  // ── تأكيد تعطيل الجهة (نموذج فردي) ──
  document.querySelectorAll('form.entity-delete-form').forEach(form => {
    form.addEventListener('submit', ev => {
      const name = form.dataset.entityName || 'هذه الجهة';
      if (!confirm(`تعطيل جهة ${name}؟ ستُخفى من القوائم مع الحفاظ على سجلّها.`)) {
        ev.preventDefault();
      }
    });
  });
})();
