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
