"""
نطاق رؤية البريد — مصدرٌ واحد للقاعدة.

كانت وحدة البريد كلّها بلا نطاق: ``mail_sent`` و``mail_inbox`` و``mail_thread``
و``mail_compose`` و``book_email_logs`` تعرض بريد **كلّ** الكتب لأيّ مستخدمٍ
مسجَّل، وعدّاد غير المقروء يُحسب على النظام كلّه. صندوقٌ واحد مشترك يقرأه
الجميع (سجلّ العيوب ح1).

القاعدة هنا مطابقة لقاعدة الكتب المعمول بها: الإداريّ (superuser أو staff) يرى
كلّ شيء، وغيره يرى ما يخصّ كتبه هو. ورسالةٌ لا كتاب لها لا مالك لها ⟵ إداريّ
فقط.

**لماذا ملفٌّ مستقلّ:** هذه ترجمةُ قاعدةِ الكتب إلى لغة البريد (خيوط، رسائل
واردة، سجلّات صادرة) — لا نسخةٌ منها. القاعدة نفسها تُستورَد من
``core/scoping.py`` مصدراً وحيداً، فحين يصل بُعد القسم (المرحلة أ) تتغيّر هناك
وحدها وتتبعها هذه الدوالّ.
"""


from core.scoping import is_privileged, scope_books_for


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
    from django.db.models import Q
    return qs.filter(Q(book__created_by=user) | Q(book__isnull=True, sent_by=user))


def scope_incoming(qs, user):
    """الرسائل الواردة التي يحقّ للمستخدم رؤيتها.

    الوارد يصل إمّا ردّاً على رسالةٍ صادرة (فله كتاب عبر الخيط) وإمّا من جهةٍ
    مسجَّلة بلا خيطٍ لكتاب — والثانية بلا مالكٍ طبيعيّ فتبقى للإداريّ.
    """
    if sees_all_mail(user):
        return qs
    return qs.filter(thread__book__created_by=user)


def scope_books(qs, user):
    """الكتب التي يحقّ للمستخدم مراسلتها/رؤية بريدها — تفويضٌ للمصدر الوحيد."""
    return scope_books_for(user, qs)


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
    book = scope_books(Book.objects.all(), user).filter(pk=int(book_id)).first()
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
    return qs.filter(book__created_by=user)


def can_view_thread(thread, user) -> bool:
    """أيحقّ للمستخدم فتح هذا الخيط؟"""
    if sees_all_mail(user):
        return True
    return bool(thread.book_id and thread.book.created_by_id == user.id)


def can_view_book_mail(book, user) -> bool:
    """أيحقّ للمستخدم رؤية بريد هذا الكتاب؟"""
    if sees_all_mail(user):
        return True
    return book.created_by_id == user.id
