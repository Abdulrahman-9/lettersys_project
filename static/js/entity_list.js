/* =====================================================
   صفحة الجهات — تبديل العرض + شريط التحديد + حواريّة «جهة جديدة»
   البحث والترتيب واللغة server-side؛ هنا ما لا يعيش إلّا في المتصفّح.
   ===================================================== */
(function () {
  'use strict';

  const tableView   = document.getElementById('entitiesTableView');
  const cardsView   = document.getElementById('entitiesGrid');
  const tableToggle = document.getElementById('viewToggleTable');
  const cardsToggle = document.getElementById('viewToggleCards');
  const bulkBar     = document.getElementById('entityBulkBar');
  const selectedCountEl = document.getElementById('selectedCount');
  const selectAllRows = document.getElementById('selectAllRows');
  const mergeBtn    = document.getElementById('mergeSelectedBtn');
  const mergeCountEl = document.getElementById('mergeCount');
  const kindMoveGroup = document.getElementById('kindMoveGroup');
  const clearBtn    = document.getElementById('clearSelectionBtn');

  const checkedBoxes = () => document.querySelectorAll(
    '.entities-table .row-check:checked, #entitiesGrid .row-check:checked'
  );

  // ── تبديل العرض (جدول / بطاقات) ──
  function setView(mode) {
    if (!tableView || !cardsView) return;
    const cards = mode === 'cards';
    tableView.classList.toggle('d-none', cards);
    cardsView.classList.toggle('d-none', !cards);
    if (tableToggle) { tableToggle.classList.toggle('active', !cards); tableToggle.setAttribute('aria-pressed', String(!cards)); }
    if (cardsToggle) { cardsToggle.classList.toggle('active', cards); cardsToggle.setAttribute('aria-pressed', String(cards)); }
    // عطّل صناديق التحديد في العرض المخفي حتى لا تُرسَل قيم مكرّرة عند الإرسال
    const activeRoot = cards ? cardsView : tableView;
    const hiddenRoot = cards ? tableView : cardsView;
    activeRoot.querySelectorAll('.row-check').forEach(cb => { cb.disabled = false; });
    hiddenRoot.querySelectorAll('.row-check').forEach(cb => { cb.disabled = true; cb.checked = false; });
    try { localStorage.setItem('entitiesViewMode', mode); } catch (_) {}
    refreshSelection();
  }
  tableToggle?.addEventListener('click', () => setView('table'));
  cardsToggle?.addEventListener('click', () => setView('cards'));

  // ── شريط التحديد: يظهر بالتحديد وحدَه ويلتصق بأسفل الشاشة ──
  function refreshSelection() {
    document.querySelectorAll('.entities-table tbody tr.entity-item').forEach(tr => {
      const cb = tr.querySelector('.row-check');
      tr.classList.toggle('is-selected', !!(cb && cb.checked));
    });
    const checked = checkedBoxes().length;
    if (selectedCountEl) selectedCountEl.textContent = checked;
    if (bulkBar) bulkBar.hidden = checked === 0;
    // الدمجُ يلزمه جهتان على الأقل؛ النقلُ والتعطيلُ تكفيهما واحدة
    if (mergeBtn) mergeBtn.hidden = checked < 2;
    if (mergeCountEl) mergeCountEl.textContent = checked;
    // التأكيدُ يسمّي العددَ والتبويب (تدقيقُ نيلسن D#13) — حواريّةُ data-confirm في app.js
    kindMoveGroup?.querySelectorAll('[data-kind-label]').forEach(btn => {
      btn.dataset.confirm = 'نقل ' + checked + ' جهةً إلى تبويب «' + btn.dataset.kindLabel + '»؟';
    });
    if (selectAllRows && tableView) {
      const rows = tableView.querySelectorAll('tbody tr.entity-item .row-check');
      const on = tableView.querySelectorAll('tbody tr.entity-item .row-check:checked').length;
      selectAllRows.checked = rows.length > 0 && on === rows.length;
      selectAllRows.indeterminate = on > 0 && on < rows.length;
    }
  }
  document.addEventListener('change', e => {
    if (e.target?.classList?.contains('row-check')) refreshSelection();
  });
  selectAllRows?.addEventListener('change', () => {
    tableView?.querySelectorAll('tbody tr.entity-item .row-check').forEach(cb => {
      cb.checked = selectAllRows.checked;
    });
    refreshSelection();
  });
  clearBtn?.addEventListener('click', () => {
    checkedBoxes().forEach(cb => { cb.checked = false; });
    refreshSelection();
  });

  // ── «دمج المحدد»: ينقل الجهات المحدّدة إلى صفحة الدمج كعنقود يدوي ──
  mergeBtn?.addEventListener('click', () => {
    const ids = [...checkedBoxes()].map(cb => cb.value);
    if (ids.length < 2) return;
    window.location.href = (mergeBtn.dataset.mergeUrl || '') + '?ids=' + ids.join(',');
  });

  let savedMode = 'table';
  try { savedMode = localStorage.getItem('entitiesViewMode') || 'table'; } catch (_) {}
  setView(savedMode);

  // ── الترتيبُ يُطبَّق باختياره (زرُّ «بحث» يبقى لمن بلا سكربت) ──
  document.querySelectorAll('select[data-autosubmit]').forEach(sel => {
    sel.addEventListener('change', () => sel.form?.requestSubmit ? sel.form.requestSubmit() : sel.form?.submit());
  });

  // ═════════ حواريّة «جهة جديدة» ═════════
  const modal = document.getElementById('entityCreateModal');
  if (!modal) return;
  const form     = document.getElementById('entityCreateForm');
  const nameIn   = document.getElementById('ecName');
  const statusEl = document.getElementById('ecNameStatus');
  const similar  = document.getElementById('ecSimilar');
  const submit   = document.getElementById('ecSubmit');
  const submitSpinner = submit.querySelector('.en-submit-spinner');
  const checkUrl = modal.dataset.checkUrl;
  const radios   = [...form.querySelectorAll('input[name="kind"]')];
  let kindTouched = false;   // اختيارُ الكاتب لا يُكتب فوقه بالاقتراح
  let timer = null;
  let inflight = null;
  let blocked = false;

  radios.forEach(r => r.addEventListener('change', () => { kindTouched = true; }));

  const STATUS = {
    active:   { label: 'مسجّلة', cls: 'is-active' },
    inactive: { label: 'معطّلة', cls: 'is-inactive' },
    merged:   { label: 'مدموجة', cls: 'is-merged' },
  };

  function setStatus(tone, text) {
    statusEl.className = 'en-namecheck' + (tone ? ' is-' + tone : '');
    statusEl.textContent = text || '';
  }

  function markSuggested(kind) {
    radios.forEach(r => {
      const badge = r.closest('.en-kindopt')?.querySelector('.en-suggested');
      if (badge) badge.hidden = r.value !== kind;
      if (!kindTouched) r.checked = !!kind && r.value === kind;
    });
  }

  function inactiveLink(name) {
    return '?status=inactive&q=' + encodeURIComponent(name);
  }

  function renderMatches(data) {
    similar.replaceChildren();
    const rows = data.matches || [];
    rows.forEach(m => {
      const li = document.createElement('li');
      const st = STATUS[m.status] || STATUS.active;
      const name = document.createElement(m.url ? 'a' : 'span');
      name.className = 'en-similar-name';
      name.textContent = m.name;
      if (m.url) { name.href = m.url; name.target = '_blank'; name.rel = 'noopener'; }
      const meta = document.createElement('span');
      meta.className = 'en-similar-meta';
      meta.textContent = [m.code, m.kind_label].filter(Boolean).join(' · ');
      const badge = document.createElement('span');
      badge.className = 'en-similar-badge ' + st.cls;
      badge.textContent = st.label;
      li.append(name, meta, badge);
      if (m.status === 'merged' && m.merged_into) {
        const to = document.createElement('a');
        to.className = 'en-similar-to';
        to.href = m.merged_into.url; to.target = '_blank'; to.rel = 'noopener';
        to.textContent = '← في «' + m.merged_into.name + '»';
        li.append(to);
      } else if (m.status === 'inactive') {
        const to = document.createElement('a');
        to.className = 'en-similar-to';
        to.href = inactiveLink(m.name);
        to.textContent = 'استرجعها';
        li.append(to);
      }
      similar.append(li);
    });
    similar.hidden = rows.length === 0;
  }

  function applyCheck(data) {
    renderMatches(data);
    markSuggested(data.suggested_kind || '');
    const ex = data.exact;
    // الاسمُ فريدٌ في القاعدة: التطابقُ التامّ يُرفض عند الحفظ أيّاً كانت حالتُه —
    // نقوله الآن بالسبب والمخرج بدل رسالةِ خطأٍ بعد إعادة تحميل الصفحة.
    blocked = !!ex;
    if (ex && ex.status === 'active') {
      setStatus('danger', 'الجهة مسجّلةٌ بهذا الاسم — افتحها من القائمة أدناه بدل تسجيلها مرّةً ثانية.');
    } else if (ex && ex.status === 'merged') {
      setStatus('danger', 'هذا الاسمُ دُمج في جهةٍ أخرى — استعمل الجهةَ الموحَّدة.');
    } else if (ex) {
      setStatus('danger', 'جهةٌ معطّلةٌ تحمل هذا الاسم — استرجعها بدل تسجيلها من جديد.');
    } else if ((data.matches || []).length) {
      setStatus('warn', 'أسماءٌ مشابهة مسجّلة — تأكّد أنّ الجهة ليست إحداها.');
    } else {
      setStatus('ok', 'اسمٌ جديد — لا جهةَ مسجّلةً به.');
    }
    submit.disabled = blocked;
  }

  function runCheck() {
    const name = nameIn.value.trim().replace(/\s+/g, ' ');
    if (inflight) inflight.abort();
    if (name.length < 2) {
      blocked = false; submit.disabled = false;
      setStatus('', ''); similar.hidden = true; markSuggested('');
      return;
    }
    setStatus('busy', 'يتحقّق من الاسم…');
    inflight = new AbortController();
    fetch(checkUrl + '?name=' + encodeURIComponent(name), {
      signal: inflight.signal, headers: { 'X-Requested-With': 'XMLHttpRequest' },
    })
      .then(r => { if (!r.ok) throw new Error(r.status); return r.json(); })
      .then(data => {
        // الردُّ يخصّ ما في الحقل الآن لا ما كان فيه عند الطلب
        if (data.name !== nameIn.value.trim().replace(/\s+/g, ' ')) return;
        applyCheck(data);
      })
      .catch(err => {
        if (err.name === 'AbortError') return;
        blocked = false; submit.disabled = false;
        setStatus('warn', 'تعذّر التحقّق من التكرار الآن — الحفظُ ما يزال يرفض الاسمَ المكرّر.');
      });
  }

  nameIn.addEventListener('input', () => {
    clearTimeout(timer);
    timer = setTimeout(runCheck, 280);
  });

  form.addEventListener('submit', e => {
    if (!nameIn.value.trim()) {
      e.preventDefault();
      setStatus('danger', 'اكتب اسم الجهة.');
      nameIn.focus();
      return;
    }
    if (blocked) { e.preventDefault(); nameIn.focus(); return; }
    submit.disabled = true;
    submit.setAttribute('aria-busy', 'true');
    submitSpinner.hidden = false;
  });

  modal.addEventListener('shown.bs.modal', () => nameIn.focus());
  modal.addEventListener('hidden.bs.modal', () => {
    form.reset();
    kindTouched = false; blocked = false;
    submit.disabled = false; submit.removeAttribute('aria-busy');
    submitSpinner.hidden = true;
    setStatus('', ''); similar.hidden = true; markSuggested('');
  });
})();
