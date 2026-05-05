/**
 * TitleAutocomplete Widget  v2.0
 * ─────────────────────────────────────────────────────────────────────────────
 * طبقات التنبؤ (بالأولوية):
 *   1. localStorage      — فوري، بدون شبكة (عناوين كاملة سابقة)
 *   2. قاموس كلمات محلي — إكمال الكلمة الجزئية الحالية (عربي + إنجليزي)
 *   3. قاعدة البيانات   — اقتراحات عناوين كاملة (trigram + icontains)
 *   4. Bigram            — الكلمة التالية الأكثر شيوعاً من DB
 *
 * ميزات جديدة:
 *   • إكمال الكلمة بضغطة Tab (كـ Word/VS Code)
 *   • حجم خط ديناميكي يتكيف مع طول العنوان
 *   • اتجاه نص ديناميكي (RTL ↔ LTR) حسب أول حرف مكتوب
 *   • مؤشر [Tab ↹] يظهر عند وجود اقتراح
 */

(function () {
  'use strict';

  // ─── ثوابت ──────────────────────────────────────────────────────────────────
  const LS_KEY         = 'ta_history_v1';
  const LS_MAX         = 120;
  const DEBOUNCE_MS    = 220;
  const MIN_CHARS      = 2;
  const API_BASE       = '/books/api/title-autocomplete/';
  const WORDS_API      = '/books/api/title-words/';
  const MAX_DROPDOWN   = 8;

  // ─── قاموس الكلمات العربية — مراسلات رسمية وأرشفة ──────────────────────────
  // مُرتَّب في وقت التهيئة عبر .sort() — يُشغَّل مرة واحدة فقط
  const AR_WORDS_RAW = [
    // ── أفعال المراسلة الرسمية (مضارع + ماضٍ) ──────────────────────────────
    'أبدى','أبلغ','أتاح','أجرى','أحاط','أحال','أخطر','أرسل','أرفق',
    'أشار','أصدر','أطلع','أعاد','أعلم','أفاد','أقر','أكد','أمر','أنجز','أنهى',
    'أوضح','أوصى','أوعز','أفصح','أنذر','أجاب','أبرم','أثبت','أحدّث','أدرج',
    'أدرك','أرجأ','أسقط','أعلن','أفرج','أقرّ','أكمل','أمدّ','أناب','أنجز',
    'استفسر','استكمل','استلم','استوجب','استوفى','استقال','استدعى','استعرض',
    'استرد','استقر','استأنف','استعان','استفاد','استمر','استنتج','استهدف',
    'اعتمد','اقترح','اتخذ','اتفق','احتج','احتاط','احتسب','احتضن','احتفظ',
    'ادّعى','اطّلع','اعترض','اعترف','اقتضى','اكتسب','التزم',
    'تتضمن','تتعلق','تجدر','تحيط','تحيطكم','تدعو','ترفق','ترغب',
    'تطلب','تعقيباً','تفضلوا','تقرر','توضح','تبلّغ','تبيّن','تتطلب',
    'تثبت','تحدد','تخص','تشير','تضمّن','تعتمد','تقتضي','تكفل','تمنح',
    'يتضمن','يتعلق','يخص','يرجى','يستوجب','يشير','يشمل','يعود','يفيد','يقرر',
    'يتطلب','يستدعي','يستلزم','يكفل','يمنح','يقتضي','يحدد','يثبت',
    'نحيط','نرفق','نطلب','نفيدكم','نود','نقترح','نؤكد','نعلمكم','نبلّغ',
    'نستفسر','نستكمل','نستلم','نعتمد','نلتزم','نرحّب','نشير','نرى',
    'أبادر','أبرر','أثمّن','أتحمل','أتعامل','أتقدم','أتوجه','أخضع',
    'أرحّب','أستأذن','أستدعي','أستعرض','أقدّم','أتعهد',
    // ── وثائق وإجراءات وأنواع المراسلات ──────────────────────────────────
    'إجازة','إجراء','إحالة','إحاطة','إخطار','إرسال','إشارة','إشعار',
    'إضافة','إعارة','إعلام','إفادة','إقرار','إلغاء','إنجاز','إنهاء',
    'إنذار','إبلاغ','إبراء','إبرام','إثبات','إجابة','إدراج','إعداد',
    'إفراج','إقامة','إقفال','إكمال','إنابة','إيفاد','إيضاح','إيعاز',
    'اتفاقية','استفسار','استلام','استمارة','استنتاج','اعتراض','استئناف',
    'استدعاء','استعراض','استرداد','استقالة','استمرارية','استنكار',
    'أمر','أوامر','أذونات','أسباب','أحكام',
    'بطاقة','بيان','بلاغ','بروتوكول','بند','بيانات',
    'تأجيل','تحقيق','تحويل','تدريب','تعديل','تعليمات','تعميم',
    'تفويض','تقرير','تقييم','تكليف','توجيه','توضيح','توصية','توكيل',
    'تبليغ','تثبيت','تجديد','تحديد','تحديث','تخصيص','تدقيق','ترقية',
    'تسجيل','تسوية','تشكيل','تصديق','تصريح','تعيين','تفتيش','تقاعد',
    'تمديد','تمويل','توظيف','تحرير','تخفيض','تزكية','تصحيح','توزيع',
    'جواب','جدول','جرد','جلسة','جهة',
    'خطاب','خطة','خلاصة','خبر','خدمة','خلاف',
    'دراسة','دعوة','ديوان','دفع','دورة','دليل',
    'رد','رسالة','رواتب','ردود','ربط','رصيد','رفض',
    'سجل','سؤال','سير','سند','سلفة',
    'شهادة','شكوى','شرح','شروط','شأن',
    'صرف','صيغة','صدور','صلاحية','صكّ',
    'طلب','طلبات','طعن',
    'عرض','عقد','عريضة','علم','عمل','عطلة','عقوبة','عتاد',
    'قرار','قرارات','قانون','قواعد','قضية','قسيمة',
    'كتاب','كشف','كتيب','كفالة',
    'لجنة','لائحة','لوائح','لغاء','لقاء',
    'مبادرة','متابعة','مخطط','مذكرة','مراجعة','مراسلة','مرفق',
    'مشروع','مشاركة','مطالبة','معلومات','ملاحظة','ملف','منشور',
    'موافقة','مؤتمر','مؤهل','محضر','مجلة','محاضر','مخالفة','مرتب',
    'مستند','مسودة','مصادقة','مصفوفة','معاهدة','مقترح','مقرر','ملزم',
    'منح','منع','موازنة','مؤشر','مكافأة','ملحق','منهج','موقف',
    'نتيجة','نسخة','نموذج','نظام','نزاع','نقل',
    'وثيقة','وصل','وكالة','ورقة','واجبات','وقف','وصاية',
    'هيكل','هوية',
    // ── مؤسسات وتسميات تنظيمية ────────────────────────────────────────────
    'إدارة','إدارات','إداري','إدارية',
    'استشارة','استشارات','استشاري',
    'أمانة','أمانات',
    'جامعة','جهاز',
    'حكومة','حكومي',
    'دائرة','دوائر','ديوان',
    'رئاسة','رئاسات',
    'شركة','شركات','شعبة',
    'فرع','فروع',
    'قسم','أقسام',
    'كلية','كليات',
    'مجلس','مجالس','مديرية','مديريات','مركز','مراكز',
    'محكمة','محاكم','معهد','معاهد','منظمة','منظمات','مؤسسة','مؤسسات',
    'مكتب','مكاتب','مستشفى','مستشفيات','مصلحة','مصالح',
    'هيئة','هيئات',
    'وحدة','وحدات','وزارة','وزارات','وكالة','وكالات',
    // ── تحية وألقاب رسمية ──────────────────────────────────────────────────
    'الأفاضل','الأستاذ','الأستاذة',
    'الاحترام','الاطلاع',
    'السلام','السيد','السيدة',
    'التحية','التقدير','التفضل',
    'الكريم','الكريمة',
    'المحترم','المحترمة','الموقر','الموقرة',
    'المدير','المديرة','الرئيس','الوزير',
    'الدكتور','الدكتورة','المهندس','المهندسة',
    // ── حروف جر وتعبيرات موضوعية ───────────────────────────────────────────
    'بخصوص','بشأن','بموجب','بناءً','بتاريخ','بمقتضى','بالنسبة',
    'استناداً','إشارةً','تعقيباً','إضافةً','علاوةً','وفقاً',
    'موضوع','خلاصة','فحوى','محتوى',
    'ردًا','إجابةً','متعلق','مرتبط','خاص','متضمن',
    'عطفاً','تنفيذاً','إكمالاً','استكمالاً',
    // ── صفات وصفات تفصيلية ─────────────────────────────────────────────────
    'الحالي','الحالية',
    'الخاص','الخاصة',
    'الداخلي','الداخلية',
    'الرسمي','الرسمية',
    'الساري','السارية',
    'السابق','السابقة',
    'العام','العامة',
    'الكامل','الكاملة',
    'المؤرخ','المؤرخة',
    'المحدد','المحددة',
    'المذكور','المذكورة',
    'المرفق','المرفقة',
    'المشار',
    'المعتمد','المعتمدة',
    'المعني','المعنية',
    'المقدم','المقدمة',
    'المنوه','المنوه',
    'الوارد','الواردة',
    'الجديد','الجديدة',
    'الإضافي','الإضافية',
    'التنفيذي','التنفيذية',
    'الفني','الفنية',
    'القانوني','القانونية',
    'الإداري','الإدارية',
    'المالي','المالية',
    'الخدمي','الخدمية',
    'الاستثنائي','الاستثنائية',
    'التفصيلي','التفصيلية',
    'المرحلي','المرحلية',
    'النهائي','النهائية',
    // ── ظروف زمنية وأرقام ترتيبية ──────────────────────────────────────────
    'اليومي','الأسبوعي','الشهري','السنوي','الفصلي','الربعي',
    'القادم','الماضي','المؤرخ','القادمة','الماضية',
    'الأول','الثاني','الثالث','الرابع','الخامس',
    'الأولى','الثانية','الثالثة','الرابعة','الخامسة',
    'السادس','السابع','الثامن','التاسع','العاشر',
    // ── مصطلحات مالية وإدارية ───────────────────────────────────────────────
    'ميزانية','موازنة','اعتماد','اعتمادات','تخصيص','تخصيصات',
    'صرف','مصروف','مصروفات','إيرادات','نفقات','مبلغ','مبالغ',
    'راتب','رواتب','أجر','أجور','علاوة','علاوات','مكافأة','مكافآت',
    'تقاعد','تأمين','ضريبة','رسوم','غرامة','مقاول','عطاء','مناقصة',
    'تدقيق','مراجعة','تفتيش','رقابة','محاسبة','متابعة','تقييم',
    'مشتريات','لوازم','تجهيزات','معدات','موجودات',
    // ── مصطلحات الموارد البشرية ─────────────────────────────────────────────
    'توظيف','تعيين','ترقية','نقل','إجازة','انتداب','إعارة','استقالة',
    'تقاعد','فصل','إيقاف','عقوبة','تحقيق','لجنة','درجة','فئة',
    'ملاك','كادر','درجات','أقدمية','خدمة','تدريب','مؤهل','شهادة',
    // ── مصطلحات المشاريع والعقود ───────────────────────────────────────────
    'مشروع','عقد','عقود','اتفاقية','بروتوكول','مذكرة','تفاهم',
    'مقاول','مقاولة','تنفيذ','إنجاز','إتمام','استكمال','تأجيل',
    'مناقصة','ممارسة','عطاء','عطاءات','مزايدة','أسعار','كميات',
    'مواصفات','متطلبات','شروط','أحكام','جداول','خرائط','تصاميم',
    // ── مصطلحات قانونية وقضائية ────────────────────────────────────────────
    'حكم','أحكام','قرار','قرارات','قانون','قوانين','نظام','أنظمة',
    'تعليمات','لوائح','مرسوم','مراسيم','أمر','أوامر','ديوان',
    'طعن','طعون','استئناف','تمييز','نقض','إلغاء','تأييد',
    'دعوى','دعاوى','قضية','قضايا','حادثة','شكوى','شكاوى',
    'مدعي','مدعى','خصوم','أطراف','شهود','بيّنة','دليل','أدلة',
  ];

  // ─── قاموس الكلمات الإنجليزية ──────────────────────────────────────────────
  const EN_WORDS_RAW = [
    // ── verbs of official correspondence ──────────────────────────────────
    'acknowledge','advise','agree','allocate','amend','announce','apply',
    'approve','arrange','assess','assign','attach','authorize',
    'certify','circulate','clarify','close','communicate','complete',
    'confirm','consider','coordinate','cover','create',
    'decline','delegate','deliver','deny','designate','direct','discuss',
    'draft','endorse','establish','evaluate','examine','expedite','extend',
    'facilitate','finalize','follow','forward','fulfill',
    'grant','guide',
    'implement','inform','initiate','inspect','investigate','issue',
    'kindly','notify',
    'obtain','outline',
    'prepare','present','proceed','process','propose','provide','pursue',
    'receive','recommend','refer','reject','release','renew','request',
    'resolve','respond','review','revise',
    'schedule','sign','submit','supply',
    'terminate','transfer','transmit',
    'update','verify',
    // ── document types ─────────────────────────────────────────────────────
    'addendum','agenda','agreement','amendment','annex','appendix',
    'application','approval','attachment','authorization',
    'brief','budget','bulletin',
    'certificate','charter','circular','compliance','confirmation',
    'contract','correspondence','council','cover','decision','decree',
    'directive','document','draft',
    'endorsement','exhibit',
    'form','framework',
    'gazette','guideline',
    'handbook',
    'instruction','invoice',
    'letter','license','list',
    'manual','memorandum','minutes',
    'notice','notification','order','ordinance',
    'permit','plan','policy','procedure','proposal','protocol',
    'record','reference','regulation','report','request','resolution',
    'response','review',
    'schedule','specification','statement','statute','summary',
    'tender',
    'voucher','waiver',
    // ── administrative / institutional terms ──────────────────────────────
    'about','above','accordance','action','activities',
    'administration','agency','annual','authority',
    'board','branch','bureau',
    'cabinet','committee','council','department','directorate','division',
    'establishment','executive',
    'federal','general','government','governorate',
    'headquarters','hereby','honorable',
    'implementation','information','institution',
    'jurisdiction',
    'management','ministry','municipal',
    'national','official','organization',
    'parliament','presidential','provincial',
    'regional','secretariat','section',
    'unit','urgent',
    // ── financial / procurement terms ─────────────────────────────────────
    'acquisition','allocation','allowance','audit','award',
    'bidding','bonus','budget',
    'compensation','contract','cost',
    'disbursement','expenditure',
    'financial','funding',
    'invoice',
    'payment','payroll','pension','procurement','purchase',
    'quotation',
    'reimbursement','revenue',
    'salary','settlement','subsidy','surplus',
    'taxation','tender',
    // ── HR terms ──────────────────────────────────────────────────────────
    'appointment','attendance',
    'demotion','dismissal',
    'employment',
    'leave','loan',
    'pension','position','probation','promotion',
    'recruitment','redundancy','reinstatement','resignation','retirement',
    'secondment','seniority','suspension',
    'training','transfer',
    'vacancy',
    // ── project / engineering terms ───────────────────────────────────────
    'completion','construction','contract',
    'design','development',
    'engineering','execution',
    'feasibility','final',
    'infrastructure','inspection',
    'maintenance','modification',
    'operation','oversight',
    'performance','phase','procurement','progress',
    'quality',
    'rehabilitation','requirements',
    'scope','specifications','supervision',
    'technical',
    'upgrade',
    // ── adjectives / qualifiers ───────────────────────────────────────────
    'academic','administrative','amended','annual',
    'approved','attached',
    'binding','budgetary',
    'central','classified','commercial','confidential','constitutional',
    'contractual',
    'departmental','detailed',
    'executive','external',
    'federal','financial','fiscal','formal',
    'general','governmental',
    'internal','international',
    'legal','local',
    'ministerial','monthly',
    'national',
    'official','operational','organizational',
    'parliamentary','pending','periodic','permanent','preliminary',
    'presidential','prior',
    'quarterly',
    'regional','related','relevant',
    'secretarial','special','statutory',
    'technical','temporary',
    'urgent',
    'whereas','within','written',
    'yearly',
  ];

  // ─── WordDict — إكمال بادئة كلمة (Binary Search) ─────────────────────────
  const WordDict = (() => {
    // مصفوفتان مُرتَّبتان قابلتان للتوسيع ديناميكياً
    const _ar = AR_WORDS_RAW.slice().sort();
    const _en = EN_WORDS_RAW.slice().sort();

    /** يجد أول كلمة في المصفوفة المُرتَّبة تبدأ بـ prefix */
    function _bsearch(arr, prefix) {
      let lo = 0, hi = arr.length;
      while (lo < hi) {
        const mid = (lo + hi) >>> 1;
        if (arr[mid] < prefix) lo = mid + 1;
        else hi = mid;
      }
      return lo < arr.length && arr[lo].startsWith(prefix) ? arr[lo] : null;
    }

    /** يُدرج كلمة في مصفوفة مُرتَّبة دون تكرار */
    function _insertSorted(arr, word) {
      let lo = 0, hi = arr.length;
      while (lo < hi) {
        const mid = (lo + hi) >>> 1;
        if (arr[mid] < word) lo = mid + 1;
        else hi = mid;
      }
      if (arr[lo] !== word) arr.splice(lo, 0, word);
    }

    return {
      /**
       * يعيد اللاحقة لإكمال prefix إلى الكلمة الأقرب في القاموس.
       * مثال: findCompletion('مراس') → 'لة'  (لإكمال 'مراسلة')
       */
      findCompletion(prefix) {
        if (!prefix || prefix.length < 2) return null;
        const isArabic = /[\u0600-\u06FF]/.test(prefix[0]);
        const word = isArabic
          ? _bsearch(_ar, prefix)
          : _bsearch(_en, prefix.toLowerCase());
        return word && word !== prefix ? word.slice(prefix.length) : null;
      },

      /**
       * يُضيف كلمات جديدة من DB إلى القاموس الحي دون إعادة بناء كامل.
       * يُستدعى مرة واحدة عند تحميل الصفحة.
       */
      inject(words) {
        if (!Array.isArray(words)) return;
        for (const w of words) {
          if (!w || w.length < 3) continue;
          const isArabic = /[\u0600-\u06FF]/.test(w[0]);
          if (isArabic) {
            _insertSorted(_ar, w);
          } else if (/^[a-z]/.test(w)) {
            _insertSorted(_en, w.toLowerCase());
          }
        }
      },

      /** للاختبار — يُعيد حجم كلا القاموسين */
      size() { return { ar: _ar.length, en: _en.length }; },
    };
  })();

  // ─── localStorage manager ──────────────────────────────────────────────────
  const HistoryStore = {
    _cache: null,

    _load() {
      if (this._cache) return this._cache;
      try {
        this._cache = JSON.parse(localStorage.getItem(LS_KEY) || '[]');
      } catch {
        this._cache = [];
      }
      return this._cache;
    },

    save(title) {
      if (!title || title.trim().length < 4) return;
      const arr = this._load().filter(t => t !== title);
      arr.unshift(title.trim());
      this._cache = arr.slice(0, LS_MAX);
      try { localStorage.setItem(LS_KEY, JSON.stringify(this._cache)); } catch {}
    },

    search(q) {
      const lower = q.toLowerCase();
      return this._load()
        .filter(t => t.toLowerCase().includes(lower))
        .slice(0, MAX_DROPDOWN);
    }
  };

  // ─── Debounce helper ───────────────────────────────────────────────────────
  function debounce(fn, ms) {
    let timer;
    return function (...args) {
      clearTimeout(timer);
      timer = setTimeout(() => fn.apply(this, args), ms);
    };
  }

  // ─── Widget class ──────────────────────────────────────────────────────────
  class TitleAutocomplete {
    constructor(textarea, options = {}) {
      this.textarea   = textarea;
      this.kind       = options.kindGetter || (() => '');
      this.apiBase    = options.apiBase || API_BASE;
      this.onSelect   = options.onSelect || null;

      this._selectedIdx   = -1;
      this._suggestions   = [];
      this._ghostWord     = null;      // اللاحقة (إكمال) أو الكلمة التالية (bigram)
      this._ghostMode     = null;      // 'word_complete' | 'next_word'
      this._abortCtrl     = null;      // AbortController لـ _search
      this._ghostAbortCtrl = null;     // AbortController منفصل لـ _fetchGhost
      this._active        = false;

      this._build();
      this._bind();
      // تطبيق الحجم والاتجاه الأولي
      this._adjustDynamic();
    }

    // ── بناء DOM ──────────────────────────────────────────────────────────────
    _build() {
      const wrapper = document.createElement('div');
      wrapper.className = 'ta-wrapper';
      wrapper.style.cssText = 'position:relative;display:block;';
      this.textarea.parentNode.insertBefore(wrapper, this.textarea);
      wrapper.appendChild(this.textarea);

      // طبقة النص الشبحي (ghost overlay)
      this.ghost = document.createElement('div');
      this.ghost.className = 'ta-ghost';
      this.ghost.setAttribute('aria-hidden', 'true');
      this.ghost.style.cssText = [
        'position:absolute; top:0; left:0; right:0; bottom:0;',
        'pointer-events:none; white-space:pre-wrap; word-break:break-word;',
        'padding:inherit; font:inherit; line-height:inherit;',
        'color:transparent; overflow:hidden;',
        'border:1px solid transparent; border-radius:inherit;',
        'box-sizing:border-box;',
      ].join(' ');
      wrapper.appendChild(this.ghost);

      // مؤشر لوحة المفاتيح [Tab ↹]
      this.tabHint = document.createElement('div');
      this.tabHint.className = 'ta-tab-hint';
      this.tabHint.setAttribute('aria-hidden', 'true');
      this.tabHint.textContent = 'Tab ↹';
      wrapper.appendChild(this.tabHint);

      // قائمة الاقتراحات المنسدلة
      this.dropdown = document.createElement('ul');
      this.dropdown.className = 'ta-dropdown';
      this.dropdown.setAttribute('role', 'listbox');
      this.dropdown.style.cssText = [
        'position:absolute; top:calc(100% + 4px); right:0; left:0;',
        'background:#fff; border:1px solid #d4c5a9;',
        'border-radius:10px; box-shadow:0 8px 24px rgba(0,0,0,0.14);',
        'max-height:280px; overflow-y:auto;',
        'z-index:9999; margin:0; padding:4px 0; list-style:none;',
        'display:none;',
      ].join(' ');
      wrapper.appendChild(this.dropdown);
    }

    // ── ربط الأحداث ───────────────────────────────────────────────────────────
    _bind() {
      const debouncedSearch = debounce(q => this._search(q), DEBOUNCE_MS);
      const debouncedGhost  = debounce(q => this._fetchGhost(q), DEBOUNCE_MS + 60);

      this.textarea.addEventListener('input', () => {
        const val = this.textarea.value;
        this._adjustDynamic();
        if (val.length < MIN_CHARS) { this._hide(); this._clearGhost(); return; }
        debouncedSearch(val);
        debouncedGhost(val);
      });

      this.textarea.addEventListener('keydown', e => {
        // ── التنقل في القائمة المنسدلة ──────────────────────────────────────
        if (this._active) {
          if (e.key === 'ArrowDown') { e.preventDefault(); this._move(1); return; }
          if (e.key === 'ArrowUp')   { e.preventDefault(); this._move(-1); return; }
          if (e.key === 'Enter' && this._selectedIdx >= 0) {
            e.preventDefault();
            this._accept(this._suggestions[this._selectedIdx]);
            return;
          }
          if (e.key === 'Escape') { this._hide(); return; }
        }

        // ── Tab → قبول النص الشبحي (الأولوية القصوى) ──────────────────────
        if (e.key === 'Tab' && this._ghostWord) {
          e.preventDefault();
          this._acceptGhost();
          return;
        }

        // ── Escape → إلغاء النص الشبحي ────────────────────────────────────
        if (e.key === 'Escape' && this._ghostWord) {
          this._clearGhost();
          return;
        }
      });

      // مسح النص الشبحي عند المسافة إذا كنا في وضع إكمال الكلمة
      this.textarea.addEventListener('keyup', e => {
        if (e.key === ' ' && this._ghostMode === 'word_complete') {
          this._clearGhost();
        }
      });

      // إغلاق عند النقر خارجاً
      document.addEventListener('pointerdown', e => {
        if (!this.dropdown.contains(e.target) && e.target !== this.textarea) {
          this._hide();
        }
      });
    }

    // ── الحجم الديناميكي + اتجاه النص ────────────────────────────────────────
    _adjustDynamic() {
      this._adjustFontSize();
      this._adjustDirection();
    }

    _adjustFontSize() {
      const len = this.textarea.value.length;
      let newSize;
      if      (len <= 45)  newSize = '15px';
      else if (len <= 75)  newSize = '14px';
      else if (len <= 110) newSize = '13px';
      else                 newSize = '12px';
      if (this.textarea.style.fontSize !== newSize) {
        this.textarea.style.fontSize = newSize;
      }
    }

    _adjustDirection() {
      const text = this.textarea.value.trimStart();
      // إعادة الافتراضي RTL عند الحقل الفارغ
      if (!text.length) {
        if (this.textarea.dir !== 'rtl') {
          this.textarea.dir             = 'rtl';
          this.textarea.style.textAlign = 'right';
        }
        return;
      }
      const ch = text[0];
      // نطاقات اليونيكود للعربية والنصوص الأخرى RTL
      const isArabic = /[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF\uFB50-\uFDFF\uFE70-\uFEFF]/.test(ch);
      const newDir    = isArabic ? 'rtl' : 'ltr';
      const newAlign  = isArabic ? 'right' : 'left';
      if (this.textarea.dir !== newDir) {
        this.textarea.dir              = newDir;
        this.textarea.style.textAlign  = newAlign;
      }
    }

    // ── البحث عن الاقتراحات الكاملة ──────────────────────────────────────────
    async _search(q) {
      // طبقة 1: localStorage
      const local = HistoryStore.search(q);

      // طبقة 2: AJAX (DB)
      let remote = [];
      try {
        if (this._abortCtrl) this._abortCtrl.abort();
        this._abortCtrl = new AbortController();
        const params = new URLSearchParams({ q, mode: 'full', kind: this.kind() });
        const resp = await fetch(`${this.apiBase}?${params}`, {
          signal: this._abortCtrl.signal,
          headers: { 'X-Requested-With': 'XMLHttpRequest' }
        });
        if (resp.ok) {
          const data = await resp.json();
          remote = (data.suggestions || []).map(s => s.text);
        }
      } catch (err) {
        if (err.name !== 'AbortError') console.warn('title-ac:', err);
      }

      const merged = [...new Set([...local, ...remote])].slice(0, MAX_DROPDOWN);
      this._suggestions = merged;
      merged.length ? this._show(merged, q) : this._hide();
    }

    // ── جلب النص الشبحي (إكمال كلمة → Bigram) ────────────────────────────────
    async _fetchGhost(q) {
      // إلغاء أي طلب bigram سابق لمنع الكتابة فوق نتيجة القاموس (race condition)
      if (this._ghostAbortCtrl) { this._ghostAbortCtrl.abort(); this._ghostAbortCtrl = null; }

      // ── الأولوية 1: إكمال الكلمة الجزئية الحالية من القاموس ──────────────
      const endsWithSpace = q.endsWith(' ');
      if (!endsWithSpace) {
        const words   = q.trimEnd().split(/\s+/);
        const lastWord = words[words.length - 1] || '';
        if (lastWord.length >= 2) {
          const suffix = WordDict.findCompletion(lastWord);
          if (suffix) {
            this._ghostWord = suffix;
            this._ghostMode = 'word_complete';
            this._renderGhost(q);
            this._showTabHint();
            return;
          }
        }
      }

      // ── الأولوية 2: الكلمة التالية من قاعدة البيانات (Bigram) ────────────
      // لا نغير _ghostMode هنا — نغيره فقط بعد استلام الرد
      try {
        this._ghostAbortCtrl = new AbortController();
        const params = new URLSearchParams({ q, mode: 'next_word', kind: this.kind() });
        const resp = await fetch(`${this.apiBase}?${params}`, {
          signal: this._ghostAbortCtrl.signal,
          headers: { 'X-Requested-With': 'XMLHttpRequest' }
        });
        this._ghostAbortCtrl = null;
        if (!resp.ok) { this._clearGhost(); return; }
        const data = await resp.json();
        if (data.next_word) {
          this._ghostWord = data.next_word;
          this._ghostMode = 'next_word';   // يُضبط بعد استلام الرد فقط
          this._renderGhost(q);
          this._showTabHint();
        } else {
          this._clearGhost();
        }
      } catch (err) {
        if (err.name !== 'AbortError') this._clearGhost();
      }
    }

    // ── رسم النص الشبحي ───────────────────────────────────────────────────────
    _renderGhost(q) {
      if (!this._ghostWord) { this.ghost.innerHTML = ''; return; }

      // نسخ خصائص textarea للمحاذاة الدقيقة
      const cs = getComputedStyle(this.textarea);
      [
        'padding','paddingTop','paddingBottom','paddingLeft','paddingRight',
        'font','fontSize','fontFamily','fontWeight','lineHeight',
        'letterSpacing','wordSpacing','borderRadius','boxSizing',
        'textAlign','direction'
      ].forEach(p => { this.ghost.style[p] = cs[p]; });

      if (this._ghostMode === 'word_complete') {
        // عرض: [النص المكتوب شفاف][لاحقة الإكمال بلون رمادي]
        this.ghost.innerHTML =
          `<span style="color:transparent">${this._escHtml(q)}</span>` +
          `<span class="ta-ghost-completion">${this._escHtml(this._ghostWord)}</span>`;
      } else {
        // عرض: [النص المكتوب شفاف][مسافة + الكلمة التالية بخط مائل رمادي]
        const spacer = q.endsWith(' ') ? '' : ' ';
        this.ghost.innerHTML =
          `<span style="color:transparent">${this._escHtml(q)}</span>` +
          `<span class="ta-ghost-nextword">${spacer}${this._escHtml(this._ghostWord)}</span>`;
      }
    }

    _clearGhost() {
      this._ghostWord = null;
      this._ghostMode = null;
      this.ghost.innerHTML = '';
      this._hideTabHint();
    }

    // ── قبول النص الشبحي (Tab) ────────────────────────────────────────────────
    _acceptGhost() {
      if (!this._ghostWord) return;
      const cur = this.textarea.value;
      if (this._ghostMode === 'word_complete') {
        // أضف اللاحقة + مسافة للانتقال للكلمة التالية
        this.textarea.value = cur + this._ghostWord + ' ';
      } else {
        // أضف الكلمة التالية مع مسافة
        this.textarea.value = (cur.endsWith(' ') ? cur : cur + ' ') + this._ghostWord + ' ';
      }
      this._clearGhost();
      this.textarea.dispatchEvent(new Event('input'));
      this._moveCursorToEnd();
      this._adjustDynamic();
    }

    // ── إظهار/إخفاء مؤشر Tab ─────────────────────────────────────────────────
    _showTabHint() {
      // موضع الإشارة يتبع اتجاه النص: RTL → يسار (نهاية النص)، LTR → يمين
      const isRTL = this.textarea.dir !== 'ltr';
      this.tabHint.style.left  = isRTL ? '8px' : 'auto';
      this.tabHint.style.right = isRTL ? 'auto' : '8px';
      this.tabHint.classList.add('visible');
    }
    _hideTabHint() {
      this.tabHint.classList.remove('visible');
    }

    // ── عرض القائمة المنسدلة ──────────────────────────────────────────────────
    _show(items, q) {
      this._active = true;
      this._selectedIdx = -1;
      this.dropdown.innerHTML = '';

      const qLower = q.toLowerCase();
      items.forEach((text, i) => {
        const li = document.createElement('li');
        li.setAttribute('role', 'option');
        li.style.cssText = [
          'padding:9px 14px; cursor:pointer; font-size:0.88rem;',
          'line-height:1.5; border-bottom:1px solid #f3ede3;',
          'color:#4a3728; transition:background .12s;',
          'display:flex; align-items:center; gap:8px;',
        ].join(' ');
        li.dataset.idx = i;

        const highlighted = this._highlight(text, qLower);
        const isLocal = HistoryStore.search(q).includes(text);
        li.innerHTML = `
          <span class="ta-icon" style="font-size:0.8rem;opacity:0.55">${isLocal ? '🕐' : '📋'}</span>
          <span class="ta-text">${highlighted}</span>
        `;

        li.addEventListener('pointerdown', e => {
          e.preventDefault();
          this._accept(text);
        });
        li.addEventListener('mouseenter', () => {
          this._selectedIdx = i;
          this._highlightItem();
        });
        this.dropdown.appendChild(li);
      });

      this.dropdown.style.display = 'block';
    }

    _hide() {
      this._active = false;
      this._selectedIdx = -1;
      this.dropdown.style.display = 'none';
    }

    _accept(text) {
      this.textarea.value = text;
      HistoryStore.save(text);
      this._hide();
      this._clearGhost();
      this.textarea.focus();
      this._moveCursorToEnd();
      this._adjustDynamic();
      if (this.onSelect) this.onSelect(text);
    }

    _move(dir) {
      const items = this.dropdown.querySelectorAll('li');
      this._selectedIdx = Math.max(-1,
        Math.min(items.length - 1, this._selectedIdx + dir));
      this._highlightItem();
    }

    _highlightItem() {
      this.dropdown.querySelectorAll('li').forEach((li, i) => {
        li.style.background = i === this._selectedIdx ? '#fef3e2' : '';
        li.style.color      = i === this._selectedIdx ? '#92400e' : '#4a3728';
      });
    }

    // ── مساعدات ───────────────────────────────────────────────────────────────
    _highlight(text, q) {
      const idx = text.toLowerCase().indexOf(q);
      if (idx === -1) return this._escHtml(text);
      return (
        this._escHtml(text.slice(0, idx)) +
        `<mark style="background:#fde68a;color:#92400e;padding:0 1px;border-radius:2px">${this._escHtml(text.slice(idx, idx + q.length))}</mark>` +
        this._escHtml(text.slice(idx + q.length))
      );
    }

    _escHtml(str) {
      return str
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
    }

    _moveCursorToEnd() {
      const len = this.textarea.value.length;
      this.textarea.setSelectionRange(len, len);
    }

    /** يُستدعى عند الحفظ الناجح لتخزين العنوان في السجل المحلي */
    static saveToHistory(title) {
      HistoryStore.save(title);
    }
  }

  // ─── تصدير عام ─────────────────────────────────────────────────────────────
  window.TitleAutocomplete = TitleAutocomplete;

  // ─── جلب كلمات DB وحقنها في القاموس الحي ──────────────────────────────────
  // يُنفَّذ مرة واحدة في الخلفية عند تحميل الصفحة.
  // الكلمات الجديدة تُكمَّل فوراً بـ Tab بمجرد استلام الاستجابة.
  (function _loadDbWords() {
    const CACHE_KEY = 'ta_dbwords_v1';
    const CACHE_TTL = 60 * 60 * 1000; // ساعة واحدة بالمللي ثانية

    // تحقق من كاش localStorage أولاً لتجنب طلب شبكة في كل صفحة
    try {
      const stored = JSON.parse(localStorage.getItem(CACHE_KEY) || 'null');
      if (stored && (Date.now() - stored.ts) < CACHE_TTL) {
        WordDict.inject(stored.ar);
        WordDict.inject(stored.en);
        return;
      }
    } catch (_) {}

    // جلب من DB في الخلفية (لا يُعيق الواجهة)
    fetch(WORDS_API, { headers: { 'X-Requested-With': 'XMLHttpRequest' } })
      .then(r => r.ok ? r.json() : null)
      .then(data => {
        if (!data) return;
        WordDict.inject(data.ar || []);
        WordDict.inject(data.en || []);
        // حفظ في كاش localStorage
        try {
          localStorage.setItem(CACHE_KEY, JSON.stringify({
            ts: Date.now(),
            ar: data.ar || [],
            en: data.en || [],
          }));
        } catch (_) {}
      })
      .catch(() => {});
  })();

})();
