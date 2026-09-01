/* ══════════════════════════════════════════════════════════════════
   منتقي أعضاء العنقود — بحثٌ فوق قائمةٍ طويلة.

   674 جهةً لا تُمسَح بالعين، والتمريرُ وحده يجعل تشكيلَ عنقودٍ عقوبة.
   فالبحثُ يُخفي غيرَ المطابق، **والمُحدَّدُ يبقى ظاهراً دائماً**: مَن يبحث
   عن عضوٍ جديد يجب أن يرى ما اختاره قبله وإلّا ظنّه ضاع.

   بلا إطارِ عمل ولا مكتبة — والقائمةُ في الـDOM أصلاً فالتصفيةُ إظهارٌ وإخفاء.
   ══════════════════════════════════════════════════════════════════ */
(function () {
  'use strict';

  function MemberPicker(root) {
    this.root    = root;
    this.search  = root.querySelector('[data-picker-search]');
    this.options = Array.prototype.slice.call(root.querySelectorAll('[data-picker-option]'));
    this.counter = root.querySelector('[data-picker-count]');
    if (!this.options.length) return;

    var self = this;
    if (this.search) {
      this.search.addEventListener('input', function () { self.filter(); });
    }
    root.addEventListener('change', function () { self.count(); });
    this.count();
  }

  MemberPicker.prototype.filter = function () {
    var q = (this.search.value || '').trim().toLowerCase();
    var shown = 0;

    this.options.forEach(function (opt) {
      var box = opt.querySelector('input');
      /* المُحدَّدُ لا يُخفى مهما كان البحث — وإلّا بدا أنّه أُلغي. */
      var keep = !q || (box && box.checked) ||
                 (opt.getAttribute('data-text') || '').indexOf(q) !== -1;
      opt.hidden = !keep;
      if (keep) shown++;
    });

    this.count(q ? shown : null);
  };

  MemberPicker.prototype.count = function (shown) {
    if (!this.counter) return;
    var picked = this.options.filter(function (o) {
      var b = o.querySelector('input');
      return b && b.checked;
    }).length;

    var text = picked ? ('اختير ' + picked) : 'لم يُختر عضوٌ بعد';
    if (typeof shown === 'number') text += ' · مطابقٌ للبحث ' + shown;
    this.counter.textContent = text;
  };

  document.addEventListener('DOMContentLoaded', function () {
    document.querySelectorAll('[data-member-picker]').forEach(function (root) {
      root.__memberPicker = new MemberPicker(root);
    });
  });
})();
