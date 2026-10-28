# تشغيل LetterSys على شبكة Windows بعنوان IP (HTTP مؤقتاً)

> هذا دليل تثبيتٍ بديلٍ على خادم Windows جديد، وليس إجراء تحديث للخادم الحالي.
> الخدمة القائمة `LetterSys` في `D:\lettersys` تعمل عبر NSSM وWaitress على
> المنفذ `1312`؛ لا تثبّت خدمة Daphne أو Caddy بجانبها ولا تغيّر مخططها عند
> نشر تحديث التطبيق. تحديث الخدمة القائمة يتبع إجراء الإطلاق المعتمد.

### تحديث خدمة الإنتاج القائمة

لتحديث خدمة `LetterSys` الحالية استخدم `scripts/release_live_windows.ps1` من
فرع `main`، وليس خطوات تثبيت Daphne/Caddy أعلاه. أغلق VS Code والتطبيقات
الثقيلة، ثم افتح PowerShell بصلاحية المسؤول وتأكد من توفر 600 MB على الأقل من
الذاكرة الحرة (ذروة خطوات Django المقيسة 141 MB). يأخذ الإجراء نسخة `pg_dump` جديدة بعد إيقاف الخدمة مباشرةً،
ويتحقق من بصمتها قبل تحديث الشيفرة أو قاعدة البيانات. شغّله من مجلد التطبيق
بالتأكيد الصريح `-ConfirmProductionRelease LETTERSYS`؛ يتوقف الإجراء بدلاً من
المتابعة إذا لم تتحقق بوابات الصلاحية أو الذاكرة أو سلامة النسخة.

## حدود هذا الخيار ومخاطره

هذا إعدادٌ مؤقت لشبكة داخلية موثوقة، بلا شهادة وبلا تشفير. كلمات المرور وملفات
الجلسات والبيانات تنتقل عبر الشبكة كنصّ غير مشفّر؛ لا تستخدمه عبر الإنترنت أو
شبكة Wi-Fi عامة أو شبكة لا تثق بكل أجهزتها. احصر جدار الحماية في شبكة الشركة
الداخلية أو VPN موثوق، وارجع إلى HTTPS حال توفر شهادة.

المتصفح لا يعدّ `http://<IP>` سياقاً آمناً: لن يعمل Service Worker، ولن تظهر
خيارات تثبيت PWA أو تحديثها. يمكن فتح الموقع كصفحة عادية أو حفظه اختصاراً، لكن
الأيقونة لا تشغّل الخادم. تشغيل الماسح يحتاج وكيلاً محلياً على جهاز الماسح.

## البنية المطلوبة

- ثبّت LetterSys في مسار دائم مثل `C:\LetterSys`، لا في مجلد Downloads.
- ثبّت للخادم عنوان IPv4 خاصاً ثابتاً أو احجزه في DHCP، مثلاً `192.0.2.16`.
- خدمة Windows `LetterSysDaphne` تشغّل Daphne على `127.0.0.1:1313` فقط.
- يشغّل Caddy كخدمة Windows على `http://<IP>:1312`، ويخدم `/static/` من
  `STATIC_ROOT` ويمرّر بقية الطلبات وWebSocket إلى Daphne المحلي.
- اسمح في جدار الحماية بمنفذ TCP `1312` من نطاق شبكة الشركة فقط. لا تفتح منفذ
  Daphne `1313` على الشبكة.
- كل جهاز ماسح يحتاج وكيل المسح المحلي مرة واحدة؛ لا يشارك الماسح عبر خدمة الخادم.

## إعداد `.env`

اضبط القيم في ملف `.env` على جهاز الخادم. هذه القيم تطابق الرابط الحالي
`http://192.0.2.16:1312`؛ غيّرها إذا تغيّر عنوان الخادم:

```dotenv
DEBUG=False
ALLOWED_HOSTS=192.0.2.16
CSRF_TRUSTED_ORIGINS=http://192.0.2.16:1312

LETTERSYS_PUBLIC_HOST=192.0.2.16
LETTERSYS_PUBLIC_PORT=1312
LETTERSYS_SERVICE_PORT=1313

SECURE_SSL_REDIRECT=False
SECURE_HSTS_SECONDS=0
SESSION_COOKIE_SECURE=False
CSRF_COOKIE_SECURE=False
USE_X_FORWARDED_PROTO=False
```

