/**
 * ============================================
 * Extraction Smart Desktop JavaScript - Enhanced
 * نظام الاستخراج الذكي المحسّن
 * ============================================
 */

/**
 * عتبات الثقة الموحَّدة لألوان شارات الحقول — مصدر الحقيقة الدلالي خادمياً هو
 * ConfidenceAnalyzer (core/extraction/helpers.py): high ≥ 0.85، medium ≥ 0.65.
 * (كان JS سابقاً يستخدم 0.70 للـ medium، فيظهر لون مختلف لنفس القيمة بين الواجهة
 *  وتقرير المراجعة الخادمي — وحّدناه على 0.65.)
 * TODO: إعادة معايرة هذه العتبات بعد استقرار محرّك Tesseract الجديد (مقياس ثقته
 *       يختلف عن EasyOCR) — بالتنسيق مع نافذة تطوير المحرّك.
 */
const CONFIDENCE_THRESHOLDS = { high: 0.85, medium: 0.65 };

class ExtractionSmartSystem {
    constructor() {
        this.currentFile = null;
        this.scannedFiles = [];   // مصفوفة الصفحات الممسوحة (للدمج مع "مسح المزيد")
        // معاينة المستند الممسوح عبر صور الخادم (PyMuPDF) — تلائم اللوحة دائماً
        this.previewToken = null;
        this.pageCount = 1;
        this.currentPage = 1;
        this.zoom = 1;
        this.fitMode = 'width';   // 'width' = ملء عرض اللوحة (أكبر/أوضح، بلا هوامش جانبية) | 'page' = احتواء كامل
        this.previewDpi = 130;
        this.extractedData = {};
        this.confidenceScores = {};
        this.suggestions = {};
        this.suggestionCache = {};
        this.fallbackNotified = false;
        this.entityList = [];
        this.lang = 'ar';
        this.autoNumberEnabled = true;
        // Per-kind active reservation cache: { incoming_internal: {id, formatted, number,...}, ... }
        this.reservations = {};
        this.apiEndpoints = this.readApiEndpoints();
        this.documentTypeCatalog = this.readJsonScript('documentTypeCatalogData', {});
        this.documentTypeDefaults = this.readJsonScript('documentTypeDefaultsData', {});
        this.documentTypeSelectionByKind = {};
        this.documentTypeStorageKey = 'lettersys.documentTypeCustomByKind';
        this.customDocumentTypeCatalog = this.readStoredDocumentTypes();
        // وضع التعديل: مصدر واحد يُقرأ عند الإنشاء (قبل init) — وسم JSON للبيانات + سمة الجذر لوجهة العودة.
        // يُغني عن monkey-patch القالب لكشف الوضع في saveBook/ensureReservation.
        this._editData = this.readJsonScript('editBookData', null);
        this.backUrl = (document.querySelector('.extraction-container')?.dataset.backUrl) || '';
        this.messages = {
            ar: {
                uploadRequired: 'يرجى تحميل ملف أولاً',
                extractFail: 'تعذر الاستخراج',
                saveFail: 'تعذر الحفظ',
                saveSuccess: 'تم حفظ الكتاب بنجاح ✓',
                extractSuccess: 'تم استخراج البيانات بنجاح ✓',
                invalidFields: 'يرجى ملء جميع الحقول المطلوبة',
                fileType: 'نوع الملف غير مدعوم (صورة أو PDF فقط)',
                fileSize: 'حجم الملف أكبر من 10MB',
                fallbackSuggestions: 'يتم استخدام اقتراحات افتراضية',
                fallbackExtraction: 'تم استخدام وضع محاكاة'
            },
            en: {
                uploadRequired: 'Please upload a file first',
                extractFail: 'Extraction failed',
                saveFail: 'Save failed',
                saveSuccess: 'Book saved successfully ✓',
                extractSuccess: 'Extraction completed successfully ✓',
                invalidFields: 'Please fill all required fields',
                fileType: 'Unsupported file type',
                fileSize: 'File size exceeds 10MB',
                fallbackSuggestions: 'Using fallback suggestions',
                fallbackExtraction: 'Mock extraction used'
            }
        };
        this.init();
    }

    readApiEndpoints() {
        const container = document.querySelector('.extraction-container');
        const dataset = container ? container.dataset : {};

        return {
            smartExtractStream: dataset.smartExtractStreamEndpoint || '/books/api/extract/smart/stream/',
            entityList: dataset.entityListEndpoint || '/books/api/entity-list/',
            suggestions: dataset.suggestionsEndpoint || '/books/api/suggestions/',
            saveBook: dataset.saveBookEndpoint || '/books/api/book/save/',
            updateBook: dataset.updateBookEndpoint || '/books/api/book/update/',
            nextNumber: dataset.nextNumberEndpoint || '/books/api/next-number/',
            reservationReserve: dataset.reservationReserveEndpoint || '/books/api/reservation/reserve/',
            reservationVoid: dataset.reservationVoidEndpoint || '/books/api/reservation/void/',
            reservationStatus: dataset.reservationStatusEndpoint || '/books/api/reservation/status/',
            reservationHeartbeat: dataset.reservationHeartbeatEndpoint || '/books/api/reservation/heartbeat/'
        };
    }

    buildSuggestionsUrl(categoryKey) {
        const baseUrl = this.apiEndpoints.suggestions;
        const separator = baseUrl.includes('?') ? '&' : '?';
        return `${baseUrl}${separator}category=${encodeURIComponent(categoryKey)}`;
    }

    readJsonScript(scriptId, fallbackValue) {
        const scriptEl = document.getElementById(scriptId);
        if (!scriptEl) {
            return fallbackValue;
        }

        try {
            const parsed = JSON.parse(scriptEl.textContent || 'null');
            return parsed && typeof parsed === 'object' ? parsed : fallbackValue;
        } catch (error) {
            console.warn(`[ExtractionSmart] Failed to parse ${scriptId}:`, error);
            return fallbackValue;
        }
    }

    readStoredDocumentTypes() {
        try {
            const raw = window.localStorage.getItem(this.documentTypeStorageKey);
            if (!raw) {
                return {};
            }
            const parsed = JSON.parse(raw);
            return parsed && typeof parsed === 'object' ? parsed : {};
        } catch (error) {
            console.warn('[ExtractionSmart] Failed to read custom document types:', error);
            return {};
        }
    }

    persistStoredDocumentTypes() {
        try {
            window.localStorage.setItem(this.documentTypeStorageKey, JSON.stringify(this.customDocumentTypeCatalog));
        } catch (error) {
            console.warn('[ExtractionSmart] Failed to persist custom document types:', error);
        }
    }

    t(key) {
        return (this.messages[this.lang] && this.messages[this.lang][key]) || key;
    }

    getCurrentKind() {
        return document.getElementById('bookKind')?.value || 'incoming_internal';
    }

    getDocumentTypeOptions(kind) {
        const baseOptions = Array.isArray(this.documentTypeCatalog[kind]) && this.documentTypeCatalog[kind].length > 0
            ? this.documentTypeCatalog[kind]
            : ['مذكرة داخلية'];
        const customOptions = Array.isArray(this.customDocumentTypeCatalog[kind])
            ? this.customDocumentTypeCatalog[kind]
            : [];
        const mergedOptions = [...new Set([
            ...baseOptions.map((item) => String(item || '').trim()).filter(Boolean),
            ...customOptions.map((item) => String(item || '').trim()).filter(Boolean)
        ])];

        if (mergedOptions.length > 0) {
            return mergedOptions;
        }
        return ['مذكرة داخلية'];
    }

    getDefaultDocumentType(kind) {
        const options = this.getDocumentTypeOptions(kind);
        return this.documentTypeDefaults[kind] || options[0] || 'مذكرة داخلية';
    }

    isCustomDocumentTypeSelected() {
        return document.getElementById('documentTypeSelect')?.value === '__custom__';
    }

    toggleCustomDocumentTypeInput(shouldShow) {
        const customInput = document.getElementById('documentTypeCustom');
        if (!customInput) {
            return;
        }

        customInput.style.display = shouldShow ? 'block' : 'none';
        customInput.setAttribute('aria-hidden', shouldShow ? 'false' : 'true');

        if (!shouldShow) {
            customInput.value = '';
            customInput.classList.remove('has-error', 'is-valid');
        }
    }

    getResolvedDocumentTypeValue(kind = null) {
        const resolvedKind = kind || this.getCurrentKind();
        const select = document.getElementById('documentTypeSelect');
        const customInput = document.getElementById('documentTypeCustom');

        if (!select) {
            return this.getDefaultDocumentType(resolvedKind);
        }

        if (select.value === '__custom__') {
            return (customInput?.value || '').trim();
        }

        return (select.value || '').trim() || this.getDefaultDocumentType(resolvedKind);
    }

    rememberDocumentTypeState(kind = null) {
        const resolvedKind = kind || this.getCurrentKind();
        const value = this.getResolvedDocumentTypeValue(resolvedKind);

        if (value) {
            this.documentTypeSelectionByKind[resolvedKind] = value;
        } else {
            delete this.documentTypeSelectionByKind[resolvedKind];
        }
    }

    syncDocumentTypeControls(kind, preferredValue = null) {
        const select = document.getElementById('documentTypeSelect');
        const customInput = document.getElementById('documentTypeCustom');
        const hint = document.getElementById('documentTypeHint');

        if (!select) {
            return;
        }

        const options = this.getDocumentTypeOptions(kind);
        const defaultValue = this.getDefaultDocumentType(kind);
        const savedValue = this.documentTypeSelectionByKind[kind];
        const candidateValue = preferredValue != null ? String(preferredValue).trim() : (savedValue || '');
        const resolvedValue = candidateValue || defaultValue;
        const optionSet = new Set(options);

        select.innerHTML = '';
        options.forEach((label) => {
            const option = document.createElement('option');
            option.value = label;
            option.textContent = label;
            select.appendChild(option);
        });

        const customOption = document.createElement('option');
        customOption.value = '__custom__';
        customOption.textContent = 'نوع آخر...';
        select.appendChild(customOption);

        if (optionSet.has(resolvedValue)) {
            select.value = resolvedValue;
            this.toggleCustomDocumentTypeInput(false);
        } else {
            select.value = '__custom__';
            this.toggleCustomDocumentTypeInput(true);
            if (customInput) {
                customInput.value = resolvedValue;
            }
        }

        if (hint) {
            hint.textContent = `الافتراضي لهذا التبويب: ${defaultValue}. يمكنك تغييره من القائمة أو اختيار "نوع آخر..." لإدخال تصنيف جديد.`;
        }

        this.documentTypeSelectionByKind[kind] = resolvedValue;
        this.validateField('documentTypeSelect');
        this.validateField('documentTypeCustom');
    }

    handleDocumentTypeSelectionChange({ focusCustom = true } = {}) {
        const kind = this.getCurrentKind();
        const select = document.getElementById('documentTypeSelect');
        const customInput = document.getElementById('documentTypeCustom');

        if (!select) {
            return;
        }

        if (select.value === '__custom__') {
            this.toggleCustomDocumentTypeInput(true);
            const savedValue = this.documentTypeSelectionByKind[kind];
            const knownOptions = this.getDocumentTypeOptions(kind);

            if (customInput && savedValue && !knownOptions.includes(savedValue) && !customInput.value.trim()) {
                customInput.value = savedValue;
            }

            if (focusCustom && customInput) {
                customInput.focus();
                customInput.select();
            }
        } else {
            this.toggleCustomDocumentTypeInput(false);
            this.documentTypeSelectionByKind[kind] = select.value || this.getDefaultDocumentType(kind);
        }

        this.validateField('documentTypeSelect');
        this.validateField('documentTypeCustom');
    }

    setDocumentTypeValue(value, kind = null) {
        const resolvedKind = kind || this.getCurrentKind();
        const normalizedValue = String(value || '').trim();

        if (!normalizedValue) {
            delete this.documentTypeSelectionByKind[resolvedKind];
            this.syncDocumentTypeControls(resolvedKind, this.getDefaultDocumentType(resolvedKind));
            return;
        }

        this.documentTypeSelectionByKind[resolvedKind] = normalizedValue;
        this.syncDocumentTypeControls(resolvedKind, normalizedValue);
    }

    isRecoverableReservationError(data) {
        const code = data?.error_code;
        if (data?.refresh_reservation === true) {
            return true;
        }
        return [
            'INVALID_RESERVATION',
            'RESERVATION_EXPIRED',
            'RESERVATION_VOIDED',
            'RESERVATION_KIND_MISMATCH',
            'INVALID_RESERVATION_STATUS'
        ].includes(code);
    }

    updateFormDataReservation(formData, reservation) {
        const formattedNumber = reservation?.formatted || '';

        formData.delete('reservation_id');
        formData.delete('auto_number');
        formData.delete('our_number');
        formData.delete('book_number');

        if (reservation?.id) {
            formData.append('reservation_id', reservation.id);
        } else {
            formData.append('auto_number', this.autoNumberEnabled ? 'true' : 'false');
        }

        formData.append('our_number', formattedNumber);
        formData.append('book_number', formattedNumber);
    }

    async recoverReservationForRetry(kind, currentMessage) {
        const previousReservation = this.reservations[kind] || null;
        const previousNumber = previousReservation?.formatted || document.getElementById('bookNumber')?.value || '';

        delete this.reservations[kind];
        const bookNumberField = document.getElementById('bookNumber');
        if (bookNumberField) {
            delete bookNumberField.dataset.reservationId;
            bookNumberField.classList.remove('is-valid');
        }

        this.showToast(currentMessage || 'تغيّرت حالة الحجز الحالي. جارٍ طلب رقم قيد جديد...', 'warning', 4500);

        const reservation = await this.ensureReservation(kind);
        if (!reservation || !reservation.id) {
            return null;
        }

        const newNumber = reservation.formatted || '';
        if (newNumber && newNumber !== previousNumber) {
            this.showToast(`تم تحديث رقم القيد تلقائياً إلى ${newNumber} لاستكمال الحفظ.`, 'info', 5000);
        }

        return reservation;
    }

    addCustomDocumentType(kind, value) {
        const normalizedValue = String(value || '').trim();
        if (!normalizedValue) {
            return;
        }

        const baseOptions = Array.isArray(this.documentTypeCatalog[kind])
            ? this.documentTypeCatalog[kind].map((item) => String(item || '').trim()).filter(Boolean)
            : [];
        if (baseOptions.includes(normalizedValue)) {
            return;
        }

        const currentCustomOptions = Array.isArray(this.customDocumentTypeCatalog[kind])
            ? this.customDocumentTypeCatalog[kind].map((item) => String(item || '').trim()).filter(Boolean)
            : [];
        if (currentCustomOptions.includes(normalizedValue)) {
            return;
        }

        this.customDocumentTypeCatalog[kind] = [...currentCustomOptions, normalizedValue];
        this.persistStoredDocumentTypes();
    }

    init() {
        this.setupEventListeners();
        this.setupKeyboardShortcuts();
        this.setupTextUndo();
        this.loadSuggestions();
        this.loadEntityData();
        this.setupEntityCodeRecognition();
        this.setupKindControls();
        this.setupDueDateAutoCalculation();
        this.applyInitialContext();
        this.enhanceUIFeedback();
        this.checkScanToken();
        this._initScanAgent();
        this._setupAgentButton();
        this._setupAutoExtractToggle();
    }

    // ═══════ مفتاح الاستخراج التلقائي (تفعيل/إطفاء، مُخزَّن) ═══════
    /** هل يُشغَّل الاستخراج تلقائياً بعد رفع الملف؟ (افتراضياً نعم؛ يُخزَّن في localStorage). */
    _autoExtractEnabled() {
        return localStorage.getItem('lettersys_auto_extract') !== 'off';
    }

    _setupAutoExtractToggle() {
        const btn = document.getElementById('autoExtractToggle');
        if (!btn) return;
        const render = () => {
            const on = this._autoExtractEnabled();
            btn.classList.toggle('is-on', on);
            btn.classList.toggle('is-off', !on);
            btn.setAttribute('aria-checked', on ? 'true' : 'false');
            const lbl = btn.querySelector('.aet-label');
            if (lbl) lbl.textContent = on ? 'استخراج تلقائي' : 'استخراج يدوي';
        };
        render();
        btn.addEventListener('click', () => {
            const next = this._autoExtractEnabled() ? 'off' : 'on';
            localStorage.setItem('lettersys_auto_extract', next);
            render();
            this.showToast(
                next === 'on' ? 'الاستخراج التلقائي مفعّل — يُستخرَج فور رفع الملف.'
                              : 'الاستخراج التلقائي مُطفأ — أدخِل يدوياً أو اضغط «استخراج» وقتما تشاء.',
                'info', 4000);
        });
    }

    /** يحدّث مؤشّر حالة الوكيل (الحبّة الملوّنة) في رأس المعاينة.
     *  النصّ يُخفى بصرياً (نقطة فقط) فنمرّره أيضاً إلى title ليبقى مقروءاً بالتحويم. */
    setScanStatus(state, text) {
        const pill = document.getElementById('scanAgentStatus');
        if (pill) { pill.dataset.state = state; if (text) { pill.textContent = text; pill.title = text; } }
    }

    /** يعيد المؤشّر لحالة «جاهز: اسم الجهاز» إن كان هناك ماسح معروف. */
    _resetScanPill() {
        const devs = this._scanDevices || [];
        if (!devs.length) return;
        const sel = document.getElementById('scanDeviceSelect');
        const chosen = (sel && sel.value) || devs[0].id;
        const name = (devs.find(d => d.id === chosen) || devs[0]).name;
        this.setScanStatus('ready', 'جاهز: ' + name);
    }

    /**
     * يحدّد عنوان الوكيل العامل: يجرّب 127.0.0.1 ثم localhost (كلاهما مسموح في CSP
     * وCORS). يحلّ حالة حجب توجيه/بروكسي المتصفح لأحد المضيفين دون الآخر (مثلاً
     * التطبيق على localhost والبروكسي يحجب 127.0.0.1). يُخزَّن أوّل ناجح + استجابة health.
     */
    async _resolveAgentBase(td) {
        if (this._agentBase) return this._agentBase;
        let port = '17865';
        try { port = new URL(td.agent_url).port || '17865'; } catch (_) {}
        for (const base of [`http://127.0.0.1:${port}`, `http://localhost:${port}`]) {
            try {
                const r = await this._fetchWithTimeout(base + '/agent/health', {}, 5000);
                if (r.ok) { this._agentBase = base; this._agentHealth = await r.json(); return base; }
            } catch (_) { /* جرّب المضيف التالي */ }
        }
        return null;
    }

    // فحص جاهزية وكيل المسح المحلي وملء قائمة الأجهزة + المؤشّر (بلا مستمع نقر منافس).
    async _initScanAgent() {
        this._startAgentHealthMonitor();
        const select = document.getElementById('scanDeviceSelect');
        const setPill = (state, text) => this.setScanStatus(state, text);   // موحّد (يضبط النصّ + التلميح)
        const hideSelect = () => { if (select) select.style.display = 'none'; };
        this._scanDevices = [];
        try {
            const td = await (await this._fetchWithTimeout('/books/api/scan/agent-token/', { credentials: 'same-origin' }, 8000)).json();
            if (!td.available) { this._agentHealthy = false; setPill('unavailable', 'وكيل المسح غير مشغّل'); hideSelect(); return; }
            const agentBase = await this._resolveAgentBase(td);
            if (!agentBase) { this._agentHealthy = false; setPill('unavailable', 'تعذّر الاتصال بالوكيل'); hideSelect(); return; }
            const hd = this._agentHealth || {};
            if (!hd.naps2_available) { this._agentHealthy = false; setPill('no_naps2', 'NAPS2 غير مثبّت'); hideSelect(); return; }
            const dd = await (await this._fetchWithTimeout(agentBase + '/agent/devices', { headers: { 'X-LetterSys-Token': td.token } }, 20000)).json();
            this._scanDevices = dd.devices || [];
            if (!this._scanDevices.length) { this._agentHealthy = true; setPill('no_device', 'لا يوجد ماسح متصل'); hideSelect(); return; }
            if (select) {
                select.innerHTML = '';
                this._scanDevices.forEach(d => {
                    const o = document.createElement('option');
                    o.value = d.id; o.textContent = d.name;
                    select.appendChild(o);
                });
                const last = localStorage.getItem('lettersys_scan_device');
                if (last && this._scanDevices.some(d => d.id === last)) select.value = last;
                select.style.display = this._scanDevices.length > 1 ? '' : 'none';
                select.onchange = () => localStorage.setItem('lettersys_scan_device', select.value);
            }
            // المسح أوتوماتيكي بالكامل — لا خيارات جودة يدوية (وجهان/لون/تدوير).
            const chosen = (select && select.value) || this._scanDevices[0].id;
            const name = (this._scanDevices.find(d => d.id === chosen) || this._scanDevices[0]).name;
            this._agentHealthy = true;
            setPill('ready', 'جاهز: ' + name);
        } catch (e) {
            this._agentHealthy = false;
            setPill('unavailable', 'وكيل المسح غير مشغّل');
            hideSelect();
        }
    }

    /** مراقبة دورية لحالة الوكيل — تُنبّه باحترافية عند توقّفه أو عدم استجابته (وعند عودته). */
    _startAgentHealthMonitor() {
        if (this._agentMonitorTimer) return;
        this._agentMonitorTimer = setInterval(() => this._pollAgentHealth(), 25000);
    }

    async _pollAgentHealth() {
        // لا تُزعج أثناء مسح جارٍ
        const pill = document.getElementById('scanAgentStatus');
        if (pill && pill.dataset.state === 'scanning') return;

        let state = 'ready', title = '', msg = '';
        try {
            const td = await (await this._fetchWithTimeout('/books/api/scan/agent-token/', { credentials: 'same-origin' }, 5000)).json();
            if (!td.available) {
                state = 'unavailable'; title = 'توقّف وكيل المسح';
                msg = 'توقّف وكيل المسح المحلي أو أُغلق. شغّله لاستئناف المسح.';
            } else {
                const hd = await (await this._fetchWithTimeout(td.agent_url + '/agent/health', {}, 4000)).json();
                if (!hd.naps2_available) {
                    state = 'no_naps2'; title = 'NAPS2 غير مثبّت';
                    msg = 'برنامج المسح NAPS2 لم يعد متوفّراً على هذا الجهاز.';
                }
            }
        } catch (_) {
            state = 'unavailable'; title = 'وكيل المسح لا يستجيب';
            msg = 'توقّف وكيل المسح أو لا يستجيب. أعد تشغيله لاستئناف المسح.';
        }

        const wasHealthy = this._agentHealthy !== false;   // غير معروف ⇒ نعدّه سليماً
        const nowHealthy = state === 'ready';
        this._agentHealthy = nowHealthy;

        if (nowHealthy) {
            if (!wasHealthy) {
                this._resetScanPill();
                this.showToast('عاد وكيل المسح للعمل — يمكنك المسح الآن.', 'success', 4000, 'الماسح جاهز');
            }
        } else {
            this.setScanStatus(state, title);
            if (wasHealthy) this.showToast(msg, 'warning', 6000, title);   // نبّه عند التحوّل فقط
        }
    }

