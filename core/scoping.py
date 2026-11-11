"""
نطاق رؤية الكتب — **المصدر الوحيد** لقاعدة «من يرى ماذا».

كانت القاعدة منسوخة يدويّاً في سبعةٍ وعشرين موضعاً بشكلين (إداريّ فقط، وإداريّ
أو مالك الكتاب). قاعدةٌ بهذا الانتشار لا تُغيَّر: كلّ نسخةٍ منسيّة تصير ثغرةً
أو تراجعاً. وهذا الملفّ هو ما جعل الانتقال إلى بُعد القسم تعديلَ دالّتين.

**العقد (قرارات المالك 2026-08-27):**

* **مدير النظام** (``is_superuser``) يرى كلّ شيء.
* **الموظّف** يرى كتب **قسمه** — لا كتبه هو وحدها. الكتاب ملكُ القسم لا مُدخِله.
* **السرّيّة حجبُ محتوىً لا حجبُ صفّ** — انظر ``secret_access`` أدناه.
* **مستخدمٌ بلا ملفٍّ أو بلا قسم** يرى ما أنشأه هو — سلوكُ ما قبل الأقسام،
  فلا ينكسر تنصيبٌ لم تُبذَر أقسامُه بعد. ويُضاف كتابٌ سرّيّ واحد عند منحه
  تفويضاً سارياً عليه صراحةً.

**`is_staff` لا تُوسّع الرؤية.** كانت تمنح حاملها رؤيةَ كلّ الكتب ضمناً،
وإبقاؤها مع نطاق القسم يقوّضه من يومه الأوّل. صارت صفةً إداريّةً لواجهات
الإدارة فحسب — وهي ما يحرسه ``staff_required``. **والهويّةُ والسلطة** (الحساباتُ
وإسنادُ الأدوار الحسّاسة والعناقيد والإدارة العابرة للأقسام) لمدير النظام
وحدَه: ``can_manage_accounts``. إدارةُ الموظفين التشغيليّة والشُّعب محصورةٌ
بشجرة رئيس القسم عبر ``can_manage_departments`` و``can_manage_department``.
"""

from typing import NamedTuple
from django.db.models import Q
from django.utils import timezone

from core import numbering

#: تصنيفاتٌ يُحجب محتواها داخل القسم.
RESTRICTED_SECRET_LEVELS = ('secret', 'topsecret')

#: مستويا الوصول إلى الكتاب السرّي.
ACCESS_FULL = 'full'
ACCESS_STUB = 'stub'


def is_privileged(user) -> bool:
    """أهذا مدير النظام الذي يرى بيانات الشركة كلّها؟"""
    return bool(user.is_superuser)


def user_department_id(user):
    """رقمُ قسم المستخدم، أو ``None`` إن لم يُسنَد بعد."""
    profile = getattr(user, 'profile', None)
    return profile.department_id if profile else None


def can_use_system_admin(user) -> bool:
    """شريطُ «إدارة النظام» وصفحاتُ المركز والقسم والتشغيل — لمدير النظام وحده."""
    return is_privileged(user)


def is_department_head(user) -> bool:
    profile = getattr(user, 'profile', None)
    return bool(profile and profile.is_department_head)


def is_mail_officer(user) -> bool:
    """أهو مختصُّ البريد والأرشفة في قسمه؟

    شهادةُ موظّف البريد: «السرّي يُحفظ في السجلّ عاديّ، لكن فقط **مسؤول إدارة
    البريد والأرشفة** يحقّ لهم الاطّلاع». فهو أمينُ السرّيّ فعليّاً — يمسكه
    بيده ويفرّقه — فيُخوَّل بدوره لا بمنحةٍ فرديّة.

    **والعضويّةُ لا التسمية** — كأختِها `is_archivist`: تسميةُ `get_user_role`
    أحاديّةٌ بسلسلةِ أولويّة، فرئيسُ شعبةٍ عضوٌ في «مشرف المتابعة» كان يُعيد
    `dept_head` فيفقد قسمَ البريد في لوحته **رغم أنّ خانتَه مؤشَّرة**. وهذا
    شرطُ دمج الوظيفتين لا زينتُه: «مسؤول إدارة البريد والأرشفة» اجتماعُ
    عضويّتين، ولا يصحّ أن تُلغي إحداهما الأخرى بترتيبِ سلسلةٍ للعرض.
    """
    from core.roles import CONTROLLER_GROUP_NAME

    if not getattr(user, 'pk', None):
        return False
    return user.groups.filter(name=CONTROLLER_GROUP_NAME).exists()


def is_archivist(user) -> bool:
    """أهو مسؤولُ الأرشفة؟ — **عضويّةُ مجموعةٍ لا تسميةُ دور**.

    التسميةُ في `roles.get_user_role` واحدةٌ بسلسلةِ أولويّة، والشهادةُ الميدانيّة
    تقول «مسؤول إدارة البريد والأرشفة» بصيغةٍ واحدة — أي أنّ الرجلَ الواحد قد
    يحمل الدورين. فلو سُئلت التسميةُ هنا لفقَد الجامعُ أحدَ بابيه: إمّا طاولةُ
    البريد وإمّا الأرشفة. والعضويّةُ تحتمل الجمعَ فتُسأل هي.
    """
    from core.roles import ARCHIVE_ALL_GROUP_NAME, ARCHIVIST_GROUP_NAME

    if not getattr(user, 'pk', None):
        return False
    return user.groups.filter(
        name__in=(ARCHIVIST_GROUP_NAME, ARCHIVE_ALL_GROUP_NAME)).exists()


def is_company_archivist(user) -> bool:
    """أيتخطّى شجرةَ قسمه فيحفظ ورقَ الشركة كلِّها؟

    **موسّعُ نطاقٍ لا دورٌ رابع**: القرارُ الافتراضيُّ أنّ لكلّ قسمٍ أرشيفيَّه
    (فمَن أغلق الملفَّ يُسأل عنه)، وهذه استثناءٌ يُمنح صراحةً حين يكون
    الأرشيفُ مركزيّاً. وهي تحمل الدورَ الأساسَ معها — فلا حاملَ لها بلا
    صلاحيّةِ أرشفة.
    """
    from core.roles import ARCHIVE_ALL_GROUP_NAME

    if not getattr(user, 'pk', None):
        return False
    return user.groups.filter(name=ARCHIVE_ALL_GROUP_NAME).exists()


def can_archive(user) -> bool:
    """مَن يقيّد «تمامَ الأرشفة»؟ — الأرشيفيُّ ومديرُ النظام وحدَهما.

    الأرشفةُ خاتمةُ الدورة وتوقيعُها الثاني (استلامُ الوحدة · تمامُ الأرشفة ·
    تسليمُ المتعهّد). فلو ملَكها المُدخِلُ أو مختصُّ البريد لأُغلقت كتبٌ لم
    تُحفظ — وصار الطابورُ الذي يعيش عليه هذا الدورُ كاذباً.
    """
    return is_privileged(user) or is_archivist(user)


def can_view_audit(user) -> bool:
    """أيحقّ له فتحُ **سجلّ الحركات**؟ رئيسُ القسم والسوبر أدمن حصراً.

    **ومختصُّ البريد لا يراه** رغم أنّه أمينُ السرّيّ تشغيليّاً: سجلُّ القراءة
    أداةُ **مراقبةِ أشخاص** لا أداةُ بريد، ومَن يحاسِب موظّفي القسم هو رئيسُه.
    """
    return is_privileged(user) or is_department_head(user)


def can_view_reports(user) -> bool:
    """أيحقّ له فتحُ **التقارير**؟ رئيسُ القسم ومديرُ النظام حصراً — كلٌّ بشجرته.

    قرارُ المالك (2026‑09‑29، الخطّة v2 §10): التقريرُ أداةُ إشرافٍ على عمل القسم
    لا أداةُ عمل، ومخرَجُه (الطباعة وCSV) يخرج من الجهاز. توأمُ ``can_view_audit``؛
    و``roles.role_capabilities`` قاموسُ عرضٍ لا بوّابة.
    """
    return is_privileged(user) or is_department_head(user)


