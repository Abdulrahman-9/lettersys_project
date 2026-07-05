# -*- coding: utf-8 -*-
"""أمر تهيئة الجهات — يوحّد الكيانات المُكرّرة إملائياً لأي قاعدة بيانات جديدة عند النشر.

خطة تهيئة قابلة لإعادة الاستخدام (multi-tenant): كل جهة جديدة تُهيّئ بياناتها بأمرٍ واحد.
يعتمد التطبيع المحافظ عالي الدقّة (norm_key: تشكيل/همزات/ة-ه/ى-ي/مسافات فقط) — لا يدمج
الفروق الدلالية (مثل «الفنية»≠«الادارية»). التكرارات الدلالية/التصحيفية تُراجَع يدوياً
عبر واجهة الدمج (build_manual_cluster) لأنها تحتاج حكماً بشرياً.

الاستخدام:
    python manage.py prepare_entities            # تقرير فقط (لا تغيير — الافتراضي الآمن)
    python manage.py prepare_entities --apply     # ينفّذ الدمج الآلي الآمن ويوحّد الذاكرة
"""
from django.core.management.base import BaseCommand

from core.entity_dedup import find_duplicate_clusters, merge_entities


class Command(BaseCommand):
    help = 'كشف/دمج الجهات المُكرّرة إملائياً — تهيئة قاعدة بيانات جديدة عند النشر.'

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true',
                            help='ينفّذ الدمج فعلياً (الافتراضي: تقرير فقط بلا تغيير).')

    def handle(self, *args, **opts):
        apply = opts['apply']
        clusters = find_duplicate_clusters()
        if not clusters:
            self.stdout.write(self.style.SUCCESS('✓ لا تكرارات إملائية — قاعدة البيانات نظيفة.'))
            return

        self.stdout.write(f'عناقيد تكرار إملائي: {len(clusters)}\n')
        merged = moved_books = moved_mem = 0
        for c in clusters:
            canon = c['canonical']
            victims = [m for m in c['members'] if m.id != canon.id]
            self.stdout.write(f'  الأمّ: {canon.name!r}')
            for v in victims:
                self.stdout.write(f'     ← {v.name!r}')
            if apply:
                r = merge_entities(canon.id, [v.id for v in victims])
                merged += r['merged']; moved_books += r['moved_books']; moved_mem += r['moved_memory']

        if apply:
            self.stdout.write(self.style.SUCCESS(
                f'\n✓ دُمج {merged} نسخة | {moved_books} رابط كتاب + {moved_mem} صفّ ذاكرة أُعيد توجيهه.'))
            self.stdout.write(self.style.WARNING(
                'أعد تشغيل الخادم لإعادة بناء فهرس ذاكرة الترويسة بالإشارة المُوحَّدة.'))
        else:
            self.stdout.write(self.style.WARNING(
                '\n(تقرير فقط — لم يُنفَّذ شيء). للتنفيذ: python manage.py prepare_entities --apply'))
