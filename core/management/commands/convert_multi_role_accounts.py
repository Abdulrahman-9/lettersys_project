# -*- coding: utf-8 -*-
"""التحويلُ إلى دورٍ واحد (قرارُ المالك 2026‑11‑16، الدفعة 0): جافٌّ افتراضيّاً، و``--apply`` عند النشر.

يبقى لكلّ حسابٍ الدورُ الذي يعرضه المحرّر، ويتحوّل ما زاد عليه استثناءاتٍ باسمه (``one_role_plan``).
الحسابُ الذي لا يُسند دورُه الباقي في قسمه يُترك لقرار المالك ولا يُمسّ. ``--undo CSV`` يعيد ما كُتب.
"""
import csv
import os
from datetime import datetime

from django.conf import settings
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.permission_service import apply_one_role_plan, one_role_plan, undo_one_role_plan
from core.scoping import CAPABILITIES, ROLE_LABELS


def _labels(keys):
    return '، '.join(CAPABILITIES[k].label if k in CAPABILITIES else k for k in keys) or '-'


class Command(BaseCommand):
    help = 'يحوّل الحسابات التي تجمع دورين إلى دورٍ واحد واستثناءات. جافٌّ ما لم يُعطَ --apply.'

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true', help='اكتب التحويل (بلا هذا: عرضٌ فقط).')
        parser.add_argument('--undo', metavar='CSV', help='تراجعْ عن تحويلٍ سابق من ملفّه.')
        parser.add_argument('--expect-db', help='اسمُ القاعدة المقصودة — شرطٌ لـ--apply و--undo.')
        parser.add_argument('--by', help='اسمُ مدير النظام الذي يُنسب إليه الأثر (الافتراض: أوّلُ مديرٍ نشط).')
        parser.add_argument('--out', help='ملفُّ CSV لما كُتب (للتراجع).')

    def handle(self, *args, **options):
        writes = options['apply'] or options['undo']
        db = settings.DATABASES['default']['NAME']
        if writes and options['expect_db'] != db:
            raise CommandError(f'القاعدةُ {db} لا تطابق --expect-db ({options["expect_db"]}). لم يُكتب شيء.')
        by = (User.objects.filter(username=options['by'], is_superuser=True, is_active=True).first() if options['by']
              else User.objects.filter(is_superuser=True, is_active=True).order_by('pk').first())
        if writes and by is None:
            raise CommandError('لا مديرَ نظامٍ نشطاً يُنسب إليه الأثر. لم يُكتب شيء.')
        if options['undo']:
            return self._undo(options['undo'], by)

        out = options['out'] or f'convert_multi_role_{datetime.now():%Y%m%d_%H%M}.csv'
        # ذرّيّ (فيبل 11-16): ملفُّ التراجع يُفتح قبل أيّ كتابة ('x' يرفض ملفّاً قائماً أو مساراً خاطئاً)،
        # والتحويلُ كلُّه معاملةٌ واحدة — سقوطٌ في منتصفه لا يترك تحويلاً جزئيّاً بلا ملفّ.
        fh = open(out, 'x', encoding='utf-8-sig', newline='') if options['apply'] else None
        try:
            with transaction.atomic():
                done, skipped, planned = self._convert(options['apply'], by, fh)
        except BaseException:
            if fh is not None:
                fh.close()
                os.remove(out)
            raise
        if fh is not None:
            fh.close()
            self.stdout.write(self.style.SUCCESS(f'حُوِّل {done} حساباً · تُرك {len(skipped)} لقرارك · {out}'))
        else:
            self.stdout.write(f'جافّ: {planned} حساباً يجمع دورين، {len(skipped)} منها يحتاج قرارك. لم يُكتب شيء.')

    def _convert(self, apply, by, fh):
        writer = None
        if fh is not None:
            writer = csv.writer(fh)
            writer.writerow(['username', 'removed_groups', 'created_exceptions'])
        done, skipped, planned = 0, [], 0
        for user in User.objects.filter(is_superuser=False).select_related('profile').order_by('username'):
            plan = one_role_plan(user)
            if plan is None:
                continue
            planned += 1
            self.stdout.write(
                f'{user.get_username()}\tيبقى: {ROLE_LABELS[plan["kept"]]}\tيُزال: {"، ".join(plan["remove"])}\t'
                f'استثناء: {_labels(plan["grant"])}\tخامد: {_labels(plan["dormant"])}\t'
                f'يُسقط: {_labels(plan["dropped"])}\tمقفل: {_labels(plan["locked"])}\t'
                f'قائم: {_labels(plan["existing"])}')
            if not plan['kept_assignable']:
                skipped.append(user.get_username())
                self.stdout.write('  !! دورُه الباقي لا يُسند في قسمه — يُترك لقرار المالك ولا يُمسّ.')
                continue
            if apply:
                record = apply_one_role_plan(user, plan, by=by)
                writer.writerow([user.get_username(), '|'.join(record['removed']), '|'.join(record['created'])])
                done += 1
        return done, skipped, planned

    def _undo(self, path, by):
        restored = 0
        with open(path, encoding='utf-8-sig', newline='') as fh:
            for row in csv.DictReader(fh):
                user = User.objects.filter(username=row['username']).first()
                if user is None:
                    self.stdout.write(f'  !! {row["username"]} غيرُ موجود — تُرك.')
                    continue
                removed = [x for x in row['removed_groups'].split('|') if x]
                created = [x for x in row['created_exceptions'].split('|') if x]
                undo_one_role_plan(user, removed, created, by=by)
                restored += 1
        self.stdout.write(self.style.SUCCESS(f'أُعيد {restored} حساباً إلى ما كان عليه.'))
