# مواصفة تنفيذ المرحلة 1 (MVP) — وكيل المسح المحلي لـ LetterSys

**التاريخ:** 2026-06-24 · **المرجع:** قرار المالك #1 (وكيل TWAIN/WIA عام) + قرار #2 (رفع مباشر بلا مجلد وسيط) · **الحالة:** مواصفة تنفيذية جاهزة للكتابة المباشرة · **المراجع التقنية:** `SCAN_AGENT_DESIGN_2026-06-24.md`, `core/views/scan_settings.py`, `core/extraction/pipeline.py::run_ocr_isolated`.

---

## 0. النطاق والقرارات المثبَّتة

| القرار | القيمة المعتمدة في المرحلة 1 |
|--------|------------------------------|
| نوع الماسح | ماسح مستندات ADF عبر USB، **TWAIN أولاً** ثم WIA كاحتياط |
| محرّك المسح | **NAPS2 Console** (`NAPS2.Console.exe`) — يغطّي WIA+TWAIN+ADF+duplex+PDF بأمر واحد |
| احتياط المحرّك | WIA عبر `pywin32` (flatbed صفحة واحدة) — يُبنى فقط إن لزم؛ يجوز تأجيله لنهاية القائمة |
| قناة الإرجاع | **رفع مباشر**: الوكيل يمسح → يقرأ الـPDF → يرسله `multipart` إلى Django مباشرةً → لا مجلد وسيط |
| ربط الشبكة | الوكيل يستمع على `127.0.0.1` فقط على منفذ ثابت **17865** |
| إخراج المسح | **PDF متعدد الصفحات** (NAPS2 يجمّع كل صفحات الـADF في ملف واحد تلقائياً) |
| العمق الافتراضي | `dpi=300`, `bitdepth=color`, `pagesize=a4`, `source=feeder` |

**خارج نطاق المرحلة 1 (يؤجَّل للمرحلة 2):** اختيار جهاز/مصدر/DPI من الواجهة، duplex من الواجهة، بثّ تقدّم حيّ (SSE)، تغليف `.exe`. **في المرحلة 1**: مسح من ADF (وجه واحد) أو flatbed، إعدادات افتراضية ثابتة، استجابة طلب/رد بسيطة.

---

## 1. الأوامر النهائية الدقيقة لـ NAPS2

> جميع الأعلام موثّقة رسمياً وتنطبق على NAPS2 ≥ 7.3.0 وحتى 8.2.1 (المصدر: `naps2.com/doc/command-line`، مُتحقَّق منها). القيم المقبولة: `--driver {twain|wia|escl}` على ويندوز، `--source {glass|feeder|duplex}`، `--bitdepth {color|gray|bw}` (لا تستعمل `grayscale`/`blackwhite`)، `--pagesize {a4|letter|legal|...}`.

### 1.1 المسار التنفيذي (قابل للضبط)
```
المثبّت العادي: C:\Program Files\NAPS2\NAPS2.Console.exe
المحمول:        <agent_dir>\naps2_portable\NAPS2.Console.exe
متغيّر بيئة:    NAPS2_CONSOLE  (له الأولوية)
```

### 1.2 سرد الأجهزة (لنقطة `/agent/devices`)
```bash
# TWAIN أولاً (الأنسب لماسحات ADF عبر USB)
"C:\Program Files\NAPS2\NAPS2.Console.exe" --listdevices --driver twain

# WIA احتياط
"C:\Program Files\NAPS2\NAPS2.Console.exe" --listdevices --driver wia

# escl (ماسحات الشبكة — اختياري، بلا تعريف)
"C:\Program Files\NAPS2\NAPS2.Console.exe" --listdevices --driver escl
```
المخرجات: **اسم جهاز واحد لكل سطر على stdout**. قائمة فارغة = لا أجهزة (الماسح مطفأ/مفصول) — تُعامَل كنجاح بقائمة فارغة لا كخطأ.

