/* ══════════════════════════════════════════════════════════════════
   «أين الموضوع؟» — حين يصمت الاستخراج عن الموضوع (قرارُ المالك 2026‑09‑11).
   الخادم يرسل اقتراحَ موضعٍ (صندوقٌ + مرشّحون + معاينةُ الصفحة + رمزٌ لصفحةٍ
   محفوظةٍ 15 دقيقة). الكاتبُ **ينقر سطراً** أو يسحب مستطيلاً ⟵ «اقرأ من هنا»
   ⟵ يرى النصَّ ⟵ «استعمِله» يملأ الحقل. التعلّمُ يُرسَل عند **الحفظ** لا عند
   الاستعمال: إن عدّل الكاتبُ النصَّ قبل الحفظ فالصندوقُ لا يُعلّم (قد يكون خطأً).
   ══════════════════════════════════════════════════════════════════ */
(function () {
  'use strict';
  var els = {}, state = { proposal: null, box: null, text: '', token: '', entityId: null, fills: null };

  function $(id) { return document.getElementById(id); }
  function csrf() {
    var m = document.cookie.match(/csrftoken=([^;]+)/);
    return m ? m[1] : (document.querySelector('[name=csrfmiddlewaretoken]') || {}).value || '';
  }
  function clamp(v) { return v < 0 ? 0 : (v > 1 ? 1 : v); }

  function init() {
    els = { card: $('subjectLocate'), stage: $('subjectLocateStage'), img: $('subjectLocateImg'),
            rect: $('subjectLocateRect'), cands: $('subjectLocateCands'), read: $('subjectLocateRead'),
            text: $('subjectLocateText'), reason: $('subjectLocateReason'), src: $('subjectLocateSrc'),
            readBtn: $('subjectLocateReadBtn'), apply: $('subjectLocateApply'), dismiss: $('subjectLocateDismiss'),
            title: $('title') };
    if (!els.card || !els.stage) return;
    bindDrag();
    els.readBtn.addEventListener('click', readBox);
    els.apply.addEventListener('click', applyText);
    els.dismiss.addEventListener('click', hide);
  }

  /* ── العرض ── */
  function show(proposal) {
    if (!proposal || !proposal.page_preview) { hide(); return; }
    state.proposal = proposal; state.token = proposal.page_token || '';
    state.entityId = proposal.entity_id || null; state.text = '';
    els.img.src = proposal.page_preview;
    els.src.textContent = ({ 'learned-relative': 'من ذاكرة الجهة (نسبيّ)', learned: 'من ذاكرة الجهة',
                             scored: 'مرشّحٌ مُدرَّج', structural: 'بين «إلى/» والتحيّة', 'default': 'حزامٌ افتراضيّ' })[proposal.source] || '';
    els.read.hidden = true; els.apply.hidden = true;
    els.card.hidden = false;
    els.img.onload = function () { drawCandidates(proposal.candidates || []); setBox(proposal.box); };
    if (els.img.complete && els.img.naturalWidth) els.img.onload();
  }
  function hide() { if (els.card) els.card.hidden = true; state.proposal = null; }

  function drawCandidates(cands) {
    els.cands.innerHTML = '';
    cands.forEach(function (c, i) {
      var d = document.createElement('div');
      d.className = 'subject-locate__cand' + (i === 0 ? ' is-best' : '');
      d.title = (c.text || '') + (c.score != null ? ' · ' + c.score : '');
      d.tabIndex = 0; d.setAttribute('role', 'button');
      place(d, c.box);
      d.addEventListener('click', function () { setBox(c.box); });
      d.addEventListener('keydown', function (e) { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setBox(c.box); } });
      els.cands.appendChild(d);
    });
  }
  function place(el, box) {
    el.style.left = (box.x * 100) + '%'; el.style.top = (box.y * 100) + '%';
    el.style.width = (box.w * 100) + '%'; el.style.height = (box.h * 100) + '%';
  }
  function setBox(box) {
    if (!box) return;
    state.box = box; els.rect.hidden = false; place(els.rect, box);
    els.read.hidden = true; els.apply.hidden = true;
  }

  /* ── السحب الحرّ ── */
  function bindDrag() {
    var origin = null;
    function pt(e) {
      var r = els.img.getBoundingClientRect();
      var p = e.touches ? e.touches[0] : e;
      return { x: clamp((p.clientX - r.left) / r.width), y: clamp((p.clientY - r.top) / r.height) };
    }
    function start(e) { if (e.target.classList.contains('subject-locate__cand')) return; origin = pt(e); }
    function move(e) {
      if (!origin) return;
      var p = pt(e);
      setBox({ x: Math.min(origin.x, p.x), y: Math.min(origin.y, p.y),
               w: Math.abs(p.x - origin.x), h: Math.abs(p.y - origin.y) });
      e.preventDefault();
    }
    function end() { if (origin && state.box && (state.box.w < 0.02 || state.box.h < 0.01)) setBox(state.proposal && state.proposal.box); origin = null; }
    els.stage.addEventListener('mousedown', start); els.stage.addEventListener('mousemove', move);
    window.addEventListener('mouseup', end);
    els.stage.addEventListener('touchstart', start, { passive: true });
    els.stage.addEventListener('touchmove', move, { passive: false });
    els.stage.addEventListener('touchend', end);
  }

  /* ── القراءة والاستعمال ── */
  function readBox() {
    if (!state.box || !state.token) return;
    els.readBtn.disabled = true;
    fetch('/books/api/extract/subject-box/read/', {
      method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf() },
      body: JSON.stringify({ page_token: state.token, box: state.box })
    }).then(function (r) { return r.json().then(function (j) { return { ok: r.ok, status: r.status, j: j }; }); })
      .then(function (res) {
        els.read.hidden = false;
        if (res.status === 410) { els.text.textContent = ''; els.reason.textContent = res.j.message || 'انتهت صلاحيةُ الصفحة'; els.apply.hidden = true; return; }
        state.text = res.j.text || '';
        els.text.textContent = state.text || (res.j.raw ? '«' + res.j.raw + '»' : '—');
        els.reason.textContent = res.j.accepted ? '' : (res.j.reason || 'لم تُقرأ قراءةٌ صالحة');
        els.apply.hidden = !res.j.accepted;
      })
      .catch(function () { els.read.hidden = false; els.reason.textContent = 'تعذّر الاتّصال'; })
      .finally(function () { els.readBtn.disabled = false; });
  }
  function applyText() {
    if (!state.text || !els.title) return;
    els.title.value = state.text;
    els.title.dispatchEvent(new Event('input', { bubbles: true }));
    // يُرسَل التعلّمُ عند الحفظ — نُبقي ما يلزم لمقارنة النصّ آنذاك
    window.__subjectSample = { page_token: state.token, entity_id: state.entityId, box: state.box, text: state.text };
    hide();
  }

  /* ── التعلّم عند الحفظ: يستدعيه سطحُ الاستخراج بعد نجاح الحفظ ── */
  function confirmOnSave(savedTitle) {
    var s = window.__subjectSample;
    if (!s) return;
    window.__subjectSample = null;
    var edited = (savedTitle || '').trim() !== (s.text || '').trim();
    fetch('/books/api/extract/subject-box/confirm/', {
      method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf() },
      body: JSON.stringify({ page_token: s.page_token, entity_id: s.entity_id, box: s.box, text: s.text, edited: edited })
    }).catch(function () {});
  }

  window.SubjectLocate = { init: init, show: show, hide: hide, confirmOnSave: confirmOnSave };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init();
})();
