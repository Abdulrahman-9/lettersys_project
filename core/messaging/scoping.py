"""
نطاق رؤية البريد — مصدرٌ واحد للقاعدة.

كانت وحدة البريد كلّها بلا نطاق: ``mail_sent`` و``mail_inbox`` و``mail_thread``
و``mail_compose`` و``book_email_logs`` تعرض بريد **كلّ** الكتب لأيّ مستخدمٍ
مسجَّل، وعدّاد غير المقروء يُحسب على النظام كلّه. صندوقٌ واحد مشترك يقرأه
الجميع (سجلّ العيوب ح1).

القاعدة هنا مطابقة لقاعدة الكتب المعمول بها: مدير النظام يرى كلّ شيء، ومسؤول
البريد يرى مراسلات الكتب التي يستطيع فتحها في نطاق قسمه. وبقيّة المستخدمين
يرون مراسلات كتبهم هم. ورسالةٌ بلا كتاب لا يراها إلا مرسلها أو مدير النظام.

**لماذا ملفٌّ مستقلّ:** هذه ترجمةُ قاعدةِ الكتب إلى لغة البريد (خيوط، رسائل
واردة، سجلّات صادرة). صلاحيةُ فتح المحتوى من ``core/scoping.py`` هي الحارس
الأخير، فلا تكشف مراسلاتُ كتابٍ سرّيّ لمَن لا يفتح محتواه.
"""


from django.db.models import Q

from core.scoping import (
    RESTRICTED_SECRET_LEVELS,
    _live_grants_for,
    is_mail_officer,
    is_privileged,
    scope_books_for,
    user_department_id,
)


def sees_all_mail(user) -> bool:
    """أهذا مستخدمٌ إداريّ يرى بريد الجميع؟ — تفويضٌ للمصدر الوحيد."""
    return is_privileged(user)


def scope_sent_logs(qs, user):
    """سجلّات البريد الصادر التي يحقّ للمستخدم رؤيتها.

    الرسالة بلا كتاب (مسموحةٌ منذ صارت ``BookEmailLog.book`` اختياريّة) لا مالك
    لها عبر الكتاب — فمالكها مُرسِلها. بدون هذا الشرط تختفي رسائل المستخدم
    الإداريّة من صادره لأنّ الوصل عبر ``book__`` يُسقط الصفوف الفارغة.
    """
    if sees_all_mail(user):
        return qs
    from core.models import Book

    books = scope_mail_books(Book.objects.all(), user)
    return qs.filter(Q(book__in=books) | Q(book__isnull=True, sent_by=user))


def scope_incoming(qs, user):
    """الرسائل الواردة التي يحقّ للمستخدم رؤيتها.

    الوارد يصل إمّا ردّاً على رسالةٍ صادرة (فله كتاب عبر الخيط) وإمّا من جهةٍ
    مسجَّلة بلا خيطٍ لكتاب — والثانية بلا مالكٍ طبيعيّ فتبقى للإداريّ.
    """
    if sees_all_mail(user):
        return qs
    from core.models import EmailThread

    threads = scope_threads(EmailThread.objects.all(), user)
    return qs.filter(thread__in=threads)


def scope_books(qs, user):
    """الكتب التي يحقّ للمستخدم مراسلتها/رؤية بريدها — تفويضٌ للمصدر الوحيد."""
    return scope_books_for(user, qs)


def scope_mail_books(qs, user):
    """الكتب التي يحقّ للمستخدم قراءة مراسلاتها دون كشف محتوى السرّيّ المحجوب."""
    if sees_all_mail(user):
        return qs
    if not is_mail_officer(user):
        return qs.filter(created_by=user)

    department_id = user_department_id(user)
    live_grants = _live_grants_for(user)
    scoped = scope_books_for(user, qs)
    restricted_content_access = (
        Q(created_by=user)
        | Q(department_id=department_id)
        | Q(pk__in=live_grants.values('book_id'))
    )
    openable = scoped.filter(
        Q(secret_level='normal')
        | Q(secret_level__in=RESTRICTED_SECRET_LEVELS)
        & restricted_content_access
    )
    return openable | qs.filter(pk__in=live_grants.values('book_id'))


def mailable_book(user, book_id):
    """الكتابُ الذي يحقّ للمستخدم مراسلةُ جهته عنه — أو ``None``.

    **البريدُ محتوى لا صفّ**: الموضوعُ يحمل العنوان، والمعاينةُ أسماءَ الملفّات،
    والإرسالُ الملفّاتِ نفسَها، والقالبُ يُصيَّر بـ``book.title``. فالسؤالُ
    ``can_open_content`` لا ``can_view_book`` — وإلّا أخذ مَن لا يرى من السرّيّ
    إلّا كعبَه عنوانَه ومرفقاتِه من باب البريد (وأرسلها فعلاً).

    وجوابُ الحالتين واحد (``None`` ⟵ «غير موجود»): فلا يُفرَّق بين كتابٍ خارج
    النطاق وسرّيٍّ مُغلق المظروف.
    """
    from core.models import Book
    from core.scoping import can_open_content

    if not str(book_id or '').isdigit():
        return None
    book = scope_mail_books(Book.objects.all(), user).filter(pk=int(book_id)).first()
    if book is None or not can_open_content(book, user):
        return None
    return book


def repliable_thread(user, thread_id):
    """الخيطُ الذي يحقّ للمستخدم الردُّ فيه — أو ``None`` (تدقيقُ نيلسن E#2، مذكّرةُ فيبل).

    كان ``api_compose`` يأخذ ``EmailThread`` بالرقم مطلقاً — فيعلّق أيُّ مستخدمٍ رسالتَه
    على خيطِ غيره (IDOR). والجوابُ للخارج عن النطاق «غير موجود» كـ``mailable_book``.
    """
    from core.models import EmailThread

    if not str(thread_id or '').isdigit():
        return None
    threads = scope_threads(EmailThread.objects.select_related('book', 'entity'), user)
    return threads.filter(pk=int(thread_id)).first()


def scope_threads(qs, user):
    """خيوط المراسلة التي يحقّ للمستخدم رؤيتها/تعديل حالتها."""
    if sees_all_mail(user):
        return qs
    from core.models import Book

    books = scope_mail_books(Book.objects.all(), user)
    return qs.filter(
        Q(book__in=books)
        | Q(book__isnull=True, created_by=user)
    )


def can_view_thread(thread, user) -> bool:
    """أيحقّ للمستخدم فتح هذا الخيط؟"""
    if sees_all_mail(user):
        return True
    if thread.book_id:
        return can_view_book_mail(thread.book, user)
    return thread.created_by_id == user.id


def can_view_book_mail(book, user) -> bool:
    """أيحقّ للمستخدم رؤية بريد هذا الكتاب؟"""
    from core.models import Book

    return scope_mail_books(Book.objects.filter(pk=book.pk), user).exists()
