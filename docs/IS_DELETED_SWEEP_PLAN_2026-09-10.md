# خريطةُ تنفيذ 7.4‑هـ — كنسُ `is_deleted=False` والحارسان البنيويّان

> **حالةُ القياس**: كلُّ رقمٍ وكلُّ `ملفّ:سطر` في هذه الوثيقة مقيسٌ على
> `main@cd29281` بتاريخ 2026‑09‑10، و**أُعيد التحقّق من الأعداد الحاكمة على
> `main@17d7178`** (آخرُ إيداعٍ لحظةَ الإغلاق): 106 / 92 / 37 / 7 — بلا تغيير.
> **وكيلٌ آخرُ يودع في الشجرة أثناء الكتابة**: `HEAD` تحرّك خمسَ مرّاتٍ خلال جلسة
> القياس (`9d164e0` ⟵ `0ea2bad` ⟵ `cd29281` ⟵ `63c32e6` ⟵ `17d7178`).
> **أعد تشغيل أوامر الجرد في §0 قبل أوّل تعديل** — أسطرُ
> `core/extraction/views/ui.py` وحدَها انزاحت 81/97/146 ⟵ 84/102/152 في نصف ساعة،
> و`templates/core/user_roles.html` فقد أربعةَ شواهدِ أدوارٍ بين قياسين متتاليين.
> **هذه وثيقةُ قراءةٍ فقط**: لم يُعدَّل أيُّ ملفٍّ في المستودع، ولم تُشغَّل اختبارات،
> ولم يُتَّصل بخادم، ولم يُقرأ قرصُ قاعدة البيانات.

---

## ملخّصٌ تنفيذيّ (8 أسطر)

1. **العدُّ الصحيح: 106 سطراً في 49 ملفّاً غيرِ اختباريّ** (98 منها للكنس في 48 ملفّاً) في المستودع كلِّه — منها **92 سطراً في 37 ملفّاً داخل `core/`** (يطابق قياس 11.13) و**14 سطراً في 12 ملفّاً** في `scripts/` و`training/`. رقمُ «73» في `core/models.py:205` و§7.4 تاريخٌ لا قياس.
2. **98 من 106 زائدةٌ حقّاً وحذفُها لا يغيّر صفّاً واحداً** — لأنّ `Book.objects` و`Attachment.objects` مديرُهما `SoftDeleteManager`، و`get_object_or_404(Model, …)` يمرّ بـ`_default_manager`، و**العلاقةُ العكسيّة `book.attachments` تتبع المديرَ الافتراضيَّ أيضاً** (مُثبَتٌ من كود جانغو 4.2.14 المثبَّت، لا من الذاكرة).
3. **فرضيّةُ الفئة (ب) في التكليف مدحوضة**: العلاقاتُ العكسيّة ليست الخطر. الخطرُ الحقيقيُّ هو **الضمّ (JOIN)**: `filter(book__is_deleted=False)` — الضمُّ لا يمرّ بمديرٍ إطلاقاً. مواضعُه **موضعان اثنان** فقط: `core/extraction/matchers/profile.py:122` و`:144`. حذفُهما يُدخل كتباً محذوفةً في تدريب بصمة الأرقام.
4. **أربعةُ مواضعَ مقصودةٌ لا تُمَسّ**، أخطرُها `core/models.py:574` — شرطُ `UniqueConstraint` في القاعدة: لمسُه **يحتاج هجرة** وسيكسر بوّابةَ 0077 (نفسُ سببِ تأجيل 8.6‑أ).
5. **قاعدةُ §7.2 الذهبيّة تُطبَّق في موضعين فقط** (`core/views/queues.py:171` و`core/dashboard_sections.py:112`). لا طابورَ مكشوفاً اليوم، لكنّ **حرزَين عرَضيَّين** يحملان الخطر: دفترُ `desk_ledger` محميٌّ بأنّ `legacy_restore` لا يكتب `department` أبداً، و`archive_service.py:213`/`custody_service.py:115` يحملان افتراضاً `qs=None` يفتح 13 ألفَ صفّ لأوّل نداءٍ بلا وسيط.
6. **حارسُ «مبنيٌّ ولا يوصله أحد» قابلٌ للتنفيذ بشقّين**: عقدُ `nav_gates` (4 مفاتيح، كلُّها موصولةٌ اليوم = حارسٌ بصفر إيجابيّاتٍ كاذبة) + بلوغُ أسماء المسارات (176 اسماً، **10 مرشّحين حقيقيّين** بعد تصفية ضجيج القياس) بقائمةِ سماحٍ مُجمَّدة.
7. **حارسُ «لا شرطَ دورٍ في قالب» يجد 7 مواضعَ اليوم** في 4 قوالب (كانت 11 قبل ساعتين — `T7.5-3` أزال 4 منها بالفعل)، وواحدٌ منها فقط (`templates/base.html:165`) بوّابةُ تنقّلٍ حقيقيّة.
8. **الحجم**: كنسٌ ميكانيكيٌّ لـ98 سطراً في 47 ملفّاً + حارسان جديدان (~140 سطرَ اختبار) + 3 اختباراتِ انحدارٍ للفئة (د). **لا هجرة، ولا تغييرَ لما يراه المستخدم**، بشرط عدم لمس §3‑ج.

---

## §0 — أوامرُ الجرد (أعد تشغيلها قبل التنفيذ)

```bash
# العدُّ الحاكم (يُقارَن بـ 106 / 92 / 37)
grep -rn "is_deleted=False" --include=*.py . | grep -v "^./.venv" | grep -v tests_ | wc -l
grep -rn "is_deleted=False" core/ --include=*.py | grep -v tests_ | wc -l
grep -rl "is_deleted=False" core/ --include=*.py | grep -v tests_ | wc -l

# الفئة (ب) — الضمُّ وحدَه (يجب أن يبقى موضعان)
grep -rn "__is_deleted" --include=*.py core/ scripts/ training/ lettersys/

# المخرجُ الصريح
grep -rn "all_objects" --include=*.py . | grep -v "^./.venv" | grep -v tests_ | wc -l   # 30 سطراً (21 كوداً)
grep -rn "is_deleted=True" --include=*.py . | grep -v "^./.venv" | grep -v tests_ | wc -l # 10

# حارسُ القوالب
grep -rnE "\{%[[:space:]]*(if|elif)[^%]*(is_staff|is_superuser|\.groups|perms\.|has_perm)" templates/ --include=*.html
```

**ما لم يُقَس ولا يُدَّعى**: أيُّ عددِ صفوفٍ في القاعدة الحيّة (لا اتّصالَ بقاعدة في هذه الجلسة)؛ زمنُ الاستعلامات قبل الكنس وبعده؛ عددُ الاختبارات الخضراء الحاليّ (لم تُشغَّل حزمة).

---

## §1 — عقدُ المديرَين: ما تراه كلُّ بوّابة (مقروءٌ من `django 4.2.14` المثبَّت)

`core/models.py:202‑219` يعرّف `SoftDeleteManager.get_queryset()` بـ`filter(is_deleted=False)`.
و`Book` (`core/models.py:531‑532`) و`Attachment` (`core/models.py:657‑658`) وحدَهما يحملانه:

```
objects     = SoftDeleteManager()   # الأوّلُ تعريفاً ⟵ هو _default_manager
all_objects = models.Manager()
```

**لا `Meta.base_manager_name` ولا `Meta.default_manager_name` في أيّ نموذجٍ في الملفّ** (مقيس: صفرُ مطابقةٍ للاسمَين في `core/models.py`).