### 1.3 المسح الكامل ADF → PDF (لنقطة `/agent/scan`)
```bash
# ADF وجه واحد → PDF متعدد الصفحات (الأمر الأساسي للمرحلة 1)
"C:\Program Files\NAPS2\NAPS2.Console.exe" --noprofile --driver twain --device "<DEVICE_NAME>" --source feeder --dpi 300 --bitdepth color --pagesize a4 -o "<TEMP>\scan.pdf" --force --verbose

# flatbed صفحة واحدة (إن لم يوجد ADF)
"C:\Program Files\NAPS2\NAPS2.Console.exe" --noprofile --driver twain --device "<DEVICE_NAME>" --source glass --dpi 300 --bitdepth bw -o "<TEMP>\scan.pdf" --force

# duplex (متاح للمرحلة 2 — معرَّف هنا للاكتمال)
"C:\Program Files\NAPS2\NAPS2.Console.exe" --noprofile --driver twain --device "<DEVICE_NAME>" --source duplex --dpi 300 --bitdepth gray --pagesize a4 -o "<TEMP>\scan.pdf" --force --verbose
```

### 1.4 قواعد إلزامية (Gotchas مثبَّتة)
- **`--noprofile` إلزامي** عند تمرير أعلام الجهاز مباشرةً؛ بدونه يتوقّع NAPS2 بروفايلاً عبر `-p` ويفشل.
- **`--device` يستلزم `--driver`** دائماً معه.
- مطابقة `--device` **جزئية غير حسّاسة لحالة الأحرف** → مرّر **الاسم الكامل تماماً** كما عاد من `--listdevices` لتفادي اختيار جهاز خاطئ.
- **لا تستخدم `--progress`** (يفتح نافذة GUI ويعطّل التشغيل الصامت). استخدم `--verbose` لالتقاط التقدّم عبر stdout.
- على ويندوز قد يكتب NAPS2 رسائل على stderr مع `returncode=0` → **التحقق من النجاح = `returncode==0` و `os.path.getsize(out) > 0` معاً**.
- لا تستخدم `--email/-e`؛ نكتفي بـ `-o` ثم نقرأ ونرفع ونحذف.

---

## 2. عقد نقاط الوكيل (Agent API)

كل النقاط على `http://127.0.0.1:17865`، تتطلّب رأس `X-LetterSys-Token` (انظر §4)، وترد `application/json` (عدا تدفّق ثنائي PDF عند الحاجة). كل استجابة فشل تتبع الشكل `{"ok": false, "error": "<رسالة>", "code": "<رمز>"}`.

### 2.1 `GET /agent/health`
فحص حياة الوكيل وتوفّر المحرّك. **لا يتطلب token** (يُستخدم للكشف الأولي قبل امتلاك token صالح)، لكنه يُخضع لفحص Origin.

الاستجابة (200):
```json
{
  "ok": true,
  "version": "1.0.0",
  "backend": "naps2",
  "naps2_path": "C:\\Program Files\\NAPS2\\NAPS2.Console.exe",
  "naps2_available": true,
  "platform": "win32"
}
```
إن لم يُعثر على NAPS2: `"naps2_available": false, "backend": "wia"` (أو `"none"` إن لا pywin32).

### 2.2 `GET /agent/devices`
الاستعلام الاختياري: `?driver=twain|wia|escl` (افتراضي `twain`، مع fallback تلقائي إلى `wia` إن كانت قائمة twain فارغة).

الاستجابة (200):
```json
{
  "ok": true,
  "driver": "twain",
  "devices": [
    {"id": "Canon DR-C225 TWAIN", "name": "Canon DR-C225 TWAIN", "driver": "twain"}
  ]
}
```
- `id` و `name` متطابقان (الاسم الكامل هو المعرّف لـ NAPS2).
- قائمة فارغة `"devices": []` = نجاح بلا أجهزة.

### 2.3 `POST /agent/scan`
يمسح فعلياً ويرفع مباشرةً إلى Django ثم يُعيد نتيجة Django للصفحة (**رفع مباشر — لا مجلد وسيط**).