def report_departments(user):
    """الأقسامُ التي يُفلتَر بها التقرير — **الشجرةُ تسيل نزولاً** كالنطاق.

    المديرُ: كلُّ قسمٍ نشط. رئيسُ القسم: قسمُه وشُعبُه (``subtree_ids``). وغيرُهما
    لا تقريرَ له أصلاً (``can_view_reports``) فلا قسم.
    """
    from core.models import Department

    if is_privileged(user):
        return Department.objects.filter(is_active=True)
    if is_department_head(user):
        return Department.objects.filter(pk__in=subtree_ids(user_department_id(user)))
    return Department.objects.none()


def scope_activity_for(user, qs=None):
    """صفوفُ سجلّ الحركات المرئيّة — النطاقُ في الاستعلام لا في القالب.

    أدمنُ القسم يرى: ما فاعلُه من **شجرته** (بلقطة `department` وقتَ الحدث لا
    بقسمه الحيّ — المستخدم ينتقل)، **أو** ما كتابُه من شجرته — فيرى أيضاً
    غريباً قرأ كتابَ قسمه عبر إحالة، وهو حقُّ تدقيقٍ مشروع.
    """
    from core.logging_models import UserActivityLog

    if qs is None:
        qs = UserActivityLog.objects.all()
    if is_privileged(user):
        return qs
    if not is_department_head(user):
        return qs.none()

    mine = subtree_ids(user_department_id(user))
    if not mine:
        return qs.none()
    # أفعالُ مدير النظام الإداريّة (إعادةُ كلمة سرّ، فتحُ السجلّ…) تحمل لقطةَ قسمه
    # فكانت تظهر لرئيس ذلك القسم؛ ويبقى ظاهراً ما مسَّ **كتاباً** من شجرته (دفعة 10‑28)
    return qs.filter((Q(department_id__in=mine) & ~Q(user__is_superuser=True))
                     | Q(book__department_id__in=mine))


def can_manage_system(user) -> bool:
    """أيحقّ له إدارةُ البيانات العامّة (الجهات والنسخ وإعدادات النظام)؟
    — صفةُ موظّف Django أو المدير.

    **والحساباتُ خرجت منها** إلى ``can_manage_accounts``: مَن يُنشئ الحسابَ هو مَن
    يُسند قسمَه ودورَه، لا موظّفٌ يُنشئ حساباً ثمّ يلقى 403 عند إسناده."""
    return bool(user.is_staff)


def can_manage_mail(user) -> bool:
    """أيحقّ له إدارةُ تشغيل البريد وقوالبه؟

    يشمل إعدادات SMTP/IMAP ومزامنة الوارد والقوالب واختبار الاتصال. لا يساوي
    صلاحيةَ إدارة الحسابات أو بقية إعدادات النظام. ويدخل حاملُ ``is_staff``
    حفاظاً على السلوك الإداريّ القائم.
    """
    return is_privileged(user) or bool(user.is_staff) or is_mail_officer(user)


def can_manage_accounts(user) -> bool:
    """أيحقّ له إدارةُ **الهويّة والسلطة**؟ — مديرُ النظام وحدَه.

    قرارُ المالك (2026‑10‑07): **الحساباتُ** (قراءةً وإنشاءً وحذفاً وإعادةَ تعيين
    كلمة المرور) و**لوحةُ الإدارة** (الأقسامُ وإسنادُ الأدوار) و**ورشةُ العناقيد**
    في صفحة الجهات — بوّابةٌ واحدةٌ لثلاثتها. كانت صفحةُ الحسابات على ``is_staff``
    ولوحةُ الإدارة على ``is_superuser``: فالموظّفُ الإداريّ يُنشئ حساباً ثمّ يلقى
    403 عند إسناد قسمه، وورشةُ العناقيد تُفتح له وكلُّ حفظٍ فيها يُرفض.
    وإدارةُ رئيس القسم لمستخدمي شجرته لا توسّع هذه البوّابة؛ لها
    ``can_manage_departments``. و``is_staff`` تبقى لإدارة البيانات وحدَها
    (``can_manage_system``)."""
    return is_privileged(user)


def can_delete_account(by, user) -> bool:
    """أيحذف ``by`` حسابَ ``user`` نهائيّاً؟ — مديرُ النظام وحدَه، ولا حسابَه الذي يعمل به.

    وآخرُ مديرٍ نشطٍ محميٌّ بهذا الشرط نفسِه: الفاعلُ مديرٌ نشط، فالهدفُ غيرُه
    لا يكون آخرَهم أبداً.
    """
    return can_manage_accounts(by) and getattr(by, 'pk', None) != user.pk


def can_enroll_workstation(user) -> bool:
    return bool(user.is_authenticated and user.is_active)


def can_restore_system(user) -> bool:
    """أيحقّ له **استعادةُ نسخةٍ مشفّرةٍ من هذا النظام** إلى قاعدةٍ جديدة
    (``/books/restore-system/``)؟ — لمدير النظام وحدَه (ملاحظةُ التكليف 2026‑10‑07).

    الاستعادةُ لا تكتب في القاعدة الحيّة، لكنّها تُنشئ قاعدةً كاملةً على الخادم
    (حساباتٌ وكلماتُ مرورٍ قديمةٌ معها) يُحوَّل إليها النظامُ بقرار المالك.
    والسطرُ هنا وحدَه يحرس الصفحةَ وواجهتَيها وبطاقتَها في مركز الإعدادات —
    فإن قُرّر أن تكون لموظّفي الإدارة (كالنسخ) فالتغييرُ هنا لا في قالب."""
    return is_privileged(user)


def can_use_desk(user) -> bool:
    """أيحقّ له فتحُ **طاولة البريد** (كشفُ التسليم ودفترُ الوارد المطبوع)؟

    مختصُّ البريد ورئيسُ القسم ومديرُ النظام. وهي ليست بوّابةَ سرّيّةٍ بل
    بوّابةُ **سطحٍ يخرج من الجهاز**: ورقةٌ تحمل خريطةَ عمل القسم كاملةً.
    """
    return is_privileged(user) or is_department_head(user) or is_mail_officer(user)


def _department_custodian(user) -> bool:
    """أهو أمينُ ورقِ قسمه؟ — رئيسُه أو مختصُّ بريده أو أرشيفيُّه.

    **مسندٌ واحدٌ يُستهلك في موضعين**: `secret_access` (فتحُ المحتوى) و
    `_unauthorized_secret_q` (حارسُ البحث النصّيّ). وكانا نسختين متطابقتين
    بالصدفة؛ ولو أُضيف دورٌ إلى إحداهما دون الأخرى لصار البحثُ إمّا أداةَ
    استنطاقٍ وإمّا حاجباً لِما يملكه صاحبُه. والحارسُ البنيويُّ يقارنهما.
    """
    return is_department_head(user) or is_mail_officer(user) or is_archivist(user)


def secret_access(user, book) -> str:
    """مستوى وصول المستخدم إلى كتابٍ سرّيّ: ``full`` أو ``stub``.

    **حجبُ محتوىً لا حجبُ صفّ** — وهذه مطابقةٌ للورق حرفيّاً: قال الكاتب «السرّي
    يُحفظ في **السجلّ عاديّ**»، أي أنّ الدفتر يكشف الرقم والتاريخ للجميع
    والمظروفَ مغلق. وكان الكود يُخفي الصفَّ كلَّه — فيكسر تسلسلَ الدفتر عند
    الكاتب ويجعله يعدّ الأرقام الناقصة.

    ``full`` لخمسة: مدير النظام · رئيس قسم الكتاب · **مختصّ بريد قسمه** ·
    مُنشئه · حاملُ تفويضٍ ساري. وما عداهم ``stub``.
    """
    if book.secret_level not in RESTRICTED_SECRET_LEVELS:
        return ACCESS_FULL
    if is_privileged(user) or book.created_by_id == user.id:
        return ACCESS_FULL

    same_department = book.department_id and book.department_id == user_department_id(user)
    if same_department and _department_custodian(user):
        return ACCESS_FULL

    if _has_live_grant(user, book):
        return ACCESS_FULL
    return ACCESS_STUB