استخدم مفتاح Django سرياً وقوياً، ولا تستخدم القيمة التجريبية في `.env.example`.
أبقِ `DEBUG=False`. الخدمة ترفض المضيف غير الخاص أو غير المطابق لـ
`ALLOWED_HOSTS` و`CSRF_TRUSTED_ORIGINS`، وإعدادات HTTPS/الكوكيز الآمنة غير المتوافقة،
أو غياب `staticfiles\manifest.json`.

## الملفات الثابتة والوكيل

من مجلد المشروع شغّل `collectstatic` بالبيئة المعتمدة، وتأكد من وجود
`staticfiles\manifest.json`. لا تشغّل migrations على قاعدة الإنتاج من هذه النسخة.

أنشئ ملف Caddyfile لخدمة HTTP على عنوان الخادم. هذا المثال مطابق للرابط الحالي؛
عدّل المسار إذا ثُبّت المشروع في مكان آخر:

```caddyfile
http://192.0.2.16:1312 {
    handle_path /static/* {
        root * C:/LetterSys/staticfiles
        file_server
    }

    handle {
        reverse_proxy 127.0.0.1:1313
    }
}
```

شغّل Caddy كخدمة Windows تلقائية، وتأكد من أن قواعد الجدار الناري تسمح بالوصول
إلى `1312` من شبكة الموظفين المعتمدة فقط. لا تعرض المنفذ `1313` أو لوحة إدارة Caddy
للشبكة.

## تسجيل خدمة Daphne وتشغيلها

امنح حساب خدمة Windows محدود الصلاحيات قراءةً لملفات التطبيق و`.env` والأوزان،
وكتابةً للمجلدين `logs` و`MEDIA_ROOT`، وصلاحية الاتصال بقاعدة البيانات. لا تستخدم
`LocalSystem` إلا بموافقة مسؤول النظام.

من PowerShell كمسؤول، داخل مجلد المشروع:

الخدمة تتطلب بيئة المشروع في `.venv` وتستخدم
`.venv\Scripts\python.exe` لتشغيل Daphne، لا `sys.executable` الذي يكون
`pythonservice.exe` داخل مدير خدمات Windows. ثبّت اعتماديات المشروع في هذه
البيئة قبل تسجيل الخدمة؛ لا يوجد رجوع صامت إلى Python عام.

```powershell
.\.venv\Scripts\python.exe .\scripts\windows_service.py --startup auto install
Start-Service LetterSysDaphne
```

يمكن إيقافها أو إعادة تشغيلها عبر `Stop-Service LetterSysDaphne` و
`Start-Service LetterSysDaphne`. سجلات الخدمة في
`logs\windows_service.log` وسجلات التطبيق في `logs\lettersys.log`.

تظل Daphne محصورة في `127.0.0.1`. لا يبدأ الخادم عند نقر أيقونة الموقع؛ خدمة
Windows هي التي تبقيه عاملاً، ويجب أن يبدأ Caddy تلقائياً أيضاً حتى يصل المستخدمون
عبر عنوان IP.

## التحقق على أجهزة الشبكة

1. من جهاز آخر على شبكة الشركة افتح `http://192.0.2.16:1312`.
2. جرّب تسجيل الدخول والصفحات والملفات الثابتة ورفع/تنزيل المرفقات وWebSocket.
3. إن تعذّر الاتصال، تحقق من ثبات IP، وحالة خدمتي `LetterSysDaphne` وCaddy، وقاعدة
   الجدار الناري، ثم راجع `logs\windows_service.log`.
4. لا تعتبر فتح `http://127.0.0.1:8011` على جهاز التطوير دليلاً على أن عنوان IP
   متاح من أجهزة الشبكة؛ `127.0.0.1` يشير دائماً إلى الجهاز الحالي.

## وكيل المسح وPWA

### إضافة HTTPS إلى خدمة Waitress القائمة — انتقال تدريجي

بعد موافقة المالك يمكن إضافة خدمة NSSM مستقلة `LetterSysHTTPS` لتشغيل Caddy
على `443` أمام `127.0.0.1:1312`، دون استبدال خدمة `LetterSys` أو تغيير منفذها.
هذا **مسار آخر غير تركيب Daphne/Caddy المذكور أعلاه**. يُثبت Caddy من
إصداره الرسمي بعد مطابقة بصمة الأرشيف؛ ملف checksums في الإصدار 2.11.7
يحتوي SHA512، بينما حقل digest في واجهة GitHub يحتوي SHA256.