الطلب (JSON):
```json
{
  "device_id": "Canon DR-C225 TWAIN",
  "driver": "twain",
  "source": "feeder",
  "duplex": false,
  "dpi": 300,
  "color": "color",
  "format": "pdf",
  "upload_url": "http://127.0.0.1:8000/books/api/scan/process-upload/",
  "scan_token": "<DJANGO_SCAN_TOKEN>",
  "csrf_token": "<DJANGO_CSRF>"
}
```
الحقول الإلزامية: `device_id`. الباقي افتراضات: `driver=twain`, `source=feeder`, `dpi=300`, `color=color`, `format=pdf`. `upload_url`/`scan_token`/`csrf_token` تُمرَّر من الصفحة (الصفحة تعرف عنوان Django والـtoken).

الاستجابة الناجحة (200): يُمرَّر ناتج Django كما هو إلى الصفحة:
```json
{
  "ok": true,
  "pages": 3,
  "django": {
    "ok": true,
    "token": "<scan_token>",
    "redirect": "/books/extract/smart-desktop/?scan_token=<token>",
    "source_file": "scan.pdf",
    "overall_confidence": 0.82
  }
}
```
استجابات الفشل:
```json
{"ok": false, "code": "no_device",   "error": "لم يُحدَّد جهاز"}
{"ok": false, "code": "scan_failed", "error": "<stderr من NAPS2>"}
{"ok": false, "code": "empty_output","error": "ملف الإخراج فارغ — تحقّق من وجود ورق في الـADF"}
{"ok": false, "code": "upload_failed","error": "تعذّر رفع الملف لـ Django: <تفصيل>"}
```

**سلوك داخلي لـ `/agent/scan`:** (1) يبني أمر NAPS2 إلى ملف مؤقت `tempfile` بامتداد `.pdf`؛ (2) ينفّذ `subprocess.run(..., timeout=300)`؛ (3) يتحقّق `returncode==0` و `getsize>0`؛ (4) يفتح الـPDF بـ PyMuPDF لعدّ الصفحات؛ (5) يرفعه `multipart/form-data` إلى `upload_url`؛ (6) **يحذف الملف المؤقت في `finally`** سواء نجح أم فشل.

---

## 3. عقد نقطة Django للرفع المباشر

### 3.1 المسار والتسجيل
أضِف في `core/urls.py` (بجوار `api/scan/process-local/` القائم):
```python
path("api/scan/process-upload/", views.scan_process_upload, name="scan_process_upload"),
```
الدالة في `core/views/scan_settings.py` — **توأم لـ `scan_process_local_file` الموجود لكن برفع ملف بدل مسار محلي**، وتعيد استخدام نفس `run_ocr_isolated` و `scan_token` cache و `scan_file_serve`.

### 3.2 العقد
`POST /books/api/scan/process-upload/`

| البند | القيمة |
|-------|--------|
| المصادقة | `@login_required` — جلسة Django (نفس المستخدم في المتصفح). الوكيل لا يصادق؛ المتصفح يمرّر cookies الجلسة عبر الـfetch إن كان نفس الأصل، أو يمرّر الوكيلُ ملفَ التعريف. **في المرحلة 1**: الصفحة هي التي ترفع (انظر بديل §3.4) — أنظف للمصادقة. |
| نوع المحتوى | `multipart/form-data` |
| الحقول | `file` (الـPDF، إلزامي)، `source_name` (اسم العرض، اختياري) |
| CSRF | يتطلّب `X-CSRFToken` (الصفحة تملكه). إن رفع الوكيلُ مباشرةً يلزم استثناء CSRF + توثيق بديل — يُفضَّل مسار الصفحة. |

الإخراج الناجح (200) — **مطابق تماماً لإخراج `scan_process_local_file` ليعمل نفس JS**:
```json
{
  "ok": true,
  "token": "<uuid hex>",
  "redirect": "/books/extract/smart-desktop/?scan_token=<token>",
  "source_file": "scan.pdf",
  "overall_confidence": 0.82
}
```
الفشل:
```json
{"ok": false, "error": "file مطلوب"}                  // 400
{"ok": false, "error": "نوع الملف غير مدعوم"}          // 400  (PDF فقط في هذه النقطة)
{"ok": false, "error": "حجم الملف يتجاوز 50 MB"}       // 400
{"ok": false, "error": "فشل الاستخراج: <_error>"}      // 500
```

