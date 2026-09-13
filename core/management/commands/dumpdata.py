# -*- coding: utf-8 -*-
"""تظليلُ ``dumpdata`` — أربعةُ حرّاسٍ حول أمرٍ أنتج تسريباً فعليّاً (Merge9 §8.6-ج).

في 2026-09-08 أُنتج ملفُّ `dumpdata` لنقل البيانات فكتب **كلمتَي مرور البريد
صريحتين** بينما عمودُ القاعدة مشفَّرٌ سليمٌ ببادئة ``enc::`` — لأنّ
``EncryptedCharField.from_db_value`` كان الأصلُ يفكّ (قبل 8.6‑أ) — والمزيجُ القديم يفكّ عند التحميل، فيقرأ المُسلسِلُ الكائنَ
المفكوك. ولم يكن في الطريق ما يعترض: لا الأمرُ حذّر، ولا الملفُّ بدا مريباً،
ولا ``loaddata`` أعاد التشفير (``raw=True`` يتخطّى ``save()``).

**الحرّاسُ الأربعة** (كلُّها ترفع ``CommandError`` = خروجٌ ≠0):

1. **لا كتابةَ داخل المستودع** — مستودعُ المشروع **عامٌّ** على GitHub، و`git add`
   واحدٌ يجعل الملفَّ منشوراً للأبد. `.gitignore` حمايةٌ ثانيةٌ لا أولى.
2. **`--all` إلزاميّ** — بدونه يعمل المديرُ الافتراضيُّ فيُسقط المحذوفَ ناعماً
   (45 كتاباً في هذه القاعدة) **بصمت**، فتبدو النسخةُ كاملةً وهي ناقصة.
3. **النماذجُ ذاتُ الأسرار تُستثنى** تلقائيّاً، وطلبُها صراحةً يُرفض.
4. **فحصُ المخرَج بعد الكتابة** — آخرُ خطٍّ: إن ظهر سجلٌّ لنموذجٍ ذي أسرار
   (أو قيمةُ حقلٍ مشفَّرٍ بلا بادئة ``enc::``) **يُحذَف الملفُّ ويفشل الأمر**.

**ولماذا يُرفض المخرَجُ إلى stdout**: `dumpdata > file` يُنتج ملفّاً لا نراه —
فلا يُفحَص المسارُ ولا يُفحَص المحتوى ولا يُحذَف عند الانتهاك. الحارسان 1 و4
يسقطان معاً، فالرفضُ أصدقُ من خضرةٍ كاذبة.

**والصحيحُ لنقل بياناتٍ بين قاعدتَي PostgreSQL** هو ``pg_dump -Fc``/``pg_restore``
(أو ``manage.py verify_backup`` للنسخة المشفَّرة) — لا هذا الأمر.
"""
from __future__ import annotations

import bz2
import gzip
import json
import locale
import lzma
from pathlib import Path

from django.conf import settings
from django.core.management.base import CommandError
from django.core.management.commands.dumpdata import Command as DumpDataCommand

from core.encrypted_columns import encrypted_columns, encrypted_models

#: امتدادُ ضغطٍ ⟵ (دالّةُ الفتح، وسائطُها) — مطابقٌ لِما يكتب به ``dumpdata``.
_COMPRESSED = {
    '.gz': (gzip.open, {}),
    '.bz2': (bz2.open, {}),
    '.xz': (lzma.open, {}),
    '.lzma': (lzma.open, {'format': lzma.FORMAT_ALONE}),
}

_ALTERNATIVE = ('لنقل البيانات بين قاعدتَي PostgreSQL استعمل '
                '`pg_dump -Fc` + `pg_restore`، أو `manage.py verify_backup` '
                'للنسخة المشفَّرة.')


def secret_model_labels():
    """أسماءُ النماذج التي تحمل حقولاً مشفَّرة — تُستثنى من كلّ مخرَج."""
    return tuple(model._meta.label for model in encrypted_models())


