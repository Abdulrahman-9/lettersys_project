/**
 * ReservationManager — نظام حجز أرقام القيود
 *
 * السيناريو:
 *  1. المستخدم يبدأ الكتابة → حجز تلقائي في الخلفية
 *  2. تُعرض شارة "محجوز" مع عداد تنازلي
 *  3. عند التراجع → مودال: قفل أو احتفاظ
 *  4. عند إطفاء المتصفح → بعد عودته يُسأل إذا كان قد كتب الرقم
 *  5. عند الحفظ → يُرسل reservation_id مع بيانات الكتاب
 */

(function () {
  'use strict';

  const URLS = {
    reserve:    '/books/api/reservation/reserve/',
    void:       '/books/api/reservation/void/',
    reactivate: '/books/api/reservation/reactivate/',
    status:     '/books/api/reservation/status/',
  };
  const EXPIRE_WARN_SECS = 5 * 60; // تحذير عند 5 دقائق متبقية

  // ─── CSRF ────────────────────────────────────────────────────────────────
  function getCsrf() {
    const m = document.cookie.match(/csrftoken=([^;]+)/);
    return m ? m[1] : '';
  }

  async function apiPost(url, body) {
    const r = await fetch(url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': getCsrf(),
        'X-Requested-With': 'XMLHttpRequest',
      },
      body: JSON.stringify(body),
    });
    return r.json();
  }

  async function apiGet(url, params = {}) {
    const qs = new URLSearchParams(params).toString();
    const r = await fetch(`${url}?${qs}`, {
      headers: { 'X-Requested-With': 'XMLHttpRequest' }
    });
    return r.json();
  }

  // ─── ReservationManager ──────────────────────────────────────────────────
  class ReservationManager {
    constructor(options = {}) {
      this.kindGetter      = options.kindGetter || (() => 'incoming_internal');
      this.onReserved      = options.onReserved || null;   // cb(reservation)
      this.onVoided        = options.onVoided   || null;   // cb(reservation)
      this.onExpired       = options.onExpired  || null;   // cb(reservation)
      this.badgeEl         = options.badgeEl    || null;   // عنصر الشارة
      this.numberFieldEl   = options.numberFieldEl || null; // حقل الرقم

      this._reservation    = null;
      this._timerInterval  = null;
      this._reserving      = false; // لمنع الطلبات المتزامنة
      this._triggered      = false; // تم الحجز مرة؟

      this._buildModal();
      this._checkOnLoad();
    }

    // ── الحجز التلقائي عند الكتابة ─────────────────────────────────────────
    async triggerReserve() {
      if (this._triggered || this._reserving || this._reservation) return;
      this._reserving = true;
      try {
        const data = await apiPost(URLS.reserve, { kind: this.kindGetter() });
        if (data.success) {
          this._reservation = data.reservation;
          this._triggered   = true;
          this._startTimer();
          this._updateBadge('reserved');
          this._updateNumberField(data.reservation.formatted);
          if (this.onReserved) this.onReserved(data.reservation);
          if (!data.already_reserved) {
            this._showToast(`✅ تم حجز القيد ${data.reservation.formatted} لك`, 'success');
          }
        }
      } catch (e) {
        console.warn('[Reservation] reserve error:', e);
      } finally {
        this._reserving = false;
      }
    }

    // ── إلغاء الحجز (قفل) ─────────────────────────────────────────────────
    async voidReservation(note = '') {
      if (!this._reservation) return;
      try {
        const data = await apiPost(URLS.void, {
          reservation_id: this._reservation.id,
          note
        });
        if (data.success) {
          const old = this._reservation;
          this._reset();
          if (this.onVoided) this.onVoided(old);
          this._showToast(`🔒 تم قفل القيد ${old.formatted} وتسجيله كملغي`, 'warning');
        }
      } catch (e) {
        console.warn('[Reservation] void error:', e);
      }
    }

    // ── إعادة تفعيل ────────────────────────────────────────────────────────
    async reactivateReservation(resId) {
      try {
        const data = await apiPost(URLS.reactivate, { reservation_id: resId });
        if (data.success) {
          this._reservation = data.reservation;
          this._triggered   = true;
          this._startTimer();
          this._updateBadge('reserved');
          this._updateNumberField(data.reservation.formatted);
          if (this.onReserved) this.onReserved(data.reservation);
          this._showToast(`♻️ تم إعادة تفعيل القيد ${data.reservation.formatted}`, 'info');
        }
      } catch (e) {
        console.warn('[Reservation] reactivate error:', e);
      }
    }

    // ── إغلاق الحجز بعد الحفظ ──────────────────────────────────────────────
    markUsed() {
      this._clearTimer();
      this._reservation = null;
      this._triggered   = false;
      this._updateBadge('idle');
      this._updateNumberField('---');
    }

    // ── الحصول على reservation_id للإرسال مع الحفظ ─────────────────────────
    getReservationId() {
      return this._reservation ? this._reservation.id : null;
    }

    getFormattedNumber() {
      return this._reservation ? this._reservation.formatted : null;
    }

    // ── فحص عند تحميل الصفحة ───────────────────────────────────────────────
    async _checkOnLoad() {
      try {
        const data = await apiGet(URLS.status, { kind: this.kindGetter() });

        if (data.has_reservation) {
          this._reservation = data.reservation;
          this._triggered   = true;
          this._startTimer();
          this._updateBadge('reserved');
          this._updateNumberField(data.reservation.formatted);
          if (this.onReserved) this.onReserved(data.reservation);
          return;
        }

        // هل انتهت صلاحية حجز قديم؟ اسأل المستخدم
        if (data.expired_reservation) {
          this._showExpiredModal(data.expired_reservation);
        } else if (data.preview_number) {
          this._updateNumberField(data.preview_number + ' ⏳', true);
        }
      } catch {}
    }

    // ── العداد التنازلي ─────────────────────────────────────────────────────
    _startTimer() {
      this._clearTimer();
      this._timerInterval = setInterval(() => {
        if (!this._reservation) { this._clearTimer(); return; }
        const sec = this._reservation.remaining_seconds - Math.floor(
          (Date.now() - new Date(this._reservation.reserved_at).getTime()) / 1000
          + (45 * 60 - this._reservation.remaining_seconds)
        );
        const remaining = this._calcRemaining();

        if (remaining <= 0) {
          this._clearTimer();
          const old = this._reservation;
          this._reset();
          this._updateBadge('expired');
          if (this.onExpired) this.onExpired(old);
          this._showExpiredModal(old);
          return;
        }

        // تحديث العداد في الشارة
        this._updateBadgeTimer(remaining);

        // تحذير قبل 5 دقائق
        if (remaining === EXPIRE_WARN_SECS) {
          this._showToast(`⚠️ سينتهي حجز القيد ${this._reservation.formatted} خلال 5 دقائق`, 'warning');
        }
      }, 1000);
    }

    _calcRemaining() {
      if (!this._reservation) return 0;
      const exp  = new Date(this._reservation.expires_at).getTime();
      const diff = Math.floor((exp - Date.now()) / 1000);
      return Math.max(0, diff);
    }

    _clearTimer() {
      if (this._timerInterval) {
        clearInterval(this._timerInterval);
        this._timerInterval = null;
      }
    }

    _reset() {
      this._reservation   = null;
      this._triggered     = false;
      this._clearTimer();
    }

    // ── تحديث UI ────────────────────────────────────────────────────────────
    _updateBadge(state) {
      const el = this.badgeEl;
      if (!el) return;
      el.className = 'reservation-badge reservation-badge--' + state;
      const icons  = { idle: '⏳', reserved: '🔒', expired: '⚠️' };
      const labels = { idle: 'في انتظار الحجز', reserved: '', expired: 'انتهت الصلاحية' };
      el.querySelector('.badge-icon').textContent  = icons[state]  || '';
      el.querySelector('.badge-label').textContent = labels[state] || '';
      el.querySelector('.badge-number').textContent = this._reservation
        ? this._reservation.formatted : '---';
      el.querySelector('.badge-timer').textContent = '';
    }

    _updateBadgeTimer(sec) {
      const el = this.badgeEl;
      if (!el) return;
      const m = Math.floor(sec / 60).toString().padStart(2, '0');
      const s = (sec % 60).toString().padStart(2, '0');
      const timerEl = el.querySelector('.badge-timer');
      if (timerEl) timerEl.textContent = `⏱ ${m}:${s}`;

      // لون أحمر إذا أقل من دقيقة
      el.classList.toggle('reservation-badge--urgent', sec < 60);
    }

    _updateNumberField(val, muted = false) {
      const el = this.numberFieldEl;
      if (!el) return;
      el.value = val;
      el.style.color  = muted ? '#a0956a' : '';
      el.style.fontWeight = muted ? 'normal' : '700';
    }

    // ── مودال التراجع ────────────────────────────────────────────────────────
    _buildModal() {
      // مودال التراجع
      const cancelModal = document.createElement('div');
      cancelModal.id    = 'reservationCancelModal';
      cancelModal.innerHTML = `
        <div class="res-modal-overlay">
          <div class="res-modal-box" dir="rtl">
            <div class="res-modal-icon">⚠️</div>
            <h3 class="res-modal-title">لديك قيد محجوز</h3>
            <p class="res-modal-sub" id="resCancelDesc"></p>
            <div class="res-modal-actions">
              <button class="res-btn res-btn--danger" id="resBtnVoid">
                🔒 قفل هذا القيد والبدء بقيد جديد
              </button>
              <button class="res-btn res-btn--info" id="resBtnKeep">
                ♻️ احتفظ بالقيد واستخدمه لاحقاً
              </button>
            </div>
          </div>
        </div>`;
      document.body.appendChild(cancelModal);
      this._cancelModal = cancelModal;

      // مودال انتهاء الصلاحية
      const expiredModal = document.createElement('div');
      expiredModal.id    = 'reservationExpiredModal';
      expiredModal.innerHTML = `
        <div class="res-modal-overlay">
          <div class="res-modal-box" dir="rtl">
            <div class="res-modal-icon">🕐</div>
            <h3 class="res-modal-title">انتهت صلاحية القيد المحجوز</h3>
            <p class="res-modal-sub" id="resExpiredDesc"></p>
            <p class="res-modal-question">هل كتبت هذا الرقم على وثيقة رسمية؟</p>
            <div class="res-modal-actions">
              <button class="res-btn res-btn--primary" id="resBtnReactivate">
                نعم — أريد استخدام هذا القيد
              </button>
              <button class="res-btn res-btn--ghost" id="resBtnNewNumber">
                لا — ابدأ بقيد جديد
              </button>
            </div>
          </div>
        </div>`;
      document.body.appendChild(expiredModal);
      this._expiredModal = expiredModal;

      this._injectStyles();
    }

    showCancelModal(note = '') {
      if (!this._reservation) return;
      const r = this._reservation;
      document.getElementById('resCancelDesc').textContent =
        `القيد المحجوز: ${r.formatted} — ماذا تريد أن تفعل؟`;

      this._cancelModal.style.display = 'flex';

      document.getElementById('resBtnVoid').onclick = async () => {
        this._cancelModal.style.display = 'none';
        await this.voidReservation(note);
        this._triggered = false;
        // أحجز جديداً تلقائياً إذا كان المستخدم لا يزال يكتب
      };
      document.getElementById('resBtnKeep').onclick = () => {
        this._cancelModal.style.display = 'none';
        this._showToast(`♻️ القيد ${r.formatted} محفوظ لك حتى ${this._formatExpiry()}`, 'info');
      };
    }

    _showExpiredModal(r) {
      document.getElementById('resExpiredDesc').textContent =
        `القيد: ${r.formatted} — انتهت صلاحيته`;
      this._expiredModal.style.display = 'flex';

      document.getElementById('resBtnReactivate').onclick = async () => {
        this._expiredModal.style.display = 'none';
        await this.reactivateReservation(r.id);
      };
      document.getElementById('resBtnNewNumber').onclick = () => {
        this._expiredModal.style.display = 'none';
        this._triggered = false;
        this._updateBadge('idle');
      };
    }

    _formatExpiry() {
      if (!this._reservation) return '';
      return new Date(this._reservation.expires_at).toLocaleTimeString('ar-IQ');
    }

    // ── Toast ────────────────────────────────────────────────────────────────
    _showToast(msg, type = 'info') {
      if (window.ToastCenter) {
        window.ToastCenter.show(type, msg, { delay: 4000 });
      } else {
        console.info(`[Reservation Toast] ${msg}`);
      }
    }

    // ── CSS ──────────────────────────────────────────────────────────────────
    _injectStyles() {
      if (document.getElementById('reservation-styles')) return;
      const s = document.createElement('style');
      s.id = 'reservation-styles';
      s.textContent = `
        /* شارة الحجز */
        .reservation-badge {
          display: inline-flex; align-items: center; gap: 6px;
          padding: 5px 10px; border-radius: 20px; font-size: 0.82rem;
          font-weight: 600; border: 1.5px solid; transition: all .3s;
          white-space: nowrap;
        }
        .reservation-badge--idle {
          background: #f3ede3; border-color: #d4c5a9; color: #8a7560;
        }
        .reservation-badge--reserved {
          background: #ecfdf5; border-color: #6ee7b7; color: #065f46;
        }
        .reservation-badge--expired {
          background: #fff7ed; border-color: #fbbf24; color: #92400e;
        }
        .reservation-badge--urgent {
          background: #fef2f2; border-color: #fca5a5; color: #991b1b;
          animation: res-pulse 1s ease-in-out infinite;
        }
        @keyframes res-pulse {
          0%,100% { opacity:1; } 50% { opacity:.6; }
        }
        .badge-number { font-weight: 800; letter-spacing: 0.03em; }
        .badge-timer  { font-family: monospace; font-size: 0.78rem; }

        /* المودال */
        #reservationCancelModal, #reservationExpiredModal {
          display: none; position: fixed; inset: 0; z-index: 99999;
          background: rgba(0,0,0,0.55);
          align-items: center; justify-content: center;
        }
        .res-modal-overlay {
          display: flex; align-items: center; justify-content: center;
          width: 100%; height: 100%;
        }
        .res-modal-box {
          background: #fff; border-radius: 18px;
          box-shadow: 0 20px 60px rgba(0,0,0,0.25);
          padding: 32px 28px; max-width: 420px; width: 90%;
          text-align: center;
        }
        .res-modal-icon  { font-size: 2.5rem; margin-bottom: 10px; }
        .res-modal-title { font-size: 1.1rem; font-weight: 800; color: #1e293b; margin: 0 0 8px; }
        .res-modal-sub   { color: #64748b; font-size: 0.92rem; margin-bottom: 6px; }
        .res-modal-question { color: #92400e; font-weight: 700; font-size: 0.95rem; margin: 12px 0 20px; }
        .res-modal-actions { display: flex; flex-direction: column; gap: 10px; }
        .res-btn {
          padding: 11px 18px; border-radius: 10px; border: none;
          font-size: 0.9rem; font-weight: 700; cursor: pointer;
          transition: all .2s; font-family: inherit;
        }
        .res-btn--danger  { background: #fef2f2; color: #991b1b; border: 1.5px solid #fca5a5; }
        .res-btn--info    { background: #eff6ff; color: #1e40af; border: 1.5px solid #93c5fd; }
        .res-btn--primary { background: #ecfdf5; color: #065f46; border: 1.5px solid #6ee7b7; }
        .res-btn--ghost   { background: #f8fafc; color: #475569; border: 1.5px solid #cbd5e1; }
        .res-btn:hover    { filter: brightness(0.96); transform: translateY(-1px); }
      `;
      document.head.appendChild(s);
    }
  }

  window.ReservationManager = ReservationManager;

})();
