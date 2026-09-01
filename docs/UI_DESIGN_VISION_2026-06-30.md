# رؤية تطوير واجهة «الإدخال الذكي» — حزمة تسليم للمختصّين

> أنتجها فريق تصميم متعدّد العدسات (9 وكلاء). **هذه رؤية وتسليم — التنفيذ لفريق النافذة الأخرى.**
> القيود المُلزِمة: عربي RTL أصيل · جهاز 8GB (لا مكتبات ثقيلة) · هوية رصينة (لا جماليات AI عامة) · عدم كسر الكود القائم.

---

## الرؤية المُركّبة (Head of Design)

تأكّدت من الحقائق الحاسمة. هذا يغيّر جوهر الرؤية — سأبنيها على الأرض الفعلية لا على تصوّر العدسات:

**ما تحقّقت منه في الكود (لا افتراض):**
1. **`entity_matches` مُنتَج ومُهدَر جزئياً:** الخادم يبني `issuing/receiving_entity_matches[:3]` (pipeline.py:507,517) ويخزّنها في `to_dict` الداخلي (653-654) — **لكن `result_to_scan_data` (المُشكِّل الذي يقرؤه العميل فعلاً، 706-727) لا يصدّرها.** فالسلك مقطوع عند خطّ التسليم النهائي بالضبط كما ادّعت عدسة الجهات — تصدير سطرين يفتحه.
2. **Tesseract يرمي الصناديق فعلاً:** `_run_tesseract` (250-262) يقرأ `data['left/top/...']` ضمنياً عبر `image_to_data` ويبني الأسطر منها، ثم `extract()` يُرجع `'details': None` (288). الصناديق تُحسب وتُرمى — عدسة doc-intel صادقة، لكن استعادتها **ليست سطراً واحداً** بل تتطلب بناء قائمة `details` + تمريرها عبر `result_to_scan_data` (سلك ثانٍ مقطوع، أطول). هذا يضع الخيط/العدسة/انقر-الكلمة في مرحلة لاحقة لا الرائدة.

الأرض واضحة. إليك الرؤية.

---

# رؤية التصميم — واجهة «الإدخال الذكي»
## من «نموذج يُملأ» إلى «آلة تُصادِق»

---

## ١. الرؤية الشمالية (North Star)

> **«الآلة تقرأ. أنت تُصادِق. النظام يتعلّم — وكلّ ذلك يُرى.»**

واجهة الإدخال الذكي ليست استمارة تُملأ، بل **طاولة تصديق حكومية**: تضع الآلة قراءتها أمام الموظّف موسومةً بيقينها (ثقة على كلّ حقل)، فيمرّ الموظّف على مواطن الشكّ وحدها — لا على كلّ حقل — يُصادق بضغطة، فتتحوّل قراءة الآلة إلى **يقين بشري موقّع بلونه**، ويلتقط النظام كلّ تصحيح كتعليمٍ مرئيّ محترَم. لغة واحدة، محور لوني واحد (**تركوازي حكومي رصين** يتقاعد أمامه البنفسجي العام)، حركة واحدة هادفة اتّجاهية (من يمين الآلة نحو تصديق الإنسان)، صفر ابتذال «ذكاء اصطناعي». الرصانة هي الفخامة؛ والوضوح هو الاحترام.

**المبادئ الأربعة الحاكمة:**
1. **الثقة خاصيّة فيزيائية للحقل، لا شارة معلّقة** — تُقرأ بالمسح المحيطي لا بقراءة رقم.
2. **المراجعة موجَّهة لا استكشافية** — النظام يقودك للأضعف، يتخطّى المؤكَّد.
3. **التعلّم مرئيّ ومحترَم** — كلّ تصحيح شهادة تعليم رصينة، لا كونفيتي.
4. **محور واحد للّون والحركة** — تركوازي = يقين، والحركة تسير باتّجاه واحد فقط.

---

## ٢. أفضل ٦ أفكار مختارة (الأعلى إبهاراً × الجدوى)

مرتّبة حسب أولوية التنفيذ. كلّها CSS-first، صفر مكتبات، تحترم `prefers-reduced-motion`، خفيفة على 8GB.

| # | الفكرة | العدسة | لماذا اختِيرت | الجدوى |
|---|--------|--------|----------------|--------|
| **١** | **حافّة الثقة + التلاشي بالّمس** (`conf-ledge` / provenance edge) | spatial + confidence + learning | **حجر الأساس.** تحوّل الثقة من شارة على ٣ حقول إلى حافّة فيزيائية على كلّ حقل، وتُطفأ باللمس فتصير القيمة «يقيناً بشرياً» تركوازياً. تصلح — كأثر جانبي معماري — أخطر اختناق موثَّق (ازدواج `_fillExtractionFields`/`applyExtractionResult`) لأنها تفرض نقطة ربط واحدة `setFieldConfidence`. | عالية جداً. CSS + دالة واحدة. البيانات (`*_confidence`) مُصدَّرة أصلاً في `result_to_scan_data`. |
| **٢** | **مسار الثقة** (Confidence Rail + `Alt+↑/↓`) | power-flow | يحوّل الثقة إلى **بنية تنقّل**: عمود عُقد ملوّنة يقفز فوق الأخضر ويقف على الأحمر/الكهرماني، مع عدّاد «٢ يحتاج مراجعة». يجعل `_focusFirstReviewField` (يقفز مرّة ويختفي) بوصلةً دائمة. | عالية. يبني على `getNavigableFieldIds()` القائمة + يشارك `data-conf` من الفكرة ١. |
| **٣** | **بطاقة الترشيح** (Candidate Ballot: top-3 بأشرطة TF-IDF + اختيار بالرقم) | entity | **توصيل سلك مقطوع محقّق:** الخادم يبني top-3 بدرجات ويهدرها عند `result_to_scan_data`. تصدير سطرين + بطاقة قرار (شريط تشابه لكل مرشّح + `Alt+1/2/3`) + **فجوة الثقة** («متقاربان — راجِع» إذا < ٨ نقاط). تُلغي الملء الصامت الخطر عند `blur`. | عالية بعد سطرَي التصدير. تنقل كلّ الـinline إلى CSS. |
| **٤** | **أثر المُصحِّح** (Correction Ledger: حبّة تعلّم في شريط الإجراءات) | learning | يجعل حلقة الالتقاط الصامتة **مرئية ومحترمة**: حبّة تركوازية «تعلّم النظام من ٣ تصحيحات» تميّز تصحيحاً/إضافةً/لا-تغيير، وتُصفَّر عند `smartClearAndStay` (حارس ضدّ تلوّث `scan_token`). | عالية. عنصر DOM واحد + `Map` — يعيد استخدام `_origExtracted` من الفكرة ١. |
| **٥** | **صدى التعلّم عبر الجلسة** (Growth Ledger في رأس الصفحة) | learning | يرفع البصر: شريحة `sessionStorage` «علّمت النظام ١٧ مثالاً هذه الجلسة» + عتبات رصينة (٥/١٠/٢٥). يمنح كرامةً للعمل الروتيني دون تحويله لعبة. | عالية. `sessionStorage` + عنصر واحد. يُغذّى من عدّاد الفكرة ٤. |
| **٦** | **الخيط + انقر-الكلمة** (Provenance Thread + Tap-to-fill) | doc-intel + spatial | **الطموح البعيد:** خيط SVG يربط الحقل بمصدره في الورقة، ونقرة على كلمة OCR تملأ الحقل. أعلى إبهاراً على الإطلاق — لكنه يتطلّب استعادة `details` من Tesseract + تمريرها عبر `result_to_scan_data` (سلك أطول). لذا يأتي أخيراً كتتويج. | متوسّطة. يتطلّب بناء `details` + عقد بيانات نسبي (0-1). لا مكتبات مع ذلك. |

**ما استُبعد ولماذا:** العدسة/الـsprite (فكرة جميلة لكنها تضاعف بيانات الصور المكانية دون عائد يفوق الخيط)؛ «هل تقصد؟» و«الإضافة السلسة» (ممتازتان لكنهما توسيع لا تأسيس — تنتظران استقرار البطاقة). الجسر (bridge) يُدمج ضمنياً في الخيط لاحقاً بدل مسارَين متوازيين.

---

## ٣. الميزة الرائدة (Flagship)

### 🏴 «حافّة الثقة» — Confidence Ledge + التلاشي بالّمس

**ما هي:** حافّة عمودية رفيعة (4px) على الحدّ الابتدائي لكلّ حقل (يمين الـ`input` في RTL) بلون = مستوى ثقة OCR: أخضر واثق / كهرماني تحقّق / أحمر راجِع. لحظة يلمس الموظّف الحقل ويعدّله، تتلاشى الحافّة الملوّنة وتُستبدل بلون **تركوازي «مُصادَق بشرياً» `#0f766e`**. الشاشة تتحوّل تدريجياً من مبعثرة الألوان إلى عمود تركوازي هادئ = «انتهت المراجعة».

**لماذا هي الرائدة بالتحديد:**
1. **أعلى أثر بصري بأدنى مخاطرة:** البيانات (`*_confidence`) مُصدَّرة أصلاً في `result_to_scan_data` — لا تعديل خادمي إطلاقاً.
2. **تصلح أخطر اختناق موثَّق كأثر جانبي:** توحيد ملء الحقول خلف `setFieldConfidence` واحدة يُشعل الثقة في **مسار المسح** (حالة الاستخدام الأساسية) الذي يعمل اليوم بلا شارات ثقة.
3. **تؤسّس البنية التحتية للأفكار ٢/٤/٥/٦:** `data-conf` + `_origExtracted` هي المصدر الواحد الذي تقتات منه بقيّة المنظومة.
4. **تُجسّد الرؤية الشمالية حرفياً:** «الآلة تقرأ (لون OCR)، أنت تُصادِق (تلاشٍ تركوازي)».

**الرسم الملموس (RTL، خفيف، لا يكسر القائم):**

الخطوة الحاسمة أولاً — **توحيد المسارين** خلف نقطة ربط واحدة تُستدعى من `_fillExtractionFields` و`applyExtractionResult` معاً:

```js
// نقطة الربط الوحيدة — تعمل في مساري المسح والرفع معاً (يصلح ازدواج المسار)
setFieldConfidence(fieldId, score){
  const g = document.getElementById(fieldId)?.closest('.form-group-smart');
  if(!g) return;
  g.dataset.conf = score>=0.85 ? 'high' : score>=0.65 ? 'medium' : 'low';
  g.dataset.machineConf = score;                 // يُغذّي مسار الثقة (فكرة ٢)
  (this._origExtracted ||= {})[fieldId] =        // يُغذّي أثر المُصحِّح (فكرة ٤)
    { value: (document.getElementById(fieldId)?.value || '').trim(), extracted: true };
}
// التلاشي بالّمس — سطر واحد داخل handleFieldInput الموجود
markHumanConfirmed(fieldId){
  const g = document.getElementById(fieldId)?.closest('.form-group-smart');
  if(g && g.dataset.conf !== 'human') g.dataset.conf = 'human';
}
```

```css
.form-group-smart{ position:relative; }
.form-group-smart::before{                        /* الحافّة — بداية RTL (يمين) */
  content:""; position:absolute; inset-block:32px 12px; inset-inline-start:0;
  inline-size:4px; border-radius:4px; background:var(--edge,transparent);
  transform-origin:bottom; transition:background .4s cubic-bezier(.4,0,.2,1), transform .4s;
}
.form-group-smart[data-conf="high"]  { --edge:#16a34a; }
.form-group-smart[data-conf="medium"]{ --edge:#d97706; }
.form-group-smart[data-conf="low"]   { --edge:#dc2626; }
.form-group-smart[data-conf="low"] .form-control-smart{ background:rgba(220,38,38,.03); }
.form-group-smart[data-conf="human"] { --edge:#0f766e; }   /* اليقين البشري — تركوازي */
@media (prefers-reduced-motion:reduce){ .form-group-smart::before{ transition:none; } }
```

**التكلفة على 8GB:** صفر مكتبات، صفر صور، صفر canvas، صفر `backdrop-filter`. حافّة CSS واحدة لكلّ حقل + دالتان قصيرتان. لا إزاحة تخطيط (`::before` مطلق). يحترم `prefers-reduced-motion`.

**عقد عدم الكسر:** لا نلمس `updateConfidenceBadge` القائمة (تبقى تعمل)؛ نضيف `setFieldConfidence` بجانبها ونستدعيها من نقطتَي الملء. الشارات القديمة تتعايش حتى نقرّر تقاعدها في مرحلة لاحقة — لا تغيير كاسر في الدفعة الأولى.

---

## ٤. خطة المراحل (رائدة → توسّع)

**المرحلة ٠ — الأساس المعماري (شرط مسبق، ½ يوم):**
توحيد `_fillExtractionFields` + `applyExtractionResult` خلف `setFieldConfidence`/`_origExtracted`. هذا وحده يصلح أخطر اختناق وظيفي (المسار الرئيسي بلا ثقة/بلا تفعيل حفظ). **لا فكرة بصرية تُنشر قبله** وإلا ماتت في مسار المسح.

**المرحلة ١ — الرائدة (يوم):**
حافّة الثقة + التلاشي بالّمس (الفكرة ١). أوّل تحوّل تركوازي مرئي = أوّل تجسيد للرؤية الشمالية. تُبهر الفريق فوراً بأقلّ مخاطرة.

**المرحلة ٢ — بوصلة المراجعة (يوم):**
مسار الثقة + `Alt+↑/↓` + عدّاد «يحتاج مراجعة» (الفكرة ٢). يعيد استخدام `data-conf`؛ يحوّل الثقة إلى تنقّل.

**المرحلة ٣ — توصيل السلك المقطوع (يوم-يومان):**
تصدير `issuing/receiving_entity_matches` في `result_to_scan_data` (سطران) + بطاقة الترشيح بأشرطة TF-IDF + اختيار بالرقم + فجوة الثقة، وإلغاء الملء الصامت الخطر (الفكرة ٣). ينقل كلّ الـinline إلى CSS.

**المرحلة ٤ — إظهار حلقة التعلّم (يوم):**
أثر المُصحِّح (فكرة ٤) + صدى الجلسة (فكرة ٥). يعيدان استخدام `_origExtracted` والعدّاد؛ يجعلان الميزة المميِّزة مرئية محترمة، مع حارس تلوّث `scan_token`.

**المرحلة ٥ — التتويج البعيد (٢-٣ أيام):**
استعادة `details` من Tesseract + تمريرها عبر `result_to_scan_data` بعقد نسبي `[{text,confidence,box}]` → الخيط (provenance thread) + انقر-الكلمة-لتملأ (فكرة ٦). أعلى إبهار، يُبنى على عقد بيانات تثبته المراحل السابقة.

**الخيط الجامع:** كلّ مرحلة تُصلح دَيْناً تقنياً موثَّقاً بينما تضيف بهجة — ازدواج المسار (م٠/١)، `_focusFirstReviewField` الأعمى (م٢)، سلك entity_matches المقطوع + الملء الصامت (م٣)، `scan_token` غير المُصفَّر (م٤). **الهوية تتوحّد تدريجياً:** التركوازي يتسلّل كلون «اليقين البشري» من المرحلة ١، فيبدأ تقاعُد البنفسجي العام عضوياً لا بقرار فوقيّ — حتى تصير الواجهة كلّها بلغة لونية واحدة رصينة تليق بمراسلات حكومية.


---

## ملحق: العدسات التصميمية الستّ (تفصيل)


### عدسة 1 — الثقة الحيّة

ممتاز. الأرض الآن واضحة تماماً. البنية الحالية: `label-with-confidence` (label + شارة نسبة مئوية جامدة، تظهر بجانب 3 حقول فقط)، `form-control-smart` بحدود `#e2e8f0` وتركيز بنفسجي، وعتبات `high:0.85 / medium:0.65`. الشارة مجرّد pill رقمي — الحقل نفسه لا «يعرف» ثقته.

الآن أُنتج أفكاري ضمن عدسة **الثقة الحيّة**.

---

# ثلاث أفكار — عدسة «الثقة الحيّة» (Live Confidence)

الأطروحة المركزية: الثقة اليوم **رقم يُقرأ**. يجب أن تصير **حرارة تُحَسّ في الحقل نفسه**، تُوجّه العين تلقائياً لأضعف نقطة، وتتلاشى تدريجياً كلما لمَسها الإنسان — فتتحوّل شاشة المراجعة من «افحص كل شيء» إلى «اطمئن، وأصلِح هذين فقط».

الأفكار تشترك في محور لوني واحد (تقاعُد النسبة المئوية المجرّدة لصالح إشارة على الحقل)، وكلها CSS-first خفيفة تحترم `prefers-reduced-motion` وجهاز 8GB.

---

## الفكرة 1 — «الحافّة الواثقة» (The Confidence Edge) + التلاشي بالّمس

### الوصف البصري الدقيق
بدل شارة النسبة المئوية الطافية، تُحقَن الثقة في **الحدّ اليميني للحقل** (بداية القراءة في RTL) كشريط عمودي رفيع (3px) بتدرّج لوني حَيّ:
- ثقة عالية (≥0.85): الحافّة خضراء صلبة `#16a34a`، هادئة، بلا حركة.
- ثقة متوسطة (0.65–0.85): الحافّة كهرمانية `#d97706`، مع **تدرّج خفيف متحرّك بطيء** (shimmer عمودي 3ث) يقول «راجعني».
- ثقة منخفضة (<0.65): الحافّة حمراء `#dc2626` + الحقل بأكمله يكتسب خلفية حمراء شفّافة جداً (`rgba(220,38,38,.03)`) ونبضة واحدة عند الظهور فقط (لا نبض دائم — رصانة).

**اللمسة المُبهِرة — التلاشي بالّمس (Touch-to-earn):** لحظة يركّز المستخدم الحقل ويعدّله (`input`)، تتحوّل الحافّة الملوّنة إلى **تركوازي «مُؤكَّد بشرياً» `#0f766e`** بانتقال 400ms، وتظهر أيقونة صغيرة (check) مكان الشارة. الرسالة الضمنية: «هذا الحقل لم يعد ظنّ الآلة — صار يقينك». الشاشة تتحوّل تدريجياً من مبعثرة الألوان إلى صفّ تركوازي هادئ = «انتهت المراجعة».

فوق الحقول، «مقياس نضج» صغير في رأس القسم: `▓▓▓░░ 3/5 مؤكّد` يمتلئ تركوازياً مع كل حقل تلمسه.

### لماذا تُبهر
الفريق يفكّر في الثقة كـ «عرض قيمة». هذه الفكرة تقلبها إلى **آلية سلوكية**: الثقة ليست معلومة، بل **دَيْن بصري يُسدَّد باللمس**. لا أحد يبني «earned trust» — تحويل فعل التصحيح إلى مكافأة لونية فورية يستثمر حلقة الالتقاط التدريبي ضمنياً (كل تحوّل تركوازي = مثال تدريب جديد). وهي تحلّ اختناقاً موثّقاً: تعطّل الثقة في مسار المسح — لأن الحافّة تُقاد من `data-confidence` على الحقل، فتعمل في كلا مساري الملء بسطر واحد مشترك.