في التطبيق الحالي:

- مجلد إعدادات HTTPS هو `D:\lettersys\https`، وملف الإعداد `Caddyfile`.
- الخدمة الجديدة تعمل بحساب `LocalService` وببدء تلقائي مؤجّل، بلا اعتماد
  خدمات على `LetterSys` حتى لا يعطل ذلك أوامر إيقافها في إجراء النشر.
- التخزين مثبت عبر `XDG_DATA_HOME` و`XDG_CONFIG_HOME` داخل المجلد نفسه.
  البيانات والسجلات تسمح بالكتابة لـ LocalService؛ بقية الملفات للقراءة فقط.
  مفاتيح السلطة الداخلية محصورة في LocalService وSYSTEM وAdministrators.
  مجلد backup، الذي يحتوي نسخة البيئة، محصور في SYSTEM وAdministrators.
- Caddy يستمع على IP الخادم فقط، ويستخدم `tls internal`، مع `admin off`
  و`auto_https disable_redirects` و`skip_install_trust`. لا يفترض ثقة
  أجهزة الموظفين ولا يفتح المنفذ 80. قاعدة `LetterSys-HTTPS-LAN` تسمح
  بـ TCP/443 من LocalSubnet فقط.
- تُضاف ثقة الشهادة العامة إلى مخزن الجذور على الخادم صراحةً. يوزع على
  الأجهزة **ملف الشهادة العامة فقط**، لا أي مفتاح أو مجلد بيانات Caddy.
  الثقة بسلطة داخلية أوسع من موقع واحد: حماية مفتاحها إلزامية، وفي حال
  اختراقه يجب إلغاء الثقة وإصدار سلطة بديلة على كل الأجهزة.

مثال Caddyfile (استبدل IP التوثيقي بعنوان الخادم):

```caddyfile
{
    admin off
    auto_https disable_redirects
    skip_install_trust
}

https://192.0.2.16 {
    bind 192.0.2.16
    tls internal
    reverse_proxy 127.0.0.1:1312 {
        header_up X-Forwarded-Proto https
        header_up -Forwarded
        header_up -X-Forwarded-Port
    }
}
```

تحتاج خدمة Waitress القائمة إلى هذه الخيارات الإضافية، **مع إبقاء بقية
وسائطها الأصلية**:

```text
--trusted-proxy=127.0.0.1 --trusted-proxy-count=1 --trusted-proxy-headers="x-forwarded-proto x-forwarded-for" --clear-untrusted-proxy-headers
```

الخيار المنطقي الأخير لا يأخذ `=true`. عند كتابة AppParameters في سجل
NSSM حافظ على علامتي الاقتباس حول قائمة الترويسات؛ فقد تعيد طبقات تحليل
أوامر Windows تقسيمها إلى وسائط منفصلة. احفظ القيمة القديمة وتحقق من
القيمة المخزنة قبل إعادة تشغيل LetterSys.

Waitress يضبط `wsgi.url_scheme` من الوكيل المحلي الموثوق فقط، ولذلك يبقى
`USE_X_FORWARDED_PROTO=False` في Django؛ لا تفعّل ثقة مباشرة في ترويسات
عملاء الشبكة. أضف `https://<IP>` إلى `CSRF_TRUSTED_ORIGINS` واحتفظ بالأصول
القديمة في المرحلة الانتقالية. لا تغير مخطط البيانات ولا تشغّل migrations.

HTTP على 1312 وملفات الجلسة غير الموسومة Secure باقيان **مؤقتاً بموافقة
المالك** حتى تجهيز أجهزة الموظفين. هذه ليست نهاية تأمين النشر: بعد توزيع
الثقة يلزم تغيير مستقل لإغلاق HTTP من الشبكة وتفعيل
`SESSION_COOKIE_SECURE` و`CSRF_COOKIE_SECURE` والتحقق من تسجيل الدخول.
لا تغيّر ذلك ضمن تجهيز الشهادة دون قرار انتقال واضح.

