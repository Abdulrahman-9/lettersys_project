# -*- coding: utf-8 -*-
"""بناءُ شجرة الأقسام من ملفٍّ مُخلَّد — بالرموز لا بالمعرِّفات.

**لماذا ملفٌّ لا اشتقاق:** جُرّب اشتقاقُ الأبوّة من بادئة الرمز فأنتج هراءً
مقيساً («مجلس الادارة» تحت مكتب المدير العام، و«وحدة الموارد البشرية» تحت
«وحدة مشاريع المساهمة»، و«و» ملتبسةٌ بين واسط ووحدة). الأبوّةُ خريطةُ المالك
التنظيميّة، والملفُّ يحفظها ويُعيدها عند كلّ استعادة.

**ولماذا الرموز:** المعرِّفاتُ تتبدّل مع كلّ استعادة، والرمزُ ثابتٌ ومقروء.

جافٌّ افتراضاً — لا يكتب شيئاً حتى يُمرَّر ``--apply``.
"""

import io
import json
import os

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError

from core.admin_service import update_department
from core.models import Department

TREE_PATH = os.path.join(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))), 'data', 'department_tree.json')


def load_tree(path=None):
    """خريطةُ {رمز الابن: رمز الأب} — والمفاتيحُ الشارحةُ (_وصف) تُتخطّى.

    المسارُ يُقرأ **عند الاستدعاء** لا عند الاستيراد: قيمةٌ افتراضيّةٌ مثبَّتةٌ
    في التوقيع تُجمَّد لحظةَ تحميل الوحدة فلا تقبل توجيهاً لاحقاً.
    """
    path = path or TREE_PATH
    if not os.path.exists(path):
        return {}
    with io.open(path, encoding='utf-8') as handle:
        raw = json.load(handle)
    return {k: v for k, v in raw.items() if not k.startswith('_')}


class Command(BaseCommand):
    help = 'يبني شجرة الأقسام من core/data/department_tree.json (جافٌّ افتراضاً).'

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true',
                            help='ينفّذ ما عُرض.')
        parser.add_argument('--by', default='',
                            help='اسمُ مستخدمٍ مديرٍ يُنسَب إليه التغيير في سجلّ الحركات.')

    def handle(self, *args, **options):
        tree = load_tree()
        if not tree:
            self.stdout.write('لا خريطةَ في الملفّ — لا شيء يُفعل.')
            return

        by_code = {d.code: d for d in Department.objects.all()}
        planned, skipped = [], []

        for child_code, parent_code in sorted(tree.items()):
            child = by_code.get(child_code)
            parent = by_code.get(parent_code) if parent_code else None
            if child is None:
                skipped.append('لا قسمَ برمز «%s»' % child_code)
                continue
            if parent_code and parent is None:
                skipped.append('لا أبَ برمز «%s» (لـ%s)' % (parent_code, child_code))
                continue
            if child.parent_id == (parent.pk if parent else None):
                continue
            planned.append((child, parent))

        for note in skipped:
            self.stdout.write(self.style.WARNING('  ⚠ ' + note))

        if not planned:
            self.stdout.write('الشجرةُ مطابقةٌ للملفّ — لا تغيير.')
            return

        for child, parent in planned:
            self.stdout.write('  %-8s %-40s ⟵ %s' % (
                child.code, child.name[:40], parent.code if parent else '— بلا أب'))

        if not options['apply']:
            self.stdout.write('')
            self.stdout.write('عرضٌ فقط (%d رابطاً). أضِف --apply للتنفيذ.' % len(planned))
            return

        actor = self._actor(options['by'])
        for child, parent in planned:
            update_department(child, by=actor, parent=parent)

        self.stdout.write(self.style.SUCCESS(
            'رُبِط %d قسماً بأبيه. الشجرةُ تسيل نزولاً — والآباءُ يرون دفاترَ الأبناء الآن.'
            % len(planned)))

    def _actor(self, username):
        """التغييرُ يُنسَب إلى مديرٍ حقيقيّ — سجلُّ الحركات لا يقبل فاعلاً مجهولاً."""
        if username:
            actor = User.objects.filter(username=username, is_superuser=True).first()
            if actor is None:
                raise CommandError('لا مديرَ باسم «%s».' % username)
            return actor

        actor = User.objects.filter(is_superuser=True).order_by('pk').first()
        if actor is None:
            raise CommandError('لا مديرَ نظامٍ في القاعدة — مرّر --by.')
        return actor
