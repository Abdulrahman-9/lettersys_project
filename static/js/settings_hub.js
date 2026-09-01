/* ============================================================
   مركز الإعدادات — منطق الشريط العلوي
   • تبويبات مُدمَجة (عام/إشعارات/أمان/نسخ): تبديل لحظي بلا تحميل.
   • تبويبات أدوات ثقيلة: تُحمَّل داخل iframe (?embed=1) بلا مغادرة المركز.
   • تبويب خارجي (الذكاء الاصطناعي): يفتح لوحة الأدمن في تبويب جديد.
   • مزامنة ?tab عبر history، بحث فوري، مؤشّر منزلق، تنقّل بلوحة المفاتيح.
   ============================================================ */
(function () {
  'use strict';

  var strip     = document.getElementById('settingsTabstrip');
  var shell     = document.getElementById('settingsTabstripShell');
  var indicator = document.getElementById('settingsTabIndicator');
  var panes     = document.getElementById('settingsPanes');
  var embedWrap = document.getElementById('settingsEmbedWrap');
  var embedFrame= document.getElementById('settingsEmbedFrame');
  var searchInp = document.getElementById('settingsTabSearch');
  if (!strip || !panes) return;

  var tabs = Array.prototype.slice.call(strip.querySelectorAll('.settings-tab'));
  var loadedEmbedUrl = null;

  function paneFor(key) { return panes.querySelector('.settings-pane[data-pane="' + key + '"]'); }

  function moveIndicator(tab) {
    if (!indicator) return;
    if (!tab || tab.getAttribute('data-kind') === 'external') { indicator.style.width = '0'; return; }
    // offsetLeft/Width قياسات فيزيائية نسبةً لمحتوى التمرير — صحيحة حتى في RTL.
    indicator.style.width = tab.offsetWidth + 'px';
    indicator.style.left  = tab.offsetLeft + 'px';
  }

  function showEmbed(url) {
    if (!embedWrap || !embedFrame) return;
    panes.querySelectorAll('.settings-pane.is-active').forEach(function (p) { p.classList.remove('is-active'); });
    embedWrap.style.display = '';
    if (loadedEmbedUrl !== url) {
      embedWrap.classList.add('is-loading');
      embedFrame.src = url;
      loadedEmbedUrl = url;
    }
  }

  function showPane(key) {
    if (embedWrap) embedWrap.style.display = 'none';
    var target = paneFor(key);
    panes.querySelectorAll('.settings-pane.is-active').forEach(function (p) { p.classList.remove('is-active'); });
    if (target) target.classList.add('is-active');
  }

  function syncUrl(key) {
    try {
      var url = new URL(window.location.href);
      url.searchParams.set('tab', key);
      window.history.replaceState({}, '', url);
    } catch (e) {}
  }

  function select(tab, opts) {
    opts = opts || {};
    var kind = tab.getAttribute('data-kind');
    var key  = tab.getAttribute('data-tab');

    if (kind === 'external') {
      // يفتح في تبويب جديد — لا يغيّر الحالة النشطة.
      window.open(tab.getAttribute('href') || tab.getAttribute('data-embed-url'), '_blank', 'noopener');
      return;
    }

    tabs.forEach(function (t) { t.setAttribute('aria-selected', String(t === tab)); });
    moveIndicator(tab);

    if (kind === 'embed') {
      showEmbed(tab.getAttribute('data-embed-url'));
    } else {
      showPane(key);
    }
    syncUrl(key);
    if (!opts.silent) tab.scrollIntoView({ inline: 'center', block: 'nearest' });
  }

  // ── أحداث النقر ──
  tabs.forEach(function (t) {
    t.addEventListener('click', function (e) {
      if (t.getAttribute('data-kind') === 'external') return; // اترك السلوك الافتراضي للرابط
      e.preventDefault();
      select(t);
    });
  });

  // ── أزرار تفتح أداة داخل الإطار المُضمَّن مع إبقاء تبويبها نشطاً (نسخ يدوي/استعادة) ──
  panes.querySelectorAll('[data-embed-open]').forEach(function (btn) {
    btn.addEventListener('click', function (e) {
      e.preventDefault();
      showEmbed(btn.getAttribute('data-embed-open'));
    });
  });

  // ── لوحة المفاتيح (أسهم/Home/End) ──
  strip.addEventListener('keydown', function (e) {
    if (['ArrowLeft', 'ArrowRight', 'Home', 'End'].indexOf(e.key) === -1) return;
    var visible = tabs.filter(function (t) { return t.style.display !== 'none'; });
    if (!visible.length) return;
    e.preventDefault();
    var cur = visible.findIndex(function (t) { return t.getAttribute('aria-selected') === 'true'; });
    if (cur < 0) cur = 0;
    var next = cur;
    if (e.key === 'Home') next = 0;
    else if (e.key === 'End') next = visible.length - 1;
    else { var dir = e.key === 'ArrowRight' ? -1 : 1; next = (cur + dir + visible.length) % visible.length; } // RTL
    var t = visible[next];
    if (t.getAttribute('data-kind') !== 'external') select(t);
    t.focus();
  });

  // ── البحث الفوري ──
  if (searchInp) {
    searchInp.addEventListener('input', function () {
      var q = this.value.trim();
      tabs.forEach(function (t) {
        t.style.display = (!q || t.textContent.indexOf(q) !== -1) ? '' : 'none';
      });
      var active = tabs.find(function (t) { return t.getAttribute('aria-selected') === 'true'; });
      if (active && active.style.display !== 'none') moveIndicator(active);
      else if (indicator) indicator.style.width = '0';
    });
  }

  // ── حواف التلاشي عند فيض الشريط ──
  function updateOverflow() {
    if (!shell) return;
    var max = strip.scrollWidth - strip.clientWidth - 1;
    var sl  = Math.abs(strip.scrollLeft);
    shell.classList.toggle('is-overflow-end', sl < max);
    shell.classList.toggle('is-overflow-start', sl > 4);
  }
  strip.addEventListener('scroll', updateOverflow);
  window.addEventListener('resize', function () {
    var a = tabs.find(function (t) { return t.getAttribute('aria-selected') === 'true'; });
    if (a) moveIndicator(a);
    updateOverflow();
  });

  // ── ارتفاع الإطار المُضمَّن ──
  window.addEventListener('message', function (e) {
    if (e.origin !== window.location.origin) return;
    if (!e.data || e.data.type !== 'settings-embed-height') return;
    if (embedFrame && e.data.height) embedFrame.style.height = Math.max(340, e.data.height) + 'px';
    if (embedWrap) embedWrap.classList.remove('is-loading');
  });
  if (embedFrame) {
    embedFrame.addEventListener('load', function () {
      if (embedWrap) embedWrap.classList.remove('is-loading');
    });
  }

  // ── التهيئة: التبويب النشط من ?tab أو الأول ──
  function initialTab() {
    var q; try { q = new URL(window.location.href).searchParams.get('tab'); } catch (e) { q = null; }
    var byQuery = q && tabs.find(function (t) { return t.getAttribute('data-tab') === q && t.getAttribute('data-kind') !== 'external'; });
    return byQuery || tabs.find(function (t) { return t.getAttribute('aria-selected') === 'true'; }) || tabs[0];
  }
  var first = initialTab();
  if (first) select(first, { silent: true });
  updateOverflow();
})();
