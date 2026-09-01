/* ══════════════════════════════════════════════════════════════════
   منتقي الربط — يبحث ثمّ يثبّت ضلعاً اختاره إنسان.

   **لا ربطَ بلا نقرة**: زرُّ «اربط» معطَّلٌ حتى يُختار صفٌّ بعينه. ربطٌ خاطئ
   يُقفل التزاماً لم يُنجَز — فالتأكيدُ شرطٌ لا تزيين.

   والبحثُ **مُمهَل** (debounce): كلُّ حرفٍ استعلامٌ على 13 ألف كتاب.
   ══════════════════════════════════════════════════════════════════ */
(function () {
  'use strict';

  var DEBOUNCE_MS = 260;
  var MIN_QUERY = 2;

  function el(id) { return document.getElementById(id); }

  function csrf() {
    var m = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
    return m ? decodeURIComponent(m[1]) : '';
  }

  function LinkPicker(root) {
    this.bookId  = root.getAttribute('data-book-id');
    this.query   = el('lpQuery');
    this.results = el('lpResults');
    this.chosen  = el('lpChosen');
    this.label   = el('lpChosenLabel');
    this.submit  = el('lpSubmit');
    this.relation = el('lpRelation');
    this.note    = el('lpNote');
    this.picked  = null;
    this.timer   = null;

    if (!this.query || !this.results || !this.submit) return;
    this._bind();
  }

  LinkPicker.prototype._bind = function () {
    var self = this;

    this.query.addEventListener('input', function () {
      clearTimeout(self.timer);
      self.timer = setTimeout(function () { self.search(); }, DEBOUNCE_MS);
    });

    this.results.addEventListener('click', function (e) {
      var row = e.target.closest('[data-book]');
      if (row) self.choose(row);
    });

    this.submit.addEventListener('click', function () { self.save(); });
  };

  LinkPicker.prototype.search = function () {
    var q = (this.query.value || '').trim();
    if (q.length < MIN_QUERY) {
      this.results.innerHTML =
        '<p class="text-muted mb-0" style="font-size:.82rem">اكتب حرفين على الأقلّ.</p>';
      return;
    }

    var self = this;
    var url = '/books/api/links/picker/?q=' + encodeURIComponent(q) +
              '&exclude=' + encodeURIComponent(this.bookId);

    fetch(url, { headers: { 'X-Requested-With': 'XMLHttpRequest' } })
      .then(function (r) { return r.json(); })
      .then(function (data) { self.render(data.results || []); })
      .catch(function () {
        /* رسالةٌ صادقة: صفرُ نتائجَ ليس نجاحاً، والعطلُ ليس «لا يوجد». */
        self.results.innerHTML =
          '<p class="text-danger mb-0" style="font-size:.82rem">تعذّر البحث — أعد المحاولة.</p>';
      });
  };

  LinkPicker.prototype.render = function (rows) {
    if (!rows.length) {
      this.results.innerHTML =
        '<p class="text-muted mb-0" style="font-size:.82rem">لا كتابَ يطابق — جرّب الرقم وحده.</p>';
      return;
    }

    var html = rows.map(function (r) {
      var meta = [r.date, r.department || r.entity, r.kind_label]
        .filter(Boolean).join(' · ');
      return '<div class="lc-result" role="option" tabindex="0"' +
             ' data-book="' + r.id + '"' +
             ' data-label="' + escapeAttr(r.number + ' — ' + r.title) + '">' +
             '<span class="lc-result-num">' + escapeHtml(r.number) + '</span>' +
             '<span class="lc-result-title">' + escapeHtml(r.title) + '</span>' +
             '<span class="lc-result-meta">' + escapeHtml(meta) + '</span>' +
             '</div>';
    }).join('');
    this.results.innerHTML = html;
  };

  LinkPicker.prototype.choose = function (row) {
    this.results.querySelectorAll('.lc-result').forEach(function (r) {
      r.classList.remove('is-active');
      r.setAttribute('aria-selected', 'false');
    });
    row.classList.add('is-active');
    row.setAttribute('aria-selected', 'true');

    this.picked = row.getAttribute('data-book');
    if (this.chosen) this.chosen.hidden = false;
    if (this.label) this.label.textContent = 'المختار: ' + row.getAttribute('data-label');
    this.submit.disabled = false;
  };

  LinkPicker.prototype.save = function () {
    if (!this.picked) return;
    var self = this;
    this.submit.disabled = true;

    fetch('/books/api/book/' + this.bookId + '/links/add/', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf() },
      body: JSON.stringify({
        to_book: this.picked,
        relation: this.relation ? this.relation.value : '',
        note: this.note ? this.note.value : ''
      })
    })
      .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, d: d }; }); })
      .then(function (res) {
        if (res.ok && res.d.success) {
          window.location.reload();
          return;
        }
        /* الرسالةُ من الخادم بنصّها — لا تُخترع في JS. */
        self.fail(res.d.message || 'تعذّر الربط.');
      })
      .catch(function () { self.fail('تعذّر الاتّصال بالخادم.'); });
  };

  LinkPicker.prototype.fail = function (message) {
    this.submit.disabled = false;
    if (this.label) {
      this.label.textContent = message;
      this.label.classList.add('text-danger');
    }
  };

  function escapeHtml(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  function escapeAttr(s) { return escapeHtml(s); }

  document.addEventListener('DOMContentLoaded', function () {
    var host = document.querySelector('[data-book-id]');
    if (host && document.getElementById('linkPickerModal')) new LinkPicker(host);
  });
})();
