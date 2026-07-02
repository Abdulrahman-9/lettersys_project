/**
 * book_detail.js — تفاعلات صفحة تفاصيل الكتاب
 * يربط: حفظ الملاحظات (notesModal) + إضافة/تعديل/حذف التعليقات.
 * النقاط الخلفية موجودة مسبقاً؛ هذا الملف كان مفقوداً فبقيت الأزرار بلا معالج.
 */
(function () {
  'use strict';

  const COMMENT_MAX = 5000;

  function getCsrf() {
    const m = document.cookie.match(/csrftoken=([^;]+)/);
    return m ? m[1] : '';
  }

  function toast(level, message) {
    if (window.ToastCenter && typeof window.ToastCenter.show === 'function') {
      window.ToastCenter.show(level === 'danger' ? 'error' : level, message);
    }
  }

  async function postJSON(url, body) {
    const resp = await fetch(url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': getCsrf(),
        'X-Requested-With': 'XMLHttpRequest',
      },
      body: JSON.stringify(body || {}),
    });
    let payload = {};
    try { payload = await resp.json(); } catch (e) { /* تُترك فارغة */ }
    if (!resp.ok || payload.status !== 'ok') {
      throw new Error(payload.message || `خطأ ${resp.status}`);
    }
    return payload;
  }

  // ─────────────────────────────────────────────────────────────
  // الملاحظات (notesModal)
  // ─────────────────────────────────────────────────────────────
  function renderNotes(margin) {
    const el = document.getElementById('bookNotesDisplay');
    if (!el) return;
    el.innerHTML = '';
    if (margin) {
      const div = document.createElement('div');
      div.className = 'p-3 bg-light rounded-3 border-start border-3 border-primary';
      div.style.whiteSpace = 'pre-wrap';
      div.textContent = margin;
      el.appendChild(div);
    } else {
      const empty = document.createElement('div');
      empty.className = 'text-muted text-center py-4';
      empty.innerHTML = '<i class="bi bi-chat-dots fs-3 opacity-50 d-block mb-2"></i>لا توجد ملاحظات';
      el.appendChild(empty);
    }
  }

  function initNotes() {
    const btn = document.getElementById('saveNotesBtn');
    const textarea = document.getElementById('notesTextarea');
    if (!btn || !textarea) return;

    btn.addEventListener('click', async function () {
      const bookId = btn.dataset.bookId;
      const margin = textarea.value;
      btn.disabled = true;
      try {
        const payload = await postJSON(`/books/api/book-notes/${bookId}/`, { margin });
        renderNotes(payload.margin);
        const modalEl = document.getElementById('notesModal');
        if (modalEl && window.bootstrap) bootstrap.Modal.getInstance(modalEl)?.hide();
        toast('success', payload.message || 'تم حفظ الملاحظات');
      } catch (err) {
        toast('error', err.message || 'تعذّر حفظ الملاحظات');
      } finally {
        btn.disabled = false;
      }
    });
  }

  // ─────────────────────────────────────────────────────────────
  // التعليقات
  // ─────────────────────────────────────────────────────────────
  function commentCount() {
    return document.querySelectorAll('#commentsList .comment-item').length;
  }

  function syncCommentCount() {
    const n = commentCount();
    const badge = document.querySelector('[data-comments-count]');
    if (badge) { badge.textContent = n; badge.dataset.commentsCount = String(n); }
    const empty = document.getElementById('noCommentsMessage');
    if (empty) empty.classList.toggle('d-none', n > 0);
  }

  // بناء عنصر تعليق جديد عبر DOM (يطابق بنية القالب) — آمن ضد XSS عبر textContent
  function buildCommentNode(comment, author, canEdit) {
    const item = document.createElement('div');
    item.className = 'comment-item';
    item.dataset.commentId = String(comment.id);
    item.dataset.canEdit = canEdit ? 'true' : 'false';
    item.dataset.author = author;

    const header = document.createElement('div');
    header.className = 'comment-header d-flex justify-content-between align-items-start mb-2';

    const left = document.createElement('div');
    left.className = 'd-flex align-items-center gap-2';
    left.innerHTML = '<div class="comment-avatar"><i class="bi bi-person-circle fs-4 text-primary"></i></div>';

    const meta = document.createElement('div');
    const authorLine = document.createElement('div');
    authorLine.className = 'comment-author fw-semibold text-dark';
    authorLine.textContent = author + ' ';
    const youBadge = document.createElement('span');
    youBadge.className = 'badge bg-success text-white ms-1';
    youBadge.style.fontSize = '0.65rem';
    youBadge.textContent = 'أنت';
    authorLine.appendChild(youBadge);

    const dateLine = document.createElement('small');
    dateLine.className = 'comment-date text-muted';
    dateLine.textContent = comment.created_at || '';

    meta.appendChild(authorLine);
    meta.appendChild(dateLine);
    left.appendChild(meta);
    header.appendChild(left);

    if (canEdit) {
      const actions = document.createElement('div');
      actions.className = 'comment-actions dropdown';
      actions.innerHTML =
        '<button class="btn btn-sm btn-link text-muted" type="button" data-bs-toggle="dropdown" aria-label="إجراءات التعليق"><i class="bi bi-three-dots-vertical"></i></button>' +
        '<ul class="dropdown-menu dropdown-menu-end">' +
        `<li><button class="dropdown-item edit-comment-btn" data-comment-id="${comment.id}"><i class="bi bi-pencil me-1"></i>تعديل</button></li>` +
        '<li><hr class="dropdown-divider"></li>' +
        `<li><button class="dropdown-item text-danger delete-comment-btn" data-comment-id="${comment.id}"><i class="bi bi-trash me-1"></i>حذف</button></li>` +
        '</ul>';
      header.appendChild(actions);
    }

    const content = document.createElement('div');
    content.className = 'comment-content';
    const p = document.createElement('p');
    p.className = 'mb-0 text-dark';
    p.style.whiteSpace = 'pre-wrap';
    p.textContent = comment.content;
    content.appendChild(p);

    item.appendChild(header);
    item.appendChild(content);
    return item;
  }

  function initComments() {
    const addBtn = document.getElementById('addCommentBtn');
    const textarea = document.getElementById('newCommentContent');
    const counter = document.getElementById('commentCharCount');
    const list = document.getElementById('commentsList');
    if (!addBtn || !textarea || !list) return;

    // عدّاد الأحرف
    if (counter) {
      const updateCounter = () => { counter.textContent = `${textarea.value.length} / ${COMMENT_MAX}`; };
      textarea.addEventListener('input', updateCounter);
      updateCounter();
    }

    // إضافة
    addBtn.addEventListener('click', async function () {
      const content = textarea.value.trim();
      if (!content) { toast('warning', 'محتوى التعليق مطلوب'); return; }
      const bookId = addBtn.dataset.bookId;
      addBtn.disabled = true;
      try {
        const payload = await postJSON(`/books/api/book-comments/${bookId}/add/`, { content });
        const node = buildCommentNode(payload.comment, addBtn.dataset.currentUser || '', true);
        list.insertBefore(node, list.firstChild);
        textarea.value = '';
        if (counter) counter.textContent = `0 / ${COMMENT_MAX}`;
        syncCommentCount();
        toast('success', payload.message || 'تم إضافة التعليق');
      } catch (err) {
        toast('error', err.message || 'تعذّر إضافة التعليق');
      } finally {
        addBtn.disabled = false;
      }
    });

    // تعديل/حذف عبر التفويض (يشمل التعليقات المُضافة ديناميكياً)
    list.addEventListener('click', function (e) {
      const editBtn = e.target.closest('.edit-comment-btn');
      const delBtn = e.target.closest('.delete-comment-btn');
      if (editBtn) { startInlineEdit(editBtn.closest('.comment-item')); }
      else if (delBtn) { deleteComment(delBtn.closest('.comment-item')); }
    });
  }

  function startInlineEdit(item) {
    if (!item || item.querySelector('.comment-edit-box')) return;
    const contentEl = item.querySelector('.comment-content');
    const p = contentEl.querySelector('p');
    const original = p ? p.textContent : '';

    const box = document.createElement('div');
    box.className = 'comment-edit-box';
    const ta = document.createElement('textarea');
    ta.className = 'form-control mb-2';
    ta.rows = 3;
    ta.maxLength = COMMENT_MAX;
    ta.value = original;
    const actions = document.createElement('div');
    actions.className = 'd-flex gap-2 justify-content-end';
    const save = document.createElement('button');
    save.className = 'btn btn-sm btn-primary';
    save.textContent = 'حفظ';
    const cancel = document.createElement('button');
    cancel.className = 'btn btn-sm btn-outline-secondary';
    cancel.textContent = 'إلغاء';
    actions.appendChild(cancel);
    actions.appendChild(save);
    box.appendChild(ta);
    box.appendChild(actions);

    contentEl.style.display = 'none';
    contentEl.parentNode.insertBefore(box, contentEl.nextSibling);
    ta.focus();

    cancel.addEventListener('click', () => { box.remove(); contentEl.style.display = ''; });
    save.addEventListener('click', async () => {
      const content = ta.value.trim();
      if (!content) { toast('warning', 'محتوى التعليق مطلوب'); return; }
      const commentId = item.dataset.commentId;
      save.disabled = true;
      try {
        const payload = await postJSON(`/books/api/book-comments/${commentId}/edit/`, { content });
        if (p) p.textContent = payload.comment.content;
        // علامة (معدّل)
        const dateEl = item.querySelector('.comment-date');
        if (dateEl && payload.comment.is_edited && !dateEl.querySelector('.comment-edited-flag')) {
          const flag = document.createElement('span');
          flag.className = 'text-primary comment-edited-flag';
          flag.textContent = ' (معدّل)';
          dateEl.appendChild(flag);
        }
        box.remove();
        contentEl.style.display = '';
        toast('success', payload.message || 'تم تعديل التعليق');
      } catch (err) {
        toast('error', err.message || 'تعذّر تعديل التعليق');
      } finally {
        save.disabled = false;
      }
    });
  }

  async function deleteComment(item) {
    if (!item) return;
    if (!window.confirm('حذف هذا التعليق؟')) return;
    const commentId = item.dataset.commentId;
    try {
      const payload = await postJSON(`/books/api/book-comments/${commentId}/delete/`, {});
      item.remove();
      syncCommentCount();
      toast('success', payload.message || 'تم حذف التعليق');
    } catch (err) {
      toast('error', err.message || 'تعذّر حذف التعليق');
    }
  }

  // ─────────────────────────────────────────────────────────────
  // عارض المستند المضمّن (أعلى العمود الرئيسي) — يفوّض البناء لـ DocView
  // ─────────────────────────────────────────────────────────────
  function initDocViewer() {
    const card = document.getElementById('bookDocCard');
    const viewer = document.getElementById('bookDocViewer');
    const chips = document.getElementById('bookDocChips');
    if (!card || !viewer) return;
    if (!window.DocView) { card.classList.add('d-none'); return; }  // تحصين: doc_view.js لم يُحمَّل

    const btns = Array.from(document.querySelectorAll('.preview-btn'));
    const atts = btns
      .map((b) => ({
        id: b.dataset.attId,
        url: b.dataset.fileUrl,
        name: (b.dataset.fileName || 'مستند').split('/').pop(),
        kind: window.DocView.fileKind(b.dataset.fileUrl),
      }))
      .filter((a) => a.url);

    if (!atts.length) { card.classList.add('d-none'); return; }
    card.classList.remove('d-none');

    // ── نصّ OCR (تحميل كسول، قابل للتحديد والبحث، بديل وصولية للصورة) ──
    const ocrToggle = document.getElementById('bookOcrToggle');
    const ocrPanel = document.getElementById('bookOcrPanel');
    const ocrCache = {};
    let currentAttId = null;

    function resetOcr() {
      if (ocrPanel) { ocrPanel.classList.add('d-none'); ocrPanel.innerHTML = ''; }
      if (ocrToggle) ocrToggle.classList.remove('active');
    }

    function renderOcr(data) {
      if (!ocrPanel) return;
      ocrPanel.innerHTML = '';
      if (!data.has_text) {
        const none = document.createElement('div');
        none.className = 'text-muted small p-2';
        none.textContent = 'لا يوجد نص مستخرج لهذا المرفق.';
        ocrPanel.appendChild(none);
        return;
      }
      if (data.confidence) {
        const meta = document.createElement('div');
        meta.className = 'text-muted small px-2 pt-1';
        meta.textContent = `ثقة الاستخراج: ${data.confidence}%`;
        ocrPanel.appendChild(meta);
      }
      const pre = document.createElement('pre');
      pre.className = 'bp-ocr-text';
      pre.textContent = data.text;
      ocrPanel.appendChild(pre);
    }

    async function showOcr() {
      if (!ocrPanel || currentAttId == null) return;
      if (ocrToggle) ocrToggle.classList.add('active');
      ocrPanel.classList.remove('d-none');
      if (ocrCache[currentAttId] !== undefined) { renderOcr(ocrCache[currentAttId]); return; }
      ocrPanel.innerHTML = '<div class="text-muted small p-2">…جارٍ تحميل النص</div>';
      try {
        const resp = await fetch(`/books/api/attachment/${currentAttId}/ocr/`, { headers: { 'X-Requested-With': 'XMLHttpRequest' } });
        const data = await resp.json();
        if (!resp.ok || data.status !== 'ok') throw new Error(data.message || 'تعذّر التحميل');
        ocrCache[currentAttId] = data;
        renderOcr(data);
      } catch (err) {
        ocrPanel.innerHTML = '';
        const e = document.createElement('div');
        e.className = 'text-muted small p-2';
        e.textContent = err.message || 'تعذّر تحميل النص المستخرج';
        ocrPanel.appendChild(e);
      }
    }

    if (ocrToggle) {
      ocrToggle.addEventListener('click', function () {
        if (ocrPanel && !ocrPanel.classList.contains('d-none')) resetOcr();
        else showOcr();
      });
    }

    function select(att) {
      currentAttId = att.id;
      resetOcr();
      viewer.innerHTML = '';
      viewer.appendChild(window.DocView.buildNode({ url: att.url, name: att.name, kind: att.kind }));
      if (chips) {
        chips.querySelectorAll('.bp-doc-chip').forEach((c) => {
          c.classList.toggle('active', c.dataset.attId === String(att.id));
        });
      }
    }

    if (atts.length > 1 && chips) {
      chips.classList.remove('d-none');
      atts.forEach((att) => {
        const chip = document.createElement('button');
        chip.type = 'button';
        chip.className = 'bp-doc-chip';
        chip.dataset.attId = String(att.id);
        const icon = document.createElement('i');
        icon.className = att.kind === 'pdf' ? 'bi bi-file-earmark-pdf' : (att.kind === 'image' ? 'bi bi-image' : 'bi bi-file-earmark');
        chip.appendChild(icon);
        chip.appendChild(document.createTextNode(' ' + att.name));
        chip.addEventListener('click', () => select(att));
        chips.appendChild(chip);
      });
    }

    // إعادة توجيه أزرار «معاينة» لكل مرفق إلى العارض المضمّن بدل مودال منفصل
    btns.forEach((b) => {
      b.addEventListener('click', function (e) {
        e.preventDefault();
        const att = atts.find((a) => String(a.id) === String(b.dataset.attId));
        if (att) { select(att); card.scrollIntoView({ behavior: 'smooth', block: 'start' }); }
      });
    });

    // المستند الأساسي: أول PDF، وإلا أول صورة، وإلا أول مرفق
    const primary = atts.find((a) => a.kind === 'pdf') || atts.find((a) => a.kind === 'image') || atts[0];
    select(primary);
  }

  // ─────────────────────────────────────────────────────────────
  // العودة لنقطة الدخول: إن جئنا من صفحة داخلية نرجع في تاريخ المتصفح
  // (يحفظ حالة القائمة: التبويب/الفلتر/الصفحة/التمرير)، وإلا نتبع href (back_url من العرض).
  // ─────────────────────────────────────────────────────────────
  function initBackNav() {
    const ref = document.referrer || '';
    const sameOrigin = ref.indexOf(window.location.origin) === 0;
    let internalNotSelf = false;
    if (sameOrigin) {
      try { internalNotSelf = new URL(ref).pathname !== window.location.pathname; } catch (e) { /* تجاهل */ }
    }
    document.querySelectorAll('[data-back-nav]').forEach(function (el) {
      el.addEventListener('click', function (e) {
        if (internalNotSelf && window.history.length > 1) {
          e.preventDefault();
          window.history.back();
        }
        // غير ذلك: اترك href (next/Referer/القائمة) يعمل كاحتياطي
      });
    });
  }

  // ─────────────────────────────────────────────────────────────
  // طباعة المستند المرفق عبر عارض PDF (العارض المضمّن إن أمكن، وإلا تبويب جديد)
  // ─────────────────────────────────────────────────────────────
  function initPrint() {
    const btn = document.getElementById('printDocBtn');
    if (!btn) return;
    btn.addEventListener('click', function () {
      const frame = document.querySelector('#bookDocViewer iframe');
      if (frame && frame.src) {
        try { frame.contentWindow.focus(); frame.contentWindow.print(); return; }
        catch (e) { /* قد يُمنع طباعة PDF داخل iframe في بعض المتصفحات → نفتح تبويباً */ }
      }
      const first = document.querySelector('.preview-btn');
      const url = (frame && frame.src) || (first && first.dataset.fileUrl);
      if (url) window.open(url, '_blank', 'noopener');
      else toast('warning', 'لا يوجد مستند للطباعة');
    });
  }

  document.addEventListener('DOMContentLoaded', function () {
    // عزل كل تهيئة: فشل واحدة (مثلاً العارض) لا يُجهض البقية (العودة/الطباعة)
    [initNotes, initComments, initDocViewer, initBackNav, initPrint].forEach(function (fn) {
      try { fn(); } catch (e) { if (window.console) console.error('book_detail init:', e); }
    });
  });
})();