إصلاح شرط التثبيت في هذا الانتقال: `static/manifest.json` يشير إلى
أيقونتين حقيقيتين، PNG بأبعاد 192 و512، مشتقتين من شعار المشروع؛ أزيلت
مراجع الأحجام غير الموجودة وادعاء maskable غير المختبر. نُقلت الأيقونات
والـ manifest نفسها إلى static وstaticfiles في النسخة الحية؛ عند النشر
اللاحق اجمعها بـ collectstatic كالمعتاد. لم تُنشر بقية تغييرات شجرة العمل.

التحقق المطلوب قبل الإعلان:

1. HTTPS في المتصفح دون تجاوز شهادة؛ `isSecureContext === true`.
2. manifest والأيقونات يرجعون 200، والأبعاد تطابق الإعلان.
3. Service Worker نشط على أصل HTTPS ونطاق `/`.
4. `Page.getInstallabilityErrors` في Chromium يعيد قائمة فارغة. ظهور
   beforeinstallprompt في المتصفح المدمج ليس ضماناً؛ اختبر التثبيت في
   Edge/Chrome العاديين، ويمكن استخدام خيار التثبيت من قائمة المتصفح.
5. POST غير مصادق بحقول دخول فارغة لا يفشل بـ CSRF من أصل HTTPS الصحيح؛
   يُرفض Referer غير الآمن فوق HTTPS، ولا يُوثق X-Forwarded-Proto
   المزور من اتصال الشبكة المباشر إلى 1312.
6. يظل رابط HTTP الحالي صالحاً خلال الانتقال، وتعمل الخدمتان تلقائياً.
7. يضاف أصل HTTPS إلى `allowed_origins` لوكيل المسح على **كل** جهاز
   ماسح، ثم يعاد تشغيل الوكيل والتحقق من المسح وإذن الشبكة المحلية.

الشهادات الداخلية بلا نقطة تحقق إلغاء عامة قد تجعل curl/Schannel يعرض
`CRYPT_E_NO_REVOCATION_CHECK`. للتحقق التشخيصي استخدم
`--ssl-revoke-best-effort`، الذي يبقي فحص الثقة والاسم، وليس `-k`.
لا تغيّر سياسات أمان المتصفح لتجاوز الخطأ.

للرجوع: أوقف `LetterSysHTTPS` وعطّل قاعدة جدارها، واستعد `production.env`
و`LetterSys-AppParameters.txt` من backup، ثم أعد تشغيل LetterSys وتحقق
من HTTP. لا تحذف سلطة الشهادة أو تغيّرها عشوائياً؛ ثقة أجهزة الموظفين
مربوطة بها. دليل توزيع الثقة يجب أن يحمل بصمة الشهادة العامة الفعلية.

### معالج تجهيز أجهزة الموظفين المبتدئين

صفحة `/books/device-setup/` متاحة لكل مستخدم مسجّل، وليست محصورة بدور
إداري: التجهيز يخص جهاز الموظف نفسه. يوجد رابط دائم «تجهيز هذا الجهاز»
في القائمة، ورابط في دليل الزيارة الأولى. التوستات لا تختفي بمؤقت، وتظهر
مرة لكل متصفح وأصل؛ تعذّر localStorage يُعلن في سجل المتصفح ولا يمنع المساعدة.
لا يظهر دليل التثبيت داخل iframe أو التطبيق standalone أو صفحة عدم الاتصال.
منع ظهور الدليل في التطبيق المثبت لا يلغي رابط معالج الجهاز الدائم.

المعالج يفحص اتصال الخادم عبر نقطة غير مخزنة، ثم يطلب نقرة «فحص هذا الجهاز»
قبل الاتصال بالوكيل المحلي، حتى يفهم الموظف طلب إذن الأجهزة المحلية إن ظهر.
يفرق بين: الاتصال غير الآمن، تعذّر الخادم/جلسة الدخول، تعذّر الوصول للوكيل
(وقد يكون محجوباً أو يرفض الأصل)، نسخة الوكيل القديمة، غياب NAPS2، قائمة
ماسحات فارغة، فشل سرد الأجهزة، وظهور ماسح فعلي. لا يُفسّر تحذير السائق
كقائمة فارغة ناجحة، ولا يعدّ ظهور الجهاز اختباراً لمسح الورق. لا يجرب مسح
مستند تلقائياً؛ الورقة التجريبية قرار الموظف في صفحة الإدخال.