| المسار | ما يُستعمَل فعلاً | يرى المحذوف؟ | المرجع (كودُ جانغو المثبَّت) |
|---|---|---|---|
| `Book.objects` · `Attachment.objects` | `SoftDeleteManager` | **لا** | `core/models.py:219` |
| `Book.all_objects` · `Attachment.all_objects` | `Manager` عادي | **نعم** | `core/models.py:532` · `:658` |
| `book.attachments` (علاقةٌ عكسيّة FK) | صنفُ `related_model._default_manager` = `SoftDeleteManager` | **لا** | `.venv/.../django/db/models/fields/related_descriptors.py:596‑602` |
| `entity.books…` (M2M عكسيّ/أماميّ) | صنفُ `_default_manager` كذلك | **لا** | نفسُ الملفّ `:961‑968` |
| `attachment.book` (اجتيازُ FK أماميّ) | `_base_manager` = `Manager()` مُنشأٌ تلقائيّاً | **نعم** (ولا يرمي) | `.venv/.../django/db/models/options.py:468‑490` |
| `get_object_or_404(Book, …)` | `klass._default_manager.all()` | **لا** | `.venv/.../django/shortcuts.py:58‑60` |
| `Prefetch('attachments', queryset=Attachment.objects…)` | ما يمرّره الكاتب صراحةً | حسبَ المدير الممرَّر | — |
| **`filter(book__is_deleted=…)` / `filter(attachments__isnull=…)` / `Count('attachments')`** | **لا مديرَ إطلاقاً — ضمٌّ خامّ في SQL** | **نعم** | سلوكُ ORM: المديرون لا يُطبَّقون على الضمّ |

> **الجملةُ التي تُجيب سؤالَ التكليف حرفيّاً**: العلاقاتُ العكسيّة **مُرشَّحة** — `book.attachments.all()` لا يُظهر المحذوفَ، وهو مثبَّتٌ باختبارٍ قائمٍ في `core/tests_soft_delete.py:41‑52`. أمّا `_base_manager` فغيرُ مُرشَّحٍ عمداً، ومُثبَّتٌ هو الآخر في `core/tests_soft_delete.py:54‑65`. **فالخطرُ ليس في العلاقة بل في الضمّ.**

---

## §2 — الجردُ الكامل لـ`is_deleted=False` (106 سطراً)

### 2.1 — الفئة (أ): زائدٌ آمنُ الحذف — **98 سطراً في 48 ملفّاً**

الشرطُ مكتوبٌ فوق مديرٍ يُرشّح أصلاً (أو فوق `get_object_or_404` على صنف النموذج، أو فوق علاقةٍ عكسيّة تتبع الافتراضيّ، أو داخل `Prefetch` مبنيٍّ على `Attachment.objects`). **حذفُ الشرط لا يغيّر أيَّ صفّ.**

| الملفّ | الأسطر | المديرُ في السطر نفسِه | النموذج |
|---|---|---|---|
| `core/api.py` | 166 · 214 · 312 · 443 · 447 · 454 · 455 · 465 | `Book.objects` (443/447 داخل `Subquery`+`OuterRef`) | Book |
| `core/archive_service.py` | 213 | `Book.objects` (افتراضُ `qs is None`) | Book |
| `core/attachment_sharing.py` | 104 | `book.attachments` — **علاقةٌ عكسيّة** | Attachment |
| `core/custody_service.py` | 115 | `Book.objects` (افتراضُ `qs is None`) | Book |
| `core/dashboard_sections.py` | 79 · 111 · 148 · 184 · 185 | `Book.objects` | Book |
| `core/entity_dedup.py` | 71 · 73 | `Book.objects` داخل `Subquery` | Book |
| `core/extraction/entity_profiles.py` | 69 | `Book.objects` | Book |
| `core/extraction/pipeline.py` | 1947 · 1974 | `Book.objects` | Book |
| `core/extraction/views/ui.py` | 84 · 152 | `Book.objects` | Book |
| `core/extraction/views/ui.py` | 102 | `book.attachments` — **علاقةٌ عكسيّة** | Attachment |
| `core/legacy_restore.py` | 520 · 637 · 1008 · 1261 | `Attachment.objects` | Attachment |
| `core/management/commands/backfill_letterhead_memory.py` | 41 | `Book.objects` | Book |
| `core/management/commands/eval_outgoing_number.py` | 46 | `Book.objects` | Book |
| `core/management/commands/harvest_number_strips.py` | 87 | `Book.objects` | Book |
| `core/management/commands/harvest_number_strips.py` | 107 | `b.attachments` — **علاقةٌ عكسيّة** | Attachment |
| `core/management/commands/learn_number_layouts.py` | 43 · 50 | `Book.objects` · `b.attachments` | Book · Attachment |
| `core/management/commands/models_healthcheck.py` | 157 | `Book.objects` | Book |
| `core/management/commands/notify_overdue_books.py` | 45 | `Book.objects` (وسيطٌ في نداءٍ متعدّدِ الأسطر، السطر 42) | Book |
| `core/management/commands/refresh_extraction_profiles.py` | 37 | `Book.objects` | Book |
| `core/management/commands/study_entity_layouts.py` | 92 · 106 | `Book.objects` · `b.attachments` | Book · Attachment |
| `core/messaging/api/email_endpoints.py` | 263 · 316 | `Book.objects` | Book |
| `core/models.py` | 437 | `self.attachments` — **علاقةٌ عكسيّة** داخل `Book.attachment` | Attachment |
| `core/views/api.py` | 122 | `Book.objects.select_related(…).get(…)` | Book |
| `core/views/api.py` | 204 | `get_object_or_404(Attachment.objects.select_related(…), …)` | Attachment |
| `core/views/attachments.py` | 79 | `Attachment.objects` | Attachment |
| `core/views/attachments.py` | 228 · 267 · 323 · 411 · 488 | `get_object_or_404(Attachment, …)` ⟵ `_default_manager` | Attachment |
| `core/views/books_api.py` | 496 · 557 | `Book.objects` | Book |
| `core/views/books_api.py` | 643 | `Prefetch(queryset=Attachment.objects…)` | Attachment |
| `core/views/books_api.py` | 644 · 735 · 791 | `Book.objects.…get(…)` · `get_object_or_404(Book, …)` | Book |
| `core/views/books_api.py` | 880 | `book.attachments` — **علاقةٌ عكسيّة** | Attachment |
| `core/views/books_detail.py` | 38 · 290 | `Prefetch(queryset=Attachment.objects…)` | Attachment |
| `core/views/books_detail.py` | 48 · 199 · 228 · 299 | `get_object_or_404(Book(.objects…), …)` | Book |
| `core/views/books_detail.py` | 192 | `book.attachments` — **علاقةٌ عكسيّة** | Attachment |
| `core/views/books_helpers.py` | 61 | `Book.objects` (مرشّحو كشف التكرار) | Book |
| `core/views/books_list.py` | 134 · 261 · 361 | `Book.objects` | Book |
| `core/views/comments.py` | 52 | `Book.objects.get(…)` | Book |
| `core/views/dashboard.py` | 52 · 152 | `Book.objects` | Book |
| `core/views/dashboard.py` | 689 | `Attachment.objects` | Attachment |
| `core/views/desk.py` | 36 · 68 | `Book.objects` | Book |
| `core/views/dossiers.py` | 67 | `Book.objects` | Book |
| `core/views/entities.py` | 89 · 97 | `Book.objects` داخل `Subquery` | Book |
| `core/views/lifecycle_api.py` | 258 | `Book.objects` | Book |
| `core/views/linking.py` | 55 · 127 | `Book.objects` | Book |
| `core/views/queues.py` | 123 · 169 | `Book.objects` | Book |
| `core/views/scan_settings.py` | 329 | `get_object_or_404(Attachment, …)` | Attachment |
| `core/views/signatures.py` | 30 | `get_object_or_404(Attachment, …)` | Attachment |
| `scripts/eval/build_e2e_d.py` | 65 | `Book.objects` | Book |
| `scripts/eval/build_e2e_e.py` | 59 | `Book.objects` | Book |
| `scripts/eval/date_sealed_100.py` | 37 | `Book.objects` | Book |
| `scripts/eval/e2e_number_f.py` | 41 | `Book.objects` | Book |
| `scripts/eval/entity_sealed_e100.py` | 34 | `Book.objects` | Book |
| `scripts/eval/harvest_dates.py` | 177 | `Book.objects` | Book |
| `scripts/eval/harvest_subject_boxes.py` | 98 · 129 | `Book.objects` | Book |
| `scripts/eval/harvest_t24.py` | 105 | `Book.objects` | Book |
| `scripts/verify_archmdoc_refresh.py` | 94 | `Attachment.objects` | Attachment |
| `training/handwriting/harvest/augment_dates.py` | 100 | `b.attachments` — **علاقةٌ عكسيّة** | Attachment |
| `training/handwriting/harvest/build_entity_profiles.py` | 105 | `Book.objects` | Book |
| `training/handwriting/harvest/build_lora_dataset.py` | 59 · 107 | `b.attachments` · `Book.objects` | Attachment · Book |

