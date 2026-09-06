# خدمة الوسائط المحميّة على الخادم (X-Accel-Redirect)

المرفقاتُ كتبٌ رسميّة. حاليّاً Nginx يخدم `/media/` بـ`alias` مباشر، فأيُّ شخصٍ
يعرف رابطَ ملفٍّ يحمّله **بلا تسجيل دخول**. هذا الإصلاح يجعل الإذنَ في Django
والبثَّ في Nginx: يطلب المتصفّحُ `/media/…` ⟵ يمرّره Nginx إلى Django ⟵ يتحقّق
`serve_media` من الدخول والملكيّة ⟵ يردّ بترويسة `X-Accel-Redirect` إلى موقعٍ
**داخليّ** (`internal`) لا يُوصَل إليه من الخارج ⟵ Nginx يخدم البايتات.

> **هذا الملفُّ توثيقٌ فقط.** طبّقه أنت على الخادم — لم يُنفَّذ من هنا.

## ١) في `.env` على الخادم
```ini
USE_X_ACCEL_REDIRECT=True
# اختياريّ (الافتراض /protected_media/) — لو غيّرته فغيّر موقعَ nginx أدناه ليطابقه:
# X_ACCEL_MEDIA_PREFIX=/protected_media/
```
في التطوير (runserver بلا nginx) والاختبارات يبقى `False`، فيبثّ Django مباشرةً.

## ٢) في كتلة `server` لـ Nginx
**احذف** الموقعَ المكشوف الحاليّ:
```nginx
# احذف هذا — إنّه أصلُ الثغرة:
# location /media/ { alias /var/www/lettersys/media/; }
```
بحذفه تمرّ طلباتُ `/media/` عبر `proxy_pass` الافتراضيّ إلى Django فيُصادِق.

**وأضف** الموقعَ الداخليّ (يطابق `X_ACCEL_MEDIA_PREFIX`؛ الـ`alias` يطابق
`MEDIA_ROOT` الفعليّ على الخادم — أكّد قيمتَه في `.env`):
```nginx
location /protected_media/ {
    internal;                          # لا يُخدَم إلا عبر X-Accel-Redirect من Django
    alias /var/www/lettersys/media/;   # = MEDIA_ROOT (انتبه للشرطة المائلة الختاميّة)
    add_header Cache-Control "private, no-store" always;
}
```
تأكّد أنّ الموقعَ العامّ (المُصادَق) يصل إلى gunicorn — إن لم يكن `/media/`
يقع ضمن `location /` العامّ فوجّهه صراحةً:
```nginx
location /media/ {
    proxy_pass http://lettersys_app;   # نفس upstream التطبيق
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}
```

## ٣) بعد التطبيق
```bash
nginx -t && systemctl reload nginx     # -t يفحص قبل إعادة التحميل فلا تُقفَل الخدمة
```

## ٤) التحقّق
- بمتصفّحٍ **بلا** جلسة: فتحُ رابط `/media/…` ⟵ تحويلٌ إلى `/login/` (لا الملفّ).
- بجلسة **مالكٍ**: يُفتح الملفّ (يخدمه nginx؛ التطبيقُ يردّ فارغاً + الترويسة).
- بجلسة مستخدمٍ **لا يملك** الكتاب: `403`.
- في `access.log`: زمنُ ردّ التطبيق للطلب لم يعد يشمل زمنَ نقل الملفّ.

## ملاحظات
- القوالبُ لا تتغيّر: `att.file.url` أصلاً يساوي `/media/…` المارَّ عبر `serve_media`.
- الرابطُ الموقّت العامّ `serve_shared_attachment` (للجهات الخارجيّة بلا حساب)
  يمرّ بنفس الآليّة تلقائيّاً حين يُفعَّل العلم — يبقى محميّاً بالتوقيع والمدّة.
- لا `Content-Length` من Django في وضع X-Accel — يحسبه nginx من الملفّ الداخليّ.
