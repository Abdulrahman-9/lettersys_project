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

  // ─── Build one table row from a book JSON object ─────────────────────────────
  function buildRow(book) {
    const ts = book.time_state || 'normal';
    let rowCls = 'book-row ';
    if (book.status === 'done')       rowCls += 'book-row-done';
    else if (ts === 'danger')         rowCls += 'book-row-overdue';
    else if (ts === 'today')          rowCls += 'book-row-today';
    else if (ts === 'future')         rowCls += 'book-row-upcoming';
    else                              rowCls += 'book-row-normal';

    const isIncoming = book.kind && book.kind.startsWith('incoming');
    const kindIcon = KIND_ICONS[book.kind] || (isIncoming
      ? '<i class="bi bi-box-arrow-in-down kind-icon kind-icon-incoming"></i>'
      : '<i class="bi bi-box-arrow-up kind-icon kind-icon-outgoing"></i>');

    // due indicator
    let dueHtml = '';
    if (book.status !== 'done') {
      if (ts === 'danger')
        dueHtml = `<div class="due-indicator due-overdue"><i class="bi bi-exclamation-triangle-fill"></i><span>متأخر ${esc(book.delay_days)} يوم</span></div>`;
      else if (ts === 'today')
        dueHtml = `<div class="due-indicator due-today"><i class="bi bi-calendar-event-fill"></i><span>مستحق اليوم</span></div>`;
      else if (ts === 'future' && book.delay_days <= 3)
        dueHtml = `<div class="due-indicator due-soon"><i class="bi bi-clock-fill"></i><span>بعد ${esc(book.delay_days)} يوم</span></div>`;
    }

    // kind badge (new column — embedded in title cell for backwards compat with CSS)
    const kindBadge = isIncoming
      ? `<span class="status-badge badge-kind-incoming">${kindIcon}${esc(book.kind_label)}</span>`
      : `<span class="status-badge badge-kind-outgoing">${kindIcon}${esc(book.kind_label)}</span>`;

    // status badge
    const statusIcon = STATUS_ICONS[book.status] || '';
    const statusBadge = `<span class="status-badge badge-status-${esc(book.status)}">${statusIcon}${esc(book.status_label)}</span>`;

    // entities
    const issuingHtml = (book.issuing_entities || []).map(e =>
      `<span class="entity-name" title="${esc(e.name)}">${esc(e.name)}</span>`
    ).join('<span class="text-muted mx-1">·</span>') || '<span class="entity-name text-muted">—</span>';

    const recvHtml = (book.receiving_entities || []).length
      ? `<div class="entity-secondary"><i class="bi bi-arrow-left-right"></i>${
          (book.receiving_entities).map(e =>
            `<span class="entity-name-secondary" title="${esc(e.name)}">${esc(e.name)}</span>`
          ).join('<span class="text-muted mx-1">·</span>')
        }</div>`
      : '';

    // status toggle buttons
    const toggleBtns = ['pending', 'hold', 'done'].map(s =>
      `<button type="button" class="btn btn-toggle-status ${book.status === s ? 'active' : ''}"
         data-book-id="${book.id}" data-status="${s}"
         data-status-url="/books/api/book/${book.id}/status-inline/"
         title="${s === 'pending' ? 'قيد المتابعة' : s === 'hold' ? 'معلق' : 'منجز'}"
       >${STATUS_ICONS[s]}</button>`
    ).join('');

    return `
<tr class="${rowCls}"
    data-book-id="${book.id}"
    data-book-number="${esc(book.our_number)}"
    data-status="${esc(book.status)}"
    data-kind="${esc(book.kind)}">

  <td class="col-select">
    <div class="form-check">
      <input class="form-check-input row-checkbox" type="checkbox"
             value="${book.id}" data-book-id="${book.id}"
             aria-label="تحديد كتاب رقم ${esc(book.our_number)}">
    </div>
  </td>

  <td class="col-number">
    <div class="book-number-cell">
      <div class="book-number-main">
        <a href="#" class="book-number-link" data-book-id="${book.id}"
           data-bs-toggle="tooltip" title="نقر للمعاينة السريعة">
          ${kindIcon}
          <span class="book-number-text">${esc(book.our_number) || '-'}</span>
        </a>
      </div>
      ${dueHtml}
      <div class="book-date-registered"><i class="bi bi-calendar3"></i>${esc(book.date)}</div>
    </div>
  </td>

  <td class="col-title">
    <div class="book-title-cell">
      <div class="book-title-text" title="${esc(book.title)}">${esc(book.title) || 'بدون عنوان'}</div>
      <div class="book-status-badges">
        ${kindBadge}
        ${statusBadge}
      </div>
    </div>
  </td>

  <td class="col-entity">
    <div class="book-entity-cell">
      <div class="entity-primary"><i class="bi bi-building entity-icon"></i>${issuingHtml}</div>
      ${recvHtml}
    </div>
  </td>

  <td class="col-actions">
    <div class="book-actions-cell">
      <div class="action-icons-row">
        <a href="${book.urls.detail}" class="action-icon-btn btn-view" title="عرض التفاصيل"
           aria-label="عرض تفاصيل كتاب ${esc(book.our_number)}"><i class="bi bi-eye"></i></a>
        <a href="${book.urls.edit}" class="action-icon-btn btn-edit" title="تعديل"
           aria-label="تعديل كتاب ${esc(book.our_number)}"><i class="bi bi-pencil"></i></a>
        <button class="action-icon-btn btn-delete"
          data-book-id="${book.id}" data-book-number="${esc(book.our_number)}"
          data-delete-url="/books/api/book/${book.id}/delete/"
          title="نقل إلى السلة" aria-label="حذف كتاب ${esc(book.our_number)}">
          <i class="bi bi-trash"></i>
        </button>
      </div>
      <div class="status-toggle-row">
        <div class="btn-group btn-group-sm status-toggle-group" role="group"
             aria-label="تحديث حالة الكتاب">
          ${toggleBtns}
        </div>
      </div>
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
        <td colspan="5" class="text-center py-5">
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
      // Re-attach status toggle handlers
      tbody.querySelectorAll('.btn-toggle-status').forEach(btn => {
        btn.addEventListener('click', () => {
          const url = btn.dataset.statusUrl;
          const status = btn.dataset.status;
          const bookId = btn.dataset.bookId;
          if (!url) return;
          fetch(url, {
            method: 'POST',
            headers: { 'X-CSRFToken': getCsrf(), 'Content-Type': 'application/json' },
            body: JSON.stringify({ status })
          }).then(r => r.json()).then(data => {
            if (data.success || data.status) {
              // update row data-status + toggle active class
              const row = document.querySelector(`tr[data-book-id="${bookId}"]`);
              if (row) {
                row.dataset.status = status;
                row.querySelectorAll('.btn-toggle-status').forEach(b =>
                  b.classList.toggle('active', b.dataset.status === status)
                );
              }
            }
          }).catch(() => {});
        });
      });
      // Delete button handlers
      tbody.querySelectorAll('.btn-delete').forEach(btn => {
        btn.addEventListener('click', () => {
          if (window.bookUnifiedApp && window.bookUnifiedApp.handleDeleteBook) {
            window.bookUnifiedApp.handleDeleteBook(btn);
          }
        });
      });
      // Preview (number link) handlers
      tbody.querySelectorAll('.book-number-link').forEach(link => {
        link.addEventListener('click', e => {
          e.preventDefault();
          if (window.bookUnifiedApp && window.bookUnifiedApp.showPreview) {
            window.bookUnifiedApp.showPreview(link.dataset.bookId);
          }
        });
      });
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
        tab: 'all',
        search: '',
        dateFrom: '',
        dateTo: '',
        entityId: '',
        status: '',
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

      // Update search results display on page load
      setTimeout(() => { this.updateSearchResultsDisplay(); }, 100);
    }

    // ─── 1. Tab handlers ───────────────────────────────────────────────────────
    attachTabHandlers() {
      const self = this;
      const tabs = document.querySelectorAll('.tab-btn');

      tabs.forEach(btn => {
        btn.addEventListener('click', e => {
          e.preventDefault();
          e.stopPropagation();

          const tabName = btn.dataset.tab || 'all';
          tabs.forEach(t => { t.classList.remove('active'); t.setAttribute('aria-selected', 'false'); });
          btn.classList.add('active');
          btn.setAttribute('aria-selected', 'true');

          self.currentState.tab  = tabName;
          self.currentState.page = 1;
          self.updateUrlAndLoadData();
        });
      });

      // Sub-menu items (incoming_internal, outgoing_external …)
      document.querySelectorAll('.tab-sub-item[data-sub-kind]').forEach(item => {
        item.addEventListener('click', e => {
          e.preventDefault();
          e.stopPropagation();
          const kind = item.dataset.subKind;
          self.currentState.tab  = kind;
          self.currentState.page = 1;
          // Highlight parent tab
          const parentBtn = item.closest('.tab-dropdown-wrapper')?.querySelector('.tab-btn');
          if (parentBtn) {
            tabs.forEach(t => { t.classList.remove('active'); t.setAttribute('aria-selected', 'false'); });
            parentBtn.classList.add('active');
            parentBtn.setAttribute('aria-selected', 'true');
          }
          self.updateUrlAndLoadData();
        });
      });
    }

    // ─── 2. Pill handlers ──────────────────────────────────────────────────────
    attachPillHandlers() {
      const self = this;
      document.querySelectorAll('.pill-filter, [data-filter]').forEach(pill => {
        pill.addEventListener('click', e => {
          e.preventDefault();
          const filter = pill.dataset.filter || 'all';
          if (['all', 'done', 'overdue', 'today', 'upcoming'].includes(filter)) {
            self.currentState.tab = filter;
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
      if (this.currentState.tab && this.currentState.tab !== 'all') params.tab = this.currentState.tab;
      if (this.currentState.search)   params.q          = this.currentState.search;
      if (this.currentState.dateFrom) params.date_from  = this.currentState.dateFrom;
      if (this.currentState.dateTo)   params.date_to    = this.currentState.dateTo;
      if (this.currentState.entityId) params.entity_id  = this.currentState.entityId;
      if (this.currentState.status)   params.status     = this.currentState.status;
      if (this.currentState.page > 1) params.page       = this.currentState.page;
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
      this.currentState.tab       = p.get('tab')       || 'all';
      this.currentState.search    = p.get('q')         || '';
      this.currentState.dateFrom  = p.get('date_from') || '';
      this.currentState.dateTo    = p.get('date_to')   || '';
      this.currentState.entityId  = p.get('entity_id') || '';
      this.currentState.status    = p.get('status')    || '';
      this.currentState.page      = parseInt(p.get('page')) || 1;
      this.currentState.sort      = p.get('sort')      || '-date';
    }

    clearAllFilters() {
      this.currentState = { tab: 'all', search: '', dateFrom: '', dateTo: '',
                            entityId: '', status: '', page: 1, sort: '-date' };
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