**توزيعُ الفئة (أ)** — مقيسٌ لا مقدَّر:

| القطع | أسطر | ملفّات |
|---|---|---|
| `core/` | **84** | **36** |
| `scripts/` | 10 | 9 |
| `training/` | 4 | 3 |
| **المجموع** | **98** | **48** |

| بحسب النموذج | أسطر | ملفّات |
|---|---|---|
| `Attachment` | **28** (منها 25 في `core/`) | 17 (منها 14 في `core/`) |
| `Book` | **70** (منها 59 في `core/`) | 40 (منها 30 في `core/`) |
| تداخلُ الملفّات (تحمل النوعين) | — | 9 (منها 8 في `core/`) |

منها **10 أسطرٍ على علاقةٍ عكسيّة**: `attachment_sharing.py:104` · `extraction/views/ui.py:102` · `harvest_number_strips.py:107` · `learn_number_layouts.py:50` · `study_entity_layouts.py:106` · `models.py:437` · `views/books_api.py:880` · `views/books_detail.py:192` · `augment_dates.py:100` · `build_lora_dataset.py:59` — **كلُّها مُرشَّحةٌ أصلاً بحسب §1 وحذفُها آمن** (وهذا هو الموضعُ الذي كانت الوثيقةُ القديمة تظنّه خطراً).

### 2.2 — الفئة (ب): **يبدو زائداً وهو حاملٌ للحمل** — موضعان

| ملفّ:سطر | السياق | النموذج | المديرُ في السطر | **لماذا يبقى** |
|---|---|---|---|---|
| `core/extraction/matchers/profile.py:122` | `through.objects.filter(book__is_deleted=False)` حيث `through = Book.issuing_entities.through` | جدولُ M2M الوسيط | مديرٌ عاديٌّ على النموذج الوسيط | **الخطر**: `through` نموذجٌ تلقائيٌّ بلا `SoftDeleteManager`، والشرطُ يعبر إلى `Book` **بضمٍّ** لا بمدير. حذفُه يُدخل أرقامَ كتبٍ محذوفةٍ في بصمة الأرقام لكلّ جهة (`_ensure_index`) — تلوّثٌ صامتٌ في التدريب لا يظهر في أيّ اختبار. **البديلُ الصحيحُ إن أُريد التوحيد**: `.filter(book__in=Book.objects.all())` — أوضحُ لا أقصر. |
| `core/extraction/matchers/profile.py:144` | `LetterheadMemory.objects.…filter(book__is_deleted=False)` | `LetterheadMemory` ⟵ ضمٌّ إلى `Book` | `LetterheadMemory.objects` (مديرٌ عاديّ) | **الخطر**: ذاكرةُ الترويسة تتعلّم من كتبٍ حُذفت — وهي المسارُ الوحيدُ الحيُّ للتعلّم في النظام (انظر ذاكرةَ «Learning Loop Plateau»). حذفُ الشرط يُعيد الكتبَ الممحوّةَ إلى التوصية بصمت. |

### 2.3 — الفئة (ج): مقصودٌ — لا يُمَسّ — 4 مواضع

| ملفّ:سطر | ماذا | الحكم |
|---|---|---|
| `core/models.py:219` | جسدُ `SoftDeleteManager.get_queryset()` | **هو القاعدة نفسُها.** لمسُه يُلغي الدفعة. |
| `core/models.py:574` | `condition=… & models.Q(is_deleted=False)` داخل `UniqueConstraint('department','our_number','kind')` | **قيدٌ في القاعدة لا استعلام.** تغييرُه يولّد هجرةً — والهجرةُ ممنوعةٌ في هذه الدفعة (نفسُ سببِ تأجيل 8.6‑أ: `AlterField` يكسر بوّابةَ 0077). ونظيرُه المُطبَّق في `core/migrations/0058:24` و`0065:55`. |
| `core/views/books_api.py:614` | `Attachment.all_objects.filter(book=book, is_deleted=True).update(is_deleted=False, …)` | **كتابةٌ لا ترشيح** — استعادةٌ من السلّة. |
| `core/views/dashboard.py:395` | `Attachment.all_objects.filter(book=book, is_deleted=True).update(is_deleted=False, …)` | نفسُه — استعادةُ كتابٍ من السلّة. |

### 2.4 — الفئة (د): مشبوهٌ يحتاج نظراً

| # | ملفّ:سطر | نوعُ الشبهة | **الخطر بجملة** |
|---|---|---|---|
| د‑1 | `core/models.py:205` | نصُّ توثيق («73 مرّة») | رقمٌ ميّتٌ يُضلّل من يقيس بعدَنا؛ **يُحدَّث إلى 106/98 لا يُحذف**. |
| د‑2 | `core/views/books_detail.py:129` | تعليقٌ يشرح عقدَ الـ`Prefetch` | يبقى: هو ما يمنع أن يُبدَّل `.all()` باستعلامٍ جديدٍ يُبطل الكاش. |
| د‑3 | `core/models.py:433` — `[a for a in cache if not a.is_deleted]` | ترشيحٌ بايثونيٌّ على كاش `_prefetched_objects_cache` | **دفاعٌ في العمق**: الكاش يُملأ بما يمرّره النادي؛ لو استعمل أحدُهم `Prefetch(queryset=Attachment.all_objects…)` صار هذا السطرُ الحارسَ الوحيد. **يبقى** (وهو خارجُ الـ106 لأنّه `not a.is_deleted` لا `is_deleted=False`). |
| د‑4 | `core/views/queues.py:181` · `core/dashboard_sections.py:119` — `live.filter(attachments__isnull=True)` | **ضمٌّ بلا مدير** | كتابٌ مرفقُه الوحيدُ محذوفٌ ناعماً **لا يظهر** في طابور «بلا مرفق» ولا في عدّاده — أي أنّ الطابورَ يُخفي عملاً بدل أن يُظهره. غيرُ مقيسٍ كم صفّاً يمسّ (لا اتّصالَ بالقاعدة). العلاج: `.exclude(pk__in=Attachment.objects.values('book_id'))`. |
| د‑5 | `core/archive_service.py:213` · `core/custody_service.py:115` | `qs = Book.objects.filter(is_deleted=False) if qs is None else qs` | الافتراضُ **بلا `source_ref=''`/`is_training=False`**. كلُّ نداءٍ حيٍّ اليوم يمرّر `live` (مقيس: `unarchived_books` يُنادى من موضعين فقط، `dashboard_sections.py:113` و`queues.py:172`، وكلاهما يمرّر `live`) — لكنّ الافتراضَ سلاحٌ مُذخَّرٌ لأوّل نداءٍ ينسى. |
| د‑6 | `core/api.py:312` · `:454` · `:455` · `:465` | إحصاءاتٌ عامّةٌ مكشوفةٌ ومكاشة | تشمل المنقولَ من الورق عمداً — **إحصاءٌ لا طابور**، فالقاعدةُ الذهبيّة لا تسري. يُبقى كما هو ويُوثَّق. |
| د‑7 | `scripts/eval/*` و`training/**` (14 سطراً) | نصوصُ تقييمٍ وحصاد | حذفُ الشرط منها لا يغيّر شيئاً، لكنّ **بعضَها يُنتج مجموعاتٍ مختومة** (`date_sealed_100` · `entity_sealed_e100` · `e2e_number_f`). أيُّ تعديلٍ فيها يجب أن يبقى **بلا أثرٍ على البذرة والترتيب** وإلّا انتقلت المجموعةُ المختومة. **الأسلمُ: لا تُمَسّ في هذه الدفعة.** |

