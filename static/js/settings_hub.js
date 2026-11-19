/* ============================================================
   مركز الإعدادات — الشريطُ واللوحات (عرضٌ وحده، بلا منطقٍ في الخادم)
   • لوحاتٌ مُدمَجة (عام · الإشعارات · الأمان · الذكاء الاصطناعيّ): تبديلٌ لحظيّ بلا تحميل.
   • أداتان ثقيلتان (العدّادات · الشبكة): تُحمَّلان داخل إطار (?embed=1) بلا مغادرة المركز.
   • اللوحُ المنزلق تحت النشط من المكوّن المشترك (data-lx-tabs ← js/lx_tabs.js): هنا تُقلب
     aria-selected وحدها، ومراقِبُه هناك يلحق بها — لا مؤشّرَ ثانياً هنا.
   • ?tab= يُزامَن عبر history · بحثٌ فوريّ يتسامح مع التشكيل · أسهمُ لوحة المفاتيح (RTL) ·
     تبويبٌ واحدٌ في ترتيب Tab (نمطُ ARIA) · معاينةُ الشريط العلويّ في «عام» تتبع ما يُكتب.
   ============================================================ */
(function () {
  'use strict';

  var strip      = document.getElementById('settingsTabstrip');
  var shell      = document.getElementById('settingsTabstripShell');
  var panes      = document.getElementById('settingsPanes');
  var embedWrap  = document.getElementById('settingsEmbedWrap');
  var embedFrame = document.getElementById('settingsEmbedFrame');
  var searchInp  = document.getElementById('settingsTabSearch');
  var searchNote = document.getElementById('settingsSearchEmpty');
  if (!strip || !panes) return;

  var tabs = Array.prototype.slice.call(strip.querySelectorAll('.settings-tab'));
  var loadedEmbedUrl = null;
  var reducedMotion = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)');

  function isShown(t) { return t.style.display !== 'none'; }
  function activeTab() { return tabs.find(function (t) { return t.getAttribute('aria-selected') === 'true'; }); }
  function paneFor(key) { return panes.querySelector('.settings-pane[data-pane="' + key + '"]'); }

  // تبويبٌ واحدٌ في ترتيب Tab: النشط، أو أوّلُ ظاهرٍ إن أخفاه البحث — والأسهمُ تتنقّل بينها
  function syncTabStops() {
    var active = activeTab();
    var stop = active && isShown(active) ? active : tabs.filter(isShown)[0];
    tabs.forEach(function (t) { t.tabIndex = t === stop ? 0 : -1; });
  }

  // يُظهر التبويبَ داخل الشريط وحده (لا تتحرّك الصفحة). في الهاتف كان ?tab=ai يُفتح وتبويبُه خارجَ الشاشة
  function reveal(tab, smooth) {
    var s = strip.getBoundingClientRect();
    var r = tab.getBoundingClientRect();
    var delta = (r.left + r.width / 2) - (s.left + s.width / 2);
    if (Math.abs(delta) < 2) return;
    var animate = smooth && !(reducedMotion && reducedMotion.matches);
    strip.scrollTo({ left: strip.scrollLeft + delta, behavior: animate ? 'smooth' : 'auto' });
  }

  function hidePanes() {
    panes.querySelectorAll('.settings-pane.is-active').forEach(function (p) { p.classList.remove('is-active'); });
  }

  function embedLoaded() {
    if (!embedWrap) return;
    embedWrap.classList.remove('is-loading');
    embedWrap.removeAttribute('aria-busy');
  }

  function showEmbed(tab) {
    if (!embedWrap || !embedFrame) return;
    var url = tab.getAttribute('data-embed-url');
    hidePanes();
    embedWrap.style.display = '';
    // لوحةٌ واحدة لتبويبين: اسمُها وعنوانُ إطارها من التبويب الذي فتحها
    embedWrap.setAttribute('aria-labelledby', tab.id);
    embedFrame.title = tab.textContent.trim();
    if (loadedEmbedUrl !== url) {
      embedWrap.classList.add('is-loading');
      embedWrap.setAttribute('aria-busy', 'true');
      embedFrame.src = url;
      loadedEmbedUrl = url;
    }
  }

  function showPane(key) {
    if (embedWrap) embedWrap.style.display = 'none';
    hidePanes();
    var target = paneFor(key);
    if (target) target.classList.add('is-active');
  }

  function syncUrl(key) {
    try {
      var url = new URL(window.location.href);
      url.searchParams.set('tab', key);
      window.history.replaceState({}, '', url);
    } catch (e) { /* عنوانٌ لا يُبنى: يبقى كما هو */ }
  }

  function select(tab, opts) {
    opts = opts || {};
    tabs.forEach(function (t) { t.setAttribute('aria-selected', String(t === tab)); });
    syncTabStops();
    if (tab.getAttribute('data-kind') === 'embed') showEmbed(tab);
    else showPane(tab.getAttribute('data-tab'));
    syncUrl(tab.getAttribute('data-tab'));
    reveal(tab, !opts.silent);
  }

  tabs.forEach(function (t) {
    t.addEventListener('click', function (e) {
      e.preventDefault();
      select(t);
    });
  });

  // ── لوحة المفاتيح (أسهم/Home/End) — في RTL السهمُ الأيمن إلى السابق ──
  strip.addEventListener('keydown', function (e) {
    if (['ArrowLeft', 'ArrowRight', 'Home', 'End'].indexOf(e.key) === -1) return;
    var visible = tabs.filter(isShown);
    if (!visible.length) return;
    e.preventDefault();
    var cur = visible.indexOf(activeTab());
    if (cur < 0) cur = 0;
    var next = cur;
    if (e.key === 'Home') next = 0;
    else if (e.key === 'End') next = visible.length - 1;
    else next = (cur + (e.key === 'ArrowRight' ? -1 : 1) + visible.length) % visible.length;
    select(visible[next]);
    visible[next].focus();
  });

  // ── البحث الفوريّ: بلا تشكيلٍ ولا همزات («العدادات» تجد «العدّادات») ──
  function norm(s) {
    return s.replace(/[ً-ٰٟـ]/g, '').replace(/[أإآ]/g, 'ا').replace(/ى/g, 'ي').replace(/ة/g, 'ه');
  }

  if (searchInp) {
    searchInp.addEventListener('input', function () {
      var raw = this.value.trim();
      var q = norm(raw);
      var shown = 0;
      tabs.forEach(function (t) {
        var hit = !q || norm(t.textContent).indexOf(q) !== -1;
        t.style.display = hit ? '' : 'none';
        if (hit) shown++;
      });
      // اللوحُ المشترك يراقب class وaria-selected لا style: إعادةُ وسم النشط تعيد قياسَه بعد تبدّل المواضع
      var active = activeTab();
      if (active) active.setAttribute('aria-selected', 'true');
      syncTabStops();
      if (searchNote) searchNote.textContent = shown ? '' : 'لا قسمَ يطابق «' + raw + '».';
      updateOverflow();
    });
  }

  // ── حافّتا التلاشي عند فيض الشريط (scrollLeft سالبٌ في RTL) ──
  function updateOverflow() {
    if (!shell) return;
    var max = strip.scrollWidth - strip.clientWidth - 1;
    var sl = Math.abs(strip.scrollLeft);
    shell.classList.toggle('is-overflow-end', sl < max);
    shell.classList.toggle('is-overflow-start', sl > 4);
  }
  strip.addEventListener('scroll', updateOverflow, { passive: true });
  window.addEventListener('resize', updateOverflow);

  // ── ارتفاع الإطار المُضمَّن (تبلّغه الصفحةُ المضمَّنة من base.html) ──
  window.addEventListener('message', function (e) {
    if (e.origin !== window.location.origin) return;
    if (!e.data || e.data.type !== 'settings-embed-height') return;
    if (embedFrame && e.data.height) embedFrame.style.height = Math.max(340, e.data.height) + 'px';
    embedLoaded();
  });
  if (embedFrame) embedFrame.addEventListener('load', embedLoaded);

  // ── معاينةُ الشريط العلويّ: تتبع الحقلَ، وتعود إلى ما يعرضه الشريطُ حين يُترك فارغاً ──
  document.querySelectorAll('[data-brand-preview]').forEach(function (out) {
    var input = document.getElementById(out.getAttribute('data-brand-preview'));
    if (!input) return;
    var fallback = out.getAttribute('data-fallback') || '';
    input.addEventListener('input', function () { out.textContent = input.value.trim() || fallback; });
  });

  // ── التهيئة: التبويب من ?tab (والخادمُ علّمه سلفاً) أو الأول ──
  function initialTab() {
    var q;
    try { q = new URL(window.location.href).searchParams.get('tab'); } catch (e) { q = null; }
    var byQuery = q && tabs.find(function (t) { return t.getAttribute('data-tab') === q; });
    return byQuery || activeTab() || tabs[0];
  }
  var first = initialTab();
  if (first) select(first, { silent: true });
  updateOverflow();

  // خطُّ Cairo قد يكتمل بعد التهيئة فتتّسع التبويبات: في الهاتف بقي التبويبُ الأخير مقصوصاً وحافّتا
  // الفيض على قياسٍ قديم. بعد اكتماله يُعاد إظهارُ النشط، وإعادةُ وسمه تجعل اللوحَ المشترك يعيد قياسه
  if (document.fonts && document.fonts.ready) {
    document.fonts.ready.then(function () {
      var active = activeTab();
      if (active) {
        active.setAttribute('aria-selected', 'true');
        reveal(active, false);
      }
      updateOverflow();
    });
  }
})();
