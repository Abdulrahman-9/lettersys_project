/* Type-to-search for desk select lists (Tom Select 2.6.2, vendored locally). */
(function () {
  'use strict';
  if (typeof window.TomSelect !== 'function') return;

  document.querySelectorAll('select[data-desk-search]').forEach(function (select) {
    if (select.tomselect) return;
    var emptyOption = select.querySelector('option[value=""]');
    new window.TomSelect(select, {
      allowEmptyOption: true,
      create: false,
      maxOptions: null,
      placeholder: emptyOption ? emptyOption.textContent.trim() : 'اكتب للبحث…',
      searchField: ['text'],
      sortField: [{ field: '$order' }, { field: '$score' }],
      controlInput: '<input type="text" autocomplete="off" size="1" aria-label="اكتب للبحث">',
      render: {
        no_results: function () {
          return '<div class="no-results">لا توجد نتيجة مطابقة لما كتبته.</div>';
        }
      }
    });
  });
})();