def _live_grants_for(user):
    """تفاويضُ هذا المستخدم السارية — **مسندٌ واحدٌ يُستهلك في موضعين**.

    نظيرُ ``_department_custodian`` تماماً، وللسبب نفسِه: ``_has_live_grant``
    (فتحُ المحتوى) و``_unauthorized_secret_q`` (حارسُ البحث والقوائم) كانا
    يفترقان — الأوّلُ يعرف المنحةَ والثاني لا. فصاحبُ المنحة يفتح الكتابَ
    السرّيَّ برابطه **ولا يجده في بحثٍ ولا قائمة**: حقٌّ يُمنح بالباب ويُنكَر
    بالفهرس. والسريانُ هنا تعريفٌ واحد (غيرُ مسحوبٍ، وغيرُ منتهٍ) لا نسختان.
    """
    from core.models import SecretAccessGrant

    if not getattr(user, 'pk', None):
        return SecretAccessGrant.objects.none()
    return _live_grants().filter(user=user)


def _live_grants():
    """التفويضاتُ السارية كلُّها — **تعريفُ السريان الوحيد** (غيرُ مسحوبٍ وغيرُ منتهٍ)."""
    from core.models import SecretAccessGrant

    now = timezone.now()
    return SecretAccessGrant.objects.filter(revoked_at__isnull=True).filter(
        Q(expires_at__isnull=True) | Q(expires_at__gt=now))


def _has_live_grant(user, book) -> bool:
    """أعنده تفويضٌ سارٍ على هذا الكتاب بعينه؟"""
    return _live_grants_for(user).filter(book=book).exists()


def secret_openers(book):
    """مَن يفتح محتوى هذا الكتاب السرّيّ — سطرُ «مَن يفتحه» في صفحته (قرارُ Q5).

    **التوأمُ المقروء لـ``secret_access``** بمسنداته نفسِها: مُنشئُه، وأمناءُ
    ورق قسمه (``_department_custodian``)، وحمَلةُ التفويض الساري — ومديرُ النظام
    دائماً (يُسمّى دوراً لا أشخاصاً). يُعيد المستخدمين مرتّبين بالاسم؛ وحارسُ
    التطابق يتحقّق أنّ كلَّ مَن تُسمّيه يلقى ``ACCESS_FULL`` وأنّ زميلَ القسم لا.
    """
    from django.contrib.auth.models import User

    openers = {}
    if book.created_by_id:
        openers[book.created_by_id] = book.created_by
    if book.department_id:
        colleagues = User.objects.filter(profile__department_id=book.department_id
                                         ).select_related('profile')
        for user in colleagues:
            if _department_custodian(user):
                openers[user.pk] = user
    for grant in _live_grants().filter(book=book).select_related('user'):
        openers[grant.user_id] = grant.user
    # مَن عُطِّل حسابُه لا يفتح شيئاً — ذكرُه ضجيج؛ والمديرُ يُذكر دوراً في القالب
    return sorted((u for u in openers.values() if u.is_active and not u.is_superuser),
                  key=lambda u: u.get_full_name() or u.get_username())


def can_view_book(book, user) -> bool:
    """أيحقّ للمستخدم أن يرى هذا الكتاب في قوائمه؟

    **صارت تُجيب عن الصفّ لا عن المحتوى:** السرّيُّ يظهر لأهل القسم بسجلّه
    (رقمٌ وتاريخ)، ومحتواه يحكمه ``secret_access``. والتفويضُ الفرديُّ الساري
    يُظهر كتابَه السرّيَّ المحدّد ويفتح محتواه. فمن أراد المحتوى فليسأل عنه،
    ولا يُخلط السؤالان.
    """
    if is_privileged(user):
        return True

    is_owner = book.created_by_id == user.id
    if is_owner:
        return True

    dept_id = user_department_id(user)
    if dept_id is None:
        return (
            book.secret_level in RESTRICTED_SECRET_LEVELS
            and _live_grants_for(user).filter(book_id=book.pk).exists()
        )
    if book.department_id in subtree_ids(dept_id):
        return True
    # **توأمُ الشقّين الثالث والرابع في `scope_books_for`** — وانفراجُهما هو
    # صنفُ العيب الذي كلّفنا مرّتين: مسندٌ يتّسع وقرينُه لا، فيظهر الكتابُ في
    # القائمة ويُرفض عند فتحه (أو العكس، وهو أسوأ).
    #
    # **ووقع ثالثةً**: أُضيف شقُّ الذكر (الأضبارة) إلى الاستعلام ونُسي هنا،
    # فكانت الوحدةُ ترى كتابَ أضبارتها في القائمة ولا تفتحه. الحارسُ الآن
    # بنيويّ: `tests_scope_parity` يقارن الدالّتين على مصفوفة حالات.
    mine = subtree_ids(dept_id)
    if (_referred_to(mine).filter(book_id=book.pk).exists()
            or _mentioned_in(mine).filter(pk=book.pk).exists()):
        return True
    return (
        book.secret_level in RESTRICTED_SECRET_LEVELS
        and _live_grants_for(user).filter(book_id=book.pk).exists()
    )


def can_open_content(book, user) -> bool:
    """أيحقّ له **فتحُ محتوى** الكتاب: مرفقاته ونصّه وهوامشه وتعليقاته؟

    تفترق عن ``can_view_book`` عند السرّيّ وحده — وهذا هو الفرق الذي وُجدت
    الطبقةُ لأجله: الصفُّ يُرى، والمظروفُ يُفتح بإذن. وكلُّ عمليّةٍ على مرفقٍ
    (خدمةً أو رفعاً أو حذفاً أو دمجاً) تمرّ من هنا لا من ``can_view_book``.
    """
    return can_view_book(book, user) and secret_access(user, book) == ACCESS_FULL


def _writer_group_names():
    """مجموعاتُ الأدوار التي تكتب — **قائمةُ سماحٍ صريحة** لا «كلُّ مجموعةِ دور»:
    مجموعةٌ جديدةٌ تولد للقراءة حتى يُقرَّر لها، وحارسُ التطابق يُلزم بالقرار."""
    from core.roles import (ARCHIVE_ALL_GROUP_NAME, ARCHIVIST_GROUP_NAME,
                            CONTROLLER_GROUP_NAME, ENTRY_GROUP_NAME)

    return frozenset({ENTRY_GROUP_NAME, CONTROLLER_GROUP_NAME,
                      ARCHIVIST_GROUP_NAME, ARCHIVE_ALL_GROUP_NAME})


def can_write(user) -> bool:
    """أيكتب أصلاً؟ — ما عدا «قارئ فقط».

    قرارُ المالك 2026‑11‑01: **القارئُ يقرأ ويعلّق** — لا يُنشئ ولا يعدّل ولا يحذف ولا
    يغيّر حالةً ولا يفرّق ولا يرسل. كان الدورُ تسميةَ عرضٍ (``roles.get_user_role``)
    لا تمنع شيئاً. والسؤالُ هنا عن **العضويّة** لا التسمية — كأختَيها
    ``is_mail_officer`` و``is_archivist``: التسميةُ سلسلةُ أولويّةٍ للعرض.

    والنطاقُ فوقه لا تحته: مَن يكتب يكتب على ما يحقّ له (``can_edit_book``) لا على كلّ شيء.

    **(ب)3 — 2026‑11‑11:** لم يعد يحرس الكتابةَ على الكتب؛ لكلّ فعلٍ مفتاحُه في مصفوفة
    الأدوار (``can_enter_book`` · ``can_edit_book`` · ``can_link_book`` · ``can_register_book``
    · ``can_reserve_number`` · ``can_add_entity``). بقي لأبواب البريد الستّة وحدها حتى
    تُربط مع (ب)5 (قرارُ المالك)، ثمّ يُحذف.
    """
    if not (getattr(user, 'is_authenticated', False) and user.is_active):
        return False
    if is_privileged(user) or is_department_head(user):
        return True
    return user.groups.filter(name__in=_writer_group_names()).exists()


def can_link_book(book, user) -> bool:
    """العهدةُ والربط على كتابٍ يُفتح محتواه — مفتاحُ «العهدة والربط».

    الوحدةُ المُحالُ إليها تسجّل العهدةَ وتربط ولا تعدّل الكتاب (``can_edit_book``)،
    والقارئُ لا يفعلهما. وكانا مع القيد عندنا مسنداً واحداً على ``can_write``
    (``can_act_on_book``)، فصار لكلّ فعلٍ مفتاحُه في (ب)3 — والمحتوى شرطٌ لا يوسّعه منح."""
    return has_capability(user, 'custody.link') and can_open_content(book, user)