def _read_dump(path: Path) -> str:
    """نصُّ المخرَج — يفكّ الضغطَ بالطريقة نفسِها التي كتب بها ``dumpdata``.

    ``errors='replace'`` مقصود: **جانغو يكتب الملفَّ بترميز اللغة المحلّيّة**
    (``open(..., 'wt')`` بلا ``encoding``) — مقيسٌ على هذا الجهاز: عربيّةُ
    `auth.permission` خرجت بـcp1256 لا UTF-8. والبايتاتُ المشوَّهةُ لا تُعمي
    الفحصَ: أسماءُ النماذج والبادئةُ ``enc::`` وكلماتُ المرور محارفُ ASCII تبقى
    كما هي، والمشوَّهُ وحدَه يصير ``�``.
    """
    opener, kwargs = _COMPRESSED.get(path.suffix.lower(), (None, None))
    if opener is None:
        return path.read_text(encoding='utf-8', errors='replace')
    with opener(path, 'rt', encoding='utf-8', errors='replace', **kwargs) as handle:
        return handle.read()


def scan_dump_for_secrets(path, fmt='json'):
    """يُعيد أسطرَ انتهاكٍ في المخرَج — **بلا أيّ قيمة**؛ فارغةٌ = نظيف.

    الفحصُ **مستقلٌّ عن الاستثناء**: يكتشف أعمدتَه بنفسه من السجلّ، فلو أخفق
    الاستثناءُ يوماً (نموذجٌ جديدٌ بأسرار، أو خيارٌ التفّ عليه) بقي هذا الخطُّ
    قائماً. وسجلُّ نموذجٍ ذي أسرارٍ **انتهاكٌ ولو كانت قيمتُه مشفَّرة**: الاستثناءُ
    وقع خارج مكانه، والمشفَّرُ نفسُه لا يُشحَن في ملفٍّ عابر.
    """
    from core.encryption import ENCRYPTED_PREFIX

    fields_by_label = {}
    for column in encrypted_columns():
        fields_by_label.setdefault(column.label, []).append(column.field)

    text = _read_dump(Path(path))
    lowered = text.lower()
    present = [label for label in fields_by_label if label in lowered]
    if not present:
        return []

    if fmt != 'json':
        return [f"{label}: اسمُ نموذجٍ ذي أسرارٍ يظهر في مخرَجٍ بصيغة {fmt} "
                f"(لا يُحلَّل هنا — والشكُّ كافٍ)" for label in sorted(present)]

    try:
        records = json.loads(text)
    except json.JSONDecodeError as exc:
        return [f"تعذّر تحليلُ المخرَج للفحص ({exc.__class__.__name__}) "
                f"بينما فيه اسمُ نموذجٍ ذي أسرار — ولا يُسلَّم ما لا يُفحَص."]

    violations = []
    for record in records:
        if not isinstance(record, dict):
            continue
        label = str(record.get('model', '')).lower()
        if label not in fields_by_label:
            continue
        fields = record.get('fields') or {}
        plain = sorted(
            name for name in fields_by_label[label]
            if fields.get(name) and not str(fields[name]).startswith(ENCRYPTED_PREFIX)
        )
        if plain:
            violations.append(
                f"{label}: قيمةُ حقلٍ مشفَّرٍ بنصٍّ صريح بلا بادئة "
                f"'{ENCRYPTED_PREFIX}' — الحقول: {', '.join(plain)}")
        else:
            violations.append(
                f"{label}: سجلُّ نموذجٍ ذي أسرارٍ في المخرَج (الاستثناءُ لم يقع)")
    return violations


