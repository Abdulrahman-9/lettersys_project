# -*- coding: utf-8 -*-
"""عقدُ العتاد — كلُّ ملفٍّ يُحمَّل من القرص وقت التشغيل، مُعرَّفاً **مرّةً واحدة**.

**لماذا وُجد هذا الملفّ** (2026-09-01): `var/` كلُّه خارج git (`.gitignore:107`)،
فالنسخةُ الجديدة تصل **عمياء**. وكان الغيابُ يُكتشَف بثلاث طرقٍ كلُّها سيّئة:
  ١. صمتٌ تامّ — القارئان يعودان مبكراً بلا سطرِ سجلٍّ أصلاً.
  ٢. سجلٌّ لا يُكتب — `core.*` بلا مُعالِج (أُصلح بإضافة مُسجّل `core`).
  ٣. **استثناءٌ مبتلَع** — طقمُ محارف مفقودٌ يسقط إلى `'0123456789'` الافتراضيّ
     (`reader.py:44-54`). وطقمُ التاريخ `'0123456789/'`، والعشرةُ الأولى تتطابق
     فهرسةً (فلا انزياحَ خرائط — نُقض ادّعاءٌ أوّليٌّ هنا بالفحص)، لكنّ الفهرس
     11 يصير `charset[10]` ⟵ `IndexError` خارجَ `try` القارئ فيسقط الاقتراحُ
     كلُّه: وأكثرُ التواريخ فيها «/». أي **موتُ الميزة بلا رسالة**، لا خردةٌ واثقة.

**وفخُّ مجلّد العمل**: ستّةُ مساراتٍ كانت `os.path.join('var', …)` نسبيّةً
لمجلّد العمل لا لجذر المشروع، بينما الكاشفُ وحده يمرّ بـ`BASE_DIR`. فخدمةٌ
تُقلَع من مجلّدٍ آخر (والمشروع يشحن مُشغّلاً يفعل ذلك:
`scripts/run_server_background.py:22`) تجد `var/` فارغاً. مقيسٌ لا مُفترَض:
تشغيل `core.tests.AIProcessingServiceTests` من مجلّدٍ آخر كان يُسقط الاستخراج.

فالمسارات كلُّها تمرّ من هنا الآن: **تجاوزُ الإعدادات ⟵ جذرُ المشروع ⟵ مجلّد
العمل** (الأخيرُ للسكربتات خارج Django وحدها). والقائمةُ نفسُها يقرؤها
`manage.py models_healthcheck` — فلا ينجرف الفحصُ عمّا يُحمَّل فعلاً.
"""
import os
from collections import namedtuple


def base_dir() -> str:
    """جذرُ المشروع من الإعدادات، ومجلّدُ العمل حين لا Django (سكربتات التدريب)."""
    try:
        from django.conf import settings
        return str(settings.BASE_DIR)
    except Exception:          # noqa: BLE001 — الاستيرادُ خارج Django مقصود
        return ''


def artifact_path(*parts, setting: str = '') -> str:
    """`settings.<setting>` إن ضُبط ⟵ `BASE_DIR/parts` ⟵ `parts` نسبيّاً.

    الترتيبُ مقصود: النشرُ يُغيّر بمتغيّر بيئة، والتشغيلُ العاديّ لا يعتمد على
    مجلّد العمل، والسكربتُ خارج Django يبقى عاملاً كما كان.
    """
    if setting:
        try:
            from django.conf import settings
            override = getattr(settings, setting, '') or ''
        except Exception:      # noqa: BLE001
            override = ''
        if override:
            return str(override)
    root = base_dir()
    return os.path.join(root, *parts) if root else os.path.join(*parts)


# ── مُحلّلاتُ المسار — يستدعيها الكودُ الحيّ والفحصُ معاً ─────────────────────
def number_model_path() -> str:
    return artifact_path('var', 'models', 'handwritten_digits_crnn.onnx',
                         setting='HANDWRITTEN_NUMBER_ONNX')


def number_charset_path() -> str:
    return artifact_path('var', 'models', 'handwritten_digits_charset.json',
                         setting='HANDWRITTEN_NUMBER_CHARSET')


def date_model_path() -> str:
    return artifact_path('var', 'models', 'handwritten_dates_crnn.onnx',
                         setting='HANDWRITTEN_DATE_ONNX')