def can_register_book(book, user) -> bool:
    """قيدُ الكتاب في دفترنا برقمٍ من عدّادنا — مفتاحُه «الإدخال» (قرارُ المالك 2026‑11‑11:
    القيدُ إدخالٌ في سجلّنا يستهلك رقماً لا يعود). والنطاقُ فتحُ المحتوى كالعهدة."""
    return has_capability(user, 'book.enter') and can_open_content(book, user)


def _owns_book(book, user) -> bool:
    """نطاقُ الكتابة على الكتاب نفسِه بلا سؤالٍ عن الفعل — والفعلُ مفتاحُ مَن يستدعيه.

    قرارُ المالك 2026‑09‑29 (Q1‑ج): لشجرة **القسم المالك** وطاولته ومدير النظام.
    والوحدةُ التي فُرِّق إليها الكتابُ أو ذُكرت فيه تراه وتفتح محتواه
    (``can_open_content``) وتُبقي أفعالَ صفّها وعهدتها وتعليقها — لكنّها لا تكتب
    فوق ورقة غيرها. كان حقُّ الكتابة هو حقَّ الفتح، فتعدّل الوحدةُ المُحالُ إليها
    عنوانَ القسم وتحذف كتابَه وتكتب فوق هامش مديره.

    مَن بلا قسمٍ (تنصيبٌ لم تُبذَر أقسامُه) وكتابٌ بلا قسم: يكتب عليه مُنشئُه —
    كما يراه وحدَه في ``scope_books_for``.
    """
    if not can_open_content(book, user):
        return False
    if is_privileged(user):
        return True
    dept_id = user_department_id(user)
    if dept_id is None or book.department_id is None:
        return book.created_by_id == user.id
    return book.department_id in subtree_ids(dept_id)


def can_edit_book(book, user) -> bool:
    """أيعدّل **الكتابَ نفسَه**: حقولَه وهامشَه ومرفقاتِه وحالةَ متابعته ومراجعةَ
    استخراجه؟ — مفتاحُ «التعديل» على ما يملكه قسمُه (``_owns_book``).

    والمفتاحُ أوّلاً: مخبّأٌ على كائن المستخدم، فيُرفض القارئُ بلا سؤالٍ عن الكتاب."""
    return has_capability(user, 'book.edit') and _owns_book(book, user)


def can_trash_book(book, user) -> bool:
    """نقلُ الكتاب إلى السلّة، فرداً أو جملةً — مفتاحُ «الحذف إلى السلّة» على ما يملكه قسمُه.

    قرارُ المالك (ب)4: لرئيس القسم ومختصّ البريد. وحذفُ **المرفق** ليس هنا: هو لمن يعدّل
    الكتاب (``can_edit_book``، قرارُه المسجَّل)."""
    return has_capability(user, 'book.trash') and _owns_book(book, user)


def can_restore_book(book, user) -> bool:
    """الاسترجاعُ من السلّة — أبوابُه الثلاثة: استعادةُ الكتاب، واستعادةُ المرفق، والتراجعُ الفوريّ
    بعد الحذف. مفتاحُ «الاسترجاع من السلّة» (رئيسُ القسم ومختصُّ البريد ومسؤولُ الأرشفة)."""
    return has_capability(user, 'book.restore') and _owns_book(book, user)


def can_open_trash(user) -> bool:
    """السلّةُ لمن يفعل فيها شيئاً: الحذفُ إليها أو الاسترجاعُ منها — والقارئُ والمنفِّذُ خارجها
    بالرابط أيضاً (قرارُ المالك (ب)4). ورابطُ الشريط يسأل المسندَ نفسَه."""
    return has_capability(user, 'book.trash') or has_capability(user, 'book.restore')


def mark_row_actions(books, user) -> None:
    """يضع على كلّ كتابٍ في صفحة القائمة ``can_edit_row`` و``can_trash_row`` — قاعدةُ
    ``can_edit_book``/``can_trash_book`` نفسُها بلا استعلامٍ لكلّ صفّ: المفتاحان مرّةً للمستخدم،
    والملكيّةُ (``_owns_book``) من شجرة قسمه مرّةً ومن وسم ``restricted`` الذي ألحقته القائمة
    (محتوىً لا يُفتح). فلا زرَّ في الصفّ يُعرض ليُرفض، أوّليّاً وفي AJAX."""
    may_edit = has_capability(user, 'book.edit')
    may_trash = has_capability(user, 'book.trash')
    privileged = is_privileged(user)
    dept_id = user_department_id(user)
    mine = set(subtree_ids(dept_id)) if dept_id is not None and not privileged else set()
    for book in books:
        if privileged:
            owns = True
        elif getattr(book, 'restricted', False):
            owns = False
        elif dept_id is None or book.department_id is None:
            owns = book.created_by_id == user.id
        else:
            owns = book.department_id in mine
        book.can_edit_row = may_edit and owns
        book.can_trash_row = may_trash and owns


def _extraction_book(extraction):
    """كتابُ نتيجة الاستخراج: المربوطُ بها، وإلّا كتابُ مرفقها، وإلّا ``None``."""
    if extraction.book_id:
        return extraction.book
    if extraction.attachment_id and extraction.attachment is not None:
        return extraction.attachment.book
    return None


def can_open_extraction(extraction, user) -> bool:
    """أيقرأ نتيجةَ استخراج؟ هي رقمُ المستند وعنوانُه وهامشُه منسوخةً — فحكمُها
    حكمُ فتح محتوى كتابها (``can_open_content``)، وما لا كتابَ له لمدير النظام.

    تدقيقُ 2026‑10‑08: صفحةُ النتيجة وواجهتُها البرمجيّة كانتا لكلّ مَن سجّل الدخول —
    تعدادُ الأرقام يكشف عنوانَ كلّ كتابٍ وهامشَه، والسرّيُّ منها.
    """
    book = _extraction_book(extraction)
    return can_open_content(book, user) if book is not None else is_privileged(user)


def can_review_extraction(extraction, user) -> bool:
    """أيعتمدها أو يرفضها أو يصحّح مفرداتها أو يعلّق عليها؟ كتابةٌ على مفردات
    كتابٍ تُغذّي التعلّم ⟵ ``can_edit_book``، وما لا كتابَ له لمدير النظام."""
    book = _extraction_book(extraction)
    return can_edit_book(book, user) if book is not None else is_privileged(user)


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
        return qs.filter(
            Q(created_by=user)
            | Q(
                secret_level__in=RESTRICTED_SECRET_LEVELS,
                pk__in=_live_grants_for(user).values('book_id'),
            )
        )

    # كتبُ قسمك **وشُعبِه** — بما فيها السرّيّة — ومعها ما أنشأته أنت (ولو
    # انتقلتَ بين الأقسام)، **وما فُرِّق إليك**. والسرّيُّ يظهر صفّاً ويُحجب
    # محتواه في طبقة العرض.
    #
    # الشقُّ الثالث هو ما يجعل التفريقَ عملاً لا صفوفاً في جدول: الكتابُ يبقى
    # مملوكاً لقسمٍ واحد، والوحدةُ المُحال إليها تراه بلا نقلِ ملكيّة. وهو
    # **استعلامٌ فرعيّ لا وصلة** عمداً: الوصلةُ تُكرّر الصفَّ بعدد إحالاته
    # فيلزم `distinct()` على كلّ قائمةٍ في النظام.
    #
    # والشقُّ الرابع هو **الأضبارة**: «يتدفّق لها الكتبُ من ذكر اسمها في
    # الجهات — الصادر والوارد» (نصُّ المالك). وبلا هذا الشقّ تُفتح أضبارةُ
    # الشعبة **فارغةً من كلّ ماضيها**: التفريقُ يسكن `BookReferral` وهو جدولٌ
    # جديدٌ لا صفَّ فيه للتاريخ، بينما الذكرُ يسكن الـM2M ومعه آلافُ الصفوف.
    # والشقّان يتكاملان: الإحالةُ التزامٌ يُطارَد، والذكرُ انتماءٌ يُؤرشَف.
    # والشقُّ الخامس تفويضٌ فرديٌّ ساري على كتابٍ سرّيّ بعينه.
    mine = subtree_ids(dept_id)
    return qs.filter(
        Q(department_id__in=mine)
        | Q(created_by=user)
        | Q(pk__in=_referred_to(mine))
        | Q(pk__in=_mentioned_in(mine))
        | Q(
            secret_level__in=RESTRICTED_SECRET_LEVELS,
            pk__in=_live_grants_for(user).values('book_id'),
        )
    )


