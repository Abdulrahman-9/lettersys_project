/* LetterSys — لوحُ التبويب المنزلق (الهويّة الموحّدة).
 *
 * أيُّ حاويةٍ [data-lx-tabs] أبناؤها [role="tab"]: لوحٌ واحد (span.lx-tabs-ind) ينزلق إلى
 * التبويب النشط بدل أن يتلوّن كلُّ تبويبٍ وحده. النشطُ يُعرف بـ.active أو aria-selected —
 * أيّاً كان من يقلبهما (في قائمة الكتب: مديرُ AJAX)؛ المراقِبُ يلحق به بلا ربطٍ بمنطقه.
 * بلا هذا الملفّ (أو قبل تشغيله) يتلوّن التبويبُ النشط نفسُه: CSS يعرف الحالتين (.lx-tabs-on).
 * تقليلُ الحركة: الموضعُ يتبدّل بلا انزلاق (theme.css).
 */
(function () {
  'use strict';

  function activeTab(box) {
    return box.querySelector('[role="tab"].active, [role="tab"][aria-selected="true"]');
  }

  function place(box, ind) {
    var tab = activeTab(box);
    ind.hidden = !tab;
    if (!tab) return;
    // offsetLeft فيزيائيٌّ في RTL أيضاً: اللوحُ مثبّتٌ على left:0 ويُزاح أفقيّاً
    box.style.setProperty('--ind-x', tab.offsetLeft + 'px');
    box.style.setProperty('--ind-w', tab.offsetWidth + 'px');
  }

  function enhance(box) {
    if (box.querySelector(':scope > .lx-tabs-ind')) return;
    var ind = document.createElement('span');
    ind.className = 'lx-tabs-ind';
    ind.setAttribute('aria-hidden', 'true');
    box.insertBefore(ind, box.firstChild);
    place(box, ind);
    box.classList.add('lx-tabs-on');
    // الموضعُ الأوّل بلا انزلاق — الحركةُ للتبديل وحده
    requestAnimationFrame(function () {
      requestAnimationFrame(function () { ind.classList.add('is-ready'); });
    });
    // المراقِبُ يكتب style وحدها، ولا يراقبها: لا حلقة
    new MutationObserver(function () { place(box, ind); })
      .observe(box, { subtree: true, attributes: true, attributeFilter: ['class', 'aria-selected'] });
    if (window.ResizeObserver) new ResizeObserver(function () { place(box, ind); }).observe(box);
  }

  document.querySelectorAll('[data-lx-tabs]').forEach(enhance);
})();
