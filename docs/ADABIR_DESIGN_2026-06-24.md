# تصميم ميزة «الأضابير» (مجلّدات مراسلات الأقسام) — 2026-06-24

> دراسة جدوى + خطة دمج أعدّها فريق متعدّد (4 اكتشاف · 3 تصميم · تركيب) مبنيّة على قراءة فعلية للشيفرة. **للفحص قبل التنفيذ — لم يُكتب أي كود إنتاجي بعد.**

## حكم الجدوى

جدوى عالية جداً والميزة قابلة للتنفيذ بثقة. كل البيانات المطلوبة موجودة في النموذج الحالي: "القسم" = Entity، الربط = Book.issuing_entities/receiving_entities (M2M، models.py:193-198)، محور التقسيم = Book.document_type (models.py:183) مع كتالوج جاهز في document_types.py. الميزة عرض/استعلام بحت فوق نماذج قائمة.

الحكم على قاعدة البيانات: لا حاجة لأي تغيير في قاعدة البيانات في المرحلة الأولى (صفر هجرات). تأكدت أن annotate_book_counts (entity_dedup.py:66-76) والنمط المطابق في entity_list (entities.py:74-97) جاهزان للمستوى الأول، وأن apply_entity_filter (filter_helpers.py:68-75) مع .distinct() يحل المستوى الثاني، وأن get_counter_badges (filter_helpers.py:117-145) يعطي العدّادات. فهرس document_type يُؤجَّل ويُقاس أولاً لأن GROUP BY يقع على كتب قسم واحد (نطاق ضيق) لا الجدول كله.

## تعريف «القسم/الإضبارة»

التعريف النهائي المختار: "القسم/الإضبارة" = نموذج Entity الحالي نفسه. لا كيان جديد، ولا حقل "قسم" منفصل، ولا FK جديد. الـ pk في URL = entity.pk مباشرة.

كتب القسم = اتحاد الكتب عبر العلاقتين: Q(issuing_entities__id=eid) | Q(receiving_entities__id=eid).distinct() — وهو حرفياً BookFilterEngine.apply_entity_filter (filter_helpers.py:68-75). الـ distinct إلزامي لأن كتاباً قد يربط الجهة كمُصدِرة ومستلِمة معاً.

تعريف الاتجاه داخل الإضبارة (حسم السؤال المفتوح): نعتمد عضوية الربط M2M لا Book.kind:
- "صادر من القسم" = القسم ضمن issuing_entities (entity.issued_books).
- "وارد إلى القسم" = القسم ضمن receiving_entities (entity.received_books).
المبرّر: متسق مع related_name الحالي (issued_books/received_books) ومع entity_detail، وأصح دلالياً (كتاب kind=outgoing من قسم آخر يظهر صحيحاً في تبويب "وارد" لإضبارة المستلم). لا نخلطه بـ apply_tab_filter (الذي يفلتر kind) — نعرض kind_label للكتاب دون أن يحكم انتماءه للتبويب.

معالجة الجهات الخاصة:
- المدموجة: مُستبعَدة تلقائياً عبر فلتر is_active=True (entity_dedup يضبط is_active=False وينقل روابط الكتب للأمّ، فالنسخة تظهر بعدد 0). لا معالجة merged_into خاصة لازمة.
- المعطّلة (حذف ناعم): مُستبعَدة بنفس فلتر is_active=True.
- الخارجية: تظهر كأضابير افتراضياً في المرحلة الأولى (Entity لا يميّز داخلي/خارجي بشكل موثوق). مبدّل "داخلية/خارجية" مؤجَّل للمرحلة 2 بانتظار حسم العميل.
- المحذوفة نهائياً (archived_*_names نصّي JSON على Book، models.py:203-208): ليست Entity حيّة فلا تظهر كأضابير. لا "إضبارة بلا قسم" في المرحلة الأولى.
- الأقسام ذات عدد كتب صفر: مُستبعَدة (طلب العميل صراحةً "التي لها كتب فقط").

