# -*- coding: utf-8 -*-
"""فحصُ نظامٍ خفيف: هل عتادُ النماذج موجود؟ — يُطلَق مع كلّ `manage.py`.

**لماذا مع الأمر لا مع الطلب**: `models_healthcheck` يُشغَّل عند النشر مرّةً،
والتدهورُ يحدث كلَّ طلب. وهذا الفحصُ يجعل الغيابَ **مرئيّاً بلا أن يُسأل عنه**:
أيُّ `manage.py migrate` أو `runserver` أو `test` على جهازٍ بلا أوزانٍ يطبع سطراً
واضحاً بدل أن يبدو كلُّ شيءٍ سليماً.

**ولماذا `Warning` لا `Error`**: مُشغّلُ الاختبارات يستدعي `run_checks()`
(`django/test/runner.py`)، فـ`Error` يُسقط المجموعة كلَّها على أيّ نسخةٍ جديدة —
عقوبةٌ على المطوّر لا حراسةٌ للإنتاج. البوّابةُ الصارمةُ مكانُها أمرُ النشر
(`models_healthcheck --strict`)، وهذا تنبيهٌ لا حاجز.

**والفحصُ يقف عند `os.path.exists`** عمداً: لا يفتح ONNX ولا يقرأ JSON — يعمل
مع كلّ أمرٍ فلا يجوز أن يكلّف ذاكرةً (350MB للكاشف على جهاز 8GB) ولا زمناً.
"""
import os

from django.core.checks import Tags, Warning as CheckWarning, register

from core.extraction.artifacts import ARTIFACTS, is_lfs_pointer

MISSING_ARTIFACTS_ID = 'core.W001'


@register(Tags.compatibility)
def check_runtime_artifacts(app_configs, **kwargs):
    # الحالةُ الأرجحُ على نسخةٍ جديدة منذ LFS (2026-09-01) ليست الغيابَ بل **مؤشّرٌ
    # غيرُ مسحوب** باسم الملفّ نفسِه — `os.path.exists` وحدَه أعمى عنه.
    missing, pointers = [], []
    for a in ARTIFACTS:
        if a.level not in ('required', 'degrades'):
            continue
        p = a.path_fn()
        if not os.path.exists(p):
            missing.append(a)
        elif is_lfs_pointer(p):
            pointers.append(a)
    if not missing and not pointers:
        return []
    lines = '\n'.join(
        ['  · %s — مفقود: %s' % (a.label, a.breaks) for a in missing]
        + ['  · %s — مؤشّرُ Git LFS لا الملفّ' % a.label for a in pointers])
    return [CheckWarning(
        ('عتادُ النماذج ناقص: %d مفقوداً و%d مؤشّرَ LFS مِن %d.'
         % (len(missing), len(pointers), len(ARTIFACTS))) + '\n' + lines,
        hint='الأوزانُ في Git LFS: `git lfs install && git lfs pull`، والمفتاحُ '
             '`.encryption_key` يُنسَخ يدويّاً. ثمّ `python manage.py '
             'models_healthcheck --strict --load`.',
        id=MISSING_ARTIFACTS_ID,
    )]
