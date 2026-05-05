"""
Django signals لإبطال الكاش عند تعديل البيانات الأساسية.

نستخدم نمط Cache Versioning (cache_version_*):
- بدل حذف مفاتيح متعددة (تتطلّب Redis pattern delete)، نزيد رقم إصدار واحد
  ومفاتيح الكاش القديمة تُهمَل تلقائياً (لن يتطابق مفتاحها مع الإصدار الجديد).
"""

from django.core.cache import cache
from django.db.models.signals import post_save, post_delete, m2m_changed
from django.dispatch import receiver

from .models import Entity, Book

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