## المعمارية

طبقة عرض مزدوجة المستوى فوق Entity + document_type، بإعادة استخدام كامل لـ BookFilterEngine ونمط Subquery المضاد للضرب الديكارتي. صفر querysets يدوية جديدة في المحرّك المشترك.

URLs (في core/urls.py بمحاذاة كتلة entities سطور 94-102، تحت بادئة books/ من lettersys/urls.py:13):
- path("dossiers/", views.dossier_list, name="dossier_list")            # المستوى 1
- path("dossiers/<int:pk>/", views.dossier_detail, name="dossier_detail") # المستوى 2
- (مرحلة 2 اختياري) path("dossiers/<int:pk>/data/", views.dossier_data, name="dossier_data")  # AJAX "عرض الكل"

Views (ملف جديد core/views/dossiers.py، يُعاد تصديرهما من core/views/__init__.py — نفس نمط entity_list/entity_detail المؤكَّد في __init__.py:54-56):
- dossier_list(request) [@staff_required]: نسخة مبسّطة من entity_list.
- dossier_detail(request, pk) [@staff_required].

إعادة استخدام BookFilterEngine (مؤكَّدة من الشيفرة):
- apply_entity_filter (filter_helpers.py:68-75) — عمود المستوى الثاني، يجمع صادر+وارد مع distinct.
- get_counter_badges (filter_helpers.py:117-145) — عدّادات الرأس بـ aggregate واحد.
- apply_search_filter / apply_all_filters — بحث وفلاتر داخل الإضبارة، صفر كود جديد.
- BookSortEngine.apply_sort — الفرز الآمن.
لا نضيف فلتر document_type إلى المحرّك في المرحلة الأولى (التقسيم طبقة values().annotate فوق النتيجة، لا فلترة في الفئة المشتركة → نتفادى اختبار انحدار للقائمة الموحّدة/التصدير).

الاستعلامات الفعّالة:
المستوى الأول (قائمة الأقسام مع أعداد صادر/وارد) — إعادة استخدام annotate_book_counts (entity_dedup.py:66-76) حرفياً:
  from core.entity_dedup import annotate_book_counts
  qs = annotate_book_counts(Entity.objects.filter(is_active=True))
  qs = qs.annotate(total_count=F('issued_count')+F('received_count')).filter(total_count__gt=0)
  qs = qs.order_by('-total_count','name')
  Paginator(qs, 24)
هذا يتفادى الضرب الديكارتي I×R الموثّق بـ~17s (entities.py:71-73 تعليق صريح). العدّ يحترم is_deleted=False (مدمج في الاستعلام الفرعي).

المستوى الثاني (كتب قسم واحد، تقسيم بالنوع + اتجاه):
  base = _visible_books(request)
  scoped = BookFilterEngine.apply_entity_filter(base, pk)          # distinct
  scoped = BookFilterEngine.apply_search_filter(scoped, q)         # بحث مجاني
  badges = BookFilterEngine.get_counter_badges(scoped)
  # رؤوس الأنواع — GROUP BY واحد DB-side:
  type_rows = scoped.values('document_type').annotate(c=Count('id', distinct=True)).order_by('-c')
  # فصل الاتجاه بالعضوية (لا kind):
  outgoing = scoped.filter(issuing_entities__id=pk)
  incoming = scoped.filter(receiving_entities__id=pk)
distinct=True إلزامي (M2M متعدد يضاعف الصفوف). كل التجميع DB-side التزاماً بقيود الذاكرة (8GB، يتجمّد تحت الحِمل).

معالجة document_type: التجميع على القيمة الفعلية في DB (لا على الكتالوج وحده) كي لا تُفقَد القيم الحرّة/القديمة (legacy_restore يكتب CLAS الخام). تطبيع عرضي عبر normalize_document_type_value، ودمج '' والقيم خارج الكتالوج تحت سلّة "متفرقة" في طبقة بايثون رقيقة فوق نتيجة GROUP BY. ترتيب العرض بـ get_document_type_options() ثم بقية الأنواع ثم "متفرقة" أخيراً.