---

## §3 — لوحةُ الأعداد

| الفئة | الأسطر | الملفّات | الحكم |
|---|---|---|---|
| (أ) زائدٌ آمنُ الحذف | **98** | 48 (36 في `core/` + 9 `scripts/` + 3 `training/`) | يُكنَس |
| (ب) حاملٌ للحمل عبر الضمّ | **2** | 1 (`core/extraction/matchers/profile.py`) | يبقى + تعليقٌ يشرح |
| (ج) مقصود | **4** | 3 (`core/models.py` · `books_api.py` · `dashboard.py`) | لا يُمَسّ |
| (د) نصٌّ/تعليق ضمن الـ106 | **2** | 2 | يُحدَّث (د‑1) / يبقى (د‑2) |
| **المجموع** | **106** | **49** | — |

> **مصالحةُ الأرقام**: 106 (المستودع) − 14 (`scripts/`+`training/`) = **92 في `core/`** في **37 ملفّاً** ⟵ يطابق قياسَ 11.13 حرفيّاً. رقمُ «73» في §7.4 وفي `core/models.py:205` من دفعةٍ سابقة.

### جردٌ مرافق — `is_deleted=True` (10 أسطرٍ غيرَ اختباريّة)

| ملفّ:سطر | المدير | الغرض | الحكم |
|---|---|---|---|
| `core/backup_verify.py:405` · `:415` | `Book.all_objects` · `Attachment.all_objects` | بصمةُ النسخة الاحتياطيّة | صحيحٌ ومقصود |
| `core/views/books_api.py:505` | داخل `.update(is_deleted=True, …)` — حذفٌ جماعيّ | كتابة | مقصود |
| `core/views/books_api.py:603` · `:613` | `Book.all_objects` · `Attachment.all_objects` | استعادةٌ من السلّة | مقصود |
| `core/views/books_list.py:340` · `:341` | `Book.all_objects` · `Attachment.all_objects` | صفحةُ السلّة | مقصود |
| `core/views/dashboard.py:387` · `:395` · `:449` | `all_objects` | استعادةُ كتابٍ/مرفق | مقصود |

### جردٌ مرافق — `all_objects` (30 سطراً غيرَ اختباريّ: 21 كوداً + 9 نصّاً)

| الملفّ | الأسطر (كوداً) | الغرض | الحكم |
|---|---|---|---|
| `core/models.py` | 532 · 658 | تعريفُ المخرج | — |
| `core/backup_verify.py` | 403 · 404 · 405 · 414 · 415 | بصمةُ النسخة (تعمّدَ رؤيةَ المحذوف) | مقصود · مُثبَّتٌ باختبار `core/tests_verify_backup.py:583` |
| `core/management/commands/purge_dev_seed_books.py` | 50 · 66 · 86 · 87 | التفريغ | **مقصودٌ بدمٍ**: `9d164e0` أصلح بالضبط أنّ الحذفَ كان بـ`objects` والمعاينةَ بـ`all_objects` |
| `core/management/commands/verify_backup.py` | 48 (نصُّ `help`) | — | — |
| `core/admin_service.py` | 187 | منعُ حذف عنقودٍ عُمِّم به كتابٌ ولو حُذف | مقصود |
| `core/views/audit.py` | 80 | سجلُّ الحركات يشمل المحذوف | مقصود |
| `core/views/books_list.py` | 340 · 341 · 346 | السلّة | مقصود |
| `core/views/books_api.py` | 603 · 613 | الاستعادة | مقصود |
| `core/views/dashboard.py` | 387 · 395 · 449 | الاستعادة | مقصود |

**صفرُ استعمالٍ خاطئٍ لـ`all_objects` وُجد.** كلُّ الـ21 مبرَّرٌ بموضعه.

---

## §4 — قاعدةُ §7.2 الذهبيّة: مَن يحملها ومَن يجب أن يحملها

**تُطبَّق اليوم في موضعين اثنين فقط**: `core/views/queues.py:171` و`core/dashboard_sections.py:112`
(كلاهما `.filter(source_ref='', is_training=False)`). وكلُّ ما عداهما يمرّ بلا الشرطين.

| ملفّ:سطر | ما هو | **يولد كاذباً بـ13 ألفاً؟** | التعليل المقيس |
|---|---|---|---|
| `core/views/queues.py:171` · `core/dashboard_sections.py:112` | طاولةُ الأرشفة ولوحتُها | — | **المرجع**: يحملانها |
| `core/views/queues.py:123` · `core/dashboard_sections.py:79` | `visible_books` لعدّاد «سرّي مفتوح» | **لا** | يُستهلَك عبر `open_here.filter(book__in=…)` — والمنقولُ من الورق لا إحالاتِ له، فيسقط بالضمّ |
| `core/views/desk.py:36` | `visible` لكشف التسليم | **لا** | يمرّ إلى `undelivered(chosen, qs=visible)` وهو مبنيٌّ على `BookReferral` |
| `core/views/desk.py:68` | **دفترُ الوارد المطبوع** (`desk_ledger`) | **لا — بالصدفة** | `_in_our_register` (`core/views/desk.py:155‑166`) يشترط `department_id=…` أو قيداً في `BookRegistration`، و`core/legacy_restore.py` **لا يذكر `department` ولا مرّة** (مقيس: صفرُ مطابقة) ⟵ المنقولُ خارجٌ بنيويّاً. **حرزٌ عرَضيٌّ لا مقصود**: أوّلُ سكربتٍ يملأ `department` بأثرٍ رجعيّ يجعل الكاتبَ يطبع 13 ألفَ سطر. **يُضاف الشرطُ هنا استباقاً.** |
| `core/archive_service.py:213` · `core/custody_service.py:115` | افتراضُ `qs is None` في `unarchived_books` / `archived_books` / `held_by` / `undelivered` | **محتملٌ — سلاحٌ مُذخَّر** | لا نداءَ حيّاً يستعمل الافتراضَ اليوم (مقيس: نداءان فقط، كلاهما يمرّر `live`). الافتراضُ يجب أن **يرفع استثناءً أو يحمل الشرطين**، لا أن يفتح الدفترَ كلَّه |
| `core/views/queues.py:181` · `core/dashboard_sections.py:119` | `attachments__isnull=True` | **لا لـ13 ألف** — لكنّه كاذبٌ بالضمّ | انظر (د‑4): المرفقُ المحذوفُ يحجب الكتابَ عن الطابور |
| `core/views/dashboard.py:52` · `core/dashboard_sections.py:148` | عدّاداتُ الدفتر (اليوم/الأسبوع/متأخّر/الكلّ) | **لا** | «كلُّ الدفتر» يجب أن يشمل الورق؛ و`today`/`week` على `date` (تواريخُ الإرث قديمة)؛ و`overdue` يشترط `due_date__isnull=False` والمنقولُ فارغُه (فخّ 7.7: `Book.save()` يرفع `is_archived` لكلّ كتابٍ بلا `due_date`) |
| `core/views/books_list.py:134` · `:261` · `:361` | الدفترُ الموحّد وAJAX والعدّادات | **لا** | **هو الدفتر**: الرقمُ الكبيرُ مقصودٌ وهو ما يقارنه الكاتبُ بورقه |
| `core/api.py:312` · `:454` · `:455` · `:465` | إحصاءٌ عامٌّ وإكمالٌ تلقائيّ | **لا** | إحصاءٌ لا طابور — وشمولُ الورق هو الصواب |
| `core/views/dossiers.py:67` · `core/dashboard_sections.py:184` · `:185` | الأضابير وعدّاداتُها | **لا** | الأضبارةُ أرشيفُ مراسلاتٍ — الورقُ جزءٌ منها بالتعريف |
| `core/views/linking.py:55` · `:127` · `core/views/lifecycle_api.py:258` | مُنتقي الربط والأفعالُ عليه | **لا** | الربطُ بكتابٍ منقولٍ مشروعٌ ومطلوب |
| `core/views/books_helpers.py:61` | مرشّحو كشف التكرار عند الإدخال | **لا** | التكرارُ يُكشَف مقابل الورق أيضاً — بل هذا غرضُه |

