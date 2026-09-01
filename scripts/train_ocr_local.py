#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
===================================================
تصدير مجموعة تدريب OCR من التصحيحات اليدوية
===================================================

يجمع تصحيحات `OCRFeedback` التي لم تُستهلك بعد، ويكتبها ملفَّ JSONL جاهزاً
لمسار التدريب الفعلي (Kaggle/Lightning)، ويسجّل `TrainingDataset` بأعدادٍ
حقيقية بحالة «جاهز». **ثمّ يقف.**

لماذا يقف
---------
الضبط الدقيق لنموذج OCR (تحميل الأوزان، PyTorch، GPU) غير مُنفَّذ هنا، ولن
يُنفَّذ على جهازٍ بـ8 ج.ب. النسخة السابقة من هذا الملف كانت **تتظاهر** به:
تنام ثانيتين تسع مرّات، ثم تحسب «التحسّن = 3.0 + العينات/100» — رقمٌ مُختلَق
بلا أي قياس — ثم تُنشئ `OCRModelVersion` بدقّةٍ 0.0 وتفعّله، وتعلّم **كل**
التصحيحات بأنها استُهلكت. فتفقد بياناتك وتكسب رقماً كاذباً.

القاعدة هنا: لا نكتب رقماً لم نقسه. الملفّ الناتج هو المُخرَج الحقيقي، وما
بعده يجري خارجاً حيث يوجد عتادٌ فعليّ.

الاستعمال
---------
    python scripts/train_ocr_local.py                    # تصدير (لا يستهلك شيئاً)
    python scripts/train_ocr_local.py --include-used     # يشمل ما استُهلك سابقاً
    python scripts/train_ocr_local.py --out D:\ds.jsonl  # مسار مخصّص
    python scripts/train_ocr_local.py --mark-used 12     # بعد تدريبٍ فعليّ: علّم
                                                          # عيّنات المجموعة 12 مستهلَكة

`--mark-used` هو الخطوة الوحيدة التي تستهلك البيانات، ولا تُنفَّذ إلا بعد أن
يكتمل تدريبٌ حقيقيّ فعلاً — بيدك، لا تلقائياً.