## تدفّق البيانات (الربط/الاستدعاء/العرض)

من النقر على القسم إلى عرض الكتب المجمّعة:

1) المستخدم يفتح /books/dossiers/ ← dossier_list ← annotate_book_counts(Entity.filter(is_active=True)) + filter(total>0) + Paginator(24) ← render core/dossier_list.html: شبكة بطاقات، كل بطاقة قسم مع شارتي "صادر N"/"وارد M" ورابط لـ dossier_detail بـ entity.pk.

2) النقر على بطاقة قسم ← /books/dossiers/<pk>/ ← dossier_detail:
   - entity = get_object_or_404(Entity, pk=pk, is_active=True)
   - base = _visible_books(request) (المؤمَّن)
   - scoped = apply_entity_filter(base, pk) → كل كتب القسم صادرة+واردة، distinct
   - تطبيق ?q= (بحث) و?tab= (اتجاه اختياري) عبر apply_all_filters فوق scoped
   - badges = get_counter_badges(scoped)
   - type_rows = scoped.values('document_type').annotate(Count) → رؤوس مجموعات الأنواع
   - تطبيع بايثون: دمج '' وخارج-الكتالوج تحت "متفرقة"، ترتيب بـ get_document_type_options
   - جلب الصفوف مرة واحدة: scoped.select_related('created_by').prefetch_related('issuing_entities','receiving_entities').order_by('document_type','-date')، تجميع بايثوني (defaultdict) حسب (الاتجاه، النوع_المطبَّع)، حدّ 10/مجموعة + "عرض الكل"
   - render core/dossier_detail.html

3) العرض: تبويبا اتجاه (صادر/وارد) ← داخل كل تبويب مجموعات قابلة للطيّ لكل document_type مع badge عدد ← جدول صفوف الكتب (إعادة استخدام بنية جدول entity_detail.html). page_sidebar يعرض قائمة قفز (anchors) لمجموعات الأنواع مع عدّاداتها.

اتساق العدّ: لأن الميزة @staff_required (الكل بلا created_by) فإن annotate_book_counts (لا يعرف user) يُستعمل كما هو، فيتطابق عدّ البطاقة في المستوى الأول مع محتوى المستوى الثاني دائماً (لا "عدّ>0 ثم محتوى=0").

## مواصفة الواجهة (المستويان + التقسيم)

RTL، كسوة عنبرية/بُنّية دافئة متطابقة مع entity_list.css و book_unified (لا أزرق/بنفسجي SaaS). ألوان النظام المستقرّة: عنبري = صادر، أزرق = وارد.

المستوى 1 — templates/core/dossier_list.html (يرث base.html):
- رأس: عنوان "الأضابير" + نص فرعي "مجلّدات المراسلات لكل قسم/وحدة" (نمط رأس entity_list:49-53) + شريط بحث server-side (?q=) على اسم/رمز القسم (نمط entity_list:104-108).
- شبكة بطاقات: row g-3 → col-lg-4 col-md-6 (3/2/1 أعمدة). كل بطاقة: أيقونة bi-folder2-open، اسم القسم (رابط لـ dossier_detail) + رمزه، شارتان: "صادر N" (issued_count، عنبري + bi-arrow-up-right) و"وارد M" (received_count، أزرق + bi-arrow-down-left) + إجمالي + شارة etype. زر "فتح الإضبارة".
- ترتيب: الأكثر كتباً أولاً (total_count desc) ثم الاسم. Pagination 24/صفحة (إلزامي لقيود 8GB).
- حالة فارغة: "لا توجد أضابير بعد" / "لا قسم يطابق بحثك".
- page_sidebar: لوحة ملخّص (إجمالي الأقسام، إجمالي صادر، إجمالي وارد) + اختصارات.
- تنبيه واجهة: "قد يظهر الكتاب في أكثر من إضبارة" — ولا يُعرض مجموع أعداد الأقسام كـ"إجمالي نظام" (مضلِّل).