**الخلاصةُ الصادقة**: **لا طابورَ مكشوفاً اليوم**؛ لكنّ حرزَين من الثلاثة (`desk_ledger` و`qs=None`) **عرَضيّان لا مقصودان**، وهما بندا العمل الوحيدان في هذا القسم.

---

## §5 — الحارسان البنيويّان

### 5.1 — حارسُ «مبنيٌّ ولا يوصله أحد»

**السابقةُ التي يجب أن يمنعها**: `nav.audit` كان يُحسَب في `nav_gates()` ولا يستعمله قالبٌ — رابطُ «سجلّ الحركات» غيرَ ظاهرٍ لأحد (§7.2).

**الشقُّ الأوّل — عقدُ `nav_gates` (صفرُ إيجابيّاتٍ كاذبة، يُشحَن أوّلاً):**
- المصدر: `core/context_processors.py:67‑94` يُعيد `{'nav': {…}}`. المفاتيحُ اليوم: `desk` · `archive` · `audit` · `trash` (أربعة).
- المستهلك: `templates/base.html:117` (`nav.desk`) · `:123` (`nav.archive`) · `:137` (`nav.audit`) · `:159` (`nav.trash`). **الأربعةُ موصولةٌ اليوم — الحارسُ يخضرّ من أوّل يوم.**
- شكلُ الاختبار (`core/tests_wiring.py`):
  1. استخرج المفاتيح **من التنفيذ لا من النصّ**: نادِ `nav_gates(request)` بمستخدمٍ مديرِ نظامٍ واقرأ `result['nav'].keys()`.
  2. اقرأ كلَّ `templates/**/*.html` واجمعها في نصٍّ واحد.
  3. لكلّ مفتاح: `assertRegex(all_templates, r'nav\.' + key + r'\b', f'بوّابةٌ مبنيّةٌ بلا مستهلك: nav.{key}')`.
  4. والعكسُ أيضاً: كلُّ `nav.<x>` في القوالب يجب أن يكون مفتاحاً حقيقيّاً — وإلّا فالقالبُ يقرأ فراغاً (جانغو يُرجع سلسلةً فارغة صامتاً، وهو الشكلُ الآخرُ للعطب نفسِه).
- **الطفرة (إلزاميّة بحسب §7.6)**: أضف مؤقّتاً `'zz_probe': True` إلى القاموس ⟵ يجب أن يحمرّ البند 3؛ واحذف `{% if nav.audit %}` من `base.html:137` ⟵ يجب أن يحمرّ كذلك.

**الشقُّ الثاني — بلوغُ أسماء المسارات (يحتاج قائمةَ سماحٍ مُجمَّدة):**

قياسٌ ساكنٌ أُجري في هذه الجلسة (نصٌّ في مجلّد العمل المؤقّت، خارج المستودع):

| المقياس | العدد |
|---|---|
| أسماءُ مسارٍ معرَّفةٌ في كلّ `urls.py` | **176** |
| منها بلا `{% url %}` ولا `reverse()`/`redirect()` | **52** |
| ومنها لا يظهر آخرُ مقطعٍ من مسارها نصّاً في `.js`/`.html` | **17** |
| ومنها بعد طرح ضجيج القياس (7 مسارات `path(` مكتوبةٍ على أسطرٍ متعدّدة فلم يلتقطها التعبير: `api_archive_book` · `api_referral_action` · `api_remove_link` · `api_reopen_archive` · `attachment-merge` · `mail_hub` · `media`) | **10 مرشّحين حقيقيّين** |

**المرشّحون العشرة** (كلُّهم مؤكَّدون بـ`grep` مستقلّ: صفرُ ذكرٍ خارج `urls.py` وملفِّ العرض):

| الاسم | التعريف | ملاحظة |
|---|---|---|
| `followup_activity_report` | `core/urls.py:37` ⟵ `core/views/dashboard.py:101` + قالبٌ كامل | مسارٌ وعرضٌ وقالبٌ بلا رابطٍ واحد |
| `legacy_import` | `core/urls.py:110` ⟵ `core/views/dashboard.py:947` | صفحةُ استيرادٍ بلا مدخل |
| `entity_stats` | `core/urls.py:27` ⟵ `core/api.py:434` | API بلا مستهلك |
| `search_titles` | `core/urls.py:23` ⟵ `core/api.py:143` | API بلا مستهلك |
| `ai_extraction_statistics` | `core/extraction/api/urls.py:29` | — |
| `mail-api-stats` | `core/messaging/api/urls.py:44` | — |
| `mail-api-bulk-send` | `core/messaging/api/urls.py:40` | — |
| `email-test-smtp` | `core/messaging/api/urls.py:21` | — |
| `network-ping` | `core/urls.py:134` | جارُه `network-ping-all` موصولٌ في `templates/core/network_settings.html:751` |
| `dev_login` | `lettersys/urls.py:13` | أداةُ تطوير — تُدرَج في السماح بنيّة |

- **شكلُ الاختبار**: `KNOWN_UNWIRED = frozenset({… العشرة …})`؛ يفشل حين **يدخل اسمٌ جديدٌ** المجموعةَ (بناءٌ بلا وصل)، ويفشل أيضاً حين **يخرج** اسمٌ منها دون تحديث القائمة (نظافةُ المحاسبة).
- **الطفرة**: أضف `path('zz/', some_view, name='zz_unwired_probe')` ⟵ يحمرّ.
- **قياسٌ رافد (نظيفٌ اليوم)**: كلُّ `def x(request…)` غيرِ خاصّةٍ في 34 ملفَّ عرضٍ مذكورةٌ في `urls.py` — **صفرُ عرضٍ يتيم** (الوحيدان اللذان ظهرا، `core/views/dossiers.py:103 collect_filters` و`core/views/helpers.py:219 is_ajax`، دالّتا مساعدةٍ تأخذان `request` لا عروض). فهذا الفحصُ يُشحَن حارساً ثالثاً بصفر ضجيج.

