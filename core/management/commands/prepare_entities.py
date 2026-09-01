# -*- coding: utf-8 -*-
"""أمر تهيئة الجهات — يوحّد الكيانات المُكرّرة لأي قاعدة بيانات مستعادة/جديدة.

مرحلتان:
1) الكشف الإملائي الآلي المحافظ (norm_key: تشكيل/همزات/ة-ه/ى-ي/مسافات فقط).
2) خطة الدمج المُخلَّدة (core/data/entity_merge_plan.json) — قرارات دمج
   رُوجعت بشرياً (اختصارات/تصاحيف/تشريفات) محفوظة بالأسماء، تُعاد عند كل
   استعادة. تُحدَّث من تاريخ الدمج الفعلي عبر --export-plan.

موافقة المستخدم مضمونة بالتصميم: التشغيل بلا وسائط = تقرير فقط؛
--apply ينفّذ ما عُرض.

الاستخدام:
    python manage.py prepare_entities                # تقرير (الافتراضي الآمن)
    python manage.py prepare_entities --apply         # ينفّذ الكشف الآلي + الخطة
    python manage.py prepare_entities --export-plan   # يولّد الخطة من تاريخ الدمج
"""
from django.core.management.base import BaseCommand

from core.entity_dedup import (
    PLAN_PATH, apply_plan_action, export_merge_plan, find_duplicate_clusters,
    load_merge_plan, merge_entities, plan_actions, save_merge_plan,
)


class Command(BaseCommand):
    help = 'كشف/دمج الجهات المُكرّرة — تهيئة قاعدة بيانات مستعادة أو جديدة.'

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true',
                            help='ينفّذ الدمج فعلياً (الافتراضي: تقرير فقط بلا تغيير).')
        parser.add_argument('--export-plan', action='store_true',
                            help='يولّد خطة الدمج من تاريخ الدمج الفعلي (merged_into) ويحفظها.')

    def handle(self, *args, **opts):
        if opts['export_plan']:
            plan = export_merge_plan()
            save_merge_plan(plan)
            self.stdout.write(self.style.SUCCESS(
                f'✓ صُدِّرت خطة من {len(plan)} عنقوداً → {PLAN_PATH}'))
            return

        apply = opts['apply']
        merged = moved_books = moved_mem = 0

        # المرحلة 1 — الكشف الإملائي الآلي المحافظ
        clusters = find_duplicate_clusters()
        if clusters:
            self.stdout.write(f'عناقيد تكرار إملائي: {len(clusters)}\n')
            for c in clusters:
                canon = c['canonical']
                victims = [m for m in c['members'] if m.id != canon.id]
                self.stdout.write(f'  الأمّ: {canon.name!r}')
                for v in victims:
                    self.stdout.write(f'     ← {v.name!r}')
                if apply:
                    r = merge_entities(canon.id, [v.id for v in victims])
                    merged += r['merged']
                    moved_books += r['moved_books']
                    moved_mem += r['moved_memory']
        else:
            self.stdout.write('✓ لا تكرارات إملائية.')

        # المرحلة 2 — خطة الدمج المُخلَّدة (القرارات المُراجَعة بشرياً)
        actions = plan_actions(load_merge_plan())
        if actions:
            self.stdout.write(f'\nإجراءات الخطة المُخلَّدة: {len(actions)}\n')
            for a in actions:
                mark = '' if a['target'].name == a['canonical'] \
                    else f"  (تُسمّى → {a['canonical']!r})"
                self.stdout.write(f'  الأمّ: {a["target"].name!r}{mark}')
                for v in a['victims']:
                    self.stdout.write(f'     ← {v.name!r}')
                if apply:
                    r = apply_plan_action(a)
                    merged += r['merged']
                    moved_books += r['moved_books']
                    moved_mem += r['moved_memory']
        else:
            self.stdout.write('✓ خطة الدمج مُطبَّقة بالكامل (أو لا خطة).')

        if not clusters and not actions:
            self.stdout.write(self.style.SUCCESS('\n✓ قاعدة البيانات موحَّدة — لا شيء يُفعل.'))
            return

        if apply:
            self.stdout.write(self.style.SUCCESS(
                f'\n✓ دُمج {merged} نسخة | {moved_books} رابط كتاب + {moved_mem} صفّ ذاكرة أُعيد توجيهه.'))
            self.stdout.write(self.style.WARNING(
                'أعد تشغيل الخادم لإعادة بناء فهرس ذاكرة الترويسة بالإشارة المُوحَّدة.'))
        else:
            self.stdout.write(self.style.WARNING(
                '\n(تقرير فقط — لم يُنفَّذ شيء). للتنفيذ: python manage.py prepare_entities --apply'))