المستوى 2 — templates/core/dossier_detail.html:
- بطاقة رأس القسم (نمط entity_detail:56-85): اسم + رمز + شارة، وصندوق بحث داخل الإضبارة (?q=).
- شريط إحصاء سريع (4 بطاقات نمط entity_detail:88-115): إجمالي/صادر/وارد/أبرز نوع.
- البنية الأساسية (تطابق طلب العميل حرفياً: "صادرة + واردة مقسّمة حسب نوع المستند"):
  تبويبا nav-pills للاتجاه [صادر (عدد)] [وارد (عدد)] + تبويب "الكل" اختياري (نمط entity_detail:27-37).
  داخل كل تبويب: مجموعات قابلة للطيّ (accordion) واحدة لكل document_type بترتيب get_document_type_options؛ رأس المجموعة = اسم النوع المطبَّع + badge عدد. النوع الفارغ/خارج الكتالوج → مجموعة "متفرقة" أخيراً دائماً.
  جسم المجموعة: جدول صفوف الكتب بنفس أعمدة entity_detail.html (# / رقم الكتاب رابط لـ book_detail / العنوان truncatechars:60 / التاريخ d/m/Y / الجهة المقابلة كـ badges / حالة المتابعة بشارات followup_state بنفس ألوان entity_detail). حدّ 10 صفوف/مجموعة + "عرض كل (N)" (AJAX مرحلة 2).
- page_sidebar: "أنواع المستندات" كـ nav-pills روابط قفز (anchor) لكل مجموعة مع badge عدد (نمط entity_detail page_sidebar:25-37) + إجراءات (رجوع للأضابير / تصدير CSV مرحلة 2).
- حالات فارغة: قسم بلا كتب في الاتجاه ("لا كتب صادرة/واردة")، بحث بلا نتائج، مجموعة نوع فارغة لا تُعرض أصلاً.

الشريط الجانبي (templates/base.html): رابط "الأضابير" بأيقونة bi-folder2-open داخل كتلة {% if request.user.is_staff %} بمحاذاة رابط "الجهات" (base.html:124)، active state يجمع url_names: dossier_list,dossier_detail.

CSS: static/css/dossier.css بسيط يعيد استخدام متغيّرات/ألوان entity_list.css (#ff9233/#b45309 عنبري، #1e5a9e أزرق) — لا نظام تصميم جديد.

## تغييرات قاعدة البيانات

لا حاجة لأي تغيير في المرحلة الأولى (صفر هجرات).

## نقاط الدمج الدقيقة

- core/urls.py: إضافة مسارين بمحاذاة كتلة entities (سطور 94-102): dossiers/ (dossier_list) و dossiers/<int:pk>/ (dossier_detail) — تحت بادئة books/ الموروثة من lettersys/urls.py:13
- core/views/dossiers.py: ملف جديد يحوي dossier_list + dossier_detail، كلاهما @staff_required
- core/views/__init__.py: re-export لـ dossier_list و dossier_detail بنفس نمط entity_list/entity_detail المؤكَّد (سطور 54-56)
- core/views/helpers.py: استخراج helper موحّد _visible_books(request) يعيد base_qs المؤمَّن (superuser/staff ⇒ is_deleted=False، وإلا created_by=request.user) مع select_related('created_by').prefetch_related('issuing_entities','receiving_entities') — النمط مكرّر حرفياً 3 مرات (books_list.py:131-135, 259-263, 347-351)؛ يُستخدم في الأضابير ثم تُعاد توجيه النسخ القائمة إليه في دفعة منفصلة
- إعادة استخدام (بلا تعديل): core/views/filter_helpers.py::BookFilterEngine (apply_entity_filter, get_counter_badges, apply_search_filter, apply_all_filters) + BookSortEngine.apply_sort
- إعادة استخدام (بلا تعديل): core/entity_dedup.py::annotate_book_counts للمستوى الأول
- إعادة استخدام: core/document_types.py (get_document_type_options + normalize_document_type_value) لترتيب/تسمية وتطبيع مجموعات التقسيم
- templates/core/dossier_list.html و templates/core/dossier_detail.html: قالبان جديدان يرثان base.html، يعيدان استخدام بنية بطاقات entity_list.html وجدول صفوف + page_sidebar من entity_detail.html
- templates/base.html: رابط شريط جانبي جديد 'الأضابير' داخل كتلة is_staff بمحاذاة سطر 124 (الجهات)
- static/css/dossier.css: ملف جديد صغير يعيد استخدام ألوان/متغيّرات entity_list.css

## المخاطر

- document_type نص حرّ بلا قيد DB ولا فهرس (models.py:183؛ migration 0030 بلا db_index؛ غائب عن Meta.indexes 374-389): قيم قديمة (legacy_restore يكتب CLAS الخام) وفروق إملائية ('امر اداري' مقابل 'أمر إداري') تُنتج مجموعات مكرّرة. مُخفَّف بـ normalize_document_type_value + سلّة 'متفرقة'، لكنه لا يوحّد المرادفات تلقائياً — دَين بيانات للمرحلة 3.
- تسرّب صلاحيات إن نُسخ نمط entity_detail: entity_detail الحالي (entities.py:165-183) @login_required ويستخدم entity.issued_books/received_books المباشر دون created_by فيكشف كتب كل المستخدمين. يجب اشتقاق كتب المستوى الثاني من _visible_books عبر apply_entity_filter لا من related manager للجهة — وهذا يسدّ الثغرة ضمناً.
- الضرب الديكارتي M2M المزدوج: أي ضمّ issuing+receiving في استعلام واحد ينفجر (~17s موثّق في entities.py:71-73). يجب الالتزام بنمط annotate_book_counts (subquery مستقل) للمستوى الأول و.distinct للمستوى الثاني — لا ضمّ مزدوج.
- تكرار الكتاب عبر أقسام: مجموع أعداد الأقسام > إجمالي الكتب (كتاب مرتبط بعدة جهات يُحتسب في كل إضبارة). يجب توضيحه في الواجهة وعدم تقديم 'إجمالي عام' مجموعاً عبر الأقسام.
- فلترة total_count المشتقّ من Subquery تلتفّ في HAVING وقد تُبطئ على DB كبيرة. مع Pagination (24/صفحة) الأثر مقبول؛ البديل تصفية Q(issued_count__gt=0)|Q(received_count__gt=0) أو تصفية بايثونية على صفحة محدودة — قابل للقياس.
- قيود الجهاز (8GB RAM، يتجمّد تحت الحِمل): تُحتّم Pagination صارماً، تجميع DB-side (values+annotate لا Python على كامل الجدول)، وحدّ 10 صفوف/مجموعة مع 'عرض الكل' AJAX — مطبّق في التصميم.
- GROUP BY على document_type غير المفهرس: على أقسام ضخمة قد يبطؤ، لكن النطاق محصور بكتب قسم واحد (بعد apply_entity_filter) لا الجدول كله، فالأثر صغير عملياً → فهرس مؤجَّل للمرحلة 3 بعد قياس.

## أسئلة للعميل (تحتاج حسماً قبل/أثناء التنفيذ)

- سياسة الوصول: نقترح @staff_required (الأبسط والأرصن، يتسق مع entity_list ويضمن اتساق العدّ مع المحتوى). هل يوافق العميل، أم يريد إتاحتها للمستخدم العادي على كتبه فقط (يتطلب حقن created_by داخل استعلامات annotate_book_counts + اعتماد _visible_books في المستويين)؟
- تعريف 'القسم/الوحدة': هل المقصود كل Entity نشطة لها كتب (يشمل الجهات الخارجية)، أم الأقسام/الوحدات الداخلية فقط (وحدة اللجان، وحدة الإدارة)؟ إن أراد الفصل، نضيف مبدّل داخلي/خارجي في مرحلة 2 (وربما حقل is_internal_unit على Entity).
- معالجة document_type الفارغ/خارج الكتالوج: نقترح سلّة 'متفرقة' تجمع '' وكل القيم خارج الكتالوج الرسمي. هل يوافق، أم يريد عرض القيم التاريخية الحرّة (legacy CLAS) كمجموعات مستقلة بأسمائها الفعلية؟
- بنية الاتجاه + النوع: نقترح تبويبَي اتجاه (صادر/وارد) ثم تقسيم بالنوع داخل كلٍّ. هل هذا مطابق لتصوّر العميل، أم يريد دمج الصادر والوارد معاً تحت كل نوع دون تبويب اتجاه؟
- الكتاب المرتبط بعدة جهات يظهر في عدة أضابير (سلوك صحيح منطقياً، مع .distinct داخل كل إضبارة). هل هذا مقبول، أم يريد العميل قصر 'إضبارة الكتاب' على جهة واحدة (مثلاً الجهة الداخلية)؟
- هل الأضابير قراءة/تصفّح فقط في الإطلاق، أم يحتاج العميل إجراءات (تصدير CSV/PDF للإضبارة، إعادة تصنيف كتاب، نقل بين أضابير)؟

## خارطة الطريق المرحلية

- **المرحلة 0 — البنية التحتية (منخفض المخاطر)** — استخراج helper _visible_books(request) في core/views/helpers.py وإعادة توجيه النسخ الثلاث في books_list.py إليه (دفعة تنظيف مستقلة، اختبار انحداري للقائمة الموحّدة/التصدير). لا تغيير سلوك. هذا يسدّ دَين تكرار base_qs ويؤسّس مساراً مؤمَّناً واحداً للأضابير. _(الجهد: صغير (~نصف يوم))_
- **المرحلة 1 — MVP (قراءة فقط)** — core/views/dossiers.py (dossier_list + dossier_detail، @staff_required) + مساران في core/urls.py + re-export في __init__.py + قالبا dossier_list.html/dossier_detail.html + dossier.css + رابط الشريط الجانبي. المستوى 1: annotate_book_counts + filter(total>0) + Paginator(24). المستوى 2: apply_entity_filter من _visible_books + get_counter_badges + values('document_type').annotate(Count) + تطبيع/سلّة متفرقة + تبويبا اتجاه + مجموعات نوع قابلة للطيّ + بحث داخلي. صفر هجرات. _(الجهد: متوسط (~2-3 أيام))_
- **المرحلة 2 — إثراء** — 'عرض الكل' AJAX للمجموعات الكبيرة (dossier_data + _serialize_book الموجود) + تصدير الإضبارة CSV (إعادة استخدام api_export_csv الذي يقبل entity_id أصلاً، books_list.py:342-404، + عمود 'نوع المستند') + مبدّل داخلية/خارجية (etype) عند حسم العميل. إضافة apply_document_type_filter للمحرّك فقط إن لزم رابط قفز فلتري (مع اختبار انحدار). _(الجهد: متوسط)_
- **المرحلة 3 — جودة بيانات/أداء** — قياس أداء GROUP BY على document_type على بيانات حقيقية؛ عند ثبوت بطء: إضافة models.Index(fields=['is_deleted','document_type']) عبر هجرة فهرس. توحيد مرادفات document_type رجعياً (أو خريطة عرض) للقيم التاريخية الحرّة (legacy CLAS، فروق إملائية). عند حسم العميل: حقل تمييز 'وحدة داخلية' على Entity إن لزم فصل الأقسام عن الجهات الخارجية. _(الجهد: متغيّر حسب القياس)_