def date_charset_path() -> str:
    return artifact_path('var', 'models', 'handwritten_dates_charset.json',
                         setting='HANDWRITTEN_DATE_CHARSET')


def detector_path() -> str:
    return artifact_path('var', 'models', 'number_detector.onnx',
                         setting='NUMBER_DETECTOR_ONNX')


def detector_fallback_path() -> str:
    return artifact_path('var', 'models', 'number_detector_det1_backup.onnx',
                         setting='NUMBER_DETECTOR_FALLBACK_ONNX')


def layout_priors_path() -> str:
    return artifact_path('var', 'handwriting_layout_priors.json')


def entity_profiles_path() -> str:
    return artifact_path('var', 'entity_extraction_profiles.json')


def entity_doc_profiles_path() -> str:
    return artifact_path('var', 'entity_doc_profiles.json')


def encryption_key_path() -> str:
    return artifact_path('.encryption_key')


# ── القائمة ──────────────────────────────────────────────────────────────────
# kind: onnx | charset | json | key   —   يحدّد نوعَ الفحص لا مكانَ الملفّ.
# level: required   ⟵ غيابُه عطبٌ صارخ (يُفشل الفحص دائماً)
#        degrades   ⟵ ميزةٌ تسقط (تحذيرٌ، ويصير عطباً مع `--strict`)
#        optional   ⟵ احتياطيٌّ أو تحسين (تحذيرٌ فقط)
Artifact = namedtuple('Artifact', 'key label kind level path_fn needs breaks')

ARTIFACTS = (
    Artifact('detector', 'كاشفُ الصناديق det2', 'onnx', 'degrades', detector_path,
             None, 'لا صندوقَ عددٍ ولا تاريخ ⟵ المسارُ البصريُّ كلُّه صامت'),
    Artifact('detector_fallback', 'الكاشفُ الاحتياطيّ det1', 'onnx', 'optional',
             detector_fallback_path, None,
             'يسقط سقوطُ S1 على الصفحات التي يصمت فيها det2 (إصابة 72⟵70)'),
    Artifact('number_model', 'قارئُ العدد T2.4', 'onnx', 'degrades', number_model_path,
             None, 'لا قراءةَ عددٍ يدويّ — الحقلُ يبقى فارغاً للكاتب'),
    Artifact('number_charset', 'طقمُ محارف العدد', 'charset', 'optional',
             number_charset_path, 'number_model',
             'يسقط إلى الافتراضيّ (نفسِه فعليّاً) — ضررُه على العدد لا يُذكَر'),
    Artifact('date_model', 'قارئُ التاريخ D2', 'onnx', 'degrades', date_model_path,
             None, 'لا اقتراحَ تاريخ — القصاصةُ وحدها تبقى للكاتب'),
    Artifact('date_charset', 'طقمُ محارف التاريخ', 'charset', 'required',
             date_charset_path, 'date_model',
             'بلا «/» يرفع فكُّ الترميز IndexError ⟵ اقتراحُ التاريخ يموت صامتاً'),
    Artifact('layout_priors', 'بصماتُ تخطيط الجهات', 'json', 'optional',
             layout_priors_path, None, 'يضعف تموضعُ الشريط القديم (مسارٌ احتياطيّ)'),
    Artifact('entity_profiles', 'نحوُ أعداد الجهات', 'json', 'degrades',
             entity_profiles_path, None,
             'يسقط ترجيحُ نوع الوثيقة بحسب الجهة (`doc_type_prior`، pipeline.py:1448)'),
    Artifact('entity_doc_profiles', 'خريطةُ رموز الجهات', 'json', 'degrades',
             entity_doc_profiles_path, None, 'يضعف ترجيحُ مطابقة الجهة برمز السجلّ'),
    Artifact('encryption_key', 'مفتاحُ التعمية', 'key', 'required', encryption_key_path,
             None, 'يُسَكُّ مفتاحٌ جديدٌ بلا صوت ⟵ كلماتُ مرور البريد المخزّنة لا تُفكّ (يُرفع خطأ عند أوّل استعمال)'),
)

ARTIFACTS_BY_KEY = {a.key: a for a in ARTIFACTS}
