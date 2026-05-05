/**
 * ============================================
 * Extraction Smart Desktop JavaScript - Enhanced
 * نظام الاستخراج الذكي المحسّن
 * ============================================
 */

class ExtractionSmartSystem {
    constructor() {
        this.currentFile = null;
        this.scannedFiles = [];   // مصفوفة الصفحات الممسوحة (للدمج مع "مسح المزيد")
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
            scanCapture: dataset.scanCaptureEndpoint || '/books/api/scan-capture/',
            smartExtract: dataset.smartExtractEndpoint || '/books/api/extract/smart/',
            entityList: dataset.entityListEndpoint || '/books/api/entity-list/',
            suggestions: dataset.suggestionsEndpoint || '/books/api/suggestions/',
            saveBook: dataset.saveBookEndpoint || '/books/api/book/save/',
            nextNumber: dataset.nextNumberEndpoint || '/books/api/next-number/',
            reservationReserve: dataset.reservationReserveEndpoint || '/books/api/reservation/reserve/',
            reservationVoid: dataset.reservationVoidEndpoint || '/books/api/reservation/void/',
            reservationStatus: dataset.reservationStatusEndpoint || '/books/api/reservation/status/'
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
        this.loadSuggestions();
        this.loadEntityData();
        this.setupEntityCodeRecognition();
        this.setupKindControls();
        this.setupDueDateAutoCalculation();
        this.applyInitialContext();
        this.enhanceUIFeedback();
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
                senderNumberLabel: 'رقم الجهة المرسلة',
                senderNumberHint: 'رقم المرجع لدى القسم أو الوحدة التي أصدرت الكتاب.',
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
                senderNumberLabel: 'رقم الكتاب لدى الجهة الخارجية',
                senderNumberHint: 'انسخ رقم الجهة كما يظهر في المستند أو الختم.',
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
                bookNumberLabel: 'رقم الصادر الخارجي',
                bookNumberHint: 'رقم الخطاب أو الصادر الرسمي المعتمد عند الإرسال للخارج.',
                bookNumberPlaceholder: 'مثال: ص/خ/57',
                senderNumberLabel: 'رقم الجهة المرسلة',
                senderNumberHint: '',
                dateLabel: 'تاريخ الإرسال',
                dateHint: 'تاريخ إصدار وإرسال الكتاب إلى الجهة الخارجية.',
                senderDateLabel: 'تاريخ الجهة المرسلة',
                senderDateHint: '',
                propertiesCopy: 'الصادر الخارجي لا يحتاج رقم جهة مرسلة، لكنه يحتاج صياغة متابعة واضحة إذا كان هناك رد منتظر.',
                showSenderFields: false,
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

    ensureReservation(kind) {
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
        // Update the tab badge for this kind
        const badge = document.getElementById(`tabNum_${kind}`);
        if (badge) badge.textContent = reservation.number || reservation.formatted || '—';
        // If this is the currently active kind, fill the bookNumber field
        const kindSelect = document.getElementById('bookKind');
        if (kindSelect && kindSelect.value === kind) {
            const bookNumberField = document.getElementById('bookNumber');
            if (bookNumberField) {
                bookNumberField.value = reservation.formatted || '';
                bookNumberField.dataset.reservationId = reservation.id;
                bookNumberField.classList.remove('has-error', 'is-pending');
                bookNumberField.classList.add('is-valid');
                if (typeof updateValidationIndicator === 'function') updateValidationIndicator();
            }
        }
        // 🕓 ابدأ/جدّد العدّاد التنازلي لانتهاء الصلاحية
        this._ensureReservationCountdown();
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
            if (!anyActive) {
                clearInterval(this._reservationTimerId);
                this._reservationTimerId = null;
            }
        };
        tick();
        this._reservationTimerId = setInterval(tick, 20000);
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
                console.log('[ExtractionSmart] Calling clearFile() from:', btnId);
                this.clearFile();
                // مسح النموذج أيضاً عند مسح الملف
                this.clearForm();            } else if (btnId === 'extractButton') {
                e.preventDefault();
                console.log('[ExtractionSmart] Calling extractData()');
                this.extractData();
            } else if (btnId === 'saveButton') {
                e.preventDefault();
                console.log('[ExtractionSmart] Calling saveBook()');
                this.saveBook();
            } else if (btnId === 'startScanButton') {
                e.preventDefault();
                console.log('[ExtractionSmart] Calling startScan()');
                this.startScan({ append: false });
            } else if (btnId === 'scanMoreButton') {
                e.preventDefault();
                console.log('[ExtractionSmart] Calling startScan({append:true})');
                this.startScan({ append: true });
            } else if (btnId === 'clearScannedButton') {
                e.preventDefault();
                console.log('[ExtractionSmart] Calling clearScannedFile()');
                this.clearScannedFile();
            } else if (btnId === 'uploadFileButton') {
                e.preventDefault();
                console.log('[ExtractionSmart] Triggering file picker');
                const fi = document.getElementById('fileInput');
                if (fi) fi.click();
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
            'scanMoreButton',
            'clearScannedButton',
            'extractButton',
            'saveButton'
        ];
    }

    isActionButtonField(fieldId) {
        return ['uploadFileButton', 'startScanButton', 'scanMoreButton', 'clearScannedButton', 'extractButton', 'saveButton'].includes(fieldId);
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

    // ===== مسح ضوئي من السكانر - محسّن ومتقدم =====
    startScan(options = {}) {
        const append = !!options.append;
        console.log('[ExtractionSmart] 🚀 startScan() called', { append });
        // احفظ النية الحالية حتى يستخدمها callback النجاح
        this._scanAppendMode = append;

        // إن طُلب الإلحاق ولم يكن هناك ملف سابق، أضِف الملف الحالي (إن وُجد) إلى المصفوفة
        if (append && this.scannedFiles.length === 0 && this.currentFile && (this.currentFile.type || '').startsWith('image/')) {
            this.scannedFiles = [this.currentFile];
        }

        const scanProgress = document.getElementById('scanProgress');
        const startScanButton = document.getElementById('startScanButton');
        const scanMoreButton = document.getElementById('scanMoreButton');
        const clearScannedButton = document.getElementById('clearScannedButton');

        if (!scanProgress || !startScanButton) {
            console.error('[ExtractionSmart] ❌ Scan UI elements not found');
            return;
        }
        
        // Create AbortController for cancellation
        this.scanAbortController = new AbortController();
        
        // Save original button content
        const originalButtonContent = startScanButton.innerHTML;
        
        // إظهار حالة المسح مع زر إلغاء
        scanProgress.style.display = 'flex';
        startScanButton.disabled = true;
        startScanButton.style.position = 'relative';
        if (scanMoreButton) scanMoreButton.disabled = true;
        if (clearScannedButton) clearScannedButton.disabled = true;
        
        // إنشاء زر إلغاء
        const cancelBtn = document.createElement('button');
        cancelBtn.className = 'btn btn-sm btn-outline-danger';
        cancelBtn.innerHTML = '<i class="bi bi-x-circle"></i> إلغاء';
        cancelBtn.style.cssText = 'margin-right: 10px;';
        cancelBtn.onclick = (e) => {
            e.stopPropagation();
            this.cancelScan(startScanButton, originalButtonContent, scanProgress);
        };
        
        // إضافة زر الإلغاء بجانب progress
        const progressParent = scanProgress.parentElement;
        if (progressParent) {
            progressParent.appendChild(cancelBtn);
            this.scanCancelButton = cancelBtn;
        }
        
        console.log('[ExtractionSmart] ✅ Scan progress indicator shown with cancel button');
        
        // رسائل التقدم
        const progressMessages = [
            { ar: '🚀 جارٍ تشغيل الماسح الضوئي...', time: 0 },
            { ar: '📄 يرجى وضع المستند في الماسح', time: 3000 },
            { ar: '👆 انقر زر المسح في برنامج Canon', time: 6000 },
            { ar: '⏳ جارٍ انتظار الملف الممسوح...', time: 12000 },
            { ar: '⏱️ لا تزال العملية جارية...', time: 30000 },
            { ar: '🕐 يرجى الانتظار قليلاً...', time: 50000 }
        ];
        
        let currentMessageIndex = 0;
        const startTime = Date.now();
        const progressText = scanProgress.querySelector('.progress-message') || scanProgress;
        
        const updateProgressMessage = () => {
            const elapsed = Date.now() - startTime;
            const nextMessage = progressMessages.find((msg, idx) => 
                idx > currentMessageIndex && msg.time <= elapsed
            );
            
            if (nextMessage) {
                currentMessageIndex = progressMessages.indexOf(nextMessage);
                const elapsedSec = Math.floor(elapsed / 1000);
                progressText.textContent = `${nextMessage.ar} (${elapsedSec}s)`;
                console.log(`[ExtractionSmart] 📝 Progress: ${nextMessage.ar}`);
            }
        };
        
        // تحديث الرسالة الأولية
        progressText.textContent = progressMessages[0].ar;
        
        // تحديث دوري للرسائل
        const progressInterval = setInterval(updateProgressMessage, 1000);
        this.scanProgressInterval = progressInterval;
        
        // استدعاء API المسح
        const csrfToken = document.querySelector('[name=csrfmiddlewaretoken]')?.value;
        if (!csrfToken) {
            console.error('[ExtractionSmart] ❌ CSRF token not found');
            this.showToast('خطأ أمني: رمز CSRF غير موجود', 'error');
            this.cleanupScan(startScanButton, originalButtonContent, scanProgress);
            return;
        }
        
        console.log('[ExtractionSmart] 📡 Sending scan request to API...');
        
        fetch(this.apiEndpoints.scanCapture, {
            method: 'POST',
            headers: {
                'X-CSRFToken': csrfToken,
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({}),
            signal: this.scanAbortController.signal  // للسماح بالإلغاء
        })
        .then(response => {
            console.log('[ExtractionSmart] 📬 Scan API responded:', response.status, response.ok);
            return response.json();
        })
        .then(data => {
            console.log('[ExtractionSmart] 📦 Scan API data:', data);
            this.cleanupScan(startScanButton, originalButtonContent, scanProgress);
            
            // Success check: both HTTP status and JSON status
            if (data.status === 'ok' || data.status === 'success') {
                if (data.file_url) {
                    console.log('[ExtractionSmart] ✅ Scan successful! File URL:', data.file_url);
                    console.log('[ExtractionSmart] 📄 File name:', data.file_name);
                    console.log('[ExtractionSmart] 🔧 Operation:', data.operation);
                    
                    // تحميل الملف من السيرفر وعرضه
                    this.loadScannedFile(data.file_url, data.file_name);
                    this.showToast('✅ تم المسح الضوئي بنجاح', 'success');
                } else {
                    console.warn('[ExtractionSmart] ⚠️ Success but no file_url in response');
                    this.showToast('⚠️ تم المسح لكن لا يوجد رابط للملف', 'warning');
                }
            } else {
                console.error('[ExtractionSmart] ❌ Scan failed:', {
                    status: data.status,
                    error_code: data.error_code,
                    message: data.message,
                    fullData: data
                });
                
                // رسائل خطأ محسّنة مع الحلول
                let errorMessage = data.message || 'حدث خطأ في المسح';
                let troubleshootingTips = [];
                
                if (data.troubleshooting && data.troubleshooting.ar) {
                    troubleshootingTips = data.troubleshooting.ar;
                } else {
                    // Fallback troubleshooting based on error code
                    if (data.error_code === 'SCANNER_NOT_FOUND') {
                        errorMessage = '❌ برنامج Canon CaptureOnTouch غير موجود';
                        troubleshootingTips = [
                            'ثبّت برنامج Canon CaptureOnTouch',
                            'أو فعّل وضع المحاكاة: SCAN_SIMULATOR_MODE=True',
                            'تأكد من مسار البرنامج في الإعدادات'
                        ];
                    } else if (data.error_code === 'SCAN_TIMEOUT') {
                        errorMessage = '⏱️ انتهت مهلة المسح (60 ثانية)';
                        troubleshootingTips = [
                            'تأكد من تشغيل برنامج Canon',
                            'انقر زر المسح في البرنامج',
                            'تحقق من مسار الحفظ في إعدادات Canon',
                            'جرب المسح مرة أخرى'
                        ];
                    } else if (data.error_code === 'NO_ACCESSIBLE_FOLDERS') {
                        errorMessage = '📁 لا يمكن الوصول لمجلدات الحفظ';
                        troubleshootingTips = [
                            'تحقق من صلاحيات الوصول للمجلدات',
                            'غيّر مسار الحفظ في Canon إلى مجلد متاح',
                            'شغّل البرنامج بصلاحيات المدير'
                        ];
                    } else if (data.error_code === 'FILE_VALIDATION_FAILED') {
                        errorMessage = '❌ الملف الممسوح تالف أو فارغ';
                        troubleshootingTips = [
                            'تأكد من اكتمال عملية المسح',
                            'جرب مسح المستند مرة أخرى',
                            'تحقق من إعدادات الجودة في Canon',
                            'تأكد من وضع المستند بشكل صحيح'
                        ];
                    }
                }
                
                // عرض الخطأ مع النصائح
                let fullErrorMsg = errorMessage;
                if (troubleshootingTips.length > 0) {
                    fullErrorMsg += '\n\n💡 حلول مقترحة:\n' + 
                        troubleshootingTips.map((tip, i) => `${i + 1}. ${tip}`).join('\n');
                }
                
                console.error('[ExtractionSmart] 📋 Error details:', fullErrorMsg);
                this.showToast(errorMessage, 'error');
                
                // عرض النصائح في console للمطور
                if (troubleshootingTips.length > 0) {
                    console.info('[ExtractionSmart] 💡 Troubleshooting tips:', troubleshootingTips);
                }
            }
        })
        .catch(error => {
            // تحقق من الإلغاء
            if (error.name === 'AbortError') {
                console.log('[ExtractionSmart] 🚫 Scan request aborted by user');
                return; // Already handled by cancelScan
            }
            
            console.error('[ExtractionSmart] ❌ Scan error:', error);
            console.error('[ExtractionSmart] 📋 Error details:', {
                name: error.name,
                message: error.message,
                stack: error.stack
            });
            
            this.cleanupScan(startScanButton, originalButtonContent, scanProgress);
            this.showToast(`خطأ في الاتصال: ${error.message}`, 'error');
        });
    }
    
    // إلغاء المسح
    cancelScan(button, originalContent, progressElement) {
        console.log('[ExtractionSmart] 🚫 cancelScan() called - User cancelled scan');
        
        if (this.scanAbortController) {
            this.scanAbortController.abort();
            this.scanAbortController = null;
        }
        
        this.cleanupScan(button, originalContent, progressElement);
        this.showToast('تم إلغاء المسح', 'info');
    }
    
    // تنظيف واجهة المسح
    cleanupScan(button, originalContent, progressElement) {
        console.log('[ExtractionSmart] 🧹 cleanupScan() - Cleaning up UI');
        
        // إيقاف interval
        if (this.scanProgressInterval) {
            clearInterval(this.scanProgressInterval);
            this.scanProgressInterval = null;
        }
        
        // إزالة زر الإلغاء
        if (this.scanCancelButton) {
            this.scanCancelButton.remove();
            this.scanCancelButton = null;
        }
        
        // إعادة الزر لحالته
        progressElement.style.display = 'none';
        button.disabled = false;
        button.style.position = '';
        button.innerHTML = originalContent;

        // إعادة تفعيل أزرار "مسح المزيد" و "حذف الممسوح" إن كانت موجودة
        const scanMoreBtn = document.getElementById('scanMoreButton');
        const clearScannedBtn = document.getElementById('clearScannedButton');
        if (scanMoreBtn) scanMoreBtn.disabled = false;
        if (clearScannedBtn) clearScannedBtn.disabled = false;
    }

    // تحميل الملف الممسوح من السيرفر وعرضه
    loadScannedFile(fileUrl, fileName) {
        console.log('[ExtractionSmart] loadScannedFile():', fileName, 'from URL:', fileUrl);
        const append = !!this._scanAppendMode;

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
                    fileName: fileName,
                    append
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

                // ====== وضع "مسح المزيد" — دمج الصفحات ======
                if (append) {
                    // PDF لا يمكن دمجه على جانب العميل بدون مكتبة خارجية
                    if ((fileObject.type || '').includes('pdf') || /\.pdf$/i.test(safeName)) {
                        this.showToast('⚠️ لا يمكن دمج ملفات PDF تلقائياً — احتُفظ بالمسح الأخير فقط', 'warning', 6000);
                        this.scannedFiles = [fileObject];
                        this.currentFile = fileObject;
                        this.displayBlobPreview(finalBlob, fileName);
                        this.displayFileName(fileName);
                        this._updateScanState();
                        setTimeout(() => this.extractData(), 400);
                        return;
                    }
                    // أضِف للمصفوفة ثم ادمج كل الصفحات في صورة واحدة
                    this.scannedFiles.push(fileObject);
                    this._mergeScannedImages()
                        .then(merged => {
                            this.currentFile = merged;
                            this.displayBlobPreview(merged, merged.name);
                            this.displayFileName(merged.name);
                            this._updateScanState();
                            this.showToast(`✅ تم دمج ${this.scannedFiles.length} صفحات — جاري الاستخراج...`, 'info');
                            // استخراج تلقائي بعد دمج الصفحات
                            setTimeout(() => this.extractData(), 400);
                        })
                        .catch(err => {
                            console.error('[ExtractionSmart] merge error:', err);
                            this.showToast('تعذّر دمج الصفحات — احتُفظ بالأخيرة فقط', 'error');
                            this.scannedFiles = [fileObject];
                            this.currentFile = fileObject;
                            this.displayBlobPreview(finalBlob, fileName);
                            this.displayFileName(fileName);
                            this._updateScanState();
                        });
                    return;
                }

                // ====== وضع المسح الأول — استبدال ======
                this.scannedFiles = [fileObject];
                this.currentFile = fileObject;
                console.log('[ExtractionSmart] ✓ currentFile set from scanned blob');

                this.displayBlobPreview(finalBlob, fileName);
                this.displayFileName(fileName);
                this._updateScanState();
                this.showToast('✓ تم المسح — جاري الاستخراج...', 'info');
                // استخراج تلقائي بعد المسح الضوئي
                setTimeout(() => this.extractData(), 400);
            })
            .catch(error => {
                console.error('[ExtractionSmart] ✗ Failed to load scanned file:', error);
                this.showToast(`خطأ: ${error.message}`, 'error');
            });
    }

    /**
     * دمج كل الصور الممسوحة في صورة JPEG واحدة عمودياً (سهل القراءة، يحفظ الترتيب).
     * يُستخدم عند ضغط "مسح المزيد" — يحوّل عدة صفحات صور إلى ملف واحد.
     */
    _mergeScannedImages() {
        const files = this.scannedFiles.filter(f => (f.type || '').startsWith('image/'));
        if (files.length === 0) return Promise.reject(new Error('no images'));
        if (files.length === 1) return Promise.resolve(files[0]);

        // حمّل كل صورة كـ HTMLImageElement
        const loadImg = (file) => new Promise((resolve, reject) => {
            const img = new Image();
            const url = URL.createObjectURL(file);
            img.onload = () => { resolve(img); URL.revokeObjectURL(url); };
            img.onerror = () => { URL.revokeObjectURL(url); reject(new Error('img load failed: ' + file.name)); };
            img.src = url;
        });

        return Promise.all(files.map(loadImg)).then(imgs => {
            // عرض الـ canvas = أكبر عرض بين الصور (محدود بـ 2000 بكسل لأداء أفضل)
            const maxW = Math.min(2000, Math.max(...imgs.map(i => i.naturalWidth)));
            const scaled = imgs.map(img => {
                const ratio = Math.min(1, maxW / img.naturalWidth);
                return { img, w: Math.round(img.naturalWidth * ratio), h: Math.round(img.naturalHeight * ratio) };
            });
            const gap = 12;
            const totalH = scaled.reduce((s, x) => s + x.h, 0) + gap * (scaled.length - 1);
            const canvas = document.createElement('canvas');
            canvas.width = maxW;
            canvas.height = totalH;
            const ctx = canvas.getContext('2d');
            ctx.fillStyle = '#ffffff';
            ctx.fillRect(0, 0, canvas.width, canvas.height);
            let y = 0;
            scaled.forEach(({ img, w, h }, idx) => {
                const xOff = Math.round((maxW - w) / 2);
                ctx.drawImage(img, xOff, y, w, h);
                y += h + gap;
            });
            return new Promise((resolve, reject) => {
                canvas.toBlob(blob => {
                    if (!blob) return reject(new Error('canvas.toBlob returned null'));
                    const merged = new File([blob], `merged-scan-${files.length}p.jpg`, { type: 'image/jpeg' });
                    resolve(merged);
                }, 'image/jpeg', 0.92);
            });
        });
    }

    /** تحديث حالة الأزرار + عدّاد الصفحات بناءً على scannedFiles. */
    _updateScanState() {
        const scanMoreBtn = document.getElementById('scanMoreButton');
        const clearScannedBtn = document.getElementById('clearScannedButton');
        const startScanBtn = document.getElementById('startScanButton');
        const pagesCount = document.getElementById('scanPagesCount');
        const has = this.scannedFiles && this.scannedFiles.length > 0;

        if (scanMoreBtn) scanMoreBtn.style.display = has ? 'inline-flex' : 'none';
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

    /** حذف الملف الممسوح (للسماح بإعادة المسح من جديد). */
    clearScannedFile() {
        console.log('[ExtractionSmart] clearScannedFile() called');
        this.scannedFiles = [];
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
            // عرض PDF داخل المودال مباشرة
            try {
                const url = URL.createObjectURL(blob);
                this._trackPreviewUrl(url);
                const embed = document.createElement('embed');
                embed.src = url;
                embed.type = 'application/pdf';
                embed.style.width = '100%';
                embed.style.height = 'clamp(360px, 70vh, 760px)';
                embed.style.border = 'none';
                embed.onload = () => console.log('[ExtractionSmart] ✓ PDF embedded');
                embed.onerror = (err) => console.error('[ExtractionSmart] ✗ PDF embed failed:', err);

                modalBody.appendChild(embed);

                // روابط التحكم (تحميل + فتح في تبويب جديد)
                const controlsRow = document.createElement('div');
                controlsRow.style.display = 'flex';
                controlsRow.style.justifyContent = 'center';
                controlsRow.style.gap = '10px';
                controlsRow.style.marginTop = '12px';

                const openBtn = document.createElement('a');
                openBtn.href = url;
                openBtn.target = '_blank';
                openBtn.rel = 'noopener';
                openBtn.className = 'btn btn-outline-primary btn-sm';
                openBtn.textContent = 'فتح في تبويب جديد';

                const dlBtn = document.createElement('a');
                dlBtn.href = url;
                dlBtn.download = fileName || 'document.pdf';
                dlBtn.className = 'btn btn-outline-secondary btn-sm';
                dlBtn.textContent = 'تحميل الملف';

                controlsRow.appendChild(openBtn);
                controlsRow.appendChild(dlBtn);
                modalBody.appendChild(controlsRow);

                modalBody.classList.add('has-image');
                console.log('[ExtractionSmart] ✓ PDF preview embedded');
            } catch (e) {
                console.error('[ExtractionSmart] ✗ PDF preview error:', e);
                modalBody.innerHTML = '<div style="color: #ef4444; text-align: center; padding: 20px;">تعذر عرض ملف الـ PDF</div>';
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

        this.currentFile = file;
        this.displayFilePreview(file);
        this.displayFileName(file.name);
        this.showToast('تم تحميل الملف — جاري الاستخراج...', 'info');
        // استخراج تلقائي بعد تحميل الملف
        setTimeout(() => this.extractData(), 350);
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
    _showExtractionOverlay(message) {
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
            <div class="overlay-sub">يتم تحليل المستند واستخراج البيانات</div>
        `;
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
        this._showExtractionOverlay();

        this.callExtractApi()
            .then((data) => {
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
                this.showToast(this.t('extractSuccess'), 'success');
                // بعد النجاح: حدّث نص الزر ليدل على "إعادة الاستخراج" وركّز على أول حقل يحتاج مراجعة
                if (extractBtn) extractBtn.innerHTML = '↺ إعادة الاستخراج';
                setTimeout(() => this._focusFirstReviewField(data), 200);
            })
            .catch((err) => {
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

    async callExtractApi() {
        const form = new FormData();
        form.append('file', this.currentFile);

        // إضافة timeout (5 دقائق للتحميل الأول للنموذج)
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), 300000);

        let response;
        try {
            response = await fetch(this.apiEndpoints.smartExtract, {
                method: 'POST',
                headers: {
                    'X-CSRFToken': this.getCookie('csrftoken'),
                    'Accept': 'application/json'
                },
                body: form,
                signal: controller.signal
            });
            clearTimeout(timeoutId);
        } catch (err) {
            clearTimeout(timeoutId);
            if (err.name === 'AbortError') {
                console.error('[ExtractionSmart] ✗ Request timeout (5 min)');
                throw new Error('انتهت مهلة الاستخراج (5 دقائق). قد يكون السيرفر يحمّل النماذج للمرة الأولى. يرجى المحاولة مرة أخرى.');
            }
            console.error('[ExtractionSmart] ✗ Fetch failed:', err);
            throw new Error(`خطأ في الاتصال: ${err.message}`);
        }

        let data;
        try {
            data = await response.json();
        } catch (err) {
            // غالباً رد HTML (login أو خطأ خادم). نقرأ النص لعرضه.
            const text = await response.text();
            const hint = text && text.slice(0, 180);
            console.error('[ExtractionSmart] ✗ Non-JSON response from extract API:', hint);
            throw new Error(`فشل الاستخراج (HTTP ${response.status}). يرجى التحقق من تسجيل الدخول أو سجلات الخادم.`);
        }

        if (!response.ok || data.success === false) {
            const msg = data.message || this.t('extractFail');
            if (data.error_code === 'FILE_TYPE') {
                throw new Error(this.t('fileType'));
            }
            if (data.error_code === 'FILE_SIZE') {
                throw new Error(this.t('fileSize'));
            }
            throw new Error(msg);
        }

        this.applyExtractionResult(data);
        return data;
    }

    applyExtractionResult(data) {
        const mapping = [
            { field: 'bookNumber', key: 'book_number', conf: 'book_number_confidence' },
            { field: 'title', key: 'title', conf: 'title_confidence' },
            { field: 'date', key: 'book_date', conf: 'book_date_confidence' },
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
                    if (field === 'bookKind') {
                        let resolvedKind = value;
                        if (resolvedKind === 'incoming') {
                            resolvedKind = 'incoming_internal';
                        } else if (resolvedKind === 'outgoing') {
                            resolvedKind = 'outgoing_internal';
                        }
                        input.value = resolvedKind;
                        this.syncKindUI(resolvedKind);
                    } else {
                        input.value = value;
                    }
                    // إطلاق حدث input لتفعيل مؤشر التحقق وتفعيل زر الحفظ
                    try { input.dispatchEvent(new Event('input', { bubbles: true })); } catch (e) {}
                    try { input.dispatchEvent(new Event('change', { bubbles: true })); } catch (e) {}
                    this.updateConfidenceBadge(field, data[conf] || 0);
                    this.validateField(field);
                }
            }
        });

        const extractedDocumentType = (data.document_type || data.book_type_name || '').trim();
        if (extractedDocumentType) {
            this.setDocumentTypeValue(extractedDocumentType, this.getCurrentKind());
        }

        // ضمان تحديث عام بعد الانتهاء من كل الحقول
        if (typeof updateValidationIndicator === 'function') {
            try { updateValidationIndicator(); } catch (e) {}
        }
    }

    updateConfidenceBadge(fieldId, confidence) {
        const confidenceElement = document.getElementById(`${fieldId}Confidence`);
        if (!confidenceElement) return;

        const level = this.getConfidenceLevel(confidence);
        confidenceElement.className = `confidence-badge ${level}`;
        document.getElementById(`${fieldId}ConfidenceValue`).textContent = `${Math.round(confidence * 100)}%`;
        confidenceElement.style.display = 'inline-flex';
    }

    getConfidenceLevel(confidence) {
        if (confidence >= 0.85) return 'high';
        if (confidence >= 0.70) return 'medium';
        return 'low';
    }

    // ===== Form Validation =====
    handleFieldInput(e) {
        const fieldId = e.target.id;
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
            senderDateField.value = todayISO;
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

        fields.forEach(field => {
            if (field.id !== 'date' && field.id !== 'senderDate') {
                field.value = '';
            }
            field.classList.remove('has-error', 'is-valid');
            if (field.id === 'bookNumber') {
                delete field.dataset.reservationId;
            }
        });

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

        const badges = document.querySelectorAll('.confidence-badge');
        badges.forEach(badge => { badge.style.display = 'none'; });

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
    }

    // ===== Save Book =====
    async saveBook() {
        // Validate required fields
        const requiredFields = ['bookNumber', 'title', 'date', 'issuingEntity', 'receivingEntity'];
        let isValid = true;
        let firstInvalid = null;

        requiredFields.forEach(fieldId => {
            if (!this.validateField(fieldId)) {
                isValid = false;
                if (!firstInvalid) {
                    firstInvalid = document.getElementById(fieldId);
                }
            }
        });

        if (!isValid) {
            this.showToast(this.t('invalidFields'), 'error', 6000);
            if (firstInvalid) {
                firstInvalid.focus();
                firstInvalid.classList.add('has-error');
            }
            return;
        }

        const kindValue = this.getCurrentKind();
        const documentTypeValue = this.getResolvedDocumentTypeValue(kindValue);
        if (!documentTypeValue) {
            this.showToast('يرجى اختيار نوع المستند أو إدخال نوع جديد.', 'error', 6000);
            if (this.isCustomDocumentTypeSelected()) {
                const customInput = document.getElementById('documentTypeCustom');
                if (customInput) {
                    customInput.focus();
                    customInput.classList.add('has-error');
                }
            } else {
                document.getElementById('documentTypeSelect')?.focus();
            }
            return;
        }

        if (!this.hasAttachedFile()) {
            const proceedWithoutFile = await this.confirmSaveWithoutFile();
            if (!proceedWithoutFile) {
                return;
            }
        }

        const formData = new FormData();
        const bookNumber = document.getElementById('bookNumber').value;
        const senderNumber = document.getElementById('senderNumber')?.value || '';
        const senderDate = document.getElementById('senderDate')?.value || '';
        const dueDate = document.getElementById('dueDate').value;
        const needsFollowup = document.getElementById('needsFollowup')?.checked;

        // Keep both keys during the extraction transition layer.
        formData.append('our_number', bookNumber);
        formData.append('book_number', bookNumber);
        formData.append('sender_number', senderNumber);
        formData.append('outgoing_incoming_number', senderNumber);
        formData.append('title', document.getElementById('title').value);
        formData.append('date', document.getElementById('date').value);
        formData.append('sender_date', senderDate);
        formData.append('due_date', dueDate);
        formData.append('dueDate', dueDate);
        formData.append('needs_followup', needsFollowup ? 'true' : 'false');
        formData.append('issuing_entity', document.getElementById('issuingEntity').value);
        formData.append('receiving_entity', document.getElementById('receivingEntity').value);
        formData.append('secret_level', document.getElementById('secretLevel').value || 'normal');
        formData.append('document_type', documentTypeValue);
        formData.append('book_type_name', documentTypeValue);
        formData.append('kind', kindValue);
        formData.append('margin', document.getElementById('margin').value || '');

        // Prefer the active reservation; fall back to auto_number generation server-side.
        const activeReservation = this.reservations[kindValue];
        if (activeReservation && activeReservation.id) {
            formData.append('reservation_id', activeReservation.id);
        } else {
            formData.append('auto_number', this.autoNumberEnabled ? 'true' : 'false');
        }

        if (this.currentFile) {
            formData.append('file', this.currentFile);
        }

        this.submitBookData(formData);
    }

    async submitBookData(formData) {
        const saveBtn = document.getElementById('saveButton');
        const originalText = saveBtn.innerHTML;
        let savedKind = formData.get('kind') || 'incoming_internal';
        saveBtn.innerHTML = '<span class="spinner"></span> جاري الحفظ...';
        saveBtn.disabled = true;

        let retriedAfterReservationRefresh = false;

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
    showToast(message, type = 'info', duration = 4000) {
        // Delegate to global ToastCenter for consistent UX
        if (window.ToastCenter) {
            window.ToastCenter.show(type, message, { delay: duration });
        } else {
            // Fallback to alert if ToastCenter not available
            alert(message);
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