حزمة التجهيز محددة من الخادم، لا من معامل في الرابط، عبر
`LETTERSYS_WORKSTATION_PACKAGE`؛ الافتراضي
`var\workstation\LetterSys-Workstation-Setup.exe` داخل مجلد التطبيق. تنزيلها يتطلب
تسجيل الدخول وHTTPS الذي يتحقق منه Waitress الموثوق؛ HTTP يرفض التنزيل
صراحةً. قبل أول ثقة بالشهادة، يسلّم المسؤول الحزمة عبر وسيلة موثوقة؛ لا
ننزل مثبت سلطة ثقة عبر HTTP وندّعي أن بصمة داخله تثبت مصدره.

صفحة التجهيز تعرض أزراراً مستقلة لكل إجراء: فتح HTTPS، شرح تجهيز الثقة،
إعادة فحص الاتصال، فحص الماسح، خطوات تركيب الحزمة وإعادة الفحص بعدها،
تسمية الجهاز وربطه بالموافقة، إصلاح غياب الماسح، طلب تثبيت الأيقونة، وفتح
الإدخال لتجربة ورقة. لا يعتبر الضغط على زر المساعدة أو تنزيل الحزمة إتماماً
للتجهيز. رابط HTTPS على HTTP يُؤخذ من أصل HTTPS الموثوق المضبوط في
`CSRF_TRUSTED_ORIGINS` لنفس المضيف، ولا يُخمَّن من المنفذ 1312؛ إذا كان غائباً
أو متعدد المنافذ يطلب المعالج عنوان المسؤول. طلب تثبيت الأيقونة يبقى داخل
نقرة المستخدم مباشرةً؛ عند غياب عرض المتصفح تظهر طريقة التثبيت اليدوية.

على الأجهزة الجديدة: تُشغّل الحزمة من **حساب الموظف العادي** وتجهز الشهادة
ووقت Python المضمن والوكيل وNAPS2 المحمول الكامل؛ لا يحتاج الموظف إلى
Python منفصل أو تعديل agent.json. التشغيل التلقائي عبر pythonw لا يعرض
نافذة أوامر عند الدخول. تعريفات المصنع والطاقة والكابل لا يصح افتراضها
ولا يثبت المعالج تعريفاً تخمينياً. على المسؤول تجربة ماسح حقيقي واعتماد
حزمة التعريف المناسبة للطراز حين لا يظهر الجهاز.

التحقق المحلي: `node --test scripts\tests_install_guide.cjs scripts\tests_device_setup.cjs`
واختبارات Django `core.tests_device_setup` مع settings_test. عند وجود تغييرات
تطوير أخرى تمنع استيراد المشروع، اختبر هذه الدفعة في نسخة تحقق معزولة من
خط الإنتاج، لا بإصلاح/نشر التغييرات الأخرى دون إذن. فحوص Playwright
باستجابات ماسح محاكاة لا تُقتبس إثباتاً لمسح عتاد فعلي.

### أيقونة مكتبية على عنوان الشبكة (HTTP)

لفتح النظام من أيقونة في نافذة مستقلة دون انتظار شريط تثبيت PWA، شغّل من
مجلد المشروع بحساب الموظف العادي (لا يحتاج صلاحية مسؤول):

```powershell
.\scripts\install_desktop_shortcut.ps1 -ServerUrl 'http://172.16.2.16:1312/'
```

ينشئ هذا `LetterSys LAN.lnk` على سطح المكتب، باستخدام Edge، أو Chrome إن لم
يوجد Edge، مع أيقونة المشروع. تُنسخ الأيقونة إلى `%LOCALAPPDATA%\LetterSys`
كي لا يتوقف ظهورها إذا نُقل مجلد المشروع. إذا تعذّر اكتشاف سطح المكتب، مرّر
مساره الحقيقي باستخدام `-DesktopPath` (بما فيه مسار OneDrive إن كان مستخدماً).
لربط الاختصار بعنوان جديد أعد تشغيل الأمر بالعنوان الجديد؛ لا يزيل التطبيق
القديم المثبّت على المنفذ 8000 ولا يعدّل تسجيله.