> **صدقٌ مطلوب**: الشقُّ الثاني **ليس** فحصاً كامل الدقّة — استدعاءُ الواجهة بمسارٍ نصّيٍّ مبنيٍّ ديناميّاً (`'/books/api/' + x + '/'`) لا يلتقطه أيُّ تعبيرٍ نمطيّ. لذلك يُشحَن **بقائمة سماحٍ صريحة** لا بحكمٍ مطلق، والمرشّحون العشرةُ تُراجَع بالعين قبل تجميدهم.

### 5.2 — حارسُ «لا شرطَ دورٍ في قالب»

**الجردُ الحاليُّ الكامل (7 مواضعَ في 4 قوالب، مقيسٌ على `cd29281`)** — كانت 11 قبل ساعتين؛ `T7.5-3` أزال أربعةَ شواهدِ الأدوار الميتة من `templates/core/user_roles.html`:

| # | ملفّ:سطر | النصّ | التصنيف | الحكم المقترح |
|---|---|---|---|---|
| 1 | `templates/base.html:165` | `{% if request.user.is_staff %}` | **بوّابةُ تنقّلٍ حقيقيّة** — تُخفي «الجهات» و«المستخدمون» و«النسخ الاحتياطي» | **العطبُ الوحيدُ الجادّ**: يُستبدَل بمفتاحٍ في `nav_gates` (مثلاً `nav.admin`) مصدرُه دالّةٌ في `core/scoping.py`، تماماً كما فُعل بـ`desk`/`archive`/`audit`/`trash` |
| 2 | `templates/core/mail/hub.html:390` | `{% if request.user.is_staff %}` — تبويبُ «القوالب» | بوّابةُ تنقّل | مفتاحٌ `nav`/سياقٌ من العرض |
| 3 | `templates/core/mail/hub.html:553` | `{% if request.user.is_staff %}` — زرُّ «مزامنة الآن» | بوّابةُ فعل | يُمرَّر من العرض كـ`can_sync_mail` |
| 4 | `templates/core/mail/hub.html:641` | `{% if request.user.is_staff %}` — رابطُ إعدادات SMTP في تنبيه | بوّابةُ تنقّل | نفسُه |
| 5 | `templates/core/book_detail.html:363` | `data-can-edit="{% if comment.created_by == request.user or request.user.is_superuser %}…"` | شرطُ **ملكيّةٍ** + دور | يُحسَب في العرض (`can_edit` على كلّ تعليق) — والحارسُ الخادميُّ في `core/views/comments.py` هو الفاصل |
| 6 | `templates/core/book_detail.html:384` | نفسُ الشرط حول زرَّي التعديل/الحذف | ملكيّة + دور | نفسُه |
| 7 | `templates/core/admin_panel.html:176` | `{% if row.user.is_superuser %}` ⟵ **شارةُ «مدير نظام»** | **عرضُ حقيقةٍ لا بوّابة** | يبقى — أو يُنقَل إلى `row.is_superuser` في الباني ليصمت الحارس |

- **صيغةُ الاختبار المقترحة** (`core/tests_template_role_gates.py`):
  ```python
  PATTERN = re.compile(r"\{%\s*(?:if|elif)[^%]*\b(?:is_staff|is_superuser|has_perm|perms\.|\.groups)\b")
  ALLOWED = {  # عرضُ حقيقةٍ لا بوّابة — كلُّ سطرٍ هنا مبرَّرٌ بجملة
      ('core/admin_panel.html', 176): 'شارةُ «مدير نظام» — عرضٌ لا حراسة',
  }
  ```
  يمرّ على `settings.BASE_DIR / 'templates'` بـ`rglob('*.html')`، يجمع المطابقات، ويطرح `ALLOWED`، ثمّ `assertEqual(found, set(), رسالةٌ تُسمّي الملفَّ والسطر)`.
  **الشرطُ المقصور على `{% if %}`/`{% elif %}` مقصود**: `templates/core/book_detail.html:354` يمرّر `is_superuser` كسمةِ `data-` إلى JS — وهو ليس بوّابةَ عرضٍ في القالب. **قِيس**: التعبيرُ الواسع يجد 8 مواضع، والمقصورُ على `{% if %}` يجد 7 — والفرقُ هو ذلك السطرُ بعينه.
- **الطفرة**: أضف `{% if request.user.is_staff %}` في أيّ قالب ⟵ يحمرّ. واحذف سطراً من `ALLOWED` ⟵ يحمرّ.
- **ترتيبٌ لازم**: المواضعُ 1–4 تُصلَح **قبل** تجميد الحارس، وإلّا وُلد الحارسُ بقائمةِ سماحٍ من أربعة أعطابٍ حقيقيّة — وهو بالضبط الشكلُ الذي يجعل الحارسَ زينةً.

---

## §6 — ترتيبُ التنفيذ والمخاطر

### 6.1 — الترتيب (سبعُ خطوات، كلٌّ منها إيداعٌ مستقلّ)

| # | الخطوة | لماذا هنا | الحجم |
|---|---|---|---|
| **0** | أعد تشغيل أوامر §0 وقارن بـ106/92/37. إن اختلف، صحّح الجدولَ قبل أيّ تعديل | الشجرةُ تتحرّك (وكيلٌ آخرُ يودع) | دقائق |
| **1** | **الاختباراتُ أوّلاً**: أضف إلى `core/tests_soft_delete.py` طفراتٍ تُثبت العقدَ الذي يعتمد عليه الكنس — (أ) `Prefetch(queryset=Attachment.objects…)` يحجب المحذوف، (ب) `get_object_or_404(Attachment, pk=<محذوف>)` يرمي 404، (ج) `through.objects.filter(book__in=Book.objects.all())` ≠ `through.objects.all()` | **بلا هذه، الكنسُ إيمانٌ لا قياس** | ~60 سطراً |
| **2** | **كنسُ الفئة (أ) بحسب النموذج لا بحسب الملفّ**، داخل `core/` وحدَه: أوّلاً كلُّ مواضع `Attachment` (**25 موضعاً في 14 ملفّاً**)، ثمّ كلُّ مواضع `Book` (**59 موضعاً في 30 ملفّاً**) | الفصلُ بالنموذج يجعل أيَّ حمرةٍ تُنسَب فوراً إلى نموذجٍ واحد؛ والفصلُ بالملفّ يخلطهما | إيداعان |
| **3** | داخل كلّ نموذج: `core/views/**` ⟵ `core/**` ⟵ `core/management/**` | الأوّلُ مغطّىً باختباراتِ عرضٍ كثيفة (`tests_books_views` · `tests_secrecy` · `tests_content_gate`)، فيُكشَف العطبُ مبكراً | — |
| **4** | **لا تُمَسّ `scripts/eval/**` و`training/**`** في هذه الدفعة (14 سطراً) | فيها مولّداتُ مجموعاتٍ مختومة؛ الفائدةُ صفر والمخاطرةُ نقلُ مجموعةٍ مختومة | — |
| **5** | تعليقٌ صريحٌ فوق موضعَي الفئة (ب) في `core/extraction/matchers/profile.py:122,144`: «الضمُّ لا يمرّ بمدير — الشرطُ حاملٌ للحمل» + اختبارٌ يُطفَّر | يمنع الكانسَ القادم من «إكمال» العمل | ~25 سطراً |
| **6** | إصلاحُ (د‑4) و(د‑5) و`desk_ledger` (§4) + تحديثُ الرقم في `core/models.py:205` | ثلاثةُ أعطابٍ صغيرةٍ حقيقيّة، كلٌّ منها سطرٌ أو سطران | — |
| **7** | الحارسان (§5) — **حارسُ القوالب بعد إصلاح مواضعه 1–4** | حارسٌ يُولَد بقائمة سماحٍ من أعطابٍ = زينة | ~140 سطراً |

