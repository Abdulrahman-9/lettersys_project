/* ══════════════════════════════════════════════════════════════════
   قصاصةُ الهامش — اسحب مستطيلاً على صورة الصفحة.

   الهامشُ توجيهُ المدير بخطّ يده. نسخُه نصّاً يفقد اليدَ والتوقيع؛ وقصُّه
   صورةً يحفظ الأصل. والقصاصةُ **مؤشّرٌ لا نسخة**: نخزّن كسوراً من 0 إلى 1
   وصفحةً ومرفقاً — لا بكسلات ولا ملفّاً جديداً.

   بلا إطارِ عمل: النظامُ خادمُ قوالبَ وJS خام.
   ══════════════════════════════════════════════════════════════════ */
(function () {
  'use strict';

  var MIN_FRACTION = 0.02;   /* أصغرُ من هذا نقرةٌ طائشة لا تحديد */

  function clamp01(v) { return v < 0 ? 0 : (v > 1 ? 1 : v); }

  function MarginCrop(root) {
    this.root   = root;
    this.stage  = root.querySelector('[data-crop-stage]');
    this.img    = root.querySelector('[data-crop-image]');
    this.rect   = root.querySelector('[data-crop-rect]');
    this.input  = root.querySelector('[data-crop-value]');
    this.hint   = root.querySelector('[data-crop-hint]');
    this.clear  = root.querySelector('[data-crop-clear]');
    this.pageIn = root.querySelector('[data-crop-page]');

    this.dragging = false;
    this.origin = null;
    this.value = null;

    if (!this.stage || !this.img || !this.rect || !this.input) return;
    this._bind();
  }

  MarginCrop.prototype._bind = function () {
    var self = this;

    /* Pointer Events تُغطّي الفأرةَ واللمسَ والقلمَ بمسارٍ واحد — ولا مسارَ
       ثانٍ يُنسى عند الصيانة. */
    this.stage.addEventListener('pointerdown', function (e) {
      if (!self.img.complete || !self.img.naturalWidth) return;
      self.dragging = true;
      self.stage.setPointerCapture(e.pointerId);
      self.origin = self._point(e);
      self._draw(self.origin, self.origin);
      e.preventDefault();
    });

    this.stage.addEventListener('pointermove', function (e) {
      if (!self.dragging) return;
      self._draw(self.origin, self._point(e));
    });

    var finish = function (e) {
      if (!self.dragging) return;
      self.dragging = false;
      try { self.stage.releasePointerCapture(e.pointerId); } catch (_) {}
      self._commit(self.origin, self._point(e));
    };
    this.stage.addEventListener('pointerup', finish);
    this.stage.addEventListener('pointercancel', finish);

    if (this.clear) {
      this.clear.addEventListener('click', function () { self.reset(); });
    }
    if (this.pageIn) {
      this.pageIn.addEventListener('change', function () { self._loadPage(); });
    }
  };

  /** موضعُ المؤشّر ككسرٍ من الصورة — لا بالبكسل. */
  MarginCrop.prototype._point = function (e) {
    var box = this.img.getBoundingClientRect();
    return {
      x: clamp01((e.clientX - box.left) / Math.max(box.width, 1)),
      y: clamp01((e.clientY - box.top) / Math.max(box.height, 1))
    };
  };

  MarginCrop.prototype._draw = function (a, b) {
    var x = Math.min(a.x, b.x), y = Math.min(a.y, b.y);
    var w = Math.abs(b.x - a.x), h = Math.abs(b.y - a.y);
    this.rect.style.left   = (x * 100) + '%';
    this.rect.style.top    = (y * 100) + '%';
    this.rect.style.width  = (w * 100) + '%';
    this.rect.style.height = (h * 100) + '%';
    this.rect.hidden = false;
  };

  MarginCrop.prototype._commit = function (a, b) {
    var x = Math.min(a.x, b.x), y = Math.min(a.y, b.y);
    var w = Math.abs(b.x - a.x), h = Math.abs(b.y - a.y);

    if (w < MIN_FRACTION || h < MIN_FRACTION) {
      /* نقرةٌ لا سحب: لا نُخزّن قصاصةً بلا مساحة — ولا نصمت عنها. */
      this.reset();
      this._say('اسحب مستطيلاً حول الهامش — النقرةُ وحدها لا تُحدّد شيئاً.');
      return;
    }

    this.value = {
      page: this.pageIn ? parseInt(this.pageIn.value, 10) || 1 : 1,
      attachment: parseInt(this.root.getAttribute('data-attachment') || '0', 10) || null,
      x: +x.toFixed(5), y: +y.toFixed(5),
      w: +w.toFixed(5), h: +h.toFixed(5)
    };
    this.input.value = JSON.stringify(this.value);
    this._say('حُدِّد الهامش — يُحفظ مع التفريق.');
  };

  MarginCrop.prototype.reset = function () {
    this.value = null;
    this.input.value = '';
    this.rect.hidden = true;
    this._say('اسحب لتحديد الهامش على الصفحة.');
  };

  MarginCrop.prototype._say = function (text) {
    if (this.hint) this.hint.textContent = text;
  };

  MarginCrop.prototype._loadPage = function () {
    /* الرابطُ يأتي من `{% url %}` بصفحةٍ أولى، فيُبدَّل رقمُها وحده — ولا
       يُركَّب مسارٌ في JS: تغييرُ التوجيه في `urls.py` يكسر المركَّب صامتاً. */
    var base = this.root.getAttribute('data-page-url');
    if (!base) return;
    var page = parseInt(this.pageIn.value, 10) || 1;
    this.img.src = base.replace(/\/\d+\.webp$/, '/' + page + '.webp');
    this.reset();
  };

  /** القيمةُ الحاليّة — يقرؤها مُرسِلُ الحواريّة. */
  MarginCrop.prototype.get = function () { return this.value; };

  document.addEventListener('DOMContentLoaded', function () {
    document.querySelectorAll('[data-margin-crop]').forEach(function (root) {
      root.__marginCrop = new MarginCrop(root);
    });
  });

  window.MarginCrop = MarginCrop;
})();