### 3.3 المنطق الداخلي (إعادة استخدام الموجود حرفياً)
```python
@login_required
@require_http_methods(['POST'])
def scan_process_upload(request):
    """يستقبل PDF مرفوعاً من الوكيل/الصفحة، يحفظه مؤقتاً، يشغّل OCR، يعيد scan_token.
    توأم scan_process_local_file لكن برفع مباشر بدل مسار محلي."""
    import uuid, tempfile, os
    from django.core.cache import cache

    up = request.FILES.get('file')
    if not up:
        return JsonResponse({'ok': False, 'error': 'file مطلوب'}, status=400)

    if os.path.splitext(up.name)[1].lower() != '.pdf':
        return JsonResponse({'ok': False, 'error': 'نوع الملف غير مدعوم'}, status=400)

    MAX_BYTES = 50 * 1024 * 1024
    if up.size > MAX_BYTES:
        return JsonResponse({'ok': False, 'error': 'حجم الملف يتجاوز 50 MB'}, status=400)

    # احفظ في ملف مؤقت دائم نسبياً (يُعرض عبر scan_file_serve من processed_path)
    fd, tmp_path = tempfile.mkstemp(suffix='.pdf', prefix='lettersys_scan_')
    try:
        with os.fdopen(fd, 'wb') as out:
            for chunk in up.chunks():
                out.write(chunk)

        from core.extraction.pipeline import run_ocr_isolated
        data = run_ocr_isolated(tmp_path)          # نفس عملية OCR المعزولة
        if data.get('_error'):
            os.unlink(tmp_path)
            return JsonResponse({'ok': False, 'error': f"فشل الاستخراج: {data['_error']}"}, status=500)

        source_name = (request.POST.get('source_name') or up.name or 'scan.pdf').strip()
        data['source_file']    = os.path.basename(source_name)
        data['processed_path'] = tmp_path          # scan_file_serve يخدمه من هنا

        token = uuid.uuid4().hex
        cache.set(f'scan_token:{token}', data, timeout=86400)
        return JsonResponse({
            'ok': True,
            'token': token,
            'redirect': f'/books/extract/smart-desktop/?scan_token={token}',
            'source_file': data['source_file'],
            'overall_confidence': data.get('overall_confidence'),
        })
    except Exception as exc:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        logger.error('[ScanUpload] failed: %s', exc)
        return JsonResponse({'ok': False, 'error': str(exc)}, status=500)
```
- **`run_ocr_isolated(path)`** يُستدعى كما في `scan_process_local_file` (السطر 663) — تعطّل المحرّك لا يُسقط الخادم.
- **`scan_token` cache** بنفس المفتاح `scan_token:{token}` ومهلة 86400 → يعمل `scan_file_serve` و `smart-desktop` بلا تغيير.
- **`processed_path`** يشير للملف المؤقت → يُعرض في المعاينة عبر النقطة الموجودة.
- ملاحظة تنظيف: الملف المؤقت يبقى لخدمة المعاينة (مثل سلوك `scan_process_local_file` الذي يبقي الملف الأصلي). نظافته اللاحقة تتبع سياسة تنظيف الكاش — خارج نطاق المرحلة 1.

### 3.4 مَن يرفع؟ (قرار التنفيذ)
**المسار المعتمد للمرحلة 1 — الصفحة ترفع، لا الوكيل:**
1. الصفحة → `POST /agent/scan` (بلا `upload_url`) فيُعيد الوكيلُ الـPDF كـ`base64` أو كـ`stream` ثنائي.
2. الصفحة تبني `FormData` وترفعه إلى `POST /books/api/scan/process-upload/` بجلسة المتصفح + CSRF.

