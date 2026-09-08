# -*- coding: utf-8 -*-
"""اختبارات ميزة «الأضابير» (core/views/dossiers.py).

تغطّي: المستوى 1 (أقسام لها كتب + أعداد صادر/وارد)، المستوى 2 (تقسيم بالاتجاه
والنوع + سلّة متفرقة)، والتحكّم بالوصول (المستخدم العادي يرى كتبه فقط).
"""
from datetime import date, timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from .models import Book, Entity

#: تبويبُ «الشعب والوحدات والأفراد» — جهاتُ هذه الاختبارات كلُّها «وحدة …»،
#: والصفحةُ صارت مبوَّبةً بثلاثةِ أصنافٍ افتراضُها «الجهات الداخلية».
UNIT_TAB = {'kind': 'unit'}


class DossierBaseSetup(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser('admin', 'a@x.com', 'pass1234')
        self.clerk = User.objects.create_user('clerk', 'c@x.com', 'pass1234')
        self.today = date.today()

        # التبويبُ حقلٌ يملكه المالك (هجرة 0074) — تُهيَّأ هذه في «الشعب والوحدات».
        self.lijan = Entity.objects.create(name='وحدة اللجان', code='LJ',
                                           kind=Entity.KIND_UNIT)
        self.idara = Entity.objects.create(name='وحدة الإدارة', code='ID',
                                           kind=Entity.KIND_UNIT)
        self.empty = Entity.objects.create(name='قسم بلا كتب', code='EM',
                                           kind=Entity.KIND_UNIT)   # 0 كتب
        self.inactive = Entity.objects.create(name='قسم معطّل', is_active=False,
                                              kind=Entity.KIND_UNIT)

    def _mk(self, num, owner, issuing=None, receiving=None, dtype='', kind='outgoing_internal'):
        b = Book.objects.create(our_number=num, title='كتاب ' + num, date=self.today,
                                kind=kind, document_type=dtype, created_by=owner)
        if issuing:
            b.issuing_entities.set(issuing)
        if receiving:
            b.receiving_entities.set(receiving)
        return b


class DossierListTests(DossierBaseSetup):
    def setUp(self):
        super().setUp()
        # لجان: 2 صادر + 1 وارد ؛ إدارة: 1 وارد
        self._mk('s1', self.admin, issuing=[self.lijan], dtype='أمر إداري')
        self._mk('s2', self.admin, issuing=[self.lijan], dtype='تقرير')
        self._mk('w1', self.admin, receiving=[self.lijan], dtype='تقرير', kind='incoming_internal')
        self._mk('w2', self.admin, receiving=[self.idara], kind='incoming_internal')
        self.client.force_login(self.admin)

    def test_login_required(self):
        self.client.logout()
        r = self.client.get(reverse('dossier_list'))
        self.assertEqual(r.status_code, 302)

    def test_lists_only_entities_with_books(self):
        rows = self.client.get(reverse('dossier_list'), UNIT_TAB).context['page_obj'].object_list
        names = {e.name for e in rows}
        self.assertIn('وحدة اللجان', names)
        self.assertIn('وحدة الإدارة', names)
        self.assertNotIn('قسم بلا كتب', names)      # 0 كتب → مُستبعَد
        self.assertNotIn('قسم معطّل', names)         # غير نشط → مُستبعَد

    def test_counts_split_issued_received(self):
        rows = {e.name: e for e in self.client.get(reverse('dossier_list'), UNIT_TAB).context['page_obj'].object_list}
        self.assertEqual(rows['وحدة اللجان'].issued_count, 2)
        self.assertEqual(rows['وحدة اللجان'].received_count, 1)
        self.assertEqual(rows['وحدة الإدارة'].received_count, 1)
        self.assertEqual(rows['وحدة الإدارة'].issued_count, 0)

    def test_ordered_by_total_desc(self):
        rows = list(self.client.get(reverse('dossier_list'), UNIT_TAB).context['page_obj'].object_list)
        self.assertEqual(rows[0].name, 'وحدة اللجان')   # 3 كتب > 1

    def test_search_by_name(self):
        rows = self.client.get(reverse('dossier_list'), dict(UNIT_TAB, q='الإدارة')).context['page_obj'].object_list
        names = {e.name for e in rows}
        self.assertEqual(names, {'وحدة الإدارة'})


class DossierDetailTests(DossierBaseSetup):
    def setUp(self):
        super().setUp()
        self._mk('s1', self.admin, issuing=[self.lijan], dtype='أمر إداري')
        self._mk('s2', self.admin, issuing=[self.lijan], dtype='أمر إداري')
        self._mk('s3', self.admin, issuing=[self.lijan], dtype='')           # → متفرقة
        self._mk('w1', self.admin, receiving=[self.lijan], dtype='تقرير', kind='incoming_internal')
        self.client.force_login(self.admin)

    def test_detail_ok(self):
        r = self.client.get(reverse('dossier_detail', args=[self.lijan.pk]))
        self.assertEqual(r.status_code, 200)

    def test_direction_counts(self):
        ctx = self.client.get(reverse('dossier_detail', args=[self.lijan.pk])).context
        self.assertEqual(ctx['outgoing_count'], 3)    # s1,s2,s3
        self.assertEqual(ctx['incoming_count'], 1)    # w1

    def test_grouping_by_type(self):
        ctx = self.client.get(reverse('dossier_detail', args=[self.lijan.pk])).context
        out = {g['type']: g['count'] for g in ctx['outgoing_groups']}
        self.assertEqual(out.get('أمر إداري'), 2)
        self.assertEqual(out.get('متفرقة'), 1)        # الفارغ تحت متفرقة
        self.assertEqual(ctx['outgoing_groups'][-1]['type'], 'متفرقة')  # متفرقة أخيراً

    def test_inactive_entity_404(self):
        r = self.client.get(reverse('dossier_detail', args=[self.inactive.pk]))
        self.assertEqual(r.status_code, 404)


class DossierAccessControlTests(DossierBaseSetup):
    def setUp(self):
        super().setUp()
        # كتاب للمشرف وكتاب للموظّف على نفس الجهة
        self._mk('admin1', self.admin, issuing=[self.lijan], dtype='أمر إداري')
        self._mk('clerk1', self.clerk, issuing=[self.lijan], dtype='تقرير')

    def test_clerk_sees_only_own_books_in_counts(self):
        self.client.force_login(self.clerk)
        rows = {e.name: e for e in self.client.get(reverse('dossier_list'), UNIT_TAB).context['page_obj'].object_list}
        self.assertEqual(rows['وحدة اللجان'].issued_count, 1)   # كتابه فقط

    def test_clerk_detail_excludes_others(self):
        self.client.force_login(self.clerk)
        ctx = self.client.get(reverse('dossier_detail', args=[self.lijan.pk])).context
        self.assertEqual(ctx['outgoing_count'], 1)
        nums = {b.our_number for g in ctx['outgoing_groups'] for b in g['books']}
        self.assertEqual(nums, {'clerk1'})                      # لا يرى admin1

    def test_admin_sees_all(self):
        self.client.force_login(self.admin)
        ctx = self.client.get(reverse('dossier_detail', args=[self.lijan.pk])).context
        self.assertEqual(ctx['outgoing_count'], 2)


class DossierFilterTests(DossierBaseSetup):
    def setUp(self):
        super().setUp()
        from datetime import timedelta
        self._mk('f1', self.admin, issuing=[self.lijan], dtype='أمر إداري')
        self._mk('f2', self.admin, issuing=[self.lijan], dtype='تقرير')
        self._mk('f3', self.admin, issuing=[self.lijan], dtype='أمر إداري')
        Book.objects.filter(our_number='f3').update(
            date=self.today - timedelta(days=10), secret_level='secret')
        self.client.force_login(self.admin)

    def _detail(self, **params):
        return self.client.get(reverse('dossier_detail', args=[self.lijan.pk]), params)

    def test_filter_by_type(self):
        ctx = self._detail(document_type='أمر إداري').context
        self.assertEqual(ctx['outgoing_count'], 2)                 # f1, f3
        self.assertEqual({g['type'] for g in ctx['outgoing_groups']}, {'أمر إداري'})

    def test_filter_by_secret(self):
        self.assertEqual(self._detail(secret_level='secret').context['outgoing_count'], 1)

    def test_filter_by_date_to(self):
        from datetime import timedelta
        dt = (self.today - timedelta(days=5)).strftime('%Y-%m-%d')
        ctx = self._detail(date_to=dt).context
        nums = {b.our_number for g in ctx['outgoing_groups'] for b in g['books']}
        self.assertEqual(nums, {'f3'})                             # الأقدم فقط

    def test_available_types_listed(self):
        vals = {t['value'] for t in self._detail().context['available_types']}
        self.assertIn('أمر إداري', vals)
        self.assertIn('تقرير', vals)

    def test_active_filter_count(self):
        self.assertEqual(self._detail(document_type='تقرير', q='ك').context['active_filter_count'], 2)


class DossierReportTests(DossierBaseSetup):
    def setUp(self):
        super().setUp()
        self.b1 = self._mk('r1', self.admin, issuing=[self.lijan], dtype='أمر إداري')
        self._mk('r2', self.admin, receiving=[self.lijan], dtype='تقرير', kind='incoming_internal')
        self.client.force_login(self.admin)

    def test_report_ok(self):
        r = self.client.get(reverse('dossier_report', args=[self.lijan.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'تقرير إضبارة')

    def test_report_counts(self):
        ctx = self.client.get(reverse('dossier_report', args=[self.lijan.pk])).context
        self.assertEqual(ctx['outgoing_count'], 1)
        self.assertEqual(ctx['incoming_count'], 1)

    def test_report_filtered_by_type(self):
        ctx = self.client.get(reverse('dossier_report', args=[self.lijan.pk]),
                              {'document_type': 'أمر إداري'}).context
        self.assertEqual(ctx['outgoing_count'], 1)
        self.assertEqual(ctx['incoming_count'], 0)

    def test_report_single_book(self):
        r = self.client.get(reverse('dossier_report', args=[self.lijan.pk]), {'book_id': self.b1.pk})
        self.assertTrue(r.context['single_book'])
        self.assertContains(r, 'بطاقة كتاب')

    def test_report_login_required(self):
        self.client.logout()
        self.assertEqual(
            self.client.get(reverse('dossier_report', args=[self.lijan.pk])).status_code, 302)


class FilterEngineExtraTests(TestCase):
    """فلاتر المحرّك الجديدة (النوع/السرية)."""
    def setUp(self):
        self.u = User.objects.create_superuser('a', 'a@x.com', 'p')
        Book.objects.create(our_number='e1', title='ك', date=date.today(),
                            kind='outgoing_internal', document_type='تقرير',
                            secret_level='secret', created_by=self.u)
        Book.objects.create(our_number='e2', title='ك', date=date.today(),
                            kind='outgoing_internal', document_type='أمر إداري',
                            created_by=self.u)

    def test_document_type_filter(self):
        from core.views.filter_helpers import BookFilterEngine
        qs = BookFilterEngine.apply_document_type_filter(Book.objects.all(), 'تقرير')
        self.assertEqual([b.our_number for b in qs], ['e1'])

    def test_document_type_empty_noop(self):
        from core.views.filter_helpers import BookFilterEngine
        self.assertEqual(BookFilterEngine.apply_document_type_filter(Book.objects.all(), '').count(), 2)

    def test_secret_filter(self):
        from core.views.filter_helpers import BookFilterEngine
        qs = BookFilterEngine.apply_secret_filter(Book.objects.all(), 'secret')
        self.assertEqual([b.our_number for b in qs], ['e1'])

    def test_secret_filter_invalid_noop(self):
        from core.views.filter_helpers import BookFilterEngine
        self.assertEqual(BookFilterEngine.apply_secret_filter(Book.objects.all(), 'bogus').count(), 2)


class DossierReportOrgTests(DossierBaseSetup):
    """ترويسة التقرير تأخذ هوية المؤسسة (شركة/قسم/وحدة) من الإعدادات."""
    def test_report_uses_org_identity(self):
        from core.models import EmailSettings
        cfg = EmailSettings.get()
        cfg.org_name = 'شركة الاختبار'
        cfg.org_section = 'قسم الأرشيف'
        cfg.org_unit = 'وحدة الوارد'
        cfg.save()
        self._mk('x1', self.admin, issuing=[self.lijan], dtype='تقرير')
        self.client.force_login(self.admin)
        r = self.client.get(reverse('dossier_report', args=[self.lijan.pk]))
        self.assertContains(r, 'شركة الاختبار')
        self.assertContains(r, 'قسم الأرشيف')
        self.assertContains(r, 'وحدة الوارد')


class DossierDetailPerfTests(DossierBaseSetup):
    """must#1: عدد استعلامات التفصيل لا يتوسّع خطّياً مع عدد الأنواع."""
    def test_detail_query_count_bounded(self):
        for i, t in enumerate(['أمر إداري', 'تقرير', 'اعمام', 'محضر', 'توجيه', 'تأكيد']):
            self._mk(f'q{i}', self.admin, issuing=[self.lijan], dtype=t)
            self._mk(f'w{i}', self.admin, receiving=[self.lijan], dtype=t, kind='incoming_internal')
        self.client.force_login(self.admin)
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        with CaptureQueriesContext(connection) as ctx:
            self.client.get(reverse('dossier_detail', args=[self.lijan.pk]))
        # المسار القديم (3 استعلامات/نوع×اتجاهين) كان ~40+ لـ6 أنواع؛ الدفعة الواحدة تبقي العدد ثابتاً
        self.assertLess(len(ctx.captured_queries), 22,
                        f"عدد الاستعلامات تضخّم: {len(ctx.captured_queries)}")


class BookFormDocTypeTests(TestCase):
    """حوكمة: تطبيع document_type عند الحفظ يمنع متغيّرات إملائية."""
    def test_clean_document_type_collapses_whitespace(self):
        from core.forms import BookForm
        form = BookForm()
        form.cleaned_data = {'document_type': '  أمر    إداري  '}
        self.assertEqual(form.clean_document_type(), 'أمر إداري')

    def test_clean_document_type_empty(self):
        from core.forms import BookForm
        form = BookForm()
        form.cleaned_data = {'document_type': '   '}
        self.assertEqual(form.clean_document_type(), '')


class DossierFilterBarTests(DossierBaseSetup):
    """شريط الفلاتر/العدّادات + presets الفترة + إصلاحات مراجعة الفريق السبعة."""

    def setUp(self):
        super().setUp()
        self.client.force_login(self.admin)

    def _overdue(self, num, owner, issuing):
        b = Book.objects.create(our_number=num, title='ك' + num, date=self.today,
                                kind='outgoing_internal', created_by=owner,
                                due_date=self.today - timedelta(days=3), is_archived=False)
        b.issuing_entities.set(issuing)
        return b

    def _overdue_chip(self, entity):
        r = self.client.get(reverse('dossier_detail', args=[entity.pk]))
        return next(c for c in r.context['counter_chips'] if c['key'] == 'overdue')

    def test_counter_no_fanout_multi_entity(self):
        # كتاب واحد بثلاث جهات مُصدِرة، متأخّر → يُعدّ مرّة واحدة لا ثلاثاً
        self._overdue('m1', self.admin, [self.lijan, self.idara, self.empty])
        self.assertEqual(self._overdue_chip(self.lijan)['count'], 1)

    def test_counter_respects_access_control(self):
        self._overdue('o1', self.admin, [self.lijan])   # كتاب المشرف
        self.client.force_login(self.clerk)
        self.assertEqual(self._overdue_chip(self.lijan)['count'], 0)   # الموظّف لا يراه

    def test_period_preset_saturday_and_manual_wins(self):
        from core.views.filter_helpers import BookFilterEngine
        df, dt = BookFilterEngine.resolve_period_preset('week', self.today)
        self.assertEqual(df.weekday(), 5)                 # بداية الأسبوع = السبت
        self.assertEqual(dt, self.today)
        r = self.client.get(reverse('dossier_detail', args=[self.lijan.pk]), {'period': 'month'})
        self.assertEqual(r.context['filters']['period'], 'month')
        self.assertIsNotNone(r.context['filters']['date_from'])
        r2 = self.client.get(reverse('dossier_detail', args=[self.lijan.pk]),
                             {'period': 'month', 'date_from': '2020-01-01'})
        self.assertEqual(r2.context['filters']['date_from'].year, 2020)   # اليدوي يفوز

    def test_document_type_normalized_on_save_and_matches_filter(self):
        b = self._mk('d1', self.admin, issuing=[self.lijan], dtype='أمر  إداري')   # مسافة مزدوجة
        b.refresh_from_db()
        self.assertEqual(b.document_type, 'أمر إداري')     # طُبِّع في save()
        r = self.client.get(reverse('dossier_detail', args=[self.lijan.pk]), {'document_type': 'أمر إداري'})
        self.assertEqual(sum(g['count'] for g in r.context['outgoing_groups']), 1)   # يطابق (لا 0)

    def test_sort_honored_in_detail(self):
        self._mk('b2', self.admin, issuing=[self.lijan], dtype='نوع')
        self._mk('b1', self.admin, issuing=[self.lijan], dtype='نوع')
        r = self.client.get(reverse('dossier_detail', args=[self.lijan.pk]), {'sort': 'our_number'})
        nums = [bk.our_number for g in r.context['outgoing_groups'] for bk in g['books']]
        self.assertEqual(nums, sorted(nums))              # الفرز مُطبَّق فعلاً

    def test_a11y_markers_and_period_links(self):
        self._mk('a1', self.admin, issuing=[self.lijan])
        body = self.client.get(reverse('dossier_detail', args=[self.lijan.pk]),
                              {'followup': 'archived', 'period': 'month'}).content.decode()
        self.assertIn('aria-current="page"', body)         # الفلتر النشط لقارئ الشاشة
        self.assertIn('role="group"', body)                # مجموعة الفترة مسمّاة
        self.assertIn('period=month', body)                # رقائق الفترة روابط GET
        self.assertNotIn('data-period=', body)             # لا أزرار قديمة
        self.assertNotIn('<input type="hidden" name="period"', body)   # لا hidden input

    def test_folder_cabinet_full_count_and_subfile(self):
        """الخزانة: بطاقة المجلد تعرض العدد الكامل (لا قصّ مضلِّل)،
        والملف الثانوي المفتوح يعرض كل الصفوف (سقفه 200 لا 12)."""
        for i in range(14):
            self._mk('v%03d' % i, self.admin, issuing=[self.lijan], dtype='مذكرة')
        # الخزانة (بلا نوع): مجلد «مذكرة» بعدّه الكامل، بلا جداول مكدّسة
        r = self.client.get(reverse('dossier_detail', args=[self.lijan.pk]))
        body = r.content.decode()
        self.assertIn('folder-card', body)
        self.assertIn('document_type=%D9%85%D8%B0%D9%83%D8%B1%D8%A9', body)   # رابط المجلد
        g = next(x for x in r.context['outgoing_groups'] if x['type'] == 'مذكرة')
        self.assertEqual(g['count'], 14)
        # الملف الثانوي: كل الـ14 صفاً معروضة (لا قصّ عند 12) وكسرة العودة حاضرة
        r2 = self.client.get(reverse('dossier_detail', args=[self.lijan.pk]),
                             {'document_type': 'مذكرة'})
        g2 = next(x for x in r2.context['outgoing_groups'] if x['type'] == 'مذكرة')
        self.assertEqual(len(g2['books']), 14)
        self.assertFalse(g2['truncated'])
        self.assertIn('كل الملفات', r2.content.decode())

    def test_misc_folder_opens_untyped_books(self):
        """سلّة «متفرقة» تُفتح كملف ثانوي وتعرض الكتب بلا نوع فقط."""
        self._mk('m1', self.admin, issuing=[self.lijan], dtype='')
        self._mk('m2', self.admin, issuing=[self.lijan], dtype='مذكرة')
        r = self.client.get(reverse('dossier_detail', args=[self.lijan.pk]),
                            {'document_type': 'متفرقة'})
        nums = [bk.our_number for g in r.context['outgoing_groups'] for bk in g['books']]
        self.assertEqual(nums, ['m1'])

    def test_list_totals_aggregate(self):
        self._mk('t1', self.admin, issuing=[self.lijan])
        t = self.client.get(reverse('dossier_list'), UNIT_TAB).context['totals']
        self.assertGreaterEqual(t['departments'], 1)
        self.assertGreaterEqual(t['issued'], 1)


class DossierDefaultTabTests(DossierBaseSetup):
    """التبويبُ الافتراضيّ عقدٌ صريح لا أثرٌ جانبيّ."""

    def setUp(self):
        super().setUp()
        self.client.force_login(self.admin)
        self._mk('u1', self.admin, issuing=[self.lijan])

    def test_default_tab_is_external_parties(self):
        """الافتراضيُّ أوّلُ التبويبات كما سمّاها المالك: «جهات خارجية»."""
        from core.entity_kinds import EXTERNAL

        res = self.client.get(reverse('dossier_list'))

        self.assertEqual(res.context['kind'], EXTERNAL)

    def test_units_are_reachable_through_their_own_tab(self):
        """ما لا يظهر في الافتراضيّ ليس مفقوداً — له تبويبُه وعدّادُه."""
        res = self.client.get(reverse('dossier_list'), UNIT_TAB)
        names = {e.name for e in res.context['page_obj'].object_list}
        counts = {t['key']: t['count'] for t in res.context['tabs']}

        self.assertIn('وحدة اللجان', names)
        self.assertEqual(counts['unit'], 1)