### 6.2 — ما سيحمرّ حتماً، وكيف يُعدَّل **بلا إرخاء**

| الاختبار | متى يحمرّ | العلاج الصحيح |
|---|---|---|
| `core/tests_soft_delete.py` (كلُّه) | إن مُسّت `core/models.py:219` أو أُضيف `Meta.base_manager_name` | **لا تُعدَّل**: هي مواصفةُ الدفعة. الحمرةُ تعني أنّ الكنسَ تجاوز حدَّه |
| `core/tests_purge_dev_seed.py:67‑83` | إن بُدِّل `all_objects` بـ`objects` في `purge_dev_seed_books` | **لا تُعدَّل**: هي انحدارُ `9d164e0` بعينه |
| `core/tests_verify_backup.py:583‑587` (`test_uses_all_objects_not_default_manager`) | إن مُسّ `core/backup_verify.py:403‑415` | لا تُعدَّل |
| `core/tests_books_views.py:1059` (`self.book.attachments.filter(is_deleted=False)`) | لن يحمرّ بالكنس، لكنّه **الاختبارُ الوحيدُ في الحزمة الذي يكرّر النمطَ المكنوس** | يُكنَس معه (اتّساقاً) — وحدَه من ملفّات `tests_` |
| `core/tests_archive_desk.py` · `core/tests_queues.py` · `core/tests_dashboard_roles.py` | عند إصلاح (د‑4) — أعدادُ طابور «بلا مرفق» تتغيّر إن كان في التجهيز مرفقٌ محذوف | **أضف حالةَ اختبارٍ** (كتابٌ مرفقُه الوحيدُ محذوفٌ ⟵ يجب أن يظهر في «بلا مرفق»)، ولا تُخفّض التوقّع |
| `core/tests_desk.py` | عند إضافة `source_ref=''`/`is_training=False` إلى `desk_ledger` | التجهيزُ ينشئ كتباً بـ`source_ref=''` افتراضاً ⟵ لا أثر. **أضف** كتاباً بـ`source_ref='IIMAIL_2025#1'` وأكّد غيابَه عن الدفتر |
| `core/tests_archive_service.py` · `core/tests_custody.py` | عند إصلاح (د‑5) إن رُفع استثناءٌ على `qs=None` | إن كسر ذلك نداءً في الاختبار، **مرّر `qs` صراحةً في الاختبار** — لا تُعِد الافتراضَ المفتوح |
| `core/tests_extraction_ui.py` · `core/tests_user_accounts.py` | ملفّان **جديدان** (أُضيفا في `0ea2bad` و`cd29281`) | خذهما في الحسبان: لم يكونا موجودَين في أيّ قياسٍ سابق |
| حارسُ القوالب الجديد | يحمرّ يومَ كتابته على 4 مواضعَ حقيقيّة | تُصلَح المواضعُ لا يُوسَّع `ALLOWED` |

**لا يوجد `assertNumQueries` في الحزمة كلِّها** (مقيس: صفرُ مطابقة) — فالكنسُ لا يكسر عدَّ استعلامات.

### 6.3 — ما **يجب ألّا يُمَسَّ** قبل ترحيل الإنتاج

1. **`core/models.py:574`** — شرطُ `UniqueConstraint`. أيُّ تعديلٍ يولّد هجرةً، والهجرةُ **تكسر بوّابةَ 0077** التي تحرس الترحيل (نفسُ سببِ تأجيل 8.6‑أ و0078). **قاطع.**
2. **`core/models.py:219`** والـ`objects`/`all_objects` — تبديلُ مديرٍ افتراضيٍّ يغيّر ما يراه **كلُّ** استعلامٍ في التطبيق دفعةً واحدة.
3. **`Meta.base_manager_name`** — لا يُضبَط أبداً: ضبطُه على `objects` يجعل `attachment.book` يرمي `DoesNotExist` لكلّ مرفقِ كتابٍ محذوف، فتنكسر السلّةُ والاستعادةُ وسجلُّ الحركات معاً (مُثبَّتٌ في `core/tests_soft_delete.py:54‑65`).
4. **`purge_dev_seed_books` و`backup_verify` و`verify_backup`** — أدواتُ الترحيل نفسُها؛ لمسُها الآن يبطل بروفةَ N18.
5. **`scripts/eval/date_sealed_100.py` · `entity_sealed_e100.py` · `e2e_number_f.py` · `build_e2e_d/e.py`** — مولّداتُ مجموعاتٍ **مختومة**؛ تغييرُ سطرٍ فيها يُخاطر بنقل المجموعة (وهو إرخاءُ بوّابةٍ بعد النظر).
6. **أيُّ شيءٍ يغيّر ما يراه المستخدمُ النهائيّ**: بحسب هذا الجرد، **كنسُ الفئة (أ) لا يغيّر بكسلاً واحداً** — لأنّ كلَّ موضعٍ فيها زائدٌ برهاناً. الذي **يُغيّر** ما يُرى هو: (د‑4) طابورُ «بلا مرفق» (يزيد)، و`desk_ledger` (لا يتغيّر اليوم — يتغيّر فقط لو مُلئت `department` لاحقاً)، وحارسُ القوالب (يغيّر ما يظهر في الشريط لغير `is_staff`). **الثلاثةُ تُوثَّق للمالك قبل الشحن.**
7. **PWA**: أيُّ تعديلِ قالبٍ في §5.2 يلزمه رفعُ `?v=` في القالب **و**`CACHE_VERSION` في `service-worker.js` (فخّ 7.7).

### 6.4 — مخاطرُ التنفيذ

| # | الخطر | الاحتمال | التخفيف |
|---|---|---|---|
| خ1 | استبدالٌ أعمى بـ`sed` يبتلع الفئتين (ب) و(ج) | **عالٍ** — النمطُ نصّيٌّ متطابق | 6 مواضعَ محرَّمةٍ تُحصَّن بتعليقِ `# noqa: soft-delete` أو تُستثنى بمسارٍ صريحٍ في السكربت؛ ومراجعةُ الفارق سطراً سطراً قبل الإيداع |
| خ2 | حذفُ الشرط يترك `filter()` فارغاً أو فاصلةً معلّقة (سطورٌ متعدّدةُ الأسطر: `notify_overdue_books.py:45` · `books_detail.py:48/299` · `books_api.py:644` · `views/api.py:204`) | **عالٍ** | هذه السبعةُ تُعدَّل يدويّاً لا بسكربت؛ و`python -m compileall core` بعد كلّ إيداع |
| خ3 | الشجرةُ تتحرّك تحت الأرجل (وكيلٌ آخر) | **قائمٌ الآن** | worktree قصيرُ المسار + `--force-with-lease=<branch>:<hash>` (بروتوكول الجلسات الثلاث) |
| خ4 | حارسُ المسارات يُشحَن بقائمةِ سماحٍ لم تُراجَع بالعين ⟵ يُجمِّد عشرةَ أعطابٍ كأنّها قرار | متوسّط | مراجعةُ العشرة بالعين وتسجيلُ سببٍ لكلٍّ منها في الاختبار نفسِه |
| خ5 | إصلاحُ (د‑4) يفجّر طابور «بلا مرفق» على الإنتاج بعددٍ لم يُقَس | **غيرُ مقيس** (لا اتّصالَ بقاعدة) | يُقاس على القاعدة المحلّيّة **قبل** الشحن؛ وإن كان كبيراً يُؤجَّل بندُه وحدَه |
| خ6 | الجهازُ 8GB وتشغيلُ الحزمة كاملةً | قائم | `--settings=lettersys.settings_test` + `$env:PYTHONIOENCODING="utf-8"` + تشغيلٌ بملفّاتٍ لا بالحزمة كلِّها، والمخرَجُ الطويلُ إلى ملفّ |

