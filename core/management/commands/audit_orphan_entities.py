# -*- coding: utf-8 -*-
"""تدقيق الجهات اليتيمة — بلا صادرٍ ولا وارد (توجيه المالك: مشبوهة بالتعريف).

القياس (2026-07-14): 49 جهة نشطة بصفر كتب وصفر ذاكرة ترويسة — لكنها ليست صنفاً
واحداً، والحذف الجارف خطأ:

  • **سجلّية**: لها رمزٌ مسجَّل («مجلس الادارة» ش1، «لجنة عكاس» ل ع) — قيدٌ رسمي
    في دليل الشركة لم تصلنا مراسلاتُه بعد. **تُترك** (وقد تراسلنا غداً).
  • **شظايا**: اسمٌ مقتطَع من اسمٍ أطول موجود («انجانة» من «لجنة… انجانة»،
    «المواد» من «هيئة الخدمات والمواد»، «واسط»، «لجان»، «تقارير») — ضجيجُ
    استيرادٍ يسرق مطابقات TF-IDF من الأسماء الصحيحة. **تُعطَّل** (قابل للعكس).
  • **مراجعة**: اسمٌ مكتملٌ بلا رمز ولا كتب («قسم الميكانيك») — قرارُ بشرٍ.

التعطيل لا الحذف: `is_active=False` يُخرجها من الاقتراحات ويُبقيها قابلة للاسترجاع
من تبويب «المعطّلة» في صفحة الجهات.

    python manage.py audit_orphan_entities            # تقرير فقط
    python manage.py audit_orphan_entities --apply     # يعطّل الشظايا وحدها
"""
import re

from django.core.management.base import BaseCommand
from django.db.models import Q

from core.entity_dedup import annotate_book_counts, book_count, norm_key
from core.models import Entity, LetterheadMemory

_STOP = {'قسم', 'شعبة', 'هيئة', 'هيأة', 'هياة', 'وحدة', 'لجنة', 'مكتب', 'دائرة',
         'وزارة', 'شركة', 'السيد', 'مدير'}


def classify(entity, others):
    """('سجلّية'|'شظية'|'مراجعة', سبب) — الشظيةُ اسمٌ يقع **داخل** اسم جهةٍ عاملة،
    فتُظهَر معها الجهةُ الحاوية ليراجع البشرُ الحكمَ لا أن يثق به أعمى."""
    if (entity.code or '').strip():
        return 'سجلّية', 'رمزٌ مسجَّل — قيدٌ رسمي بانتظار أول مراسلة'
    key = norm_key(entity.name)
    words = [w for w in re.split(r'\s+', key) if w and w not in _STOP]
    if not words:
        return 'شظية', 'اسمٌ عامّ بلا كلمةٍ مميِّزة'
    for other_key, other_name in others:
        if key != other_key and key in other_key:
            return 'شظية', f'يقع داخل: «{other_name}»'
    return 'مراجعة', 'اسمٌ مكتمل بلا رمزٍ ولا مراسلات'


class Command(BaseCommand):
    help = 'يدقّق الجهات بلا كتب: يترك السجلّية، يعطّل الشظايا، يعرض ما يحتاج قراراً.'

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true',
                            help='يعطّل الشظايا فعلياً (الافتراضي: تقرير فقط).')

    def handle(self, *args, **opts):
        ents = list(annotate_book_counts(Entity.objects.filter(is_active=True)))
        others = [(norm_key(e.name), e.name) for e in ents if book_count(e) > 0]
        buckets = {'سجلّية': [], 'شظية': [], 'مراجعة': []}
        for e in ents:
            if book_count(e) > 0:
                continue
            if LetterheadMemory.objects.filter(
                    Q(issuing_entity=e) | Q(receiving_entity=e)).exists():
                continue           # لها ذاكرة ترويسة ⇒ ليست يتيمة حقاً
            bucket, why = classify(e, others)
            buckets[bucket].append((e, why))

        total = sum(len(v) for v in buckets.values())
        self.stdout.write(f'جهات يتيمة (صفر كتب، صفر ذاكرة): {total} من {len(ents)} نشطة\n')
        for name, items in buckets.items():
            self.stdout.write(f'\n■ {name}: {len(items)}')
            for e, why in items:
                self.stdout.write(f'    {e.name[:42]:<44} [{e.code or "—"}]  {why}')

        if not opts['apply']:
            self.stdout.write(self.style.WARNING(
                '\n(تقرير فقط). للتعطيل: python manage.py audit_orphan_entities --apply'
                '\nالشظايا وحدها تُعطَّل — السجلّية تبقى، والمراجعة قرارُك من الواجهة.'))
            return

        ids = [e.id for e, _why in buckets['شظية']]
        n = Entity.objects.filter(id__in=ids).update(is_active=False)
        self.stdout.write(self.style.SUCCESS(
            f'\n✓ عُطّلت {n} شظية (قابلة للاسترجاع من تبويب «المعطّلة»). '
            f'بقيت {len(buckets["سجلّية"])} سجلّية و{len(buckets["مراجعة"])} للمراجعة.'))
