# 📚 نظام إدارة الكتب — النسخة 2.0 المحدثة
## Django + Bootstrap 5 RTL + PWA + Modern JavaScript

> **تنبيه التشغيل:** معلومات التثبيت أدناه للتطوير المحلي وليست طريقة تشغيل
> خدمة الشبكة. نسخة LetterSys الحالية للأجهزة تعمل عبر خدمة Windows
> `LetterSys` (Waitress/NSSM) على `172.16.2.16:1312`. راجع
> [`docs/WINDOWS_LAN_DEPLOYMENT.md`](docs/WINDOWS_LAN_DEPLOYMENT.md)
> و[`docs/LAUNCH_RUNBOOK.md`](docs/LAUNCH_RUNBOOK.md) للإجراءات الحالية.

![Django](https://img.shields.io/badge/Django-4.2.14-green)
![Bootstrap](https://img.shields.io/badge/Bootstrap-5.3.3-purple)
![PWA](https://img.shields.io/badge/PWA-Ready-orange)
![JavaScript](https://img.shields.io/badge/JavaScript-ES6+-yellow)

---

## ✨ الميزات الرئيسية

### 🎯 الميزات الأساسية
- ✅ إدارة الكتب الواردة والصادرة
- ✅ نظام الجهات والعلاقات
- ✅ متابعة تلقائية للاستحقاق (7 أيام)
- ✅ إشعارات داخل النظام
- ✅ مرفقات متعددة (PDF/JPG/PNG)
- ✅ تسجيل تاريخ التعديلات
- ✅ نظام صلاحيات متقدم
- ✅ نسخ احتياطي للبيانات

### 🚀 الميزات الحديثة (جديد!)
- ✨ **البحث المباشر (Live Search)** - نتائج فورية بدون تأخير
- ✨ **نماذج AJAX** - حفظ سريع بدون إعادة تحميل
- ✨ **Progressive Web App (PWA)** - تثبيت كتطبيق + عمل بدون إنترنت
- ✨ **الوضع الليلي (Dark Mode)** - راحة للعين مع حفظ تلقائي
- ✨ **رسوم متحركة متقدمة** - 12 نوع animation smooth
- ✨ **Toast Notifications** - إشعارات جميلة واحترافية
- ✨ **تصدير Excel** - تنسيق احترافي مع ألوان
- ✨ **Service Worker** - تخزين مؤقت ذكي
- ✨ **Push Notifications** - إشعارات فورية
- ✨ **Offline Support** - عمل بدون اتصال

---

## 📋 المتطلبات

### متطلبات النظام
- Python 3.10+
- pip (مدير الحزم)
- متصفح حديث (Chrome 90+, Firefox 88+, Edge 90+, Safari 14+)

### متطلبات اختيارية
- بيئة افتراضية (مُوصى بها)
- Git (للنسخ والتحديثات)

---

## 🔧 التثبيت والتشغيل

### 1️⃣ إنشاء بيئة افتراضية (مُوصى به)
```powershell
cd lettersys_project
python -m venv .venv
.\.venv\Scripts\activate
```

### 2️⃣ تثبيت المكتبات
```powershell
pip install -r requirements.txt
```

**المكتبات المثبتة:**
- Django==4.2.14
- openpyxl==3.1.2 (لتصدير Excel)
- Pillow==10.3.0 (لمعالجة الصور)

### 3️⃣ إعداد قاعدة البيانات
```powershell
python manage.py db_healthcheck
python manage.py migrate
python manage.py db_healthcheck --strict
```

### 4️⃣ إنشاء حساب المشرف
```powershell
python manage.py createsuperuser
```

### 5️⃣ تشغيل الخادم محلياً للتطوير فقط
```powershell
python manage.py runserver
```

هذا يشغّل خادم Django التطويري على `localhost:8000` لهذا الحاسوب فقط؛ لا
يُشغّل خدمة الشبكة ولا يُحدّثها. **خدمة LetterSys المستخدمة بين أجهزة الشبكة
تعمل عبر Waitress/NSSM على المنفذ `1312`**. من جهاز آخر افتح
`http://172.16.2.16:1312`، ولا تشغّل `runserver` بديلاً عنها.

### 6️⃣ فتح نسخة التطوير محلياً
افتح: `http://localhost:8000`

### أيقونة تشغيل خدمة LetterSys الحالية (Windows)

على حاسوب الخادم `172.16.2.16`، أنشئ أيقونة **Start LetterSys Server** مرة واحدة:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\install_lettersys_server_shortcut.ps1
```

الأيقونة تبدأ خدمة Windows الموجودة `LetterSys` فقط بعد التحقق من أنها نسخة Waitress المهيأة على المنفذ `1312` ضمن `D:\lettersys`. قد يطلب Windows تأكيد المسؤول لتشغيل الخدمة. لا تغيّر قاعدة PostgreSQL أو إعداداتها؛ وبعد ظهور رسالة نجاح افتح أيقونة التطبيق المثبّتة المعتادة.

---

## 📁 هيكل المشروع

```
lettersys_project/
├── core/                      # التطبيق الرئيسي
│   ├── models.py             # نماذج البيانات
│   ├── views.py              # المعالجات (محدّث)
│   ├── forms.py              # النماذج
│   ├── urls.py               # المسارات
│   ├── numbering.py          # قواعد رقم القيد — المصدر الوحيد
│   └── management/
│       └── commands/
│           └── check_overdue_books.py
├── static/
│   ├── app.css               # التصميم (محدّث +400 سطر)
│   ├── app.js                # JavaScript الحديث (جديد! 555 سطر)
│   ├── service-worker.js     # PWA Service Worker (جديد! 350 سطر)
│   └── manifest.json         # PWA Manifest (جديد!)
├── templates/
│   ├── base.html             # القالب الأساسي (محدّث)
│   └── core/
│       ├── book_list.html    # قائمة الكتب (محدّث)
│       ├── book_detail.html
│       ├── dashboard.html
│       └── ...
├── media/                     # ملفات المستخدمين
├── db.sqlite3                # ملف قاعدة البيانات القديم (غير مستخدم)
├── manage.py
├── requirements.txt          # المكتبات (محدّث)
├── README.md                 # هذا الملف
├── MODERNIZATION_REPORT.md   # تقرير التحديثات (جديد!)
├── QUICK_START_GUIDE.md      # دليل استخدام (جديد!)
├── SUMMARY_AR.md             # ملخص عربي (جديد!)
├── NEXT_STEPS.md             # الخطوات التالية (جديد!)
├── PRINT_GUIDE.md            # دليل الطباعة
└── CLEANUP_REPORT.md         # تقرير التنظيف
```

---

## 🎨 التقنيات المستخدمة

### Backend
- **Django 4.2.14** - إطار عمل Python
- **PostgreSQL 16** - قاعدة البيانات (pg_trgm + FTS)
- **openpyxl** - تصدير Excel
- **Pillow** - معالجة الصور

### Frontend
- **Bootstrap 5.3.3 RTL** - إطار تصميم
- **Bootstrap Icons 1.11.3** - الأيقونات
- **Cairo Font** - خط عربي جميل
- **Vanilla JavaScript ES6+** - لا مكتبات خارجية
- **CSS3 Animations** - رسوم متحركة

### Modern Web
- **Service Worker API** - PWA
- **Fetch API** - طلبات AJAX
- **Intersection Observer** - رسوم متحركة
- **Local Storage** - حفظ الإعدادات
- **Notification API** - إشعارات المتصفح

---

## 📖 الاستخدام

### دليل البدء السريع
راجع ملف `QUICK_START_GUIDE.md` للحصول على:
- شرح مفصل لكل ميزة
- خطوات الاستخدام بالصور
- نصائح وحيل
- حل المشاكل الشائعة

### التقرير التقني
راجع ملف `MODERNIZATION_REPORT.md` للحصول على:
- تفاصيل التحديثات
- الأكواد المضافة
- الوظائف الجديدة
- الاختبارات

### الطباعة
راجع ملف `PRINT_GUIDE.md` لمعرفة:
- كيفية طباعة الكتب بالألوان
- إعدادات المتصفح
- حل مشاكل الطباعة

---

## 🚀 الميزات الحديثة بالتفصيل

### 1. البحث المباشر (Live Search)
```javascript
// في book_list.html
<input data-live-search="#bookTableBody" ... >
```
- البحث يعمل فوراً عند الكتابة
- Debouncing لتقليل الطلبات (300ms)
- تمييز النتائج بالأصفر

### 2. Progressive Web App (PWA)
```javascript
// التثبيت من المتصفح
// أو من البانر الذي يظهر تلقائياً
```
- تثبيت كتطبيق على الجهاز
- يعمل بدون إنترنت
- إشعارات فورية

### 3. الوضع الليلي (Dark Mode)
```javascript
// زر في Navbar للتبديل
// يحفظ الإعداد تلقائياً
```
- ألوان مريحة للعين
- يعمل في جميع الصفحات
- تبديل سلس

### 4. تصدير التقارير (CSV)
التصدير يمرّ عبر `reports_export` في `core/views/` ويشترك مع صفحة التقارير في
نفس مُصفّي الاستعلام (`_reports_qs`) فلا يتباعد المعروض عن المُصدَّر.
- ترميز UTF-8 بعلامة BOM ليفتح صحيحاً في Excel العربي
- يحترم الفلاتر النشطة (الجهة، المدى الزمني، النوع، الحالة)
- طباعة احترافية من الصفحة نفسها

---

## 🔒 الأمان

### الميزات الأمنية
- ✅ CSRF Token في جميع النماذج
- ✅ حماية من XSS
- ✅ نظام صلاحيات متقدم
- ✅ تشفير كلمات المرور
- ✅ HTTPS للإنتاج

### التوصيات
- استخدم HTTPS في الإنتاج
- غيّر `SECRET_KEY` في الإنتاج
- فعّل `DEBUG = False` في الإنتاج
- راجع `NEXT_STEPS.md` لإعدادات الإنتاج

---

## 📊 الأداء

### التحسينات المطبقة
- ⚡ Debouncing للبحث (-80% طلبات)
- ⚡ Service Worker Caching (-60% وقت تحميل)
- ⚡ AJAX Forms (بدون إعادة تحميل)
- ⚡ Lazy Loading للصور
- ⚡ CSS Animations (GPU accelerated)

---

## 🧪 الاختبار

### تشغيل الاختبارات
```powershell
python manage.py test
```

### فحص النظام
```powershell
python manage.py check
```

---

## 📚 التوثيق الإضافي

| الملف | الوصف |
|------|-------|
| `MODERNIZATION_REPORT.md` | تقرير تقني شامل بالتحديثات |
| `QUICK_START_GUIDE.md` | دليل استخدام مفصل |
| `SUMMARY_AR.md` | ملخص عربي سريع |
| `NEXT_STEPS.md` | خطوات تطوير مستقبلية |
| `PRINT_GUIDE.md` | دليل الطباعة |
| `CLEANUP_REPORT.md` | تقرير التنظيف |
| `AI_ONLINE_INTEGRATION.md` | ربط مزود OCR أونلاين اختيارياً |

---

## 🔄 التحديثات

### النسخة 2.0 (2025)
- ✨ إضافة JavaScript حديث (555 سطر)
- ✨ تطبيق PWA مع Service Worker
- ✨ الوضع الليلي (Dark Mode)
- ✨ البحث المباشر (Live Search)
- ✨ نماذج AJAX
- ✨ رسوم متحركة (12 نوع)
- ✨ تصدير Excel
- ✨ Toast Notifications
- ✨ تحسينات CSS (+400 سطر)

### النسخة 1.0 (سابقاً)
- النظام الأساسي بجميع الميزات الرئيسية

---

## 🐛 الإبلاغ عن المشاكل

### قبل الإبلاغ
1. راجع `QUICK_START_GUIDE.md`
2. افحص console المتصفح (F12)
3. تحقق من ملف `requirements.txt`

### المعلومات المطلوبة
- نسخة Python
- نسخة Django
- المتصفح المستخدم
- رسالة الخطأ الكاملة
- خطوات إعادة إنتاج المشكلة

---

## 📞 الدعم

### الموارد
- دليل البدء السريع: `QUICK_START_GUIDE.md`
- التقرير التقني: `MODERNIZATION_REPORT.md`
- الملخص العربي: `SUMMARY_AR.md`

---

## 📝 الترخيص

هذا المشروع تعليمي ويمكن استخدامه وتطويره بحرية.

---

## 👨‍💻 المطور

تم تطوير هذا النظام باستخدام أحدث التقنيات في:
- JavaScript (AJAX, Fetch API, ES6+)
- Bootstrap 5.3.3 (RTL, Animations)
- Progressive Web App (Service Worker)
- Dark Mode
- Modern CSS (Grid, Flexbox, Animations)

---

## 🧪 تشغيل نسخة تطوير محلية

```powershell
# هذه الخطوات للتطوير المحلي فقط، ولا تُحدّث خدمة الشبكة على 1312.
pip install -r requirements.txt
python manage.py runserver 127.0.0.1:8000
```

افتح `http://localhost:8000`. لا تشغّل migrations أو تنشئ حسابات على قاعدة
الإنتاج ضمن إعداد التطوير هذا.

- أو جدوله يوميًا (09:00) عبر **Windows Task Scheduler**.

## ملاحظات
- المنطقة الزمنية: Asia/Baghdad — التاريخ الافتراضي اليوم.
- المرفقات متعددة (PDF/JPG/PNG حتى 10MB).
- تنبيهات داخل التطبيق تظهر للأدمن في شارة الجرس، مع صفحة للتنبيهات.
- يمكن تعديل الألوان في `static/app.css` (البرتقالي #FF9933).
# تحديث مساحة عمل الوارد — 2026-10-20

تبويبات لتصنيف إحالات الطاولة، وتصفية مشتركة للدفتر وكشف التسليم حسب نوع الكتاب وتاريخه ونطاق رقم سجل القسم. الدفتر سجل القيود، والكشف ورقة توقيع للإحالات التي لم تسجّل عهدتها، والطباعة لا تسجّل الاستلام. إجراءات الوصول منفصلة عن نقل العهدة.

الموضوع يأخذ 42% من جدول الدفتر و43% من كشف التسليم، بهوامش A4 قدرها 10 مم وصفوف أقل حشواً دون اقتطاع النص أو تقليل ارتفاع خانة التوقيع عن 1.4 سم. الأصول محلية والتصميم مستلهم تنظيمياً من Tabler دون إضافة مكتبة. لا يتضمن هذا التحديث ترحيلات قاعدة بيانات.