class Command(DumpDataCommand):
    help = (DumpDataCommand.help
            + ' [مُظلَّلٌ في LetterSys: يرفض الكتابةَ داخل المستودع، ويفرض --all،'
              ' ويستثني النماذجَ ذاتَ الأسرار، ويفحص مخرَجَه فيحذفه عند الانتهاك.]')

    def handle(self, *app_labels, **options):
        output = options.get('output')
        if not output:
            raise CommandError(
                'المخرَجُ إلى stdout مرفوض: `dumpdata > file` يكتب ملفّاً لا يراه '
                'الأمر، فلا يُفحَص مسارُه ولا محتواه ولا يُحذَف عند الانتهاك. '
                'استعمل `-o <مسار خارج المستودع>`. ' + _ALTERNATIVE)

        target = Path(output).expanduser().resolve()
        base = Path(settings.BASE_DIR).resolve()
        if target == base or base in target.parents:
            raise CommandError(
                f'الكتابةُ داخل المستودع مرفوضة: {target}\n'
                f'مستودعُ المشروع **عامٌّ** على GitHub، و`git add` واحدٌ ينشر '
                f'الملفَّ للأبد؛ و`.gitignore` حمايةٌ ثانيةٌ لا أولى. '
                f'اكتب خارج {base}.')

        if target.suffix.lower() == '.zip':
            raise CommandError(
                'الامتدادُ .zip مرفوض: جانغو يُسقطه ويكتب باسمٍ آخر، فيفحص '
                'الحارسُ ملفّاً غيرَ الذي كُتب. استعمل .json أو .json.gz.')

        if not options.get('use_base_manager'):
            raise CommandError(
                '`--all` إلزاميّ: بدونه يعمل المديرُ الافتراضيُّ فيُسقط المحذوفَ '
                'ناعماً (`is_deleted`) **بصمت** — فتبدو النسخةُ كاملةً وهي ناقصة.')

        secrets = secret_model_labels()
        wanted = {label.lower() for label in secrets}
        asked = sorted(label for label in app_labels if label.lower() in wanted)
        if asked:
            raise CommandError(
                'نموذجٌ ذو أسرارٍ طُلب صراحةً: ' + '، '.join(asked) + '\n'
                'حقولُه المشفَّرة تُفكّ عند القراءة (`from_db`) فتُكتَب في الملفّ '
                '**صريحة**، و`loaddata` لا يُعيد تشفيرَها. ' + _ALTERNATIVE)

        options['exclude'] = list(options.get('exclude') or []) + list(secrets)
        try:
            super().handle(*app_labels, **options)
        except BaseException:
            # العقدُ: **لا يبقى على القرص ملفٌّ لم يُفحَص**. جانغو يترك المكتوبَ
            # جزئيّاً حين يفشل التسلسل (لا حذفَ في `finally`) — فيبقى ملفٌّ
            # يبدو نسخةً وهو نصفُ نسخةٍ لم يمرّ عليها الفحص. والخطأُ يُرمى كما
            # هو: تنظيفٌ لا ابتلاع.
            target.unlink(missing_ok=True)
            raise

        violations = scan_dump_for_secrets(target, options.get('format', 'json'))
        if violations:
            target.unlink(missing_ok=True)
            raise CommandError(
                'المخرَجُ حُذف: فحصُ ما بعد الكتابة وجد أسراراً فيه.\n'
                + '\n'.join('  · %s' % line for line in violations)
                + '\n(القيمُ لا تُطبع.) ' + _ALTERNATIVE)

        self.stdout.ending = '\n'
        encoding = locale.getpreferredencoding(False)
        if encoding.lower().replace('-', '') != 'utf8':
            self.stdout.write(self.style.WARNING(
                'تنبيهٌ مقيس: جانغو كتب الملفَّ بترميز اللغة المحلّيّة (%s) لا '
                'UTF-8 — العربيّةُ فيه تُقرأ مشوَّهةً على أيّ نظامٍ آخر.' % encoding))
        self.stdout.write(self.style.SUCCESS(
            'مخرَجٌ مفحوص: %s — مستثنىً منه %s.'
            % (target, '، '.join(secrets) if secrets else 'لا شيء')))
