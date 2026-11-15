/* القشرة: لوحٌ ينزلق تحت الرابط · تلميحٌ للشريط المطويّ · ظلُّ الشريط العلويّ عند التمرير.
   بلا هذا الملفّ تبقى القشرةُ عاملةً كاملةً: المرورُ والتسمياتُ بالـCSS وحدها. */
(function () {
  'use strict';
  var bar = document.querySelector('.app-topbar');
  var side = document.getElementById('appNav');
  var shell = document.querySelector('.app-shell');
  var wide = window.matchMedia('(min-width: 1200px)');

  if (bar) {
    var onScroll = function () { bar.classList.toggle('is-scrolled', window.scrollY > 4); };
    window.addEventListener('scroll', onScroll, { passive: true });
    onScroll();
  }
  if (!side || !shell) return;

  var LINKS = '.app-sidebar-link, .sa-nav a';
  var TIPPED = LINKS + ', .app-sidebar-cta, .app-sidebar-account';

  // الصفحةُ الحاليّة في مجال الرؤية — قائمةُ مدير النظام طويلة
  var current = side.querySelector('.app-sidebar-link.active, .sa-nav a.on');
  if (current && wide.matches && current.offsetTop + current.offsetHeight > side.clientHeight - 90) {
    side.scrollTop = current.offsetTop - side.clientHeight / 3;
  }

  // ── اللوحُ المنزلق ──
  var glide = document.createElement('span');
  glide.className = 'lx-glide';
  glide.setAttribute('aria-hidden', 'true');
  side.insertBefore(glide, side.firstChild);
  side.classList.add('lx-glide-ready');
  var shown = false;

  function moveTo(link) {
    if (!wide.matches) return;
    if (!shown) {
      glide.classList.add('is-instant');
      requestAnimationFrame(function () { requestAnimationFrame(function () { glide.classList.remove('is-instant'); }); });
    }
    glide.style.setProperty('--gx', link.offsetLeft + 'px');
    glide.style.setProperty('--gy', link.offsetTop + 'px');
    glide.style.setProperty('--gw', link.offsetWidth + 'px');
    glide.style.setProperty('--gh', link.offsetHeight + 'px');
    glide.classList.add('is-on');
    shown = true;
  }

  function hideGlide() { glide.classList.remove('is-on'); shown = false; }

  // ── تلميحُ المطويّ ──
  var tip = document.createElement('div');
  tip.className = 'lx-tip';
  tip.setAttribute('aria-hidden', 'true');
  document.body.appendChild(tip);
  var tipped = null;
  var tipTimer = 0;

  // التلميحُ المرسوم يحلّ محلَّ title (فلا يظهر تلميحان) — ومَن لا اسمَ له سواه يأخذه aria-label
  side.querySelectorAll(TIPPED).forEach(function (el) {
    if (!el.title) return;
    var text = el.querySelector(':scope > span:not(.app-sidebar-link-badge)');
    if (!el.getAttribute('aria-label') && !(text && text.textContent.trim())) el.setAttribute('aria-label', el.title);
    el.setAttribute('data-tip', el.title);
    el.removeAttribute('title');
  });

  function label(el) {
    if (el.getAttribute('data-tip')) return el.getAttribute('data-tip');
    var s = el.querySelector('.app-sidebar-account-text b') || el.querySelector(':scope > span:not(.app-sidebar-link-badge)');
    return (s ? s.textContent : el.textContent).trim();
  }

  function place(el) {
    tip.textContent = label(el);
    var r = el.getBoundingClientRect();
    var rail = side.getBoundingClientRect();
    tip.style.top = Math.round(r.top + r.height / 2 - tip.offsetHeight / 2) + 'px';
    tip.style.left = Math.round(rail.left - tip.offsetWidth - 12) + 'px';
  }

  // الأوّلُ بعد تريّثٍ قصير (لا يومض تحت يدٍ عابرة)، والأقرانُ فوراً، ولوحةُ المفاتيح فوراً
  function showTip(el, now) {
    if (el === tipped) return;
    tipped = el;
    clearTimeout(tipTimer);
    if (!wide.matches || !shell.classList.contains('sidebar-mini')) { tip.classList.remove('is-on'); return; }
    if (tip.classList.contains('is-on')) { place(el); return; }
    tipTimer = setTimeout(function () { place(el); tip.classList.add('is-on'); }, now ? 0 : 380);
  }

  function hideTip() { clearTimeout(tipTimer); tip.classList.remove('is-on'); tipped = null; }

  side.addEventListener('pointerover', function (e) {
    var link = e.target.closest(LINKS);
    if (link) moveTo(link);
    var el = e.target.closest(TIPPED);
    if (el) showTip(el); else hideTip();
  });
  side.addEventListener('pointerleave', function () { hideGlide(); hideTip(); });
  side.addEventListener('focusin', function (e) {
    var link = e.target.closest(LINKS);
    if (link) moveTo(link);
    var el = e.target.closest(TIPPED);
    if (el) showTip(el, true);
  });
  side.addEventListener('focusout', function (e) {
    if (!side.contains(e.relatedTarget)) { hideGlide(); hideTip(); }
  });
  side.addEventListener('scroll', hideTip, { passive: true });
  // الطيُّ يغيّر المقاسات: يُخفى اللوحُ والتلميحُ حتّى تمرّ اليدُ ثانيةً
  new MutationObserver(function () { hideGlide(); hideTip(); }).observe(shell, { attributes: true, attributeFilter: ['class'] });
})();
