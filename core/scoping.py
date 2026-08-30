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
  فلا ينكسر تنصيبٌ لم تُبذَر أقسامُه بعد.

**`is_staff` لا تُوسّع الرؤية.** كانت تمنح حاملها رؤيةَ كلّ الكتب ضمناً،
وإبقاؤها مع نطاق القسم يقوّضه من يومه الأوّل. صارت صفةً إداريّةً لواجهات
الإدارة فحسب — وهي ما يحرسه ``staff_required``.
"""

from django.db.models import Q
from django.utils import timezone

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


def is_department_head(user) -> bool:
    profile = getattr(user, 'profile', None)
    return bool(profile and profile.is_department_head)


def is_mail_officer(user) -> bool:
    """أهو مختصُّ البريد والأرشفة في قسمه؟

    شهادةُ موظّف البريد: «السرّي يُحفظ في السجلّ عاديّ، لكن فقط **مسؤول إدارة
    البريد والأرشفة** يحقّ لهم الاطّلاع». فهو أمينُ السرّيّ فعليّاً — يمسكه
    بيده ويفرّقه — فيُخوَّل بدوره لا بمنحةٍ فرديّة.
    """
    from core.roles import get_user_role

    return get_user_role(user) == 'controller'


def can_view_audit(user) -> bool:
    """أيحقّ له فتحُ **سجلّ الحركات**؟ رئيسُ القسم والسوبر أدمن حصراً.

    **ومختصُّ البريد لا يراه** رغم أنّه أمينُ السرّيّ تشغيليّاً: سجلُّ القراءة
    أداةُ **مراقبةِ أشخاص** لا أداةُ بريد، ومَن يحاسِب موظّفي القسم هو رئيسُه.
    """
    return is_privileged(user) or is_department_head(user)


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
    return qs.filter(Q(department_id__in=mine) | Q(book__department_id__in=mine))


def can_use_desk(user) -> bool:
    """أيحقّ له فتحُ **طاولة البريد** (كشفُ التسليم ودفترُ الوارد المطبوع)؟

    مختصُّ البريد ورئيسُ القسم ومديرُ النظام. وهي ليست بوّابةَ سرّيّةٍ بل
    بوّابةُ **سطحٍ يخرج من الجهاز**: ورقةٌ تحمل خريطةَ عمل القسم كاملةً.
    """
    return is_privileged(user) or is_department_head(user) or is_mail_officer(user)


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
    if same_department and (is_department_head(user) or is_mail_officer(user)):
        return ACCESS_FULL

    if _has_live_grant(user, book):
        return ACCESS_FULL
    return ACCESS_STUB


def _has_live_grant(user, book) -> bool:
    """أعنده تفويضٌ سارٍ على هذا الكتاب بعينه؟"""
    if not getattr(user, 'pk', None):
        return False
    from core.models import SecretAccessGrant

    now = timezone.now()
    return SecretAccessGrant.objects.filter(
        book=book, user=user, revoked_at__isnull=True,
    ).filter(Q(expires_at__isnull=True) | Q(expires_at__gt=now)).exists()


def can_view_book(book, user) -> bool:
    """أيحقّ للمستخدم أن يرى هذا الكتاب في قوائمه؟

    **صارت تُجيب عن الصفّ لا عن المحتوى:** السرّيُّ يظهر لأهل القسم بسجلّه
    (رقمٌ وتاريخ)، ومحتواه يحكمه ``secret_access``. فمن أراد المحتوى فليسأل
    عنه، ولا يُخلط السؤالان.
    """
    if is_privileged(user):
        return True

    is_owner = book.created_by_id == user.id
    dept_id = user_department_id(user)
    if dept_id is None:
        return is_owner
    if is_owner or book.department_id in subtree_ids(dept_id):
        return True
    # **توأمُ الشقّ الثالث في `scope_books_for`** — وانفراجُهما هو صنفُ العيب
    # الذي كلّفنا مرّتين: مسندٌ يتّسع وقرينُه لا، فيظهر الكتابُ في القائمة
    # ويُرفض عند فتحه (أو العكس، وهو أسوأ).
    return _referred_to(dept_id).filter(book_id=book.pk).exists()


def can_open_content(book, user) -> bool:
    """أيحقّ له **فتحُ محتوى** الكتاب: مرفقاته ونصّه وهوامشه وتعليقاته؟

    تفترق عن ``can_view_book`` عند السرّيّ وحده — وهذا هو الفرق الذي وُجدت
    الطبقةُ لأجله: الصفُّ يُرى، والمظروفُ يُفتح بإذن. وكلُّ عمليّةٍ على مرفقٍ
    (خدمةً أو رفعاً أو حذفاً أو دمجاً) تمرّ من هنا لا من ``can_view_book``.
    """
    return can_view_book(book, user) and secret_access(user, book) == ACCESS_FULL


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

    # كتبُ قسمك **وشُعبِه** — بما فيها السرّيّة — ومعها ما أنشأته أنت (ولو
    # انتقلتَ بين الأقسام)، **وما فُرِّق إليك**. والسرّيُّ يظهر صفّاً ويُحجب
    # محتواه في طبقة العرض.
    #
    # الشقُّ الثالث هو ما يجعل التفريقَ عملاً لا صفوفاً في جدول: الكتابُ يبقى
    # مملوكاً لقسمٍ واحد، والوحدةُ المُحال إليها تراه بلا نقلِ ملكيّة. وهو
    # **استعلامٌ فرعيّ لا وصلة** عمداً: الوصلةُ تُكرّر الصفَّ بعدد إحالاته
    # فيلزم `distinct()` على كلّ قائمةٍ في النظام.
    return qs.filter(
        Q(department_id__in=subtree_ids(dept_id))
        | Q(created_by=user)
        | Q(pk__in=_referred_to(dept_id))
    )


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


def _referred_to(department_id):
    """معرِّفاتُ الكتب المُفرَّقة إلى قسمٍ بعينه — أيّاً كانت حالةُ الالتزام.

    **حتى المنجَزة**: الوحدةُ التي نفّذت كتاباً قبل شهرٍ يجب أن تجده حين تُسأل
    عنه، وإخفاؤه بإغلاق الالتزام يُضيع المستند من حيث أُنجز.
    """
    from core.models import BookReferral

    return BookReferral.objects.filter(
        to_department_id=department_id
    ).values('book_id')


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
    ولا يُطابَق بعنوانٍ ولا جهةٍ ولا هامش. فالبحثُ الرقميّ يمرّ، والنصّيُّ
    يستثنيه.

    (يُطبَّق في ``BookFilterEngine`` بعد البحث مباشرةً — نقطةُ اختناقٍ واحدة.)
    """
    text = (search_text or '').strip()
    if not text or is_privileged(user):
        return qs
    if _is_numeric_query(text):
        return qs
    return qs.exclude(_unauthorized_secret_q(user))


