# -*- coding: utf-8 -*-
"""منسّق الحلقة الذاتيّة (فكرة المالك 2026-07-20): يُشغّل مكتشف البروفايل على
الكتب المؤكَّدة، يُقسّي القواعد الحيّة فوراً (النصف بلا GPU)، ويحسب إشارة «هل
التدريب على GPU يستحقّ الآن؟» مقارنةً باللقطة السابقة — فالجهات الجديدة تُغطَّى
آلياً والنموذج يُعاد تدريبه بنقرةٍ حين تنضج البيانات.

    python manage.py refresh_extraction_profiles            # يتعلّم + يحفظ + إشارة
    python manage.py refresh_extraction_profiles --measure-only   # بلا حفظ
    python manage.py refresh_extraction_profiles --retrain-threshold 200

آمنٌ للذاكرة (جهاز 8GB): استعلاماتٌ خفيفة بلا تحميل صور. بلا إنترنت."""
import json
import os

from django.core.management.base import BaseCommand

from core.extraction.entity_profiles import learn_profiles, PROFILES_PATH

SNAPSHOT = os.path.join('var', 'profiles_snapshot.json')


class Command(BaseCommand):
    help = 'يُشغّل مكتشف بروفايل الجهات، يُقسّي القواعد، ويصدر إشارة إعادة التدريب.'

    def add_arguments(self, parser):
        parser.add_argument('--measure-only', action='store_true', help='بلا حفظ لقطة/بروفايلات')
        parser.add_argument('--min-books', type=int, default=3)
        parser.add_argument('--retrain-threshold', type=int, default=250,
                            help='عدد الكتب المضافة الذي يُفعّل إشارة إعادة التدريب')

    def handle(self, *args, **opts):
        from core.models import Book, Entity

        out = None if opts['measure_only'] else PROFILES_PATH
        profiles, stats = learn_profiles(min_books=opts['min_books'], out_path=out)

        total_books = Book.objects.filter(is_deleted=False).count()
        total_entities = Entity.objects.filter(is_active=True).count()
        prev = {}
        if os.path.exists(SNAPSHOT):
            try:
                prev = json.load(open(SNAPSHOT, encoding='utf-8'))
            except Exception:
                prev = {}

        books_added = total_books - prev.get('total_books', 0)
        prev_ids = set(prev.get('profiled_entity_ids', []))
        now_ids = set(profiles.keys())
        new_entities = sorted(now_ids - prev_ids)
        gram = stats['with_number_grammar']

        w = self.stdout.write
        w('═' * 56)
        w('  مكتشف البروفايل — حالة الحلقة الذاتيّة')
        w('═' * 56)
        w(f"  جهاتٌ مبروفلة (≥{opts['min_books']} كتب) : {stats['entities']} / {total_entities} نشطة")
        w(f"  بنحوِ رقمٍ مُتعلَّم              : {gram}  (اتساقٌ ذاتيّ {int(stats['grammar_self_consistency']*100)}%)")
        w(f"  كتبٌ مؤكَّدة إجمالاً             : {total_books}")
        if prev:
            w(f"  جهاتٌ جديدة منذ اللقطة         : {len(new_entities)}")
            w(f"  كتبٌ مضافة منذ اللقطة          : {books_added:+d}")
        else:
            w('  (لا لقطة سابقة — هذه أوّل مرّة)')

        # النصف الفوريّ: القواعد تقسّت الآن (الملف حُدِّث؛ EntityProfileStore يقرؤه حيّاً)
        if out:
            w('')
            w('  ✅ القواعد الحيّة تقسّت الآن (طبقة المُصادِق تقرأ البروفايل المحدَّث).')

        # إشارة إعادة تدريب GPU (النصف بنقرةٍ منك)
        thr = opts['retrain_threshold']
        signal = (not prev) or books_added >= thr or len(new_entities) >= 5
        w('')
        w('─' * 56)
        if signal:
            w(f'  🔔 إشارة: إعادة تدريب GPU تستحقّ (مضاف {books_added} ≥ {thr} أو جهاتٌ جديدة).')
            w('     الخطوة (بنقرتك — رفع بياناتٍ سرّية):')
            w('       1) python training/handwriting/harvest/build_lora_dataset.py')
            w('       2) python training/handwriting/harvest/augment_dates.py')
            w('       3) (رفع + دفع نوتبوك LoRA/v6 على Lightning/كاغل)')
        else:
            w(f'  ⏸️  إشارة: التدريب لا يستحقّ بعد (مضاف {books_added} < {thr}).')
            w('     القواعد الحيّة كافية حتى تنضج البيانات.')
        w('─' * 56)

        if out:
            snap = {'total_books': total_books, 'total_entities': total_entities,
                    'profiled_entity_ids': sorted(now_ids),
                    'with_number_grammar': gram}
            json.dump(snap, open(SNAPSHOT, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
            w(f'  لقطةٌ حُفِظت: {SNAPSHOT}')
