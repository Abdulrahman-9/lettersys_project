/**
 * =====================================================
 * Book Unified - True AJAX Tab Switching & Filtering
 * تحديث جزئي حقيقي: يُعيد بناء الجدول من JSON بدون reload
 * =====================================================
 */

(function () {
  'use strict';

  // ─── الثوابت ─────────────────────────────────────────────────────────────────
  const _pageEl = document.getElementById('bookUnifiedPage');
  const API_URL = (_pageEl && _pageEl.dataset.ajaxDataUrl) || '/books/api/unified/data/';

  const KIND_ICONS = {
    outgoing_internal: '<i class="bi bi-box-arrow-up kind-icon kind-icon-outgoing"></i>',
    outgoing_external: '<i class="bi bi-box-arrow-up kind-icon kind-icon-outgoing"></i>',
    incoming_internal: '<i class="bi bi-box-arrow-in-down kind-icon kind-icon-incoming"></i>',
    incoming_external: '<i class="bi bi-box-arrow-in-down kind-icon kind-icon-incoming"></i>',
  };

  const STATUS_ICONS = {
    pending:  '<i class="bi bi-hourglass-split"></i>',
    hold:     '<i class="bi bi-pause-circle"></i>',
    done:     '<i class="bi bi-check-circle-fill"></i>',
    archived: '<i class="bi bi-archive"></i>',
  };

  // ─── Helper: XSS-safe ────────────────────────────────────────────────────────
  function esc(str) {
    const d = document.createElement('div');
    d.appendChild(document.createTextNode(str == null ? '' : String(str)));
    return d.innerHTML;
  }

  // ─── Helper: ISO date → dd-mm-yyyy ──────────────────────────────────────────
  function fmtDate(iso) {
    if (!iso) return '—';
    const p = String(iso).split('-');
    if (p.length !== 3) return esc(iso);
    return esc(p[2] + '/' + p[1] + '/' + p[0]);
  }

  // ─── Build one table row from a book JSON object ─────────────────────────────
  function buildRow(book) {
    const ts = book.time_state || 'normal';
    let rowCls = 'book-row ';
    if (book.status === 'done' || book.status === 'archived') rowCls += 'book-row-done';
    else if (ts === 'danger')  rowCls += 'book-row-overdue';
    else if (ts === 'today')   rowCls += 'book-row-today';
    else if (ts === 'future')  rowCls += 'book-row-upcoming';
    else                       rowCls += 'book-row-normal';

    const isIncoming = book.kind && book.kind.startsWith('incoming');
    const kindIcon = KIND_ICONS[book.kind] || (isIncoming
      ? '<i class="bi bi-box-arrow-in-down kind-icon kind-icon-incoming"></i>'
      : '<i class="bi bi-box-arrow-up kind-icon kind-icon-outgoing"></i>');

    const senderInline = isIncoming
      ? `<div class="sender-number-line" title="رقم الكتاب لدى الجهة المرسلة (رقم صادرهم)">
           <span class="num-tag num-tag-sender">رقمهم</span>
           ${book.sender_number
             ? `<span class="sender-number-value">${esc(book.sender_number)}</span>`
             : `<span class="sender-number-empty" title="لم يُستورد من النظام القديم — أضِفه عند التعديل">لم يُسجَّل</span>`}
         </div>`
      : '';

    let ourNumHtml;
    if (book.our_number_is_numberless) {
      ourNumHtml = `<span class="book-number-numberless" title="كتاب داخلي بلا رقم رسمي (استثناء)">بلا رقم</span>`;
    } else if (!book.our_number) {
      ourNumHtml = `<span class="book-number-missing" title="لا يوجد رقم قيد — يحتاج تخصيص">غير مسجل</span>`;
    } else if (book.our_number_year) {
      ourNumHtml = `<span class="book-number-text"><span class="num-sequence">${esc(book.our_number_sequence)}</span><span class="num-year">/${esc(book.our_number_year)}</span></span>`;
    } else {
      ourNumHtml = `<span class="book-number-text">${esc(book.our_number)}</span>`;
    }
    const ourTitle = book.legacy_number
      ? `رقم القيد لدينا: ${esc(book.our_number)} — الأصل: ${esc(book.legacy_number)}`
      : `رقم القيد لدينا: ${esc(book.our_number)}`;

    let dueHtml = '';
    if (book.status === 'pending' || book.status === 'hold') {
      if (ts === 'danger')
        dueHtml = `<div class="due-indicator due-overdue"><i class="bi bi-exclamation-triangle-fill"></i><span>متأخر (${esc(book.delay_days)} يوم)</span></div>`;
      else if (ts === 'today')
        dueHtml = `<div class="due-indicator due-today"><i class="bi bi-calendar-event-fill"></i><span>مستحق اليوم</span></div>`;
      else if (ts === 'future' && book.delay_days <= 3)
        dueHtml = `<div class="due-indicator due-followup"><i class="bi bi-clock-fill"></i><span>بعد ${esc(book.delay_days)} يوم</span></div>`;
    }

    const statusIcon = STATUS_ICONS[book.status] || '';
    const statusBadge = `<button type="button" class="status-badge status-badge-btn badge-status-${esc(book.status)}"
      data-book-id="${book.id}"
      data-current-status="${esc(book.status)}"
      data-status-url="/books/api/book/${book.id}/status-inline/"
      title="انقر لتغيير الحالة">${statusIcon}${esc(book.status_label)}<i class="bi bi-chevron-down status-badge-caret"></i></button>`;

    const kindMiniBadge = isIncoming
      ? `<span class="kind-mini-badge badge-kind-incoming">${esc(book.kind_label)}</span>`
      : `<span class="kind-mini-badge badge-kind-outgoing">${esc(book.kind_label)}</span>`;

    const attachBadge = book.attachment_url
      ? `<span class="title-attach-badge" title="يوجد مرفق"><i class="bi bi-paperclip"></i></span>` : '';

    const issuingHtml = (book.issuing_entities || []).map(e =>
      `<span class="entity-name" title="${esc(e.name)}">${esc(e.name)}</span>`
    ).join('<span class="text-muted mx-1">·</span>') || '<span class="entity-name text-muted">—</span>';

    const recvHtml = (book.receiving_entities || []).length
      ? `<div class="entity-secondary"><i class="bi bi-arrow-left-right"></i>${
          book.receiving_entities.map(e =>
            `<span class="entity-name-secondary" title="${esc(e.name)}">${esc(e.name)}</span>`
          ).join('<span class="text-muted mx-1">·</span>')
        }</div>` : '';

    return `
<tr class="${rowCls}"
    data-book-id="${book.id}"
    data-book-number="${esc(book.our_number)}"
    data-status="${esc(book.status)}"
    data-kind="${esc(book.kind)}">

  <td class="col-select">
    <input class="form-check-input row-checkbox" type="checkbox"
           value="${book.id}" data-book-id="${book.id}"
           aria-label="تحديد كتاب رقم ${esc(book.our_number)}">
  </td>

  <td class="col-our-number">
    <div class="our-number-cell">
      <div class="our-number-line" title="${esc(ourTitle)}">
        ${kindIcon}
        <span class="num-tag num-tag-ours">قيدنا</span>
        ${ourNumHtml}
      </div>
      ${senderInline}
    </div>
  </td>

  <td class="col-date">${
    isIncoming
      ? `<div class="date-stack">
           <div class="date-line date-line-ours" title="تاريخ استلامنا للكتاب">
             <span class="num-tag num-tag-ours">استلام</span>
             <span class="date-val">${fmtDate(book.date)}</span>
           </div>
           ${book.sender_date_display
             ? `<div class="date-line date-line-sender" title="تاريخ إرسال الجهة المرسلة">
                  <span class="num-tag num-tag-sender">إرسال</span>
                  <span class="date-val-sm">${esc(book.sender_date_display)}</span>
                </div>`
             : ''}
         </div>`
      : `<span class="date-val" title="تاريخ إصدار الكتاب">${fmtDate(book.date)}</span>`
  }</td>

  <td class="col-title">
    <div class="book-title-cell">
      <div class="book-title-text" title="${esc(book.title)}">${esc(book.title) || 'بدون عنوان'}</div>
      <div class="title-meta-row">${kindMiniBadge}${attachBadge}</div>
    </div>
  </td>

  <td class="col-entity">
    <div class="book-entity-cell">
      <div class="entity-primary"><i class="bi bi-building entity-icon"></i>${issuingHtml}</div>
      ${recvHtml}
    </div>
  </td>

  <td class="col-status">
    <div class="status-cell">${statusBadge}${dueHtml}</div>
  </td>

  <td class="col-actions">
    <div class="action-row">
      ${book.attachment_url
        ? `<button class="act-btn act-preview btn-preview"
             data-book-id="${book.id}"
             data-book-attachment="${esc(book.attachment_url)}"
             data-book-title="${esc(book.title || 'بدون عنوان')}"
             title="معاينة المستند">
             <i class="bi bi-file-earmark-pdf"></i>
           </button>`
        : `<button class="act-btn act-disabled" disabled title="لا يوجد مرفق">
             <i class="bi bi-file-earmark"></i>
           </button>`
      }
      <a href="${book.urls.detail}" class="act-btn act-view" title="عرض التفاصيل"><i class="bi bi-eye"></i></a>
      <a href="${book.urls.edit}" class="act-btn act-edit" title="تعديل"><i class="bi bi-pencil"></i></a>
      <button class="act-btn act-delete btn-delete"
        data-book-id="${book.id}" data-book-number="${esc(book.our_number)}"
        data-delete-url="/books/api/book/${book.id}/delete/"
        title="نقل إلى السلة">
        <i class="bi bi-trash"></i>
      </button>
    </div>
  </td>
</tr>`;
  }

  // ─── Render table body ────────────────────────────────────────────────────────
  function renderTable(books) {
    const tbody = document.getElementById('bookTableBody');
    if (!tbody) return;

    if (!books || books.length === 0) {
      tbody.innerHTML = `<tr class="empty-row">
        <td colspan="7" class="text-center py-5">
          <div class="empty-table-message">
            <i class="bi bi-inbox empty-icon"></i>
            <p class="empty-text">لا توجد كتب مطابقة</p>
            <button class="btn btn-sm btn-outline-primary" onclick="window.bookAjaxManager && window.bookAjaxManager.clearAllFilters();">
              إعادة تعيين الفلاتر
            </button>
          </div>
        </td>
      </tr>`;
    } else {
      tbody.innerHTML = books.map(buildRow).join('');
      // Re-attach tooltips if Bootstrap is available
      if (window.bootstrap) {
        tbody.querySelectorAll('[data-bs-toggle="tooltip"]').forEach(el =>
          new window.bootstrap.Tooltip(el, { trigger: 'hover' })
        );
      }
      // Status toggle + delete handlers are managed via delegated listeners in book_unified_api.js
    }
  }

  // ─── Render pagination ────────────────────────────────────────────────────────
  function renderPagination(p, currentParams) {
    const fromEl  = document.getElementById('paginationFrom');
    const toEl    = document.getElementById('paginationTo');
    const totalEl = document.getElementById('paginationTotal');
    const listEl  = document.getElementById('paginationList');

    const from = p.count === 0 ? 0 : ((p.current - 1) * p.per_page) + 1;
    const to   = Math.min(from + p.per_page - 1, p.count);

    if (fromEl)  fromEl.textContent  = from;
    if (toEl)    toEl.textContent    = to;
    if (totalEl) totalEl.textContent = p.count;

    if (!listEl) return;
    const prevParams = Object.assign({}, currentParams, { page: p.current - 1 });
    const nextParams = Object.assign({}, currentParams, { page: p.current + 1 });

    const buildLink = (params, label) => {
      const qs = new URLSearchParams(params).toString();
      return `<a class="page-link" href="?${qs}" data-page="${params.page}">${label}</a>`;
    };

    listEl.innerHTML = `
      <li class="page-item ${!p.has_prev ? 'disabled' : ''}">
        ${p.has_prev ? buildLink(prevParams, 'السابق') : '<span class="page-link">السابق</span>'}
      </li>
      <li class="page-item active"><span class="page-link">${p.current}</span></li>
      <li class="page-item ${!p.has_next ? 'disabled' : ''}">
        ${p.has_next ? buildLink(nextParams, 'التالي') : '<span class="page-link">التالي</span>'}
      </li>`;

    // Intercept pagination link clicks → AJAX
    listEl.querySelectorAll('a.page-link[data-page]').forEach(a => {
      a.addEventListener('click', e => {
        e.preventDefault();
        const mgr = window.bookAjaxManager;
        if (mgr) {
          mgr.currentState.page = parseInt(a.dataset.page) || 1;
          mgr.updateUrlAndLoadData();
        }
      });
    });
  }

  // ─── Render active filter badge ───────────────────────────────────────────────
  function renderFilterBadges(af) {
    const badge = document.getElementById('activeFiltersBadge');
    if (!badge) return;
    if (af && af.count > 0) {
      badge.textContent = af.count;
      badge.style.display = 'inline-flex';
      badge.title = af.labels ? af.labels.join(' | ') : '';
    } else {
      badge.style.display = 'none';
      badge.textContent = '';
    }
  }

  // ─── Render tab/pill badge counts from server response ───────────────────────
  function renderBadgeCounts(badges) {
    if (!badges) return;
    const MAP = {
      'badge-all':      badges.all,
      'badge-incoming': badges.incoming,
      'badge-outgoing': badges.outgoing,
      'badge-overdue':  badges.overdue,
      'badge-today':    badges.today,
      'badge-upcoming': badges.upcoming,
      'badge-done':     badges.done,
      'badge-archived': badges.archived,
      'pill-count-overdue':  badges.overdue,
      'pill-count-today':    badges.today,
      'pill-count-upcoming': badges.upcoming,
      'pill-count-done':     badges.done,
      'pill-count-archived': badges.archived,
      'quickStatsTotal':     badges.all,
    };
    for (const [id, val] of Object.entries(MAP)) {
      const el = document.getElementById(id);
      if (el && val !== undefined) el.textContent = val;
    }
  }

  // ─── CSRF helper ─────────────────────────────────────────────────────────────
  function getCsrf() {
    const el = document.querySelector('[name=csrfmiddlewaretoken]');
    if (el) return el.value;
    const m = document.cookie.match(/csrftoken=([^;]+)/);
    return m ? m[1] : '';
  }

  // ─── Main class ──────────────────────────────────────────────────────────────
  class BookUnifiedAjaxManager {
    constructor() {
      this.isLoading = false;
      this.currentState = {
        tab: 'incoming',
        search: '',
        dateFrom: '',
        dateTo: '',
        entityId: '',
        status: '',
        due_status: '',
        page: 1,
        sort: '-date'
      };
      this.init();
    }

    init() {
      this.attachTabHandlers();
      this.attachPillHandlers();
      this.attachSearchHandler();
      this.attachFilterHandlers();
      this.attachSortHandlers();
      this.restoreStateFromUrl();
      this.applyTheme();
      this.attachAdvancedToggle();

      // Update search results display on page load
      setTimeout(() => { this.updateSearchResultsDisplay(); }, 100);
    }

    // ─── Theme switching: incoming → blue, outgoing → yellow ───────────────────
    applyTheme() {
      const direction = (this.currentState.tab || 'incoming').startsWith('outgoing')
        ? 'outgoing' : 'incoming';
      const page = document.getElementById('bookUnifiedPage');
      if (page) page.dataset.theme = direction;
    }

    // ─── Advanced filter panel toggle ──────────────────────────────────────────
    attachAdvancedToggle() {
      const btn = document.getElementById('filterToggleBtn');
      const panel = document.getElementById('advancedFilters');
      if (!btn || !panel) return;
      btn.addEventListener('click', () => {
        const isOpen = panel.classList.toggle('open');
        btn.setAttribute('aria-expanded', isOpen);
      });
    }

    // ─── 1. Main tab handlers (وارد / صادر) ────────────────────────────────────
    attachTabHandlers() {
      const self = this;
      const mainTabs = document.querySelectorAll('.tab-main');

      function getMainDirection(tabValue) {
        if (!tabValue) return 'incoming';
        if (tabValue.startsWith('outgoing')) return 'outgoing';
        return 'incoming';
      }

      mainTabs.forEach(btn => {
        btn.addEventListener('click', e => {
          e.preventDefault();
          e.stopPropagation();
          const direction = btn.dataset.tab;
          mainTabs.forEach(t => { t.classList.remove('active'); t.setAttribute('aria-selected', 'false'); });
          btn.classList.add('active');
          btn.setAttribute('aria-selected', 'true');

          self.currentState.tab = direction;
          self.currentState.page = 1;
          self.applyTheme();
          self.updateUrlAndLoadData();
        });
      });

      // Scope sub-toggle (داخلي / خارجي / الكل) — refines current direction
      document.querySelectorAll('.fb-scope-btn[data-scope]').forEach(btn => {
        btn.addEventListener('click', e => {
          e.preventDefault();
          const scope = btn.dataset.scope;
          const dir   = getMainDirection(self.currentState.tab);
          const newTab = scope === 'all' ? dir : `${dir}_${scope}`;
          document.querySelectorAll('.fb-scope-btn').forEach(b => b.classList.remove('active'));
          btn.classList.add('active');
          self.currentState.tab  = newTab;
          self.currentState.page = 1;
          self.updateUrlAndLoadData();
        });
      });
    }

    // ─── 2. Status pill handlers (متأخر/اليوم/منجز/مؤرشف/الكل) ────────────────
    attachPillHandlers() {
      const self = this;
      document.querySelectorAll('.fb-pill[data-filter]').forEach(pill => {
        pill.addEventListener('click', e => {
          e.preventDefault();
          const filter = pill.dataset.filter || 'all';
          // Highlight active pill
          document.querySelectorAll('.fb-pill').forEach(p => p.classList.remove('active'));
          pill.classList.add('active');

          // Map pill → due_status أو status — orthogonal to tab
          if (filter === 'all') {
            self.currentState.due_status = '';
            self.currentState.status = '';
          } else if (filter === 'overdue' || filter === 'today' || filter === 'upcoming') {
            self.currentState.due_status = filter;
            self.currentState.status = '';
          } else if (filter === 'done' || filter === 'archived') {
            self.currentState.status = filter;
            self.currentState.due_status = '';
          }
          self.currentState.page = 1;
          self.updateUrlAndLoadData();
        });
      });
    }

    // ─── 3. Search handler ─────────────────────────────────────────────────────
    attachSearchHandler() {
      const self = this;
      const searchInput = document.querySelector('#liveSearchInput');
      const searchButton = document.querySelector('#searchSubmitBtn');
      const clearButton  = document.querySelector('#clearSearchBtn');
      const searchLoading = document.querySelector('#searchLoading');

      if (!searchInput) return;

      let searchTimeout;

      searchInput.addEventListener('input', e => {
        const txt = e.target.value.trim();
        if (clearButton) clearButton.style.display = txt ? 'inline-flex' : 'none';
        if (searchLoading) searchLoading.style.display = txt ? 'flex' : 'none';

        clearTimeout(searchTimeout);
        searchTimeout = setTimeout(() => {
          if (searchLoading) searchLoading.style.display = 'none';
          self.currentState.search = txt;
          self.currentState.page   = 1;
          self.updateUrlAndLoadData();
        }, 300);
      });

      searchInput.addEventListener('keydown', e => {
        if (e.key === 'Enter') {
          e.preventDefault();
          clearTimeout(searchTimeout);
          self.currentState.search = searchInput.value.trim();
          self.currentState.page   = 1;
          self.updateUrlAndLoadData();
        }
        if (e.key === 'Escape') {
          e.preventDefault();
          searchInput.value = '';
          self.currentState.search = '';
          self.currentState.page   = 1;
          if (clearButton)  clearButton.style.display  = 'none';
          if (searchLoading) searchLoading.style.display = 'none';
          self.updateUrlAndLoadData();
        }
      });

      if (searchButton) {
        searchButton.addEventListener('click', e => {
          e.preventDefault();
          clearTimeout(searchTimeout);
          self.currentState.search = searchInput.value.trim();
          self.currentState.page   = 1;
          self.updateUrlAndLoadData();
        });
      }

      if (clearButton) {
        clearButton.addEventListener('click', e => {
          e.preventDefault();
          e.stopPropagation();
          searchInput.value = '';
          searchInput.focus();
          self.currentState.search = '';
          self.currentState.page   = 1;
          clearButton.style.display = 'none';
          if (searchLoading) searchLoading.style.display = 'none';
          self.updateUrlAndLoadData();
        });
      }

      // Restore from URL
      const urlParams = new URLSearchParams(window.location.search);
      const qParam = urlParams.get('q');
      if (qParam) {
        searchInput.value = qParam;
        this.currentState.search = qParam;
        if (clearButton) clearButton.style.display = 'inline-flex';
        this.updateSearchResultsDisplay();
      }
    }

    updateSearchResultsDisplay() {
      const infoEl  = document.querySelector('#searchResultsInfo');
      const countEl = document.querySelector('#searchResultsCount');
      const totalEl = document.querySelector('#paginationTotal');

      if (infoEl && countEl && totalEl) {
        const count = parseInt(totalEl.textContent) || 0;
        countEl.textContent = count;
        infoEl.style.display = (this.currentState.search && count >= 0) ? 'flex' : 'none';
      }
    }

    // ─── 4. Filter handlers ────────────────────────────────────────────────────
    attachFilterHandlers() {
      const self = this;
      const map = {
        '[name="date_from"]': 'dateFrom',
        '[name="date_to"]':   'dateTo',
        '[name="entity_id"]': 'entityId',
        '[name="status"]':    'status',
      };
      for (const [selector, key] of Object.entries(map)) {
        const el = document.querySelector(selector);
        if (el) {
          el.addEventListener('change', e => {
            self.currentState[key] = e.target.value;
            self.currentState.page = 1;
            self.updateUrlAndLoadData();
          });
        }
      }
    }

    // ─── 5. Sort handlers ──────────────────────────────────────────────────────
    attachSortHandlers() {
      const self = this;
      document.querySelectorAll('[data-sort], .sortable-header').forEach(link => {
        link.addEventListener('click', e => {
          e.preventDefault();
          const field = link.dataset.sort || '-date';
          // toggle asc/desc
          self.currentState.sort = self.currentState.sort === field ? `-${field}` : field;
          self.currentState.page = 1;
          self.updateUrlAndLoadData();
        });
      });
    }

    // ─── 6. Core: fetch + re-render ────────────────────────────────────────────
    async updateUrlAndLoadData() {
      if (this.isLoading) return;
      this.isLoading = true;

      const params = {};
      if (this.currentState.tab && this.currentState.tab !== 'incoming') params.tab = this.currentState.tab;
      if (this.currentState.search)    params.q          = this.currentState.search;
      if (this.currentState.dateFrom)  params.date_from  = this.currentState.dateFrom;
      if (this.currentState.dateTo)    params.date_to    = this.currentState.dateTo;
      if (this.currentState.entityId)  params.entity_id  = this.currentState.entityId;
      if (this.currentState.status)    params.status     = this.currentState.status;
      if (this.currentState.due_status) params.due_status = this.currentState.due_status;
      if (this.currentState.page > 1)  params.page       = this.currentState.page;
      if (this.currentState.sort && this.currentState.sort !== '-date') params.sort = this.currentState.sort;

      // Update browser URL without reload
      const qs = new URLSearchParams(params).toString();
      const newUrl = qs ? `${window.location.pathname}?${qs}` : window.location.pathname;
      history.pushState(params, '', newUrl);

      // Show loading overlay
      const overlay = document.getElementById('loadingOverlay');
      const skeleton = document.getElementById('tableSkeleton');
      if (overlay)  overlay.style.display  = 'flex';
      if (skeleton) skeleton.style.display = 'block';

      try {
        const apiQs = new URLSearchParams(params).toString();
        const res = await fetch(`${API_URL}${apiQs ? '?' + apiQs : ''}`, {
          headers: { 'X-Requested-With': 'XMLHttpRequest' }
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();

        renderTable(data.books);
        renderPagination(data.pagination, params);
        renderFilterBadges(data.active_filters);
        renderBadgeCounts(data.badges);
        this.updateSearchResultsDisplay();

        // Empty state visibility
        const emptyState = document.getElementById('emptyState');
        const tableSection = document.getElementById('desktopTableContainer');
        if (emptyState && tableSection) {
          if (!data.books || data.books.length === 0) {
            emptyState.style.display = 'block';
            tableSection.style.display = 'none';
          } else {
            emptyState.style.display = 'none';
            tableSection.style.display = '';
          }
        }

        // Announce to screen readers
        const live = document.getElementById('bookUnifiedLiveRegion');
        if (live) {
          live.textContent = `تم تحميل ${data.pagination.count} كتاب`;
          setTimeout(() => { live.textContent = ''; }, 1000);
        }

      } catch (err) {
        console.error('[BookAjax] fetch error:', err);
        // Fallback: full page reload
        window.location.href = newUrl;
      } finally {
        this.isLoading = false;
        if (overlay)  overlay.style.display  = 'none';
        if (skeleton) skeleton.style.display = 'none';
      }
    }

    // ─── 7. Restore state from URL ─────────────────────────────────────────────
    restoreStateFromUrl() {
      const p = new URLSearchParams(window.location.search);
      this.currentState.tab        = p.get('tab')        || 'incoming';
      this.currentState.search     = p.get('q')          || '';
      this.currentState.dateFrom   = p.get('date_from')  || '';
      this.currentState.dateTo     = p.get('date_to')    || '';
      this.currentState.entityId   = p.get('entity_id')  || '';
      this.currentState.status     = p.get('status')     || '';
      this.currentState.due_status = p.get('due_status') || '';
      this.currentState.page       = parseInt(p.get('page')) || 1;
      this.currentState.sort       = p.get('sort')       || '-date';
      this.applyTheme();
    }

    clearAllFilters() {
      this.currentState = { tab: 'incoming', search: '', dateFrom: '', dateTo: '',
                            entityId: '', status: '', due_status: '', page: 1, sort: '-date' };
      history.pushState({}, '', window.location.pathname);
      this.updateUrlAndLoadData();
    }
  }

  // ─── Init ─────────────────────────────────────────────────────────────────────
  document.addEventListener('DOMContentLoaded', () => {
    window.bookAjaxManager = new BookUnifiedAjaxManager();
  });

  // Handle browser back/forward
  window.addEventListener('popstate', () => {
    if (window.bookAjaxManager) {
      window.bookAjaxManager.restoreStateFromUrl();
      window.bookAjaxManager.updateUrlAndLoadData();
    }
  });

  window.BookUnifiedAjaxManager = BookUnifiedAjaxManager;
})();