---

## §7 — تقديرُ الحجم (صادق)

| البند | ملفّات | أسطرٌ تُلمَس | ثقةُ التقدير |
|---|---|---|---|
| كنسُ الفئة (أ) — `Attachment` داخل `core/` | 14 | 25 | **مقيس** |
| كنسُ الفئة (أ) — `Book` داخل `core/` | 30 | 59 | **مقيس** |
| (تداخلُ الملفّات بين السطرين) | −8 | — | **مقيس** |
| منها متعدّدةُ الأسطر تحتاج يداً | 5 | 7 | **مقيس** |
| استثناءُ `scripts/`+`training/` من الدفعة | 12 | (14 مؤجَّلاً) | **مقيس** |
| تعليقُ الفئة (ب) | 1 | ~10 | تقدير |
| إصلاحُ (د‑1) (د‑4) (د‑5) + `desk_ledger` | 5 | ~12 | تقدير |
| إصلاحُ مواضع القوالب 1–4 (+ `core/scoping.py` + `nav_gates`) | 4 قوالب + 2 بايثون | ~40 | تقدير |
| **اختباراتٌ جديدة** | 3 ملفّات | ~230 | تقدير |
| **المجموع** | **~45 ملفّاً** | **~390 سطراً** | — |

**الاختباراتُ الجديدةُ اللازمة (ثلاثةُ ملفّات):**

| الملفّ | ماذا يُثبت | أسطر |
|---|---|---|
| إضافةٌ إلى `core/tests_soft_delete.py` | عقدُ `Prefetch` · عقدُ `get_object_or_404` · **أنّ الضمّ لا يُرشَّح** (الاختبارُ الذي يبرّر بقاء الفئة ب) | ~60 |
| `core/tests_wiring.py` | مفاتيحُ `nav_gates` ⟷ القوالب (اتّجاهان) · أسماءُ المسارات مقابل `KNOWN_UNWIRED` · صفرُ عرضٍ يتيم | ~110 |
| `core/tests_template_role_gates.py` | صفرُ شرطِ دورٍ في `{% if %}` خارج `ALLOWED` | ~60 |

**ما لا يلزمه اختبارٌ جديد**: الفئة (أ) — تغطيتُها قائمةٌ في `tests_books_views` · `tests_secrecy` · `tests_content_gate` · `tests_archive_desk` · `tests_queues` · `tests_desk` · `tests_dossiers` (86 ملفَّ اختبارٍ في `core/`، مقيسٌ اليوم).

---

## قائمةُ تحقّقٍ لمن ينفّذ

- [ ] **ق0** — `git rev-parse --short HEAD` وسجّله في رأس الإيداع. أعد أوامرَ §0 وقارن **106 / 92 / 37**. إن اختلفت: أعد بناءَ جدول §2 قبل أيّ تعديل (الأسطرُ انزاحت مرّةً أثناء كتابة هذه الوثيقة).
- [ ] **ق1** — اعمل في worktree قصيرِ المسار، وادفع بـ`--force-with-lease=<branch>:<hash>` (وكيلٌ آخرُ يودع في الشجرة).
- [ ] **ق2** — **قبل الكنس**: أضف طفراتِ العقد الثلاث إلى `core/tests_soft_delete.py` وأثبت خضرتَها.
- [ ] **ق3** — حصّن الستّةَ المحرَّمة قبل تشغيل أيّ استبدال: `core/models.py:219` · `core/models.py:574` · `core/views/books_api.py:614` · `core/views/dashboard.py:395` · `core/extraction/matchers/profile.py:122` · `:144`.
- [ ] **ق4** — اكنس `Attachment` أوّلاً (25 موضعاً في `core/`) ⟵ حزمةٌ خضراء ⟵ إيداع. ثمّ `Book` (59 في `core/`) ⟵ حزمةٌ خضراء ⟵ إيداع.
- [ ] **ق5** — عدِّل يدويّاً السبعةَ متعدّدةَ الأسطر: `notify_overdue_books.py:45` · `views/api.py:204` · `books_detail.py:48` · `:299` · `books_api.py:644` · `books_api.py:643` · `books_detail.py:38/290`. ثمّ `python -m compileall core`.
- [ ] **ق6** — **لا تلمس** `scripts/eval/**` ولا `training/**` (14 سطراً مؤجَّلاً) — سجّلها ديناً في `Merge9.md` بدل كنسها.
- [ ] **ق7** — اكتب تعليقَ الفئة (ب) فوق موضعَي `profile.py` بجملةٍ واحدة: «الضمُّ لا يمرّ بمدير».
- [ ] **ق8** — صحّح الرقمَ في `core/models.py:205` من «73» إلى «106 موضعاً في 49 ملفّاً، منها 98 زائدةٌ كُنِست في 7.4‑هـ».
- [ ] **ق9** — أصلح (د‑4): طابورُ «بلا مرفق» في `queues.py:181` و`dashboard_sections.py:119` — **وقِس الفارقَ على القاعدة المحلّيّة قبل الشحن** وسجّله.
- [ ] **ق10** — أصلح (د‑5): افتراضُ `qs=None` في `archive_service.py:213` و`custody_service.py:115` — إمّا يحمل الشرطين أو يرفع `TypeError`.
- [ ] **ق11** — أضف `source_ref=''`/`is_training=False` إلى `desk_ledger` (`core/views/desk.py:68`) **واكتب في التعليق أنّ الحرزَ الحاليَّ عرَضيّ** (`legacy_restore` لا يكتب `department`).
- [ ] **ق12** — أصلح مواضعَ القوالب 1–4 (`base.html:165` · `mail/hub.html:390/553/641`) **قبل** كتابة الحارس. ارفع `?v=` و`CACHE_VERSION` في `service-worker.js`.
- [ ] **ق13** — اشحن حارسَ `nav_gates` (يخضرّ اليوم) ثمّ حارسَ القوالب ثمّ حارسَ المسارات بقائمةِ السماح العشرة **بعد مراجعتها بالعين**.
- [ ] **ق14** — **طفِّر كلَّ حارسٍ** (§7.6): أضف `nav.zz_probe` · احذف `{% if nav.audit %}` · أضف `{% if request.user.is_staff %}` في قالب · أضف `path(name='zz_unwired_probe')`. **الأربعُ يجب أن تحمرّ**، وإلّا فالحارسُ زائف.
- [ ] **ق15** — «منجَز» = طرفٌ إلى طرفٍ في المتصفّح **بلقطةٍ تُقرأ**: افتح `/books/desk/archive/` و`/books/trash/` و`/books/<id>/` بمستخدمٍ غيرِ `is_staff` وأثبت أنّ شيئاً لم يختفِ.
- [ ] **ق16** — ألحق سطراً في «سجلّ التنفيذ» بـ`Merge9.md` (إلحاقٌ لا كتابةٌ فوق) بالأعداد الفعليّة المكنوسة والحارسَين والديون المؤجَّلة (14 سطراً في `scripts/`+`training/`).
- [ ] **ق17** — لا هجرةَ في هذه الدفعة. `python manage.py makemigrations --check --dry-run` يجب أن يقول «لا تغييرات».
