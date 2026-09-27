"""``EncryptedCharField`` — التشفيرُ في **الحقل** لا في ``save()`` (Merge9 §8.6‑أ).

حادثةُ 09‑08: ``dumpdata`` كتب كلمتَي البريد **صريحتين** لأنّ ``from_db`` كان يفكّ
عند التحميل والمُسلسِلُ يقرأ الكائن. وثغرتان أختان: ``save(raw=True)`` (``loaddata``)
و``QuerySet.update()`` كانا يتخطّيان ``save()`` فيكتبان الصريح. نقلُ التشفير إلى
الحقل يسدّ الثلاثةَ من نقطةٍ واحدة:

- ``from_db_value``  ⟵ يفكّ عند القراءة (الذاكرةُ صريحةٌ دائماً — العقدُ القديم نفسُه).
- ``get_prep_value`` ⟵ يشفّر عند الكتابة، **ويُستدعى مع ``raw=True`` ومع ``update()``**.
- ``value_to_string`` ⟵ المُسلسِلات تُخرج ``enc::`` لا الصريح.

**لا تشفيرَ مضاعفاً**: ما يبدأ بـ``enc::`` يمرّ كما هو؛ فمفتاحٌ مبدَّلٌ (الفكُّ يفشل)
يُبقي القيمةَ ``enc::`` في الذاكرة وفي القاعدة بلا استثناءٍ وبلا سكٍّ صامت.
"""

from django.db import models


class EncryptedCharField(models.CharField):
    description = 'نصٌّ يُخزَّن مشفَّراً ببادئة enc:: ويُقرأ صريحاً'

    def from_db_value(self, value, expression, connection):
        from .encryption import decrypt_text, is_encrypted
        if is_encrypted(value):
            try:
                return decrypt_text(value)
            except Exception:
                # مفتاحٌ مفقودٌ أو مُبدَّل: تبقى القيمةُ enc:: ليظهر العطبُ عند
                # الاستعمال، لا أن يُبتلع هنا — وget_prep_value لن يشفّرها ثانيةً.
                return value
        return value

    def get_prep_value(self, value):
        from .encryption import encrypt_text, is_encrypted
        value = super().get_prep_value(value)
        if value and not is_encrypted(value):
            return encrypt_text(value)
        return value

    def value_to_string(self, obj):
        """المُسلسِلات (dumpdata) تحصل على ``enc::`` — لا على الصريح."""
        return self.get_prep_value(self.value_from_object(obj)) or ''