def listed_books(user):
    """ما تعرضه «كلّ الكتب» وتعدّه اللوحة: **القديمُ والجديد عرضٌ واحد**.

    قرارُ المالك 2026‑11‑03: الورقُ المنقول أرشيفُ قسم المتابعة نفسه لا صنفٌ يُخفى،
    وكان إخفاؤه يفتح الصفحةَ فارغة (الجديدُ صفرٌ من 15,703). وكتبُ التدريب خارجها.
    أمّا طوابيرُ العمل (الطاولة والدفتر والعهدة) فتبقى على ``Book.objects.live()``:
    كتابٌ من 2025 ليس مهمّةً مفتوحة.
    """
    from core.models import Book

    return scope_books_for(user, Book.objects.filter(is_training=False))


def books_in_scope(user, *, legacy=False):
    """الكتبُ التي **تُعَدّ وتُعرَض** للمستخدم — الحيُّ وحدَه افتراضاً.

    قرارُ المالك 2026‑10‑06 («نعم»): لوحةُ القيادة والقائمةُ تعدّان كالتقارير
    (قاعدةُ §7.2 · ``Book.objects.live()``): المنقولُ من الورق (``source_ref``)
    وكتبُ التدريب خارج العدّ، فرقمُ كلِّ بلاطةٍ هو عددُ ما تفتحه. و``legacy=True``
    يُدخلها صراحةً — مفتاحُ «يشمل الورق القديم». **مصدرٌ واحد**: اللوحةُ والقائمةُ
    والتصديرُ والتقاريرُ تقرأ من هنا، فلا يعدّ سطحٌ ما لا يعدّه جاره.
    """
    from core.models import Book

    return scope_books_for(user, Book.objects.all() if legacy else Book.objects.live())


def subtree_ids(department_id):
    """معرِّفاتُ القسم وكلِّ ما تحته — **الشجرةُ تسيل نزولاً لا صعوداً**.

    رئيسُ القسم ومختصُّ بريده يريان دفاترَ الشُّعب (وإلّا كان القسمُ أعمى عن
    عمله)، والشعبةُ لا ترى دفترَ القسم الأمّ: «للوحدات مستخدمون يستطيعون
    الوصول **لأضابيرهم** والاستعلام داخلها ومراجعة **بريدهم** الذي أرسلوه»
    — نصُّ المالك. وما يخصّ الشعبةَ من كتب القسم يصلها **بالتفريق** لا
    بالنطاق: التزامٌ صريحٌ لا اطّلاعٌ عامّ.

    استعلامٌ واحد: الجدولُ عشراتُ الصفوف (42 وحدةً مقيسة)، والمشي في بايثون
    أرخصُ من استعلامٍ متكرّرٍ لكلّ مستوى.
    """
    from core.models import Department

    if department_id is None:
        return []

    parents = dict(Department.objects.values_list('id', 'parent_id'))
    found, frontier = {department_id}, {department_id}
    while frontier:
        frontier = {cid for cid, pid in parents.items()
                    if pid in frontier and cid not in found}
        found |= frontier
    return sorted(found)


def managed_department_ids(user):
    """الأقسامُ التي يديرها المستخدم — مديرُ النظام يرى الكلَّ والرئيسُ شجرته."""
    from core.models import Department

    if can_manage_accounts(user):
        return list(Department.objects.values_list('pk', flat=True))
    if is_department_head(user):
        return subtree_ids(user_department_id(user))
    return []


def can_manage_departments(user) -> bool:
    """أيحقّ له فتحَ إدارة الأقسام؟ مديرُ النظام أو رئيسُ قسمٍ مسند."""
    return can_manage_accounts(user) or bool(
        is_department_head(user) and user_department_id(user))


def can_manage_department(user, department) -> bool:
    """أيحقّ له إدارةُ عقدةٍ بعينها؟ ولا تُوسّع هذه القاعدة إدارةَ الحسابات العامة."""
    department_id = getattr(department, 'pk', department)
    if can_manage_accounts(user):
        return True
    return bool(
        is_department_head(user)
        and department_id is not None
        and department_id in subtree_ids(user_department_id(user))
    )


#: ما يمنحه رئيسُ القسم لمن في شجرته (قرارُ المالك 2026‑10‑26)، وما فوقه لمدير
#: النظام وحدَه. **مصدرٌ واحد** لخدمة الإدارة وقراءتِها ونموذجِ الإنشاء — كانت
#: القاعدةُ في ثلاثة مواضع، والقالبُ يقرأ ``grantable_roles`` لا شرطَ دور.
HEAD_GRANTABLE_ROLES = frozenset({'viewer', 'entry', 'archivist', 'controller'})
ADMIN_ONLY_ROLES = frozenset({'department_head', 'company_archivist'})


def grantable_roles(user) -> frozenset:
    """الأدوارُ التي يمنحها هذا المستخدم — فارغةٌ لمن لا يدير أحداً."""
    if can_manage_accounts(user):
        return HEAD_GRANTABLE_ROLES | ADMIN_ONLY_ROLES
    if can_manage_departments(user):
        return HEAD_GRANTABLE_ROLES
    return frozenset()


def _group_names(user, group_names):
    return set(group_names if group_names is not None
               else user.groups.values_list('name', flat=True))


def is_sensitive_account(user, group_names=None) -> bool:
    """حسابٌ يفتح السرّيّ أو يدير غيرَه: مديرٌ، أو أمينُ ورقِ قسمه
    (``_department_custodian``: رئيسٌ · مختصُّ بريد · أرشيفيّ)، أو أرشيفُ الشركة.

    ``group_names`` من صفوفٍ مُسبقةِ الجلب — دوالُّ ``is_*`` تسأل القاعدةَ لكلّ صفّ.
    """
    from core.roles import ARCHIVE_ALL_GROUP_NAME, ARCHIVIST_GROUP_NAME, CONTROLLER_GROUP_NAME

    if user.is_superuser or is_department_head(user):
        return True
    return bool(_group_names(user, group_names)
                & {CONTROLLER_GROUP_NAME, ARCHIVIST_GROUP_NAME, ARCHIVE_ALL_GROUP_NAME})


def can_manage_user(by, user, *, group_names=None, managed_ids=None) -> bool:
    """أيُدير ``by`` حسابَ ``user``؟ — قاعدةٌ واحدة لحارس الخدمة ولصفّ اللوحة.

    رئيسُ القسم يدير مستخدمي شجرته، **إلّا**: حسابَه هو (كان يمنح نفسَه البريدَ
    فيملك إعداداتِ الشركة، والأرشفةَ — مراجعةُ 2026‑10‑27)، والحساباتِ الإداريّة،
    وأرشيفَ الشركة (يمنحه المديرُ وحدَه)، ورئيساً نظيراً في قسمه نفسِه.
    ``managed_ids``: شجرةُ ``by`` محسوبةً سلفاً لصفوف الجدول (لا ``subtree_ids`` لكلّ صفّ).
    """
    from core.roles import ARCHIVE_ALL_GROUP_NAME

    if can_manage_accounts(by):
        return True
    profile = getattr(user, 'profile', None)
    if (user.pk == getattr(by, 'pk', None) or user.is_superuser or user.is_staff
            or profile is None or profile.department_id is None):
        return False
    in_tree = (profile.department_id in managed_ids if managed_ids is not None
               else can_manage_department(by, profile.department_id))
    if not in_tree:
        return False
    if ARCHIVE_ALL_GROUP_NAME in _group_names(user, group_names):
        return False
    return not (profile.is_department_head
                and profile.department_id == user_department_id(by))


def _referred_to(department_ids):
    """معرِّفاتُ الكتب المُفرَّقة إلى قسمٍ بعينه — أيّاً كانت حالةُ الالتزام.

    **حتى المنجَزة**: الوحدةُ التي نفّذت كتاباً قبل شهرٍ يجب أن تجده حين تُسأل
    عنه، وإخفاؤه بإغلاق الالتزام يُضيع المستند من حيث أُنجز.
    """
    from core.models import BookReferral

    return BookReferral.objects.filter(
        to_department_id__in=department_ids
    ).values('book_id')


