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

  // ملاحظة: رسم الصف (KIND_ICONS/STATUS_ICONS/esc/fmtDate/buildRow) أُزيل —
  // الصفوف تُصيَّر خادمياً من book_unified_row.html وتصل عبر data.rows_html (#13).

  // ─── Render table body ────────────────────────────────────────────────────────
  // الصفوف تُصيَّر خادمياً من نفس قالب الرسم الأولي (book_unified_row.html) وتُرسَل في
  // rows_html — مصدر حقيقة واحد للصف بدل إعادة بنائه هنا، فلا يتباعد المساران (#13).
  function renderTable(books, rowsHtml) {
    const tbody = document.getElementById('bookTableBody');
    if (!tbody) return;

    if (!books || books.length === 0) {
      tbody.innerHTML = `<tr class="empty-row">
        <td colspan="9" class="text-center py-5">
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
      tbody.innerHTML = rowsHtml || '';
      // Re-attach tooltips if Bootstrap is available
      if (window.bootstrap) {
        tbody.querySelectorAll('[data-bs-toggle="tooltip"]').forEach(el =>
          new window.bootstrap.Tooltip(el, { trigger: 'hover' })
        );
      }
      // Status toggle + delete handlers are managed via delegated listeners in book_unified_api.js
    }
  }

  // ─── Search highlighting ──────────────────────────────────────────────────────
  // يلفّ مطابقات نص البحث داخل خلايا الرقم/العنوان/الجهة بـ <mark> ويبرز الصف.
  // يعمل على نصوص DOM الموجودة فعلاً (آمن من XSS — لا HTML من المستخدم).
  // خلايا الأرقام (تظليل أزرق) مقابل خلايا النصّ (تظليل كهرماني) — لونان مختلفان.
  const HL_NUM_SELECTOR = '.col-our-number, .col-sender-number';
  const HL_TEXT_SELECTOR = '.col-title, .col-entity';

  // تطبيع عربي 1:1 — يجب أن يبقى الطول مطابقاً حرفاً بحرف، لأن الفهارس المحسوبة
  // على النصّ المُطبَّع تُستعمَل لتقطيع النصّ **الأصلي**. لذا لا نستدعي
  // toLowerCase() على النصّ كلّه: بعض الحروف تتمدّد (مثل 'İ' → حرفان) فتنزاح
  // كل الفهارس بعدها ويُبتَر ذيل النصّ من الصفحة. نُصغّر حرفاً حرفاً ونتراجع
  // عن أي تصغير يغيّر الطول.
  function _foldAr(s) {
    s = s || '';
    let out = '';
    for (let i = 0; i < s.length; i++) {
      const ch = s[i];
      let low = ch.toLowerCase();
      if (low.length !== 1) low = ch;
      switch (low) {
        case 'إ': case 'أ': case 'آ': low = 'ا'; break;
        case 'ؤ': low = 'و'; break;
        case 'ئ': case 'ى': low = 'ي'; break;
        case 'ة': low = 'ه'; break;
        default: break;
      }
      out += low;
    }
    return out;
  }

  function _highlightTextNode(node, tokens, cls) {
    const text = node.nodeValue;
    const folded = _foldAr(text);
    // حارس دفاعي: لو انكسر تعادل الطول يوماً، لا نلمس الـDOM أصلاً.
    if (folded.length !== text.length) return false;
    const ranges = [];
    tokens.forEach(tok => {
      let idx = folded.indexOf(tok);
      while (idx !== -1) {
        ranges.push([idx, idx + tok.length]);
        idx = folded.indexOf(tok, idx + tok.length);
      }
    });
    if (!ranges.length) return false;
    // دمج النطاقات المتداخلة (كلمات متجاورة/متكرّرة)
    ranges.sort((a, b) => a[0] - b[0]);
    const merged = [];
    ranges.forEach(r => {
      const last = merged[merged.length - 1];
      if (last && r[0] <= last[1]) last[1] = Math.max(last[1], r[1]);
      else merged.push(r.slice());
    });
    const frag = document.createDocumentFragment();
    let pos = 0;
    merged.forEach(([s, e]) => {
      if (s > pos) frag.appendChild(document.createTextNode(text.slice(pos, s)));
      const mark = document.createElement('mark');
      mark.className = cls;
      mark.textContent = text.slice(s, e);   // نُبرز الأصل لا المُطبَّع
      frag.appendChild(mark);
      pos = e;
    });
    if (pos < text.length) frag.appendChild(document.createTextNode(text.slice(pos)));
    node.parentNode.replaceChild(frag, node);
    return true;
  }

  function _paintCells(row, selector, tokens, cls, state) {
    if (!tokens.length) return;
    row.querySelectorAll(selector).forEach(cell => {
      const walker = document.createTreeWalker(cell, NodeFilter.SHOW_TEXT);
      const nodes = [];
      while (walker.nextNode()) nodes.push(walker.currentNode);
      nodes.forEach(n => { if (_highlightTextNode(n, tokens, cls)) state.matched = true; });
    });
  }

  function highlightMatches(term) {
    const tbody = document.getElementById('bookTableBody');
    if (!tbody) return;

    // تنظيف إبراز الصفوف السابق (الـ <mark> يختفي تلقائياً عند إعادة بناء tbody)
    tbody.querySelectorAll('tr.book-row--match').forEach(r => r.classList.remove('book-row--match'));

    const clean = (term || '').trim();
    if (!clean) return;

    const isNumeric = /^\d+$/.test(clean);
    // الأرقام: كلمة واحدة. النصّ: كلمات مطبَّعة (≥ حرفين) لتظليل كلٍّ على حدة.
    const numTokens = [_foldAr(clean)];
    const textTokens = isNumeric
      ? [_foldAr(clean)]
      : clean.split(/\s+/).map(_foldAr).filter(t => t.length >= 2);

    tbody.querySelectorAll('tr.book-row').forEach(row => {
      const state = { matched: false };
      _paintCells(row, HL_NUM_SELECTOR, numTokens, 'search-hl-num', state);   // أزرق
      _paintCells(row, HL_TEXT_SELECTOR, textTokens, 'search-hl-text', state); // كهرماني
      if (state.matched) row.classList.add('book-row--match');
    });
  }

  // ─── توسيع الصفّ بالنقر لإظهار العنوان/الجهات كاملةً (مفوَّض، يتجاهل التفاعلي) ───
  if (!window.__bookRowExpandBound) {
    window.__bookRowExpandBound = true;
    document.addEventListener('click', function (e) {
      if (e.target.closest(
        'button, a, input, label, select, .status-badge, .act-btn, ' +
        '.row-checkbox, .col-select, .col-status, .col-actions'
      )) return;
      const row = e.target.closest('tr.book-row');
      if (row) row.classList.toggle('row-expanded');
    });
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
    // المعرّفات الحيّة فقط (book_unified_tabs.html + book_unified_filter_bar.html)
    // ومفاتيح get_counter_badges: all/incoming/outgoing/pending/due_today/overdue/archived
    const MAP = {
      'badge-incoming':       badges.incoming,
      'badge-outgoing':       badges.outgoing,
      'pill-count-pending':   badges.pending,
      'pill-count-due-today': badges.due_today,
      'pill-count-overdue':   badges.overdue,
      'pill-count-archived':  badges.archived,
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

      // تظليل مطابقات البحث في صفوف الجدول المُحمَّلة من الخادم (SSR)
      if (this.currentState.search) highlightMatches(this.currentState.search);

      // تمرير وإبراز الكتاب المطلوب من ودجة «آخر الكتب» (?focus=<id>)
      this._focusRequestedBook();
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

      // الجوال: بطاقات القائمة تُصيَّر خادمياً فقط (لا مسار AJAX لها) —
      // فنعتمد تنقّلاً كاملاً ليُعاد بناؤها بدل بقاء القائمة قديمة.
      if (window.matchMedia('(max-width: 991.98px)').matches) {
        window.location.href = newUrl;
        return;
      }

      this.isLoading = true;
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

        renderTable(data.books, data.rows_html);
        highlightMatches(this.currentState.search);
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

    // ─── تمرير + إبراز كتاب محدَّد قادم من ودجة «آخر الكتب» (?focus=<id>) ─────────
    _focusRequestedBook() {
      const raw = new URLSearchParams(window.location.search).get('focus');
      const id = parseInt(raw, 10);
      if (!id) return;
      const tbody = document.getElementById('bookTableBody');
      const row = tbody && tbody.querySelector(`tr.book-row[data-book-id="${id}"]`);
      if (!row) return;
      row.scrollIntoView({ block: 'center', behavior: 'smooth' });
      row.classList.add('book-row--focused');
      setTimeout(() => { row.classList.remove('book-row--focused'); }, 2600);
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
