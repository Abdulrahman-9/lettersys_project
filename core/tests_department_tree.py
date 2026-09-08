# -*- coding: utf-8 -*-
"""حرّاسُ بناء شجرة الأقسام من الملفّ المُخلَّد."""

import io
import json
import tempfile
from unittest import mock

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase

from core.management.commands import set_department_parents as cmd
from core.models import Department


class DepartmentTreeCommandTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser('root', 'r@x.co', 'pw')
        # الاسمُ فريدٌ أيضاً، وهجرةُ بُعد القسم تُنشئ قسماً افتراضيّاً —
        # فأسماءُ الاختبار مُميَّزةٌ بلاحقة.
        self.dg = Department.objects.create(name='مكتب المدير العام (خ)', code='ت.ش')
        self.dept = Department.objects.create(name='قسم المتابعة (خ)', code='ت.ش13')
        self.section = Department.objects.create(name='شعبة الموازنة (خ)', code='ت.ش.ت')
        self.unit = Department.objects.create(name='وحدة التقارير (خ)', code='ت.و.ت')

    def _tree(self, mapping):
        handle = tempfile.NamedTemporaryFile('w', suffix='.json', delete=False,
                                             encoding='utf-8')
        json.dump(mapping, handle, ensure_ascii=False)
        handle.close()
        return mock.patch.object(cmd, 'TREE_PATH', handle.name)

    def _run(self, mapping, **opts):
        with self._tree(mapping):
            call_command('set_department_parents', **opts)

    def test_dry_run_writes_nothing(self):
        """جافٌّ افتراضاً — الشجرةُ تُوسّع الرؤية فلا تُبنى بالخطأ."""
        self._run({'ت.ش13': 'ت.ش'})

        self.dept.refresh_from_db()
        self.assertIsNone(self.dept.parent_id)

    def test_apply_builds_the_full_chain(self):
        """قسم ← شعبة ← وحدة كما أقرّه المالك."""
        self._run({'ت.ش13': 'ت.ش', 'ت.ش.ت': 'ت.ش13', 'ت.و.ت': 'ت.ش.ت'},
                  apply=True)

        self.dept.refresh_from_db()
        self.section.refresh_from_db()
        self.unit.refresh_from_db()
        self.assertEqual(self.dept.parent_id, self.dg.pk)
        self.assertEqual(self.section.parent_id, self.dept.pk)
        self.assertEqual(self.unit.parent_id, self.section.pk)

    def test_the_parent_sees_the_whole_subtree(self):
        """أثرُ الأبوّة الوحيد: الأبُ يرى دفاترَ الأبناء."""
        from core.scoping import subtree_ids

        self._run({'ت.ش.ت': 'ت.ش13', 'ت.و.ت': 'ت.ش.ت'}, apply=True)

        self.assertEqual(sorted(subtree_ids(self.dept.pk)),
                         sorted([self.dept.pk, self.section.pk, self.unit.pk]))
        self.assertEqual(subtree_ids(self.unit.pk), [self.unit.pk])

    def test_running_twice_changes_nothing(self):
        """الأمرُ خاملٌ عند التكرار — يُعاد عند كلّ استعادةٍ بلا أثرٍ جانبيّ."""
        mapping = {'ت.ش13': 'ت.ش'}
        self._run(mapping, apply=True)
        self._run(mapping, apply=True)

        self.dept.refresh_from_db()
        self.assertEqual(self.dept.parent_id, self.dg.pk)

    def test_a_cycle_is_refused(self):
        """حارسُ الحلقات في الخدمة لا في الواجهة — والأمرُ يمرّ منها."""
        from django.core.exceptions import ValidationError

        self._run({'ت.ش.ت': 'ت.ش13'}, apply=True)

        with self.assertRaises(ValidationError):
            self._run({'ت.ش13': 'ت.ش.ت'}, apply=True)

    def test_unknown_codes_are_reported_not_crashed(self):
        """رمزٌ غائبٌ في الملفّ لا يُسقط الأمرَ على بقيّة الروابط."""
        self._run({'لا-وجود-له': 'ت.ش', 'ت.ش13': 'ت.ش'}, apply=True)

        self.dept.refresh_from_db()
        self.assertEqual(self.dept.parent_id, self.dg.pk)

    def test_comment_keys_are_skipped(self):
        """المفاتيحُ الشارحةُ (_وصف) توثيقٌ لا بيانات."""
        self.assertEqual(cmd.load_tree.__doc__ is not None, True)

        with self._tree({'_وصف': 'شرح', 'ت.ش13': 'ت.ش'}):
            self.assertEqual(cmd.load_tree(cmd.TREE_PATH), {'ت.ش13': 'ت.ش'})


class ShippedTreeFileTests(TestCase):
    def test_the_shipped_file_is_valid_and_acyclic(self):
        """ملفُّ المشروع نفسُه سليم — بلا حلقةٍ وبقيمٍ نصّيّة."""
        tree = cmd.load_tree()

        self.assertTrue(tree)
        for child, parent in tree.items():
            self.assertIsInstance(parent, str)
            seen, node, hops = {child}, parent, 0
            while node in tree and hops < 20:
                self.assertNotIn(node, seen, 'حلقةٌ في ملفّ الشجرة')
                seen.add(node)
                node = tree[node]
                hops += 1