def _mentioned_in(department_ids):
    """الكتبُ التي ذُكرت فيها وحدةٌ من شجرتي — صادراً أو وارداً.

    الجسرُ هو **توأمُ الجهة** (``Department.entity``): الكتابُ يذكر جهةً،
    والجهةُ تُقابل قسماً. فوحدةٌ بلا توأمٍ لا تملك أضبارةً بعد — وهذا صحيحٌ
    لا نقص: لا اسمَ لها في دليل الجهات لتُذكر به.

    استعلامٌ فرعيٌّ لا وصلة، كشقِّ التفريق تماماً: وصلُ علاقتَي M2M يُنتج
    ضرباً ديكارتيّاً (صادر × وارد) لكلّ كتاب.
    """
    from core.models import Book, Department

    entity_ids = (Department.objects.filter(pk__in=department_ids,
                                            entity__isnull=False)
                  .values('entity_id'))
    return Book.objects.filter(
        Q(issuing_entities__in=entity_ids) | Q(receiving_entities__in=entity_ids)
    ).values('pk')


def scope_referrals_for(user, qs=None):
    """صفوفُ الإحالة المرئيّة للمستخدم — النطاقُ في الاستعلام لا في القالب.

    ثلاثةُ أطراف لكلّ صفّ، ولكلٍّ منها حقٌّ مشروعٌ في رؤيته: **قسمُ الكتاب**
    (المالك يتابع أين وصل)، و**القسمُ المُرسِل** (وقد يكون غيرَ المالك في
    السلسلة)، و**القسمُ المستقبِل** (الالتزامُ عليه). وما عدا ذلك لا يراه.
    """
    from core.models import BookReferral

    if qs is None:
        qs = BookReferral.objects.all()
    if is_privileged(user):
        return qs

    dept_id = user_department_id(user)
    if dept_id is None:
        return qs.filter(book__created_by=user)
    mine = subtree_ids(dept_id)
    return qs.filter(
        Q(book__department_id__in=mine)
        | Q(to_department_id__in=mine)
        | Q(from_department_id__in=mine)
        | Q(book__created_by=user)
    )


def guard_secret_text_search(qs, user, search_text):
    """يمنع البحثَ **النصّيّ** من كشف السرّيّ لغير المخوَّل.

    أخطرُ قناةِ تسريبٍ في المنظومة كلّها: حجبُ العنوان في صفحة التفاصيل بلا
    قيمةٍ إن كان البحثُ بكلمةٍ من ذلك العنوان يُعيد الكتاب — عندها يصير البحثُ
    **أداةَ استنطاق**: تُجرّب الكلمات حتى تعرف الموضوع.

    والقاعدة: السرّيُّ يُطابَق **برقمه وتاريخه** — وهما ظاهران في الدفتر أصلاً —
    ولا يُطابَق بعنوانٍ ولا جهةٍ ولا هامش. فالنصّيُّ يستثنيه كلَّه.

    **والرقميُّ لا يمرّ كما هو**: ``apply_search_filters`` يطابق الرقمَ على رقم
    الجهة والرقم القديم والعنوان والهامش أيضاً، فكان «771» يُعيد السرّيَّ الظاهرَ
    برقمه متى ورد في رقم جهته المحجوب — تأكيدُ محتوىً رقماً رقماً. فلا يبقى من
    المقيَّد إلّا ما طابق **هويّتَه** (``numbering.identity_search_q``).

    (يُطبَّق في ``BookFilterEngine`` بعد البحث مباشرةً — نقطةُ اختناقٍ واحدة.)
    """
    text = (search_text or '').strip()
    if not text or is_privileged(user):
        return qs
    identity = numbering.identity_search_q(text)
    if identity is None:
        return qs.exclude(_unauthorized_secret_q(user))
    return qs.exclude(_unauthorized_secret_q(user) & ~identity)


def content_authorized_books(qs, user):
    """الكتبُ التي يملك المستخدمُ محتواها — لكلّ ما يكشف **علاقاتِ** الكتاب لا رقمَه.

    جهاتُ الإرسال والورود والتوزيع محتوىً كالعنوان: قائمةُ جهاتٍ مبنيّةٌ من سرّيٍّ
    محجوب، أو تصفيةٌ بجهةٍ تُعيده، تكشف مراسلاتِه جهةً جهة.
    """
    if is_privileged(user):
        return qs
    return qs.exclude(_unauthorized_secret_q(user))


def _unauthorized_secret_q(user):
    """الكتبُ السرّيّة التي لا يملك هذا المستخدم محتواها.

    **شقّاً بشقٍّ مع ``secret_access``**: المُنشئُ · المخوَّلُ بالدور داخل قسمه ·
    وصاحبُ المنحة الفرديّة. وأيُّ شقٍّ يُضاف إلى إحداهما دون الأخرى يُسقطه
    حارسُ التطابق في ``tests_archivist_role``.
    """
    q = Q(secret_level__in=RESTRICTED_SECRET_LEVELS) & ~Q(created_by=user)
    dept_id = user_department_id(user)
    if dept_id and _department_custodian(user):
        # مخوَّلٌ بالدور داخل قسمه — فلا يُستثنى منه إلّا سرّيُّ غيره.
        q &= ~Q(department_id=dept_id)
    # ومُفوَّضٌ بعينه على كتابٍ بعينه — من المسند نفسِه الذي يقرؤه
    # ``_has_live_grant``، لا من نسخةٍ ثانيةٍ تنحرف عنه.
    q &= ~Q(pk__in=_live_grants_for(user).values('book_id'))
    return q


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


#: الحقولُ التي يُصفَّر محتواها في العرض المقيَّد — والباقي يمرّ كما هو.
#: تُبقى **الأربعةُ الظاهرة في الدفتر الورقيّ**: الرقم والتاريخ والنوع (وارد/صادر
#: — ``kind``، لا نوعُ المستند: ``document_type`` مُصفَّرٌ أدناه) والقسم.
STUB_BLANK_FIELDS = (
    'sender_number', 'director_general_number', 'sender_date', 'sender_date_display', 'margin',
    'document_type', 'attachment_url', 'legacy_number',
)

#: عنوانُ الكتاب المقيَّد كما يُعرض.
STUB_TITLE = '— سرّي —'


def shown_field_sql(user, field, hidden):
    """قيمةُ حقلٍ **كما يراها المستخدم** — تعبيرُ SQL يُفرَز عليه ويُجمَّع ويُصفّى.

    ``stub_book_payload`` وأخواتُه تحجب ما **يُطبع**؛ لكنّ الاستعلامَ نفسَه يكشف
    ما لا يُطبع: الفرزُ بالعنوان يضع الصفَّ المحجوبَ في موضع عنوانه الحقيقيّ بين
    جيرانه (فيُستخرج حرفاً حرفاً بتعديل عنوانِ كتابٍ يملكه الباحث)، والتجميعُ
    بنوع المستند يُسمّي ملفّاً بنوع كتابٍ محجوب ويعدّه. فمن لا يملك المحتوى
    يُفرَز ويُجمَّع ويُصفّى على ``hidden`` لا على القيمة.

    المسندُ هو ``_unauthorized_secret_q`` — توأمُ ``secret_access`` المحروسُ
    بالتطابق — فالمحجوبُ في SQL هو المحجوبُ في العرض. و``user=None`` فشلٌ
    مغلق: لا أحدَ مخوَّل، فيُحجب كلُّ مقيَّد.
    """
    from django.db.models import Case, CharField, F, Value, When

    if user is not None and is_privileged(user):
        return F(field)
    restricted = (Q(secret_level__in=RESTRICTED_SECRET_LEVELS) if user is None
                  else _unauthorized_secret_q(user))
    return Case(When(restricted, then=Value(hidden)), default=F(field),
                output_field=CharField())


def restricted_flag_sql(user):
    """أمحجوبٌ محتوى هذا الصفّ عن المستخدم؟ — علَمٌ منطقيٌّ في SQL.

    **توأمُ ``shown_field_sql`` على المسند نفسِه** (``_unauthorized_secret_q``،
    المحروسِ بالتطابق مع ``secret_access``): صفحةٌ تعرض صفوفاً كثيرة وتصدّرها
    تسأل الاستعلامَ مرّةً بدل ``secret_access`` لكلّ صفّ، وتُصفّي عليه ما لا يجوز
    أن يُطابَق («لا يُطابَق بجهةٍ» — ``guard_secret_text_search``). ومديرُ النظام
    لا محجوبَ عنه؛ و``user=None`` فشلٌ مغلق كأخيه.
    """
    from django.db.models import BooleanField, Case, Value, When

    if user is not None and is_privileged(user):
        return Value(False, output_field=BooleanField())
    restricted = (Q(secret_level__in=RESTRICTED_SECRET_LEVELS) if user is None
                  else _unauthorized_secret_q(user))
    return Case(When(restricted, then=Value(True)), default=Value(False),
                output_field=BooleanField())