def _is_numeric_query(text) -> bool:
    """أبحثٌ برقمٍ هو؟ — يطابق فرعَي ``apply_search_filters`` الرقميّين."""
    import re

    return bool(text.isdigit() or re.match(r'^(\d+)[-/](\d+)$', text))


def _unauthorized_secret_q(user):
    """الكتبُ السرّيّة التي لا يملك هذا المستخدم محتواها."""
    q = Q(secret_level__in=RESTRICTED_SECRET_LEVELS) & ~Q(created_by=user)
    dept_id = user_department_id(user)
    if dept_id and (is_department_head(user) or is_mail_officer(user)):
        # مخوَّلٌ بالدور داخل قسمه — فلا يُستثنى منه إلّا سرّيُّ غيره.
        q &= ~Q(department_id=dept_id)
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
#: تُبقى **الأربعةُ الظاهرة في الدفتر الورقيّ**: الرقم والتاريخ والنوع والقسم.
STUB_BLANK_FIELDS = (
    'sender_number', 'sender_date', 'sender_date_display', 'margin',
    'document_type', 'attachment_url', 'legacy_number',
)

#: عنوانُ الكتاب المقيَّد كما يُعرض.
STUB_TITLE = '— سرّي —'


def stub_book_payload(payload):
    """يحجب محتوى كتابٍ سرّيّ من حمولةٍ **مُسلسَلةٍ سلفاً**.

    يعمل على القاموس لا على النموذج عمداً: مُسلسِلُ القائمة واحدٌ ويُستدعى في
    موضعٍ واحد، فالحجبُ بعده يضمن أنّ **كلّ حقلٍ يُضاف مستقبلاً إلى الحمولة
    يمرّ من هنا** — بينما الحجبُ داخل المُسلسِل كان سيُنسى مع أوّل حقلٍ جديد.

    ولا يُحجب: الرقمُ والتاريخُ والنوعُ والقسم — لأنّ **الدفتر الورقيّ يكشفها
    للجميع**، وإخفاؤها يكسر تسلسل الدفتر عند الكاتب.
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
