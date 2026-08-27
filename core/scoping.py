"""
نطاق رؤية الكتب — **المصدر الوحيد** لقاعدة «من يرى ماذا».

كانت القاعدة منسوخة يدويّاً في سبعةٍ وعشرين موضعاً بشكلين (إداريّ فقط، وإداريّ
أو مالك الكتاب). قاعدةٌ بهذا الانتشار لا تُغيَّر: كلّ نسخةٍ منسيّة تصير ثغرةً
أو تراجعاً. وهذا الملفّ هو ما جعل الانتقال إلى بُعد القسم تعديلَ دالّتين.

**العقد بعد المرحلة أ (قرارات المالك 2026-08-27):**

* **مدير النظام** (``is_superuser``) يرى كلّ شيء.
* **الموظّف** يرى كتب **قسمه** — لا كتبه هو وحدها. الكتاب ملكُ القسم لا مُدخِله.
* **طبقة السرّيّة:** الكتاب المصنَّف سرّيّاً لا يراه إلّا مُنشئُه ورئيسُ قسمه
  (ومدير النظام). قِيس في القاعدة الحيّة: **487 كتاباً سرّيّاً** من 13,236 —
  ولذلك تُنشر هذه الطبقة **مع** بُعد القسم لا بعده: تفعيلُ النطاق وحده كان
  سيكشفها لكلّ موظّفي القسم، وهي نافذةُ تسريبٍ تصنعها الخطّة نفسها.
* **مستخدمٌ بلا ملفٍّ أو بلا قسم** يرى ما أنشأه هو — سلوكُ ما قبل الأقسام،
  فلا ينكسر تنصيبٌ لم تُبذَر أقسامُه بعد.

**`is_staff` لم تعد تُوسّع الرؤية.** كانت تمنح حاملها رؤيةَ كلّ الكتب ضمناً،
وإبقاؤها مع نطاق القسم يقوّضه من يومه الأوّل: أيّ staff يرى كلّ الأقسام. صارت
صفةً إداريّةً لواجهات الإدارة فحسب — وهي ما يحرسه ``staff_required``. حسابان
مقيسان تأثّرا، وكلاهما في القسم الافتراضيّ فلا يفقدان شيئاً اليوم.
"""

from django.db.models import Q

#: تصنيفاتٌ تُقيَّد رؤيتها داخل القسم.
RESTRICTED_SECRET_LEVELS = ('secret', 'topsecret')


def is_privileged(user) -> bool:
    """أهذا مدير النظام الذي يرى بيانات الشركة كلّها؟"""
    return bool(user.is_superuser)


def user_department_id(user):
    """رقمُ قسم المستخدم، أو ``None`` إن لم يُسنَد بعد."""
    profile = getattr(user, 'profile', None)
    return profile.department_id if profile else None


def is_department_head(user) -> bool:
    profile = getattr(user, 'profile', None)
    return bool(profile and profile.is_department_head)


def can_view_book(book, user) -> bool:
    """أيحقّ للمستخدم الاطّلاع على هذا الكتاب (أو التصرّف به)؟"""
    if is_privileged(user):
        return True

    is_owner = book.created_by_id == user.id
    if book.secret_level in RESTRICTED_SECRET_LEVELS:
        return is_owner or (is_department_head(user)
                            and book.department_id == user_department_id(user))

    dept_id = user_department_id(user)
    if dept_id is None:
        return is_owner
    return is_owner or book.department_id == dept_id


def scope_books_for(user, qs=None):
    """الكتب المرئيّة للمستخدم — صيغة الـqueryset.

    تُفضَّل على ``can_view_book`` حيثما أمكن: النطاق داخل الاستعلام يجعل
    كتابَ غيرك «غير موجود» لا «ممنوع»، فلا يُسرَّب وجودُه من فرق الرمزين.
    """
    if qs is None:
        from core.models import Book
        qs = Book.objects.all()

    if is_privileged(user):
        return qs

    dept_id = user_department_id(user)
    if dept_id is None:
        return qs.filter(created_by=user)

    # كتبُ قسمك، ومعها ما أنشأته أنت دائماً (ولو انتقلتَ بين الأقسام).
    visible = qs.filter(Q(department_id=dept_id) | Q(created_by=user))
    if is_department_head(user):
        return visible
    return visible.exclude(
        Q(secret_level__in=RESTRICTED_SECRET_LEVELS) & ~Q(created_by=user)
    )


def ensure_profile(user):
    """يضمن ملفّاً للمستخدم، ويُسنده للقسم الافتراضيّ في وضع «قسم واحد».

    الهجرة تُسنِد القائمين، لكنّ **المستخدم الجديد بعدها** كان يبقى بلا ملفّ
    فيسقط إلى «كتبي أنا» — أي أنّ موظّفاً جديداً في قسم المتابعة لا يرى كتب
    قسمه. وقاعدة التوافق تقتضي أن يعمل تنصيبُ القسم الواحد **بلا خطوةٍ يدويّة**.

    في وضع الشركة لا نُخمّن القسم: يُترك فارغاً ليُسنده الـadmin صراحةً
    (لوحة الإدارة، المرحلة ب) — وإسنادٌ خاطئٌ صامت أسوأ من إسنادٍ مؤجَّل.
    """
    from core.models import Department, SystemSettings, UserProfile

    profile = getattr(user, 'profile', None)
    if profile is not None:
        return profile

    department = None
    if SystemSettings.get().deployment_profile == SystemSettings.PROFILE_SINGLE:
        department = Department.objects.filter(is_active=True).order_by('id').first()
    return UserProfile.objects.create(user=user, department=department)