def stub_book_payload(payload):
    """يحجب محتوى كتابٍ سرّيّ من حمولةٍ **مُسلسَلةٍ سلفاً**.

    يعمل على القاموس لا على النموذج عمداً: مُسلسِلُ القائمة واحدٌ ويُستدعى في
    موضعٍ واحد، فالحجبُ بعده يضمن أنّ **كلّ حقلٍ يُضاف مستقبلاً إلى الحمولة
    يمرّ من هنا** — بينما الحجبُ داخل المُسلسِل كان سيُنسى مع أوّل حقلٍ جديد.

    ولا يُحجب: الرقمُ والتاريخُ والنوعُ (وارد/صادر) والقسم — لأنّ **الدفتر
    الورقيّ يكشفها للجميع**، وإخفاؤها يكسر تسلسل الدفتر عند الكاتب.
    """
    payload = dict(payload)
    payload['title'] = STUB_TITLE
    payload['is_secret_stub'] = True
    for field in STUB_BLANK_FIELDS:
        if field in payload:
            payload[field] = '' if isinstance(payload.get(field), str) else None
    payload['issuing_entities'] = []
    payload['receiving_entities'] = []
    return payload


def present_book_payload(payload, book, user):
    """يمرّر الحمولة كما هي، أو مقيَّدةً إن لم يملك المستخدمُ محتواها."""
    if secret_access(user, book) == ACCESS_FULL:
        payload['is_secret_stub'] = False
        return payload
    return stub_book_payload(payload)

# ══════════════════════════════════════════════════════════════════
#  محلِّلُ الصلاحيّات — «الفعلُ» قاعدةٌ قابلةٌ للتعديل، و«النطاقُ» كود
#  ─────────────────────────────────────────────────────────────────
#  ``can_X(book, user) = في_النطاق(book, user) AND has_capability(user, 'X')``.
#  الصلاحيّةُ تقرّر ماذا يفعل الموظّف، والهيكلُ يقرّر على أيّ كتب: فلا يصل منحٌ
#  إلى كتب قسمٍ آخر ولا إلى السرّيّ. والمصفوفةُ قراراتُ المالك للمستوى 3 (2026‑11‑02)
#  بتعديلات مراجعة 2026‑11‑03. الحرّاسُ توصل بها شريحةً شريحة.
# ══════════════════════════════════════════════════════════════════

ROLE_HEAD, ROLE_MAIL, ROLE_ARCHIVIST, ROLE_ENTRY = 'head', 'mail', 'archivist', 'entry'
ROLE_UNIT, ROLE_EXECUTOR, ROLE_READER = 'unit', 'executor', 'reader'
ROLE_LABELS = {
    ROLE_HEAD: 'رئيس قسم', ROLE_MAIL: 'مختصّ البريد', ROLE_ARCHIVIST: 'مسؤول الأرشفة',
    ROLE_ENTRY: 'مدخل', ROLE_UNIT: 'مسؤول شعبة أو وحدة', ROLE_EXECUTOR: 'موظّف تنفيذ', ROLE_READER: 'قارئ',
}
_EVERYONE = frozenset(ROLE_LABELS)
_WRITERS = frozenset({ROLE_HEAD, ROLE_MAIL, ROLE_ARCHIVIST, ROLE_ENTRY})
_CUSTODIANS = frozenset({ROLE_HEAD, ROLE_MAIL, ROLE_ARCHIVIST})
_DESK = frozenset({ROLE_HEAD, ROLE_MAIL})
_OVERSEERS = frozenset({ROLE_HEAD, ROLE_UNIT})


class Capability(NamedTuple):
    label: str
    group: str
    holders: frozenset
    locked: bool = False


CAPABILITIES = {
    'book.read': Capability('قراءة كتب نطاقه', 'الكتب', _EVERYONE, locked=True),
    'book.comment': Capability('التعليق', 'الكتب', _EVERYONE),
    'book.enter': Capability('الإدخال', 'الكتب', _WRITERS),
    'book.edit': Capability('التعديل', 'الكتب', _WRITERS),
    'number.reserve': Capability('حجز رقم', 'الكتب', _WRITERS),
    'entity.add': Capability('إضافة جهة جديدة', 'الكتب', _WRITERS),
    'book.trash': Capability('الحذف إلى السلّة', 'الكتب', _DESK),
    'book.restore': Capability('الاسترجاع من السلّة', 'الكتب', _CUSTODIANS),
    'secret.own': Capability('فتح سرّيّ قسمه', 'الكتب', _CUSTODIANS, locked=True),
    'secret.other': Capability('فتح سرّيّ الأقسام الأخرى', 'الكتب', frozenset(), locked=True),
    'referral.send': Capability('الإحالة', 'الإحالة والإنجاز', frozenset({ROLE_HEAD, ROLE_MAIL, ROLE_UNIT})),
    'referral.receive': Capability('استلام المُحال وإنجازه', 'الإحالة والإنجاز',
                                   frozenset({ROLE_HEAD, ROLE_MAIL, ROLE_UNIT, ROLE_EXECUTOR})),
    'custody.link': Capability('العهدة والربط', 'الإحالة والإنجاز', _WRITERS),
    'book.sign': Capability('التوقيع', 'الإحالة والإنجاز', frozenset({ROLE_HEAD}), locked=True),
    'archive.complete': Capability('تمام الأرشفة', 'الإحالة والإنجاز', frozenset({ROLE_ARCHIVIST})),
    # الطاولةُ للمنفِّذ مقصورةً على وحدته (قرارُ المالك 2026‑11‑04)، والدفترُ والكشفُ ليسا له.
    'desk.board': Capability('طاولة البريد', 'الطاولات', _DESK | {ROLE_EXECUTOR}),
    'desk.ledger': Capability('الدفتر وكشف التسليم', 'الطاولات', _DESK),
    'desk.mine': Capability('طاولتي', 'الطاولات', frozenset({ROLE_UNIT})),
    'report.view': Capability('التقارير', 'الرقابة', _OVERSEERS),
    'audit.view': Capability('سجلّ الحركات', 'الرقابة', _OVERSEERS),
    'mail.operate': Capability('تشغيل البريد', 'البريد', frozenset({ROLE_MAIL})),
    'mail.send_book': Capability('إرسال الكتاب بالبريد', 'البريد', frozenset({ROLE_MAIL})),
    'mail.settings': Capability('إعدادات بريد الشركة', 'البريد', frozenset(), locked=True),
    'staff.manage': Capability('إدارة موظّفي نطاقه', 'الإدارة', _OVERSEERS, locked=True),
    'grant.office': Capability('منح مختصّ البريد والأرشفة والمدخل', 'الإدارة', frozenset({ROLE_HEAD}), locked=True),
    'grant.basic': Capability('منح موظّف التنفيذ والقارئ', 'الإدارة', _OVERSEERS, locked=True),
    'unit.add': Capability('إضافة الوحدات', 'الإدارة', frozenset({ROLE_HEAD}), locked=True),
    'account.manage': Capability('إنشاء الحسابات وحذفها', 'الإدارة', frozenset(), locked=True),
}

# ما يقرؤه حارسٌ فعلاً اليوم. البقيّةُ مسجَّلةٌ في المصفوفة ولم يُربط حارسُها بعد فتعمل بالأدوار
# القديمة: صفحةُ الأدوار تعرضها ولا تقبل تعديلها، كي لا تقول «يسري الآن» على ما لا يسري.
# كلُّ شريحةٍ تربط حارساً تضيف مفتاحه هنا، واختبارُ التطابق في tests_roles_page يفشل إن نُسي.
# الإحالة (11-04) · الإدخالُ والتعديلُ وحجزُ الرقم وإضافةُ الجهة والعهدةُ والربط ((ب)3، 11-11) ·
# الحذفُ إلى السلّة والاسترجاعُ منها ((ب)4، 11-11).
WIRED_CAPABILITIES = frozenset({'book.enter', 'book.edit', 'number.reserve', 'entity.add', 'book.trash',
                                'book.restore', 'referral.send', 'referral.receive', 'custody.link'})

