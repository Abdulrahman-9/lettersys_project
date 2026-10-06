"""
Django signals لإبطال الكاش عند تعديل البيانات الأساسية.

نستخدم نمط Cache Versioning (cache_version_*):
- بدل حذف مفاتيح متعددة (تتطلّب Redis pattern delete)، نزيد رقم إصدار واحد
  ومفاتيح الكاش القديمة تُهمَل تلقائياً (لن يتطابق مفتاحها مع الإصدار الجديد).
"""

from django.core.cache import cache
from django.db.models.signals import post_save, post_delete, m2m_changed
from django.dispatch import receiver

from .models import Entity, Book, LetterheadMemory

ENTITY_CACHE_VERSION_KEY = 'cache_version_entity'
BOOK_CACHE_VERSION_KEY = 'cache_version_book'


def _bump(version_key):
    """زيادة رقم الإصدار ذرياً (cache.incr fallback إن لم يكن موجوداً)."""
    try:
        cache.incr(version_key)
    except ValueError:
        # المفتاح غير موجود — أنشئه
        cache.set(version_key, 2, None)


@receiver([post_save, post_delete], sender=Entity)
def invalidate_entity_cache(sender, **kwargs):
    """أبطل كاش بحث الجهات عند أي تعديل/حذف."""
    _bump(ENTITY_CACHE_VERSION_KEY)


@receiver([post_save, post_delete], sender=Book)
def invalidate_book_cache(sender, **kwargs):
    """أبطل كاش بحث العناوين وكاش كلمات القاموس عند أي تعديل/حذف للكتاب."""
    _bump(BOOK_CACHE_VERSION_KEY)
    # مسح كاش كلمات القاموس المُستخرجة من العناوين
    cache.delete('title_words_dict_v1')


@receiver(m2m_changed, sender=Book.issuing_entities.through)
@receiver(m2m_changed, sender=Book.receiving_entities.through)
def invalidate_book_m2m_cache(sender, action, **kwargs):
    """أبطل كاش العناوين عند تعديل M2M للجهات (يؤثّر على فلترة بحث العناوين بـ entity_id)."""
    if action in ('post_add', 'post_remove', 'post_clear'):
        _bump(BOOK_CACHE_VERSION_KEY)


# ── فهارسُ الاستخراج المشتركة (ذاكرةُ الترويسة وبصماتُ الترقيم) ──────────────────
#
# الفهرسان يقرآن صفوفَ الذاكرة والكتب والجهات وروابطها؛ أيُّ حفظٍ أو حذفٍ عبر التطبيق
# يُبطلهما عند الإيداع ويُجدوِل بناءهما في الخلفيّة — فيجدهما الاستخراجُ التالي جاهزَين.
# ما يجري خارج الإشارات (أوامرُ الإدارة، `queryset.update`) تلتقطه بصمةُ القاعدة والعمرُ.
# العقدُ كاملاً في `core/extraction/shared_index.py`.

# ما يقرؤه البناءان من الكتاب والجهة: حفظٌ مُحدَّدُ الحقول لا يمسّها (هامشٌ، أرشفةٌ، عهدة)
# لا يُغيّر المصدر فلا يُبطل شيئاً — كان سيُعيد بناءَ ~1.8 ث في الخلفيّة بلا داع. والحفظُ
# العاديّ (بلا `update_fields`) والحذفُ يُبطلان دائماً: لا نعرف ما تغيّر.
_INDEX_READ_FIELDS = {
    Book: frozenset({'date', 'sender_number', 'is_deleted'}),
    Entity: frozenset({'name', 'code'}),
}


@receiver([post_save, post_delete], sender=LetterheadMemory)
@receiver([post_save, post_delete], sender=Entity)
@receiver([post_save, post_delete], sender=Book)
def invalidate_extraction_indexes_on_save(sender, update_fields=None, **kwargs):
    read = _INDEX_READ_FIELDS.get(sender)
    if read is not None and update_fields is not None and not (read & set(update_fields)):
        return
    from core.extraction.shared_index import invalidate_extraction_indexes
    invalidate_extraction_indexes()


@receiver(m2m_changed, sender=Book.issuing_entities.through)
@receiver(m2m_changed, sender=Book.receiving_entities.through)
def invalidate_extraction_indexes_on_links(sender, action, **kwargs):
    if action in ('post_add', 'post_remove', 'post_clear'):
        from core.extraction.shared_index import invalidate_extraction_indexes
        invalidate_extraction_indexes()


# ── سجلُّ الحسابات: دخولٌ وخروجٌ وفشلُ دخول ──────────────────────────────────
#
# إشاراتُ جانغو نفسُها هي نقطةُ الالتقاط الصحيحة: تُطلَق من كلّ مسارِ مصادقة
# (الواجهة، الإدارة، أيُّ نقطةٍ مستقبليّة) فلا يفوتنا مسارٌ نسيناه.

from django.contrib.auth.signals import (user_logged_in, user_logged_out,
                                         user_login_failed)


@receiver(user_logged_in)
def _log_login(sender, request, user, **kwargs):
    from core.audit_service import record_login

    record_login(user, request, action='LOGIN')


@receiver(user_logged_out)
def _log_logout(sender, request, user, **kwargs):
    from core.audit_service import record_login

    record_login(user, request, action='LOGOUT')


@receiver(user_login_failed)
def _log_login_failed(sender, credentials, request=None, **kwargs):
    """محاولةٌ فاشلة — بالاسم المُحاوَل والعنوان.

    **ولا يُسجَّل شيءٌ من حقل كلمة المرور إطلاقاً** — ولا طولُه ولا وجودُه:
    ``credentials`` يحمل كلمةَ السرّ نصّاً، وقراءةُ أيّ شيءٍ منها سوى اسم
    المستخدم فتحُ بابٍ لا يُغلق.
    """
    from core.audit_service import record_login

    record_login(None, request, action='LOGIN_FAILED',
                 username=(credentials or {}).get('username', '') or '')