### رسم التنفيذ
```css
/* الحقل حاوٍ للحافّة عبر متغيّر واحد */
.form-control-smart { position: relative; --edge: transparent; }
.form-group-smart { position: relative; }
.form-group-smart::before {          /* الحافّة اليمنى (بداية RTL) */
  content: ""; position: absolute; top: 34px; bottom: 14px; right: 0;
  width: 3px; border-radius: 3px; background: var(--edge, transparent);
  transition: background .4s cubic-bezier(.4,0,.2,1);
}
.form-group-smart[data-conf="high"]   { --edge: #16a34a; }
.form-group-smart[data-conf="medium"] { --edge: #d97706; }
.form-group-smart[data-conf="low"]    { --edge: #dc2626; }
.form-group-smart[data-conf="low"] .form-control-smart { background: rgba(220,38,38,.03); }
/* مُؤكَّد بشرياً */
.form-group-smart[data-conf="human"]  { --edge: #0f766e; }
.form-group-smart[data-conf="medium"]::before {
  background: linear-gradient(#d97706, #f0b45e, #d97706);
  background-size: 100% 200%; animation: edgeShimmer 3s ease-in-out infinite;
}
@keyframes edgeShimmer { 0%,100%{background-position:0 0} 50%{background-position:0 100%} }
@media (prefers-reduced-motion: reduce){ .form-group-smart::before{animation:none!important} }
```
```js
// نقطة ربط واحدة تعمل لكلا مساري الملء (ب و ج) — يحلّ اختناق المسح
setFieldConfidence(fieldId, conf){
  const g = document.getElementById(fieldId)?.closest('.form-group-smart');
  if(!g) return;
  g.dataset.conf = conf>=0.85?'high': conf>=0.65?'medium':'low';
  g.dataset.machineConf = conf;            // نحفظ الأصل للفرز
}
// التلاشي بالّمس: يُستدعى من handleFieldInput الموجود أصلاً
markHumanConfirmed(fieldId){
  const g = document.getElementById(fieldId)?.closest('.form-group-smart');
  if(g && g.dataset.conf!=='human'){ g.dataset.conf='human'; this._bumpMaturity(); }
}
```
تُستدعى `setFieldConfidence` من **كلٍّ** من `_fillExtractionFields` و`applyExtractionResult` (تصحيح الاختناق #1)، و`markHumanConfirmed` تُضاف سطراً واحداً داخل `handleFieldInput` الموجود.

---

## الفكرة 2 — «مسار المراجعة» (Review Rail / Triage Comb) — سلّم أولويات جانبي حيّ

### الوصف البصري الدقيق
شريط عمودي رفيع (6px) ملتصق بالحافّة اليمنى للوحة النموذج (`position:sticky`)، مقسوم إلى **أسنان صغيرة** — سنّ لكل حقل قابل للاستخراج، **مرتّبة تنازلياً بالثقة** (الأضعف أعلى). كل سنّ نقطة/شرطة ملوّنة بحالة الحقل. هذا «مِشط فرز» (triage comb) يعطي المستخدم في لمحة واحدة: «كم حقلاً يحتاجني، وأين».

- عند الاستخراج: تتحرّك الأسنان بترتيب صاعد للثقة مع انزلاق دخول متتالٍ (stagger 40ms) — أضعف حقل يستقرّ في القمة.
- النقر على سنّ → `scrollIntoView` ناعم + وميض هالة (halo) حول الحقل الهدف 600ms.
- زر عائم صغير أسفل المشط: **«التالي للمراجعة ↑»** (`Alt+↑`) يقفز من أضعف حقل إلى الذي يليه ثقةً — يحوّل المراجعة إلى «مسار موجَّه» بدل بحث بصري.
- كلما أُكِّد حقل (لمسة) تتحوّل سنّه لتركوازي وتنزلق لأسفل المشط (المؤكّدات تتجمّع في القاع). المشط «يُفرَّغ من الأعلى» = تقدّم ملموس.

### لماذا تُبهر
هذا يترجم `_focusFirstReviewField` (الموجود لكن الأعمى — يقفز مرة واحدة فقط ثم يختفي) إلى **بوصلة دائمة مرئية**. الجديد: ترتيب الحقول بصرياً حسب الثقة **مستقلٌّ عن ترتيبها في النموذج**. لا أحد يربط «فرز الثقة» بعنصر تنقّل. المشط يجيب فوراً على السؤال الوحيد المهمّ في شاشة استخراج: **«أين أراجع؟»** — وهو خفيف جداً (عناصر `<i>` صغيرة، صفر صور).

### رسم التنفيذ
```html
<nav class="review-rail" id="reviewRail" aria-label="مسار المراجعة"></nav>
```
```css
.review-rail{ position:sticky; top:12px; right:2px; width:6px; display:flex;
  flex-direction:column; gap:4px; float:right; height:min-content; }
.rail-tooth{ width:6px; height:14px; border-radius:3px; cursor:pointer;
  background:#cbd5e1; transition:background .3s, transform .2s, height .3s; }
.rail-tooth[data-c="low"]{ background:#dc2626; height:20px; }
.rail-tooth[data-c="medium"]{ background:#d97706; }
.rail-tooth[data-c="high"]{ background:#16a34a; }
.rail-tooth[data-c="human"]{ background:#0f766e; opacity:.6; }
.rail-tooth:hover{ transform:scaleX(2.2); }
.field-halo{ animation:halo .6s ease-out; }
@keyframes halo{ from{box-shadow:0 0 0 0 rgba(15,118,110,.5)} to{box-shadow:0 0 0 12px rgba(15,118,110,0)} }
```
```js
buildReviewRail(){                       // بعد الاستخراج
  const rail = document.getElementById('reviewRail'); rail.innerHTML='';
  const fields = [...document.querySelectorAll('.form-group-smart[data-machine-conf]')]
    .sort((a,b)=> a.dataset.machineConf - b.dataset.machineConf);   // أضعف أولاً
  fields.forEach((g,i)=>{
    const t=document.createElement('i'); t.className='rail-tooth';
    t.dataset.c=g.dataset.conf; t.style.animationDelay=`${i*40}ms`;
    t.onclick=()=>{ g.scrollIntoView({behavior:'smooth',block:'center'});
      g.classList.add('field-halo'); setTimeout(()=>g.classList.remove('field-halo'),600);
      g.querySelector('.form-control-smart')?.focus(); };
    rail.appendChild(t);
  });
}
jumpNextReview(){ /* أول tooth غير human من الأعلى → focus */ }
```
يعيد استخدام `data-conf`/`data-machine-conf` من الفكرة 1 — الفكرتان تتقاسمان نفس مصدر الحقيقة (تكامل لا تكرار).

---

## الفكرة 3 — «همسة الجهة الواثقة» (TF-IDF Confidence Whisper) — ثقة الربط تُرى قبل الاختيار

### الوصف البصري الدقيق
تستثمر السياق المُهدَر: TF-IDF يعطي top-3 جهات بدرجات تشابه. بدل الملء التلقائي الصامت عند `blur` (الاختناق #4 الخطير في سياق حكومي)، نقلب المنطق: حقل الجهة منخفض الثقة يعرض **«همسة»** تحته — بطاقة صغيرة بثلاث شرائح (top-3) لكل شريحة **قوس ثقة دائري مصغّر** (conic-gradient، صفر SVG):
- الأعلى تشابهاً: قوس تركوازي ممتلئ + «أقرب تطابق» + مفتاح `[Enter]`.
- الثاني/الثالث: أقواس أبهت + `[1]`/`[2]`.
- إن كانت أعلى درجة عالية جداً (≥0.9) والحقل فارغاً: الشريحة الأولى **تتوهّج تركوازياً وتقترح** لكن **لا تملأ حتى Enter** — أمان الحسم البشري.

القوس نفسه هو «مقياس ثقة الربط»: كلما امتلأ الحلقة، ازداد يقين المطابقة. عند الاختيار، الوسم يطير للحقل ويومض تركوازياً (نفس لغة «مُؤكَّد بشرياً») — فتتّحد لغة ثقة الحقل مع لغة ثقة الربط.

### لماذا تُبهر
تحوّل درجة TF-IDF المجرّدة (رقم مخفيّ في JS) إلى **لغة بصرية موحّدة مع ثقة الحقل** — القوس الدائري «يتكلّم» نفس لهجة الحافّة العمودية. الأجرأ: **تعطيل الملء التلقائي الخطير** واستبداله بـ «اقتراح واثق يُحسَم بضغطة» — أمان حكومي + سرعة. وكل ذلك بـ conic-gradient صرف (لا SVG، لا مكتبة رسم) — مثالي لـ 8GB. يحلّ أيضاً الاختناق #9 (أنماط inline) بنقل كل شيء لـ CSS.

### رسم التنفيذ
```css
.entity-whisper{ display:flex; flex-direction:column; gap:6px; margin-top:6px; }
.whisper-item{ display:flex; align-items:center; gap:10px; padding:8px 12px;
  border:1px solid #e2e8f0; border-radius:10px; cursor:pointer; transition:all .18s;
  background:#fafbfc; }
.whisper-item:hover, .whisper-item.is-top{ border-color:#0f766e; background:#f0fdfa; }
.whisper-item.is-top{ box-shadow:0 0 0 3px rgba(15,118,110,.08); }
.sim-arc{ width:26px; height:26px; border-radius:50%; flex:none;
  /* --p نسبة التشابه 0..100 */
  background:conic-gradient(#0f766e calc(var(--p)*1%), #e2e8f0 0);
  -webkit-mask:radial-gradient(circle 8px, transparent 98%, #000 100%); }
.whisper-key{ margin-inline-start:auto; font-size:.7rem; color:#64748b;
  border:1px solid #cbd5e1; border-radius:5px; padding:1px 6px; }
```
```js
showEntityWhisper(fieldId, matches){     // matches: [{name,code,score}] من TF-IDF
  const box = document.getElementById(fieldId+'Whisper'); box.innerHTML='';
  matches.slice(0,3).forEach((m,i)=>{
    const p = Math.round(m.score*100);
    const el = document.createElement('div');
    el.className = 'whisper-item'+(i===0?' is-top':'');
    el.innerHTML = `<span class="sim-arc" style="--p:${p}"></span>
      <span class="w-name">${m.name}</span><span class="w-code">${m.code}</span>
      <span class="whisper-key">${i===0?'Enter':i}</span>`;
    el.onclick = ()=> this.commitEntity(fieldId, m);   // حسم صريح، لا blur صامت
    box.appendChild(el);
  });
}
// استبدال ملء blur التلقائي: عند blur نعرض الهمسة بدل الحقن الصامت
```

---

## كيف تتضافر الثلاث (منظومة واحدة، لا زخارف متفرّقة)
- **مصدر حقيقة واحد:** `data-conf` + `data-machine-conf` على `.form-group-smart` يغذّي الحافّة (1)، المشط (2)، وقوس الجهة (3).
- **لغة لونية واحدة:** أحمر=راجعني، كهرماني=تحقّق، أخضر=واثق آلياً، **تركوازي=يقين بشري**. التركوازي يستبدل البنفسجي العام كلون «الإنجاز» — يبدأ توحيد الهوية المطلوب في خريطة UX.
- **حلقة الالتقاط تصير مرئية:** كل تحوّل لتركوازي (لمسة حقل / اختيار جهة) هو أثر بصري لمثال تدريب جديد — أوّل مرة تُرى فيها ميزة التفرّد.
- **تصحيح اختناقات موثّقة:** توحيد ربط الثقة عبر المسارين (#1/#2)، تعطيل الملء التلقائي الخطير (#4)، نقل أنماط inline لـ CSS (#9) — كلها تسقط طبيعياً من هذه الأفكار.

**التوصية:** ابدأ بالفكرة 1 (أعلى أثر/جهد، تصحّح اختناق المسح فوراً)، ثم 2 (بوصلة المراجعة)، ثم 3 (تتطلّب كشف درجات TF-IDF للواجهة). كلها CSS-first، صفر مكتبات، تحترم `prefers-reduced-motion`.

ملاحظة: هذا تصوّر تصميمي — لم أعدّل أي ملف (قراءة فقط).

### عدسة 2 — ذكاء المستند

الآن لديّ الصورة التقنية الدقيقة والحاسمة. هذه معلومة ذهبية للتصميم:

**الوضع الفعلي (لا افتراضات):**
- **Tesseract (المحرّك الأساسي، الافتراضي)**: `image_to_data` **يُنتج صناديق لكل كلمة** (`left/top/width/height`) + ثقة لكل كلمة — لكن `TesseractOCRProvider.extract()` حالياً يُرجع `'details': None` (السطر 288). **الصناديق تُحسَب ثم تُرمى.** استعادتها = تغيير سطر واحد (بناء قائمة `details` من `data['left'][i]...`).
- **EasyOCR (الاحتياطي)**: يُرجع الصناديق كاملة بالفعل عند `detail=True` (رباعية نقاط + ثقة).
- **إذن**: البنية التحتية للـ doc-intel **موجودة بالكامل تقريباً**؛ الفجوة الوحيدة سطر Python واحد + تمرير `details` عبر `pipeline` إلى الرد. هذا يجعل أفكاري التالية **قابلة للتنفيذ فعلاً، لا خيالاً**.

الآن أُنتج أفكاري ضمن عدسة doc-intel.

---

# عدسة doc-intel — ثلاث أفكار لتحويل المعاينة من خلفية صامتة إلى سطح ذكاء

> **الأرضية التقنية (محقّقة، لا مفترضة):** الصناديق لكل كلمة + الثقة موجودة أصلاً في `image_to_data` (Tesseract) و`readtext(detail=1)` (EasyOCR). الفجوة الوحيدة: `TesseractOCRProvider.extract()` يُرجع `details:None` (سطر 288 في `providers.py`) — استعادتها تغيير جراحي صغير. كل ما يلي يُبنى على هذا العقد فقط: `[{text, confidence, box:[x,y,w,h]}]` بإحداثيات نسبية للصورة (0-1).

---

## الفكرة ١ — «الخيط» (The Thread): ربط بصري حيّ بين الحقل ومصدره في الورقة

**العنوان:** كل حقل في النموذج يرسم خيطاً منحنياً رفيعاً يعبر الفجوة بين لوحتَي النموذج والمعاينة، لينتهي عند الكلمة/المنطقة التي استُخرِج منها في الصورة الممسوحة.

### الوصف البصري الدقيق (كيف يبدو ويتحرّك)

- عند **التركيز على أي حقل** (`focus`) أو المرور فوقه (`hover`)، يومض في المعاينة **مستطيل توهّج** حول الكلمة المصدر (لا حدّ صلب — بل `box-shadow` داخلي ناعم بلون النوع + خلفية شبه شفّافة `rgba(15,118,110,.10)`)، ويُرسَم بين مركز الحقل ومركز الصندوق **خيط SVG منحنٍ واحد** (Bézier تكعيبي) بسُمك `1.5px`، متدرّج من لون الحقل إلى شفّاف عند طرف الورقة.
- الخيط لا يُرسَم فوق المحتوى كطبقة مزعجة دائمة — بل طبقة `<svg>` واحدة `position:fixed; pointer-events:none; inset:0` تُفعَّل فقط للحقل النشط. **خيط واحد في كل لحظة**، لا شبكة عنكبوت.
- **الحركة:** الخيط يُرسَم بـ `stroke-dashoffset` animation (يُرسَم من الحقل نحو الورقة في ~220ms، `ease-out`) — إحساس «القذف» البصري من الحقل إلى مصدره. عند فقد التركيز يتلاشى (`opacity` 160ms) بلا ارتداد.
- في RTL: النموذج يميناً والمعاينة يساراً، فالخيط يعبر **من اليمين إلى اليسار** بانحناء طبيعي لأسفل — يحترم اتجاه القراءة العربي بدل قوس LTR معكوس.
- **استثمار الثقة:** لون الخيط ومربّع التوهّج يتبع ثقة ذلك الحقل: أخضر (≥.85) / كهرماني (≥.65) / أحمر (<.65). فبمجرّد التنقّل بين الحقول بـ Tab، ترى **بصرياً أين ينظر النظام في الورقة، وكم هو واثق** — دون قراءة رقم واحد.

### لماذا تُبهر (الجريء الذي لا يخطر للفريق)

الفريق يفكّر في المعاينة كـ«صورة مرجعية». الخيط يقلبها إلى **إثبات (provenance)**: النظام لا يقول «العنوان = كذا بثقة 72%» فحسب — بل **يشير بإصبعه** إلى مكان قراءته على الورقة. هذا يحلّ أخطر مشكلة ثقة في أنظمة الـOCR الحكومية: «من أين أتى هذا الرقم؟». المراجعة تصبح تحقّقاً بصرياً في جزء من الثانية بدل مقارنة يدوية مُرهِقة. ولا أحد يتوقّع خيطاً يُرسم *عبر الفجوة بين اللوحتين* — إنه يستثمر تخطيط العمودين الموجود بدل مقاومته.

### رسم التنفيذ (مختصر، بلا مكتبات، RTL، 8GB)

```html
<!-- طبقة واحدة عامة فوق كل شيء -->
<svg id="provenanceLayer" aria-hidden="true"></svg>
```
```css
#provenanceLayer{position:fixed;inset:0;pointer-events:none;z-index:60;
  opacity:0;transition:opacity .16s}
#provenanceLayer.on{opacity:1}
#provenanceLayer path{fill:none;stroke-width:1.5;stroke-linecap:round;
  stroke-dasharray:1;stroke-dashoffset:1;
  animation:thread .22s cubic-bezier(.4,0,.2,1) forwards}
@keyframes thread{to{stroke-dashoffset:0}}
.doc-source-glow{position:absolute;border-radius:4px;
  box-shadow:0 0 0 1px var(--src-c),0 0 14px -2px var(--src-c);
  background:color-mix(in srgb,var(--src-c) 12%,transparent);
  transition:opacity .16s;pointer-events:none}
@media (prefers-reduced-motion:reduce){
  #provenanceLayer path{animation:none;stroke-dashoffset:0}}
```
```js
// box: [x,y,w,h] نسبية 0..1 مرفقة على كل حقل من نتيجة الاستخراج
drawThread(fieldEl, box, conf){
  const img = this.docImgEl.getBoundingClientRect();
  const f   = fieldEl.getBoundingClientRect();
  // مركز الصندوق في إحداثيات الشاشة
  const tx = img.left + box[0]*img.width  + box[2]*img.width/2;
  const ty = img.top  + box[1]*img.height + box[3]*img.height/2;
  const sx = f.left, sy = f.top + f.height/2;              // حافة الحقل (RTL: اليسرى تجاه المعاينة)
  const c  = conf>=.85?'#16a34a':conf>=.65?'#d97706':'#dc2626';
  const cx = (sx+tx)/2;                                     // نقطة تحكّم منحنى ناعم
  const d  = `M${sx},${sy} C${cx},${sy} ${cx},${ty} ${tx},${ty}`;
  const path=`<path d="${d}" stroke="${c}"/>`;
  const total=Math.hypot(tx-sx,ty-sy);                     // اضبط dasharray للطول الفعلي
  this.layer.innerHTML=path;
  const p=this.layer.firstChild; p.style.strokeDasharray=total; p.style.strokeDashoffset=total;
  this.layer.classList.add('on');
  this.positionGlow(box,c);                                 // مربّع التوهّج على الكلمة
}
// ربط: كل حقل يُخزّن مصدره وقت الاستخراج
fieldEl.addEventListener('focus',()=>this.drawThread(fieldEl, fieldEl._srcBox, fieldEl._srcConf));
fieldEl.addEventListener('blur', ()=>this.layer.classList.remove('on'));
```
**التكلفة:** SVG واحد، `path` واحد في كل لحظة، صفر مكتبات، صفر canvas ثقيل. يحترم `prefers-reduced-motion` (يُرسم فوراً بلا حركة).

---

## الفكرة ٢ — «انقر-الكلمة-لتُصحّح» + التقاط تدريب مرئي دقيق (Tap-to-fill & The Correction Ledger)

**العنوان:** الصورة الممسوحة تصبح **سطح إدخال مباشر**: كلمات OCR منخفضة الثقة تُبرَز خفيفاً على الورقة؛ نقرة على أي كلمة تُدرِجها في الحقل النشط. وكل تصحيح يُطلق **ومضة تعلّم دقيقة** تجعل حلقة الالتقاط التدريبي مرئية لأول مرة.

### الوصف البصري الدقيق

- **الطبقة التفاعلية:** فوق الصورة، طبقة `<div>` واحدة تحوي صناديق نصّية شفّافة (`<button.ocr-word>`) بموضع مطلق مطابق لكل كلمة. غير مرئية افتراضياً (`background:transparent`)، لكن:
  - **الكلمات منخفضة الثقة** (< .65) تُرسَم بتسطير متموّج خفيف كهرماني/أحمر (`text-decoration` لا يعمل هنا — بل `border-bottom:1.5px dashed`) — «هذه قرأها النظام بتردّد، افحصها».
  - عند **المرور فوق أي كلمة**: خلفية `rgba(...,.14)` + مؤشّر `cursor:cell`. عند **النقر**: تُدرَج قيمتها في **الحقل النشط حالياً** (آخر حقل مركَّز)، مع ومضة إدراج على الحقل.
- **التقاط الاختيار متعدّد الكلمات (لعناوين/جهات):** السحب فوق عدّة كلمات متجاورة يرسم مستطيل تحديد رفيع؛ عند الإفلات تُدمَج الكلمات بترتيب RTL الصحيح وتُدرَج معاً. هذا يحلّ حالة «العنوان = 4 كلمات في الورقة».
- **دفتر التصحيح (The Correction Ledger) — إبراز حلقة الالتقاط:** عند **كل تصحيح يدوي لحقل مُستخرَج** (تغيّرت القيمة عمّا اقترحه OCR)، تظهر بجانب الحقل — لا toast مزعج — **شارة صغيرة مؤقّتة** (`✎ تعلّم`) تنبض مرة واحدة ثم تتقلّص إلى **نقطة خضراء ثابتة صغيرة** على حافة الحقل. النقطة تعني: «هذا التصحيح سيُدرِّب النموذج». وفي شريط الإجراءات، عدّاد صغير رصين: **«٣ تصحيحات ستُعلّم النظام»** — يتراكم مع الجلسة.
- **الإحساس:** لأول مرة، المستخدم *يرى* أنه معلّم، لا مُدخِل بيانات. التصحيح يصبح مساهمة، لا عبئاً.

### لماذا تُبهر (الجريء)

نقطتان يفوتهما الفريق:
1. **«انقر-الكلمة-لتملأ»** يقلب اقتصاد المراجعة: بدل «اقرأ الورقة بعينك ← اكتب في الحقل بيدك»، تصبح المراجعة **مطابقة بنقرة**. للأرقام العربية والأسماء الطويلة (حيث الكتابة اليدوية بطيئة ومعرّضة للخطأ) هذا تسريع هائل، ويقضي على أخطاء النقل اليدوي.
2. **دفتر التصحيح** هو الترجمة البصرية للميزة المميِّزة التي لا أثر لها اليوم إطلاقاً (حلقة الالتقاط الصامتة). لكن الجرأة في **الرصانة**: لا احتفالات AI مبتذلة (لا «🎉 رائع! علّمت الذكاء!»)، بل **نقطة خضراء صامتة + عدّاد واقعي**. هذا يحترم هوية «مراسلات حكومية رصينة» ويجعل الميزة مرئية دون ابتذال — وهذا بالضبط التوازن الذي يصعب على الفريق إيجاده.

### رسم التنفيذ (مختصر)

```css
.ocr-layer{position:absolute;inset:0;pointer-events:none}      /* الطبقة تعلو الصورة */
.ocr-word{position:absolute;pointer-events:auto;background:transparent;
  border:0;border-radius:3px;cursor:cell;transition:background .12s}
.ocr-word:hover{background:color-mix(in srgb,var(--kind-c) 16%,transparent)}
.ocr-word.low{border-bottom:1.5px dashed var(--warn,#d97706)}   /* ثقة منخفضة */
.learn-dot{width:6px;height:6px;border-radius:50%;background:#16a34a;
  position:absolute;inset-inline-start:-3px;top:8px;opacity:0;transition:opacity .2s}
.field-learned .learn-dot{opacity:1}                            /* تصحيح مُلتقَط */
@keyframes learnPulse{0%{transform:scale(1)}40%{transform:scale(1.5)}100%{transform:scale(1)}}
```
```js
// بناء الطبقة مرة واحدة من details الاستخراج (بإحداثيات نسبية)
renderOcrWords(words){                                         // [{text,confidence,box:[x,y,w,h]}]
  this.ocrLayer.innerHTML = words.map((w,i)=>{
    const [x,y,ww,hh]=w.box, low = w.confidence<0.65;
    return `<button class="ocr-word${low?' low':''}" data-i="${i}"
      style="inset-inline-start:${x*100}%;top:${y*100}%;width:${ww*100}%;height:${hh*100}%"
      title="ثقة ${(w.confidence*100|0)}%">${''}</button>`;   // شفّاف؛ النص في الصورة أسفله
  }).join('');
}
// نقرة = إدراج في الحقل النشط
this.ocrLayer.addEventListener('click',e=>{
  const b=e.target.closest('.ocr-word'); if(!b) return;
  const w=this.words[+b.dataset.i], t=this.activeField;       // آخر حقل مركَّز
  if(!t) return;
  t.value = t.value ? t.value+' '+w.text : w.text;
  t.dispatchEvent(new Event('input',{bubbles:true}));         // يُشغّل التحقّق/الثقة
  this.markCorrected(t);                                      // دفتر التصحيح
});
// دفتر التصحيح: كل تغيير يدوي على حقل مُستخرَج
markCorrected(t){
  if(t._ocrValue!==undefined && t.value!==t._ocrValue && !t.classList.contains('field-learned')){
    t.classList.add('field-learned');                         // نقطة خضراء ثابتة
    const dot=t.parentNode.querySelector('.learn-dot');
    if(dot) dot.style.animation='learnPulse .5s';             // نبضة واحدة رصينة
    this.learnCount++; this.updateLearnCounter();             // «ن تصحيحات ستُعلّم النظام»
  }
}
```
**التكلفة:** الطبقة صناديق شفّافة خفيفة (لا صور، لا canvas). تُبنى مرة عند الاستخراج. تحترم 8GB تماماً. تُوظّف `scan_token` القائم فعلاً كرابط الالتقاط (لا بنية خلفية جديدة — فقط جعل المرئي مرئياً).

---

## الفكرة ٣ — «العدسة» (The Lens): تكبير المصدر داخل الحقل نفسه

**العنوان:** كل حقل مُستخرَج يحمل قصاصة صورة مصغّرة (crop) من الورقة — الخطّ الأصلي المكتوب — تعيش **داخل الحقل** كدليل مرافق، وتتمدّد لعدسة مكبّرة عند التحويم.

### الوصف البصري الدقيق

- على يسار كل حقل مُستخرَج (طرف المعاينة في RTL)، **قصاصة صورة رفيعة** (~28px ارتفاع) هي بالضبط الـ crop من الصورة الممسوحة لصندوق ذلك الحقل — الخطّ الأصلي المكتوب بيد الموظّف أو المطبعة. الحقل يعرض **النص المُستخرَج والصورة الأصلية جنباً إلى جنب**.
- عند **التحويم على القصاصة**: تتمدّد إلى **عدسة عائمة مكبّرة** (×2.5) تُظهر الخطّ الأصلي واضحاً فوق الحقل — لتحقّق فوري «هل قرأ النظام هذا الرقم صحيحاً؟» دون رفع العين للمعاينة الكبيرة إطلاقاً.
- القصاصة تُقصّ عميلياً عبر `background-image` + `background-position/size` من **نفس صورة المعاينة المُحمَّلة** (صفر تحميل إضافي — نستخدم الصورة الموجودة كـ sprite بإزاحة). لكل حقل: نحسب `background-position` و`background-size` من صندوقه النسبي.
- **دمج مع الثقة:** إطار القصاصة يأخذ لون الثقة. الحقل منخفض الثقة تكون قصاصته **أبرز قليلاً** (حدّ أوضح) — دعوة صامتة: «قارِن هذا بنفسك».

### لماذا تُبهر (الجريء)

الفريق يفترض أن التحقّق يتطلب **رحلة العين** بين النموذج والمعاينة الكبيرة (نظر يمين-يسار متكرّر مُرهِق، خاصة في RTL). العدسة تُلغي الرحلة: **المصدر يأتي إلى الحقل**. رؤية «۱۲۳٤» المطبوعة بجانب «1234» المُدخَلة يجعل الخطأ يقفز للعين بلا جهد إدراكي. وذكاء التنفيذ (إعادة استخدام صورة المعاينة كـsprite بإزاحة `background-position`) يعني **صفر تكلفة شبكة/ذاكرة إضافية** — قصاصات مجانية من بايتات محمّلة أصلاً. هذا نوع الحلّ الذي يبدو مكلفاً لكنه شبه مجاني — وهو ما يميّز التصميم الرصين على 8GB.

### رسم التنفيذ (مختصر)

```css
.field-crop{width:100%;height:28px;border-radius:6px;
  background-image:var(--doc-src);background-repeat:no-repeat;
  border:1px solid var(--conf-c,#e2e8f0);cursor:zoom-in;
  filter:contrast(1.05);transition:transform .18s}
.field-crop:hover{transform:scale(1);}                 /* التكبير عبر عنصر عدسة منفصل */
.field-lens{position:absolute;z-index:70;height:70px;border-radius:8px;
  box-shadow:0 8px 28px -6px rgba(0,0,0,.35);border:2px solid var(--conf-c);
  background-image:var(--doc-src);background-repeat:no-repeat;
  pointer-events:none;opacity:0;transition:opacity .14s}
.field-crop:hover ~ .field-lens{opacity:1}
```
```js
// قصّ صورة المعاينة نفسها كـ sprite بإزاحة (صفر تحميل)
attachCrop(fieldWrap, box){                             // box:[x,y,w,h] نسبية
  const [x,y,w,h]=box;
  const crop=fieldWrap.querySelector('.field-crop');
  const natW=this.docNaturalW, natH=this.docNaturalH;  // أبعاد الصورة الحقيقية
  // نُظهر شريط الصندوق بارتفاع 28px: نكبّر الصورة بحيث ارتفاع الصندوق = 28
  const scale = 28 / (h*natH);
  crop.style.setProperty('--doc-src',`url("${this.docSrcUrl}")`);
  crop.style.backgroundSize = `${natW*scale}px ${natH*scale}px`;
  crop.style.backgroundPosition = `-${x*natW*scale}px -${y*natH*scale}px`;
  // العدسة: نفس الحساب بمقياس ×2.5
}
```
**التكلفة:** إعادة استخدام صورة واحدة محمّلة أصلاً كخلفية بإزاحات CSS. لا `<canvas>`، لا قصّ بايتات، لا طلبات. أخفّ من أيقونة إضافية. مثالي لـ8GB.

---

## كيف تتكامل الأفكار الثلاث (رؤية موحّدة)

الثلاث تشترك في **عقد بيانات واحد**: `details:[{text,confidence,box}]` — استعادته من `providers.py` (سطر 288) هي **الاستثمار الوحيد المطلوب**، ويفتح الثلاث دفعة واحدة. طبقة تدرّج مقترحة:

| المرحلة | الفكرة | الجهد | الأثر |
|---|---|---|---|
| ١ (أساس) | استعادة `details` في Tesseract + تمريرها للرد | سطر Python + تمرير | يفتح كل شيء |
| ٢ | **الخيط** (فكرة ١) | SVG واحد + ربط focus | إثبات المصدر + ترجمة الثقة بصرياً |
| ٣ | **العدسة** (فكرة ٣) | sprite بإزاحة CSS | يلغي رحلة العين، شبه مجاني |
| ٤ | **انقر-الكلمة + دفتر التصحيح** (فكرة ٢) | طبقة صناديق + ربط `scan_token` القائم | يقلب المراجعة لنقر + يُظهر حلقة التدريب لأول مرة |

**لماذا هذه الحزمة تُبهر الفريق تحديداً:** كلها تُبنى على بنية تحتية **موجودة فعلاً ومهدورة** (الصناديق تُحسَب وتُرمى، `scan_token` يُمرَّر صامتاً، الثقة تُقاس ولا تُترجَم). لا شيء منها «ميزة AI جديدة» بل **كشف لذكاء كان مدفوناً** — وهذا أرقى ما يمكن تقديمه: أن تُري الفريق أنهم بنوا نصف المعجزة بالفعل دون أن يروها.

**نقطة الحسم للتنفيذ:** أوصي البدء بالمرحلة ١+٢ (الخيط) كإثبات مفهوم في يوم واحد — لأنها الأكثر إبهاراً بأقل مخاطرة، وتُثبت عقد البيانات الذي تعتمد عليه الفكرتان الأخريان.

**ملاحظة صدق تقني:** الفجوة الوحيدة المحقّقة هي `'details': None` في `TesseractOCRProvider.extract()` (`core/extraction/ocr/providers.py:288`) وعدم تمرير `details` عبر `pipeline.py` إلى استجابة الـAPI. كل شيء آخر في هذه الأفكار يستهلك بيانات موجودة أو صوراً محمّلة أصلاً — لا مكتبات، لا canvas، لا أعباء ذاكرة على 8GB. **قراءة فقط — لم أُجرِ أي تعديل على الكود.**

### عدسة 3 — الإدخال الخارق

الآن لديّ الصورة الكاملة والدقيقة. أرى بالضبط: `getNavigationOrder()`، `_focusFirstReviewField` (يقفز لأول حقل ثقته `<0.65`)، `updateConfidenceBadge` (شارة منفصلة `#{field}Confidence`)، ونظام الجهات. كل نقاط الربط الحقيقية بين يدي. لن أقرأ أكثر — لديّ ما يكفي لأفكار قابلة للتنفيذ فعلاً.

---

# عدسة power-flow — تدفّق بلا فأرة لمحطّة عمل احترافية

**فلسفتي:** الموظّف الحكومي يُدخل عشرات الكتب يومياً. الفأرة عدوّه. الميزات المميّزة (ثقة لكل حقل، حلقة تدريب، رابط جهات) ليست زخارف — يجب أن تصبح **وقوداً للسرعة**: الثقة تقرّر أين يقف المؤشّر، حلقة التدريب تُكافئ التصحيح فوراً، رابط الجهات يُختار برقم بلا لمس الفأرة. أدناه ثلاث أفكار مترابطة، كلها تبني على `getNavigationOrder()` و`_focusFirstReviewField` الموجودَين فعلاً.

---

## الفكرة ١ — «مسار الثقة» (Confidence Rail): تنقّل يتخطّى المؤكَّد ويقف على المشكوك

### الوصف البصري الدقيق
شريط رفيع عمودي (4px) لاصق على **الحافة اليمنى** للوحة النموذج (RTL: الحافة الداخلية)، يمتدّ بمحاذاة الحقول. كل حقل مستخرَج يُسقِط على هذا الشريط **عُقدة** (نقطة 8px) بلونٍ = مستوى ثقته: أخضر `#16a34a` (≥0.85)، كهرماني `#d97706` (≥0.65)، أحمر `#dc2626` (<0.65). الحقول الفارغة/غير المستخرَجة = عُقدة رمادية مجوّفة.

- بعد الاستخراج، الشريط يرسم نفسه بانزلاق سريع من الأعلى (`stroke-dashoffset`)، فيرى المستخدم في **لمحة واحدة** توزيع جودة الاستخراج: «حقلان أحمران يحتاجان مراجعة، الباقي أخضر».
- العُقدة النشطة (الحقل المُركَّز الآن) تكبر إلى 12px وتُحاط بحلقة رفيعة بلون النوع النشط. الحقل نفسه يحمل **حدّاً أيمن ملوّناً 3px** بنفس لون ثقته (ترجمة الثقة على الحقل ذاته — النقطة المفقودة رقم 2 في تحليل الألم).
- **الحركة الحاسمة:** مفتاح `Alt+↓` / `Alt+↑` لا ينتقل للحقل التالي بل **للعُقدة الحمراء/الكهرمانية التالية** — يقفز فوق كل ما هو أخضر. أسفل الشريط عدّاد حيّ: «٢ يحتاج مراجعة». مع كل تصحيح، العُقدة تتحوّل أخضر بانتقال 200ms والعدّاد ينقص. حين يصل الصفر: الشريط كله يومض أخضر مرّة واحدة (نبضة واحدة فقط، احتراماً للرصانة) وشارة الحفظ في `action-bar` تتفعّل.

### لماذا تُبهر
الفريق يفكّر في الثقة كـ«شارة نسبة مئوية بجانب حقل». أنا أحوّلها إلى **بنية تنقّل**: الثقة تصبح خريطة طريق للمراجعة. الموظّف لا يقرأ 12 حقلاً — يضغط `Alt+↓` مرّتين ويصحّح نقطتين ثم يحفظ. هذا يحلّ مباشرة الاختناق الموثَّق أن `_focusFirstReviewField` يقفز مرّة واحدة فقط — أنا أجعله **تنقّلاً متكرّراً عبر قائمة المراجعة**، وأصلح ضمناً أن المسار الرئيسي (المسح) لا يُظهر ثقة بأن أجعل الشريط يُرسَم من نفس بيانات الرد.

### رسم التنفيذ
HTML (عمود واحد لاصق داخل لوحة النموذج):
```html
<div class="confidence-rail" id="confidenceRail" aria-hidden="true">
  <svg class="rail-track" viewBox="0 0 4 100" preserveAspectRatio="none">
    <line x1="2" y1="0" x2="2" y2="100" class="rail-line"/>
  </svg>
  <!-- العُقد تُحقن ديناميكياً -->
  <div class="rail-counter" id="railCounter"><b>0</b> يحتاج مراجعة</div>
</div>
```
CSS (خفيف — لا blur، لا ظلال ثقيلة):
```css
.confidence-rail{position:sticky;top:0;inset-inline-start:0;width:20px;height:100%;
  display:flex;flex-direction:column;align-items:center}
.rail-node{width:8px;height:8px;border-radius:50%;transition:transform .2s,background .2s;
  background:var(--c-gray,#cbd5e1)}
.rail-node.high{background:#16a34a}.rail-node.medium{background:#d97706}.rail-node.low{background:#dc2626}
.rail-node.active{transform:scale(1.5);box-shadow:0 0 0 3px var(--kind-ring,rgba(15,118,110,.25))}
.field-input.conf-low{border-inline-end:3px solid #dc2626}
.field-input.conf-medium{border-inline-end:3px solid #d97706}
.rail-flash{animation:rail-ok .4s ease}@keyframes rail-ok{50%{background:#16a34a}}
@media (prefers-reduced-motion:reduce){.rail-node{transition:none}.rail-flash{animation:none}}
```
JS (يُبنى فوق `updateConfidenceBadge` الموجود — نضيف سطراً واحداً في تلك الدالة + منقّل جديد):
```js
// داخل updateConfidenceBadge(fieldId, confidence): أضف هذا السطر
this._syncRailNode(fieldId, this.getConfidenceLevel(confidence));

_syncRailNode(fieldId, level){
  const node = this._railNodes?.[fieldId]; if(!node) return;
  node.className = `rail-node ${level}`;
  const input = document.getElementById(fieldId);
  input?.classList.toggle('conf-low', level==='low');
  input?.classList.toggle('conf-medium', level==='medium');
  this._refreshRailCounter();
}
_refreshRailCounter(){
  const need = Object.values(this._railNodes||{}).filter(n=>/low|medium/.test(n.className)).length;
  const c = document.getElementById('railCounter'); if(c) c.querySelector('b').textContent = need;
  if(need===0){ document.getElementById('confidenceRail')?.classList.add('rail-flash'); }
}
// منقّل المراجعة — يعيد استخدام getNavigableFieldIds() + الشرط نفسه في _focusFirstReviewField
focusNextReviewField(dir=1){
  const ids = this.getNavigableFieldIds();
  const from = ids.indexOf(this.getNavigationFieldId(document.activeElement)||'');
  for(let i=1;i<=ids.length;i++){
    const el = document.getElementById(ids[(from + dir*i + ids.length*i)%ids.length]);
    const node = this._railNodes?.[el?.id];
    if(node && /low|medium/.test(node.className)){ this.focusFieldById(el.id); return; }
  }
}
// اربطها في مستمع الاختصارات الموجود (سطر 1145):
if(e.altKey && e.key==='ArrowDown'){ e.preventDefault(); this.focusNextReviewField(1); }
if(e.altKey && e.key==='ArrowUp'){ e.preventDefault(); this.focusNextReviewField(-1); }
```
**نقطة الربط الفريدة:** حين نصلح ازدواج المسار (`_fillExtractionFields` لا يستدعي `updateConfidenceBadge`) بأن نجعله يستدعي `_syncRailNode`، يعمل الشريط تلقائياً في **المسار الرئيسي (المسح)** — فيتحوّل إصلاح دَيْن تقني إلى ميزة مرئية.

---

## الفكرة ٢ — «الجهة بالرقم» (Numeric Entity Pick): اختيار top-3 بلوحة المفاتيح مع درجة التشابه مرئية

### الوصف البصري الدقيق
حين يُركَّز حقل جهة (issuing/receiving) وله اقتراحات، تنبثق منسدلة **بثلاثة صفوف فقط** (top-3 من رابط TF-IDF). كل صف:
- **رقم مفتاح كبير `[١]` `[٢]` `[٣]`** على الحافة اليمنى (RTL) — رمادي داكن في مربّع 22px بزوايا 6px.
- اسم الجهة + كود.
- **مقياس تشابه دائري صغير** (18px): حلقة SVG تُملأ بنسبة درجة TF-IDF، بلون متدرّج (أخضر عالٍ → كهرماني منخفض) + رقم النسبة داخلها. هذا يستبدل الأنماط inline الحالية (نقطة الألم 4 و9 — أنقلها كلها إلى CSS).
- الصف الأول (أعلى تطابق) له خلفية بلون النوع الخفيف + وسم صغير «الأقرب».

**الحركة:** الضغط على `1`/`2`/`3` (أو `Alt+1..3` لتفادي تعارض الكتابة) يختار الصف فوراً، يملأ الحقل، ويقفز للحقل التالي — **بلا فأرة، بلا سهم، ضغطة واحدة**. مؤشّر «▍» صغير يومض على رقم المفتاح ليعلّم أنه interactive.

**إصلاح خطر صامت:** أُلغي الملء التلقائي العدواني عند `blur` (سطر 2950 — يستبدل نص المستخدم دون تأكيد، خطر في سياق حكومي). بدله: عند `blur` بنص غير محسوم، يظهر شريط رفيع أسفل الحقل: «⌨ اضغط ١ لتأكيد: [اسم الجهة] · ٩٢٪» — تأكيد صريح بضغطة، لا استبدال صامت.

### لماذا تُبهر
رابط TF-IDF (ميزة مبنية، top-3 + درجات) **مُهدَر تماماً** حالياً — المنسدلة تعرض اسماً وكوداً فقط. أنا أحوّله إلى أداة سرعة: الموظّف يرى الدرجة (ثقة القرار) ويختار برقم. هذا «إحساس محطة عمل» حقيقي — مثل اختيار من قائمة IDE بالأرقام. الجرأة: **إظهار درجة الثقة في المطابقة نفسها**، فالموظّف يتعلّم متى يثق ومتى يتحقّق — شفافية القرار الآلي في نظام حكومي.

### رسم التنفيذ
CSS (بديل نظيف لكل الـinline في `displayEntitySuggestions`):
```css
.entity-suggestion-item{display:flex;align-items:center;gap:10px;padding:10px 12px;
  border-bottom:1px solid #e2e8f0;cursor:pointer;background:#fff}
.entity-suggestion-item:hover,.entity-suggestion-item.kbd-active{background:var(--kind-soft,#f0fdfa)}
.entity-suggestion-item.top-match{background:var(--kind-soft,#f0fdfa)}
.esi-key{font:600 .8rem/1 monospace;background:#1e293b;color:#fff;width:22px;height:22px;
  display:grid;place-items:center;border-radius:6px;flex:0 0 auto}
.esi-name{flex:1;font-weight:600;color:#1e293b}
.esi-code{background:#dbeafe;color:#0369a1;padding:2px 7px;border-radius:4px;font-size:.8rem}
.esi-score{--v:0;width:18px;height:18px;flex:0 0 auto;
  background:conic-gradient(var(--sc,#16a34a) calc(var(--v)*1%),#e2e8f0 0);border-radius:50%}
.entity-confirm-bar{font-size:.72rem;color:#475569;padding:4px 8px;background:#f8fafc;
  border-inline-start:2px solid #d97706;display:none}
```
JS (يستبدل جسم `displayEntitySuggestions` — أنظف وأخصر من الحالي):
```js
displayEntitySuggestions(fieldId, suggestions, dropdown, field, type){
  if(!dropdown) return;
  dropdown.replaceChildren();
  const top3 = suggestions.slice(0,3);
  top3.forEach((e,i)=>{
    const score = Math.round((e.score ?? e.similarity ?? 0)*100);   // درجة TF-IDF
    const row = document.createElement('div');
    row.className = 'entity-suggestion-item' + (i===0?' top-match':'');
    row.dataset.id = e.id; row.dataset.name = e.name||'';
    const hue = score>=75?'#16a34a':score>=50?'#d97706':'#dc2626';
    row.innerHTML =
      `<span class="esi-key">${i+1}</span>`+
      `<span class="esi-name"></span>`+
      (e.code?`<span class="esi-code"></span>`:'')+
      `<span class="esi-score" style="--v:${score};--sc:${hue}" title="${score}%"></span>`;
    row.querySelector('.esi-name').textContent = e.name||'';
    if(e.code) row.querySelector('.esi-code').textContent = e.code;
    row.addEventListener('click', ()=>this._commitEntity(field, e, dropdown));
    dropdown.appendChild(row);
  });
  this._entityKbd = {field, dropdown, items: top3};   // حالة الاختيار بالرقم
  dropdown.style.display = 'block';
}
_commitEntity(field, e, dropdown){
  field.value = e.name; field.dataset.entityId = e.id;
  field.dispatchEvent(new Event('input',{bubbles:true}));
  dropdown.style.display='none'; this._entityKbd=null;
  this.focusRelativeField(this.getNavigationFieldId(field), 1);   // القفز التلقائي
}
// في مستمع الاختصارات: اختيار بالرقم أثناء فتح المنسدلة
if(this._entityKbd && e.altKey && ['1','2','3'].includes(e.key)){
  const pick = this._entityKbd.items[+e.key-1];
  if(pick){ e.preventDefault(); this._commitEntity(this._entityKbd.field, pick, this._entityKbd.dropdown); }
}
```
> ملاحظة تكامل: `e.score` يتطلّب أن يعيد endpoint البحث درجة TF-IDF (top-3). إن لم تكن متاحة عميلياً بعد، نحسب تقريباً محلياً من ترتيب `searchEntities`؛ لكن الربط الحقيقي يعيد الدرجة من الخادم — استثمار مباشر للميزة المبنية.

---

## الفكرة ٣ — «صدى التعلّم» (Learning Echo): تغذية راجعة دقيقة تُظهر أن التصحيح درّب النموذج

### الوصف البصري الدقيق
حلقة الالتقاط التدريبي (كل تصحيح = مثال يدرّب النموذج) **غير مرئية إطلاقاً** — أخطر فرصة ضائعة في التحليل. لا أريد شارة صاخبة؛ أريد **إيماءة رصينة دقيقة**:

عندما يصحّح المستخدم حقلاً كان قد استُخرج بثقة منخفضة/متوسطة (أي: النموذج أخطأ وتعلّم الآن)، لحظة مغادرة الحقل (`Tab`/`blur`) تحدث ثلاث حركات متزامنة سريعة (≤400ms):
1. العُقدة الحمراء/الكهرمانية في «مسار الثقة» (الفكرة ١) تتحوّل أخضر بانزلاق — لكن قبلها بومضة، **شرارة صغيرة** (نقطة 4px) تنطلق من الحقل نحو العُقدة (transform + opacity، خفيف جداً).
2. أسفل الحقل، سطر واحد بخط 0.7rem يظهر ويختفي: «✓ تعلّم النظام هذا التصحيح» — بلون النوع، بلا صندوق، بلا أيقونة OS (أيقونة Bootstrap `bi-mortarboard`).
3. عدّاد صامت في `action-bar` بجانب زر الحفظ: «علّمتَ النموذج ٣ مرّات هذه الجلسة» — يتراكم عبر الكتب، فيشعر الموظّف أنه **يبني** شيئاً.

عند الحفظ (حين يُرسَل `scan_token` فعلاً — سطر 3421)، توهّج أخضر خفيف يمرّ على زر الحفظ مع نصّ عابر: «حُفِظ · ٣ أمثلة تدريب أُرسِلت». هذه اللحظة تُغلق الحلقة: التصحيح → التعلّم → التأكيد.

### لماذا تُبهر
هذا يحوّل عملاً روتينياً (تصحيح OCR) إلى **إحساس بالفاعلية**: «أنا أُحسّن النظام». لا نظام حكومي آخر يفعل هذا. الفريق لم يفكّر فيه لأن الميزة خلفية صامتة — أنا أجعلها **حلقة تفاعل مرئية** بأقلّ حركة ممكنة (شرارة واحدة، سطر واحد، عدّاد). والأذكى: أربطها بإصلاح خطر `scan_token` الموثَّق (لا يُعاد ضبطه بعد الحفظ → تلوّث التدريب) — العدّاد يُصفَّر عند `smartClearAndStay`، فيصبح المؤشّر البصري **حارساً** ضد التلوّث: إذا رأى المستخدم عدّاداً غير صفري على كتاب جديد فارغ، فذاك خلل.

### رسم التنفيذ
CSS (حركة بالغة الخفّة، تحترم reduced-motion):
```css
.learn-spark{position:absolute;width:4px;height:4px;border-radius:50%;
  background:var(--kind-accent,#0f766e);pointer-events:none;
  animation:spark .4s cubic-bezier(.4,0,.2,1) forwards}
@keyframes spark{to{transform:translate(var(--dx),var(--dy)) scale(.4);opacity:0}}
.learn-note{font:0.7rem/1.4 inherit;color:var(--kind-accent,#0f766e);
  opacity:0;height:0;overflow:hidden;transition:opacity .2s}
.learn-note.show{opacity:1;height:auto;animation:fade-out 2s .5s forwards}
@keyframes fade-out{to{opacity:0}}
.learn-tally{font-size:.72rem;color:#64748b;display:inline-flex;gap:5px;align-items:center}
.save-taught{animation:taught-glow .6s ease}@keyframes taught-glow{50%{box-shadow:0 0 0 3px rgba(22,163,74,.35)}}
@media (prefers-reduced-motion:reduce){.learn-spark,.learn-note.show,.save-taught{animation:none}}
```
JS (يعلّق على تصحيح حقل مستخرَج منخفض الثقة):
```js
// نحفظ الثقة الأصلية لحظة الاستخراج
// في applyExtractionResult/_fillExtractionFields: this._extractedConf[field]=conf; this._origValue[field]=value;
_maybeEmitLearningEcho(fieldId){
  const orig = this._origValue?.[fieldId];
  const conf = this._extractedConf?.[fieldId] ?? 1;
  const el = document.getElementById(fieldId);
  if(!el || conf>=0.85) return;                    // كان مؤكَّداً → لا تعلّم يُذكر
  const now = el.value.trim();
  if(!now || now===orig) return;                   // لم يُصحَّح فعلاً
  if(this._taught?.has(fieldId)) return;           // مرّة واحدة لكل حقل
  (this._taught ||= new Set()).add(fieldId);
  this._spawnSpark(el);                             // الشرارة نحو عُقدة المسار
  const note = el.parentElement.querySelector('.learn-note') || this._makeLearnNote(el);
  note.textContent = 'تعلّم النظام هذا التصحيح'; note.classList.add('show');
  this._teachCount = (this._teachCount||0)+1;
  this._renderTally();
}
_renderTally(){ const t=document.getElementById('learnTally');
  if(t) t.innerHTML = `<i class="bi bi-mortarboard"></i> علّمتَ النموذج ${this._teachCount||0} مرّة`; }
// اربطها في blur/Tab commit للحقول المستخرَجة، وصفّرها في smartClearAndStay:
// this._teachCount=0; this._taught?.clear(); this._renderTally();  ← حارس ضد تلوّث scan_token
```

---

## الخيط الجامع (لماذا الثلاثة معاً منظومة، لا زخارف منفصلة)
- **الفكرة ١ (المسار)** هي العمود الفقري البصري للثقة.
- **الفكرة ٣ (الصدى)** تحقن الحياة في نفس عُقد المسار عند التصحيح — تعيد استخدام بنيتها.
- **الفكرة ٢ (الجهة بالرقم)** تُسرّع أبطأ حقلين (الجهات) وتغذّي المسار بعُقدة خضراء فور الاختيار.

كلها بلا مكتبات، حركة مقيَّدة (نبضة/شرارة واحدة، `prefers-reduced-motion` معمَّم — يعالج نقطة الألم 5 والأداء على 8GB)، تبني على `getNavigationOrder()`/`getNavigableFieldIds()`/`updateConfidenceBadge()` **الموجودة فعلاً**، وتنقل الأنماط inline إلى CSS (نقطة الألم 4/6/9). والأهم: كل فكرة تُصلح دَيْناً تقنياً موثَّقاً (ازدواج المسار، الملء العدواني، عدم إعادة ضبط `scan_token`) بينما تضيف بهجة — تصميم يخدم الرصانة الحكومية والسرعة معاً.

**قراءة فقط — لم أُجرِ أي تعديل على الكود.** الملفات المرجعية: `static/extraction_smart.js` (المنطق)، `static/extraction_smart.css`، `templates/core/extraction_smart_desktop.html`.

### عدسة 4 — تعليم الـ AI مرئياً

الآن أرى الصورة الكاملة. لديّ كل ما أحتاجه: نقطة الالتقاط عند التصحيح (`applyExtractionResult` يحفظ `extractedData` + `confidenceScores`، والحقول تُطلق `input`)، `scan_token` هو الرابط، والقيم الأصلية المُستخرَجة متاحة للمقارنة. إليك أفكاري.

---

# عدسة LEARNING — «اجعل النموذج يتنفّس مع كل تصحيح»

المبدأ الحاكم: الميزة المميِّزة (كل تصحيح = مثال تدريب) اليوم **صامتة تماماً** — الرابط الوحيد هو تمرير `scan_token` خفيّ عند الحفظ. المستخدم يصحّح في فراغ، لا يعلم أنه معلّم. الأفكار الثلاث تحوّل هذا الصمت إلى حوار رصين، غير مبتذل، حكومي الطابع — لا نجوم متطايرة ولا «AI سحري»، بل **شهادة دقيقة على أثر عمله**.

نقطة الارتكاز التقنية المتاحة الآن (تحقّقت منها): عند `applyExtractionResult` نملك `data[key]` (القيمة المُقترَحة) و`data[conf]` (ثقتها). إذا خزّنّا لكل حقل `_origExtracted[field] = {value, conf}`، فأيّ حدث `input` لاحق يغيّر القيمة = **تصحيح ملموس قابل للقياس**. هذا كل ما نحتاجه لبناء الأفكار الثلاث بلا أي بنية خلفية جديدة.

---

## الفكرة الأولى — «أثر المُصحِّح» (The Correction Ledger): سطر التعلّم الحيّ في شريط الإجراءات

### الوصف البصري الدقيق
في شريط الإجراءات (`.action-bar`)، يسار مؤشّر التحقّق مباشرة، تُزرَع **حبّة تعلّم واحدة هادئة** (`.learn-pill`) لا تظهر إلا بعد أول تصحيح فعلي:

- الحالة الافتراضية: مخفيّة تماماً (لا ضجيج قبل أن يوجد ما نقوله).
- عند أول تصحيح لحقل استخرجه النظام: تنزلق للظهور من اليمين (`slideInRight` 220ms، مسافة 8px فقط — لا قفزة)، بخلفية تركوازية شفّافة `rgba(15,118,110,.08)`، حدّ يسار تركوازي 2px، أيقونة Bootstrap `bi-mortarboard` (قبّعة التخرّج — رمز التعليم الرصين، لا إيموجي)، ونص **«تعلّم النظام من تصحيحٍ واحد»**.
- العدّاد يتصاعد: `«تعلّم من ٣ تصحيحات»` — بأرقام عربية، مع **animate على الرقم نفسه فقط** (تلاشٍ سريع 120ms للرقم القديم، ظهور الجديد) — لا يتحرّك السطر بأكمله.
- عند الحفظ الناجح: الحبّة تومض ومضة تأكيد واحدة (تركوازي → أخضر → تركوازي، 400ms) والنص يتحوّل لحظياً: **«حُفِظت ٣ أمثلة لتدريب النموذج ✓»** ثم تختفي مع مسح النموذج.

نقطة الجمال الخفيّة: **لا يُحتسَب التصحيح إلا إذا كان الحقل مُستخرَجاً أصلاً وتغيّرت قيمته فعلاً**. لو مسح المستخدم حقلاً ثم أعاد نفس القيمة، لا يُحتسَب. لو ملأ حقلاً كان فارغاً في الاستخراج، يُحتسَب كـ«إضافة» بنبرة مختلفة («أضفت حقلاً لم يره النظام»). هذه الدقّة هي ما يرفعها عن العدّاد الساذج.

### لماذا تُبهر (ما لا يخطر للفريق)
الفريق سيقترح غالباً «شارة عدّاد» — لكن العدّاد المجرّد يقيس النشاط لا القيمة. الجرأة هنا في **قلب المعادلة النفسية**: المستخدم الحكومي يكره الشعور بأنه يصحّح خطأ الآلة (إحباط). نحن نعيد تأطير كل تصحيح كـ**فعل تعليم مُقدَّر** — «أنت تُدرِّب»، لا «الآلة أخطأت». والدقّة في التمييز بين تصحيح/إضافة/لا-تغيير تجعلها تبدو ذكية بصدق، لا زخرفة. لا أحد يتوقّع أن يُميّز النظام «إضافة حقل جديد» عن «تصحيح اقتراح».

### رسم التنفيذ (حقيقي، خفيف)
التقاط اللحظة الصفرية — نُخزّن الاستخراج الأصلي:
```js
// داخل applyExtractionResult، أعلى forEach:
this._origExtracted = {};
// داخل الـforEach بعد ضبط القيمة:
this._origExtracted[field] = { value: String(value).trim(), extracted: true };
```
عدّاد التصحيح — hook واحد على `input` (نستفيد من `handleFieldInput` الموجود):
```js
_trackCorrection(fieldId) {
    const el = document.getElementById(fieldId);
    if (!el) return;
    const orig = this._origExtracted?.[fieldId];
    const now = el.value.trim();
    // حالة 1: تصحيح اقتراح مُستخرَج
    if (orig?.extracted && orig.value !== '' && now !== orig.value) {
        this._corrections.set(fieldId, 'edit');
    // حالة 2: إضافة حقل لم يستخرجه النظام
    } else if ((!orig || orig.value === '') && now !== '') {
        this._corrections.set(fieldId, 'add');
    } else {
        this._corrections.delete(fieldId); // عاد لنفس القيمة → يُلغى
    }
    this._renderLearnPill();
}
_renderLearnPill() {
    const pill = document.getElementById('learnPill');
    const n = this._corrections.size;
    if (n === 0) { pill.classList.remove('is-active'); return; }
    const edits = [...this._corrections.values()].filter(v => v === 'edit').length;
    const noun = n === 1 ? 'تصحيحٍ واحد' : n === 2 ? 'تصحيحين' : `${this._ar(n)} تصحيحات`;
    pill.querySelector('.lp-text').textContent = `تعلّم النظام من ${noun}`;
    pill.classList.add('is-active', 'lp-bump'); // bump = تلاشي الرقم فقط
    setTimeout(() => pill.classList.remove('lp-bump'), 200);
}
```
```css
.learn-pill{display:none;align-items:center;gap:6px;padding:5px 12px;border-radius:999px;
  background:rgba(15,118,110,.08);border-inline-start:2px solid #0f766e;color:#0f766e;
  font-size:.8rem;font-weight:600;white-space:nowrap;}
.learn-pill.is-active{display:inline-flex;animation:slideInRight .22s cubic-bezier(.4,0,.2,1);}
.learn-pill .bi{font-size:.95rem;}
.learn-pill.lp-bump .lp-text{animation:lpNum .2s ease;}
@keyframes lpNum{0%{opacity:.3;transform:translateY(-2px)}100%{opacity:1;transform:none}}
.learn-pill.lp-saved{background:rgba(22,163,74,.1);border-color:#16a34a;color:#15803d;
  transition:all .4s;}
@media (prefers-reduced-motion:reduce){.learn-pill.is-active,.learn-pill.lp-bump .lp-text{animation:none;}}
```
ربط عند الحفظ الناجح (داخل فرع النجاح في `submitBookData`): `pill.classList.add('lp-saved'); pill.querySelector('.lp-text').textContent = \`حُفِظت ${this._ar(n)} أمثلة لتدريب النموذج\`;`

**التكلفة:** صفر بنية خلفية جديدة، عنصر DOM واحد، `Map` واحدة، لا polling. مثالية لـ8GB.

---

## الفكرة الثانية — «هالة المصدر» (Provenance Halo): توقيع بصري يفرّق ما كتبه النظام عمّا صحّحته أنت

### الوصف البصري الدقيق
هذه أعمق فكرة وأكثرها جرأة. اليوم كل الحقول تبدو متطابقة بعد الاستخراج — لا فرق بصري بين «قيمة ثقتها 0.95 لم تلمسها» و«قيمة صحّحتها بيدك». نحن نمنح كل حقل **توقيع مصدر** دقيقاً عبر حدّ بداية (`border-inline-start`) رفيع 3px يروي قصّة الحقل:

- **حقل استخرجه النظام بثقة عالية، لم تُصحَّح:** حدّ تركوازي صلب `#0f766e` — «النظام واثق».
- **حقل ثقته منخفضة (`< 0.65`):** حدّ كهرماني **متقطّع** `dashed #d97706` — إشارة صامتة «راجعني». (هذا يحلّ نقطة الألم رقم 2 في الخريطة: الثقة لكل حقل غير مترجَمة بصرياً على الحقل نفسه.)
- **حقل صحّحته أنت (اللحظة الذهبية):** بمجرّد أن يتغيّر، ينتقل الحدّ بسلاسة (300ms) إلى **أخضر توقيعي `#16a34a`** مع علامة `bi-check` صغيرة جداً تظهر في زاوية الحقل الداخلية — «هذا لمستك». ويبقى أخضر. الحقل الآن يحمل **بصمتك**، مرئياً.
- **حقل أضفته من الصفر (لم يره النظام):** حدّ أخضر لكن **منقّط** `dotted #16a34a` — «معرفة جديدة كلياً قدّمتها».

الحركة الأساسية: عند التصحيح، الانتقال من كهرماني/تركوازي إلى الأخضر يتمّ عبر `transition: border-color .3s` — انزلاق لوني هادئ، بلا وميض. علامة الصح تتلاشى للظهور (`scale(.6)→scale(1)`, 180ms). كل شيء على الحدّ فقط — **صفر إزاحة تخطيط (zero layout shift)**، حرج على 8GB.

اللمسة النهائية: تلميح (`title`/tooltip رصين) عند المرور على الحدّ الأخضر: **«صحّحته — سيُدرَّب عليه النموذج»**. هكذا نربط التوقيع البصري بحلقة التدريب صراحةً.

### لماذا تُبهر
هذا **يحوّل النموذج بأكمله إلى خريطة حرارية للمصدر (provenance heatmap)** دون أي عنصر UI إضافي — فقط حدود 3px تحكي: الأخضر يتراكم بصرياً كلما صحّحت أكثر، فترى بعينك «كم علّمت النظام في هذا المستند» دفعة واحدة. الفريق سيفكّر في «حدّ ملوّن للثقة» (تحسين معروف)؛ لن يفكّر في أن **الحدّ نفسه يتحوّل عند التصحيح ليصبح شهادة ملكية**. الدمج بين «ثقة الآلة» و«لمسة الإنسان» في محور بصري واحد (اللون على الحدّ) هو الابتكار — قصّتان في بُعد واحد.

### رسم التنفيذ
```js
// عند الاستخراج، ضع حالة المصدر الأولية:
_setProvenance(field, conf) {
    const wrap = document.getElementById(field)?.closest('.field-block') || document.getElementById(field);
    if (!wrap) return;
    wrap.classList.remove('prov-high','prov-low','prov-user','prov-new');
    wrap.classList.add(conf >= 0.65 ? 'prov-high' : 'prov-low');
}
// داخل _trackCorrection، عند اكتشاف تغيير فعلي:
if (type === 'edit') wrap.classList.replace(/* أياً كان */ , 'prov-user'), this._addProvCheck(wrap);
if (type === 'add')  wrap.classList.add('prov-new');
```
```css
.field-block{border-inline-start:3px solid transparent;padding-inline-start:9px;
  transition:border-color .3s cubic-bezier(.4,0,.2,1);}
.field-block.prov-high{border-inline-start-color:#0f766e;}
.field-block.prov-low {border-inline-start-color:#d97706;border-inline-start-style:dashed;}
.field-block.prov-user{border-inline-start-color:#16a34a;border-inline-start-style:solid;}
.field-block.prov-new {border-inline-start-color:#16a34a;border-inline-start-style:dotted;}
.prov-check{position:absolute;inset-inline-end:8px;top:8px;color:#16a34a;font-size:.75rem;
  animation:provPop .18s ease;}
@keyframes provPop{from{opacity:0;transform:scale(.6)}to{opacity:1;transform:scale(1)}}
@media (prefers-reduced-motion:reduce){.field-block{transition:none;}.prov-check{animation:none;}}
```
**ملاحظة اتّساق:** هذا يستبدل شارات الثقة الثلاث المتفرّقة (نقطة الألم 2) بلغة واحدة على الحدّ — تبسيط رصين، لا إضافة ضجيج. يمكن إبقاء الشارة الرقمية عند hover فقط لمن يريد الرقم.

---

## الفكرة الثالثة — «سطر النموّ» (Growth Ledger): ذاكرة الجلسة — كم علّمت النظام اليوم

### الوصف البصري الدقيق
الفكرتان أعلاه تعيشان داخل المستند الواحد. هذه الفكرة **ترفع البصر للأعلى**: شريحة صغيرة رصينة في **رأس الصفحة** (`.app-page-header`، يسار المستخدم)، تتذكّر عبر الجلسة كم مثالاً ساهم به المستخدم:

- المظهر: شريحة زجاجية شفّافة على خلفية الرأس البنفسجية (أو التركوازية بعد التوحيد)، أيقونة `bi-graph-up-arrow`، ونص بأرقام عربية: **«علّمت النظام ١٧ مثالاً هذه الجلسة»**.
- تُخزَّن في `sessionStorage` (لا `localStorage` — نريد «هذه الجلسة» لا للأبد، ويتّسق مع حيلة `lettersys_scan_notice` القائمة التي تعيش عبر إعادة تحميل الصفحة الكاملة بعد المسح).
- **اللحظة السحرية — العتبات (milestones):** عند بلوغ عتبة (5، 10، 25، 50)، الشريحة تنبض ومضة تركوازية واحدة رصينة (400ms، لا تكرار) ويظهر toast دقيق لا يزعج: **«١٠ أمثلة اليوم — النموذج يتحسّن بفضلك»**. تحفيز لطيف، غير طفولي، بلا نجوم ولا كونفيتي.
- عند الوصول لأرقام أكبر، النص يتطوّر لنبرة تقدير أعمق: عند 50+ → **«مساهم رئيسي — ٥٢ مثالاً»** بلمسة ذهبية خفيفة على الأيقونة فقط.

الترابط عبر الأفكار: عدّاد الفكرة 1 (تصحيحات المستند الحالي) **يُصبّ في** سطر النموّ عند الحفظ الناجح — فترى الرقم في الرأس يتصاعد لحظة الحفظ بنفس حركة `lpNum`. حلقة مغلقة: صحّحت (فكرة 2) → رأيت العدّ يتراكم (فكرة 1) → عند الحفظ يرتفع رصيدك الكلّي (فكرة 3).

### لماذا تُبهر
تحوّل مهمة إدخال بيانات مملّة إلى **سردية نموّ شخصية هادئة** — دون تحويلها لعبة رخيصة (لا نقاط، لا شارات كرتونية). النبرة الحكومية الرصينة («مساهم رئيسي») تمنح كرامة للعمل الروتيني. الجرأة: معظم أنظمة الإدخال الحكومية باردة تماماً؛ نحن نُدخل **دفئاً محسوباً بالمليمتر** يحترم جدّية السياق. والذكاء في `sessionStorage` (لا للأبد) يمنع تضخّم الأرقام الفارغ الذي يفقد المعنى.

### رسم التنفيذ
```js
_bumpGrowthLedger(n) {
    const KEY = 'lettersys_session_examples';
    const prev = parseInt(sessionStorage.getItem(KEY) || '0', 10);
    const total = prev + n;
    sessionStorage.setItem(KEY, String(total));
    const chip = document.getElementById('growthLedger');
    chip.querySelector('.gl-text').textContent =
        total >= 50 ? `مساهم رئيسي — ${this._ar(total)} مثالاً`
                    : `علّمت النظام ${this._ar(total)} مثالاً هذه الجلسة`;
    chip.classList.remove('gl-hidden');
    chip.classList.toggle('gl-gold', total >= 50);
    // milestones
    if ([5,10,25,50].includes(total)) {
        chip.classList.add('gl-pulse');
        setTimeout(() => chip.classList.remove('gl-pulse'), 450);
        this.showToast(`${this._ar(total)} أمثلة اليوم — النموذج يتحسّن بفضلك`, 'success');
    }
}
// يُستدعى داخل فرع الحفظ الناجح: this._bumpGrowthLedger(this._corrections.size);
```
```css
.growth-ledger{display:inline-flex;align-items:center;gap:6px;padding:4px 11px;border-radius:999px;
  background:rgba(255,255,255,.14);color:#fff;font-size:.78rem;font-weight:600;
  backdrop-filter:blur(4px);}          /* backdrop خفيف واحد فقط، مقبول على 8GB */
.growth-ledger.gl-hidden{display:none;}
.growth-ledger.gl-gold .bi{color:#fbbf24;}
.growth-ledger.gl-pulse{animation:glPulse .45s ease;}
@keyframes glPulse{0%,100%{box-shadow:0 0 0 0 rgba(15,118,110,0)}
  50%{box-shadow:0 0 0 4px rgba(15,118,110,.35)}}
@media (prefers-reduced-motion:reduce){.growth-ledger.gl-pulse{animation:none;}}
```
`_ar(n)` مساعد صغير لتحويل الأرقام الغربية لعربية-هندية (`n.toString().replace(/\d/g, d => '٠١٢٣٤٥٦٧٨٩'[d])`) — يخدم الأفكار الثلاث ويحفظ أصالة RTL.

---

## كيف تتضافر الثلاثة (النظام لا القائمة)

| الطبقة | المكان | تجيب على سؤال المستخدم |
|---|---|---|
| **هالة المصدر** (2) | على كل حقل | «أيّ لمسة لي في هذا الحقل؟» |
| **أثر المُصحِّح** (1) | شريط الإجراءات | «كم علّمت في هذا المستند؟» |
| **سطر النموّ** (3) | رأس الصفحة | «كم علّمت النظام اليوم؟» |

ثلاثة مستويات تكبير (حقل → مستند → جلسة) لقصّة واحدة: **أنت تصنع هذا النظام أذكى**. الحلقة الخفيّة (`scan_token` الصامت) أصبحت مرئية، رصينة، وحكومية الطابع — بلا أي جمالية AI مبتذلة، وبتكلفة أداء شبه صفرية (عنصرا DOM، `Map` واحد، `sessionStorage`، حدود CSS، صفر polling).

### توصية تنفيذية أولى (أقلّ مخاطرة، أعلى أثر)
ابدأ بـ**الفكرة 2 (هالة المصدر)** — لأنها تُصلح نقطة ألم موثّقة (الثقة لكل حقل غير مرئية) وتُنشئ البنية التحتية (`_origExtracted` + `_trackCorrection`) التي تعتمد عليها الفكرتان 1 و3. ثم 1 ثم 3 بالتتابع — كل واحدة تُعيد استخدام نفس `Map` التصحيحات. **شرط حرج للتنفيذ:** يجب أولاً توحيد `_fillExtractionFields` مع `applyExtractionResult` (الدَّيْن الموثّق سطر 607) — وإلا الأفكار الثلاث تعمل في الرفع اليدوي فقط وتموت في المسار الرئيسي (المسح الفعلي). هذا الإصلاح شرط مسبق، لا خيار.

**قراءة فقط — لم أُجرِ أي تعديل على الكود.**

الملفات ذات الصلة:
- `C:\Users\fwz\Downloads\lettersys_django_bootstrap_v4_scan\lettersys_django_bootstrap_v4_scan\lettersys_project\static\extraction_smart.js` (نقاط الربط: `applyExtractionResult` سطر 2708، `_fillExtractionFields` سطر 602، `handleFieldInput` سطر 2776، فرع الحفظ الناجح `submitBookData` سطر 3447)
- `C:\Users\fwz\Downloads\lettersys_django_bootstrap_v4_scan\lettersys_django_bootstrap_v4_scan\lettersys_project\static\extraction_smart.css` (حبّة التعلّم + هالة المصدر)
- `C:\Users\fwz\Downloads\lettersys_django_bootstrap_v4_scan\lettersys_django_bootstrap_v4_scan\lettersys_project\templates\core\extraction_smart_desktop.html` (زرع `#learnPill` في `.action-bar` و`#growthLedger` في `.app-page-header`)

### عدسة 5 — اقتراح الجهات

لقد تأكّدت من الحقيقة الحاسمة: **الخادم يبني بالفعل `issuing_entity_matches` و`receiving_entity_matches` (top-3 مع `score` و`entity_id`) ويخزّنها في نتيجة الاستخراج (سطر 507, 517, 653-654)** — لكنّ العميل في `applyExtractionResult` يتجاهلها تماماً؛ يأخذ الاسم النصّي فقط. الكنز مُنتَج على الخادم ومُهدَر على الشاشة. هذا يجعل أفكاري ليست خيالاً بل «توصيل سلك مقطوع».

فيما يلي أفكاري الثلاث ضمن عدسة **الجهات**.

---

# عدسة الجهات — 3 أفكار متقدّمة قابلة للتنفيذ

**أساس واقعي مؤكَّد من الكود** (لا افتراضات):
- الخادم ينتج `issuing_entity_matches[]` / `receiving_entity_matches[]` = **top-3 فعلي** مع `{entity_id, entity_name, entity_code, entity_type, score(0-100), match_type:'tfidf'}` — ويُهدَر في `applyExtractionResult`.
- `search_entities` API يُعيد `similarity` (0-1 مدوّرة) + `priority` (1..99) + `has_email` + `type` — كلها غير مستغلّة بصرياً.
- المنسدلة الحالية مبنية بـ `style.cssText` inline (سطر 3004-3040) + إيموجي OS (📤📥📝🔍) — تلوّث ومظهر غير رصين.
- الخطر: `blur` يملأ بأفضل نتيجة **بلا تأكيد** (سطر 2950) — مطابقة خاطئة صامتة في سياق حكومي.

---

## الفكرة 1 — «بطاقة الترشيح» (The Candidate Ballot): top-3 كقرار محسوم لا قائمة

**الوصف البصري الدقيق:**
بدل منسدلة نصّية باهتة، عند استخراج الجهة تظهر تحت الحقل مباشرة **بطاقة ترشيح مضغوطة** فيها 3 مرشّحين كصفوف، مرتّبين تنازلياً بالدرجة. لكل صف:
- **شارة رتبة** يمين (RTL): المرشّح الأول يحمل حلقة تركوازية صلبة، الثاني والثالث حلقة رمادية باهتة — تسلسل بصري فوري.
- **اسم الجهة** بخط Cairo 600، وتحته صفّ ميتا: رمز الجهة في شريحة تركوازية + نوعها (مُرسِل/مستقبِل بأيقونة Bootstrap `bi-box-arrow-up-right`/`bi-box-arrow-in-down-left`، لا إيموجي).
- **عمود الدرجة يسار**: رقم النسبة (مثلاً `87%`) فوق **شريط تشابه أفقي دقيق** (2px) يمتدّ من اليمين، لونه يتدرّج: ≥80% تركوازي صلب، 50-80% تركوازي باهت، <50% كهرماني تحذيري. الشريط هو الترجمة البصرية المباشرة لدرجة TF-IDF المهدورة.

**الحركة:** البطاقة تدخل بـ `slideInUp` خفيف 120ms (لا نبض). المرشّح الأول يُبرَز تلقائياً (highlight ring) وجاهز للقبول بـ Enter. الأسهم ↑↓ تتنقّل بين الثلاثة، Enter يقبل، Esc يُغلق ويُبقي نصّ المستخدم. عند الاختيار: الصف يومض تركوازياً مرة واحدة (150ms) ثم البطاقة تنطوي — لا toast منفصل.

**فجوة الثقة الصريحة (اللمسة الجريئة):** إذا كان الفارق بين المرشّح #1 و#2 **أقل من 8 نقاط**، تظهر شارة صغيرة «متقاربان — راجِع» بلون كهرماني بين الصفّين. هذا يقلب المنطق: بدل إخفاء الغموض (كما يفعل `blur` الحالي بملئه الصامت)، نُظهره صراحةً حيث القرار حسّاس.

**لماذا تُبهر:**
- الفريق يفكّر في «تحسين المنسدلة». الجريء هو **إظهار درجة TF-IDF كشريط فيزيائي** — البيانات موجودة على الخادم ومُهدرة؛ نحن نوصّل السلك فقط، فالكلفة الهندسية دنيا والأثر بصري صادم.
- «فجوة الثقة» فكرة لا تخطر لأحد: تحويل *تقارب* المرشّحين إلى تحذير مرئي يمنع المطابقة الخاطئة الصامتة — قيمة حكومية حقيقية، لا زخرفة.
- تلغي سلوك `blur` الخطر (الملء بلا تأكيد) وتستبدله بقرار واعٍ.

**رسم التنفيذ (HTML/CSS/JS حقيقي، بلا مكتبات):**

بنية العنصر (يُبنى في `displayEntitySuggestions`، لكن الأنماط في CSS):
```html
<div class="ent-ballot" role="listbox" dir="rtl">
  <button class="ent-cand is-top" role="option" data-id="42" aria-selected="true">
    <span class="ent-cand__rank"></span>
    <span class="ent-cand__main">
      <span class="ent-cand__name">وزارة المالية</span>
      <span class="ent-cand__meta">
        <span class="ent-cand__code">ش3</span>
        <i class="bi bi-box-arrow-up-right ent-cand__type"></i>
      </span>
    </span>
    <span class="ent-cand__score">
      <span class="ent-cand__pct">87%</span>
      <span class="ent-cand__bar"><i style="inline-width-only"></i></span>
    </span>
  </button>
  <!-- صفّان آخران -->
</div>
```
النسبة المئوية الوحيدة inline المسموحة هي عرض الشريط (بيانات بحتة):
```js
bar.querySelector('i').style.inlineSize = score + '%';
```

CSS (يذهب في `extraction_smart.css` — يقاعِد كلّ `cssText`):
```css
.ent-ballot{position:absolute;inset-inline:0;top:calc(100% + 4px);z-index:30;
  background:#fff;border:1px solid var(--ent-border,#e2e8f0);border-radius:12px;
  box-shadow:0 8px 24px -8px rgba(15,23,42,.18);overflow:hidden;
  animation:entIn .12s cubic-bezier(.4,0,.2,1)}
@keyframes entIn{from{opacity:0;transform:translateY(-4px)}to{opacity:1;transform:none}}
@media (prefers-reduced-motion:reduce){.ent-ballot{animation:none}}
.ent-cand{display:flex;align-items:center;gap:12px;inline-size:100%;
  padding:10px 14px;border:0;background:none;cursor:pointer;text-align:start;
  border-bottom:1px solid #f1f5f9}
.ent-cand:hover,.ent-cand[aria-selected="true"]{background:#f0fdfa} /* teal-50 */
.ent-cand__rank{inline-size:8px;block-size:8px;border-radius:50%;
  box-shadow:0 0 0 2px #cbd5e1 inset}
.ent-cand.is-top .ent-cand__rank{box-shadow:0 0 0 3px #0f766e inset;background:#0f766e}
.ent-cand__main{flex:1;min-inline-size:0}
.ent-cand__name{display:block;font-weight:600;color:#1e293b;font-size:.92rem}
.ent-cand__meta{display:flex;gap:8px;align-items:center;margin-top:3px}
.ent-cand__code{background:#ccfbf1;color:#0f766e;padding:1px 7px;border-radius:5px;
  font-size:.78rem;font-weight:600;font-variant-numeric:tabular-nums}
.ent-cand__score{display:flex;flex-direction:column;align-items:flex-start;gap:3px;inline-size:56px}
.ent-cand__pct{font-size:.8rem;font-weight:700;color:#0f766e;font-variant-numeric:tabular-nums}
.ent-cand__bar{inline-size:100%;block-size:2px;background:#e2e8f0;border-radius:2px;overflow:hidden}
.ent-cand__bar i{display:block;block-size:100%;background:#0f766e}
.ent-cand.is-weak .ent-cand__pct,.ent-cand.is-weak .ent-cand__bar i{color:#d97706;background:#d97706}
.ent-gap-warn{font-size:.72rem;color:#92400e;background:#fffbeb;
  padding:3px 14px;border-block:1px solid #fef3c7}
```

توصيل البيانات المهدورة (التعديل الحاسم في `applyExtractionResult`، بعد سطر 2743):
```js
if (Array.isArray(data.issuing_entity_matches))
  this.renderBallot('issuingEntity', data.issuing_entity_matches);
if (Array.isArray(data.receiving_entity_matches))
  this.renderBallot('receivingEntity', data.receiving_entity_matches);
```
> ملاحظة تنفيذ: يجب إضافة `issuing_entity_matches`/`receiving_entity_matches` إلى قاموس الرد في `pipeline.py::to_dict` (سطر ~716) — حالياً تُخزَّن في `raw_data` (سطر 653) لكن لا تُصدَّر في القاموس المُسطَّح الذي يقرؤه العميل. سلك واحد صغير.

---

## الفكرة 2 — «هل تقصد؟» الصوتي-الإملائي (Arabic Phonetic Did-You-Mean)

**الوصف البصري الدقيق:**
عند كتابة المستخدم يدوياً (لا استخراج) واسمٌ لا يطابق تماماً لكنه قريب إملائياً/همزياً (وزارة المالية ضد «وزاره الماليه»، أو «الأمانه» ضد «الأمانة»)، يظهر تحت الحقل **سطر واحد رفيع** غير مزعج:
> «هل تقصد **وزارة المالية**؟» — الجزء الغامق قابل للنقر، وبجانبه زر ✕ صغير للتجاهل.

الحرف المختلف (الهمزة/التاء المربوطة) يُميَّز داخل الاقتراح بلون تركوازي خفيف تحت الحرف — يعلّم المستخدم *أين* كان الاختلاف. النقر يستبدل ويومض الحقل تركوازياً مرة.

**آلية التطبيع العربي (خفيفة، صفر مكتبات):** نطبّع query والأسماء بنفس قاعدة الخادم (`_normalize_ar`) داخل JS: توحيد الهمزات (أإآ→ا)، التاء المربوطة (ة→ه)، الألف المقصورة (ى→ي)، حذف التشكيل. إذا طابق النصّ **بعد** التطبيع اسماً موجوداً بينما لم يطابق **قبله** → هذا بالضبط «هل تقصد؟». لا حاجة لمسافة تحرير ثقيلة؛ فرق التطبيع وحده إشارة قوية ومجانية حسابياً.

**لماذا تُبهر:**
- العربية تعاني فوضى الهمزة/التاء المربوطة أكثر من أي لغة، ولا أحد في الفريق يعالجها في الواجهة. تطبيق قاعدة التطبيع نفسها التي يستخدمها الخادم TF-IDF على العميل يخلق **اتّساقاً معرفياً** بين ما يراه المستخدم وما يفهمه النموذج.
- إبراز *الحرف* المختلف تعليمي — يقلّل تكرار الخطأ الإملائي مستقبلاً، لا يصلح المرة الحالية فقط.
- خفيف جداً (دالة تطبيع + مقارنة سلسلة) — مثالي لجهاز 8GB.

**رسم التنفيذ:**
```js
const AR_NORM = s => (s||'')
  .replace(/[\u064B-\u0652]/g,'')        // حذف التشكيل
  .replace(/[أإآ]/g,'ا').replace(/ة/g,'ه')
  .replace(/ى/g,'ي').replace(/ؤ/g,'و').replace(/ئ/g,'ي')
  .trim().toLowerCase();

didYouMean(query, entityType){
  const nq = AR_NORM(query);
  if(!nq) return null;
  const exact = this.entityList.some(e=>e.name.toLowerCase()===query.toLowerCase());
  if(exact) return null;                  // مطابقة حرفية — لا داعي
  return this.entityList.find(e=>
    AR_NORM(e.name)===nq &&               // يطابق بعد التطبيع فقط
    (!entityType||e.etype===entityType||e.etype==='both')) || null;
}
```
```css
.ent-dym{display:flex;align-items:center;gap:6px;font-size:.78rem;color:#64748b;
  margin-top:5px;padding-inline-start:2px}
.ent-dym__pick{color:#0f766e;font-weight:600;background:none;border:0;cursor:pointer;
  text-decoration:underline;text-decoration-color:#99f6e4;text-underline-offset:3px}
.ent-dym__diff{border-bottom:2px solid #0f766e;padding-bottom:1px}
.ent-dym__x{color:#cbd5e1;background:none;border:0;cursor:pointer;font-size:.9rem}
.ent-dym__x:hover{color:#94a3b8}
```
يُستدعى في مستمع `input` الموجود (سطر 2913) بعد فحص `searchEntities`: إن لم توجد نتائج مباشرة لكن `didYouMean` وجد شيئاً → أظهر السطر بدل إخفاء المنسدلة.

---

## الفكرة 3 — «الإضافة السلسة» (Inline Entity Forge): إنشاء جهة جديدة دون مغادرة السياق

**الوصف البصري الدقيق:**
حين لا يوجد أي مرشّح جيّد (كل الدرجات < عتبة، أو `searchEntities` فارغ)، بدل منسدلة فارغة محبطة يظهر **صفّ فعل واحد** أخضر ناعم في موضع البطاقة:
> `+ إضافة «مديرية التخطيط» كجهة جديدة`
الاسم بين قوسين هو نصّ المستخدم الحرفي. النقر لا يفتح صفحة/مودال ثقيل — بل يوسّع الصفّ نفسه inline (`grid-template-rows` من 0fr→1fr، 160ms) كاشفاً حقلين مصغّرين: **رمز مقترَح تلقائياً** (أوّل حروف الكلمات، قابل للتحرير) + منتقي نوع (مُرسِل/مستقبِل/كلاهما، أزرار segmented صغيرة). زر «حفظ وربط» أخضر يرسل POST، وعند النجاح يُدرِج الجهة الجديدة في `entityList` محلياً، يربطها بالحقل، ويومض أخضر — **دون أي إعادة تحميل**.

**استثمار حلقة الالتقاط (الجسر الجريء بين العدسات):** الجهة المُنشأة inline تُعلَّم بـ `origin:'inline_forge'` وتُربط بـ `scan_token` الحالي. أي: *المستخدم علّم النظام كياناً جديداً كلياً أثناء تصحيحه* — أقوى إشارة تدريب ممكنة. يظهر بجانبها بعد الحفظ وسمٌ دقيق «جهة جديدة» كهرماني (يطابق لون «الوسوم الجديدة» القائم `#fef3c7/#92400e`) — فيتّسق مع نظام الوسوم الموجود بدل اختراع لغة جديدة.

**لماذا تُبهر:**
- تحويل «الحالة الفارغة» (أحبط لحظات UX) إلى **لحظة إنتاج**. المستخدم لا يُطرَد لصفحة إدارة الجهات ويعود؛ يبقى في تدفّق الإدخال.
- الرمز المقترَح تلقائياً من الحروف الأولى لمسة تفصيلية تُشعر بالذكاء دون AI.
- ربط الإنشاء بـ `scan_token` يجعل حلقة التدريب تلتقط ليس التصحيحات فقط بل **توسيع المعجم** — بُعد لا يخطر للفريق.

**رسم التنفيذ:**
```html
<div class="ent-forge" dir="rtl">
  <button class="ent-forge__trigger"><i class="bi bi-plus-lg"></i>
    إضافة «<b class="ent-forge__q">مديرية التخطيط</b>» كجهة جديدة</button>
  <div class="ent-forge__body" hidden>
    <input class="ent-forge__code" maxlength="8" placeholder="الرمز">
    <div class="ent-forge__seg" role="group">
      <button data-t="issuer">مُرسِل</button>
      <button data-t="receiver" class="on">مستقبِل</button>
      <button data-t="both">كلاهما</button>
    </div>
    <button class="ent-forge__save"><i class="bi bi-check-lg"></i> حفظ وربط</button>
  </div>
</div>
```
```css
.ent-forge{border:1px dashed #86efac;background:#f0fdf4;border-radius:10px;overflow:hidden}
.ent-forge__trigger{inline-size:100%;padding:10px 14px;border:0;background:none;
  color:#166534;font-weight:600;cursor:pointer;text-align:start;font-size:.86rem}
.ent-forge__body{display:grid;grid-template-rows:0fr;transition:grid-template-rows .16s ease}
.ent-forge.open .ent-forge__body{grid-template-rows:1fr}
.ent-forge__body>*{overflow:hidden}
.ent-forge__seg button{border:1px solid #d1fae5;background:#fff;padding:3px 10px;
  border-radius:6px;font-size:.78rem;cursor:pointer;color:#475569}
.ent-forge__seg button.on{background:#dcfce7;color:#166534;border-color:#86efac}
@media(prefers-reduced-motion:reduce){.ent-forge__body{transition:none}}
```
```js
const code = query.trim().split(/\s+/).map(w=>w[0]).join('').slice(0,4); // رمز مقترَح
// عند الحفظ: POST /books/api/entities/create/ {name, code, etype, origin:'inline_forge', scan_token}
// النجاح → this.entityList.push(newEnt); ربط الحقل; وسم «جهة جديدة»
```
> ملاحظة تنفيذ: يتطلّب endpoint إنشاء جهة خفيف (قد يوجد جزئياً — يُتحقّق). حقل `origin` + قبول `scan_token` إضافتان صغيرتان تُغذّيان حلقة التدريب.

---

## خيط ناظم عبر الأفكار الثلاث

الثلاث تشترك في **قاعدة واحدة رصينة**: تقاعُد `style.cssText` inline والإيموجي، ونقل كل شيء إلى `extraction_smart.css` بلغة **تركوازية موحّدة** (`#0f766e` — نفس علامة DocCanvas/docman) بدل البنفسجي العام — فتُعالَج نقطة الألم اللونية #1 (التشتّت) داخل عدسة الجهات نفسها. وكلها تحترم `prefers-reduced-motion` وخفيفة على 8GB (لا blur، لا مكتبات، حركات ≤160ms).

**الأولوية الموصى بها:** الفكرة 1 أولاً (أعلى أثر/أدنى كلفة — البيانات مُنتَجة أصلاً وتُهدَر)، ثم 2 (تطبيع عربي مجاني)، ثم 3 (تتطلّب endpoint).

**ملفات التنفيذ:**
- `static/extraction_smart.js` — `displayEntitySuggestions` (سطر 2989)، `applyExtractionResult` (سطر 2708، توصيل top-3 المهدور)، مستمع `input`/`blur` (سطر 2913-2966، إزالة الملء الصامت الخطر).
- `static/extraction_smart.css` — كل الأنماط الجديدة (تقاعُد inline).
- `core/extraction/pipeline.py` — سطر ~716 `to_dict`: تصدير `issuing_entity_matches`/`receiving_entity_matches` للعميل (السلك المقطوع الحقيقي).
- `templates/core/extraction_smart_desktop.html` — حاويات `#issuingEntityDropdown`/`#receivingEntityDropdown` (تصبح مضيفة للبطاقة/DYM/Forge).

### عدسة 6 — الحيّز والحركة

الآن لديّ الحقيقة المكانية الكاملة: `.form-group-smart` تحوي `.label-with-confidence` (label + `confidence-badge`)، شبكة `.field-grid-two`، والمعاينة اللاصقة في العمود الأيسر. الأفكار التالية تبني على هذه الهياكل الموجودة بالضبط — لا تخمين.

---

# ثلاث أفكار مكانية (spatial) — «آلة راقية موثوقة» لواجهة الإدخال الذكي

عدستي: الحيّز والحركة. كل فكرة تستثمر بنية العمودين القائمة وتحوّل ميزاتنا الفريدة (الثقة لكل حقل / حلقة الالتقاط / رابط الجهات) من بيانات مخفيّة إلى **مكان مادّي يتحرّك**.

---

## الفكرة ١ — «خيط الثقة» (The Confidence Ledge): حافة يسارية للحقل تحمل حالة OCR مكانياً

### الوصف البصري الدقيق
اليوم الثقة شارة معلّقة أعلى الحقل (نسبة مئوية جامدة، 3 حقول فقط، ومعطّلة أصلاً في مسار المسح). المقترح: نقل الثقة من «شارة» إلى **بُعد مكاني للحقل نفسه** — حافّة رفيعة (4px) على الحدّ الابتدائي للحقل (في RTL: الحافة اليمنى للـ`input`)، تمتدّ بطول الحقل كـ«عمود ثقة».

- **الحقل عالي الثقة (≥0.85):** الحافة خضراء صلبة `#16a34a`، بلا حركة. الحقل يبدو «مستقرّاً».
- **الحقل متوسّط الثقة (0.65–0.85):** الحافة كهرمانية `#d97706`، وتُطبع على خلفية الحقل تدرّجاً خفيفاً جداً (`linear-gradient` كهرماني 3% opacity) — «يحتاج نظرة».
- **الحقل منخفض الثقة (<0.65):** الحافة حمراء `#dc2626`، وترتفع الحافة من الأسفل للأعلى كـ«تعبئة» عند الاستخراج (مؤشّر أن هذا حقل مرشَّح للمراجعة الأولى).
- **اللمسة المكانية الحاسمة:** حين يبدأ المستخدم الكتابة/التصحيح في حقل، الحافة **تنزلق للخارج وتتلاشى** (`transform: scaleY(0)` من الأعلى) — أي «أنت تولّيت هذا الحقل، ثقة OCR لم تعد ذات صلة». الحقل يتحوّل من «مقروء آلياً» إلى «مؤكَّد بشرياً» بحركة مكانية واحدة.

مصدر الترتيب المكاني للمراجعة موجود أصلاً: `_focusFirstReviewField` بأولوية `[title, senderNumber, issuingEntity, receivingEntity, secretLevel]` وعتبة 0.65. نجعل هذا الترتيب **مرئياً**: الحقول ذات الحافة الحمراء/الكهرمانية تحمل شارة ترتيب صغيرة «١ / ٣» في زاوية الحافة تشير لموضعها في طابور المراجعة.

### لماذا تُبهر
الفريق يفكّر في «تحسين الشارة». هذا يلغي الشارة كفكرة ويحوّل الثقة إلى **خاصية فيزيائية للحقل** — تُقرأ بلا قراءة نصّ، بالمسح البصري المحيطي لعمود واحد من الحواف الملوّنة على يمين النموذج. المستخدم يرى «شكل الثقة» للمستند كله في لمحة (كم حافة حمراء؟)، وهذا هو جوهر العدسة المكانية: المعلومة أصبحت طوبوغرافيا. وتلاشي الحافة عند التصحيح يحلّ الاختناق الأخطر الموثَّق (المسار الرئيسي بلا شارات ثقة) بجعل الثقة تُطبَّق على **كل** الحقول عبر مسار موحّد، لا على 3 حقول في مسار واحد.

### رسم التنفيذ
البنية موجودة: نضيف عنصراً واحداً داخل `.form-group-smart` ونوحّد الملء.

```html
<!-- داخل .form-group-smart، قبل الـ input -->
<div class="form-group-smart" data-conf="pending">
  <div class="label-with-confidence"> ... </div>
  <div class="field-shell">
    <span class="conf-ledge" aria-hidden="true"></span>   <!-- الحافة -->
    <input class="form-control-smart" id="title">
  </div>
</div>
```

```css
.field-shell { position: relative; }
.conf-ledge {
  position: absolute; inset-block: 6px; inset-inline-start: 0;  /* RTL: يمين */
  inline-size: 4px; border-radius: 4px;
  transform-origin: bottom;
  transform: scaleY(0);
  transition: transform .4s cubic-bezier(.2,.7,.2,1), background-color .2s;
}
[data-conf="high"]   .conf-ledge { background:#16a34a; transform:scaleY(1); }
[data-conf="medium"] .conf-ledge { background:#d97706; transform:scaleY(1); }
[data-conf="low"]    .conf-ledge { background:#dc2626; transform:scaleY(1); }
[data-conf="medium"] .form-control-smart { background:linear-gradient(90deg,#fffaf0,#fff); }
/* التلاشي عند التصحيح البشري */
[data-conf][data-touched] .conf-ledge { transform: scaleY(0); opacity:0; }
@media (prefers-reduced-motion: reduce){ .conf-ledge{ transition:none; } }
```

```js
// نقطة الربط الوحيدة: توحيد المسارين (ب و ج) عبر دالة واحدة
setFieldConfidence(fieldId, score){
  const g = document.getElementById(fieldId)?.closest('.form-group-smart');
  if(!g) return;
  g.dataset.conf = score>=0.85?'high':score>=0.65?'medium':'low';
  // عند أول input بشري: علّم الحقل كمؤكَّد → الحافة تتلاشى
  const inp = g.querySelector('.form-control-smart');
  inp?.addEventListener('input', ()=> g.dataset.touched='1', {once:true});
}
```
هذا يُستدعى من **كلا** `_fillExtractionFields` و`applyExtractionResult` — فيُصلح ازدواج المسار ويُشعِل الثقة في مسار المسح الرئيسي بسطر واحد لكلٍّ.

---

## الفكرة ٢ — «جسر الجهة» (Entity Bridge): ربط TF-IDF كخطّ مكاني يعبر من الحقل إلى لوحة المعاينة

### الوصف البصري الدقيق
اليوم منسدلة الجهات قائمة نصّية (اسم + كود) بأنماط inline، ودرجات TF-IDF top-3 مهدورة تماماً، والملء التلقائي عند `blur` يستبدل نص المستخدم صامتاً (خطر حكومي). المقترح يستثمر أن **المستند مرئيّ دائماً في العمود الأيسر** (المعاينة اللاصقة) — نبني علاقة مكانية بين الاسم في المستند والاقتراح.

عند التركيز في حقل جهة، تنبثق منسدلة top-3 لكن بتصميم «مقياس»:
- كل اقتراح صفّ فيه: اسم الجهة + كودها + **شريط تشابه أفقي** (طول الشريط = درجة TF-IDF، ٠–١٠٠٪) + النسبة رقماً صغيراً.
- **الترتيب المكاني:** top-1 أعرض شريطاً وأعلى، والفجوة بين top-1 و top-2 مرئية بصرياً (إن كان top-1 حاسماً: شريطه ممتلئ وله حدّ يسار أخضر «تطابق واثق»؛ إن كانت الدرجات متقاربة: الأشرطة متساوية وبلا أخضر = «راجع بنفسك»).
- **اللمسة المكانية الجريئة (الجسر):** عند تمرير المؤشّر على اقتراح، يُرسَم **خط سيرو (SVG) رفيع منحنٍ** يعبر من صفّ الاقتراح، عبر الفراغ بين اللوحتين، إلى موضع اسم الجهة داخل صورة المستند في المعاينة (إن توفّر bbox من OCR؛ وإلا يومض عنوان لوحة المعاينة). الخط يقول مكانياً: «هذا الاقتراح مصدره هذا الموضع في مستندك».
- إلغاء الملء التلقائي عند `blur`: يُستبدل بـ**تثبيت** — لا يُكتب شيء حتى ينقر المستخدم الاقتراح أو يضغط Enter عليه. إن غادر الحقل باسم لا يطابق شيئاً، يبقى نصّه كما هو مع حافة كهرمانية «جهة جديدة؟».

### لماذا تُبهر
لا أحد يربط الاقتراح بموضعه في المستند. «الجسر» يحوّل الفراغ بين اللوحتين — الذي يعتبره الفريق مجرّد `gap:28px` — إلى **قماش علائقي**. هذا يعطي إحساس «آلة تفهم مستندك» لا «قائمة اقتراحات». وإظهار درجات TF-IDF كأشرطة يجعل قرار المستخدم مبنيّاً على معلومة (فجوة الثقة بين top-1 و top-2)، ويقتل الملء الصامت الخطر باستبداله بفعل مقصود. كل هذا CSS/SVG خفيف — لا مكتبة.

### رسم التنفيذ
```html
<div class="entity-suggest" role="listbox">
  <button class="ent-row is-top" role="option">
    <span class="ent-name">مديرية التربية</span><span class="ent-code">TRB-01</span>
    <span class="ent-bar"><i style="inline-size:92%"></i></span><span class="ent-score">٩٢٪</span>
  </button>
  <!-- top-2, top-3 ... -->
</div>
<svg class="entity-bridge" aria-hidden="true"><path/></svg> <!-- طبقة أعلى الحاوية -->
```
```css
.ent-row{ display:grid; grid-template-columns:1fr auto 80px auto; gap:10px;
  align-items:center; padding:9px 12px; border:0; background:transparent; text-align:start; }
.ent-row:hover,.ent-row:focus-visible{ background:#f1f5f9; }
.ent-bar{ block-size:6px; background:#e2e8f0; border-radius:6px; overflow:hidden; }
.ent-bar i{ display:block; block-size:100%; background:#0f766e; border-radius:6px;
  transition:inline-size .35s cubic-bezier(.2,.7,.2,1); }        /* ينمو عند الفتح */
.ent-row.is-top{ border-inline-start:3px solid #16a34a; }        /* تطابق واثق فقط */
.entity-bridge{ position:absolute; inset:0; pointer-events:none; overflow:visible; }
.entity-bridge path{ fill:none; stroke:#0f766e; stroke-width:1.5; stroke-dasharray:4 4;
  opacity:0; transition:opacity .2s; }
.entity-bridge.show path{ opacity:.55; animation:dash 12s linear infinite; }
@keyframes dash{ to{ stroke-dashoffset:-200; } }
```
```js
// عند hover على اقتراح: ارسم منحنى بيزييه من الصفّ إلى موضع bbox في المعاينة
drawBridge(rowEl, bbox){
  const a = rowEl.getBoundingClientRect(), host = container.getBoundingClientRect();
  const x1=a.left-host.left, y1=a.top-host.top+a.height/2;
  const t = mapBboxToPreview(bbox); // من OCR؛ fallback: مركز عنوان المعاينة
  path.setAttribute('d',`M${x1},${y1} C${x1-120},${y1} ${t.x+120},${t.y} ${t.x},${t.y}`);
  bridgeSvg.classList.add('show');
}
```
`is-top` يُضاف فقط إن `score1 - score2 > 0.15` (فجوة حاسمة) — القرار المكاني يعكس اليقين الإحصائي.

---

## الفكرة ٣ — «أثر التعلّم» (Learning Trace): حلقة الالتقاط تُصبح حركة مكانية من الحقل المصحَّح إلى «ذاكرة» النظام

### الوصف البصري الدقيق
الميزة المميِّزة — كل تصحيح يدرّب النموذج عبر `scan_token` — **غير مرئية إطلاقاً**. لا feedforward ولا feedback. المقترح يعطيها مكاناً وحركة، بلا ثرثرة.

- **العنصر المكاني الثابت:** في رأس لوحة النموذج (أو بجوار شارة وضع المسح)، «بذرة تعلّم» صغيرة جداً — أيقونة Bootstrap `bi-cpu` أو نقطة مع حلقة رفيعة، محايدة رمادية في السكون. هذا «مستودع» النظام مكانياً.
- **الحركة عند التصحيح:** حين يصحّح المستخدم حقلاً كان OCR قد ملأه (أي `data-touched` صار `1` على حقل كانت له حافة ثقة)، تنطلق **شرارة مكانية**: نقطة ضوئية صغيرة بلون النوع تنفصل من حافة الحقل المصحَّح، تسافر بمسار منحنٍ قصير (200ms، `cubic-bezier`) عبر النموذج إلى «بذرة التعلّم»، وتُمتصّ فيها — فتنبض البذرة نبضة واحدة خافتة وتضيف علامة صغيرة (زيادة عدّاد «٣ تصحيحات ستُعلّم النظام»).
- **عند الحفظ:** البذرة تُطلق حركة «ختم» واحدة — حلقتها تكتمل (`stroke-dashoffset` من ٠ إلى محيط كامل) بلون أخضر، مع نصّ خافت يتلاشى: «تعلّم النظام من ٣ تصحيحات». هذا هو feedback حلقة الالتقاط: مرئي، لحظي، غير مزعج.
- **حماية سلامة الحلقة:** بصرياً نربط `scan_token` بالجلسة الحالية — البذرة «تُطفأ» (رمادية بلا حلقة) فور بدء كتاب جديد بلا `scan_token`، فيفهم المستخدم أن هذا الكتاب لا يُدرّب النموذج (لا مستند ممسوح). هذا يعالج بصرياً اختناق «scan_token لا يُعاد ضبطه».

### لماذا تُبهر
هذه الميزة هي تفرّد المنتج، والفريق لم يفكّر في تمثيلها إطلاقاً. تحويلها إلى **حركة مكانية للجُسيم** (correction → memory) يجعل المستخدم يشعر أنه «يبني» شيئاً مع كل تصحيح — تحفيز نفسي حقيقي يرفع جودة التصحيحات (وهي وقود النموذج). والحركة موجزة، هادفة، بلا نبض دائم — تحترم «الرصانة» بعكس اللمعان الحالي. البذرة المُطفأة تجعل حالة «هل يُدرَّب النظام؟» مكاناً مرئياً بدل حالة خفيّة في الذاكرة.

### رسم التنفيذ
```html
<div class="learn-seed" id="learnSeed" title="ذاكرة التعلّم" data-armed="0">
  <svg viewBox="0 0 24 24"><circle class="ring" cx="12" cy="12" r="10"/></svg>
  <span class="learn-count" hidden>٠</span>
</div>
```
```css
.learn-seed .ring{ fill:none; stroke:#cbd5e1; stroke-width:2;
  stroke-dasharray:63; stroke-dashoffset:63; transition:stroke-dashoffset .5s ease, stroke .3s; }
.learn-seed[data-armed="1"] .ring{ stroke:#0f766e; }
.learn-seed.saved .ring{ stroke:#16a34a; stroke-dashoffset:0; }
.learn-spark{ position:absolute; inline-size:8px; block-size:8px; border-radius:50%;
  background:var(--kind-color,#0f766e); pointer-events:none;
  transition:transform .22s cubic-bezier(.4,0,.2,1), opacity .22s; }
@media (prefers-reduced-motion: reduce){ .learn-spark{ display:none; } }
```
```js
onCorrection(fieldEl){                 // يُنادى عند أول input بشري على حقل كان OCR
  if(!this.scanToken) return;          // لا مستند ممسوح ⇒ لا تدريب ⇒ لا شرارة
  const s = fieldEl.getBoundingClientRect(), d = learnSeed.getBoundingClientRect();
  const spark = document.createElement('span'); spark.className='learn-spark';
  spark.style.insetInlineStart = s.right+'px'; spark.style.top = s.top+'px';
  document.body.append(spark);
  requestAnimationFrame(()=>{ spark.style.transform =
    `translate(${d.left-s.right}px, ${d.top-s.top}px)`; spark.style.opacity='0'; });
  spark.addEventListener('transitionend', ()=>{ spark.remove();
    learnSeed.dataset.armed='1'; bumpLearnCount(); });
}
onSaveSuccess(){ learnSeed.classList.add('saved'); showFadeNote('تعلّم النظام من '+n+' تصحيحات'); }
```
البذرة تُربط بـ`this.scanToken`: `data-armed` يُضبط على `0` والحلقة تُطفأ فور `smartClearAndStay` إن لم يوجد رمز جديد — feedback مكاني لسلامة حلقة التدريب.

---

## كيف تتكامل الأفكار الثلاث مكانياً (لماذا تُبهر كنظام واحد)
تُقرأ يميناً-ليساراً كـ**تدفّق مكاني للثقة**: الحافة (١) تُظهر ثقة OCR على الحقل ← التصحيح يُطفئ الحافة ويُطلق شرارة (٣) نحو ذاكرة النظام ← جهات الحقل تُربط بالمستند عبر الجسر (٢) الذي يعبر الفراغ إلى المعاينة اليسرى. الحركة الوحيدة المسموحة في الواجهة تصبح **هادفة واتّجاهية**: من قراءة الآلة (يمين) نحو تأكيد الإنسان وذاكرة النظام — وهذا يبرّر تهدئة كل النبضات/اللمعان الزخرفية الحالية (نقطة الألم ٥) ويستبدلها بلغة حركة واحدة رصينة. الثلاث تُنفَّذ بـ CSS transforms + SVG خفيف فقط (مناسب 8GB)، وكلها RTL-أصيلة عبر `inset-inline-start`/`text-align:start`.

### أثر جانبي معماري (قيمة إضافية)
الفكرة ١ تفرض توحيد `_fillExtractionFields` و`applyExtractionResult` خلف `setFieldConfidence` واحدة — فتُصلح **أخطر اختناق وظيفي موثَّق** (المسار الرئيسي بلا ثقة/بلا تفعيل حفظ) كأثر جانبي للتصميم، لا كإصلاح منفصل.

**ملاحظة:** لم أعدّل أي ملف — قراءة فقط لتثبيت دقّة الرسوم على الهياكل الفعلية (`.form-group-smart` + `.label-with-confidence`، شبكة `1.55fr/1fr`، `_focusFirstReviewField`، `updateConfidenceBadge`).

الملفات المرجعية:
- `C:\Users\fwz\Downloads\lettersys_django_bootstrap_v4_scan\lettersys_django_bootstrap_v4_scan\lettersys_project\templates\core\extraction_smart_desktop.html`
- `C:\Users\fwz\Downloads\lettersys_django_bootstrap_v4_scan\lettersys_django_bootstrap_v4_scan\lettersys_project\static\extraction_smart.css`
- `C:\Users\fwz\Downloads\lettersys_django_bootstrap_v4_scan\lettersys_django_bootstrap_v4_scan\lettersys_project\static\extraction_smart.js`


---

## ملحق: خريطة الواجهة الحالية (فهم الفريق)


I now have a complete picture of the interface. Here is my UX map.

---

# خريطة UX — واجهة «الإدخال الذكي» (extraction_smart_desktop)

## 1. التخطيط العام (Layout)

**نمط «تطبيق سطح مكتب» بشاشة واحدة (single-viewport app-shell):**
- `body.app-shell-body` يُخفي الشريط العلوي الافتراضي (`.app-topbar`)، يقفل `overflow:hidden` على `html/body`، ويجعل الارتفاع `100vh` بلا تمرير للصفحة كاملة. الصفحة نافذة مقفلة، لا مستند طويل.
- **شريط رأس مخصّص** (`.app-page-header`): شعار الشركة + «نظام الكتب» + فاصل + عنوان «الإدخال الذكي» + spacer + التنبيهات + المستخدم. خلفيته بنفسجي متدرّج `#667eea→#764ba2`.
- **الجسم = شبكة عمودين** (`.extraction-container`، CSS Grid):
  - العمود الأيمن (RTL: بصرياً يمين) عريض ≈ 1.55fr = **لوحة النموذج** (الإدخال).
  - العمود الأيسر ≈ 1fr (min 420px) = **لوحة المعاينة الدائمة** (المستند).
  - كل لوحة قابلة للتمرير داخلياً وحدها؛ الحاوية نفسها `overflow:hidden`.
- **اللوحة اليسرى (المعاينة)** بطاقة بيضاء لاصقة (sticky) بارتفاع كامل، رأسها بنفسجي متدرّج نفسه، وقابلة للطيّ (`.preview-collapsed`) عبر زر همبرغر يحوّل الشبكة لعمود واحد ويكبّر الحقول بانتقال ناعم.

**داخل لوحة النموذج — شبكة فرعية** (`.desktop-workbench`، عمودان: 1.25fr / 0.85fr):
- عمود رئيس: تبويبات التصنيف + قسم «بيانات الكتاب الأساسية» (double).
- عمود جانبي مكدّس (`.desktop-sidebar-stack`): «الجهات المرتبطة» + «الخصائص والأرشفة» + ودجة «آخر الكتب».
- في الأسفل شريط إجراءات ثابت (relative داخل app-shell، لا sticky).

---

## 2. المكوّنات الرئيسية

**أ. تبويبات التصنيف (`.kind-tabs`)** — 4 تبويبات أفقية متساوية (وارد داخلي/خارجي، صادر داخلي/خارجي) + زر ترس للإعدادات. كل تبويب: نقطة ملوّنة + تسمية + شارة رقم القيد التالي. لكل نوع لون هوية عبر CSS vars:
- وارد داخلي: تركوازي `#0f766e` · وارد خارجي: أزرق `#0369a1` · صادر داخلي: كهرماني `#b45309` · صادر خارجي: عنّابي `#9f1239`.
- الحالة `.active`: خلفية ناعمة بلون النوع + حلقة توهّج (`box-shadow` مزدوج). شارات حالة الحجز (fresh/warn/critical/expired) عبر `inset box-shadow` سفلي ملوّن + نبض للحرِج.

**ب. قسم «بيانات الكتاب الأساسية»** — أزواج حقول (`.field-grid-two`):
- رقمنا (readonly، خلفية متدرّجة بنفسجية-زرقاء، خط Cairo/monospace) + شارة ثقة + شريحة «حجز شبكي مفعل» + toggle «بلا رقم» للداخلي.
- تاريخنا (معطّل افتراضياً، يُفعّل بزر قلم toggle) + شارة ثقة.
- رقم/تاريخ الجهة المرسلة.
- العنوان (مع Ghost text تنبّؤي: لاحقة إكمال + كلمة تالية مائلة بألوان ترابية `#7c6b52/#a0956a` + تلميح [Tab]).
- **بطاقة المتابعة الزمنية** (`.followup-card`): مفتاح تبديل (switch) كهرماني؛ عند التفعيل تكشف حقل تاريخ الاستحقاق مع مفتاح ألوان الحالة (أزرق/كهرماني/أحمر).

**ج. قسم «الجهات المرتبطة»** — حقلا وسوم متعدّدة (`.multi-tag-wrapper`): جهة الإصدار + جهة الاستقبال. وسوم موجودة زرقاء `#e0f2fe/#0369a1`، وسوم جديدة كهرمانية `#fef3c7/#92400e`. قائمة اقتراحات منسدلة + خيار «إضافة كجهة جديدة» أخضر.

**د. قسم «الخصائص والأرشفة»** — مستوى السرية (select) + نوع المستند (select + حقل مخصّص) + ملاحظات (textarea 6 أسطر + عدّاد /1000).

**هـ. ودجة «آخر الكتب المسجّلة»** — قائمة روابط مدمجة (شارة نوع + رقم + عنوان) في قاع العمود الجانبي، وضع الإدخال فقط.

**و. شريط الإجراءات (`.action-bar`)** — مؤشّر تحقّق (validation pill يتحوّل pending→success) + إلغاء + استخراج + حفظ الكتاب. أزرار primary بنفسجية متدرّجة.

**ز. لوحة المعاينة (اليسرى):**
- رأس (بنفسجي متدرّج): أيقونة + «معاينة المستند» + معلومات الملف (LTR) + مُرقّم صفحات (pager) شفّاف.
- جسم (`DocCanvas`): «ورقة على مكتب» — خلفية متدرّجة شعاعية رمادية، صفحة بيضاء بظل ناعم، `object-fit:contain` (ملاءمة تلقائية)، هيكل عظمي (skeleton) بوميض RTL، تلاشٍ عند التحميل (`.dc-loaded`)، أشرطة أدوات/تكبير عائمة، حالة خطأ.
- **الحالة الفارغة (empty-state / dropZone):** أيقونة 📄 + «اسحب الملف هنا أو اضغط للرفع» + تلميح. تفاعل السحب: `.is-dragover` (خلفية زرقاء + حدود متقطّعة + «⬇️ أفلِت الملف هنا»).
- شريط مصغّرات الصفحات (thumbs، عند التعدّد، قابل لإعادة الترتيب بالسحب).
- لوحة إدارة المستندات (`docman`، وضع التعديل): بطاقات مرفقات بأيقونات ملوّنة حسب النوع + أزرار + حوارات أنيقة.
- **شريط أزرار المسح** (`.scan-action-bar`): حالة وكيل المسح (نقطة ملوّنة: checking/ready/scanning/error) + اختيار جهاز + شارة «تلقائي ذكي» بنفسجية + حذف/رفع/**مسح من السكانر** (زر primary أخضر للوارد أو كهرماني للصادر).

---

## 3. اللغة البصرية (Design Language)

**الألوان:**
- **العلامة البنفسجية المزدوجة `#667eea→#764ba2`** هي الهوية المسيطرة: رأس الصفحة، رأس المعاينة، أزرار primary، تركيز الحقول. **لكنها لا تتّسق مع ألوان هوية الأنواع الأربعة** (تركوازي/أزرق/كهرماني/عنّابي) — ازدواج في اللغة اللونية.
- palette رمادي Slate متّسق (`#e2e8f0` حدود، `#64748b/#94a3b8` نص ثانوي، `#f8fafc/#fafbfc` خلفيات).
- ألوان دلالية ثابتة: أخضر `#16a34a` (ثقة عالية/نجاح)، كهرماني `#d97706` (ثقة متوسطة/pending)، أحمر `#dc2626` (خطأ/متأخر).
- **DocCanvas يقدّم نظام tokens خاص (`--dc-*`) وعلامته تركوازية `#0f766e`** — و`docman` كذلك (`--dm-accent:#0f766e`). فهناك **ثلاثة أنظمة لونية متجاورة**: بنفسجي (الهيكل)، تركوازي (المعاينة/المستندات)، وألوان الأنواع.

**الخطوط:** Cairo (موروثة عبر `font-family:inherit`)؛ رقمنا بـ monospace + tabular-nums. أحجام مضغوطة في وضع app-shell (labels ~0.85rem، حقول ~0.9rem، تلميحات ~0.72rem).

**المسافات والزوايا:** أنصاف أقطار سخيّة (10–16px للبطاقات، 999px للحبوب). ظلال ناعمة متدرّجة الشدّة. فجوات مضغوطة بـ `!important` في app-shell (10–12px) — كثافة عالية مقصودة لملء الشاشة.

**الحركة:** غنية جداً — `cubic-bezier(.4,0,.2,1)` سائد، رفع `translateY(-1/-2px)` على hover لكل شيء تقريباً، نبضات (`pulse`, `fallback-pulse`, `tab-critical-pulse`, `scanPulse`)، انزلاقات دخول (`slideIn/slideInRight/slideInUp`)، شمر skeleton، لمعان أزرار السكانر «الملكية».

---

## 4. الحالات المرئية (Visual States)

- **الثقة (confidence):** 3 شارات — high أخضر / medium كهرماني / low أحمر، بنقطة نابضة. تظهر بجانب رقمنا/تاريخنا/العنوان عند الاستخراج.
- **التحقق:** حقول `has-error` (حدود حمراء + خلفية) / `is-valid` (خضراء). wrapper الجهات `has-error`. مؤشّر شريط الإجراءات pending↔success.
- **fallback banner:** كهرماني نابض عند فشل الذكاء الاصطناعي (بيانات افتراضية).
- **حالة الحجز على التبويب:** خطّ سفلي ملوّن (fresh/warn/critical-نابض/expired).
- **المعاينة:** فارغة / سحب (dragover) / تحميل (skeleton+spinner+overlay) / محمّلة (dc-loaded) / خطأ.
- **وكيل المسح:** checking رمادي / ready أخضر / scanning كهرماني / unavailable أحمر.
- **الطيّ:** المعاينة `is-hiding`→`is-hidden`؛ الحاوية `preview-collapsed` (عمود واحد + حقول أكبر).
- **وضع التعديل:** شارة صفراء «وضع التعديل — الكتاب #…»، إخفاء زر الاستخراج، تفعيل docman.

---

## 5. نقاط الألم والفرص البصرية

**نقاط ألم:**
1. **تشتّت لوني (الأخطر):** ثلاثة أنظمة ألوان متنافسة — بنفسجي الهيكل، تركوازي المعاينة/`docman`، وألوان الأنواع الأربعة. البنفسجي `#667eea` عام/مبتذل (AI-generic) ولا صلة له بهوية «مراسلات حكومية رصينة»، ويتصادم مع تركوازي الوارد الداخلي في التبويب النشط.
2. **الثقة (confidence) موظَّفة ضعيفاً:** مجرد نسبة مئوية جامدة بجانب 3 حقول فقط. السياق المميّز (ثقة لكل حقل) لا يُترجَم بصرياً على الحقل نفسه (لا حدّ ملوّن للحقل منخفض الثقة، لا ترتيب مراجعة). فرصة ضائعة كبرى.
3. **حلقة التقاط التدريب غير مرئية إطلاقاً:** ميزة التفرّد (كل تصحيح يدرّب النموذج) لا أثر لها بصرياً — لا تغذية راجعة تُظهر للمستخدم أن تصحيحه «علّم» النظام.
4. **رابط الجهات TF-IDF (top-3 + درجات) مُهدَر:** القائمة المنسدلة تعرض اسماً + كود فقط، بلا درجة تشابه ولا تمييز top-3، مع أنماط inline في JS (`item.style.cssText`) خارج ملفات CSS — تلوّث للفصل بين البنية والأسلوب.
5. **إفراط في الحركة:** نبضات + لمعان + رفع hover في كل مكان يُنهك بصرياً ويخالف «الرصانة/البساطة»، وثقيل على جهاز 8GB (backdrop-filter blur في عدة مواضع).
6. **أنماط inline كثيرة في القالب** (dropdowns الجهات، شارة وضع التعديل، toggles) — صعوبة صيانة وتناقض مع ملفات CSS المنظّمة.
7. **إيموجي نظام التشغيل** (📄🔍✓✕➕⬇️) مختلط مع أيقونات Bootstrap — عدم اتّساق أيقوني، ومظهر أقل رصانة.
8. **ازدحام app-shell:** كثرة `!important` وتصغير عدواني (تلميحات 0.72rem) قد يضغط القراءة في RTL.

**فرص:**
- توحيد اللغة اللونية حول محور واحد رصين (تركوازي/كحلي حكومي) واعتماد ألوان الأنواع كلكنات فقط، وتقاعُد البنفسجي العام.
- ترجمة الثقة على الحقل نفسه (شريط/حدّ ملوّن + فرز «يحتاج مراجعة») بدل نسبة مجرّدة.
- إبراز حلقة التدريب بلمسة تغذية راجعة دقيقة عند التصحيح («تم التعلّم من تصحيحك»).
- إظهار درجات TF-IDF و top-3 بصرياً في منسدلة الجهات، ونقل أنماطها إلى CSS.
- تهدئة الحركة (احترام `prefers-reduced-motion` موجود جزئياً في doc_canvas فقط — يجب تعميمه) لصالح الرصانة والأداء.
- توحيد الأيقونات على Bootstrap Icons وإزالة إيموجي OS.

**الملفات:**
- `templates/core/extraction_smart_desktop.html`
- `static/extraction_smart.css`
- `static/css/doc_canvas.css`
- `static/css/document_manager.css`


I've now read the complete logic file (all 3590 lines). I have a full map of the interaction model. Here is my focused analysis.

---

# خريطة تفاعل «الإدخال الذكي» — تحليل `static/extraction_smart.js`

كل المنطق داخل صنف واحد `ExtractionSmartSystem` (سطر 18–3561)، يُنشَأ مرة واحدة عند تحميل DOM ويُعرَّض عالمياً كـ `window.extractionSystem`. الحالة كلها حقول نسخة (instance fields)، بلا مخزن مركزي.

## 1. تدفّق المستخدم (مسح ← استخراج ← مراجعة ← حفظ)

يوجد **ثلاثة مداخل** للمستند تلتقي جميعاً عند نفس معاينة الصفحات المُخدَّمة خادمياً (server-rendered) ثم عند نفس منطق المراجعة/الحفظ:

**المدخل أ — مسح ضوئي (`startScan`, سطر 1457):** المسار الرئيسي المقصود.
1. `startScan({append})` → يعطّل الزر، يُظهر `scanProgress` + زر إلغاء ديناميكي، يضبط الحبّة على `scanning`.
2. سلسلة استدعاءات مُسَلسَلة كلها بمهل زمنية (`_fetchWithTimeout`): `/scan/agent-token/` → `_resolveAgentBase` (يجرّب `127.0.0.1` ثم `localhost`) → فحص `naps2_available` → `/agent/devices` → `/agent/scan` (mode:auto، مهلة 180 ثانية) يُعيد blob (PDF).
3. رفع الـPDF إلى `/scan/process-upload/` مع `trim_blanks=1` → يُعيد `redirect`.
4. **إعادة توجيه كامل للصفحة** (`window.location.href = ud.redirect`, سطر 1602) — لا SPA. أي تنبيه استخراج يُخزَّن في `sessionStorage` (`lettersys_scan_notice`) ليعيش عبر التنقّل، ثم يُلتقط في الخطوة التالية.

**المدخل ب — إعادة تحميل بعد المسح عبر `scan_token` (`checkScanToken`, سطر 523):** يُستدعى داخل `init()`. يقرأ `?scan_token=` من URL، يجلب `/extract/scan-token/{token}/`، يملأ الحقول عبر `_fillExtractionFields` **دون إعادة OCR** (`noAutoExtract:true`)، يضبط `previewToken`، ينظّف URL بـ `replaceState`. هذا هو المسار الذي يُغلق حلقة المسح←الاستخراج.

**المدخل ج — رفع/سحب يدوي (`processFile`, سطر 2347):** تحقّق نوع/حجم (10MB) → `stageAndPreview` يرفع إلى نفس `/scan/process-upload/` للحصول على `token` موحّد → `loadScannedFile(..., {noAutoExtract:false})` → **استخراج تلقائي بعد 400ms** (سطر 2369, 2722). عند فشل التجهيز الخادمي، سقوط رشيق إلى معاينة عميل محلية.

**مرحلة الاستخراج (`extractData` → `callExtractApi`, سطر 2606, 2652):** تُرسِل `currentFile` إلى `smartExtract` (مهلة 5 دقائق لتحميل النموذج أول مرة). عند النجاح → `applyExtractionResult`. **تحذير: المدخلان (ب) و(ج) يستخدمان دالتَي ملء مختلفتين** — المدخل ب يستخدم `_fillExtractionFields`، المدخل ج يستخدم `applyExtractionResult`. هذا تكرار موثَّق صراحةً كدَيْن (سطر 607–611): «المعرّفات الصحيحة `#date` و `#title`... لم يُدمج المساران بعد».

**مرحلة المراجعة:** بعد الاستخراج، `_focusFirstReviewField` (سطر 2590) يقفز تلقائياً لأول حقل فارغ أو ثقته `< 0.65` بترتيب أولوية `[title, senderNumber, issuingEntity, receivingEntity, secretLevel]`. تحقّق حيّ لكل حقل، شارات ثقة، اقتراحات جهات.

**مرحلة الحفظ (`saveBook` → `submitBookData`, سطر 3342, 3447):** تحقّق الحقول المطلوبة → تحقّق نوع المستند → تأكيد الحفظ بلا مرفق إن لزم → بناء `FormData` → **حلقة `while(true)`** تُعيد المحاولة مرة واحدة تلقائياً عند خطأ حجز قابل للاسترداد. عند النجاح: `smartClearAndStay` + `clearFile` + `ensureReservation` جديد (يبقى في نفس التبويب، جاهز للكتاب التالي).

## 2. الحالات (State)

- **حالة الملف:** `currentFile` (المُرسَل للاستخراج/الحفظ) + `scannedFiles[]` (مصفوفة صفحات للدمج). `hasAttachedFile()` تفحص كليهما.
- **حالة المعاينة:** `previewToken`, `pageCount`, `currentPage`, `zoom`, `previewDpi`, `_previewVersion` (كسر كاش الصور بعد التحرير), `_manifest` (هندسة الصفحات للهيكل العظمي).
- **حالة الاستخراج:** `extractedData`, `confidenceScores`, `suggestionCache`, `fallbackNotified`.
- **حالة الحجز:** `reservations{}` مُفهرَسة بالنوع (per-kind cache) — القلب النابض؛ انظر §4.
- **حالة النوع (kind):** `bookKind` select هو مصدر الحقيقة؛ تبويبات `.kind-tab` تكتب فيه. `getKindConfig` (سطر 632) يحمل كامل النصوص العربية الأربعة لكل نوع (labels/hints/placeholders/showSenderFields).
- **حالة الوكيل:** `_agentBase`, `_agentHealth`, `_agentHealthy`, `_scanDevices`, `_agentMonitorTimer` (نبضة كل 25 ثانية), `_scanCancelled`, `_scanAppendMode`.
- **حالة نوع المستند:** `documentTypeSelectionByKind{}` (اختيار لكل نوع) + `customDocumentTypeCatalog` مُخزَّن في `localStorage`.
- **الرمز الحاسم:** `this.scanToken` (سطر 527) يُلتقط من URL ويُرسَل عند الحفظ (سطر 3421) — هذا هو **رابط حلقة الالتقاط التدريبي**.

## 3. نقاط الربط (Hooks)

**الثقة (Confidence):**
- عتبات موحَّدة `CONFIDENCE_THRESHOLDS = {high:0.85, medium:0.65}` (سطر 16) — موثَّق أنها طُوبِقت مع `ConfidenceAnalyzer` الخادمي (كان JS سابقاً 0.70). فيه `TODO` لإعادة المعايرة بعد استقرار Tesseract.
- `getConfidenceLevel` (سطر 2769) → `updateConfidenceBadge` (سطر 2756) يلوّن شارة `#{field}Confidence` ويكتب النسبة في `#{field}ConfidenceValue`.
- **الثقة تُقاد فقط عبر `applyExtractionResult` (المدخل ج).** المدخل ب (`_fillExtractionFields`) **لا يستدعي `updateConfidenceBadge` إطلاقاً** — فالمستند القادم من `scan_token` يملأ الحقول بلا أي شارات ثقة مرئية، رغم أن `overall_confidence` و`needs_review` متاحان في الرد. هذا اختناق ربط ثقة رئيسي.

**scan_token:** يُلتقط في `checkScanToken` (سطر 527)، يُنظَّف من URL فوراً (`replaceState`)، ويُعاد إرساله عند الحفظ (سطر 3421). حلقة الالتقاط تعتمد كلياً على استمرار `this.scanToken` من لحظة الفتح حتى الحفظ. **اختناق:** إذا مسح المستخدم النموذج (`clearForm`) أو حفظ ثم بدأ كتاباً جديداً، لا يُعاد ضبط `this.scanToken` — قد يُرسَل نفس الرمز لكتاب لاحق (تلوّث حلقة التدريب).

**حلقة الالتقاط (Capture loop):** غير مرئية في الواجهة إطلاقاً — لا يوجد أي مؤشّر بصري يخبر المستخدم أن تصحيحاته ستُدرِّب النموذج. الربط الوحيد هو تمرير `scan_token` الصامت. **فرصة تصميم مهدورة كبرى**: الميزة المميِّزة (كل تصحيح = مثال تدريب) لا صدى لها في التفاعل.

**الجهات (Entities):** نظامان منفصلان يتعايشان:
1. `searchEntities` (سطر 2841) — بحث عميل محلي على `entityList` المُحمَّلة مسبقاً، بأولويات (رمز مطابق تام → يبدأ بـ → يحتوي → اسم). يُغذّي `displayEntitySuggestions` (قائمة منسدلة مبنية يدوياً بأنماط inline).
2. `window.entityTagManagers` (issuing/receiving) — مدير وسوم خارجي (غير معرّف في هذا الملف) تعتمد عليه `isFormReadyForSave`, `commitPendingFieldValue`, `focusFieldById`.
- **لا أثر لـ TF-IDF top-3 المذكور في السياق.** الربط الموجود هو بحث نصي/رمزي محلي فقط. `blur` يملأ تلقائياً بأفضل نتيجة (سطر 2950) — سلوك عدواني قد يستبدل إدخال المستخدم دون تأكيد صريح.

## 4. الاختناقات التفاعلية (أهم النتائج)

1. **ازدواج مسار الملء (ب مقابل ج):** `_fillExtractionFields` و`applyExtractionResult` غير متطابقين. الأول لا يُطلق أحداث `input/change`، لا يحدّث شارات الثقة، ولا يستدعي `updateValidationIndicator`. النتيجة: المستند القادم من مسار المسح الفعلي (المسار الرئيسي!) تظهر حقوله **بلا شارات ثقة وقد لا يُفعَّل زر الحفظ** حتى يلمس المستخدم كل حقل. هذا أخطر اختناق وظيفي.

2. **الثقة معطّلة في المسار الرئيسي:** كما أعلاه — ميزة «ثقة لكل حقل» تعمل فقط في الرفع اليدوي، لا في المسح (الذي هو حالة الاستخدام الأساسية).

3. **قفزة إعادة تحميل الصفحة الكاملة بعد المسح** (سطر 1602): تجربة غير سلسة؛ تعتمد على حيلة `sessionStorage` لنقل التنبيهات. أي حالة عابرة في الذاكرة (مثل `reservations` غير المحفوظة، تصحيحات جزئية) تضيع.

4. **ملء الجهة التلقائي عند `blur`** (سطر 2935–2966): يستبدل نص المستخدم بأفضل تطابق **دون تأكيد**، مع toast «تم المطابقة». في سياق حكومي دقيق، مطابقة خاطئة صامتة خطر حقيقي.

5. **حلقة الالتقاط خفيّة تماماً:** لا feedforward ولا feedback بصري. المستخدم لا يعلم أنه يُدرِّب النموذج، فيُحبَط أثر الميزة المميِّزة.

6. **`scan_token` لا يُعاد ضبطه** بعد الحفظ/المسح: خطر تلوّث بيانات التدريب بربط تصحيحات كتاب بمستند آخر.

7. **تعقيد الحجز مقابل رؤيته:** منطق الحجز (سطر 824–992) رصين جداً (عدّاد تنازلي، ألوان تبويبات، استرداد ذري، void عند المسح). لكنه معقّد جداً نسبياً لما يعرضه المستخدم (شارة رقم على التبويب فقط). العدّاد التنازلي `_ensureReservationCountdown` (سطر 879) يُبدّل ألوان التبويبات وينبّه عند اقتراب الانتهاء — تفاعل غني لكن قد يُشتِّت.

8. **ثلاثة مستمعي `keydown` منفصلون** (سطر 1145, 1167, 1918): اختصارات (Ctrl+E/S/Enter/Esc)، تنقّل النموذج (Tab/Enter مخصّص عبر `getNavigationOrder`)، وتنقّل المعاينة (أسهم RTL). التنقّل المخصّص غنيّ (Enter على آخر حقل = حفظ إن جاهز، سطر 1340) لكن تعدّد المستمعين يزيد خطر تعارض الأولويات.

9. **إعادة رسم القائمة المنسدلة للجهات بأنماط inline** (سطر 2989–3065): كل عنصر يُبنى بـ `style.cssText` مُضمَّن — ثقيل على DOM ومنفصل عن نظام التصميم (لا يحترم `document_manager.css`/RTL identity).

10. **`updateSuggestions` دالة فارغة** (سطر 3252): نقطة ربط لاقتراحات AI حيّة معلّقة/ميتة — تُستدعى من عدة أماكن بلا أثر.

## الملفات ذات الصلة
- المنطق: `C:\Users\fwz\Downloads\lettersys_django_bootstrap_v4_scan\lettersys_django_bootstrap_v4_scan\lettersys_project\static\extraction_smart.js`
- تكرار الملء الحرج: الدالتان `_fillExtractionFields` (سطر 602) و`applyExtractionResult` (سطر 2708).

**قراءة فقط — لم أُجرِ أي تعديل.**
