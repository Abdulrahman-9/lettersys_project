# -*- coding: utf-8 -*-
"""
بذرُ الأقسام من الجهات المرمّزة — أساسُ بُعد النطاق في خطّة التعميم.

**حدُّ القسم بقرار المالك:** الوحداتُ الداخليّة المرمّزة برموزٍ عربيّة (ش13
المتابعة، ش5 العقود، د الموارد البشرية…). أمّا الرموز اللاتينيّة فشركاتٌ
خارجيّة (ADE، ebs، kar…)، والجهات بلا رمزٍ (364) تبقى أطرافَ مراسلةٍ لا أقساماً
مالكة.

جافٌّ افتراضاً — لا يكتب شيئاً حتى يُمرَّر ``--apply``.
"""

import re

from django.core.management.base import BaseCommand
from django.db import transaction

from core.models import Department, Entity

#: حرفٌ عربيٌّ واحدٌ يكفي لتمييز رمز السجلّ الداخليّ عن رمز الشركة الأجنبيّة.
ARABIC = re.compile(r'[؀-ۿ]')


def is_internal_code(code: str) -> bool:
    """أرمزُ سجلٍّ داخليّ هو؟

    شذوذٌ مقيس في القاعدة الحيّة: جهةٌ واحدة حقلُ ``code`` فيها عنوانُ بريد —
    فنستثني ما فيه ``@`` صراحةً بدل أن نثق بالشكل.
    """
    code = (code or '').strip()
    return bool(code) and '@' not in code and bool(ARABIC.search(code))


def internal_entities():
    """الجهات التي تُمثّل وحداتٍ داخليّة، مرتّبةً بالرمز."""
    return sorted(
        (e for e in Entity.objects.exclude(code='').exclude(code__isnull=True)
         if is_internal_code(e.code)),
        key=lambda e: e.code,
    )


class Command(BaseCommand):
    help = 'ينشئ الأقسام من الجهات الداخليّة المرمّزة (جافٌّ ما لم يُمرَّر --apply)'

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true',
                            help='نفّذ الكتابة فعلاً (الافتراضي: عرضٌ فقط)')
        parser.add_argument('--default-code', default='ش13',
                            help='رمزُ القسم الافتراضيّ الذي تُسنَد إليه البيانات القائمة')

    def handle(self, *args, **options):
        apply_changes = options['apply']
        entities = internal_entities()

        if not entities:
            self.stdout.write(self.style.WARNING('لا جهاتٍ داخليّةً مرمّزة — لا شيء يُبذَر.'))
            return

        existing = set(Department.objects.values_list('code', flat=True))
        to_create = [e for e in entities if e.code not in existing]

        self.stdout.write(f'جهاتٌ داخليّةٌ مرمّزة: {len(entities)}')
        self.stdout.write(f'أقسامٌ قائمة: {len(existing)} · ستُنشأ: {len(to_create)}')
        for e in to_create[:60]:
            self.stdout.write(f'  + {e.code} — {e.name}')

        default_code = options['default_code']
        if not any(e.code == default_code for e in entities) and default_code not in existing:
            self.stdout.write(self.style.WARNING(
                f'تنبيه: القسم الافتراضيّ «{default_code}» غير موجودٍ بين الجهات المرمّزة — '
                f'سيُنشأ بلا جهةٍ مقابلة.'
            ))

        if not apply_changes:
            self.stdout.write(self.style.WARNING('\nعرضٌ فقط. أضِف --apply للتنفيذ.'))
            return

        with transaction.atomic():
            created = 0
            for e in to_create:
                Department.objects.create(name=e.name, code=e.code, entity=e)
                created += 1

            default_dept = Department.objects.filter(code=default_code).first()
            if default_dept is None:
                default_dept = Department.objects.create(
                    name='قسم المتابعة', code=default_code,
                )
                created += 1

        self.stdout.write(self.style.SUCCESS(
            f'أُنشئ {created} قسماً. الافتراضيّ: {default_dept}'
        ))
