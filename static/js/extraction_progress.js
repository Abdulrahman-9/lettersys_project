/* شريط تقدّم الاستخراج: الورقة مكشوفة، والنسبة من مراحل الأنبوب الفعليّة.
 *
 * مصدر المراحل طريقان يغذّيان معالجاً واحداً: البثّ، وسؤالٌ دوريّ قصير. البثّ قد يُحتجَز
 * حتى نهايته في طريقه إلى المتصفّح (مقيس 2026-11-03: Chromium وEdge استلما استجابة خادمٍ
 * تجريبيّ كاملةً في آخرها)، والسؤال القصير لا يُحتجَز. وإن لم تصل مرحلةٌ أصلاً يبقى الشريط
 * تقديراً زمنيّاً معلَناً بعبارة عامّة، ولا يدّعي مرحلةً لم يسمع بها.
 */
(function () {
  'use strict';

  // الأوزان من بثٍّ حقيقيّ لمستندٍ ممسوح (2026-11-03، n=1) — تُعايَر عند توفّر عيّنةٍ أوسع.
  const SEGMENTS = [
    { label: 'تجهيز', weight: 6, stages: ['cache_check', 'image_enhancement'] },
    { label: 'قراءة النص', weight: 49, stages: ['ocr', 'ocr_azure_fallback'] },
    { label: 'مطابقة الجهات', weight: 19, stages: ['pattern_matching', 'entity_matching'] },
    { label: 'قراءة الرقم', weight: 26, stages: ['handwritten_number', 'confidence'] },
  ];
  const READING_SEGMENT = 1;
  const TICK_MS = 120;
  const POLL_MS = 500;
  const DEFAULT_EXPECTED_MS = 6000;
  const MIN_RECORDED_MS = 1500;            // ما دونه كاش — لا يمثّل مدّة استخراج
  const HISTORY_KEY = 'lettersys_extract_ms';
  const HISTORY_SIZE = 8;
  const BLIND_CEILING = 0.92;              // بلا أحداث: لا يبلغ النهاية قبل وصول النتيجة
  const SEGMENT_CEILING = 0.96;            // داخل المرحلة: لا يكملها قبل حدث التالية
  const EASE = 2.4;
  const SLOW_FACTOR = 1.5;
  const DONE_LINGER_MS = 2200;
  const REDUCED_MOTION = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  const TOTAL_WEIGHT = SEGMENTS.reduce((sum, s) => sum + s.weight, 0);
  const SEGMENT_OF_STAGE = {};
  let consumed = 0;
  SEGMENTS.forEach((s, i) => {
    s.from = consumed / TOTAL_WEIGHT;
    consumed += s.weight;
    s.to = consumed / TOTAL_WEIGHT;
    s.stages.forEach((stage) => { SEGMENT_OF_STAGE[stage] = i; });
  });

  function readHistory() {
    try {
      const saved = JSON.parse(localStorage.getItem(HISTORY_KEY) || '[]');
      return Array.isArray(saved) ? saved.filter(Number.isFinite) : [];
    } catch (_) {
      return [];
    }
  }

  function expectedDuration() {
    const history = readHistory().sort((a, b) => a - b);
    return history.length ? history[Math.floor(history.length / 2)] : DEFAULT_EXPECTED_MS;
  }

  function recordDuration(ms) {
    if (ms < MIN_RECORDED_MS) return;
    try {
      localStorage.setItem(HISTORY_KEY, JSON.stringify([...readHistory(), Math.round(ms)].slice(-HISTORY_SIZE)));
    } catch (_) { /* تخزينٌ محجوب: يبقى الافتراضيّ */ }
  }

  function newProgressId() {
    return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 12)}`;
  }

  function fieldCountText(n) {
    if (n === 1) return 'حقل واحد';
    if (n === 2) return 'حقلان';
    return n <= 10 ? `${n} حقول` : `${n} حقلاً`;
  }

  function displayedValue(field) {
    if (field.tagName === 'SELECT') return field.selectedOptions[0]?.textContent?.trim() || '';
    return String(field.value || '').trim();
  }

  class ExtractionProgress {
    constructor({ onStop }) {
      this._onStop = onStop;
      this._dom = null;
      this._run = 0;
      this._active = false;
      this._tickTimer = null;
      this._pollTimer = null;
      this._lingerTimer = null;
      this._beam = null;
      this._stamp = null;
    }

    get running() { return this._active; }

    /** يبدأ جولة جديدة ويعيد رقمها؛ كلُّ إنهاءٍ يحمل رقمه فلا تُنهي جولةٌ قديمةٌ جولةً أحدث. */
    start() {
      this._buildDom();
      this._clearTimers();
      this._removeMarks();
      this._run += 1;
      this._active = true;
      this._value = 0;
      this._percent = -1;
      this._segment = -1;
      this._flights = 0;
      this._stageLabel = '';
      this._startedAt = performance.now();
      this._segmentAt = this._startedAt;
      this._expectedMs = expectedDuration();
      this._dom.strip.hidden = false;
      this._dom.stop.hidden = false;
      this._addBeam();
      this._render();
      this._tickTimer = setInterval(() => this._tick(), TICK_MS);
      return this._run;
    }

    /** يبدأ السؤال الدوريّ ويعيد المعرّف الذي يُرسَل مع طلب الاستخراج. */
    beginPolling(baseUrl, onEvent) {
      const run = this._run;
      const progressId = newProgressId();
      const url = `${baseUrl}${progressId}/`;
      let lastStage = null;
      let inFlight = false;
      const isCurrent = () => run === this._run && this._active;
      const ask = async () => {
        if (inFlight || !isCurrent()) return;
        inFlight = true;
        try {
          const response = await fetch(url, {
            credentials: 'same-origin',
            headers: { 'X-Requested-With': 'XMLHttpRequest' },
          });
          if (!response.ok) return;
          const { event } = await response.json();
          if (event && event.stage !== lastStage && isCurrent()) {
            lastStage = event.stage;
            onEvent(event);
          }
        } catch (_) {
          /* انقطاعٌ عابر: السؤال التالي أو البثّ يعوّضان */
        } finally {
          inFlight = false;
        }
      };
      this._pollTimer = setInterval(ask, POLL_MS);
      return progressId;
    }

    onStage(stage, label) {
      if (!this._active) return;
      const segment = SEGMENT_OF_STAGE[stage];
      if (segment === undefined || segment < this._segment) return;
      if (segment > this._segment) {
        this._segment = segment;
        this._segmentAt = performance.now();
      }
      this._stageLabel = label || SEGMENTS[segment].label;
      if (segment > READING_SEGMENT) this._removeBeam();
      this._render();
    }

    /** outcome: done | empty | stopped | error | cancel. لا أثر له إن انتهت الجولة أو حلّت محلّها أحدث. */
    end(outcome, count = 0, run = this._run) {
      if (run !== this._run || !this._active) return;
      this._active = false;
      this._clearTimers();
      this._removeBeam();
      if (outcome !== 'done') {
        this._dom.strip.hidden = true;
        return;
      }
      recordDuration(performance.now() - this._startedAt);
      this._value = 1;
      this._segment = SEGMENTS.length;
      this._render();
      this._dom.stage.textContent = `جاهز للمراجعة · ${fieldCountText(count)}`;
      this._dom.eta.textContent = '';
      this._dom.stop.hidden = true;
      this._addStamp();
      this._lingerTimer = setTimeout(() => {
        this._dom.strip.hidden = true;
        this._removeMarks();
      }, DONE_LINGER_MS);
    }

    /** يطير ما استُخرج من الورقة إلى حقله. */
    fly(field) {
      if (REDUCED_MOTION || !this._active) return;
      const text = displayedValue(field);
      const sheet = document.getElementById('modalBody')?.getBoundingClientRect();
      const target = field.getBoundingClientRect();
      if (!text || !sheet || !target.width || target.bottom < 0 || target.top > window.innerHeight) return;
      const startX = sheet.left + sheet.width / 2;
      const startY = sheet.top + sheet.height * 0.3;
      const dx = target.left + target.width / 2 - startX;
      const dy = target.top + target.height / 2 - startY;
      const chip = document.createElement('div');
      chip.className = 'xp-fly';
      chip.textContent = text.length > 40 ? `${text.slice(0, 40)}…` : text;
      chip.style.left = `${startX}px`;
      chip.style.top = `${startY}px`;
      document.body.appendChild(chip);
      const flight = chip.animate([
        { transform: 'translate(-50%, -50%) scale(1)', opacity: 1 },
        { transform: `translate(calc(-50% + ${dx}px), calc(-50% + ${dy}px)) scale(.92)`, opacity: 0.85 },
      ], { duration: 620, delay: this._flights * 90, easing: 'cubic-bezier(.45,.05,.25,1)', fill: 'backwards' });
      this._flights += 1;
      flight.onfinish = () => {
        chip.remove();
        field.classList.add('xp-land');
        field.addEventListener('animationend', () => field.classList.remove('xp-land'), { once: true });
      };
    }

    _buildDom() {
      if (this._dom) return;
      const byId = (id) => document.getElementById(id);
      const dom = {
        strip: byId('extractProgress'),
        pct: byId('xpPct'),
        stage: byId('xpStage'),
        eta: byId('xpEta'),
        stop: byId('xpStop'),
        track: byId('xpTrack'),
        steps: byId('xpSteps'),
        fills: [],
        segs: [],
        stepEls: [],
      };
      SEGMENTS.forEach((s) => {
        const seg = document.createElement('div');
        seg.className = 'xp-seg';
        seg.style.flex = `${s.weight} 1 0`;
        const fill = document.createElement('div');
        fill.className = 'xp-fill';
        seg.appendChild(fill);
        dom.track.appendChild(seg);
        dom.segs.push(seg);
        dom.fills.push(fill);
        const step = document.createElement('span');
        step.className = 'xp-step';
        step.textContent = s.label;
        dom.steps.appendChild(step);
        dom.stepEls.push(step);
      });
      dom.stop.addEventListener('click', () => this._onStop());
      this._dom = dom;
    }

    _tick() {
      this._value = Math.max(this._value, this._estimate());
      this._render();
    }

    _estimate() {
      const now = performance.now();
      if (this._segment < 0) {
        return BLIND_CEILING * (1 - Math.exp(-EASE * (now - this._startedAt) / this._expectedMs));
      }
      const { from, to } = SEGMENTS[this._segment];
      const expected = (to - from) * this._expectedMs;
      return from + (to - from) * SEGMENT_CEILING * (1 - Math.exp(-EASE * (now - this._segmentAt) / expected));
    }

    _render() {
      const dom = this._dom;
      SEGMENTS.forEach((s, i) => {
        const fill = Math.min(1, Math.max(0, (this._value - s.from) / (s.to - s.from)));
        dom.fills[i].style.width = `${(fill * 100).toFixed(1)}%`;
        dom.segs[i].classList.toggle('is-cur', i === this._segment);
        dom.stepEls[i].classList.toggle('is-cur', i === this._segment);
        dom.stepEls[i].classList.toggle('is-ok', i < this._segment);
      });
      const percent = Math.round(this._value * 100);
      if (percent !== this._percent) {
        this._percent = percent;
        dom.pct.textContent = `${percent}%`;
        dom.track.setAttribute('aria-valuenow', String(percent));
      }
      const stageText = this._stageLabel ? `يجري ${this._stageLabel}…` : 'يجري تحليل المستند…';
      if (dom.stage.textContent !== stageText) dom.stage.textContent = stageText;
      const etaText = this._etaText();
      if (dom.eta.textContent !== etaText) dom.eta.textContent = etaText;
    }

    _etaText() {
      const elapsed = performance.now() - this._startedAt;
      const remaining = this._expectedMs - elapsed;
      if (remaining >= 1000) return `نحو ${Math.ceil(remaining / 1000)} ث`;
      return elapsed > this._expectedMs * SLOW_FACTOR ? 'أطول من المعتاد' : '';
    }

    _addBeam() {
      const sheet = document.getElementById('modalBody');
      if (!sheet || REDUCED_MOTION) return;
      const beam = document.createElement('div');
      beam.className = 'xp-beam';
      beam.style.setProperty('--xp-travel', `${Math.max(0, sheet.clientHeight - 3)}px`);
      sheet.appendChild(beam);
      this._beam = beam;
    }

    _removeBeam() {
      this._beam?.remove();
      this._beam = null;
    }

    _addStamp() {
      const sheet = document.getElementById('modalBody');
      if (!sheet) return;
      const stamp = document.createElement('div');
      stamp.className = 'xp-stamp';
      stamp.textContent = 'جاهز للمراجعة';
      sheet.appendChild(stamp);
      this._stamp = stamp;
    }

    _removeMarks() {
      this._removeBeam();
      this._stamp?.remove();
      this._stamp = null;
    }

    _clearTimers() {
      clearInterval(this._tickTimer);
      clearInterval(this._pollTimer);
      clearTimeout(this._lingerTimer);
      this._tickTimer = this._pollTimer = this._lingerTimer = null;
    }
  }

  window.ExtractionProgress = ExtractionProgress;
})();