هذا يحافظ على **`@login_required` + CSRF القياسيين** بلا استثناءات، ويُبقي Django جاهلاً بالوكيل. (البديل «الوكيل يرفع مباشرةً» متاح لكنه يحتاج تمرير cookies/CSRF للوكيل + استثناء — يؤجَّل.)
بناءً عليه، استجابة `/agent/scan` في المرحلة 1 تكون:
```json
{"ok": true, "pages": 3, "pdf_base64": "JVBERi0xLj..."}
```
والصفحة تتولّى رفعها لـ Django.

---

## 4. مخطّط الأمن العملي

| الطبقة | التنفيذ |
|--------|---------|
| **ربط 127.0.0.1** | الوكيل يستمع على `127.0.0.1` **فقط** (ليس `0.0.0.0`) على المنفذ 17865 → لا وصول من الشبكة المحلية إطلاقاً. |
| **فحص Origin** | على كل طلب: قراءة رأس `Origin` (و`Referer` احتياطاً)؛ يُقبل فقط `http://127.0.0.1:8000` و `http://localhost:8000`. أي أصل آخر → `403`. يحمي من المواقع الخبيثة التي تستغل المتصفح (anti-DNS-rebinding). |
| **CORS** | الرد بـ `Access-Control-Allow-Origin: http://127.0.0.1:8000` (يُعكَس من Origin المقبول)، `Access-Control-Allow-Headers: X-LetterSys-Token, Content-Type`, `Access-Control-Allow-Methods: GET, POST, OPTIONS`. التعامل مع طلب `OPTIONS` preflight بـ`204`. |
| **token مشترك** | Django يولّد `agent_token` في الجلسة (مثلاً عند فتح صفحة المسح) ويضعه في الصفحة (data-attribute/meta). الصفحة ترسله في `X-LetterSys-Token` لكل طلب لـ`/agent/devices` و`/agent/scan`. الوكيل يقرأ التوكِن المتوقَّع من ملف محلي مشترك (انظر أدناه) ويرفض أي طلب بلا تطابق → `401`. (`/agent/health` معفى لأنه كشف مبدئي.) |
| **آلية مشاركة الـtoken** | عند أول تشغيل، الوكيل يكتب توكِناً عشوائياً في `%LOCALAPPDATA%\LetterSys\agent_token.txt`. صفحة Django تقرأه عبر نقطة محلية اختيارية، أو يُلصَق يدوياً مرة في الإعدادات. **مبدأ المرحلة 1 المبسّط:** token ثابت في إعداد مشترك بين الوكيل و`ScanSettings` (حقل جديد `agent_token`) — يكفي لمنع الاستغلال العابر. |
| **حدود التشغيل** | `subprocess timeout=300s` لكل مسح؛ حدّ حجم 50MB في نقطة Django؛ رفض امتدادات غير PDF؛ تنظيف الملف المؤقت في `finally`. |
| **لا أوامر من المستخدم** | معاملات NAPS2 من قائمة بيضاء: `driver∈{twain,wia,escl}`, `source∈{glass,feeder,duplex}`, `color∈{color,gray,bw}`, `dpi` عدد صحيح 100–600. `device_id` يُمرَّر كوسيط منفصل في قائمة `subprocess` (لا shell) → لا حقن أوامر. |

---

## 5. هيكل ملفات الوكيل المقترح

```
scan_agent/                         # حزمة الوكيل المستقلة (خارج Django، تعمل لوحدها)
├── __main__.py                     # نقطة الدخول: python -m scan_agent  → يشغّل الخادم
├── server.py                       # خادم HTTP على 127.0.0.1:17865 + توجيه النقاط + CORS/Origin
├── auth.py                         # قراءة/توليد agent_token + فحص X-LetterSys-Token + فحص Origin
├── naps2.py                        # غلاف NAPS2.Console: locate_exe(), list_devices(), scan_to_pdf()
├── wia_fallback.py                 # (اختياري/مؤجَّل) WIA عبر pywin32 — flatbed صفحة واحدة → PDF عبر PyMuPDF
├── pdfutil.py                      # count_pages() + (للاحتياط) images_to_pdf() عبر PyMuPDF/Pillow
├── config.py                       # المنفذ، المسارات، NAPS2_CONSOLE، الأصول المسموحة، المهلات
├── requirements.txt                # (لا تبعيات ثقيلة؛ pywin32 اختياري) — Flask اختياري أو http.server المدمج
├── naps2_portable/                 # (اختياري) نسخة NAPS2 المحمولة المضمَّنة
│   └── NAPS2.Console.exe
├── run_agent.bat                   # تشغيل صامت عبر pythonw -m scan_agent
└── README.md                       # تثبيت + تشغيل + استكشاف الأخطاء
```