ملاحظة ويندوز: صدّر PYTHONIOENCODING=utf-8 قبل التشغيل.
"""
import argparse
import json
import os
import sys
from datetime import datetime

os.environ.setdefault('OPENBLAS_NUM_THREADS', '1')
os.environ.setdefault('OMP_NUM_THREADS', '1')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'lettersys.settings')

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

import django                                            # noqa: E402
django.setup()

from django.conf import settings                          # noqa: E402
from django.utils import timezone                         # noqa: E402

from core.models import OCRFeedback, TrainingDataset      # noqa: E402

DEFAULT_DIR = os.path.join(PROJECT_ROOT, 'var', 'training')


def _resolve_image(path):
    """المسار المخزَّن قد يكون مطلقاً أو نسبيّاً لـMEDIA_ROOT — نجرّب الاثنين."""
    if not path:
        return None
    if os.path.isabs(path) and os.path.exists(path):
        return path
    cand = os.path.join(str(settings.MEDIA_ROOT), path)
    if os.path.exists(cand):
        return cand
    cand = os.path.join(PROJECT_ROOT, path)
    if os.path.exists(cand):
        return cand
    return None


def export(out_path, include_used=False, min_samples=1, include_unchanged=False):
    qs = OCRFeedback.objects.all().order_by('id')
    if not include_used:
        qs = qs.filter(used_for_training=False)

    rows, skipped_empty, skipped_unchanged, missing_image = [], 0, 0, 0
    langs = {'ar': 0, 'en': 0, 'mixed': 0}

    for fb in qs.iterator(chunk_size=500):
        text = (fb.corrected_text or '').strip()
        if not text:
            skipped_empty += 1          # تصحيحٌ فارغ ليس عيّنةَ تدريب
            continue
        # **الحارس الحاسم**: نصٌّ «مصحَّح» يطابق ناتج OCR حرفياً ليس تصحيحاً —
        # لا إشارة تعلّم فيه، والتدريب عليه يُعلّم النموذج إعادة إنتاج أخطائه
        # ويثبّتها. مقيسٌ على البيانات الحيّة: 14/14 مطابقةٌ بنسبة 1.0000، أي
        # أنّ الجدول كلّه مخرَجات OCR خام سُجّلت باسم «تصحيحات».
        if not include_unchanged and text == (fb.original_text or '').strip():
            skipped_unchanged += 1
            continue
        resolved = _resolve_image(fb.image_path)
        if resolved is None:
            missing_image += 1          # يُصدَّر مع علامة، فالقرار للمُدرِّب لا لنا
        langs[fb.language] = langs.get(fb.language, 0) + 1
        rows.append({
            'id': fb.id,
            'image': resolved or fb.image_path,
            'image_exists': resolved is not None,
            'text': text,
            'ocr_text': (fb.original_text or '').strip(),
            'language': fb.language,
            'ocr_confidence': fb.original_confidence,
            'correction_type': fb.correction_type,
            'corrected_at': fb.corrected_at.isoformat() if fb.corrected_at else None,
        })

    print('=' * 72)
    print('تصحيحات مقروءة        : %s' % f'{qs.count():,}')
    print('عيّنات صالحة          : %s' % f'{len(rows):,}')
    print('  عربي / إنجليزي / مختلط: %d / %d / %d'
          % (langs.get('ar', 0), langs.get('en', 0), langs.get('mixed', 0)))
    print('مستبعَد (نصّ فارغ)     : %d' % skipped_empty)
    print('مستبعَد (لم يُصحَّح شيء) : %d' % skipped_unchanged)
    print('صورتها مفقودة على القرص: %d' % missing_image)

    if len(rows) < min_samples:
        print('=' * 72)
        print('لا شيء يُصدَّر (المطلوب %d عيّنة على الأقل).' % min_samples)
        total = OCRFeedback.objects.count()
        if not total:
            print('جدول OCRFeedback فارغ — ولا مسارَ في التطبيق يُنشئ صفوفه اليوم،')
            print('فالتصحيحات تُلتقَط عبر ExtractionFeedback لا عبره.')
        elif skipped_unchanged and not rows:
            print('كل الصفوف مخرجات OCR خام لا تصحيحاتٍ بشرية (المصحَّح == الأصلي).')
            print('لا إشارة تعلّم فيها؛ التدريب عليها يُثبّت أخطاء النموذج لا يُصلحها.')
            print('لتجاوز الحارس عمداً: --include-unchanged')
        elif not include_used and not OCRFeedback.objects.filter(
                used_for_training=False).exists():
            print('كل الـ%d صفّاً معلَّمٌ مستهلَكاً سلفاً — لتضمينها: --include-used' % total)
        return None

    os.makedirs(os.path.dirname(out_path) or '.', exist_ok=True)
    tmp = out_path + '.part'
    with open(tmp, 'w', encoding='utf-8') as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + '\n')
    os.replace(tmp, out_path)           # كتابة ذرّية: لا ملفَّ نصفَ مكتوب

    size = os.path.getsize(out_path)
    ds = TrainingDataset.objects.create(
        name='feedback_%s' % datetime.now().strftime('%Y%m%d_%H%M%S'),
        dataset_type='feedback',
        status='ready',                 # «جاهز» لا «مستخدم»: لم يُدرَّب عليه بعد
        total_samples=len(rows),
        arabic_samples=langs.get('ar', 0),
        english_samples=langs.get('en', 0),
        metadata={
            'export_path': out_path,
            'bytes': size,
            'feedback_ids': [r['id'] for r in rows],
            'missing_images': missing_image,
            'skipped_empty': skipped_empty,
            'skipped_unchanged': skipped_unchanged,
            'include_used': include_used,
            'include_unchanged': include_unchanged,
            'exported_at': timezone.now().isoformat(),
            'note': 'تصدير فقط — لم يجرِ تدريب. الضبط الدقيق يجري خارجياً.',
        },
    )

    print('=' * 72)
    print('الملف   : %s  (%s ك.ب)' % (out_path, f'{size / 1024:,.0f}'))
    print('المجموعة: #%d  %s  [%s]' % (ds.id, ds.name, ds.get_status_display()))
    print('=' * 72)
    print('لم يجرِ تدريب — هذه خطوة التصدير وحدها.')
    print('التالي: ارفع الملف إلى مسار التدريب (Kaggle/Lightning)، وبعد أن')
    print('يكتمل فعلاً شغّل:  python scripts/train_ocr_local.py --mark-used %d' % ds.id)
    return ds


def mark_used(dataset_id):
    """يستهلك عيّنات مجموعةٍ بعينها — بعد تدريبٍ حقيقيّ اكتمل، لا قبله."""
    try:
        ds = TrainingDataset.objects.get(pk=dataset_id)
    except TrainingDataset.DoesNotExist:
        print('لا مجموعة بالرقم %d.' % dataset_id)
        return 1

    ids = (ds.metadata or {}).get('feedback_ids') or []
    if not ids:
        print('المجموعة #%d لا تحمل قائمة عيّناتها — لا نستهلك بالتخمين.' % dataset_id)
        return 1

    n = OCRFeedback.objects.filter(id__in=ids, used_for_training=False).update(
        used_for_training=True, training_date=timezone.now())
    ds.status = 'used'
    ds.trained_at = timezone.now()
    ds.save(update_fields=['status', 'trained_at', 'updated_at'])
    print('استُهلكت %d عيّنة من المجموعة #%d (%s).' % (n, ds.id, ds.name))
    print('الباقي غير المستهلَك: %d'
          % OCRFeedback.objects.filter(used_for_training=False).count())
    return 0


def main():
    ap = argparse.ArgumentParser(description='تصدير مجموعة تدريب OCR من التصحيحات اليدوية.')
    ap.add_argument('--out', default=None, help='مسار ملف JSONL (افتراضياً var/training/)')
    ap.add_argument('--include-used', action='store_true',
                    help='يشمل التصحيحات التي استُهلكت في تدريبٍ سابق')
    ap.add_argument('--include-unchanged', action='store_true',
                    help='يشمل صفوفاً لم يُصحَّح فيها شيء (بلا إشارة تعلّم — للفحص فقط)')
    ap.add_argument('--min-samples', type=int, default=1,
                    help='لا يُصدَّر شيء دون هذا العدد')
    ap.add_argument('--mark-used', type=int, metavar='DATASET_ID', default=None,
                    help='بعد تدريبٍ فعليّ: علّم عيّنات هذه المجموعة مستهلَكة')
    args = ap.parse_args()

    if args.mark_used is not None:
        return mark_used(args.mark_used)

    out = args.out or os.path.join(
        DEFAULT_DIR, 'training_dataset_%s.jsonl' % datetime.now().strftime('%Y%m%d_%H%M%S'))
    ds = export(out, args.include_used, args.min_samples, args.include_unchanged)
    # 0 = كُتبت مجموعة · 2 = عمل بنجاح ولا شيء يستحقّ التصدير · 1 = خطأ فعليّ.
    # «لا عيّنة صالحة» ليس فشلاً — الفشل أن نصدّر ما لا إشارة تعلّم فيه.
    return 0 if ds else 2


if __name__ == '__main__':
    sys.exit(main())
