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

from core.extraction.artifacts import ARTIFACTS

MISSING_ARTIFACTS_ID = 'core.W001'


@register(Tags.compatibility)
def check_runtime_artifacts(app_configs, **kwargs):
    missing = [a for a in ARTIFACTS
               if a.level in ('required', 'degrades') and not os.path.exists(a.path_fn())]
    if not missing:
        return []
    lines = '\n'.join('  · %s — %s' % (a.label, a.breaks) for a in missing)
    return [CheckWarning(
        'عتادُ النماذج ناقص: %d ملفّاً مفقوداً مِن %d.\n%s'
        % (len(missing), len(ARTIFACTS), lines),
        hint='`var/` خارج git فلا يصل مع النسخة. انسخ الأوزان ثمّ تحقّق بـ'
             '`python manage.py models_healthcheck --strict --load`.',
        id=MISSING_ARTIFACTS_ID,
    )]