### 5.1 اختيار إطار الخادم
- **المفضَّل:** `http.server` المدمج في المكتبة القياسية (لا تبعية جديدة) — كافٍ لـ 3 نقاط بسيطة. استعمل `ThreadingHTTPServer` لمعالجة طلب الرفع المتزامن مع health.
- بديل: **Flask** إن أردت توجيهاً أنظف (تبعية واحدة خفيفة). القرار: ابدأ بـ`http.server` لتجنّب أي تثبيت.

### 5.2 التشغيل والإبقاء حيّاً
- **تشغيل يدوي للتطوير:** `python -m scan_agent`.
- **تشغيل صامت:** `pythonw.exe -m scan_agent` عبر `run_agent.bat` (بلا نافذة console).
- **تلقائي مع ويندوز (المرحلة 1):** اختصار في مجلد Startup للمستخدم (`shell:startup`) يشغّل `run_agent.bat`. لا يحتاج صلاحيات مدير.
- **مؤشّر الصحّة:** صفحة المسح تستدعي `/agent/health` عند الفتح؛ إن فشل → بانر «شغّل وكيل المسح» مع زر/رابط لـ`run_agent.bat`.
- **التغليف بـ`.exe` وTask Scheduler:** مؤجَّل للمرحلة 3.

---

## 6. قائمة مهام التنفيذ المرتّبة

> الترتيب يحقّق «أصغر مسار عامل end-to-end» أولاً، ثم يصلّب الأمن والاحتياط.

### المرحلة 0 — تثبّت (قبل أي كود)
1. تثبيت NAPS2 (أو فكّ المحمول إلى `scan_agent/naps2_portable/`) والتأكد أن `NAPS2.Console.exe` موجود.
2. تشغيل `--listdevices --driver twain` على الماسح الفعلي → تسجيل **الاسم الكامل** الناتج.
3. تشغيل أمر المسح من §1.3 يدوياً والتأكد من إنتاج PDF صالح غير فارغ.

### المرحلة 1 — كود الوكيل
4. `scan_agent/config.py`: المنفذ 17865، الأصول المسموحة، `locate naps2` عبر `NAPS2_CONSOLE` → المثبّت → المحمول، المهلات، حدّ 50MB.
5. `scan_agent/naps2.py`:
   - `locate_exe()` (ترتيب المسارات أعلاه).
   - `list_devices(driver="twain")` → `subprocess.run([exe,"--listdevices","--driver",driver],capture_output=True,text=True,timeout=60)`؛ ترجع أسطر stdout غير الفارغة؛ على فشل/فراغ → `[]`. مع fallback تلقائي إلى `wia` عند فراغ twain.
   - `scan_to_pdf(device, source, dpi, color, driver, duplex)` → يبني الأمر مع `--noprofile`، ينفّذ `timeout=300`، يتحقّق `returncode==0` و`getsize>0`، يعيد مسار الـPDF المؤقت؛ يرمي `RuntimeError(stderr or stdout)` عند الفشل.
6. `scan_agent/pdfutil.py`: `count_pages(pdf_path)` عبر PyMuPDF (`fitz.open(path).page_count`).
7. `scan_agent/auth.py`: توليد/قراءة `agent_token`؛ `check_origin(headers)`؛ `check_token(headers)`.
8. `scan_agent/server.py`:
   - معالج `ThreadingHTTPServer`.
   - توجيه: `GET /agent/health`, `GET /agent/devices`, `POST /agent/scan`, `OPTIONS *` (preflight).
   - تطبيق CORS + فحص Origin على الكل؛ فحص token على `devices`/`scan`.
   - `/agent/scan`: استدعاء `scan_to_pdf` → `count_pages` → قراءة الـbytes → `base64` → الرد `{ok,pages,pdf_base64}` → **حذف الملف في `finally`**.