# القارئُ احتياطيُّ كلِّ حسابٍ بلا دور: منحُ الكتابة له على مستوى الدور يمنحها للجميع،
# فتُجمَّد خليّتُه هو والمنفِّذ في المصفوفة، وتبقى ممكنةً باستثناءٍ لشخصٍ بعينه.
_FROZEN_ROLES = frozenset({ROLE_EXECUTOR, ROLE_READER})
_FROZEN_FOR_THEM = frozenset({'book.enter', 'book.edit', 'number.reserve', 'entity.add', 'book.trash',
                              'book.restore', 'custody.link', 'mail.send_book'})


def role_cell_frozen(key, role) -> bool:
    return key in _FROZEN_FOR_THEM and role in _FROZEN_ROLES


def role_of(user) -> str:
    """الدورُ الواحد لهذا الحساب، مشتقٌّ من العلَم والمجموعات ومستوى الوحدة بلا تخزين."""
    from core.roles import (ARCHIVE_ALL_GROUP_NAME, ARCHIVIST_GROUP_NAME, CONTROLLER_GROUP_NAME,
                            ENTRY_GROUP_NAME, EXECUTOR_GROUP_NAME)

    profile = getattr(user, 'profile', None)
    if profile is not None and profile.is_department_head:
        department = profile.department
        return ROLE_HEAD if department is None or department.holds_register else ROLE_UNIT
    # ``all()`` لا ``values_list``: صفحةُ المصفوفة تعدّ الحاملين بمجموعاتٍ مجلوبةٍ سلفاً.
    names = {group.name for group in user.groups.all()}
    if CONTROLLER_GROUP_NAME in names:
        return ROLE_MAIL
    if names & {ARCHIVIST_GROUP_NAME, ARCHIVE_ALL_GROUP_NAME}:
        return ROLE_ARCHIVIST
    if ENTRY_GROUP_NAME in names:
        return ROLE_ENTRY
    if EXECUTOR_GROUP_NAME in names:
        return ROLE_EXECUTOR
    return ROLE_READER


def role_capability(role, key, overrides=None) -> bool:
    """ما يملكه الدورُ كما هو الآن: الافتراضُ أو تجاوزُه، بلا استثناءات الأشخاص.

    ``overrides`` ({(role, key): allowed}) لمن قرأ الجدولَ كلَّه مرّةً، كصفحة المصفوفة.
    """
    from core.models import RoleCapabilityOverride

    capability = CAPABILITIES[key]
    default = role in capability.holders
    if capability.locked or role_cell_frozen(key, role):
        return default
    if overrides is not None:
        return overrides.get((role, key), default)
    row = RoleCapabilityOverride.objects.filter(role=role, capability=key).first()
    return row.allowed if row else default


def _capability_rows(user):
    """الدورُ وصفوفُ التجاوز، مرّةً لكلّ كائن مستخدم (كائنٌ جديدٌ لكلّ طلب)."""
    rows = getattr(user, '_capability_rows_cache', None)
    if rows is None:
        from core.models import RoleCapabilityOverride, UserCapabilityOverride

        role = role_of(user)
        rows = (role,
                dict(RoleCapabilityOverride.objects.filter(role=role).values_list('capability', 'allowed')),
                dict(UserCapabilityOverride.objects.filter(user=user).values_list('capability', 'allowed')))
        user._capability_rows_cache = rows
    return rows


def clear_capability_cache(user) -> None:
    user.__dict__.pop('_capability_rows_cache', None)


def has_capability(user, key) -> bool:
    """أيملك هذا الفعل؟ سوبر ⟵ مقفل ⟵ استثناءُ الشخص ⟵ تجاوزُ الدور ⟵ الافتراض.

    مفتاحٌ مجهولٌ خطأٌ برمجيّ فيرفع ``KeyError``: بوّابةٌ تسأل عن شيءٍ غير مسجَّل لا تُفتح ولا تُغلق بصمت.
    """
    capability = CAPABILITIES[key]
    if not (getattr(user, 'is_authenticated', False) and user.is_active):
        return False
    if is_privileged(user):
        return True
    role, role_rows, user_rows = _capability_rows(user)
    default = role in capability.holders
    if capability.locked:
        return default
    if key in user_rows:
        return user_rows[key]
    if key in role_rows and not role_cell_frozen(key, role):
        return role_rows[key]
    return default


def can_edit_role_matrix(user) -> bool:
    """مصفوفةُ الأدوار العامّة: «يعدّلها مدير النظام وحده» (قرارُ المالك 2026‑11‑03)."""
    return is_privileged(user)


def can_edit_exception(by, target, key) -> bool:
    """استثناءُ شخص: السوبر، أو رئيسُ القسم لموظّفيه فقط «وضمن ما يملكه هو». ولا أحدَ لنفسه.

    مسؤولُ الشعبة والوحدة مغلقٌ بقرار المالك 2026‑11‑03.
    """
    if by.pk == target.pk or CAPABILITIES[key].locked:
        return False
    if is_privileged(by):
        return True
    return role_of(by) == ROLE_HEAD and can_manage_user(by, target) and has_capability(by, key)


def can_send_referral(book, user) -> bool:
    """أيُحيل هذا الكتاب أو يطارد إحالتَه؟ الفعلُ من المحلِّل، ومحتوى الكتاب شرطٌ لا يوسّعه منح."""
    return has_capability(user, 'referral.send') and can_open_content(book, user)


def can_enter_book(user) -> bool:
    """إدخالُ كتابٍ جديد — مفتاحُ «الإدخال»: الحفظُ الأوّل، ووضعُ الإدخال في صفحته، وكلُّ
    رابطٍ إليه (الشريطُ ولوحةُ التحكّم و«إدخال كتابٍ مماثل»)."""
    return has_capability(user, 'book.enter')


def can_use_entry_desk(user) -> bool:
    """صفحةُ الإدخال وأدواتُها (الاستخراجُ والمسح) تخدم وضعين: كتاباً جديداً وتعديلَ كتابٍ
    قائم (``edit_pk``) — فتُفتح لمن يملك «الإدخال» أو «التعديل»، والصفحةُ تسأل عن مفتاح
    وضعها (قرارُ المالك 2026‑11‑11). والحفظُ مساران: ``save_book_api`` بالإدخال
    و``update_book_api`` بالتعديل."""
    return can_enter_book(user) or has_capability(user, 'book.edit')


def can_enter_for(user, department) -> bool:
    """الإدخالُ في دفتر قسمٍ يُختار من صفحته في مركز الأقسام — لمدير النظام وحده، وفي قسمٍ نشطٍ
    يمسك سجلَّه **هو** (مواصفةُ المالك (ب)3). لا صعودَ إلى ماسك: تأكيدٌ يسمّي شعبةً ويستهلك
    عدّادَ أبيها يكذب. وغيرُه يُدخل في دفتر قسمه (``BookSequence.resolve_department``)."""
    return (is_privileged(user) and department is not None
            and department.is_active and department.holds_register)


def can_reserve_number(user) -> bool:
    """حجزُ رقمٍ مسبقاً وإعادةُ تفعيل حجزٍ — مفتاحُ «حجز رقم»، وزرُّه في صفحة الإدخال يتبعه."""
    return has_capability(user, 'number.reserve')


def can_add_entity(user) -> bool:
    """إضافةُ جهةٍ جديدة إلى السجلّ من نقطة ``add_new_entity`` — مفتاحُ «إضافة جهة جديدة»."""
    return has_capability(user, 'entity.add')


def can_refer_to(user, department=None) -> bool:
    """إلى أين يُحيل؟ نطاقٌ لا صلاحيّة: ديوانُ قسمٍ يمسك سجلّاً يُحيل حيث شاء،
    والشعبةُ والوحدةُ إلى ما تحتهما فقط، و``None`` (جهةٌ خارجيّة) خارجُ يدهما."""
    if is_privileged(user):
        return True
    profile = getattr(user, 'profile', None)
    own = profile.department if profile is not None else None
    if own is None or own.holds_register:
        return True
    return department is not None and getattr(department, 'pk', department) in subtree_ids(own.pk)