هذا اختصار لفتح الخادم، **وليس تثبيت PWA أو تشغيل الخادم**، ولا يضيف العمل
دون اتصال أو يتجاوز قيود HTTP. يحتاج الخادم والشبكة إلى البقاء متاحين.
على أجهزة الموظفين الأخرى شغّل الأمر من نسخة المشروع مرة واحدة؛ وبعدها
لا يحتاج الاختصار إلا المتصفح والوصول إلى عنوان الخادم.

- على كل جهاز موصول بماسح، شغّل مرة واحدة من حساب الموظف نفسه:
  `scan_agent\install_agent.bat http://192.0.2.16:1312`.
  الاختصار التلقائي يشغّل `pythonw.exe` بلا نافذة
  أوامر؛ نافذة تعريف الماسح قد تبقى بحسب برنامج الشركة المصنّعة.
- على HTTP عبر IP لا يمكن تثبيت PWA ولا استخدام Service Worker أو إشعار تحديث PWA.
  التحديثات تصل بفتح/إعادة تحميل الموقع بعد نشر الإصدار. عودة أزرار التثبيت والتحديث
  تتطلب HTTPS بشهادة موثوقة أو نشر التطبيق عبر آلية تثبيت مكتبية أخرى.
## Managed client workstations (2026-10-13)

The server and employee computers have different roles. The Windows server keeps
Django, PostgreSQL, Caddy and the boot-time Windows services. A client receives
only the public trust certificate, embedded Python and the full portable NAPS2
scanner agent. No database, `.env`, mail credentials, CA private keys or server
services are distributed. Installing the client package on the server is not
part of workstation rollout.

Device enrollment is immediate after an active employee signs in over trusted
HTTPS and explicitly approves pairing. The employee supplies a friendly device
name. The identity belongs to that Windows user profile, not to the server's
`core.device_identity` and not to the legacy database-peer `NetworkNode`.
Use one active Windows login session per scanner workstation; simultaneous
fast-user-switched sessions can contend for the same loopback agent port.

The narrow `core.workstations` Django application has its own migration namespace
and depends only on the authentication user model. This keeps workstation schema
deployment independent of unrelated pending `core` migrations. Deploy its files,
register the app and run `manage.py migrate workstations`, not an unreviewed
blanket migration of pending development changes.

The device credential is random, hashed in the server database and encrypted
with Windows CurrentUser DPAPI on the client. It authorizes only status
heartbeats; it never creates a browser session or grants document access.
Pairing is guarded by the existing loopback Host and exact Origin checks,
HTTPS-only configured server, JSON/custom-header preflight and a local nonce.
Never put the raw credential into browser storage, URLs or logs.

Heartbeats run independently of the browser every 30 seconds while the agent is
running. The board is at `/books/workstations/`, for the system administrator
only. Connection status becomes offline after 90 seconds without a heartbeat.
Scanner status records a user-requested enumeration, not a successful paper scan,
and becomes unknown after 10 minutes or while offline. Opening the setup page
does not automatically scan paper or continuously enumerate hardware.

A paired agent checks HTTPS connection and live authorization before pulling
new paper. Network/TLS errors, revoked credentials, disabled accounts and expired
credentials fail closed. This deliberately changes paired-device scan behavior:
restore connectivity before scanning. Existing unpaired installations retain
their original behavior until explicitly paired. Browser-mediated document
uploads/downloads continue to use the existing user/department permissions;
there is no background replication of personal files or arbitrary remote-command
facility.

The new client package sets `require_pairing=true` in the per-user `agent.json`.
Unlike legacy manually installed agents, these managed clients cannot pull paper
before the employee completes authenticated pairing. This is an intentional,
explicitly tested opt-in behavior change for the all-in-one distribution.

Pairing must finish within 10 minutes; credentials require re-pairing after
90 days. Renewing the same owner's registration needs explicit consent and
invalidates the previous credential. An administrator's device stop cannot be
bypassed by the owner: the administrator must first lift the stop, after which
the employee renews pairing. Lifting the stop does not reactivate the old token.

The optional `scan_agent/build_workstation_exe.ps1` wraps the full ZIP in a
windowless, per-user extractor so employees need not manually extract files.
It verifies its embedded payload SHA256, validates extraction paths and runs the
GUI launcher. Its `--validate-only` mode tests extraction without installing
anything. A locally built executable is unsigned; Windows/SmartScreen may still
require a visible approval. Do not disable those protections or bypass
certificate warnings to simplify rollout.