9. `scan_agent/__main__.py` + `run_agent.bat` (تشغيل `pythonw -m scan_agent`).

### المرحلة 1 — كود Django
10. إضافة `scan_process_upload` في `core/views/scan_settings.py` (كود §3.3) + إعادة تصديره في `core/views/__init__.py` إن لزم.
11. تسجيل المسار `api/scan/process-upload/` في `core/urls.py`.
12. إضافة حقل `agent_token` (اختياري) إلى `ScanSettings` + توليد token الجلسة وحقنه في صفحة المسح (meta/data-attr).

### المرحلة 1 — تكامل الواجهة
13. تحديث JS صفحة المسح (`static/extraction_smart.js` أو ما يستدعي `scan_launch_api`):
    - عند الفتح: `fetch('http://127.0.0.1:17865/agent/health')` → مؤشّر جاهزية + قائمة `/agent/devices`.
    - زر «مسح»: `POST /agent/scan` (مع `X-LetterSys-Token`) → استلام `pdf_base64` → بناء `FormData` → `POST /books/api/scan/process-upload/` بـ CSRF → عند `ok` التوجّه إلى `redirect`.
    - استبدال منطق البروتوكول/المجلد القديم بهذا التدفّق المباشر.

### المرحلة 1 — الاحتياط والاختبار
14. (اختياري/مؤجَّل إن ضاق الوقت) `scan_agent/wia_fallback.py`: WIA عبر pywin32 (تعداد 1-based، `WIA_DPS_DOCUMENT_HANDLING_SELECT=3088`, التقاط `0x80210003` لنفاد الورق، خصائص item 6146/6147/6148، تجميع PDF عبر PyMuPDF) — يُفعَّل فقط إن `naps2_available=false`.
15. اختبار end-to-end: ماسح حقيقي → زر مسح → PDF يصل → OCR → token → معاينة عبر `scan_file_serve` → فتح `smart-desktop`.
16. اختبار أمني: طلب من أصل آخر يُرفض (403)؛ طلب بلا token صحيح يُرفض (401)؛ منفذ غير قابل للوصول من جهاز آخر على الشبكة.

---

## 7. ملخّص نقاط التماس مع الكود الموجود (لا تكسرها)

| الموجود | الاستخدام في المرحلة 1 |
|---------|------------------------|
| `core/extraction/pipeline.py::run_ocr_isolated(path)` | يُستدعى كما هو من `scan_process_upload` (نفس استدعاء `scan_process_local_file` السطر 663). |
| `cache key: scan_token:{token}` (timeout 86400) | نفس المفتاح والقيمة (تتضمّن `processed_path`, `source_file`, `overall_confidence`). |
| `scan_file_serve(request, token)` (السطر 508) | يعرض الـPDF من `processed_path` بلا تغيير. |
| `redirect: /books/extract/smart-desktop/?scan_token=...` | نفس صيغة `scan_process_local_file` → JS الواجهة يعمل بلا تعديل في صفحة المعاينة. |
| `ScanSettings.get()` | يُضاف إليه `agent_token` (اختياري)؛ صفحة الإعدادات تُحدَّث لاحقاً (المرحلة 2). |
| `scan_launch_api` / بروتوكول `lettersys-scan://` / المراقب | يبقى كـ fallback للماسحات الشبكية/MFP؛ لا يُحذف في المرحلة 1. |

**المحصّلة:** المرحلة 1 تضيف وكيلاً مستقلاً + نقطة رفع واحدة، وتعيد استخدام خط OCR/token/serve الحالي بالكامل، فتحصل على مسح صفحة (أو كومة ADF) من أي ماسح TWAIN عبر الوكيل مع رفع مباشر بلا مجلد وسيط.