    // ═══════ زرّ حالة الوكيل + لوحة التعليمات لكل حالة ═══════
    /** يربط زرّ مؤشّر الحالة: نقرة تفتح/تغلق لوحة التعليمات، وأزرارها تُشغّل/تُعيد الفحص. */
    _setupAgentButton() {
        const btn = document.getElementById('scanAgentStatus');
        const help = document.getElementById('scanAgentHelp');
        if (!btn || !help) return;
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            if (help.hidden) this._openAgentHelp(); else this._closeAgentHelp();
        });
        document.addEventListener('click', (e) => {
            if (!help.hidden && !help.contains(e.target) && e.target !== btn) this._closeAgentHelp();
        });
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && !help.hidden) this._closeAgentHelp();
        });
        help.addEventListener('click', (e) => {
            const b = e.target.closest('[data-action]');
            if (!b) return;
            const act = b.dataset.action;
            if (act === 'recheck') this._recheckAgent();
            else if (act === 'start') this._startAgentAndVerify();
            else if (act === 'close') this._closeAgentHelp();
        });
    }

    _openAgentHelp() {
        const btn = document.getElementById('scanAgentStatus');
        const help = document.getElementById('scanAgentHelp');
        if (!help) return;
        this._renderAgentHelp(btn?.dataset.state || 'checking');
        help.hidden = false;
        btn?.setAttribute('aria-expanded', 'true');
        this._positionAgentHelp();
    }

    /** يضع اللوحة (fixed) قرب الزرّ ويقصُرها داخل الشاشة: فوقه إن اتّسع وإلا تحته، وأفقياً بلا خروج. */
    _positionAgentHelp() {
        const btn = document.getElementById('scanAgentStatus');
        const help = document.getElementById('scanAgentHelp');
        if (!btn || !help || help.hidden) return;
        const b = btn.getBoundingClientRect();
        const pw = help.offsetWidth, ph = help.offsetHeight, m = 8;
        const vw = window.innerWidth, vh = window.innerHeight;
        let top = b.top - ph - m;                                  // الأصل: فوق الزرّ
        if (top < m) top = Math.min(b.bottom + m, vh - ph - m);    // لا يتّسع فوق → تحته
        top = Math.max(m, top);
        let left = b.right - pw;                                   // RTL: حاذِ يمين اللوحة بيمين الزرّ
        left = Math.max(m, Math.min(left, vw - pw - m));           // اقصُر أفقياً داخل الشاشة
        help.style.top = top + 'px';
        help.style.left = left + 'px';
    }

    _closeAgentHelp() {
        const help = document.getElementById('scanAgentHelp');
        const btn = document.getElementById('scanAgentStatus');
        if (help) help.hidden = true;
        btn?.setAttribute('aria-expanded', 'false');
    }

    /** يبني محتوى اللوحة حسب الحالة: عنوان + شرح + خطوات مرقّمة + أزرار (تشغيل/إعادة فحص). */
    _renderAgentHelp(state) {
        const help = document.getElementById('scanAgentHelp');
        if (!help) return;
        const devs = this._scanDevices || [];
        let dev = '';
        if (devs.length) {
            const sel = document.getElementById('scanDeviceSelect');
            const chosen = (sel && sel.value) || devs[0].id;
            dev = (devs.find(d => d.id === chosen) || devs[0]).name;
        }
        const C = {
            checking:   { tone: 'info', title: 'جارٍ فحص وكيل المسح…',
                desc: 'نتحقّق من اتصال وكيل المسح والماسح الضوئي على هذا الجهاز.', steps: [], actions: [] },
            ready:      { tone: 'ok', title: 'الماسح جاهز',
                desc: dev ? `وكيل المسح متصل، والماسح «${dev}» جاهز. اضغط «مسح من السكانر» لبدء المسح.`
                          : 'وكيل المسح متصل وجاهز للمسح.', steps: [], actions: ['recheck'] },
            scanning:   { tone: 'busy', title: 'جارٍ المسح…',
                desc: 'يجري مسح المستند الآن — لا تُغلق النافذة حتى ينتهي.', steps: [], actions: [] },
            unavailable:{ tone: 'err', title: 'وكيل المسح غير مشغّل',
                desc: 'برنامج وكيل المسح المحلي متوقّف — وهو الوسيط الذي يشغّل الماسح الضوئي.', steps: [
                    'اضغط «شغّل الوكيل الآن» أدناه ليبدأ تلقائياً.',
                    'أو يدوياً: نفّذ <code>scan_agent\\run_agent.bat</code> من مجلد المشروع.',
                    'لتشغيله تلقائياً مع ويندوز: ضع اختصاره في <code>shell:startup</code> (Win+R).',
                ], actions: ['start', 'recheck'] },
            no_naps2:   { tone: 'err', title: 'برنامج NAPS2 غير مثبّت',
                desc: 'الوكيل يعمل، لكنه لا يجد NAPS2 — وهو محرّك المسح الفعلي.', steps: [
                    'نزّل NAPS2 من <code>naps2.com</code> وثبّته (الإعداد الافتراضي كافٍ).',
                    'بعد التثبيت أعد تشغيل وكيل المسح.',
                    'اضغط «إعادة الفحص».',
                ], actions: ['recheck'] },
            no_device:  { tone: 'err', title: 'لا يوجد ماسح متصل',
                desc: 'الوكيل وNAPS2 جاهزان، لكن لا يوجد ماسح ضوئي متّصل ومُكتشَف.', steps: [
                    'وصّل الماسح بمنفذ USB وشغّله (تأكّد أنه ليس نائماً).',
                    'تحقّق أن ويندوز يتعرّف عليه (لوحة التحكم ← الأجهزة والطابعات).',
                    'اضغط «إعادة الفحص».',
                ], actions: ['recheck'] },
        };
        const c = C[state] || C.checking;
        const label = { recheck: '<i class="bi bi-arrow-clockwise"></i> إعادة الفحص',
                        start: '<i class="bi bi-play-circle"></i> شغّل الوكيل الآن' };
        const cls = { recheck: 'sah-btn-ghost', start: 'sah-btn-primary' };
        const stepsHtml = c.steps.length
            ? `<ol class="sah-steps">${c.steps.map(s => `<li>${s}</li>`).join('')}</ol>` : '';
        const actionsHtml = c.actions.length
            ? `<div class="sah-actions">${c.actions.map(a =>
                `<button type="button" class="sah-btn ${cls[a]}" data-action="${a}">${label[a]}</button>`).join('')}</div>` : '';
        help.innerHTML =
            `<div class="sah-head ${c.tone}"><span class="sah-dot"></span>${c.title}` +
            `<button type="button" class="sah-close" data-action="close" aria-label="إغلاق">✕</button></div>` +
            `<p class="sah-desc">${c.desc}</p>${stepsHtml}${actionsHtml}`;
        if (!help.hidden) this._positionAgentHelp();   // الارتفاع تغيّر → أعِد القصّ داخل الشاشة
    }

    /** يعيد فحص الوكيل من الصفر (يمسح الكاش) ويحدّث المؤشّر واللوحة. */
    async _recheckAgent() {
        this.setScanStatus('checking', 'جارٍ فحص وكيل المسح…');
        this._renderAgentHelp('checking');
        this._agentBase = null; this._agentHealth = null;   // أعِد حلّ العنوان من الصفر
        await this._initScanAgent();
        const btn = document.getElementById('scanAgentStatus');
        this._renderAgentHelp(btn?.dataset.state || 'unavailable');
    }

    /** يطلب من الخادم تشغيل الوكيل المحلي، ثم ينتظر حياة المنفذ (حتى ~8ث) ويعيد الفحص. */
    async _startAgentAndVerify() {
        const help = document.getElementById('scanAgentHelp');
        const startBtn = help?.querySelector('[data-action="start"]');
        if (startBtn) { startBtn.disabled = true; startBtn.innerHTML = '<i class="bi bi-hourglass-split"></i> يجري التشغيل…'; }
        this.setScanStatus('checking', 'جارٍ تشغيل الوكيل…');
        try {
            const r = await fetch('/books/api/scan/agent-start/', {
                method: 'POST', headers: { 'X-CSRFToken': this.getCookie('csrftoken') }, credentials: 'same-origin',
            });
            const d = await r.json();
            if (!d.ok) {
                this.showToast(d.message || 'تعذّر تشغيل الوكيل', 'error', 6000, 'وكيل المسح');
                await this._recheckAgent(); return;
            }
        } catch (_) {
            this.showToast('تعذّر الاتصال بالخادم لتشغيل الوكيل.', 'error', 6000, 'وكيل المسح');
            await this._recheckAgent(); return;
        }
        // انتظر حتى يصير المنفذ حيّاً (الوكيل يستغرق لحظات للإقلاع)
        for (let i = 0; i < 8; i++) {
            await new Promise(res => setTimeout(res, 1000));
            try {
                const td = await (await this._fetchWithTimeout('/books/api/scan/agent-token/', { credentials: 'same-origin' }, 3000)).json();
                if (td.available) break;
            } catch (_) { /* استمر بالانتظار */ }
        }
        await this._recheckAgent();
        const st = document.getElementById('scanAgentStatus')?.dataset.state;
        if (st === 'ready' || st === 'no_device') this.showToast('تم تشغيل وكيل المسح.', 'success', 4000, 'وكيل المسح');
    }

    /**
     * إذا وُجد scan_token في URL (يُضاف بواسطة Hot Folder Watcher)،
     * يجلب البيانات المستخرجة مسبقاً ويملأ الحقول تلقائياً.
     */
    checkScanToken() {
        const params = new URLSearchParams(window.location.search);
        const token = params.get('scan_token');
        if (!token) return;
        // تنبيه مُخزَّن من مسار قديم كان يعيد التوجيه — إن وُجد
        let notice = null;
        try {
            notice = sessionStorage.getItem('lettersys_scan_notice');
            if (notice) sessionStorage.removeItem('lettersys_scan_notice');
        } catch (_) {}
        // نظّف الرمز من الـURL فوراً (بلا إعادة تحميل)
        window.history.replaceState({}, '', window.location.pathname);
        this._loadScanToken(token, { notice });
    }

    /**
     * يجلب بيانات scan_token، يملأ الحقول، ويعرض الملف الممسوح — بلا إعادة تحميل للصفحة.
     * يُستدعى من checkScanToken (رمز في الـURL) ومن startScan مباشرةً بعد المسح المحلي،
     * فيحفظ ما أدخله المستخدم قبل المسح بدل محوه بإعادة التحميل.
     */
    _loadScanToken(token, { notice = null } = {}) {
        this.scanToken = token;   // يُرسَل عند الحفظ لحلقة التقاط التدريب (نصّ OCR → الحقول)
        const tokenUrl = `/books/api/extract/scan-token/${encodeURIComponent(token)}/`;
        this._showProgressBanner('جاري تحميل بيانات المسح...');

        fetch(tokenUrl, { credentials: 'same-origin' })
            .then(r => r.json())
            .then(resp => {
                if (!resp.success || !resp.data) {
                    this._showProgressBanner('رمز المسح منتهي الصلاحية — يمكنك الرفع يدوياً', 'warning');
                    return;
                }
                const data = resp.data;
                this.extractedData = data;
                this._fillExtractionFields(data);
                // تنبيه (تأجيل الاستخراج/فشل OCR) له الأولوية على رسالة الثقة
                if (notice) {
                    this._showProgressBanner(notice, 'warning');
                } else if (data.extract_skipped) {
                    // المستخدم أطفأ الاستخراج التلقائي — رسالة صادقة بدل «ثقة 0%»
                    this._showProgressBanner(
                        'تم التقاط المستند — الاستخراج التلقائي مُطفأ. أدخِل الحقول يدوياً أو اضغط «استخراج».',
                        'info');
                } else {
                    this._showProgressBanner(
                        `تم تحميل بيانات المسح تلقائياً — ثقة ${Math.round((data.overall_confidence || 0) * 100)}%`,
                        data.needs_review ? 'warning' : 'success'
                    );
                }
                // تحميل وعرض الملف الممسوح في منطقة المعاينة (بدون إعادة OCR)
                // (الخادم لم يعد يُسرّب processed_path — يكشف has_file فقط)
                if (data.has_file || data.processed_path) {
                    // المعاينة تُرسَم كصور خادم عبر هذا الـtoken (تلائم اللوحة دائماً)
                    this.previewToken = token;
                    this.pageCount = data.page_count || 1;
                    this.currentPage = 1;
                    const fileUrl = `/books/api/scan/serve/${encodeURIComponent(token)}/`;
                    const fileName = data.source_file || 'scanned-document';
                    this.loadScannedFile(fileUrl, fileName, { noAutoExtract: true });
                }
            })
            .catch(err => {
                console.warn('[ScanToken] fetch error:', err);
                this._showProgressBanner('تعذّر تحميل بيانات المسح — يمكنك الرفع يدوياً', 'warning');
            });
    }

    _showProgressBanner(message, type = 'info') {
        let banner = document.getElementById('scanProgressBanner');
        if (!banner) {
            banner = document.createElement('div');
            banner.id = 'scanProgressBanner';
            banner.style.cssText = [
                'position:fixed;top:0;left:0;right:0;z-index:9999',
                'padding:10px 20px;text-align:center;font-weight:600',
                'transition:opacity 0.4s;direction:rtl',
            ].join(';');
            document.body.prepend(banner);
        }
        const colors = {
            info: '#1d4ed8',
            success: '#15803d',
            warning: '#b45309',
            error: '#dc2626',
        };
        banner.style.background = colors[type] || colors.info;
        banner.style.color = '#fff';
        banner.style.opacity = '1';
        banner.textContent = message;
        if (type !== 'info') {
            setTimeout(() => { banner.style.opacity = '0'; }, 5000);
        }
    }

    _fillExtractionFields(data) {
        this.beginTextUndoBatch?.();   // لقطة قبل التعبئة → يصير الاستخراج خطوة تراجع واحدة
        const setVal = (id, val) => {
            const el = document.getElementById(id);
            if (el && val != null && val !== '') el.value = val;
        };
        // ملاحظة DRY: هذا التعيين يوازي applyExtractionResult (مسار الرفع المباشر).
        // المعرّفات الصحيحة في القالب هي #date و #title (لا #bookDate/#bookTitle) —
        // الخلل هنا كان يمنع ملء التاريخ والعنوان نهائياً في مسار scan_token.
        // لم يُدمج المساران بعد لأن مُنتِج كاش scan_token قيد إعادة الكتابة في نافذة
        // أخرى (عقد القيمة المُخزَّنة غير مُجمَّد) — يُوحَّدان حين يستقرّ العقد.
        const dateOnly = (v) => (v ? String(v).slice(0, 10) : v);   // ISO بوقت → YYYY-MM-DD
        // رقم السجلّ اليدويّ يمرّ عبر مصالحة صريحة؛ وسلسلة النظام لا تُمسّ إطلاقاً.
        if (data.book_number != null && data.book_number !== '') {
            const numEl = document.getElementById('bookNumber');
            if (numEl && this._reconcileManualNumber(numEl, data.book_number, data.book_number_confidence)) {
                numEl.value = data.book_number;
            }
        }
        setVal('date', dateOnly(data.book_date));
        setVal('senderDate', dateOnly(data.sender_date));
        setVal('senderNumber', data.sender_number);
        setVal('title', data.title);
        setVal('secretLevel', data.secret_level);
        if (data.book_kind) {
            setVal('bookKind', data.book_kind);
        }
        if (data.issuing_entity) {
            const issuingInput = document.querySelector('[data-field="issuingEntity"] input, #issuingEntity');
            if (issuingInput) issuingInput.value = data.issuing_entity;
        }
        if (data.receiving_entity) {
            const receivingInput = document.querySelector('[data-field="receivingEntity"] input, #receivingEntity');
            if (receivingInput) receivingInput.value = data.receiving_entity;
        }
        // حافّة الثقة + بطاقتا P1 في مسار المسح أيضاً — البيانات مُصدَّرة في result_to_scan_data
        const confMap = {
            bookNumber: 'book_number_confidence',
            date: 'book_date_confidence',
            senderDate: 'sender_date_confidence',
            senderNumber: 'sender_number_confidence',
            title: 'title_confidence',
            secretLevel: 'secret_level_confidence',
            issuingEntity: 'issuing_entity_confidence',
            receivingEntity: 'receiving_entity_confidence',
        };
        Object.keys(confMap).forEach(fid => {
            const c = data[confMap[fid]];
            if (typeof c === 'number') this.setFieldConfidence(fid, c);
        });
        if (window.__autoGrowTitle) window.__autoGrowTitle();   // وسّع الموضوع لطول النصّ المملوء
        this.updateQualitySummary(data);
        this.renderEntityCandidates(data);
        this.endTextUndoBatch?.();

        if (data.needs_review) {
            console.info('[ScanToken] manual review recommended — confidence below threshold');
        }
    }

    getKindConfig(kind) {
        const configs = {
            incoming_internal: {
                label: 'وارد داخلي',
                direction: 'incoming',
                directionText: 'وارد',
                scopeText: 'داخلي',
                summaryCopy: 'مراسلة تدخل من وحدة أو قسم داخل المؤسسة وتحتاج رقم قيد داخلي مع تاريخ الجهة إذا كان مثبتاً على المستند.',
                numberPlanTitle: 'رقمنا + رقم الجهة الداخلية',
                numberPlanCopy: 'نُسجل رقم القيد الداخلي لدينا، ويمكن إضافة رقم الجهة المرسلة الداخلية للمطابقة المرجعية.',
                datePlanTitle: 'تاريخ القيد + تاريخ الجهة',
                datePlanCopy: 'تاريخنا هو تاريخ القيد الداخلي، مع إظهار تاريخ الجهة المرسلة لتوثيق تسلسل المراسلة.',
                bookNumberLabel: 'رقم القيد الوارد',
                bookNumberHint: 'الرقم الداخلي الذي نعتمد عليه عند تسجيل الوارد.',
                bookNumberPlaceholder: 'مثال: و/144',
                senderNumberLabel: 'العدد',
                senderNumberHint: 'رقم الجهة المرسلة — كما يظهر على كتابهم بعد «العدد /».',
                dateLabel: 'تاريخ القيد لدينا',
                dateHint: 'تاريخ إدخال الكتاب في سجل الوارد الداخلي.',
                senderDateLabel: 'تاريخ الجهة المرسلة',
                senderDateHint: 'تاريخ الكتاب كما صدر من الجهة الداخلية الأخرى.',
                propertiesCopy: 'الوارد الداخلي يعرض حقول رقم وتاريخ الجهة المرسلة لأنها جزء من التسلسل الداخلي.',
                showSenderFields: true,
            },
            incoming_external: {
                label: 'وارد خارجي',
                direction: 'incoming',
                directionText: 'وارد',
                scopeText: 'خارجي',
                summaryCopy: 'مراسلة تصل من جهة خارج المؤسسة، لذا نحتاج رقمنا الداخلي مع مرجع الجهة الخارجية وتاريخها.',
                numberPlanTitle: 'رقمنا + رقم الجهة الخارجية',
                numberPlanCopy: 'أدخل رقم القيد الوارد لدينا، وسجّل رقم الجهة الخارجية كما هو في المستند.',
                datePlanTitle: 'تاريخ القيد + تاريخ الصادر الخارجي',
                datePlanCopy: 'يحمل هذا المسار تاريخنا الداخلي مع إظهار تاريخ المستند لدى الجهة الخارجية للمطابقة.',
                bookNumberLabel: 'رقم القيد الوارد',
                bookNumberHint: 'رقمنا الداخلي المعتمد عند تسجيل الوارد الخارجي.',
                bookNumberPlaceholder: 'مثال: خ/203',
                senderNumberLabel: 'العدد',
                senderNumberHint: 'رقم الجهة الخارجية — كما يظهر في المستند/الختم بعد «العدد /».',
                dateLabel: 'تاريخ القيد لدينا',
                dateHint: 'تاريخ استلام الكتاب وتسجيله في المؤسسة.',
                senderDateLabel: 'تاريخ الجهة الخارجية',
                senderDateHint: 'تاريخ المستند الأصلي الصادر من الجهة الخارجية.',
                propertiesCopy: 'الوارد الخارجي يحتفظ بمرجع الجهة الخارجية وتاريخها إلى جانب رقمنا الداخلي.',
                showSenderFields: true,
            },
            outgoing_internal: {
                label: 'صادر داخلي',
                direction: 'outgoing',
                directionText: 'صادر',
                scopeText: 'داخلي',
                summaryCopy: 'مراسلة تصدر بين أقسام المؤسسة، ويكفي فيها رقمنا وتاريخنا دون الحاجة لمرجع صادر من جهة أخرى.',
                numberPlanTitle: 'رقمنا الداخلي فقط',
                numberPlanCopy: 'في الصادر الداخلي نعتمد رقم الإصدار الداخلي ولا نعرض رقم جهة مرسلة أخرى.',
                datePlanTitle: 'تاريخ الإصدار + المتابعة',
                datePlanCopy: 'يُعتمد تاريخنا كتاريخ إصدار، ويمكن إضافة متابعة إذا كان التنفيذ يحتاج زمناً لاحقاً.',
                bookNumberLabel: 'رقم الصادر الداخلي',
                bookNumberHint: 'رقم الإصدار المعتمد بين وحدات المؤسسة.',
                bookNumberPlaceholder: 'مثال: ص/88',
                senderNumberLabel: 'رقم الجهة المرسلة',
                senderNumberHint: '',
                dateLabel: 'تاريخ الإصدار',
                dateHint: 'التاريخ الرسمي لخروج الكتاب من القسم أو الوحدة.',
                senderDateLabel: 'تاريخ الجهة المرسلة',
                senderDateHint: '',
                propertiesCopy: 'الصادر الداخلي يركز على بيانات الإصدار الداخلي والمتابعة عند الحاجة.',
                showSenderFields: false,
            },
            outgoing_external: {
                label: 'صادر خارجي',
                direction: 'outgoing',
                directionText: 'صادر',
                scopeText: 'خارجي',
                summaryCopy: 'مراسلة تخرج إلى جهة خارجية، لذا نُبرز رقمنا وتاريخنا الرسميين مع متابعة التسليم أو الرد إن وجدت.',
                numberPlanTitle: 'رقم الصادر الرسمي',
                numberPlanCopy: 'في الصادر الخارجي نستخدم رقمنا الرسمي فقط لأنه المرجع الذي يُرسل إلى الخارج.',
                datePlanTitle: 'تاريخ الإرسال + المتابعة',
                datePlanCopy: 'تاريخنا هو تاريخ الإرسال الرسمي، ويمكن إدخال تاريخ متابعة للرد أو الإنجاز.',
                bookNumberLabel: 'رقم صادر مكتب السيد المدير العام',
                bookNumberHint: 'اكتبه كما هو على الكتاب، أو امسح المستند ليُقرأ تلقائياً. لا يولّده النظام.',
                bookNumberPlaceholder: 'مثال: 7436',
                senderNumberLabel: 'رقم الجهة المرسلة',
                senderNumberHint: '',
                dateLabel: 'تاريخ الإرسال',
                dateHint: 'تاريخ إصدار وإرسال الكتاب إلى الجهة الخارجية.',
                senderDateLabel: 'تاريخ الجهة المرسلة',
                senderDateHint: '',
                propertiesCopy: 'الصادر الخارجي لا يحتاج رقم جهة مرسلة، لكنه يحتاج صياغة متابعة واضحة إذا كان هناك رد منتظر.',
                showSenderFields: false,
                // هذا السجلّ **لا سلسلة له**: الرقم يصدر من مكتب المدير العام لا من النظام.
                // قياساً على البيانات الفعلية أرقامه (0, 109, 1555, 27189…) بلا تسلسل ولا
                // ترتيب، وتتكرّر — فحجز رقمٍ له من عدّادنا يخترع رقماً لا وجود له على الورق.
                manualNumber: true,
            },
        };

        return configs[kind] || configs.incoming_internal;
    }

    setupKindControls() {
        const kindSelect = document.getElementById('bookKind');
        const kindTabs = document.querySelectorAll('.kind-tab');

        if (!kindSelect) {
            return;
        }

        // Tab clicks (smooth navigation, preserves per-kind reservation)
        kindTabs.forEach((tab) => {
            tab.addEventListener('click', () => {
                kindSelect.value = tab.dataset.kind;
                this.syncKindUI(kindSelect.value);
            });
        });

        kindSelect.addEventListener('change', () => {
            this.syncKindUI(kindSelect.value);
        });
    }

    syncKindUI(kind) {
        const kindSelect = document.getElementById('bookKind');
        const config = this.getKindConfig(kind);
        const kindTabs = document.querySelectorAll('.kind-tab');
        const senderNumberGroup = document.getElementById('senderNumberGroup');
        const senderDateGroup = document.getElementById('senderDateGroup');
        const startScanButton = document.getElementById('startScanButton');
        const previousKind = kindSelect?.value;

        if (previousKind && previousKind !== kind) {
            this.rememberDocumentTypeState(previousKind);
        }

        if (kindSelect) {
            kindSelect.value = kind;
        }

        // Update tab active states
        kindTabs.forEach((tab) => {
            tab.classList.toggle('active', tab.dataset.kind === kind);
        });

        this.setText('bookNumberLabel', config.bookNumberLabel);
        this.setText('bookNumberHint', config.bookNumberHint);
        this.setText('senderNumberLabel', config.senderNumberLabel);
        this.setText('senderNumberHint', config.senderNumberHint);
        this.setText('dateLabel', config.dateLabel);
        this.setText('dateHint', config.dateHint);
        this.setText('senderDateLabel', config.senderDateLabel);
        this.setText('senderDateHint', config.senderDateHint);

        const bookNumber = document.getElementById('bookNumber');
        if (bookNumber) {
            bookNumber.placeholder = config.bookNumberPlaceholder;
            this.applyNumberMode(kind, config, bookNumber);
        }

        if (senderNumberGroup) {
            senderNumberGroup.classList.toggle('is-hidden', !config.showSenderFields);
        }
        if (senderDateGroup) {
            senderDateGroup.classList.toggle('is-hidden', !config.showSenderFields);
        }

        if (!config.showSenderFields) {
            const senderNumber = document.getElementById('senderNumber');
            const senderDate = document.getElementById('senderDate');
            if (senderNumber) senderNumber.value = '';
            if (senderDate) senderDate.value = '';
        }

        if (startScanButton) {
            startScanButton.classList.remove('btn-scanner-royal-incoming', 'btn-scanner-royal-outgoing');
            startScanButton.classList.add(config.direction === 'incoming' ? 'btn-scanner-royal-incoming' : 'btn-scanner-royal-outgoing');
        }

        this.syncDocumentTypeControls(kind);

        // Ensure a reservation exists for this kind (atomic, idempotent per session)
        this.ensureReservation(kind);
    }

    /**
     * ============================================
     * Reservation Logic — Professional Archival
     * ============================================
     * Per-kind atomic number reservation with smooth tab navigation.
     *
     * Flow:
     *  - Tab click → ensureReservation(kind):
     *      • If we have it cached → just paint the UI (preserves the held number)
     *      • Else → POST /reservation/reserve/ → cache → paint
     *  - On save → consume that reservation_id; clear cache; reserve fresh one
     *  - On manual clear → POST /reservation/void/ for current kind; clear cache
     *  - On page open → loadAllReservationStatuses() restores any active holds
     */

    /**
     * يضبط سلوك حقل الرقم حسب السجلّ.
     *
     * السجلّات الثلاثة الأولى: الرقم يولّده النظام ويُحجز ذرّياً — الحقل للقراءة فقط
     * كي لا يكتب موظّفان الرقم نفسه.
     * الصادر الخارجي: لا سلسلة له أصلاً — الرقم يصدر من مكتب المدير العام. فالحقل
     * قابل للكتابة، ويُملأ تلقائياً من استخلاص المستند الممسوح، وإن كُتب قبل المسح
     * يُطلَب تأكيد المطابقة بدل الكتابة فوقه بصمت.
     */
    applyNumberMode(kind, config, field) {
        const manual = !!config.manualNumber;
        field.readOnly = !manual;
        field.tabIndex = manual ? 0 : -1;
        field.classList.toggle('book-number-readonly', !manual);
        field.classList.toggle('book-number-manual', manual);
        field.setAttribute('inputmode', manual ? 'numeric' : 'none');

        // عناصر الحجز لا معنى لها بلا سلسلة
        ['reservationStatus', 'reservationRing', 'numberlessToggle', 'recycledBanner']
            .forEach((id) => {
                const el = document.getElementById(id);
                if (el && manual) el.style.display = 'none';
            });

        if (manual) {
            // نظّف أي رقم محجوز بقي من تبويب آخر — رقم هذا السجلّ يأتي من الورق
            if (field.dataset.reservationId) {
                delete field.dataset.reservationId;
                delete field.dataset.formatted;
                field.value = '';
            }
            field.classList.remove('is-valid', 'is-pending', 'has-error');
        }
    }

    ensureReservation(kind) {
        // وضع التعديل: الرقم ثابت فلا حجز (كان override في القالب — نُقل للصنف لتوحيد كشف الوضع)
        if (this._editData) return Promise.resolve(null);
        // سجلّ بلا سلسلة (الصادر الخارجي): لا نحجز رقماً لا وجود له على الورق.
        if (this.getKindConfig(kind).manualNumber) return Promise.resolve(null);
        // Already have an active reservation cached for this kind → just paint
        if (this.reservations[kind] && this.reservations[kind].id) {
            this.applyReservationToUI(kind, this.reservations[kind]);
            return Promise.resolve(this.reservations[kind]);
        }
        // Otherwise reserve atomically on the server
        return fetch(this.apiEndpoints.reservationReserve, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': this.getCookie('csrftoken')
            },
            body: JSON.stringify({ kind })
        })
            .then(r => r.json())
            .then(data => {
                if (data.success && data.reservation) {
                    this.reservations[kind] = data.reservation;
                    this.applyReservationToUI(kind, data.reservation);
                    return data.reservation;
                }
                // Fallback: show next-available preview if reservation refused
                this.fetchNextNumber(kind);
                return null;
            })
            .catch(err => {
                console.warn('[ExtractionSmart] ensureReservation error:', err);
                this.fetchNextNumber(kind);
                return null;
            });
    }

    applyReservationToUI(kind, reservation) {
        if (!reservation) return;
        // نوع السجل: تسمية + لون. رمز السجل (1-4) مُعرِّف داخلي يبقى في formatted،
        // لكن المستخدم يرى التسلسل النظيف فقط + شارة النوع (النوع معروف من التبويب أصلاً).
        // لون + تسمية النوع من مصدر واحد (يطابق التبويبات ومودال التكرار)
        const meta = this._kindMeta(kind);
        const seq = (reservation.number !== null && reservation.number !== undefined && reservation.number !== '')
            ? String(reservation.number) : (reservation.formatted || '');

        // شارة التبويب: التسلسل النظيف
        const badge = document.getElementById(`tabNum_${kind}`);
        if (badge) badge.textContent = seq || '—';

        // الحقل + الشارة: للنوع الفعّال فقط
        const kindSelect = document.getElementById('bookKind');
        if (kindSelect && kindSelect.value === kind) {
            const f = document.getElementById('bookNumber');
            if (f) {
                f.value = seq;                                  // التسلسل النظيف (89) لا الرمز الخام (10089)
                f.dataset.reservationId = reservation.id;       // الحفظ يعتمد على الحجز (يُخزَّن formatted الكامل)
                f.dataset.formatted = reservation.formatted || '';
                f.classList.remove('has-error', 'is-pending');
                f.classList.add('is-valid');
                f.title = `${meta.label} — رقمك ${seq} (المعرّف الداخلي الفريد: ${reservation.formatted || ''})`;
                if (typeof updateValidationIndicator === 'function') updateValidationIndicator();
            }
            const chip = document.getElementById('bookRegisterChip');
            if (chip) {
                chip.textContent = meta.label;
                chip.style.display = 'inline-flex';
                chip.style.background = meta.bg;
                chip.style.color = meta.fg;
            }
            // بانر «رقم مُدوّر» — تحذير صارخ عند استلام رقم أُعيد تدويره
            const banner = document.getElementById('recycledBanner');
            if (banner) banner.style.display = reservation.is_recycled ? 'flex' : 'none';
            // زرّ التحرير الاختياريّ (يُظهره فقط عند وجود حجز فعّال)
            const relBtn = document.getElementById('releaseReservationBtn');
            if (relBtn) relBtn.style.display = 'inline';
            // وميض خاطف يجذب العين لكتابة الرقم على الورق
            if (f) { f.classList.remove('just-reserved'); void f.offsetWidth; f.classList.add('just-reserved'); }
            // مؤشّر «محجوز لك» البارز + العدّاد الحيّ
            this._updateReservationPill();
        }
        // 🕓 ابدأ/جدّد العدّاد التنازلي + الحضور اللحظيّ (heartbeat + خمول)
        this._ensureReservationCountdown();
        this._ensurePresence();
    }

    /** خاتم الحجز (أيقونة صح أقصى يسار الحقل): أخضر=محجوز، رمادي=لا حجز/بلا رقم/تعديل.
     *  يُقاد من مصدر الحجز نفسه (_activeReservation + حالة «بلا رقم»)، ويُستدعى في مطلع
     *  _updateReservationPill فيتحدّث مع كل نبضة عدّاد وكل تغيّر حجز أو «بلا رقم». */
    _updateReservationRing() {
        const ring = document.getElementById('reservationRing');
        if (!ring) return;
        const numberless = document.getElementById('numberlessCheckbox')?.checked;
        const reserved = !this._editData && !numberless && !!this._activeReservation();
        ring.classList.toggle('is-reserved', reserved);
        ring.title = reserved ? 'الرقم محجوز لك — اكتبه على المستند' : 'لم يُحجز رقم بعد';
    }

    /** مؤشّر «محجوز لك» البارز: يُظهر الحالة + الوقت المتبقّي بلون يتدرّج مع الاقتراب من الانتهاء.
     *  حين يظهر المؤشّر يُخفى #bookNumberHint المكرّر فيبقى سطر تنبيه واحد نظيف أسفل الحقل. */
    _updateReservationPill() {
        this._updateReservationRing();   // الخاتم يتحدّث دائماً، مستقلّاً عن وجود المؤشّر أو مساراته المبكّرة
        const pill = document.getElementById('reservationStatus');
        const hint = document.getElementById('bookNumberHint');
        if (!pill) return;
        const timerEl = document.getElementById('reservationTimer');
        const cur = this._activeReservation();
        const numberless = document.getElementById('numberlessCheckbox')?.checked;
        if (this._editData || numberless || !cur) {
            pill.style.display = 'none';
            if (hint) hint.style.display = '';        // لا مؤشّر → أظهِر التلميح (قيد الطلب / بلا رقم)
            return;
        }
        pill.style.display = 'flex';
        if (hint) hint.style.display = 'none';        // المؤشّر يكفي — أخفِ التلميح المكرّر
        let secs = 0;
        if (cur.r.expires_at) {
            secs = Math.max(0, Math.floor((new Date(cur.r.expires_at).getTime() - Date.now()) / 1000));
        }
        pill.classList.remove('rs-warn', 'rs-critical');
        if (secs > 0 && secs < 5 * 60) pill.classList.add('rs-critical');
        else if (secs < 10 * 60) pill.classList.add('rs-warn');
        if (timerEl) timerEl.textContent = secs > 0 ? `صالح ${Math.ceil(secs / 60)} د` : 'انتهى — سيُجدَّد';
    }

    /** عدّاد تنازلي مركزي يحدّث ألوان وشارات تبويبات الأنواع كل 20 ثانية. */
    _ensureReservationCountdown() {
        if (this._reservationTimerId) return; // يعمل بالفعل
        const tick = () => {
            const now = Date.now();
            let anyActive = false;
            const kinds = ['incoming_internal', 'incoming_external', 'outgoing_internal', 'outgoing_external'];
            kinds.forEach((k) => {
                const r = this.reservations[k];
                const tab = document.querySelector(`.kind-tab[data-kind="${k}"]`);
                if (!tab) return;
                tab.classList.remove('reservation-fresh', 'reservation-warn', 'reservation-critical', 'reservation-expired');
                if (!r || !r.expires_at) return;
                anyActive = true;
                const expMs = new Date(r.expires_at).getTime();
                const secondsLeft = Math.floor((expMs - now) / 1000);
                if (secondsLeft <= 0) {
                    tab.classList.add('reservation-expired');
                    tab.title = 'انتهت صلاحية الحجز — اختر التبويب لإعادة الحجز';
                    delete this.reservations[k];
                    const badge = document.getElementById(`tabNum_${k}`);
                    if (badge) badge.textContent = '—';
                    // إذا كان هذا التبويب هو الفعّال، تحقّق من الحقل
                    const kindSelect = document.getElementById('bookKind');
                    if (kindSelect && kindSelect.value === k) {
                        this.showToast('انتهت صلاحية حجز الرقم — جارٍ طلب رقم جديد', 'warning', 4000);
                        this.ensureReservation(k);
                    }
                } else if (secondsLeft < 5 * 60) {
                    tab.classList.add('reservation-critical');
                    tab.title = `الحجز ينتهي خلال ${Math.ceil(secondsLeft / 60)} دقيقة`;
                    if (secondsLeft < 120 && !this._criticalNotified?.[k]) {
                        this._criticalNotified = this._criticalNotified || {};
                        this._criticalNotified[k] = true;
                        this.showToast('⏰ انتباه: الحجز ينتهي خلال أقل من دقيقتين', 'warning', 5000);
                    }
                } else if (secondsLeft < 10 * 60) {
                    tab.classList.add('reservation-warn');
                    tab.title = `الحجز ينتهي خلال ${Math.ceil(secondsLeft / 60)} دقيقة`;
                } else {
                    tab.classList.add('reservation-fresh');
                    tab.title = `الحجز صالح حتى ${new Date(expMs).toLocaleTimeString('ar-EG')}`;
                }
            });
            this._updateReservationPill();   // حدّث مؤشّر «محجوز لك» + العدّاد الحيّ
            if (!anyActive) {
                clearInterval(this._reservationTimerId);
                this._reservationTimerId = null;
            }
        };
        tick();
        this._reservationTimerId = setInterval(tick, 20000);
    }

    // ═══ الحضور اللحظيّ: نبضة heartbeat + كشف الخمول + معالجة فقدان الرقم ═══
    // (يعمل عبر HTTP؛ WS طبقة تسريع اختيارية لا شرطٌ للصحّة)
    _ensurePresence() {
        if (this._editData) return;   // التعديل: لا حجز
        if (!this._presenceBound) {
            this._presenceBound = true;
            this._lastActivity = Date.now();
            const bump = () => {
                this._lastActivity = Date.now();
                if (this._idleWarned) { this._idleWarned = false; }
            };
            ['mousemove', 'keydown', 'pointerdown', 'input', 'wheel'].forEach(ev =>
                document.addEventListener(ev, bump, { passive: true }));
            const relBtn = document.getElementById('releaseReservationBtn');
            if (relBtn) relBtn.addEventListener('click', () => this._releaseCurrentReservation());
        }
        if (!this._presenceTimer) {
            this._presenceTimer = setInterval(() => this._presenceTick(), 25000);
        }
        // WS اختياريّ (كشف لحظيّ) — مُطفأ حتى يُفعَّل عبر data-ws-presence="1" + channels
        if (!this._wsTried &&
            document.querySelector('.extraction-container')?.dataset.wsPresence === '1') {
            this._wsTried = true;
            this._connectPresenceWS();
        }
    }

    _connectPresenceWS() {
        if (this._ws || !window.WebSocket) return;
        const proto = location.protocol === 'https:' ? 'wss' : 'ws';
        try {
            const ws = new WebSocket(`${proto}://${location.host}/ws/reservation/presence/`);
            this._ws = ws;
            ws.onopen = () => this._wsPing();
            ws.onclose = () => { this._ws = null; };   // الخادم يتكفّل بالـcooldown عند الإغلاق
            ws.onerror = () => { try { ws.close(); } catch (e) {} };
            this._wsTimer = setInterval(() => this._wsPing(), 25000);
        } catch (e) { this._ws = null; }
    }

    _wsPing() {
        const cur = this._activeReservation();
        if (this._ws && this._ws.readyState === 1 && cur) {
            try { this._ws.send(JSON.stringify({ t: 'hb', id: cur.r.id })); } catch (e) {}
        }
    }

    _activeReservation() {
        const kind = this.getCurrentKind();
        const r = this.reservations[kind];
        return (r && r.id) ? { kind, r } : null;
    }

    _presenceTick() {
        const IDLE_WARN_MS = 5 * 60 * 1000;   // خمول 5 دقائق → تنبيه (لا إسقاط)
        const cur = this._activeReservation();
        if (!cur) return;
        // 1) خمول: تنبيه بصريّ+صوتيّ مرّة واحدة (لا يُسقط الحجز — سياسة المالك)
        if (Date.now() - (this._lastActivity || Date.now()) > IDLE_WARN_MS && !this._idleWarned) {
            this._idleWarned = true;
            this._showIdleWarning(cur.kind, cur.r);
        }
        // 2) نبضة حضور: تُبقي الرقم حيّاً؛ إن عاد alive=false فالرقم فُقد/دُوّر
        fetch(this.apiEndpoints.reservationHeartbeat || '/books/api/reservation/heartbeat/', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': this.getCookie('csrftoken') },
            body: JSON.stringify({ reservation_id: cur.r.id }),
        }).then(r => r.json()).then(d => {
            if (d && d.alive === false) this._onReservationLost(cur.kind);
        }).catch(() => {});
    }

    _beep() {
        try {
            const Ctx = window.AudioContext || window.webkitAudioContext;
            if (!Ctx) return;
            const ctx = this._audioCtx || (this._audioCtx = new Ctx());
            const o = ctx.createOscillator(), g = ctx.createGain();
            o.type = 'sine'; o.frequency.value = 880;
            g.gain.value = 0.08;
            o.connect(g); g.connect(ctx.destination);
            o.start(); o.stop(ctx.currentTime + 0.35);
        } catch (e) { /* الصوت مكمّل — لا يُفشل شيئاً */ }
    }

    _showIdleWarning(kind, res) {
        this._beep();
        const msg = `أنت تحجز الرقم ${res.formatted} وزملاؤك بانتظاره. إن لم تكتبه على المستند حرّره ليُعاد تدويره؛ وإن كتبته أبقِه وأكمل الحفظ.`;
        if (window.ToastCenter && typeof window.ToastCenter.action === 'function') {
            window.ToastCenter.action('warning', msg, [
                { label: 'أُبقيه (كتبته)', className: 'btn btn-sm btn-warning text-dark fw-semibold',
                  onClick: () => { this._lastActivity = Date.now(); this._idleWarned = false; } },
                { label: 'حرّره ليُدوَّر', className: 'btn btn-sm btn-outline-danger fw-semibold',
                  onClick: () => this._releaseCurrentReservation() },
            ], { title: '⏳ حجزٌ خامل', delay: 0, autohide: false });
        } else {
            this.showToast(msg, 'warning', 9000, 'حجز خامل');
        }
    }

    _onReservationLost(kind) {
        delete this.reservations[kind];
        const f = document.getElementById('bookNumber');
        if (f) { f.value = ''; delete f.dataset.reservationId; }
        this._beep();
        this.showToast('انتهى حجز رقمك أو أُعيد تدويره — سنطلب رقماً جديداً.', 'warning', 7000, 'تنبيه حجز');
        this.ensureReservation(kind);
    }

    _releaseCurrentReservation() {
        const cur = this._activeReservation();
        if (!cur) return;
        fetch(this.apiEndpoints.reservationVoid, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': this.getCookie('csrftoken') },
            body: JSON.stringify({ reservation_id: cur.r.id, note: 'تحرير اختياريّ من المستخدم' }),
        }).then(r => r.json()).then(() => {
            delete this.reservations[cur.kind];
            const f = document.getElementById('bookNumber');
            if (f) { f.value = ''; delete f.dataset.reservationId; }
            this.showToast('حُرّر الرقم — يمكن لزميلك استخدامه الآن. سنطلب لك رقماً جديداً عند الحاجة.', 'info', 6000);
            this.ensureReservation(cur.kind);
        }).catch(() => this.showToast('تعذّر تحرير الرقم — حاول مجدداً', 'error'));
    }

    loadAllReservationStatuses() {
        const kinds = ['incoming_internal', 'incoming_external', 'outgoing_internal', 'outgoing_external'];
        kinds.forEach((k) => {
            const url = `${this.apiEndpoints.reservationStatus}?kind=${encodeURIComponent(k)}`;
            fetch(url, { headers: { 'X-CSRFToken': this.getCookie('csrftoken') } })
                .then(r => r.json())
                .then(data => {
                    if (data.has_reservation && data.reservation) {
                        this.reservations[k] = data.reservation;
                        this.applyReservationToUI(k, data.reservation);
                    } else if (data.preview_number) {
                        // Use reservation-status preview directly when no active hold exists.
                        const badge = document.getElementById(`tabNum_${k}`);
                        if (badge) badge.textContent = data.preview_number;
                    } else {
                        // No active hold yet → show next-available number as a preview only
                        this.fetchNextNumber(k);
                    }
                })
                .catch(err => {
                    console.warn('[ExtractionSmart] reservation status error:', err);
                    this.fetchNextNumber(k);
                });
        });
    }

    /** Void the active reservation for the given kind on the server and clear cache. */
    voidReservation(kind, note = '') {
        const r = this.reservations[kind];
        if (!r || !r.id) return Promise.resolve();
        return fetch(this.apiEndpoints.reservationVoid, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': this.getCookie('csrftoken')
            },
            body: JSON.stringify({ reservation_id: r.id, note })
        })
            .then(res => res.json())
            .then(() => { delete this.reservations[kind]; })
            .catch(err => {
                console.warn('[ExtractionSmart] voidReservation error:', err);
                delete this.reservations[kind];
            });
    }

    fetchNextNumber(kind) {
        // Preview-only fallback: shows next available number without holding it.
        const url = `${this.apiEndpoints.nextNumber}?kind=${encodeURIComponent(kind)}`;
        fetch(url, { headers: { 'X-CSRFToken': this.getCookie('csrftoken') } })
            .then(r => r.json())
            .then(data => {
                const badge = document.getElementById(`tabNum_${kind}`);
                if (badge) badge.textContent = data.number || data.formatted || data.preview_number || '—';
            })
            .catch(err => console.warn('[ExtractionSmart] fetchNextNumber error:', err));
    }

    fetchAllTabNumbers() {
        // Delegate to the reservation-aware loader
        this.loadAllReservationStatuses();
    }

    setText(id, value) {
        const el = document.getElementById(id);
        if (el) {
            el.textContent = value;
        }
    }

    /**
     * تحسين التفاعلات البصرية والملاحظات
     */
    enhanceUIFeedback() {
        // Smooth scrolling for form sections
        document.querySelectorAll('a[href^="#"]').forEach(anchor => {
            anchor.addEventListener('click', (e) => {
                const target = document.querySelector(anchor.getAttribute('href'));
                if (target) {
                    e.preventDefault();
                    target.scrollIntoView({ behavior: 'smooth', block: 'start' });
                }
            });
        });

        // Add visual feedback for required fields
        const requiredFields = document.querySelectorAll('[required]');
        requiredFields.forEach(field => {
            field.addEventListener('focus', (e) => {
                e.target.closest('.form-section')?.classList.add('focused');
            });
            field.addEventListener('blur', (e) => {
                if (!e.target.value.trim()) {
                    e.target.closest('.form-group-smart')?.classList.add('has-error');
                } else {
                    e.target.closest('.form-group-smart')?.classList.remove('has-error');
                    e.target.closest('.form-section')?.classList.remove('focused');
                }
            });
        });
    }

    setupEventListeners() {
        console.log('[ExtractionSmart] Setting up enhanced event listeners...');
        
        // Drag & Drop — ربط على modalBody (دائم) ودعم النقر على empty-state
        const modalBody = document.getElementById('modalBody');
        const fileInput = document.getElementById('fileInput');

        if (modalBody && fileInput) {
            // النقر على modalBody يفتح حوار الملفات فقط حين لا يوجد ملف معروض
            modalBody.addEventListener('click', (e) => {
                if (e.target.closest('button')) return;
                if (!modalBody.classList.contains('has-image')) {
                    fileInput.click();
                }
            });
            modalBody.addEventListener('dragover', (e) => this.handleDragOver(e));
            modalBody.addEventListener('dragleave', (e) => this.handleDragLeave(e));
            modalBody.addEventListener('drop', (e) => this.handleDrop(e));
            fileInput.addEventListener('change', (e) => this.handleFileSelect(e));

        // ربط مباشر على uploadFileButton — event delegation يحجب file dialog في بعض المتصفحات
        const uploadBtn = document.getElementById('uploadFileButton');
        if (uploadBtn) {
            uploadBtn.addEventListener('click', () => {
                console.log('[ExtractionSmart] Triggering file picker');
                fileInput.click();
            });
        }
            console.log('[ExtractionSmart] ✓ Drop zone (modalBody) and file input bound');
        } else {
            console.error('[ExtractionSmart] ✗ modalBody or file input not found!');
        }

        // استخدام Event Delegation للأزرار (بما في ذلك الأزرار الديناميكية)
        document.body.addEventListener('click', (e) => {
            const target = e.target.closest('button');
            if (!target) return;

            const btnId = target.id;
            console.log('[ExtractionSmart] Button clicked:', btnId);

            if (btnId === 'clearFile' || btnId === 'clearFileFromModal') {
                e.preventDefault();
                // حذف الملف/الصورة فقط — لا يمسّ الحقول (تفريغ الحقول فعلٌ منفصل صريح)
                this.clearFile();
            } else if (btnId === 'clearFormButton') {
                e.preventDefault();
                console.log('[ExtractionSmart] Calling clearForm()');
                this.clearForm();
            } else if (btnId === 'extractButton') {
                e.preventDefault();
                console.log('[ExtractionSmart] Calling extractData()');
                this.extractData();
            } else if (btnId === 'saveButton') {
                e.preventDefault();
                console.log('[ExtractionSmart] Calling saveBook()');
                this.sendToEntityAfterSave = false;
                this.saveBook();
            } else if (btnId === 'saveAndSendButton') {
                e.preventDefault();
                // نحفظ أوّلاً ثم نفتح حوار الإرسال: لا يُرسَل مستند رسمي إلا بتأكيد
                // صريح يرى فيه المستخدم الجهة والبريد وما سيُرفَق فعلياً.
                this.sendToEntityAfterSave = true;
                this.saveBook();
            } else if (btnId === 'startScanButton') {
                e.preventDefault();
                console.log('[ExtractionSmart] Calling startScan()');
                this.startScan();
            } else if (btnId === 'clearScannedButton') {
                e.preventDefault();
                console.log('[ExtractionSmart] Calling clearScannedFile()');
                this.clearScannedFile();
            }
        });
        
        console.log('[ExtractionSmart] ✓ Event delegation set up for all buttons');

        const documentTypeSelect = document.getElementById('documentTypeSelect');
        const documentTypeCustom = document.getElementById('documentTypeCustom');

        if (documentTypeSelect) {
            documentTypeSelect.addEventListener('change', () => {
                this.handleDocumentTypeSelectionChange();
            });
        }

        if (documentTypeCustom) {
            documentTypeCustom.addEventListener('input', (e) => {
                this.validateField('documentTypeCustom');
                this.validateField('documentTypeSelect');
                this.rememberDocumentTypeState();
                this.updateSuggestions(e.target.id, e.target.value);
            });
            documentTypeCustom.addEventListener('blur', () => {
                this.rememberDocumentTypeState();
            });
        }

        // Form inputs - Live validation & suggestions
        const formFields = ['bookNumber', 'senderNumber', 'title', 'date', 'senderDate', 'dueDate', 'issuingEntity', 'receivingEntity', 'margin'];
        let fieldsFound = 0;
        
        formFields.forEach(fieldId => {
            const field = document.getElementById(fieldId);
            if (field) {
                field.addEventListener('input', (e) => this.handleFieldInput(e));
                field.addEventListener('focus', (e) => this.showSuggestions(e));
                field.addEventListener('blur', (e) => this.hideSuggestions(e));
                fieldsFound++;
            } else {
                console.warn(`[ExtractionSmart] Field not found: ${fieldId}`);
            }
        });
        
        console.log(`[ExtractionSmart] ✓ Bound ${fieldsFound}/${formFields.length} form fields`);
    }

    setupKeyboardShortcuts() {
        document.addEventListener('keydown', (e) => {
            // Ctrl/Cmd + E: Extract
            if ((e.ctrlKey || e.metaKey) && e.key === 'e') {
                e.preventDefault();
                this.extractData();
            }
            // Ctrl/Cmd + S: Save
            if ((e.ctrlKey || e.metaKey) && e.key === 's') {
                e.preventDefault();
                this.saveBook();
            }
            // Ctrl/Cmd + Enter: Save when using the notes textarea or after review.
            if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
                e.preventDefault();
                this.saveBook();
            }
            // Ctrl/Cmd + Z: تراجع نصّي بسيط (الحقول النصية فقط)
            if ((e.ctrlKey || e.metaKey) && (e.key === 'z' || e.key === 'Z') && !e.shiftKey) {
                const el = document.activeElement;
                // داخل حقل قابل للتحرير غير مُتتبَّع (الجهات/التواريخ) → دع المتصفّح يتراجع محرفياً
                const tracked = ['senderNumber', 'title', 'documentTypeCustom', 'margin'];
                const editableUntracked = el
                    && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.isContentEditable)
                    && !tracked.includes(el.id);
                if (!editableUntracked) {
                    e.preventDefault();
                    this.performTextUndo();
                }
            }
            // Escape: Clear
            if (e.key === 'Escape') {
                this.clearForm();
            }
        });

        document.addEventListener('keydown', (e) => {
            if (e.defaultPrevented || e.ctrlKey || e.metaKey || e.altKey) {
                return;
            }
            this.handleFormNavigationKeydown(e);
        });
    }

    // ── Ctrl+Z: تراجع بسيط للحقول النصية فقط ──
    // يلتقط: الكتابة اليدوية (مُجمَّعة بمهلة) + التعبئة/التفريغ البرمجي (عبر begin/endTextUndoBatch).
    // حقول التاريخ والجهات مُستثناة عمداً (تبسيط) — لها تراجع المتصفّح الأصلي.
    setupTextUndo() {
        const IDS = ['senderNumber', 'title', 'documentTypeCustom', 'margin'];
        const MAX = 60;
        const stack = [];      // [{id, value}] — أحدث تغيير في النهاية
        const prev = {};       // آخر قيمة مُثبَّتة لكل حقل
        const timers = {};
        let batch = null;

        const push = (id, value) => {
            const top = stack[stack.length - 1];
            if (top && top.id === id && top.value === value) return;   // تفادي تكرار متطابق
            stack.push({ id, value });
            if (stack.length > MAX) stack.shift();
        };
        const commit = (id) => {
            const el = document.getElementById(id);
            if (!el || el.value === prev[id]) return;
            push(id, prev[id] != null ? prev[id] : '');
            prev[id] = el.value;
        };

        IDS.forEach((id) => {
            const el = document.getElementById(id);
            if (!el) return;
            prev[id] = el.value || '';
            el.addEventListener('input', () => {
                clearTimeout(timers[id]);
                timers[id] = setTimeout(() => commit(id), 350);   // تجميع الكتابة المتتابعة كخطوة واحدة
            });
            el.addEventListener('blur', () => { clearTimeout(timers[id]); commit(id); });
        });

        // دفعة تراجع واحدة حول تعبئة/تفريغ برمجي لا يُطلق حدث input (استخراج المسح، تفريغ الحقول)
        this.beginTextUndoBatch = () => {
            batch = {};
            IDS.forEach((id) => { const el = document.getElementById(id); if (el) batch[id] = el.value; });
        };
        this.endTextUndoBatch = () => {
            if (!batch) return;
            IDS.forEach((id) => {
                const el = document.getElementById(id);
                if (el && batch[id] !== el.value) { push(id, batch[id]); prev[id] = el.value; }
            });
            batch = null;
        };

        this.performTextUndo = () => {
            // ثبّت أي كتابة معلّقة قبل التراجع
            IDS.forEach((id) => { clearTimeout(timers[id]); commit(id); });
            const entry = stack.pop();
            if (!entry) { this.showToast('لا يوجد ما يُتراجَع عنه', 'info'); return; }
            const el = document.getElementById(entry.id);
            if (!el) return;
            el.value = entry.value;
            prev[entry.id] = entry.value;   // كي لا يُلتقط الاسترجاع نفسه كتغيير جديد
            el.focus();
            try { el.dispatchEvent(new Event('input', { bubbles: true })); } catch (e) {}
        };
    }

    handleFormNavigationKeydown(e) {
        const fieldId = this.getNavigationFieldId(e.target);
        if (!fieldId) {
            return;
        }

        if (e.key === 'Tab') {
            e.preventDefault();
            const direction = e.shiftKey ? -1 : 1;
            const commitResult = direction > 0 ? this.commitPendingFieldValue(fieldId) : null;
            Promise.resolve(commitResult).finally(() => {
                this.focusRelativeField(fieldId, direction);
            });
            return;
        }

        if (e.key !== 'Enter') {
            return;
        }

        if (fieldId === 'margin') {
            return;
        }

        if (fieldId === 'dateEditToggle') {
            e.preventDefault();
            e.target.click();
            setTimeout(() => {
                const dateField = document.getElementById('date');
                if (dateField && !dateField.disabled) {
                    dateField.focus();
                } else {
                    this.focusRelativeField(fieldId, 1);
                }
            }, 0);
            return;
        }

        if (fieldId === 'needsFollowup') {
            e.preventDefault();
            e.target.click();
            setTimeout(() => {
                const dueDate = document.getElementById('dueDate');
                if (e.target.checked && this.isElementNavigable(dueDate)) {
                    dueDate.focus();
                } else {
                    this.focusRelativeField(fieldId, 1);
                }
            }, 0);
            return;
        }

        if (this.isActionButtonField(fieldId)) {
            e.preventDefault();
            document.getElementById(fieldId)?.click();
            return;
        }

        if (fieldId === 'receivingEntity' && this.isFormReadyForSave()) {
            e.preventDefault();
            this.saveBook();
            return;
        }

        e.preventDefault();
        this.focusRelativeField(fieldId, 1);
    }

    getNavigationFieldId(target) {
        if (!target) {
            return null;
        }
        if (target.id) {
            return target.id;
        }
        if (target.closest('#issuingTagWrapper')) {
            return 'issuingEntity';
        }
        if (target.closest('#receivingTagWrapper')) {
            return 'receivingEntity';
        }
        return null;
    }

    getNavigationOrder() {
        return [
            'senderNumber',
            'title',
            'dateEditToggle',
            'date',
            'senderDate',
            'needsFollowup',
            'dueDate',
            'issuingEntity',
            'receivingEntity',
            'secretLevel',
            'documentTypeSelect',
            'documentTypeCustom',
            'margin',
            'uploadFileButton',
            'startScanButton',
            'clearScannedButton',
            'clearFormButton',
            'extractButton',
            'saveButton',
            'saveAndSendButton'
        ];
    }

    isActionButtonField(fieldId) {
        return ['uploadFileButton', 'startScanButton', 'clearScannedButton', 'clearFormButton',
                'extractButton', 'saveButton', 'saveAndSendButton'].includes(fieldId);
    }

    isElementNavigable(element) {
        if (!element) {
            return false;
        }
        if (element.disabled) {
            return false;
        }
        if (element.closest('.is-hidden')) {
            return false;
        }
        const style = window.getComputedStyle(element);
        if (style.display === 'none' || style.visibility === 'hidden') {
            return false;
        }
        const rect = element.getBoundingClientRect();
        return rect.width > 0 && rect.height > 0;
    }

    getNavigableFieldIds() {
        return this.getNavigationOrder().filter((fieldId) => {
            if (fieldId === 'issuingEntity') {
                return this.isElementNavigable(window.entityTagManagers?.issuing?.input || document.getElementById(fieldId));
            }
            if (fieldId === 'receivingEntity') {
                return this.isElementNavigable(window.entityTagManagers?.receiving?.input || document.getElementById(fieldId));
            }
            return this.isElementNavigable(document.getElementById(fieldId));
        });
    }

    focusFieldById(fieldId) {
        let element = document.getElementById(fieldId);
        if (fieldId === 'issuingEntity') {
            element = window.entityTagManagers?.issuing?.input || element;
        } else if (fieldId === 'receivingEntity') {
            element = window.entityTagManagers?.receiving?.input || element;
        }
        if (!this.isElementNavigable(element)) {
            return false;
        }
        element.focus();
        return true;
    }

    focusRelativeField(currentFieldId, direction = 1) {
        const navigableIds = this.getNavigableFieldIds();
        const currentIndex = navigableIds.indexOf(currentFieldId);
        if (currentIndex === -1) {
            const fallbackIndex = direction > 0 ? 0 : navigableIds.length - 1;
            return this.focusFieldById(navigableIds[fallbackIndex]);
        }
        const targetId = navigableIds[currentIndex + direction];
        if (!targetId) {
            if (direction > 0 && this.isFormReadyForSave()) {
                this.saveBook();
            }
            return false;
        }
        return this.focusFieldById(targetId);
    }

    handleCompositeFieldAdvance(fieldId) {
        if (fieldId === 'receivingEntity' && this.isFormReadyForSave()) {
            this.saveBook();
            return;
        }
        this.focusRelativeField(fieldId, 1);
    }

    commitPendingFieldValue(fieldId) {
        if (fieldId !== 'issuingEntity' && fieldId !== 'receivingEntity') {
            return Promise.resolve();
        }
        const managerKey = fieldId === 'issuingEntity' ? 'issuing' : 'receiving';
        const manager = window.entityTagManagers?.[managerKey];
        const pendingValue = manager?.input?.value?.trim();
        if (!manager || !pendingValue) {
            return Promise.resolve();
        }
        return Promise.resolve(manager._resolveOrCreate(pendingValue, true));
    }

    isFormReadyForSave() {
        const bookNumber = document.getElementById('bookNumber')?.value?.trim();
        const title = document.getElementById('title')?.value?.trim();
        const date = document.getElementById('date')?.value?.trim();
        const issuingCount = window.entityTagManagers?.issuing?.count?.() || 0;
        const receivingCount = window.entityTagManagers?.receiving?.count?.() || 0;
        return Boolean(bookNumber && title && title.length >= 3 && date && issuingCount > 0 && receivingCount > 0);
    }

    hasAttachedFile() {
        return Boolean(this.currentFile || (Array.isArray(this.scannedFiles) && this.scannedFiles.length > 0));
    }

    confirmSaveWithoutFile() {
        return new Promise((resolve) => {
            if (!window.ToastCenter || typeof window.ToastCenter.action !== 'function') {
                resolve(window.confirm('لم يتم رفع ملف أو مسحه بعد.\n\nهل ترغب بالاستمرار في حفظ الكتاب بدون صورة أو مرفق؟'));
                return;
            }

            let settled = false;
            const finalize = (result) => {
                if (settled) return;
                settled = true;
                resolve(result);
            };

            window.ToastCenter.action('warning', 'يمكنك حفظ الكتاب الآن بدون مرفق، أو رفع أو مسح ملف أولاً.', [
                {
                    label: 'حفظ بدون مرفق',
                    className: 'btn btn-sm btn-warning text-dark fw-semibold',
                    onClick: () => finalize(true),
                },
                {
                    label: 'رفع ملف',
                    className: 'btn btn-sm btn-outline-primary fw-semibold',
                    onClick: () => {
                        const fi = document.getElementById('fileInput');
                        if (fi) {
                            fi.click();
                        }
                        finalize(false);
                    },
                }
            ], {
                title: 'لا يوجد ملف مرفوع أو ممسوح',
                delay: 0,
                autohide: false,
                onShown: (toastApi) => {
                    toastApi.element.querySelector('.btn-warning')?.focus();
                },
                onHidden: () => finalize(false),
            });
        });
    }

    /** لون + تسمية نوع السجل — مصدر واحد (يطابق تبويبات النوع). */
    _kindMeta(kind) {
        const M = {
            incoming_internal: { label: 'وارد داخلي', bg: '#f0fdfa', fg: '#0f766e' },
            incoming_external: { label: 'وارد خارجي', bg: '#f0f9ff', fg: '#0369a1' },
            outgoing_internal: { label: 'صادر داخلي', bg: '#fff7ed', fg: '#b45309' },
            outgoing_external: { label: 'صادر خارجي', bg: '#fff1f2', fg: '#9f1239' },
        };
        return M[kind] || { label: 'سجل', bg: '#e5e7eb', fg: '#374151' };
    }

    /** مودال التكرار: قائمة المطابقات + معاينة سريعة لكل كتاب، ويُعيد Promise<boolean>
     *  (true = تابِع الحفظ، false = ألغِ الإدخال). DUPLICATE_BOOK لغير المشرف = منع بلا متابعة. */
    _confirmDuplicate(data) {
        return new Promise((resolve) => {
            const dups = data.duplicates || [];
            const hard = data.error_code === 'DUPLICATE_BOOK';
            const canProceed = hard ? !!data.can_override : true;
            const title = hard ? 'كتاب مكرّر (تطابق تامّ)' : 'كتاب مشابه موجود';
            const esc = (s) => String(s == null ? '' : s)
                .replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

            if (!document.body) { resolve(false); return; }

            let settled = false;
            const overlay = document.createElement('div');
            overlay.className = 'dup-modal-overlay';
            overlay.innerHTML =
                `<div class="dup-modal" role="dialog" aria-modal="true" aria-label="${esc(title)}">
                    <div class="dup-modal-header ${hard ? 'is-hard' : 'is-soft'}">
                        <span class="dup-modal-title"><i class="bi ${hard ? 'bi-exclamation-octagon-fill' : 'bi-exclamation-triangle-fill'}"></i> ${esc(title)}</span>
                        <button type="button" class="dup-modal-close" aria-label="إغلاق">&times;</button>
                    </div>
                    <div class="dup-modal-body"></div>
                    <div class="dup-modal-footer"></div>
                </div>`;
            document.body.appendChild(overlay);
            const body = overlay.querySelector('.dup-modal-body');
            const footer = overlay.querySelector('.dup-modal-footer');

            const finish = (r) => {
                if (settled) return;
                settled = true;
                document.removeEventListener('keydown', onKey);
                overlay.classList.add('dup-closing');
                setTimeout(() => overlay.remove(), 160);
                resolve(r);
            };
            const backOrCancel = () => {
                if (overlay.dataset.view === 'preview') renderList();
                else finish(false);
            };
            const onKey = (e) => { if (e.key === 'Escape') backOrCancel(); };
            document.addEventListener('keydown', onKey);
            overlay.addEventListener('mousedown', (e) => { if (e.target === overlay) backOrCancel(); });
            overlay.querySelector('.dup-modal-close').addEventListener('click', backOrCancel);

            const renderList = () => {
                overlay.dataset.view = 'list';
                body.innerHTML =
                    `<p class="dup-msg">${esc(data.message || '')}</p>` +
                    `<div class="dup-list">` + dups.map(d => `
                        <div class="dup-item">
                            <span class="dup-badge">${esc(d.match_count || 0)}/4</span>
                            <div class="dup-item-main">
                                <div class="dup-item-num">${esc(d.our_number_display || d.our_number || '—')}</div>
                                <div class="dup-item-title">${esc(d.title || 'بدون عنوان')}</div>
                                <div class="dup-item-date">${esc(d.date || '')}</div>
                            </div>
                            <button type="button" class="dup-preview-btn" data-id="${esc(d.id)}"><i class="bi bi-eye"></i> معاينة</button>
                        </div>`).join('') + `</div>`;
                footer.innerHTML =
                    (canProceed ? `<button type="button" class="btn btn-sm ${hard ? 'btn-danger' : 'btn-warning text-dark'} fw-semibold" data-act="proceed">${hard ? 'حفظ رغم التكرار' : 'متابعة الحفظ'}</button>` : '') +
                    `<button type="button" class="btn btn-sm btn-outline-secondary fw-semibold" data-act="cancel">إلغاء الإدخال</button>`;
                footer.querySelector('[data-act="cancel"]').onclick = () => finish(false);
                const pb = footer.querySelector('[data-act="proceed"]'); if (pb) pb.onclick = () => finish(true);
                body.querySelectorAll('.dup-preview-btn').forEach(b => b.onclick = () => renderPreview(b.dataset.id));
            };

            const renderPreview = async (id) => {
                overlay.dataset.view = 'preview';
                body.innerHTML = `<div class="dup-loading"><span class="spinner"></span> جارٍ تحميل المعاينة...</div>`;
                footer.innerHTML = `<button type="button" class="btn btn-sm btn-link" data-act="back">رجوع للقائمة</button>`;
                footer.querySelector('[data-act="back"]').onclick = renderList;
                let b;
                try {
                    const r = await fetch(`/books/api/book/${id}/preview/`, { credentials: 'same-origin' });
                    b = await r.json();
                    if (!r.ok) throw new Error(b.error || 'تعذّر التحميل');
                } catch (e) {
                    body.innerHTML = `<div class="dup-error">تعذّرت المعاينة. <a href="/books/${esc(id)}/" target="_blank">افتح الكتاب في صفحة مستقلة ↗</a></div>`;
                    return;
                }
                const meta = this._kindMeta(b.kind);
                const prim = (b.attachments || []).find(a => a.is_primary) || (b.attachments || [])[0];
                let docHtml = '<div class="dup-doc-empty"><i class="bi bi-file-earmark"></i> لا مرفق</div>';
                if (prim && prim.is_image) docHtml = `<img class="dup-doc-img" src="${esc(prim.url)}" alt="مستند" loading="lazy">`;
                else if (prim) docHtml = `<a class="dup-doc-link" href="${esc(prim.url)}" target="_blank"><i class="bi bi-file-earmark-pdf"></i> فتح المستند</a>`;
                const entities = (b.issuing_entities || []).concat(b.receiving_entities || [])
                    .map(e => esc(e.name)).join('، ') || '—';
                body.innerHTML =
                    `<div class="dup-preview">
                        <div class="dup-fields">
                            <span class="dup-chip" style="background:${meta.bg};color:${meta.fg}">${esc(meta.label)}</span>
                            <div class="dup-f"><label>رقمنا</label><b>${esc(b.our_number_display || b.our_number)}</b></div>
                            <div class="dup-f"><label>العنوان</label><span>${esc(b.title || 'بدون عنوان')}</span></div>
                            <div class="dup-f"><label>تاريخنا</label><span>${esc(b.date || '—')}</span></div>
                            <div class="dup-f"><label>رقم الجهة</label><span>${esc(b.sender_number || '—')}</span></div>
                            <div class="dup-f"><label>تاريخهم</label><span>${esc(b.sender_date || '—')}</span></div>
                            <div class="dup-f"><label>الجهات</label><span>${entities}</span></div>
                            <div class="dup-f"><label>الحالة</label><span>${esc(b.followup_label || '')}</span></div>
                        </div>
                        <div class="dup-doc">${docHtml}<a class="dup-open-full" href="/books/${esc(id)}/" target="_blank">فتح الكتاب كاملاً ↗</a></div>
                    </div>`;
                footer.innerHTML =
                    `<button type="button" class="btn btn-sm btn-danger fw-semibold" data-act="cancel"><i class="bi bi-x-circle"></i> هذا مكرّر — ألغِ الإدخال</button>` +
                    (canProceed ? `<button type="button" class="btn btn-sm btn-outline-secondary fw-semibold" data-act="proceed">ليس مطابقاً — تابِع</button>` : '') +
                    `<button type="button" class="btn btn-sm btn-link" data-act="back">رجوع</button>`;
                footer.querySelector('[data-act="cancel"]').onclick = () => finish(false);
                const pb = footer.querySelector('[data-act="proceed"]'); if (pb) pb.onclick = () => finish(true);
                footer.querySelector('[data-act="back"]').onclick = renderList;
            };

            renderList();
            requestAnimationFrame(() => overlay.classList.add('dup-open'));
            setTimeout(() => overlay.querySelector('.dup-modal-close')?.focus(), 30);
        });
    }

    // ===== File Handling =====
    handleDragOver(e) {
        e.preventDefault();
        const mb = document.getElementById('modalBody');
        if (mb) mb.classList.add('is-dragover');
    }

    handleDragLeave(e) {
        e.preventDefault();
        const mb = document.getElementById('modalBody');
        if (mb) mb.classList.remove('is-dragover');
    }

    handleDrop(e) {
        e.preventDefault();
        const mb = document.getElementById('modalBody');
        if (mb) mb.classList.remove('is-dragover');
        const files = e.dataTransfer.files;
        if (files.length > 0) {
            this.processFile(files[0]);
        }
    }

    handleFileSelect(e) {
        const files = e.target.files;
        if (files.length > 0) {
            this.processFile(files[0]);
        }
    }

    // ===== مسح ضوئي — وكيل NAPS2 المحلي (TWAIN/WIA/ADF → PDF → رفع مباشر) =====

    async startScan(opts = {}) {
        if (this._scanInProgress) {   // امنع مسحاً متزامناً → يمنع تعاقب قفل الماسح وتكرار الحواريّات
            this.showToast('هناك عملية مسح جارية — انتظر انتهاءها أو ألغِها أولاً.', 'warning', 5000);
            return;
        }
        this._scanInProgress = true;
        this._scanCancelled  = false;
        this._scanAbort      = new AbortController();          // لإجهاض طلب المسح فعلاً عند الإلغاء/المهلة
        this._scanAppendMode = !!(opts && opts.appendMode);    // وضع التعديل: مسح وإلحاق بالمستند القائم

        const btn          = document.getElementById('startScanButton');
        const scanProgress = document.getElementById('scanProgress');
        const origHTML     = btn ? btn.innerHTML : '';
        if (btn) btn.disabled = true;
        if (scanProgress) scanProgress.style.display = 'flex';

        // إلغاء موحّد: يُجهض الطلب المعلّق فعلاً ويُحرّر كل الحالة (زر الشريط + زر الأوفرلاي كلاهما يستدعيه)
        const doCancel = () => {
            if (this._scanCancelled) return;
            this._scanCancelled = true;
            try { this._scanAbort && this._scanAbort.abort(); } catch (_) {}
            this._endScan(btn, origHTML, scanProgress);
            this.showToast('تم إلغاء المسح', 'info');
        };

        // زر إلغاء في شريط المسح (يظهر في وضع الإدخال)
        const cancelBtn = document.createElement('button');
        cancelBtn.className = 'btn btn-sm btn-outline-danger';
        cancelBtn.innerHTML = '<i class="bi bi-x-circle"></i> إلغاء';
        cancelBtn.style.marginRight = '10px';
        cancelBtn.onclick = doCancel;
        if (scanProgress?.parentElement) {
            scanProgress.parentElement.appendChild(cancelBtn);
            this.scanCancelButton = cancelBtn;
        }

        // وضع التعديل: شريط المسح مخفيّ → التقدّم وزر الإلغاء داخل أوفرلاي المعاينة (لا يعلق المستخدم)
        if (this._scanAppendMode) {
            this._showExtractionOverlay('جارٍ المسح الضوئي…', 'التقاط الصفحات لإلحاقها بالمستند', doCancel);
        }

        if (!btn) { this._endScan(btn, origHTML, scanProgress); return; }

        const csrf = document.querySelector('[name=csrfmiddlewaretoken]')?.value;
        if (!csrf) {
            this.showToast('خطأ: رمز CSRF غير موجود', 'error');
            this._endScan(btn, origHTML, scanProgress);
            return;
        }

        // ── المسح عبر وكيل NAPS2 المحلي — المسار الوحيد (TWAIN/WIA/ADF → PDF → رفع مباشر) ──
        const setMsg = (m) => {
            const e = scanProgress?.querySelector('.progress-message');
            if (e) e.textContent = m;
            if (this._scanAppendMode) {   // زامن نصّ التقدّم مع أوفرلاي المعاينة (وضع التعديل)
                const ov = document.querySelector('#modalBody .extraction-loading-overlay .overlay-text');
                if (ov) ov.textContent = m;
            }
        };
        const fail = (msg, title = 'تعذّر المسح') => {
            if (this._scanCancelled) return;
            this.showToast(msg, 'error', 7000, title);
            this._endScan(btn, origHTML, scanProgress);   // يحرّر الحارس + المؤشّر + الأوفرلاي + زر الإلغاء
        };
        try {
            // 1) توكِن وعنوان الوكيل المحلي من Django (يقرأ ملف التوكِن على نفس الجهاز)
            setMsg('التحقق من وكيل المسح...');
            let td;
            try {
                td = await (await this._fetchWithTimeout('/books/api/scan/agent-token/', { credentials: 'same-origin' }, 8000)).json();
            } catch (_) {
                return fail('تعذّر الوصول إلى الخادم للتحقق من وكيل المسح. حدّث الصفحة وأعد المحاولة.', 'تعذّر الاتصال');
            }
            if (!td.available) {
                return fail('لم يُعثر على وكيل المسح المحلي. شغّل تطبيق «LetterSys Scan Agent» على هذا الجهاز ثم أعد المحاولة.', 'وكيل المسح غير مشغّل');
            }
            const token = td.token;
            if (this._scanCancelled) return;

            // 2) حدّد عنوان الوكيل العامل (يجرّب 127.0.0.1 ثم localhost) + فحص NAPS2
            const agentUrl = await this._resolveAgentBase(td);
            if (!agentUrl) {
                return fail(
                    'تعذّر الاتصال بوكيل المسح المحلي رغم تشغيله. قد يحجب توجيه/بروكسي المتصفح المضيف المحلي '
                    + '(127.0.0.1 وlocalhost) — استثنِ المضيف المحلي من البروكسي، أو افتح التطبيق عبر '
                    + 'http://127.0.0.1:8000، ثم أعد المحاولة.',
                    'تعذّر الاتصال بالوكيل');
            }
            const hd = this._agentHealth || {};
            if (!hd.naps2_available) {
                return fail('برنامج المسح NAPS2 غير مثبّت على هذا الجهاز. ثبّته من naps2.com ثم أعد المحاولة.', 'NAPS2 غير مثبّت');
            }

            // 3) اختيار الجهاز: من القائمة المنسدلة إن وُجدت، وإلا أول جهاز متاح
            let dd;
            try {
                dd = await (await this._fetchWithTimeout(agentUrl + '/agent/devices', { headers: { 'X-LetterSys-Token': token } }, 20000)).json();
            } catch (err) {
                const noResp = err && err.name === 'AbortError';
                return fail(
                    noResp ? 'لم يستجب الماسح أثناء البحث عن الأجهزة. تأكّد أنه يعمل ولم يتوقّف.'
                           : 'تعذّر الاتصال بوكيل المسح لقراءة الأجهزة.',
                    noResp ? 'الماسح لا يستجيب' : 'تعذّر الاتصال بالوكيل');
            }
            const devices = dd.devices || [];
            if (!devices.length) {
                return fail('لم يُكتشف أي ماسح متصل. تأكّد من توصيل الماسح وتشغيله، ثم أعد المحاولة.', 'لا يوجد ماسح');
            }
            const sel = document.getElementById('scanDeviceSelect');
            const chosenId = (sel && sel.value) || localStorage.getItem('lettersys_scan_device');
            const device = devices.find(d => d.id === chosenId) || devices[0];
            if (this._scanCancelled) return;

            // 4) المسح الأوتوماتيكي بالكامل عبر NAPS2 (يُعيد PDF).
            // الوكيل يكتشف المصدر تلقائياً (وجهان ADF → وجه → زجاج) ويحلّ خطأ «0 صفحات»،
            // والخادم يزيل الصفحات الفارغة تلقائياً → اكتشاف الوجه/الوجهين بلا أي ضبط يدوي.
            setMsg('جارٍ المسح التلقائي من ' + device.name + '...');
            this.setScanStatus('scanning', 'جارٍ المسح…');
            let sr;
            // مهلة طويلة للمسح متعدد الصفحات (ADF)، لكن عبر AbortController نفسه كي يُجهضه زر الإلغاء فعلاً
            const scanTO = setTimeout(() => { try { this._scanAbort && this._scanAbort.abort(); } catch (_) {} }, 180000);
            try {
                sr = await fetch(agentUrl + '/agent/scan', {
                    method: 'POST',
                    headers: { 'X-LetterSys-Token': token, 'Content-Type': 'application/json' },
                    body: JSON.stringify({ device_id: device.id, driver: device.driver, mode: 'auto' }),
                    signal: this._scanAbort.signal,
                });
            } catch (err) {
                clearTimeout(scanTO);
                if (this._scanCancelled) return;   // الإلغاء نظّف الحالة بالفعل عبر doCancel
                const noResp = err && err.name === 'AbortError';
                return fail(
                    noResp ? 'لم يكتمل المسح ضمن المهلة المحددة. قد يكون الماسح متوقّفاً أو في انتظار ورق — تحقّق منه وأعد المحاولة.'
                           : 'انقطع الاتصال بالماسح أثناء المسح. تأكّد أنه متّصل ويعمل.',
                    noResp ? 'الماسح لا يستجيب' : 'انقطع الاتصال بالماسح');
            }
            clearTimeout(scanTO);
            if (!sr.ok) {
                let e = {}; try { e = await sr.json(); } catch (_) {}
                // رسالة الوكيل عند صفر صفحات صارت إرشادية (ضع الورق…) — نعرضها كما هي
                return fail(e.error || ('فشل المسح (رمز ' + sr.status + '). تأكّد من الورق والجهاز ثم أعد المحاولة.'), 'تعذّر المسح');
            }
            const blob = await sr.blob();
            if (this._scanCancelled) return;

            // 4) رفع الـPDF إلى Django (جلسة + CSRF) — مع إزالة الصفحات الفارغة تلقائياً
            setMsg('جارٍ تجهيز المستند...');
            const fd = new FormData();
            fd.append('file', blob, 'scan.pdf');
            fd.append('trim_blanks', '1');           // إزالة ظهور الصفحات الفارغة (مسح مزدوج)
            // مفتاح الاستخراج التلقائي يحكم مسار المسح أيضاً: مطفأً يُلتقط المستند فوراً بلا OCR
            fd.append('auto_ocr', this._autoExtractEnabled() ? '1' : '0');
            const ud = await (await fetch('/books/api/scan/process-upload/', {
                method: 'POST',
                credentials: 'same-origin',
                headers: { 'X-CSRFToken': csrf },
                body: fd,
            })).json();
            if (!ud.ok) return fail(ud.error || 'فشل رفع الملف الممسوح');
            if (ud.trimmed_pages > 0) {
                this.showToast('مسح تلقائي: أُزيلت ' + ud.trimmed_pages + ' صفحة فارغة — تبقّى ' + ud.page_count + ' صفحة.', 'info', 5000);
            }
            // استئناف محلي بلا إعادة تحميل — يحفظ ما أدخله المستخدم قبل المسح (كان يُفقَد
            // سابقاً عند window.location.href = ud.redirect). نُحمّل بيانات الرمز في المكان.
            this._scanInProgress = false;   // حرّر الحارس عند النجاح
            this._scanAbort = null;
            this._restoreScanButton(btn, origHTML, scanProgress);
            if (cancelBtn) cancelBtn.remove();
            this._resetScanPill();
            if (this._scanAppendMode) {
                await this.appendFromSourceToken(ud.token);   // مسح وإلحاق: يُدرج بنهاية المستند القائم
                this._hideExtractionOverlay();
            } else {
                this._loadScanToken(ud.token, { notice: ud.warning || null });
            }
        } catch (err) {
            console.warn('[scan] NAPS2 agent flow failed:', err);
            fail('تعذّر الاتصال بوكيل المسح المحلي (تأكّد أنه يعمل على 127.0.0.1:17865)');
        }
    }

    _restoreScanButton(btn, origHTML, scanProgress) {
        if (btn) {
            btn.disabled = false;
            btn.style.position = '';
            const hasScan = this.scannedFiles?.length > 0;
            btn.innerHTML = hasScan
                ? '<i class="bi bi-arrow-repeat me-1"></i>مسح جديد'
                : (origHTML || '<i class="bi bi-upc-scan me-1"></i>مسح من السكانر');
        }
        if (scanProgress) scanProgress.style.display = 'none';
        if (this.scanCancelButton) { this.scanCancelButton.remove(); this.scanCancelButton = null; }
        const clearScanned  = document.getElementById('clearScannedButton');
        if (clearScanned) clearScanned.disabled = false;
    }

    /** إنهاء دورة مسح (فشل/إلغاء): يحرّر قفل التزامن + يوقف الإجهاض + ينظّف كل واجهات التقدّم. */
    _endScan(btn, origHTML, scanProgress) {
        this._scanInProgress = false;
        this._scanAbort = null;
        this._restoreScanButton(btn, origHTML, scanProgress);   // يعيد الزرّ ويزيل زر الإلغاء
        this._resetScanPill();
        this._hideExtractionOverlay();                          // يزيل أوفرلاي المعاينة (وضع الإلحاق)
    }

    cancelScan(button, originalContent, progressElement) {
        this._scanCancelled = true;
        this._restoreScanButton(button, originalContent, progressElement);
        this.showToast('تم إلغاء المسح', 'info');
    }

    cleanupScan(button, originalContent, progressElement) {
        this._restoreScanButton(button, originalContent, progressElement);
    }

    // تحميل الملف الممسوح من السيرفر وعرضه
    // noAutoExtract: true → عرض فقط بدون إعادة تشغيل OCR (عند التحميل من scan_token)
    loadScannedFile(fileUrl, fileName, { noAutoExtract = false } = {}) {
        console.log('[ExtractionSmart] loadScannedFile():', fileName, 'from URL:', fileUrl);

        fetch(fileUrl)
            .then(response => {
                console.log('[ExtractionSmart] Fetch response:', response.status, response.headers.get('content-type'));
                if (!response.ok) throw new Error(`HTTP ${response.status}`);
                return response.blob();
            })
            .then(blob => {
                console.log('[ExtractionSmart] ✓ Blob received:', {
                    type: blob.type,
                    size: blob.size,
                    fileName: fileName
                });

                // إذا كان MIME type فارغ، حاول استنتاجه من اسم الملف
                let finalBlob = blob;
                if (!blob.type || blob.type === '') {
                    const ext = (fileName || '').split('.').pop().toLowerCase();
                    let mimeType = 'application/octet-stream';

                    if (['jpg', 'jpeg'].includes(ext)) mimeType = 'image/jpeg';
                    else if (ext === 'png') mimeType = 'image/png';
                    else if (ext === 'gif') mimeType = 'image/gif';
                    else if (ext === 'pdf') mimeType = 'application/pdf';

                    console.log('[ExtractionSmart] MIME type was empty, setting to:', mimeType);
                    finalBlob = blob.slice(0, blob.size, mimeType);
                }

                const safeName = fileName || 'scanned-document';
                const fileObject = new File([finalBlob], safeName, { type: finalBlob.type || 'application/octet-stream' });

                // مسح/تحميل جديد يستبدل الملف الحالي — دمج الصفحات المتعددة يقع خادمياً
                // (NAPS2 يُخرج PDF واحداً؛ الرفع اليدوي يُوحَّد إلى PDF في process-upload).
                this.scannedFiles = [fileObject];
                this.currentFile = fileObject;
                console.log('[ExtractionSmart] ✓ currentFile set from scanned blob');

                this.displayBlobPreview(finalBlob, fileName);
                this.displayFileName(fileName);
                this._updateScanState();
                if (!noAutoExtract) {
                    if (this._autoExtractEnabled()) {
                        this.showToast('✓ تم المسح — جاري الاستخراج...', 'info');
                        // استخراج تلقائي بعد المسح الضوئي
                        setTimeout(() => this.extractData(), 400);
                    } else {
                        // الاستخراج التلقائي مُطفأ — المستند جاهز للإدخال اليدوي، وزرّ «استخراج» متاح
                        this.showToast('✓ المستند جاهز — أدخِل الحقول يدوياً أو اضغط «استخراج» متى شئت.', 'info', 6000);
                    }
                }
            })
            .catch(error => {
                console.error('[ExtractionSmart] ✗ Failed to load scanned file:', error);
                this.showToast(`خطأ: ${error.message}`, 'error');
            });
    }

    /** تحديث حالة الأزرار + عدّاد الصفحات بناءً على scannedFiles. */
    _updateScanState() {
        const clearScannedBtn = document.getElementById('clearScannedButton');
        const startScanBtn = document.getElementById('startScanButton');
        const pagesCount = document.getElementById('scanPagesCount');
        const has = this.scannedFiles && this.scannedFiles.length > 0;

        if (clearScannedBtn) clearScannedBtn.style.display = has ? 'inline-flex' : 'none';

        // عند وجود ملف ممسوح، نص الزر الأساسي يتحول إلى "مسح جديد"
        if (startScanBtn && has) {
            startScanBtn.innerHTML = '<i class="bi bi-arrow-repeat me-1"></i>مسح جديد';
            startScanBtn.title = 'بدء مسح جديد (يستبدل الحالي)';
        } else if (startScanBtn) {
            startScanBtn.innerHTML = '<i class="bi bi-upc-scan me-1"></i>مسح من السكانر';
            startScanBtn.title = 'بدء المسح من السكانر';
        }

        if (pagesCount) {
            if (has && this.scannedFiles.length > 1) {
                pagesCount.textContent = `${this.scannedFiles.length} صفحات مدموجة`;
                pagesCount.style.display = 'block';
            } else {
                pagesCount.style.display = 'none';
            }
        }
    }

    // ===== معاينة المستند الممسوح كصور خادم (PyMuPDF) — تلائم اللوحة دائماً =====
    renderPreviewPage(n) {
        if (!this.previewToken) return;
        this._ensureManifest();
        const total = this.pageCount || 1;
        n = Math.max(1, Math.min(total, n));
        const modalBody = document.getElementById('modalBody');
        if (!modalBody) return;

        let stage = modalBody.querySelector('.preview-stage');
        const firstBuild = !stage;
        if (firstBuild) {
            modalBody.innerHTML = '';
            modalBody.classList.add('has-image');
            stage = this._buildPreviewStage();
            modalBody.appendChild(stage);
            this._buildThumbs();
            this._bindPager();
            this._bindKeyboard();
        }
        // إعادة ضبط الملاءمة/التمرير عند الانتقال لصفحة أخرى فقط — لا عند إعادة رسم نفس الصفحة
        // (تحديث الدقّة أو التدوير/الحذف) كي لا يقفز التكبير الحالي فجأة.
        const pageChanged = firstBuild || n !== this.currentPage;
        const scroll  = stage.querySelector('.preview-scroll');
        const img     = stage.querySelector('.preview-img');
        const spinner = stage.querySelector('.preview-spinner');
        const errBox  = stage.querySelector('.preview-error');
        let   skel    = stage.querySelector('.dc-skeleton');
        if (!skel) {
            skel = document.createElement('div');
            skel.className = 'dc-skeleton';
            (scroll || stage).insertBefore(skel, img);
        }

        errBox.style.display = 'none';
        // هيكل عظمي بأبعاد الصفحة (من المانيفست) ⇒ صفر قفزة تخطيط + إحساس فوري بالسرعة
        skel.style.setProperty('--dc-ar', this._pageAspect(n));
        skel.style.display = 'block';
        img.classList.remove('dc-loaded');     // أخفِ الصورة القديمة أثناء التحميل (تلاشٍ)
        if (pageChanged) this.zoom = 1;
        this.currentPage = n;                  // اضبط الصفحة قبل القياس كي تُستخدم نسبة أبعادها الصحيحة
        this._applyZoom();
        if (pageChanged && scroll) { scroll.scrollTop = 0; scroll.scrollLeft = 0; }

        // مؤشّر بطيء: لا يظهر إلا إن تأخّر التحميل (تفادي وميض للصفحات المُخبّأة مسبقاً)
        spinner.style.display = 'none';
        clearTimeout(this._slowSpinnerTimer);
        this._slowSpinnerTimer = setTimeout(() => { spinner.style.display = 'flex'; }, 300);

        // التقط هوية الطلب؛ تجاهل onload/onerror متأخّراً إن تغيّر المستند/الإصدار (حارس قديم — يُحفظ حرفياً)
        const reqTok = this.previewToken, reqVer = this._previewVersion || 0;
        img.onload = () => {
            if (this.previewToken !== reqTok || (this._previewVersion || 0) !== reqVer) return;
            clearTimeout(this._slowSpinnerTimer);
            spinner.style.display = 'none';
            skel.style.display = 'none';
            img.classList.add('dc-loaded');
            this.currentPage = n;
            this._applyZoom();                     // إعادة القياس بأبعاد الصفحة المؤكَّدة
            if (pageChanged && scroll) scroll.scrollTop = 0;
            this._updatePager();
            this._updateThumbsActive();
            this._prefetchNeighbors(n);
        };
        img.onerror = () => {
            if (this.previewToken !== reqTok || (this._previewVersion || 0) !== reqVer) return;
            clearTimeout(this._slowSpinnerTimer);
            spinner.style.display = 'none';
            skel.style.display = 'none';
            errBox.style.display = 'flex';
        };
        img.src = `/books/api/scan/preview/${encodeURIComponent(this.previewToken)}/?page=${n}&dpi=${this.previewDpi}&_v=${this._previewVersion || 0}`;
        this.currentPage = n;
        this._updatePager();
    }

    /** نسبة أبعاد الصفحة (عرض/ارتفاع) من المانيفست — مع مراعاة الدوران 90/270؛ A4 افتراضاً. */
    _pageAspect(n) {
        const p = this._manifest && this._manifest.pages && this._manifest.pages[n - 1];
        if (p && p.w && p.h) {
            const rot90 = (((p.rot || 0) % 180) !== 0);
            const w = rot90 ? p.h : p.w, h = rot90 ? p.w : p.h;
            if (w > 0 && h > 0) return (w / h).toFixed(4);
        }
        return '0.707';   // A4 (1 / 1.414)
    }

    /** جلب هندسة الصفحات (مرة لكل token/إصدار) لرسم هيكل عظمي بأبعاد صحيحة. غير حاجب. */
    _ensureManifest() {
        const tok = this.previewToken, ver = this._previewVersion || 0;
        if (!tok || (this._manifestTok === tok && this._manifestVer === ver)) return;
        this._manifestTok = tok; this._manifestVer = ver; this._manifest = null;
        fetch(`/books/api/scan/manifest/${encodeURIComponent(tok)}/`, { credentials: 'same-origin' })
            .then(r => r.ok ? r.json() : null)
            .then(m => {
                if (!m || this.previewToken !== tok || (this._previewVersion || 0) !== ver) return;
                this._manifest = m;
                const skel = document.querySelector('#modalBody .dc-skeleton');
                if (skel && skel.style.display !== 'none') {
                    skel.style.setProperty('--dc-ar', this._pageAspect(this.currentPage || 1));
                }
            })
            .catch(() => {});
    }

    /** جلب مسبق للصفحتين المجاورتين (تنقّل فوري) — يعتمد على كاش المتصفح. */
    _prefetchNeighbors(n) {
        const total = this.pageCount || 1, tok = this.previewToken, ver = this._previewVersion || 0;
        [n - 1, n + 1].forEach(p => {
            if (p >= 1 && p <= total) {
                const im = new Image();
                im.src = `/books/api/scan/preview/${encodeURIComponent(tok)}/?page=${p}&dpi=${this.previewDpi}&_v=${ver}`;
            }
        });
    }

    /** تنقّل لوحة المفاتيح (RTL) — مع حارس: لا يسرق المفاتيح من حقول الإدخال. يُربط مرة واحدة. */
    _bindKeyboard() {
        if (this._kbBound) return;
        this._kbBound = true;
        document.addEventListener('keydown', (e) => {
            if (!this.previewToken) return;
            if (!document.querySelector('#modalBody .preview-stage')) return;
            const ae = document.activeElement;
            if (ae && (ae.tagName === 'INPUT' || ae.tagName === 'TEXTAREA' || ae.isContentEditable)) return;
            const total = this.pageCount || 1, cur = this.currentPage || 1;
            switch (e.key) {
                case 'ArrowLeft': case 'PageDown': e.preventDefault(); this.renderPreviewPage(cur + 1); break;   // RTL: يسار = التالي
                case 'ArrowRight': case 'PageUp':  e.preventDefault(); this.renderPreviewPage(cur - 1); break;
                case 'Home': e.preventDefault(); this.renderPreviewPage(1); break;
                case 'End':  e.preventDefault(); this.renderPreviewPage(total); break;
                case '+': case '=': e.preventDefault(); this._stepZoom(1); break;
                case '-': e.preventDefault(); this._stepZoom(-1); break;
                case '0': e.preventDefault(); this._zoomTo(1, null, null); break;
            }
        });
    }

    /** يُستدعى من لوحة إدارة المستندات بعد أي تعديل: أبطِل المعاينة وأعِد تحميل الأساسي الجديد. */
    invalidatePreview(bookId) {
        this.previewToken = null;
        this._manifest = null; this._manifestTok = null;
        this._pagesEditedInPreview = false;   // عملية DocManager تجبّ أي تعديلات صفحات معلّقة

        if (!bookId) { if (this._resetPreviewState) this._resetPreviewState(); return; }
        fetch(`/books/api/book/${bookId}/preview/`, { headers: { 'X-Requested-With': 'XMLHttpRequest' }, credentials: 'same-origin' })
            .then(r => r.ok ? r.json() : null)
            .then(d => {
                const atts = (d && d.attachments) || [];
                const primary = atts.find(a => a.is_primary) || atts[0];
                if (primary && this.loadSavedAttachment) this.loadSavedAttachment(primary.id);
                else if (this._resetPreviewState) this._resetPreviewState();
            })
            .catch(() => {});
    }

    /**
     * تحرير الصفحات على PDF المؤقّت قبل الحفظ (تدوير/حذف/إعادة ترتيب) عبر token.
     * بعد النجاح: يعيد رسم الصفحة والمصغّرات (مع كسر الكاش) ويحدّث الملف للحفظ.
     */
    async _editPage(payload) {
        if (!this.previewToken) return null;
        const csrf = document.querySelector('[name=csrfmiddlewaretoken]')?.value;
        const stage = document.querySelector('#modalBody .preview-stage');
        const spinner = stage && stage.querySelector('.preview-spinner');
        if (spinner) spinner.style.display = 'flex';
        try {
            const resp = await fetch(`/books/api/scan/edit/${encodeURIComponent(this.previewToken)}/`, {
                method: 'POST', credentials: 'same-origin',
                headers: { 'X-CSRFToken': csrf, 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
            });
            const r = await resp.json();
            if (!r.ok) {
                if (spinner) spinner.style.display = 'none';
                this.showToast(r.error || 'تعذّر تعديل المستند', 'error');
                return null;
            }
            this.pageCount = r.page_count;
            // تتبّع الصفحات المُلحقة حديثاً للتمييز البصري (شارة «جديد»).
            if (!this._insertedPages) this._insertedPages = new Set();
            if (payload.op === 'insert' && r.inserted_count) {
                for (let k = 0; k < r.inserted_count; k++) this._insertedPages.add(r.inserted_from + k);
                this.currentPage = r.inserted_from;   // انتقل لأول صفحة مُلحقة ليراها المستخدم فوراً
            } else if (payload.op === 'delete' || payload.op === 'reorder') {
                this._insertedPages.clear();          // تغيّرت أرقام الصفحات — تبطل شارات «جديد»
            }
            if (this.currentPage > this.pageCount) this.currentPage = this.pageCount;
            this._previewVersion = (this._previewVersion || 0) + 1;   // كسر كاش الصور
            this._buildThumbs();
            this.renderPreviewPage(this.currentPage);
            this._refreshCurrentFileFromToken();
            // علِّم أن صفحات المعاينة عُدِّلت فعلاً (تدوير/حذف/ترتيب/إلحاق) — يُستخدم في وضع
            // التعديل لإرسال الملف المُعدَّل عند الحفظ فقط عند وجود تعديل حقيقي.
            this._pagesEditedInPreview = true;
            return r;
        } catch (e) {
            if (spinner) spinner.style.display = 'none';
            this.showToast('تعذّر الاتصال — حاول مجدداً', 'error');
            return null;
        }
    }

    // ===== إلحاق صفحات (مسح/رفع) بالمستند القائم في وضع التعديل — تجهيز داخل المعاينة =====
    /** يُهيّئ ملف مصدر (مرفوع/ممسوح) عبر process-upload ويعيد token جاهزاً للإلحاق. */
    async _stageSourceForAppend(file, name) {
        const csrf = document.querySelector('[name=csrfmiddlewaretoken]')?.value;
        const fd = new FormData();
        fd.append('file', file, name || file.name || 'append.pdf');
        fd.append('trim_blanks', '1');   // قصّ الفراغات كمسار المسح
        try {
            const resp = await fetch('/books/api/scan/process-upload/', {
                method: 'POST', credentials: 'same-origin',
                headers: { 'X-CSRFToken': csrf }, body: fd,
            });
            const ud = await resp.json();
            if (!ud.ok) { this.showToast(ud.error || 'تعذّر تجهيز المستند للإلحاق', 'error', 6000); return null; }
            return ud.token;
        } catch (e) {
            this.showToast('تعذّر الاتصال أثناء تجهيز المستند — حاول مجدداً', 'error', 5000);
            return null;
        }
    }

    /** يُلحق مصدراً مُهيّأً (source_token) بنهاية المستند المُرحَّل في المعاينة + تنبيه واضح. */
    async appendFromSourceToken(sourceToken) {
        if (!this.previewToken) { this.showToast('افتح مستنداً في المعاينة أولاً', 'warning'); return; }
        const r = await this._editPage({ op: 'insert', source_token: sourceToken });
        if (r && r.ok) {
            const n = r.inserted_count || 0;
            this._showAppendNotice(n);
            this.showToast(`✓ أُلحقت ${n} صفحة بنهاية المستند — احفظ التعديلات لتثبيت التحديث`, 'success', 5000, 'تمّ الإلحاق');
        }
        return r;
    }

    /** إلحاق ملف مرفوع (PDF/صورة) بنهاية المستند — يُستدعى من DocumentManager. */
    async appendUploadedFile(file) {
        if (!file) return;
        this._showExtractionOverlay('جارٍ تجهيز المستند للإلحاق…', 'يتم رفعه ومعالجته على الخادم');
        try {
            const token = await this._stageSourceForAppend(file);
            if (token) await this.appendFromSourceToken(token);
        } finally {
            this._hideExtractionOverlay();
        }
    }

    /** مسح صفحات جديدة وإلحاقها بنهاية المستند — يُستدعى من DocumentManager (وضع التعديل). */
    async scanAndAppend() {
        return this.startScan({ appendMode: true });
    }

    /** شريط إشعار سطري داخل لوحة المعاينة يؤكّد الإلحاق ويتيح التراجع — وعيُ المستخدم. */
    _showAppendNotice(count) {
        const host = document.querySelector('.extraction-preview-modal') || document.body;
        let bar = document.getElementById('appendNotice');
        if (!bar) {
            bar = document.createElement('div');
            bar.id = 'appendNotice';
            bar.className = 'append-notice';
            host.appendChild(bar);
        }
        bar.innerHTML =
            `<span class="append-notice-msg"><i class="bi bi-check-circle-fill"></i> أُلحقت ${count} صفحة بنهاية المستند — راجعها ثم <strong>احفظ التعديلات</strong> لتثبيت التحديث.</span>`;
        const undo = document.createElement('button');
        undo.type = 'button';
        undo.className = 'append-notice-undo';
        undo.innerHTML = '<i class="bi bi-arrow-counterclockwise"></i> تراجع';
        undo.onclick = () => this._undoAppend();
        bar.appendChild(undo);
        bar.style.display = 'flex';
    }

    _hideAppendNotice() {
        const b = document.getElementById('appendNotice');
        if (b) b.style.display = 'none';
    }

    /** تراجع: يعيد المستند للأصل المحفوظ (يتجاهل تعديلات المعاينة غير المحفوظة). */
    _undoAppend() {
        if (this._insertedPages) this._insertedPages.clear();
        this._pagesEditedInPreview = false;
        this._hideAppendNotice();
        const attId = this._editData && this._editData.attachment && this._editData.attachment.id;
        if (attId && this.loadSavedAttachment) {
            this.loadSavedAttachment(attId);
            this.showToast('تم التراجع — عاد المستند إلى الأصل المحفوظ', 'info', 4000);
        }
    }

    /** يعيد جلب الـPDF المُعدَّل من الخادم ليُحفظ مع الكتاب (يبقى الملف متّسقاً مع المعاينة). */
    _refreshCurrentFileFromToken() {
        if (!this.previewToken) return;
        const url = `/books/api/scan/serve/${encodeURIComponent(this.previewToken)}/?_v=${this._previewVersion || 0}`;
        fetch(url, { credentials: 'same-origin' })
            .then(r => r.ok ? r.blob() : null)
            .then(blob => {
                if (!blob) return;
                const base = ((this.currentFile && this.currentFile.name) || 'document.pdf').replace(/\.[^.]+$/, '');
                this.currentFile = new File([blob], base + '.pdf', { type: 'application/pdf' });
                this.scannedFiles = [this.currentFile];
            })
            .catch(() => {});
    }

    _buildPreviewStage() {
        const stage = document.createElement('div');
        stage.className = 'preview-stage';

        // طبقة التمرير الداخلية: تحمل الصفحة وتُمرّرها في كل الاتجاهات، بينما تبقى الأدوات
        // (أشرطة التكبير/التحرير) ثابتة على المسرح فلا تجرفها عملية التمرير.
        const scroll = document.createElement('div');
        scroll.className = 'preview-scroll';
        stage.appendChild(scroll);

        const img = document.createElement('img');
        img.className = 'preview-img';
        img.alt = 'معاينة المستند';
        img.draggable = false;
        scroll.appendChild(img);

        const zoom = document.createElement('div');
        zoom.className = 'preview-zoom';
        zoom.innerHTML =
            '<button type="button" class="pz-btn" data-z="out" title="تصغير (‪-‬)"><i class="bi bi-zoom-out"></i></button>' +
            '<span class="pz-label">100%</span>' +
            '<button type="button" class="pz-btn" data-z="in" title="تكبير (‪+‬)"><i class="bi bi-zoom-in"></i></button>' +
            '<button type="button" class="pz-btn" data-z="fit" title="ملاءمة"><i class="bi bi-arrows-angle-expand"></i></button>';
        zoom.querySelector('[data-z=out]').onclick = () => this._stepZoom(-1);
        zoom.querySelector('[data-z=in]').onclick  = () => this._stepZoom(1);
        zoom.querySelector('[data-z=fit]').onclick = () => this._toggleFit();
        stage.appendChild(zoom);

        // أدوات تحرير الصفحة الحالية (تدوير/حذف) — تعمل على PDF المؤقّت عبر token
        const tools = document.createElement('div');
        tools.className = 'preview-tools';
        tools.innerHTML =
            '<button type="button" class="pt-btn" data-op="rot-left" title="تدوير لليسار"><i class="bi bi-arrow-counterclockwise"></i></button>' +
            '<button type="button" class="pt-btn" data-op="rot-right" title="تدوير لليمين"><i class="bi bi-arrow-clockwise"></i></button>' +
            '<span class="pt-sep"></span>' +
            '<button type="button" class="pt-btn pt-danger" data-op="del" title="حذف هذه الصفحة"><i class="bi bi-trash3"></i></button>';
        tools.querySelector('[data-op=rot-left]').onclick  = () => this._editPage({ op: 'rotate', page: this.currentPage, angle: 270 });
        tools.querySelector('[data-op=rot-right]').onclick = () => this._editPage({ op: 'rotate', page: this.currentPage, angle: 90 });
        tools.querySelector('[data-op=del]').onclick = () => {
            if ((this.pageCount || 1) <= 1) { this.showToast('لا يمكن حذف الصفحة الوحيدة', 'warning'); return; }
            this._editPage({ op: 'delete', page: this.currentPage });
        };
        stage.appendChild(tools);

        const spinner = document.createElement('div');
        spinner.className = 'preview-spinner';
        spinner.innerHTML = '<div class="spinner-border text-primary" role="status"></div>';
        stage.appendChild(spinner);

        const errBox = document.createElement('div');
        errBox.className = 'preview-error';
        errBox.style.display = 'none';
        errBox.innerHTML = '<i class="bi bi-exclamation-triangle"></i><div>تعذّر عرض هذه الصفحة</div>';
        const retry = document.createElement('button');
        retry.type = 'button'; retry.className = 'btn btn-sm btn-outline-secondary';
        retry.textContent = 'إعادة المحاولة';
        retry.onclick = () => this.renderPreviewPage(this.currentPage);
        const dl = document.createElement('a');
        dl.className = 'pe-download'; dl.textContent = 'تنزيل الملف الأصلي';
        dl.href = `/books/api/scan/serve/${encodeURIComponent(this.previewToken)}/`;
        dl.setAttribute('download', '');
        errBox.appendChild(retry); errBox.appendChild(dl);
        stage.appendChild(errBox);

        // تنقّل مرن: Ctrl + عجلة الفأرة = تكبير حول المؤشّر (العجلة وحدها تُمرّر عادياً)،
        // ونقر مزدوج يبدّل بين ملاءمة/تكبير 2× عند نقطة النقر.
        scroll.addEventListener('wheel', (e) => {
            if (!e.ctrlKey) return;
            e.preventDefault();
            this._zoomAt(e.deltaY < 0 ? 1 : -1, e.clientX, e.clientY, 1.18);
        }, { passive: false });
        scroll.addEventListener('dblclick', (e) => {
            e.preventDefault();
            if (this.zoom > 1.01) { this._zoomTo(1, e.clientX, e.clientY); }
            else { this._zoomAt(1, e.clientX, e.clientY, 2); }
        });

        // إعادة القياس عند تغيّر حجم النافذة/اللوحة (يُربط مرّة واحدة)
        if (!this._resizeBound) {
            this._resizeBound = true;
            window.addEventListener('resize', () => {
                clearTimeout(this._resizeTimer);
                this._resizeTimer = setTimeout(() => {
                    if (document.querySelector('#modalBody .preview-scroll')) this._applyZoom();
                }, 120);
            });
        }

        this._enablePan(scroll, img);
        return stage;
    }

    /** يبدّل نمط الملاءمة: عرض اللوحة ⇄ الصفحة كاملة (يُعيد ضبط التكبير والتمرير). */
    _toggleFit() {
        this.fitMode = (this.fitMode === 'width') ? 'page' : 'width';
        this.zoom = 1;
        this._applyZoom();
        const scroll = document.querySelector('#modalBody .preview-scroll');
        if (scroll) { scroll.scrollTop = 0; scroll.scrollLeft = 0; }
    }

    _stepZoom(dir) {
        const steps = [1, 1.25, 1.5, 2, 3, 4];
        let i = steps.findIndex(s => Math.abs(s - this.zoom) < 0.02);
        if (i === -1) {   // تكبير حرّ (من العجلة) ⇒ اقفز لأقرب خطوة في الاتجاه المطلوب
            i = 0; for (let k = 0; k < steps.length; k++) { if (steps[k] <= this.zoom + 0.02) i = k; }
        }
        i = Math.max(0, Math.min(steps.length - 1, i + dir));
        this._zoomTo(steps[i], null, null);
    }

    /** يحسب مقاس «الملاءمة» بالبكسل من نسبة أبعاد الصفحة وحجم طبقة التمرير. */
    _computeFitSize(scroll) {
        const pad = 14;   // هامش تنفّس بسيط داخل الطبقة
        const availW = Math.max(40, scroll.clientWidth  - pad);
        const availH = Math.max(40, scroll.clientHeight - pad);
        const ar = parseFloat(this._pageAspect(this.currentPage || 1)) || 0.707;   // عرض/ارتفاع
        let w, h;
        if (this.fitMode === 'width') {
            w = availW; h = w / ar;                       // يملأ العرض (أكبر/أوضح، بلا هوامش جانبية)
        } else {                                          // 'page' — احتواء كامل الصفحة
            if (availW / availH > ar) { h = availH; w = h * ar; }
            else { w = availW; h = w / ar; }
        }
        return { w, h };
    }

    _applyZoom() {
        const modalBody = document.getElementById('modalBody');
        const stage = modalBody && modalBody.querySelector('.preview-stage');
        if (!stage) return;
        const scroll = stage.querySelector('.preview-scroll');
        const img = stage.querySelector('.preview-img');
        const label = stage.querySelector('.pz-label');
        if (scroll && img) {
            const fit = this._computeFitSize(scroll);
            img.style.width  = Math.round(fit.w * this.zoom) + 'px';
            img.style.height = Math.round(fit.h * this.zoom) + 'px';
            const pannable = (scroll.scrollHeight > scroll.clientHeight + 1) ||
                             (scroll.scrollWidth  > scroll.clientWidth  + 1);
            img.style.cursor = pannable ? 'grab' : 'default';
        }
        if (label) label.textContent = Math.round(this.zoom * 100) + '%';
        const fitBtn = stage.querySelector('[data-z=fit]');
        if (fitBtn) fitBtn.title = (this.fitMode === 'width') ? 'ملاءمة كامل الصفحة' : 'ملاءمة عرض الصفحة';
    }

    /** يضبط التكبير مع تثبيت نقطة (clientX/Y) بصرياً في مكانها — لتنقّل مريح. */
    _zoomTo(newZoom, cx, cy) {
        newZoom = Math.max(1, Math.min(5, newZoom));
        const stage = document.querySelector('#modalBody .preview-stage');
        const scroll = stage && stage.querySelector('.preview-scroll');
        if (!scroll) { this.zoom = newZoom; this._applyZoom(); return; }
        const rect = scroll.getBoundingClientRect();
        const ax = (cx == null) ? rect.width  / 2 : (cx - rect.left);
        const ay = (cy == null) ? rect.height / 2 : (cy - rect.top);
        const prev = this.zoom || 1;
        const beforeX = scroll.scrollLeft + ax;
        const beforeY = scroll.scrollTop  + ay;
        this.zoom = newZoom;
        this._applyZoom();
        const ratio = newZoom / prev;
        scroll.scrollLeft = beforeX * ratio - ax;   // يُقصّ تلقائياً إلى [0, max]
        scroll.scrollTop  = beforeY * ratio - ay;
    }

    /** خطوة تكبير نسبية حول نقطة (للعجلة/النقر المزدوج) مع مواءمة الدقّة عند التكبير القوي. */
    _zoomAt(dir, cx, cy, factor) {
        const f = factor || 1.18;
        const nz = Math.max(1, Math.min(5, dir > 0 ? this.zoom * f : this.zoom / f));
        const wantDpi = nz > 1.5 ? 220 : 130;
        if (wantDpi !== this.previewDpi) { this.previewDpi = wantDpi; this.renderPreviewPage(this.currentPage); }
        this._zoomTo(nz, cx, cy);
    }

    _enablePan(scroll, img) {
        let down = false, sx = 0, sy = 0, sl = 0, st = 0;
        const canPan = () => (scroll.scrollHeight > scroll.clientHeight + 1) ||
                             (scroll.scrollWidth  > scroll.clientWidth  + 1);
        scroll.addEventListener('mousedown', (e) => {
            if (e.button !== 0 || !canPan()) return;
            down = true; sx = e.clientX; sy = e.clientY; sl = scroll.scrollLeft; st = scroll.scrollTop;
            if (img) img.style.cursor = 'grabbing'; e.preventDefault();
        });
        window.addEventListener('mousemove', (e) => {
            if (!down) return;
            scroll.scrollLeft = sl - (e.clientX - sx);
            scroll.scrollTop  = st - (e.clientY - sy);
        });
        window.addEventListener('mouseup', () => {
            if (!down) return; down = false;
            if (img) img.style.cursor = canPan() ? 'grab' : 'default';
        });
    }

    _bindPager() {
        const prev = document.getElementById('pagerPrev');
        const next = document.getElementById('pagerNext');
        if (prev && !prev.dataset.bound) { prev.onclick = () => this.renderPreviewPage(this.currentPage - 1); prev.dataset.bound = '1'; }
        if (next && !next.dataset.bound) { next.onclick = () => this.renderPreviewPage(this.currentPage + 1); next.dataset.bound = '1'; }
    }

    _updatePager() {
        const pager = document.getElementById('previewPager');
        if (!pager) return;
        const total = this.pageCount || 1;
        if (total <= 1) { pager.style.display = 'none'; return; }
        pager.style.display = '';
        const label = document.getElementById('pagerLabel');
        const prev = document.getElementById('pagerPrev');
        const next = document.getElementById('pagerNext');
        if (label) label.textContent = `صفحة ${this.currentPage} / ${total}`;
        if (prev) prev.disabled = this.currentPage <= 1;
        if (next) next.disabled = this.currentPage >= total;
    }

    _buildThumbs() {
        const wrap = document.getElementById('previewThumbs');
        if (!wrap) return;
        const total = this.pageCount || 1;
        if (total <= 1 || !this.previewToken) { wrap.style.display = 'none'; wrap.innerHTML = ''; return; }
        wrap.style.display = '';
        wrap.innerHTML = '';
        const v = this._previewVersion || 0;
        for (let i = 1; i <= total; i++) {
            const cell = document.createElement('div');
            cell.className = 'thumb-cell';
            cell.draggable = true;
            cell.dataset.page = i;
            const t = document.createElement('img');
            t.className = 'preview-thumb';
            t.loading = 'lazy';
            t.src = `/books/api/scan/preview/${encodeURIComponent(this.previewToken)}/?page=${i}&dpi=46&_v=${v}`;
            t.alt = 'صفحة ' + i;
            const num = document.createElement('span');
            num.className = 'thumb-num';
            num.textContent = i;
            cell.appendChild(t);
            cell.appendChild(num);
            // تمييز الصفحات المُلحقة حديثاً (قبل الحفظ) بصرياً — وعيُ المستخدم بما أضافه
            if (this._insertedPages && this._insertedPages.has(i)) {
                cell.classList.add('thumb-cell--new');
                const badge = document.createElement('span');
                badge.className = 'thumb-new-badge';
                badge.textContent = 'جديد';
                cell.appendChild(badge);
            }
            cell.onclick = () => this.renderPreviewPage(parseInt(cell.dataset.page, 10));
            this._bindThumbDnD(cell, wrap);
            wrap.appendChild(cell);
        }
        this._updateThumbsActive();
    }

    /** سحب-وإفلات لإعادة ترتيب الصفحات في شريط المصغّرات. */
    _bindThumbDnD(cell, wrap) {
        cell.addEventListener('dragstart', (e) => {
            cell.classList.add('dragging');
            e.dataTransfer.effectAllowed = 'move';
            try { e.dataTransfer.setData('text/plain', cell.dataset.page); } catch (_) {}
        });
        cell.addEventListener('dragend', () => {
            cell.classList.remove('dragging');
            this._commitThumbOrder(wrap);
        });
        cell.addEventListener('dragover', (e) => {
            e.preventDefault();
            const dragging = wrap.querySelector('.thumb-cell.dragging');
            if (!dragging || dragging === cell) return;
            const rect = cell.getBoundingClientRect();
            // في RTL يُعكس المحور: النصف الأيمن من الخليّة يعني «قبل» لا «بعد»
            const rtl = getComputedStyle(wrap).direction === 'rtl';
            const pastHalf = (e.clientX - rect.left) > rect.width / 2;
            const after = rtl ? !pastHalf : pastHalf;
            wrap.insertBefore(dragging, after ? cell.nextSibling : cell);
        });
    }

    /** يرسل الترتيب الجديد للخادم إن تغيّر فعلاً عن التسلسل الحالي. */
    _commitThumbOrder(wrap) {
        const order = [...wrap.querySelectorAll('.thumb-cell')].map(c => parseInt(c.dataset.page, 10));
        if (order.length <= 1) return;
        const unchanged = order.every((p, idx) => p === idx + 1);
        if (unchanged) return;
        this._editPage({ op: 'reorder', order });
    }

    _updateThumbsActive() {
        const wrap = document.getElementById('previewThumbs');
        if (!wrap) return;
        [...wrap.querySelectorAll('.thumb-cell')].forEach((el) =>
            el.classList.toggle('active', parseInt(el.dataset.page, 10) === this.currentPage));
    }

    _renderPdfFallback(blob, fileName) {
        const modalBody = document.getElementById('modalBody');
        if (!modalBody) return;
        const url = URL.createObjectURL(blob);
        this._trackPreviewUrl(url);
        modalBody.classList.add('has-image');
        const card = document.createElement('div');
        card.className = 'preview-pdf-fallback';
        card.innerHTML = '<i class="bi bi-file-earmark-pdf"></i><div class="pf-name"></div>';
        card.querySelector('.pf-name').textContent = fileName || 'document.pdf';
        const open = document.createElement('a');
        open.href = url; open.target = '_blank'; open.rel = 'noopener';
        open.className = 'btn btn-sm btn-outline-primary'; open.textContent = 'فتح في تبويب جديد';
        const dl = document.createElement('a');
        dl.href = url; dl.download = fileName || 'document.pdf';
        dl.className = 'btn btn-sm btn-outline-secondary'; dl.textContent = 'تنزيل';
        const row = document.createElement('div'); row.className = 'pf-actions';
        row.appendChild(open); row.appendChild(dl);
        card.appendChild(row);
        modalBody.appendChild(card);
    }

    /** يعيد ضبط حالة المعاينة (صفحات/زوم) وإخفاء أدواتها. */
    _resetPreviewState() {
        this.previewToken = null;
        this.pageCount = 1;
        this.currentPage = 1;
        this.zoom = 1;
        this.fitMode = 'width';
        this.previewDpi = 130;
        const pager = document.getElementById('previewPager');
        const thumbs = document.getElementById('previewThumbs');
        if (pager) pager.style.display = 'none';
        if (thumbs) { thumbs.style.display = 'none'; thumbs.innerHTML = ''; }
    }

    /** حذف الملف الممسوح (للسماح بإعادة المسح من جديد). */
    clearScannedFile() {
        console.log('[ExtractionSmart] clearScannedFile() called');
        this.scannedFiles = [];
        this._resetPreviewState();
        this.clearFile();
        this._updateScanState();
        this.showToast('تم حذف الملف الممسوح — يمكنك المسح من جديد', 'success');
    }

    displayBlobPreview(blob, fileName) {
        const modalBody = document.getElementById('modalBody');
        if (!modalBody) {
            console.error('[ExtractionSmart] ✗ modalBody not found');
            return;
        }

        // 🧹 إلغاء أي Object URL سابق لتجنّب تسرّب الذاكرة
        this._revokeLastPreviewUrls();

        // مسح المحتوى السابق أولاً
        modalBody.innerHTML = '';

        // تحديد النوع بدقة
        let mimeType = blob.type || 'application/octet-stream';
        const fileExt = (fileName || '').split('.').pop().toLowerCase();

        console.log('[ExtractionSmart] displayBlobPreview:', {
            fileName,
            fileExt,
            detectedMimeType: mimeType,
            blobSize: blob.size
        });

        // إذا كان MIME type فارغ، استنتج من الامتداد
        if (!blob.type || blob.type === '') {
            if (['jpg', 'jpeg'].includes(fileExt)) mimeType = 'image/jpeg';
            else if (fileExt === 'png') mimeType = 'image/png';
            else if (fileExt === 'gif') mimeType = 'image/gif';
            else if (fileExt === 'pdf') mimeType = 'application/pdf';
            console.log('[ExtractionSmart] MIME type corrected to:', mimeType);
        }

        // فحص نوع الملف
        const isImage = mimeType.startsWith('image/');
        const isPdf = mimeType.includes('pdf') || fileExt === 'pdf';

        console.log('[ExtractionSmart] File type flags:', { isImage, isPdf, mimeType });

        if (isImage) {
            // تحميل الصورة من الـ blob
            try {
                const url = URL.createObjectURL(blob);
                this._trackPreviewUrl(url);
                const img = document.createElement('img');
                img.src = url;
                img.style.maxWidth = '100%';
                img.style.maxHeight = '100%';
                img.style.objectFit = 'contain';
                img.style.display = 'block';
                img.style.margin = '0 auto';
                img.onload = () => {
                    console.log('[ExtractionSmart] ✓ Image loaded successfully');
                    modalBody.classList.add('has-image');
                };
                img.onerror = (err) => {
                    console.error('[ExtractionSmart] ✗ Image load failed:', err);
                    modalBody.innerHTML = '<div style="color: #ef4444; text-align: center; padding: 20px;">خطأ في تحميل الصورة</div>';
                };
                modalBody.appendChild(img);
                modalBody.classList.add('has-image');
                console.log('[ExtractionSmart] ✓ Image element appended');
            } catch (e) {
                console.error('[ExtractionSmart] ✗ Image creation error:', e);
                modalBody.innerHTML = '<div style="color: #ef4444; text-align: center; padding: 20px;">خطأ: ' + e.message + '</div>';
            }
        } else if (isPdf) {
            // PDF: يُرسَم كصور خادم (PyMuPDF) عبر token — يلائم اللوحة دائماً (لا embed)
            if (this.previewToken) {
                modalBody.classList.add('has-image');
                this.renderPreviewPage(this.currentPage || 1);
            } else {
                // ملاذ: PDF محلي بلا token (نادر) — بطاقة فتح/تنزيل بدل عارض مدمج لا يلائم
                this._renderPdfFallback(blob, fileName);
            }
        } else {
            // ملف غير معروف
            const fileDiv = document.createElement('div');
            fileDiv.style.textAlign = 'center';
            fileDiv.style.padding = '40px 20px';
            fileDiv.style.display = 'flex';
            fileDiv.style.flexDirection = 'column';
            fileDiv.style.alignItems = 'center';
            fileDiv.style.justifyContent = 'center';
            fileDiv.style.minHeight = '350px';
            fileDiv.innerHTML = '<div style="font-size: 4rem; margin-bottom: 20px; opacity: 0.7;">📎</div><div style="font-size: 1.1rem; font-weight: 600; color: #1e293b; margin-bottom: 10px;">ملف</div><div style="font-size: 0.85rem; color: #64748b; word-break: break-word; max-width: 280px;">' + (fileName || 'unknown') + '</div>';
            modalBody.appendChild(fileDiv);
            modalBody.classList.add('has-image');
            console.log('[ExtractionSmart] ✓ Generic file display created');
        }

        // إظهار زر التنزيل فقط (إذا وجد ملف فعلي)
        try {
            const f = this.currentFile;
            if (f) this._updateDownloadButton(f, fileName);
            console.log('[ExtractionSmart] ✓ Download button updated for blob preview');
        } catch (e) {
            console.error('[ExtractionSmart] ✗ Error updating download button:', e);
        }

        console.log('[ExtractionSmart] ✓ Blob preview fully displayed');
    }

    processFile(file) {
        // Validate file type
        const validTypes = ['image/jpeg', 'image/png', 'image/jpg', 'application/pdf'];
        if (!validTypes.includes(file.type)) {
            this.showToast('نوع الملف غير مدعوم. استخدم صورة أو PDF', 'error');
            return;
        }

        // Validate file size (max 10MB)
        if (file.size > 10 * 1024 * 1024) {
            this.showToast('حجم الملف أكبر من 10MB', 'error');
            return;
        }

        this.displayFileName(file.name);
        // المسار الموحّد: نُجهّز الملف على الخادم (صورة→PDF) ونحصل على token كي تعمل
        // معاينة الصفحات وأدوات التحرير (تدوير/حذف/إعادة ترتيب) على الرفع كما المسح.
        this.stageAndPreview(file).catch(err => {
            console.warn('[upload] staging failed — fallback to client preview:', err);
            this._hideExtractionOverlay();   // لا تترك مؤشّر الرفع عالقاً عند فشل التجهيز
            this.currentFile = file;
            this.displayFilePreview(file);
            // صراحةً: نُبلّغ سبب فشل التجهيز على الخادم بدل رسالة نجاح مضلِّلة، ثم نحاول محلياً
            const why = (err && err.message) ? ` (${err.message})` : '';
            this.showToast(`تعذّرت معالجة الملف على الخادم${why} — جارٍ محاولة محلية…`, 'warning', 6000);
            setTimeout(() => this.extractData(), 350);
        });
    }

    /**
     * تجهيز ملف مرفوع على الخادم (process-upload) للحصول على token موحّد:
     * الصور تُحوَّل إلى PDF، وتُفتح نفس معاينة الصفحات القابلة للتحرير كالمسح.
     */
    async stageAndPreview(file) {
        const csrf = document.querySelector('[name=csrfmiddlewaretoken]')?.value;
        const fd = new FormData();
        fd.append('file', file, file.name);
        // تجهيز فقط بلا OCR: الاستخراج يجري بعد المعاينة عبر extractData (المحكوم بمفتاح
        // «استخراج تلقائي»). بدون هذا كان OCR يعمل مرّتين — في process-upload (وتُهمَل
        // نتيجتها) ثم في smart_extract_direct — فيتضاعف أبطأ جزء في المسار.
        fd.append('auto_ocr', '0');
        // مؤشّر تحميل احترافي داخل لوحة المعاينة (بدل التجمّد الصامت أثناء رفع/معالجة المستند).
        // يبقى ظاهراً حتى تُرسَم المعاينة، ثم يعود أثناء الاستخراج — فلا يشعر المستخدم بجمود.
        this._showExtractionOverlay('جارٍ رفع المستند…', 'يتم رفع المستند ومعالجته على الخادم');
        const resp = await fetch('/books/api/scan/process-upload/', {
            method: 'POST', credentials: 'same-origin',
            headers: { 'X-CSRFToken': csrf }, body: fd,
        });
        const ud = await resp.json();
        if (!ud.ok) throw new Error(ud.error || 'فشل تجهيز الملف');

        this.previewToken = ud.token;
        this.pageCount = ud.page_count || 1;
        this.currentPage = 1;
        this.previewDpi = 130;
        this._previewVersion = (this._previewVersion || 0) + 1;
        // إن أعاد الخادم تنبيهاً (مثلاً: تعذّر الاستخراج التلقائي — أدخِل يدوياً) نُظهره
        // في مسار الرفع أيضاً، لا مسار السكانر وحده (كان يُهمَل هنا سابقاً).
        if (ud.warning) this._showProgressBanner(ud.warning, 'warning');
        const serveUrl = `/books/api/scan/serve/${encodeURIComponent(ud.token)}/`;
        this.loadScannedFile(serveUrl, ud.source_file || file.name, { noAutoExtract: false });
    }

    /**
     * يحمّل مرفقاً محفوظاً في معاينة الصفحات (وضع التعديل) — يعرض المستند المحفوظ.
     * لا يضبط currentFile كي لا يُكرَّر المرفق عند الحفظ دون تعديل؛ أي تعديل صفحات
     * لاحق (تدوير/حذف) سيضبطه عبر _refreshCurrentFileFromToken.
     */
    async loadSavedAttachment(attachmentId) {
        try {
            const r = await fetch(`/books/api/scan/stage-attachment/${attachmentId}/`, { credentials: 'same-origin' });
            const d = await r.json();
            if (!d.ok) { console.warn('[edit] stage-attachment failed:', d.error); return; }
            this.previewToken = d.token;
            this.pageCount = d.page_count || 1;
            this.currentPage = 1;
            this.previewDpi = 130;
            this._previewVersion = (this._previewVersion || 0) + 1;
            this.displayFileName(d.source_file || 'document.pdf');
            const modalBody = document.getElementById('modalBody');
            if (modalBody) modalBody.classList.add('has-image');
            this.renderPreviewPage(1);
        } catch (e) {
            console.warn('[edit] loadSavedAttachment error:', e);
        }
    }

    displayFilePreview(file) {
        const modalBody = document.getElementById('modalBody');
        const reader = new FileReader();

        reader.onload = (e) => {
            const container = document.createElement('div');
            container.className = 'image-preview-container';

            if (file.type.startsWith('image/')) {
                const img = document.createElement('img');
                img.src = e.target.result;
                container.appendChild(img);
            } else if (file.type === 'application/pdf') {
                container.innerHTML = '<div style="text-align: center; color: #94a3b8;"><div style="font-size: 3rem; margin-bottom: 10px;">📄</div><div>ملف PDF</div></div>';
            }

            modalBody.innerHTML = '';
            modalBody.classList.add('has-image');
            modalBody.appendChild(container);

            // إظهار زر التنزيل فقط
            this._updateDownloadButton(file, file.name);
            console.log('[ExtractionSmart] ✓ Download button shown');
        };

        reader.readAsDataURL(file);
    }

    _updateDownloadButton(/* source, fileName */) {
        // أُلغي زر تنزيل الملف من تذييل المعاينة — أزرار تجميل/فتح الملف في أماكن أخرى تفي بالغرض
    }

    /* ===== بانر تحذير fallback ===== */
    _showFallbackBanner(reason) {
        const banner = document.getElementById('fallbackBanner');
        if (!banner) return;
        const sub = document.getElementById('fallbackBannerReason');
        if (sub) {
            sub.textContent = reason
                ? `خدمة الذكاء الاصطناعي غير متاحة — السبب: ${reason}`
                : 'خدمة الذكاء الاصطناعي غير متاحة — تم ملء الحقول ببيانات افتراضية';
        }
        banner.style.display = 'flex';
        const closeBtn = document.getElementById('fallbackBannerClose');
        if (closeBtn && !closeBtn._bound) {
            closeBtn._bound = true;
            closeBtn.addEventListener('click', () => this._hideFallbackBanner());
        }
    }
    _hideFallbackBanner() {
        const banner = document.getElementById('fallbackBanner');
        if (banner) banner.style.display = 'none';
    }

    /* ===== إدارة Object URLs (منع تسريب الذاكرة) ===== */
    _trackPreviewUrl(url) {
        if (!this._previewUrls) this._previewUrls = [];
        this._previewUrls.push(url);
    }
    _revokeLastPreviewUrls() {
        if (!this._previewUrls || !this._previewUrls.length) return;
        for (const u of this._previewUrls) {
            try { URL.revokeObjectURL(u); } catch (_) { /* ignore */ }
        }
        this._previewUrls = [];
    }

    displayFileName(name, extra) {
        // العرض في رأس المعاينة (modal-header)
        const headerInfo = document.getElementById('modalFileInfo');
        const headerName = document.getElementById('modalFileName');
        const headerMeta = document.getElementById('modalFileMeta');
        if (headerInfo && headerName) {
            headerName.textContent = name || '';
            headerName.title = name || '';
            // بناء سطر التفاصيل: النوع + الحجم + عدد الصفحات
            const parts = [];
            const f = this.currentFile;
            if (f && typeof f.size === 'number') {
                const kb = f.size / 1024;
                parts.push(kb >= 1024 ? (kb / 1024).toFixed(1) + ' MB' : kb.toFixed(0) + ' KB');
            }
            if (Array.isArray(this.scannedFiles) && this.scannedFiles.length > 1) {
                parts.push(this.scannedFiles.length + ' صفحات');
            }
            if (extra) parts.push(extra);
            if (headerMeta) headerMeta.textContent = parts.join(' · ');
            headerInfo.style.display = 'flex';
        }
        // التوافق الخلفي: تعبئة الحقول المخفية المتبقية
        const fileName = document.getElementById('fileName');
        const filePreview = document.getElementById('filePreview');
        if (fileName) fileName.textContent = name || '';
        if (filePreview) filePreview.style.display = 'none';
    }

    clearFile() {
        console.log('[ExtractionSmart] clearFile() called');
        this.currentFile = null;
        this.scannedFiles = [];
        // أخفِ بانر التحذير عند تفريغ الملف
        this._hideFallbackBanner();
        // أعد نص زر الاستخراج للحالة الافتراضية
        const extractBtn = document.getElementById('extractButton');
        if (extractBtn) extractBtn.innerHTML = '🔍 استخراج';
        // حرّر أي Object URLs عالقة
        this._revokeLastPreviewUrls();
        // نظّف حالة المعاينة (شريط المصغّرات + المرقّم + الرمز) — كانت تبقى ظاهرة أسفل
        // لوحة المعاينة بعد الحفظ لأن مسار الحفظ يستدعي clearFile لا clearScannedFile.
        if (typeof this._resetPreviewState === 'function') this._resetPreviewState();
        const fileInput = document.getElementById('fileInput');
        const filePreview = document.getElementById('filePreview');
        const modalBody = document.getElementById('modalBody');
        
        if (fileInput) fileInput.value = '';
        if (filePreview) filePreview.style.display = 'none';
        
        if (modalBody) {
            modalBody.innerHTML = `
                <div class="empty-state">
                    <div class="empty-state-icon">📄</div>
                    <div class="empty-state-text">لم يتم تحميل ملف بعد</div>
                </div>
            `;
            modalBody.classList.remove('has-image');
        }

        // إخفاء رأس الملف في modal-header
        const headerInfo = document.getElementById('modalFileInfo');
        if (headerInfo) headerInfo.style.display = 'none';

        // أزرار شريط المسح: إخفاء "مسح المزيد" و "حذف الممسوح" + إعادة نص "مسح من السكانر"
        if (typeof this._updateScanState === 'function') this._updateScanState();

        this.showToast('تم مسح الملف', 'success');
        console.log('[ExtractionSmart] ✓ File cleared');
    }

    // ===== Data Extraction =====
    _showExtractionOverlay(message, sub, onCancel) {
        const modalBody = document.getElementById('modalBody');
        if (!modalBody) return;
        // Remove existing overlay
        const existing = modalBody.querySelector('.extraction-loading-overlay');
        if (existing) existing.remove();
        const overlay = document.createElement('div');
        overlay.className = 'extraction-loading-overlay';
        overlay.innerHTML = `
            <div class="overlay-spinner"></div>
            <div class="overlay-text">${message || 'جاري الاستخراج الذكي...'}</div>
            <div class="overlay-sub">${sub || 'يتم تحليل المستند واستخراج البيانات'}</div>
            <div class="overlay-progress" role="progressbar" aria-label="جارٍ التحميل"><div class="overlay-progress-bar"></div></div>
        `;
        // زر إلغاء داخل الأوفرلاي — لا يترك المستخدم عالقاً حين يهنغ المسح (وضع الإلحاق: شريط المسح مخفيّ)
        if (typeof onCancel === 'function') {
            const c = document.createElement('button');
            c.type = 'button';
            c.className = 'overlay-cancel';
            c.innerHTML = '<i class="bi bi-x-circle"></i> إلغاء';
            c.addEventListener('click', () => { try { onCancel(); } catch (_) {} });
            overlay.appendChild(c);
        }
        modalBody.style.position = 'relative';
        modalBody.appendChild(overlay);
    }

    _hideExtractionOverlay() {
        const modalBody = document.getElementById('modalBody');
        if (!modalBody) return;
        const overlay = modalBody.querySelector('.extraction-loading-overlay');
        if (overlay) {
            overlay.style.opacity = '0';
            overlay.style.transition = 'opacity 0.3s';
            setTimeout(() => overlay.remove(), 300);
        }
    }

    // (أُزيلت مراحل الأوفرلاي المؤقّتة الوهمية: البثّ التدريجي صار يعطي مرحلةً حقيقية
    //  من الأنبوب مع كل حدث — انظر _onExtractStage.)

    _focusFirstReviewField(data) {
        // بعد الاستخراج، ضع التركيز على أول حقل مهم يحتاج مراجعة (ثقة منخفضة أو فارغ)
        const priority = ['title', 'senderNumber', 'issuingEntity', 'receivingEntity', 'secretLevel'];
        const lowConf = ['title', 'senderNumber'];
        for (const fieldId of priority) {
            const el = document.getElementById(fieldId);
            if (!el) continue;
            const val = el.value ? el.value.trim() : '';
            const conf = data ? (data[`${fieldId === 'title' ? 'title' : fieldId}_confidence`] || 0) : 0;
            if (!val || conf < 0.65) {
                try { el.focus(); } catch (e) {}
                return;
            }
        }
    }

    extractData() {
        if (!this.currentFile) {
            this.showToast(this.t('uploadRequired'), 'warning');
            return;
        }

        const extractBtn = document.getElementById('extractButton');
        const originalText = extractBtn ? extractBtn.innerHTML : '';
        if (extractBtn) {
            extractBtn.innerHTML = '<span class="spinner"></span> جاري...';
            extractBtn.disabled = true;
        }
        // تقدّم حقيقي من الأنبوب (بدل مؤقّتات وهمية) + إيقاف يُبقي ما استُخرج
        this._streamFilled = new Set();
        this._extractStopped = false;
        this._extractAbort = new AbortController();
        this._showExtractionOverlay(
            'جارٍ تجهيز المستند…',
            'ستُملأ الحقول تِباعاً فور استخراج كلٍّ منها',
            () => this._stopExtraction());

        this._streamExtract()
            .then((data) => {
                if (this._extractStopped) return;
                const fallbackFlag = (data.details && data.details.fallback) || (data.message && data.message.toLowerCase().includes('mock'));
                if (fallbackFlag) {
                    const reason = data.details && data.details.reason ? ` (سبب: ${data.details.reason})` : '';
                    this.showToast(this.t('fallbackExtraction') + reason, 'warning', 7000);
                    this._showFallbackBanner(data.details && data.details.reason);
                } else {
                    this._hideFallbackBanner();
                }
                if (data.request_id) {
                    console.info('extract request_id:', data.request_id);
                }
                // رسالة صادقة بحسب النتيجة الفعلية: صفر حقول ⇒ لا نُبلّغ «نجاحاً» بل نُرشد
                // للإدخال اليدوي (المستند محفوظ ومعروض)؛ وإلا نؤكّد عدد الحقول المُستخرَجة.
                const extractedCount = this._countExtractedFields(data);
                if (extractedCount === 0) {
                    this.showToast('تعذّرت قراءة بيانات المستند تلقائياً — أدخِل الحقول يدوياً. المستند محفوظ ومعروض للمراجعة.', 'warning', 8000);
                    if (extractBtn) extractBtn.innerHTML = '↺ إعادة المحاولة';
                } else {
                    this.showToast(`${this.t('extractSuccess')} (${extractedCount} حقل)`, 'success');
                    if (extractBtn) extractBtn.innerHTML = '↺ إعادة الاستخراج';
                }
                // ركّز على أول حقل يحتاج مراجعة/إدخال — إرشادٌ بصريّ لما يفعله المستخدم تالياً
                setTimeout(() => this._focusFirstReviewField(data), 200);
            })
            .catch((err) => {
                // الإيقاف المقصود ليس خطأً — _stopExtraction تولّى الرسالة والحالة
                if (this._extractStopped || err.name === 'AbortError') return;
                this.showToast(err.message || this.t('extractFail'), 'error', 6000);
                console.error(err);
            })
            .finally(() => {
                this._hideExtractionOverlay();
                if (extractBtn) extractBtn.disabled = false;
                // إذا لم يتغير الزر بسبب الخطأ، أعد النص الأصلي
                if (extractBtn && extractBtn.innerHTML.includes('جاري')) {
                    extractBtn.innerHTML = originalText;
                }
            });
    }

    // ═══════ الاستخراج التدريجي الحيّ (بثّ NDJSON) ═══════
    /** يبثّ الاستخراج ويملأ الحقول تِباعاً، ويُعيد الحصيلة النهائية.
     *  مسارٌ واحد يحلّ محلّ النداء المتزامن القديم: تقدّم حقيقي من الأنبوب + إيقاف
     *  يُبقي ما وصل (بدل انتظار كلّ شيء ثم لا شيء عند القطع). */
    async _streamExtract() {
        const form = new FormData();
        form.append('file', this.currentFile);

        let response;
        try {
            response = await fetch(this.apiEndpoints.smartExtractStream, {
                method: 'POST',
                headers: { 'X-CSRFToken': this.getCookie('csrftoken') },
                body: form,
                credentials: 'same-origin',
                signal: this._extractAbort.signal,
            });
        } catch (err) {
            if (err.name === 'AbortError') throw err;      // إيقاف المستخدم — يعالجه _stopExtraction
            throw new Error(`خطأ في الاتصال: ${err.message}`);
        }

        if (!response.ok) {
            let msg = `فشل الاستخراج (HTTP ${response.status}).`;
            try {
                const body = await response.json();
                if (body && body.error) msg = body.error;
            } catch (_) {
                if (response.status === 403 || response.redirected) {
                    msg = 'انتهت الجلسة — سجّل الدخول ثم أعد المحاولة.';
                }
            }
            throw new Error(msg);
        }
        if (!response.body) throw new Error('المتصفّح لا يدعم القراءة التدريجية للاستجابة.');

        const reader = response.body.getReader();
        const decoder = new TextDecoder('utf-8');
        let buffer = '', final = null;
        for (;;) {
            const { done, value } = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, { stream: true });
            let nl;
            while ((nl = buffer.indexOf('\n')) >= 0) {
                const line = buffer.slice(0, nl).trim();
                buffer = buffer.slice(nl + 1);
                if (!line) continue;
                let ev;
                try { ev = JSON.parse(line); } catch (_) { continue; }   // سطر تالف يُتخطّى
                if (ev.type === 'stage') this._onExtractStage(ev);
                else if (ev.type === 'error') throw new Error(ev.message || this.t('extractFail'));
                else if (ev.type === 'done') final = ev;
            }
        }
        if (!final) throw new Error('انقطع البثّ قبل اكتمال الاستخراج — أعد المحاولة.');
        this.applyExtractionResult(final);   // الحصيلة الكاملة (جهات + مرشّحات + ملخّص الثقة)
        return final;
    }

    /** حدث مرحلة: رسالة تقدّم صادقة من الأنبوب + ملء ما اكتمل من حقول فوراً. */
    _onExtractStage(ev) {
        this._applyPartialFields(ev.fields);
        const overlay = document.querySelector('#modalBody .extraction-loading-overlay');
        if (!overlay) return;
        const text = overlay.querySelector('.overlay-text');
        const sub = overlay.querySelector('.overlay-sub');
        if (text) text.textContent = `يجري ${ev.label}…`;
        if (sub) {
            const names = [...(this._streamFilled || [])].map(id => this._fieldLabelAr(id)).filter(Boolean);
            sub.textContent = names.length
                ? `تم استخراج: ${names.join('، ')}`
                : 'ستُملأ الحقول تِباعاً فور استخراج كلٍّ منها';
        }
    }

    /** يملأ حقول اللقطة الجزئية — مرّة واحدة لكل حقل (لا يدهس ما ملأه المستخدم بعدها). */
    _applyPartialFields(fields) {
        if (!fields) return;
        const filled = this._streamFilled || (this._streamFilled = new Set());
        [
            ['bookNumber', 'book_number', 'book_number_confidence'],
            ['title', 'title', 'title_confidence'],
            ['date', 'book_date', 'book_date_confidence'],
            ['senderDate', 'sender_date', 'sender_date_confidence'],
            ['senderNumber', 'sender_number', 'sender_number_confidence'],
            ['secretLevel', 'secret_level', 'secret_level_confidence'],
        ].forEach(([id, key, confKey]) => {
            const value = fields[key];
            if (value === undefined || value === null || value === '' || filled.has(id)) return;
            const el = document.getElementById(id);
            if (!el) return;
            if (id === 'bookNumber' && !this._reconcileManualNumber(el, value, fields[confKey])) {
                filled.add(id);          // حُسم أمره — لا نُعيد سؤاله في اللقطة التالية
                return;
            }
            el.value = (id === 'date' || id === 'senderDate') ? String(value).slice(0, 10) : value;
            // نفس ترتيب applyExtractionResult: حدث input أولاً ثم الثقة، وإلا وُسِم «يقين بشري»
            try { el.dispatchEvent(new Event('input', { bubbles: true })); } catch (_) {}
            const conf = fields[confKey] || 0;
            this.updateConfidenceBadge(id, conf);
            this.setFieldConfidence(id, conf);
            this.validateField(id);
            filled.add(id);
        });
        if (window.__autoGrowTitle) window.__autoGrowTitle();
    }

    _fieldLabelAr(id) {
        return ({
            bookNumber: 'رقمنا', title: 'الموضوع', date: 'تاريخنا',
            senderDate: 'تاريخ الجهة', senderNumber: 'العدد', secretLevel: 'السرية',
        })[id] || '';
    }

    /** إيقاف الاستخراج الجاري: يقطع البثّ ويُبقي كلّ ما مُلئ حتى اللحظة للإكمال يدوياً. */
    _stopExtraction() {
        if (this._extractStopped) return;
        this._extractStopped = true;
        try { this._extractAbort?.abort(); } catch (_) {}
        this._hideExtractionOverlay();
        const kept = (this._streamFilled || new Set()).size;
        this.showToast(
            kept ? `أُوقف الاستخراج — بقي ما استُخرج (${kept} حقل)، أكمل الباقي يدوياً.`
                 : 'أُوقف الاستخراج — أدخِل الحقول يدوياً.',
            'info', 6000, 'إيقاف الاستخراج');
        const btn = document.getElementById('extractButton');
        if (btn) { btn.disabled = false; btn.innerHTML = '↺ إعادة الاستخراج'; }
    }

    // يَعُدّ الحقول التي استُخرجت فعلاً (قيمة غير فارغة) — لرسالة صادقة بعد الاستخراج:
    // صفر ⇒ فشل قراءة ⇒ إرشاد للإدخال اليدوي بدل ادّعاء النجاح.
    _countExtractedFields(data) {
        const keys = ['book_number', 'title', 'book_date', 'sender_date', 'sender_number',
                      'issuing_entity', 'receiving_entity', 'secret_level', 'book_kind'];
        return keys.reduce((n, k) => {
            const v = data[k];
            return n + ((typeof v !== 'undefined' && v !== null && String(v).trim() !== '') ? 1 : 0);
        }, 0);
    }

    /**
     * يوفّق بين ما كتبه الموظّف في حقل الرقم وما قرأه الاستخلاص من المستند.
     *
     * يُعيد true إن جاز للاستخلاص الكتابة في الحقل، وfalse إن وجب تركه.
     * ثلاث حالات:
     *   • سجلّ له سلسلة  → الرقم محجوز من النظام؛ الاستخلاص لا يمسّه إطلاقاً.
     *   • الحقل فارغ     → يُملأ من المستند (وهو المقصود من المسح).
     *   • فيه رقم مكتوب  → يتطابقان: تأكيد صامت بعلامة. يختلفان: نسأله أيّهما الصحيح.
     */
    _reconcileManualNumber(input, extracted, confidence) {
        const kind = document.getElementById('bookKind')?.value;
        if (!this.getKindConfig(kind).manualNumber) return false;   // سلسلة النظام لا تُمسّ

        const norm = (v) => String(v ?? '').replace(/[^\d]/g, '');
        const typed = norm(input.value);
        const read = norm(extracted);
        if (!read) return false;

        if (!typed) {
            input.classList.add('number-from-scan');
            this.showToast(`قُرئ رقم الصادر من المستند: ${read}`, 'info', 4000);
            return true;
        }
        if (typed === read) {
            input.classList.add('number-confirmed');
            this.showToast(`تطابق: الرقم الذي كتبته «${typed}» هو نفسه المقروء من المستند.`, 'success', 4000);
            return false;                       // القيمة نفسها — لا داعي للكتابة
        }

        const takeScan = window.confirm(
            'اختلاف في رقم الصادر:\n\n' +
            `  ما كتبتَه      : ${input.value}\n` +
            `  المقروء من المستند: ${extracted}` +
            (confidence ? `  (ثقة ${Math.round(confidence * 100)}%)` : '') +
            '\n\nموافق = اعتمد المقروء من المستند\nإلغاء = أبقِ ما كتبتَه'
        );
        input.classList.add(takeScan ? 'number-from-scan' : 'number-kept-manual');
        if (!takeScan) this.showToast('أُبقي رقمك كما كتبتَه.', 'warning', 4000);
        return takeScan;
    }

    applyExtractionResult(data) {
        // حلقة التعلّم (إصلاح 2026-08-16): الخادم يسكّ رمز مسحٍ لكلّ استخراج — بما فيه
        // **الرفع اليدويّ** الذي كان بلا رمز فيضيع تصحيح الكاتب (6 سجلّات التقاطٍ فقط
        // في القاعدة كلّها). نحفظه هنا ليُرسَل مع الحفظ فيُلتقَط الزوج (اقتراح → تصحيح).
        if (data && data.scan_token) this.scanToken = data.scan_token;
        const mapping = [
            { field: 'bookNumber', key: 'book_number', conf: 'book_number_confidence' },
            { field: 'title', key: 'title', conf: 'title_confidence' },
            { field: 'date', key: 'book_date', conf: 'book_date_confidence' },
            { field: 'senderDate', key: 'sender_date', conf: 'sender_date_confidence' },
            { field: 'senderNumber', key: 'sender_number', conf: 'sender_number_confidence' },
            { field: 'issuingEntity', key: 'issuing_entity', conf: 'issuing_entity_confidence' },
            { field: 'receivingEntity', key: 'receiving_entity', conf: 'receiving_entity_confidence' },
            { field: 'secretLevel', key: 'secret_level', conf: 'secret_level_confidence' },
            { field: 'bookKind', key: 'book_kind', conf: 'book_kind_confidence' }
        ];

        mapping.forEach(({ field, key, conf }) => {
            const value = data[key];
            if (typeof value !== 'undefined' && value !== null) {
                const input = document.getElementById(field);
                if (input) {
                    // رقم السجلّ اليدويّ (الصادر الخارجي): لا يُكتب فوق ما كتبه الموظّف
                    // بصمت. إن تطابقا فتأكيدٌ صامت، وإن اختلفا فقرارٌ صريح منه.
                    if (field === 'bookNumber' && !this._reconcileManualNumber(input, value, data[conf])) {
                        return;
                    }
                    if (field === 'bookKind') {
                        let resolvedKind = value;
                        if (resolvedKind === 'incoming') {
                            resolvedKind = 'incoming_internal';
                        } else if (resolvedKind === 'outgoing') {
                            resolvedKind = 'outgoing_internal';
                        }
                        input.value = resolvedKind;
                        this.syncKindUI(resolvedKind);
                    } else if (field === 'date' || field === 'senderDate' || field === 'dueDate') {
                        // حقول التاريخ (type=date) تقبل YYYY-MM-DD فقط — أسقِط جزء الوقت
                        // من ISO («2026-06-20T00:00:00» → «2026-06-20») وإلا يرفضها المتصفّح.
                        input.value = String(value).slice(0, 10);
                    } else {
                        input.value = value;
                    }
                    // إطلاق حدث input لتفعيل مؤشر التحقق وتفعيل زر الحفظ
                    try { input.dispatchEvent(new Event('input', { bubbles: true })); } catch (e) {}
                    try { input.dispatchEvent(new Event('change', { bubbles: true })); } catch (e) {}
                    this.updateConfidenceBadge(field, data[conf] || 0);
                    this.setFieldConfidence(field, data[conf] || 0);   // حافّة الثقة
                    this.validateField(field);
                }
            }
        });

        const extractedDocumentType = (data.document_type || data.book_type_name || '').trim();
        if (extractedDocumentType) {
            this.setDocumentTypeValue(extractedDocumentType, this.getCurrentKind());
        }

        // ملخّص الثقة الكلي + تنبيه المراجعة (بطاقتا P1)
        this.updateQualitySummary(data);
        this.renderEntityCandidates(data);

        // ضمان تحديث عام بعد الانتهاء من كل الحقول
        if (typeof updateValidationIndicator === 'function') {
            try { updateValidationIndicator(); } catch (e) {}
        }
    }

    // مرشّحو الجهة top-3 بنسب التشابه — يُزرعون تحت حقلَي الجهة داخل التخطيط
    // القائم بلا أي تغيير في ترتيب الصفحة (قرار المالك 2026-07-19).
    renderEntityCandidates(data) {
        // تأجيل دورة: بعد تحويل قيمة الـAI إلى وسم (patch القالب يعمل بعد 50ms)
        setTimeout(() => {
            this._renderCandidateList('issuing', data.issuing_entity_matches);
            this._renderCandidateList('receiving', data.receiving_entity_matches);
        }, 120);
    }

    _renderCandidateList(side, matches) {
        const wrap = document.getElementById(side === 'issuing' ? 'issuingTagWrapper' : 'receivingTagWrapper');
        const container = wrap && wrap.closest('.entity-input-container');
        if (!container) return;
        let box = container.querySelector('.entity-candidates');
        const list = (Array.isArray(matches) ? matches : []).filter(m => (m.entity_name || '').trim());
        if (!list.length) { if (box) box.remove(); return; }
        if (!box) {
            box = document.createElement('div');
            box.className = 'entity-candidates';
            container.appendChild(box);
        }
        const sourceLabels = { memory: 'من الذاكرة', letterhead: 'من الترويسة', register: 'رمز السجلّ', pattern: 'نمط صريح' };
        const mgr = window.entityTagManagers?.[side];
        box.replaceChildren();
        list.slice(0, 3).forEach((m) => {
            const name = m.entity_name.trim();
            const pct = Math.round((m.score || 0) * 100);
            const chosen = !!(mgr && mgr.tags.some(t => (t.name || '').trim().toLowerCase() === name.toLowerCase()));
            const btn = document.createElement('button');
            btn.type = 'button';
            btn.className = 'entity-candidate' + (chosen ? ' is-chosen' : '');
            btn.title = chosen ? 'مُضافة كوسم' : 'إضافة كوسم';
            const nameEl = document.createElement('span');
            nameEl.className = 'candidate-name';
            nameEl.textContent = name;
            const bar = document.createElement('span');
            bar.className = 'candidate-bar';
            const fill = document.createElement('i');
            fill.style.width = pct + '%';
            bar.appendChild(fill);
            const pctEl = document.createElement('span');
            pctEl.className = 'candidate-pct';
            pctEl.textContent = pct + '%';
            const srcEl = document.createElement('small');
            srcEl.className = 'candidate-src';
            srcEl.textContent = chosen ? '✓' : (sourceLabels[m.match_type] || '');
            btn.append(nameEl, bar, pctEl, srcEl);
            btn.addEventListener('click', () => {
                if (!mgr || btn.classList.contains('is-chosen')) return;
                if (m.entity_id) mgr.addEntity({ id: m.entity_id, name, code: '' });
                else mgr._resolveOrCreate(name, true);
                box.remove();   // أدّت القائمة غرضها — تختفي بعد التضمين (قرار المالك)
            });
            box.appendChild(btn);
        });
    }

    // ملخّص الثقة الكلي (quality-hero) + تنبيه المراجعة (needs_review) — بطاقتا P1
    updateQualitySummary(data) {
        const overall = (typeof data.overall_confidence === 'number') ? data.overall_confidence : null;
        const hero = document.getElementById('qualityHero');
        if (hero && overall !== null) {
            const p = Math.round(overall * 100);
            const level = this.getConfidenceLevel(overall);
            const ring = document.getElementById('qualityHeroRing');
            const pct = document.getElementById('qualityHeroPct');
            const title = document.getElementById('qualityHeroTitle');
            const sub = document.getElementById('qualityHeroSub');
            if (pct) pct.textContent = `${p}%`;
            if (ring) {
                ring.className = `quality-hero-ring quality-hero-ring--${level}`;
                ring.style.setProperty('--pct', String(p));
            }
            if (title) {
                title.textContent = level === 'high' ? 'جودة استخراج عالية'
                    : level === 'medium' ? 'جودة استخراج متوسطة' : 'جودة استخراج منخفضة';
            }
            if (sub) {
                sub.textContent = level === 'high' ? 'تحقّق سريع ثم احفظ.'
                    : 'راجع الحقول المُبرزة قبل الحفظ.';
            }
            hero.style.display = '';
        }
        const nrc = document.getElementById('needsReviewCard');
        if (nrc) nrc.style.display = data.needs_review ? '' : 'none';
    }

    updateConfidenceBadge(fieldId, confidence) {
        const confidenceElement = document.getElementById(`${fieldId}Confidence`);
        if (!confidenceElement) return;

        const level = this.getConfidenceLevel(confidence);
        confidenceElement.className = `confidence-badge ${level}`;
        // حارس: قد توجد حاوية الشارة دون عنصر القيمة الداخلي (مثلاً شارة أُضيفت لحقل
        // جديد بلا span للقيمة) — نتجاهل تحديث النص بدل رمي TypeError.
        const valueElement = document.getElementById(`${fieldId}ConfidenceValue`);
        if (valueElement) valueElement.textContent = `${Math.round(confidence * 100)}%`;
        confidenceElement.style.display = 'inline-flex';
    }

    getConfidenceLevel(confidence) {
        if (confidence >= CONFIDENCE_THRESHOLDS.high) return 'high';
        if (confidence >= CONFIDENCE_THRESHOLDS.medium) return 'medium';
        return 'low';
    }

    // ═══ حافّة الثقة (رؤية التصميم — الميزة الرائدة): الثقة خاصية فيزيائية للحقل ═══
    // نقطة الربط الوحيدة، تُستدعى من مسارَي الملء (المسح + الرفع) فتعمل الثقة في كليهما.
    setFieldConfidence(fieldId, score) {
        const g = document.getElementById(fieldId)?.closest('.form-group-smart');
        if (!g) return;
        const s = Number(score) || 0;
        g.dataset.conf = s >= CONFIDENCE_THRESHOLDS.high ? 'high'
            : s >= CONFIDENCE_THRESHOLDS.medium ? 'medium' : 'low';
        g.dataset.machineConf = String(s);
        // نحفظ القيمة المُستخرَجة الأصلية لتتبّع التصحيح لاحقاً (أفكار التعلّم في الرؤية)
        (this._origExtracted || (this._origExtracted = {}))[fieldId] = {
            value: (document.getElementById(fieldId)?.value || '').trim(), extracted: true
        };
    }

    // التلاشي بالّمس: تعديل حقل مُستخرَج يحوّل حافّته إلى «يقين بشري» تركوازي.
    markHumanConfirmed(fieldId) {
        const g = document.getElementById(fieldId)?.closest('.form-group-smart');
        if (g && g.dataset.conf && g.dataset.conf !== 'human') g.dataset.conf = 'human';
    }

    // ===== Form Validation =====
    handleFieldInput(e) {
        const fieldId = e.target.id;
        this.markHumanConfirmed(fieldId);   // التلاشي بالّمس → يقين بشري تركوازي
        this.validateField(fieldId);
        this.updateSuggestions(fieldId, e.target.value);
    }

    validateField(fieldId) {
        const field = document.getElementById(fieldId);
        if (!field) return;

        const value = field.value.trim();
        const isValid = this.validateFieldValue(fieldId, value);

        if (isValid) {
            field.classList.remove('has-error');
            field.classList.add('is-valid');
        } else if (value !== '') {
            field.classList.add('has-error');
            field.classList.remove('is-valid');
        } else {
            field.classList.remove('has-error', 'is-valid');
        }

        return isValid;
    }

    validateFieldValue(fieldId, value) {
        const validations = {
            // bookNumber: قبول أي شيء مرن - أرقام، رموز، نص
            bookNumber: value !== '' && value.trim() !== '', // يجب ألا يكون فارغاً إذا كان مطلوباً
            title: value.length >= 3 || value === '',
            date: /^\d{4}-\d{2}-\d{2}$/.test(value) || value === '',
            issuingEntity: value.length >= 2 || value === '',
            receivingEntity: value.length >= 2 || value === '',
            documentTypeSelect: this.getResolvedDocumentTypeValue(this.getCurrentKind()).length > 0,
            documentTypeCustom: !this.isCustomDocumentTypeSelected() || value.length > 0
        };

        return validations[fieldId] !== false;
    }

    // ===== Entity Code Recognition System =====
    loadEntityData() {
        // Load all entities with their codes from the backend
        fetch(this.apiEndpoints.entityList, {
            headers: {
                'X-CSRFToken': this.getCookie('csrftoken')
            }
        })
        .then(response => response.json())
        .then(data => {
            if (data.success && data.entities) {
                this.entityList = data.entities; // Array of {id, name, code, etype}
                console.log('[ExtractionSmart] ✓ Loaded', this.entityList.length, 'entities');
            } else {
                this.entityList = [];
                console.warn('[ExtractionSmart] No entities loaded');
            }
        })
        .catch(error => {
            console.error('[ExtractionSmart] Failed to load entities:', error);
            this.entityList = [];
        });
    }

    searchEntities(query, entityType = null) {
        // ⚡ Advanced search: by code, name, or partial match with smart priorities
        if (!query || !this.entityList) return [];
        
        const q = query.trim().toLowerCase();
        const results = [];
        
        // 🏆 Priority 1: Exact code match (ش3 = ش3)
        const exactCodeMatch = this.entityList.find(e => 
            e.code && e.code.toLowerCase() === q &&
            (!entityType || e.etype === entityType || e.etype === 'both')
        );
        if (exactCodeMatch) results.push({...exactCodeMatch, matchType: 'code', priority: 1});
        
        // 🥈 Priority 2: Code starts with (ش = ش1, ش2, ش3...)
        this.entityList.forEach(e => {
            if (e.code && e.code.toLowerCase().startsWith(q) && 
                (!entityType || e.etype === entityType || e.etype === 'both') &&
                !results.find(r => r.id === e.id)) {
                results.push({...e, matchType: 'code', priority: 2});
            }
        });
        
        // 🥉 Priority 3: Code contains (e.g., "ل" in "ل ج")
        this.entityList.forEach(e => {
            if (e.code && e.code.toLowerCase().includes(q) && 
                (!entityType || e.etype === entityType || e.etype === 'both') &&
                !results.find(r => r.id === e.id)) {
                results.push({...e, matchType: 'code', priority: 3});
            }
        });
        
        // 🥈 Priority 2: Name starts with
        this.entityList.forEach(e => {
            if (e.name.toLowerCase().startsWith(q) && 
                (!entityType || e.etype === entityType || e.etype === 'both') &&
                !results.find(r => r.id === e.id)) {
                results.push({...e, matchType: 'name', priority: 2});
            }
        });
        
        // 🥉 Priority 3: Name contains
        this.entityList.forEach(e => {
            if (e.name.toLowerCase().includes(q) && 
                (!entityType || e.etype === entityType || e.etype === 'both') &&
                !results.find(r => r.id === e.id)) {
                results.push({...e, matchType: 'name', priority: 3});
            }
        });
        
        return results.slice(0, 15); // Max 15 results
    }

    setupEntityCodeRecognition() {
        // ⚡ Advanced entity fields with code/name recognition + smart suggestions
        const entityFields = [
            { id: 'issuingEntity', type: 'issuer', dropdownId: 'issuingEntityDropdown' },
            { id: 'receivingEntity', type: 'receiver', dropdownId: 'receivingEntityDropdown' }
        ];

        entityFields.forEach(({ id, type, dropdownId }) => {
            const field = document.getElementById(id);
            const dropdown = document.getElementById(dropdownId);
            if (!field || !dropdown) {
                console.warn(`[ExtractionSmart] Entity field not found: ${id} or ${dropdownId}`);
                return;
            }

            let debounceTimer = null;
            let selectedId = null;

            // 1️⃣ ON INPUT: Real-time search - عرض الاقتراحات فقط، بدون ملء تلقائي
            field.addEventListener('input', (e) => {
                const value = e.target.value.trim();
                selectedId = null; // Reset when user types
                clearTimeout(debounceTimer);
                
                if (!value) {
                    dropdown.style.display = 'none';
                    return;
                }
                
                // Search والعرض فقط - لا ملء تلقائي
                debounceTimer = setTimeout(() => {
                    const results = this.searchEntities(value, type);
                    if (results.length > 0) {
                        this.displayEntitySuggestions(id, results, dropdown, field, type);
                    } else {
                        dropdown.style.display = 'none';
                    }
                }, 150); // زيادة التأخير قليلاً
            });

            // 2️⃣ ON BLUR: محاولة المطابقة النهائية
            field.addEventListener('blur', (e) => {
                setTimeout(() => {
                    if (selectedId) return; // لا نفعل شيء إذا تم الاختيار
                    
                    const value = e.target.value.trim();
                    if (!value) {
                        dropdown.style.display = 'none';
                        return;
                    }
                    
                    const results = this.searchEntities(value, type);
                    if (results.length > 0) {
                        const best = results[0];
                        // اطلب تأكيد من المستخدم أو اترك كما هو
                        // للآن: ملء الحقل بأفضل نتيجة عند الانتقال لحقل آخر
                        field.value = best.name;
                        field.dataset.entityId = best.id;
                        selectedId = best.id;
                        field.classList.add('is-valid');
                        try { field.dispatchEvent(new Event('input', { bubbles: true })); } catch (e) {}
                        if (typeof updateValidationIndicator === 'function') { try { updateValidationIndicator(); } catch (e) {} }
                        const matchLabel = best.matchType === 'code' ? `الرمز: ${best.code}` : 'الاسم';
                        this.showToast(`✅ تم المطابقة: ${best.name} (${matchLabel})`, 'success', 2000);
                        setTimeout(() => {
                            field.classList.remove('is-valid');
                            dropdown.style.display = 'none';
                        }, 1500);
                    } else {
                        dropdown.style.display = 'none';
                    }
                }, 50);
            });
            
            // 3️⃣ ON FOCUS: Show suggestions
            field.addEventListener('focus', () => {
                if (field.value.trim() && !selectedId) {
                    const results = this.searchEntities(field.value.trim(), type);
                    if (results.length > 0) {
                        this.displayEntitySuggestions(id, results, dropdown, field, type);
                    }
                }
            });
            
            // 4️⃣ ON CLICK OUTSIDE: Hide dropdown
            document.addEventListener('click', (e) => {
                if (e.target !== field && e.target !== dropdown && !dropdown.contains(e.target)) {
                    dropdown.style.display = 'none';
                }
            });
        });

        console.log('[ExtractionSmart] ✓ Advanced entity recognition system ready');
    }

    displayEntitySuggestions(fieldId, suggestions, dropdown, field, entityType) {
        // 🎨 عرض اقتراحات الجهات بشكل آمن (createElement + textContent — بلا XSS)
        if (!dropdown) return;

        // مسح المحتوى السابق
        dropdown.replaceChildren();

        suggestions.forEach((e) => {
            const typeLabel = e.etype === 'both' ? '📤📥' : e.etype === 'issuer' ? '📤' : '📥';
            const matchLabel = e.matchType === 'code' ? '🔍 رمز' : '📝 اسم';

            const item = document.createElement('div');
            item.className = 'entity-suggestion-item';
            item.dataset.id = e.id;
            item.dataset.name = e.name || '';
            item.style.cssText = 'padding:12px 15px;border-bottom:1px solid #e2e8f0;cursor:pointer;display:flex;justify-content:space-between;align-items:center;transition:all 0.2s;background:white;';
            item.addEventListener('mouseover', () => {
                item.style.background = '#f0f9ff';
                item.style.transform = 'translateX(4px)';
            });
            item.addEventListener('mouseout', () => {
                item.style.background = 'white';
                item.style.transform = 'translateX(0)';
            });

            const left = document.createElement('div');
            left.style.flex = '1';

            const nameDiv = document.createElement('div');
            nameDiv.style.cssText = 'font-weight:600;color:#1e293b;font-size:0.95rem;';
            nameDiv.textContent = e.name || '';
            left.appendChild(nameDiv);

            const metaRow = document.createElement('div');
            metaRow.style.cssText = 'font-size:0.8rem;color:#94a3b8;margin-top:4px;display:flex;gap:8px;flex-wrap:wrap;';

            if (e.code) {
                const codeBadge = document.createElement('span');
                codeBadge.style.cssText = 'background:#dbeafe;color:#0369a1;padding:3px 8px;border-radius:4px;font-weight:600;font-size:0.85rem;';
                codeBadge.textContent = e.code;
                metaRow.appendChild(codeBadge);
            }

            const typeBadge = document.createElement('span');
            typeBadge.style.cssText = 'background:#f1f5f9;color:#475569;padding:2px 8px;border-radius:4px;';
            typeBadge.textContent = typeLabel;
            metaRow.appendChild(typeBadge);

            const matchBadge = document.createElement('span');
            matchBadge.style.color = '#cbd5e1';
            matchBadge.textContent = matchLabel;
            metaRow.appendChild(matchBadge);

            left.appendChild(metaRow);
            item.appendChild(left);
            dropdown.appendChild(item);
        });

        dropdown.querySelectorAll('.entity-suggestion-item').forEach(item => {
            item.addEventListener('click', () => {
                const name = item.dataset.name;
                const id = item.dataset.id;

                field.value = name;
                field.dataset.entityId = id;
                field.classList.add('is-valid');
                try { field.dispatchEvent(new Event('input', { bubbles: true })); } catch (e) {}
                if (typeof updateValidationIndicator === 'function') { try { updateValidationIndicator(); } catch (e) {} }
                dropdown.style.display = 'none';

                this.showToast(`✅ تم اختيار: ${name}`, 'success', 1500);
                setTimeout(() => field.classList.remove('is-valid'), 1000);
            });
        });

        dropdown.style.display = 'block';
    }

    // ===== Due Date Auto-Calculation =====
    setupDueDateAutoCalculation() {
        const dateField = document.getElementById('date');
        const dueDateField = document.getElementById('dueDate');
        const followupCheckbox = document.getElementById('needsFollowup');
        const followupCard = document.getElementById('followupCard');
        const dueDateGroup = document.getElementById('dueDateGroup');
        
        if (!dateField || !dueDateField || !followupCheckbox) {
            console.warn('[ExtractionSmart] Due date fields not found');
            return;
        }

        const updateFollowupState = () => {
            const enabled = followupCheckbox.checked;

            if (followupCard) {
                followupCard.classList.toggle('active', enabled);
            }
            if (dueDateGroup) {
                dueDateGroup.classList.toggle('is-hidden', !enabled);
            }

            if (enabled && !dueDateField.value && dateField.value) {
                this.applySuggestedDueDate(dateField.value, dueDateField);
            }

            if (!enabled) {
                dueDateField.value = '';
            }
        };

        dateField.addEventListener('change', () => {
            if (followupCheckbox.checked && !dueDateField.value && dateField.value) {
                this.applySuggestedDueDate(dateField.value, dueDateField);
            }
        });

        followupCheckbox.addEventListener('change', updateFollowupState);
        updateFollowupState();

        console.log('[ExtractionSmart] ✓ Due date auto-calculation setup complete');
    }

    applySuggestedDueDate(dateValue, dueDateField) {
        try {
            const bookDate = new Date(dateValue);
            if (isNaN(bookDate)) return;

            bookDate.setDate(bookDate.getDate() + 7);
            dueDateField.value = bookDate.toISOString().slice(0, 10);

            console.log('[ExtractionSmart] ✓ Auto-calculated due_date:', dueDateField.value);
            this.showToast('تم اقتراح تاريخ متابعة تلقائياً (+7 أيام)', 'info', 3000);
        } catch (error) {
            console.error('[ExtractionSmart] Error calculating due_date:', error);
        }
    }

    applyInitialContext() {
        const container = document.querySelector('.extraction-container');
        const kindSelect = document.getElementById('bookKind');
        const secretLevelSelect = document.getElementById('secretLevel');

        const initialKind = (container && container.dataset.initialKind) ? container.dataset.initialKind : '';
        if (kindSelect) {
            const resolvedKind = initialKind || kindSelect.value || 'incoming_internal';
            this.syncKindUI(resolvedKind);
        }

        if (secretLevelSelect && !secretLevelSelect.value) {
            const defaultSecret = secretLevelSelect.dataset.default || 'normal';
            secretLevelSelect.value = defaultSecret;
        }

        // Set date defaults and lock bookDate
        this.resetDateFields();

        // Fetch numbers for all tabs
        this.fetchAllTabNumbers();
    }

    /** Set both date fields to today; lock bookDate (disabled), unlock senderDate */
    resetDateFields() {
        const todayISO = new Date().toISOString().split('T')[0];
        const dateField = document.getElementById('date');
        const senderDateField = document.getElementById('senderDate');
        const dateToggle = document.getElementById('dateEditToggle');

        if (dateField) {
            dateField.value = todayISO;
            dateField.disabled = true;
            dateField.tabIndex = -1;
        }
        if (senderDateField) {
            // **جذر تسميم التواريخ (وُجد 2026-08-19):** كان يُملأ بتاريخ اليوم تلقائيّاً،
            // والكاتب يتركه فيُحفَظ تاريخُ الإدخال باسم «تاريخ الجهة المرسلة» — وهو
            // بالضبط نمطُ القاعدة المقيس (336 من 344 تاريخاً يخالف حبر المستند والفارق
            // دائماً موجب = زمن الوصول). يبقى فارغاً: القصاصة أمام الكاتب ينسخ منها،
            // وفارغٌ يُصحَّح بنقرة، وافتراضيٌّ خاطئ يُسمّم ذهب التدريب صامتاً.
            senderDateField.value = '';
        }
        if (dateToggle) {
            dateToggle.checked = false;
        }
    }

    // ===== Suggestions System =====
    loadSuggestions() {
        ['issuing_entity', 'receiving_entity', 'secret_level'].forEach((key) => {
            this.fetchSuggestions(key);
        });
    }

    fetchSuggestions(categoryKey) {
        if (this.suggestionCache[categoryKey]) {
            return Promise.resolve(this.suggestionCache[categoryKey]);
        }

        return fetch(this.buildSuggestionsUrl(categoryKey), {
            headers: {
                'X-CSRFToken': this.getCookie('csrftoken')
            }
        })
            .then((response) => response.json())
            .then((result) => {
                const details = result.details || {};
                const items = details.items || result.items || [];
                this.suggestionCache[categoryKey] = items;
                if (details.fallback && !this.fallbackNotified) {
                    this.showToast(this.messages.fallbackSuggestions, 'warning', 6000);
                    this.fallbackNotified = true;
                }
                return this.suggestionCache[categoryKey];
            })
            .catch(() => {
                this.suggestionCache[categoryKey] = [];
                return [];
            });
    }

    showSuggestions(e) {
        const fieldId = e.target.id;
        const value = e.target.value.trim();
        const categoryKey = fieldId === 'issuingEntity' ? 'issuing_entity' : fieldId === 'receivingEntity' ? 'receiving_entity' : null;

        if (categoryKey && value.length > 0) {
            this.fetchSuggestions(categoryKey).then((items) => {
                const suggestions = (items || []).filter((s) => s.includes(value) && s !== value);
                if (suggestions.length > 0) {
                    this.displaySuggestions(fieldId, suggestions);
                }
            });
        }
    }

    hideSuggestions(e) {
        const fieldId = e.target.id;
        const suggestionsDiv = document.getElementById(`${fieldId}Suggestions`);
        if (suggestionsDiv) {
            suggestionsDiv.classList.remove('show');
        }
    }

    displaySuggestions(fieldId, suggestions) {
        const suggestionsDiv = document.getElementById(`${fieldId}Suggestions`);
        if (!suggestionsDiv) return;

        suggestionsDiv.innerHTML = suggestions.map(suggestion => `
            <div class="suggestion-item" data-field="${fieldId}" data-value="${suggestion}">
                ✓ ${suggestion}
            </div>
        `).join('');

        // Bind click events using delegation
        suggestionsDiv.querySelectorAll('.suggestion-item').forEach(item => {
            item.addEventListener('click', () => {
                this.applySuggestion(item.dataset.field, item.dataset.value);
            });
        });

        suggestionsDiv.classList.add('show');
    }

    applySuggestion(fieldId, value) {
        document.getElementById(fieldId).value = value;
        document.getElementById(`${fieldId}Suggestions`).classList.remove('show');
        this.validateField(fieldId);
    }

    updateSuggestions(fieldId, value) {
        // Placeholder: could call backend for live AI suggestions
    }

    // ===== Form Management =====
    clearForm() {
        console.log('[ExtractionSmart] clearForm() called');

        // Manual clear: void the active reservation for the current kind on the server.
        const kindSelect = document.getElementById('bookKind');
        const currentKind = (kindSelect && kindSelect.value) || 'incoming_internal';
        const voidPromise = this.voidReservation(currentKind, 'manual_clear');

        const fields = document.querySelectorAll('.form-control-smart');
        console.log('[ExtractionSmart] Found', fields.length, 'form fields');

        this.beginTextUndoBatch?.();   // كي يستطيع Ctrl+Z استرجاع الحقول النصية بعد التفريغ (يشمل مسح Escape)
        fields.forEach(field => {
            if (field.id !== 'date' && field.id !== 'senderDate') {
                field.value = '';
            }
            field.classList.remove('has-error', 'is-valid');
            if (field.id === 'bookNumber') {
                delete field.dataset.reservationId;
            }
        });
        this.endTextUndoBatch?.();

        // امسح وسوم الجهات: مكوّن EntityTagInput مخصّص (ليست .form-control-smart) فلا تطالها الحلقة أعلاه.
        window.entityTagManagers?.issuing?.clear();
        window.entityTagManagers?.receiving?.clear();

        // صفّر «بلا رقم» كي لا يعلق مؤشَّراً بعد التفريغ (عبر معالج القالب الواحد).
        const _nlCbClear = document.getElementById('numberlessCheckbox');
        if (_nlCbClear && _nlCbClear.checked) { _nlCbClear.checked = false; _nlCbClear.dispatchEvent(new Event('change', { bubbles: true })); }

        const badges = document.querySelectorAll('.confidence-badge');
        console.log('[ExtractionSmart] Found', badges.length, 'confidence badges');
        badges.forEach(badge => {
            badge.style.display = 'none';
        });

        this.documentTypeSelectionByKind = {};

        const followupCheckbox = document.getElementById('needsFollowup');
        if (followupCheckbox) {
            followupCheckbox.checked = false;
            followupCheckbox.dispatchEvent(new Event('change'));
        }

        // After void completes, reset context and reserve fresh numbers.
        Promise.resolve(voidPromise).finally(() => {
            this.applyInitialContext();
        });

        this.showToast('تم مسح النموذج', 'success');
        console.log('[ExtractionSmart] ✓ Form cleared');
    }

    smartClearAndStay(kind) {
        console.log('[ExtractionSmart] smartClearAndStay:', kind);
        const fields = document.querySelectorAll('.form-control-smart');
        fields.forEach(field => {
            // Keep kind select and date fields (dates reset separately)
            if (field.id === 'bookKind' || field.id === 'date' || field.id === 'senderDate') return;
            // Clear bookNumber too — ensureReservation() will paint the next reserved value.
            field.value = '';
            field.classList.remove('has-error', 'is-valid');
            if (field.id === 'bookNumber') {
                delete field.dataset.reservationId;
            }
        });

        // امسح وسوم الجهات (مكوّن مخصّص خارج .form-control-smart) — «تفريغ» يشمل الجهات.
        window.entityTagManagers?.issuing?.clear();
        window.entityTagManagers?.receiving?.clear();

        // صفّر «بلا رقم» كي لا يعلق مؤشَّراً للكتاب التالي (عبر معالج القالب الواحد → يُعيد الحجز).
        const _nlCb = document.getElementById('numberlessCheckbox');
        if (_nlCb && _nlCb.checked) { _nlCb.checked = false; _nlCb.dispatchEvent(new Event('change', { bubbles: true })); }

        const badges = document.querySelectorAll('.confidence-badge');
        badges.forEach(badge => { badge.style.display = 'none'; });

        // أخفِ ملخّص الجودة وبطاقة «تحتاج مراجعة» — كانا يبقيان فوق نموذج فارغ بعد الحفظ (تسريب حالة)
        const qualityHero = document.getElementById('qualityHero');
        if (qualityHero) qualityHero.style.display = 'none';
        const needsReviewCard = document.getElementById('needsReviewCard');
        if (needsReviewCard) needsReviewCard.style.display = 'none';

        const followupCheckbox = document.getElementById('needsFollowup');
        if (followupCheckbox) {
            followupCheckbox.checked = false;
            followupCheckbox.dispatchEvent(new Event('change'));
        }

        const secretLevelSelect = document.getElementById('secretLevel');
        if (secretLevelSelect) {
            secretLevelSelect.value = secretLevelSelect.dataset.default || 'normal';
        }

        delete this.documentTypeSelectionByKind[kind];

        // Stay on the same tab and refresh the number
        this.syncKindUI(kind);
        this.fetchAllTabNumbers();

        // Reset dates to today and lock bookDate
        this.resetDateFields();

        if (typeof updateValidationIndicator === 'function') updateValidationIndicator();

        // إعادة ضبط أساس تتبّع «تغييرات غير محفوظة» بعد التفريغ (حارس زر الإلغاء/beforeunload)
        if (window.__setExtractionBaseline) window.__setExtractionBaseline();
    }

    // ===== Save Book =====
    // مسار حفظ موحّد لوضعَي الإدخال والتعديل (كان وضع التعديل monkey-patch مكرَّراً في القالب).
    // كشف الوضع بمصدر واحد: this._editData (يُقرأ من وسم editBookData عند الإنشاء).
    async saveBook() {
        const isEdit = !!this._editData;
        const kindValue = this.getCurrentKind();

        // ── 1) التحقّق من الحقول المطلوبة (حسب الوضع) ──
        // "بلا رقم": استثناء للكتب الداخلية فقط (وضع الإدخال فقط)
        const numberlessChecked = !isEdit
            && !!document.getElementById('numberlessCheckbox')?.checked
            && (kindValue === 'incoming_internal' || kindValue === 'outgoing_internal');

        // في التعديل الرقم ثابت فلا يُتحقَّق منه؛ في الإدخال نتخطّاه عند "بلا رقم".
        const requiredFields = (isEdit || numberlessChecked)
            ? ['title', 'date', 'issuingEntity', 'receivingEntity']
            : ['bookNumber', 'title', 'date', 'issuingEntity', 'receivingEntity'];
        let isValid = true;
        let firstInvalid = null;
        requiredFields.forEach(fieldId => {
            if (!this.validateField(fieldId)) {
                isValid = false;
                if (!firstInvalid) firstInvalid = document.getElementById(fieldId);
            }
        });
        if (!isValid) {
            this.showToast(this.t('invalidFields'), 'error', 6000);
            if (firstInvalid) { firstInvalid.focus(); firstInvalid.classList.add('has-error'); }
            return;
        }

        // ── 2) نوع المستند مطلوب في الإدخال فقط (التعديل لا يشترطه) ──
        const documentTypeValue = this.getResolvedDocumentTypeValue(kindValue);
        if (!isEdit && !documentTypeValue) {
            this.showToast('يرجى اختيار نوع المستند أو إدخال نوع جديد.', 'error', 6000);
            if (this.isCustomDocumentTypeSelected()) {
                const customInput = document.getElementById('documentTypeCustom');
                if (customInput) { customInput.focus(); customInput.classList.add('has-error'); }
            } else {
                document.getElementById('documentTypeSelect')?.focus();
            }
            return;
        }

        // تأكيد الحفظ بلا ملف — وضع الإدخال فقط (التعديل يُرسل الملف حصراً عند تعديل الصفحات)
        if (!isEdit && !this.hasAttachedFile()) {
            const proceedWithoutFile = await this.confirmSaveWithoutFile();
            if (!proceedWithoutFile) return;
        }

        // ── 3) تفريغ نصّ الجهة المُدخَل إلى وسم إن لم يُحوَّل (كلا الوضعين) ──
        await this._flushPendingEntities();

        // ── 4) بناء الحمولة المشتركة ──
        const formData = new FormData();
        const senderNumber = document.getElementById('senderNumber')?.value || '';
        const senderDate = document.getElementById('senderDate')?.value || '';
        formData.append('title', document.getElementById('title').value);
        formData.append('date', document.getElementById('date').value);
        formData.append('sender_number', senderNumber);
        formData.append('sender_date', senderDate);
        formData.append('secret_level', document.getElementById('secretLevel')?.value || 'normal');
        formData.append('document_type', documentTypeValue || '');
        formData.append('margin', document.getElementById('margin')?.value || '');
        // الجهات كوسوم (معرّفات + أسماء جديدة) — مصدر موحّد لكلا الوضعين
        this._appendEntityIds(formData);

        // ── 5) وضع التعديل: حمولة خاصّة + إرسال إلى update-book-api ──
        if (isEdit) {
            formData.append('edit_pk', String(this._editData.pk));
            const dueDateValue = document.getElementById('dueDate')?.value || '';
            formData.append('due_date', dueDateValue);
            formData.append('needs_followup', dueDateValue ? 'true' : 'false');
            // المرفق يُرسَل حصراً إن عُدّلت صفحات المعاينة فعلاً (تفادي الاستبدال الصامت)،
            // ويُستهدَف المرفق المُعدَّل وحده كي لا تُؤرشف بقية مرفقات الكتاب.
            if (this._pagesEditedInPreview && this.currentFile) {
                formData.append('file', this.currentFile);
                if (this._editData.attachment && this._editData.attachment.id) {
                    formData.append('attachment_id', String(this._editData.attachment.id));
                }
            }
            return this._submitEdit(formData);
        }

        // ── 6) وضع الإدخال: حقول الترقيم/الحجز + إرسال إلى save-book-api ──
        const bookNumber = document.getElementById('bookNumber').value;

        // سجلّ بلا سلسلة: النظام لا يملك رقماً يمنحه، فالرقم إلزاميّ من الموظّف.
        if (!numberlessChecked && this.getKindConfig(kindValue).manualNumber && !bookNumber.trim()) {
            this.showToast('أدخل رقم صادر مكتب السيد المدير العام — هذا السجلّ لا يولّد رقماً تلقائياً.',
                           'error', 6000);
            const el = document.getElementById('bookNumber');
            if (el) { el.focus(); el.classList.add('has-error'); }
            return;
        }
        const dueDate = document.getElementById('dueDate').value;
        const needsFollowup = document.getElementById('needsFollowup')?.checked;
        // Keep both keys during the extraction transition layer.
        formData.append('our_number', bookNumber);
        formData.append('book_number', bookNumber);
        formData.append('outgoing_incoming_number', senderNumber);
        formData.append('due_date', dueDate);
        formData.append('dueDate', dueDate);
        formData.append('needs_followup', needsFollowup ? 'true' : 'false');
        formData.append('book_type_name', documentTypeValue);
        formData.append('kind', kindValue);
        if (this.scanToken) formData.append('scan_token', this.scanToken);  // حلقة التقاط التدريب

        if (numberlessChecked) {
            // كتاب داخلي بلا رقم — يتجاهل الحجز والترقيم التلقائي
            formData.set('numberless', '1');
            formData.delete('reservation_id');
            formData.delete('auto_number');
            formData.set('our_number', '');
            formData.set('book_number', '');
        } else if (this.getKindConfig(kindValue).manualNumber) {
            // سجلّ بلا سلسلة: الرقم من الورق حرفياً — لا حجز ولا توليد تلقائي.
            // بدون هذا كان الخادم يخترع رقماً من عدّادٍ لا يخصّ هذا السجلّ.
            formData.delete('reservation_id');
            formData.append('auto_number', 'false');
        } else {
            // Prefer the active reservation; fall back to auto_number generation server-side.
            const activeReservation = this.reservations[kindValue];
            if (activeReservation && activeReservation.id) {
                formData.append('reservation_id', activeReservation.id);
            } else {
                formData.append('auto_number', this.autoNumberEnabled ? 'true' : 'false');
            }
        }

        if (this.currentFile) formData.append('file', this.currentFile);

        this.submitBookData(formData);
    }

    /** يحلّ أي نصّ جهة مُدخَل لم يُحوَّل لوسم بعد (قبل قراءة المعرّفات) — يمنع فقدان جهة جديدة. */
    async _flushPendingEntities() {
        const jobs = ['issuing', 'receiving'].map(k => {
            const mgr = window.entityTagManagers?.[k];
            if (mgr && mgr.input && mgr.input.value.trim()) {
                return Promise.resolve(mgr._resolveOrCreate(mgr.input.value.trim(), true));
            }
            return Promise.resolve();
        });
        try { await Promise.all(jobs); } catch (e) { console.warn('Pending entity flush failed:', e); }
    }

    /** يُلحق معرّفات/أسماء الجهات (وسوم EntityTagInput) بالحمولة — مصدر موحّد. */
    _appendEntityIds(formData) {
        const mgrI = window.entityTagManagers?.issuing;
        const mgrR = window.entityTagManagers?.receiving;
        (mgrI?.getIds()   || []).forEach(id => formData.append('issuing_entity_ids[]',   id));
        (mgrI?.getNames() || []).forEach(n  => formData.append('issuing_entity_new[]',   n));
        (mgrR?.getIds()   || []).forEach(id => formData.append('receiving_entity_ids[]', id));
        (mgrR?.getNames() || []).forEach(n  => formData.append('receiving_entity_new[]', n));
    }

    // ════════════════════════════════════════════════════════════════
    //  إرسال الكتاب إلى الجهة المعنيّة (مع مرفقاته)
    //  لا يخرج مستند رسمي دون أن يرى المستخدم الجهة والبريد وما سيُرفَق.
    // ════════════════════════════════════════════════════════════════

    _escapeHtml(s) {
        const d = document.createElement('div');
        d.textContent = String(s ?? '');
        return d.innerHTML;
    }

    async openSendToEntity(bookId) {
        const modalEl = document.getElementById('sendToEntityModal');
        const body    = document.getElementById('sendToEntityBody');
        const confirm = document.getElementById('sendToEntityConfirm');
        if (!modalEl || !body || !confirm) return;

        const modal = bootstrap.Modal.getOrCreateInstance(modalEl);
        body.innerHTML = '<div class="text-center text-muted py-4">'
                       + '<div class="spinner-border spinner-border-sm ms-2"></div> جارٍ تحضير المعاينة…</div>';
        confirm.disabled = true;
        modal.show();

        let preview;
        try {
            const resp = await fetch(`/books/api/email/book/${bookId}/preview/`, {
                credentials: 'same-origin',
                headers: { 'X-Requested-With': 'XMLHttpRequest' },
            });
            preview = await resp.json();
            if (!resp.ok || !preview.success) throw new Error(preview.message || 'تعذّرت المعاينة');
        } catch (e) {
            body.innerHTML = `<div class="alert alert-danger mb-0">تعذّر تحضير المعاينة: ${this._escapeHtml(e.message)}</div>`;
            return;
        }

        body.innerHTML = this._renderSendPreview(preview);

        // لا نُفعّل الإرسال إلا إذا كان ممكناً فعلاً — لا زرّ يَعِد بما لا يقدر عليه.
        const blocked = !preview.email_enabled || !preview.entity;
        confirm.disabled = blocked;
        confirm.onclick = blocked ? null : () => this._doSendToEntity(bookId, modal, confirm);
    }

    _renderSendPreview(p) {
        if (!p.email_enabled) {
            return '<div class="alert alert-warning mb-0">'
                 + '<strong>إرسال البريد معطّل.</strong> فعّله من: الإعدادات ← البريد الإلكتروني ← «تفعيل إرسال البريد».'
                 + '</div>';
        }
        if (!p.entity) {
            return `<div class="alert alert-warning mb-0"><strong>لا يمكن الإرسال.</strong> ${this._escapeHtml(p.entity_error || 'لا توجد جهة معنيّة.')}</div>`;
        }

        const cc = (p.entity.cc || []).length
            ? `<div class="text-muted small">نسخة إلى: ${this._escapeHtml(p.entity.cc.join('، '))}</div>` : '';

        const attach = p.files.filter(f => f.mode === 'attach');
        const linked = p.files.filter(f => f.mode === 'link');
        const failed = p.files.filter(f => f.mode === 'failed');

        const row = (f, icon, note) => `
            <li class="d-flex align-items-center gap-2 py-1">
              <i class="bi ${icon}"></i>
              <span class="flex-grow-1 text-truncate">${this._escapeHtml(f.name)}</span>
              <span class="text-muted small">${this._escapeHtml(f.size_label)}</span>
              ${note ? `<span class="badge bg-light text-dark">${note}</span>` : ''}
            </li>`;

        let files = '';
        if (!p.files.length) {
            files = '<div class="text-muted small">لا مرفقات على هذا الكتاب — ستُرسل الرسالة نصّاً فقط.</div>';
        } else {
            files = '<ul class="list-unstyled mb-0" style="max-height:190px;overflow:auto">'
                  + attach.map(f => row(f, 'bi-paperclip', '')).join('')
                  + linked.map(f => row(f, 'bi-link-45deg', 'رابط')).join('')
                  + failed.map(f => row(f, 'bi-exclamation-triangle text-danger', 'تعذّر')).join('')
                  + '</ul>';
        }

        const linkNote = linked.length
            ? `<div class="alert alert-info py-2 px-3 mt-2 mb-0" style="font-size:.82rem">
                 ${linked.length} ملف يتجاوز حدّ البريد (${this._escapeHtml(p.limit_label)}) — سيُرسَل
                 <strong>رابط تحميل موقّع</strong> بدل إرفاقه. الرابط ينتهي بعد 7 أيام.
               </div>` : '';

        return `
          <div class="mb-3">
            <div class="text-muted small">إلى</div>
            <div class="fw-bold">${this._escapeHtml(p.entity.name)}</div>
            <div dir="ltr" class="text-muted" style="font-size:.85rem">${this._escapeHtml(p.entity.email)}</div>
            ${cc}
          </div>
          <div class="mb-3">
            <div class="text-muted small">الموضوع</div>
            <div>${this._escapeHtml(p.subject)}</div>
          </div>
          <div>
            <div class="text-muted small mb-1">المرفقات (${p.files.length}) — سيُرفَق ${this._escapeHtml(p.attach_label)}</div>
            ${files}
            ${linkNote}
          </div>`;
    }

    async _doSendToEntity(bookId, modal, confirmBtn) {
        const original = confirmBtn.innerHTML;
        confirmBtn.disabled = true;
        confirmBtn.innerHTML = '<span class="spinner-border spinner-border-sm ms-1"></span> جارٍ الإرسال…';
        try {
            const resp = await fetch(`/books/api/email/book/${bookId}/send/`, {
                method: 'POST',
                headers: {
                    'X-CSRFToken': this.getCookie('csrftoken'),
                    'Content-Type': 'application/json',
                    'X-Requested-With': 'XMLHttpRequest',
                },
                credentials: 'same-origin',
                body: '{}',
            });
            const data = await resp.json();
            if (data.success) {
                // تقرير صادق: ما أُرفِق فعلاً وما أُحيل إلى رابط
                const bits = [data.message];
                if (data.attached?.length) bits.push(`أُرفِق ${data.attached.length} ملف (${data.attached_label})`);
                if (data.linked?.length)   bits.push(`${data.linked.length} ملف أُرسل كرابط`);
                if (data.failed?.length)   bits.push(`${data.failed.length} ملف تعذّر`);
                this.showToast(bits.join(' — '), 'success', 7000);
                modal.hide();
            } else {
                this.showToast(data.message || 'فشل الإرسال', 'error', 8000);
                confirmBtn.disabled = false;
                confirmBtn.innerHTML = original;
            }
        } catch (e) {
            this.showToast('خطأ في الاتصال — لم تُرسَل الرسالة', 'error', 6000);
            confirmBtn.disabled = false;
            confirmBtn.innerHTML = original;
        }
    }

    /** إرسال تعديل كتاب قائم إلى update-book-api ثم العودة لوجهة البدء.
     *  لا كشف تكرار هنا: الكتاب محفوظ مسبقاً — التنبيه للإدخال الأوّل فقط. */
    async _submitEdit(formData) {
        const saveBtn = document.getElementById('saveButton');
        const originalText = saveBtn.innerHTML;
        saveBtn.innerHTML = '<span class="spinner"></span> جاري الحفظ...';
        saveBtn.disabled = true;
        try {
            const resp = await fetch(this.apiEndpoints.updateBook, {
                method: 'POST',
                headers: { 'X-CSRFToken': this.getCookie('csrftoken'), 'X-Requested-With': 'XMLHttpRequest' },
                credentials: 'same-origin',
                body: formData,
            });
            const result = await resp.json();
            if (result.success) {
                this._pagesEditedInPreview = false;   // استُهلكت تعديلات الصفحات بالحفظ
                if (window.__setExtractionBaseline) window.__setExtractionBaseline();  // لا يعترض beforeunload التوجيه
                this.showToast('تم حفظ التعديلات بنجاح ✓', 'success', 3000);
                // «حفظ وإرسال» في وضع التعديل: نفتح الحوار ولا نغادر الصفحة —
                // المغادرة أثناء الإرسال تقطع العملية على المستخدم.
                if (this.sendToEntityAfterSave && result.book_id) {
                    this.sendToEntityAfterSave = false;
                    saveBtn.innerHTML = originalText;
                    saveBtn.disabled = false;
                    this.openSendToEntity(result.book_id);
                    return;
                }
                setTimeout(() => { window.location.href = this.backUrl || result.redirect_url || '/'; }, 1200);
                return;
            }
            this.showToast(result.message || 'فشل الحفظ', 'error', 6000);
        } catch (e) {
            this.showToast('خطأ في الاتصال — حاول مجدداً', 'error', 5000);
        }
        saveBtn.innerHTML = originalText;
        saveBtn.disabled = false;
    }

    async submitBookData(formData) {
        const saveBtn = document.getElementById('saveButton');
        const originalText = saveBtn.innerHTML;
        let savedKind = formData.get('kind') || 'incoming_internal';
        saveBtn.innerHTML = '<span class="spinner"></span> جاري الحفظ...';
        saveBtn.disabled = true;

        let retriedAfterReservationRefresh = false;
        let confirmedDuplicate = false;

        try {
            while (true) {
                savedKind = formData.get('kind') || 'incoming_internal';
                const response = await fetch(this.apiEndpoints.saveBook, {
                    method: 'POST',
                    headers: {
                        'X-CSRFToken': this.getCookie('csrftoken')
                    },
                    body: formData
                });

                const data = await response.json();
                const status = response.status;

                if (status >= 200 && status < 300 && data.success !== false) {
                    if (data.request_id) {
                        console.info('save request_id:', data.request_id);
                    }
                    const savedDocumentType = String(formData.get('document_type') || '').trim();
                    if (savedDocumentType) {
                        this.addCustomDocumentType(savedKind, savedDocumentType);
                    }
                    const successMessage = retriedAfterReservationRefresh
                        ? `تم تجديد رقم القيد تلقائياً ثم حفظ الكتاب بنجاح (${formData.get('book_number') || ''}).`
                        : this.t('saveSuccess');
                    this.showToast(successMessage, 'success', retriedAfterReservationRefresh ? 6500 : 4000);
                    delete this.reservations[savedKind];
                    this.smartClearAndStay(savedKind);
                    this.clearFile();
                    this.ensureReservation(savedKind);
                    // «حفظ وإرسال»: النموذج يُمسح بعد الحفظ، لذا نلتقط معرّف الكتاب
                    // من الاستجابة ونفتح حوار الإرسال عليه.
                    if (this.sendToEntityAfterSave && data.book_id) {
                        this.sendToEntityAfterSave = false;
                        this.openSendToEntity(data.book_id);
                    }
                    break;
                }

                if (!retriedAfterReservationRefresh && this.isRecoverableReservationError(data)) {
                    const replacementReservation = await this.recoverReservationForRetry(savedKind, data.message);
                    if (replacementReservation?.id) {
                        retriedAfterReservationRefresh = true;
                        this.updateFormDataReservation(formData, replacementReservation);
                        continue;
                    }
                }

                // كشف التكرار: 3/4 (SIMILAR) أو 4/4 (DUPLICATE) — نستأذن مرّة ثم نُعيد بعلَم التأكيد
                if (!confirmedDuplicate &&
                    (data.error_code === 'SIMILAR_BOOK' || data.error_code === 'DUPLICATE_BOOK')) {
                    const proceed = await this._confirmDuplicate(data);
                    if (proceed) {
                        confirmedDuplicate = true;
                        formData.set('confirm_duplicate', 'true');
                        continue;
                    }
                    break;   // ألغى المستخدم
                }

                const msg = data.message || this.t('saveFail');
                const debugSuffix = data.debug_error ? ` — ${data.debug_error}` : '';
                if (data.error_code === 'FILE_TYPE') {
                    this.showToast(this.t('fileType'), 'error', 6000);
                } else if (data.error_code === 'FILE_SIZE') {
                    this.showToast(this.t('fileSize'), 'error', 6000);
                } else if (data.error_code === 'RESERVATION_ALREADY_USED') {
                    this.showToast(msg, 'error', 7000);
                } else if (data.error_code === 'SERVER_ERROR') {
                    // الحجز يبقى نشطاً عند خطأ الخادم — نُبيّن للمستخدم أن إعادة المحاولة بنفس الرقم آمنة.
                    this.showToast(`${msg}. الرقم المحجوز محفوظ ويمكنك إعادة المحاولة بأمان${debugSuffix}.`, 'error', 9000);
                } else {
                    this.showToast(msg + debugSuffix, 'error', 6000);
                }
                break;
            }
        } catch (error) {
            this.showToast(this.t('saveFail'), 'error', 6000);
            console.error('Error:', error);
        } finally {
            saveBtn.innerHTML = originalText;
            saveBtn.disabled = false;
        }
    }

    // ===== Utilities =====
    showToast(message, type = 'info', duration = 4000, title = null) {
        // Delegate to global ToastCenter for consistent UX
        if (window.ToastCenter) {
            const opts = { delay: duration };
            if (title) opts.title = title;
            window.ToastCenter.show(type, message, opts);
        } else {
            // Fallback to alert if ToastCenter not available
            alert((title ? title + ': ' : '') + message);
        }
    }

    /** fetch مع مهلة (AbortController) لاكتشاف عدم استجابة الوكيل/الماسح. */
    async _fetchWithTimeout(url, opts = {}, timeoutMs = 8000) {
        const ctrl = new AbortController();
        const id = setTimeout(() => ctrl.abort(), timeoutMs);
        try {
            return await fetch(url, { ...opts, signal: ctrl.signal });
        } finally {
            clearTimeout(id);
        }
    }

    getCookie(name) {
        let cookieValue = null;
        if (document.cookie && document.cookie !== '') {
            const cookies = document.cookie.split(';');
            for (let i = 0; i < cookies.length; i++) {
                const cookie = cookies[i].trim();
                if (cookie.substring(0, name.length + 1) === (name + '=')) {
                    cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                    break;
                }
            }
        }
        return cookieValue;
    }
}

// Initialize system after DOM is ready and expose globally
function initExtractionSystem() {
    try {
        console.log('[ExtractionSmart] Initializing system...');
        window.extractionSystem = new ExtractionSmartSystem();
        console.log('[ExtractionSmart] ✓ System initialized successfully');
        return true;
    } catch (err) {
        console.error('[ExtractionSmart] ✗ Failed to initialize:', err);
        if (window.ToastCenter) {
            window.ToastCenter.show('error', 'فشل تهيئة نظام الاستخراج. يرجى تحديث الصفحة.', {
                title: 'تعذر تشغيل الواجهة',
                delay: 7000,
            });
        } else {
            alert('فشل تهيئة نظام الاستخراج. يرجى تحديث الصفحة.');
        }
        return false;
    }
}

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initExtractionSystem);
} else {
    // DOM already loaded
    initExtractionSystem();
}
