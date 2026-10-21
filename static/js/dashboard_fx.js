/* اللوحة المتقدّمة: جسيماتُ الترحيب · الشرارات · العدّ · لوحةُ الأوامر (Ctrl+K). بلا مكتبات. */
(function () {
  'use strict';
  var calm = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  // شرارةُ كلّ بلاطة: سبعةُ أيّامٍ من اليمين (الأقدم) إلى اليسار (اليوم) لأنّ القراءة RTL
  document.querySelectorAll('svg.db-spark[data-spark]').forEach(function (svg) {
    var vals = (svg.getAttribute('data-spark') || '').split(',').map(Number).filter(function (v) { return !isNaN(v); });
    if (vals.length < 2) return;
    var max = Math.max.apply(null, vals) || 1;
    var step = 100 / (vals.length - 1);
    var pts = vals.map(function (v, i) { return [100 - i * step, 22 - (v / max) * 20]; });
    var line = pts.map(function (p, i) { return (i ? 'L' : 'M') + p[0].toFixed(1) + ' ' + p[1].toFixed(1); }).join(' ');
    var ns = 'http://www.w3.org/2000/svg';
    var area = document.createElementNS(ns, 'path');
    area.setAttribute('class', 'a');
    area.setAttribute('d', line + ' L0 24 L100 24 Z');
    var path = document.createElementNS(ns, 'path');
    path.setAttribute('class', 'l');
    path.setAttribute('d', line);
    svg.appendChild(area);
    svg.appendChild(path);
  });

  // العدّ التصاعديّ للأرقام الكبيرة — النصّ النهائيّ موجودٌ أصلاً في HTML
  if (!calm && 'IntersectionObserver' in window) {
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        if (!e.isIntersecting) return;
        io.unobserve(e.target);
        var el = e.target, end = parseInt(el.textContent.replace(/[^\d]/g, ''), 10);
        if (!end || end < 2) return;
        var t0 = null, dur = 900;
        (function tick(t) {
          t0 = t0 || t;
          var k = Math.min(1, (t - t0) / dur);
          el.textContent = Math.round(end * (1 - Math.pow(1 - k, 3))).toLocaleString('en-US').replace(/,/g, '');
          if (k < 1) requestAnimationFrame(tick); else el.textContent = String(end);
        })(performance.now());
      });
    });
    document.querySelectorAll('.db-page .db-n[data-has], .db-flow-n').forEach(function (el) { io.observe(el); });
  }

  // جسيماتُ الترحيب الذهبيّة — تتوقّف خارج الشاشة وعند إخفاء التبويب
  var canvas = document.querySelector('.db-hero-fx');
  if (canvas && !calm && canvas.getContext) {
    var ctx = canvas.getContext('2d'), dots = [], w = 0, h = 0, raf = 0, visible = true;
    var resize = function () {
      var r = canvas.getBoundingClientRect(), dpr = Math.min(window.devicePixelRatio || 1, 2);
      w = r.width; h = r.height;
      canvas.width = w * dpr; canvas.height = h * dpr;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      var n = Math.round(Math.min(48, w / 22));
      dots = [];
      for (var i = 0; i < n; i++) {
        dots.push({ x: Math.random() * w, y: Math.random() * h, r: .6 + Math.random() * 1.8, vx: (Math.random() - .5) * .25, vy: -.1 - Math.random() * .3, a: .25 + Math.random() * .55 });
      }
    };
    var frame = function () {
      ctx.clearRect(0, 0, w, h);
      for (var i = 0; i < dots.length; i++) {
        var d = dots[i];
        d.x += d.vx; d.y += d.vy;
        if (d.y < -4) { d.y = h + 4; d.x = Math.random() * w; }
        if (d.x < -4) d.x = w + 4; else if (d.x > w + 4) d.x = -4;
        ctx.beginPath();
        ctx.arc(d.x, d.y, d.r, 0, 6.283);
        ctx.fillStyle = 'rgba(224,184,74,' + d.a + ')';
        ctx.fill();
      }
      raf = requestAnimationFrame(frame);
    };
    var run = function () { cancelAnimationFrame(raf); if (visible && !document.hidden) raf = requestAnimationFrame(frame); };
    resize();
    window.addEventListener('resize', function () { resize(); });
    document.addEventListener('visibilitychange', run);
    if ('IntersectionObserver' in window) {
      new IntersectionObserver(function (es) { visible = es[0].isIntersecting; run(); }).observe(canvas);
    } else { run(); }
  }

  // لوحةُ الأوامر
  var dlg = document.getElementById('db-palette');
  if (!dlg || typeof dlg.showModal !== 'function') return;
  var q = dlg.querySelector('[data-palette-q]');
  var items = Array.prototype.slice.call(dlg.querySelectorAll('.db-palette-list li'));
  var active = -1;
  var norm = function (s) {
    return (s || '').toLowerCase().replace(/[\u064B-\u0652\u0640]/g, '').replace(/[أإآ]/g, 'ا').replace(/ى/g, 'ي').replace(/ة/g, 'ه').trim();
  };
  var shown = function () { return items.filter(function (li) { return !li.hidden; }); };
  var mark = function (i) {
    var list = shown();
    items.forEach(function (li) { li.classList.remove('is-active'); li.removeAttribute('aria-selected'); });
    active = list.length ? (i + list.length) % list.length : -1;
    if (active >= 0) {
      list[active].classList.add('is-active');
      list[active].setAttribute('aria-selected', 'true');
      list[active].scrollIntoView({ block: 'nearest' });
    }
  };
  var open = function () {
    if (dlg.open) return;
    q.value = '';
    items.forEach(function (li) { li.hidden = false; });
    dlg.showModal();
    mark(-1);
    active = -1;
    q.focus();
  };
  document.querySelectorAll('[data-palette-open]').forEach(function (b) { b.addEventListener('click', open); });
  document.addEventListener('keydown', function (e) {
    if ((e.ctrlKey || e.metaKey) && (e.key === 'k' || e.key === 'K')) { e.preventDefault(); open(); }
  });
  q.addEventListener('input', function () {
    var term = norm(q.value);
    items.forEach(function (li) { li.hidden = !!term && norm(li.textContent).indexOf(term) === -1; });
    active = -1;
    items.forEach(function (li) { li.classList.remove('is-active'); });
  });
  q.addEventListener('keydown', function (e) {
    if (e.key === 'ArrowDown') { e.preventDefault(); mark(active + 1); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); mark(active - 1); }
    else if (e.key === 'Enter' && active >= 0) {
      var link = shown()[active] && shown()[active].querySelector('a');
      if (link) { e.preventDefault(); window.location.href = link.href; }
    }
  });
  dlg.addEventListener('click', function (e) { if (e.target === dlg) dlg.close(); });
})();
