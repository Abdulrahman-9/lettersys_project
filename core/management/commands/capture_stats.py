# -*- coding: utf-8 -*-
"""عدّاد دولاب التعلّم: كم **قصاصةً مؤكَّدة** جمعنا فعلاً لإعادة تدريب قارئ العدد.

التعريف مُسجَّلٌ في `docs/EVAL_REGISTRY.md` قبل العدّ (وإلّا صار الرقم مطّاطاً): صفٌّ
يستوفي الثلاثة معاً — كتابٌ وارد، وصندوقٌ غير فارغ، وقيمةٌ نهائيّةٌ غير فارغة.

⚠️ لا تخلط هذا بـ«تغطية الالتقاط» (نسبة الصفحات التي يجد فيها الكاشف صندوقاً ≈84%):
تلك **قدرةٌ** لا **بيانات**. بوّابة إعادة التدريب (T2.4) هي هذا العدّاد عند 300.

    python manage.py capture_stats
"""
from collections import Counter

from django.core.management.base import BaseCommand

from core.extraction.capture_schema import EVAL_HOLD_KEY
from core.models import DataExtractionResult

TARGET = 300
_INCOMING = ('incoming_internal', 'incoming_external')


class Command(BaseCommand):
    help = 'يعدّ القصاصات المؤكَّدة الصالحة لإعادة تدريب قارئ العدد (بوّابة T2.4)'

    def handle(self, *args, **opts):
        rows = DataExtractionResult.objects.values_list('additional_data', flat=True)
        total = confirmed = held = 0
        src = Counter()
        box_no_value = value_no_box = 0
        for ad in rows:
            if not isinstance(ad, dict):
                continue
            total += 1
            if (ad.get('book_kind') or '') not in _INCOMING:
                continue
            has_box = bool(ad.get('sender_number_bbox'))
            has_val = bool((ad.get('sender_number_final') or '').strip())
            if has_box and has_val:
                confirmed += 1
                # المحجوزُ للتقييم يُعدّ ولا يُدرَّب عليه — عرضُه هنا يمنع مفاجأةَ
                # «العتبة بلغت 300» بينما عُشرُها خارج متناول التدريب أصلاً.
                held += 1 if ad.get(EVAL_HOLD_KEY) else 0
                src[ad.get('sender_number_bbox_source') or '?'] += 1
            elif has_box:
                box_no_value += 1
            elif has_val:
                value_no_box += 1

        w = self.stdout.write
        w('سجلّات الاستخراج الكليّة        : %d' % total)
        w('**قصاصاتٌ مؤكَّدة (تعريف السجلّ) : %d / %d**' % (confirmed, TARGET))
        w('  بحسب المصدر                   : %s' % (dict(src) or '—'))
        w('  محجوزٌ للتقييم (لا يُدرَّب عليه) : %d' % held)
        w('  صندوقٌ بلا قيمةٍ نهائيّة        : %d' % box_no_value)
        w('  قيمةٌ بلا صندوق                : %d' % value_no_box)
        if confirmed >= TARGET:
            w(self.style.SUCCESS('بوّابة T2.4 مفتوحة — تُجدوَل إعادة تدريب CRNN.'))
        else:
            w('البوّابة مغلقة — تبقى %d قصاصة. تتراكم بالاستعمال الحقيقيّ لا بالتشغيل.'
              % (TARGET - confirmed))
