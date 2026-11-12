# -*- coding: utf-8 -*-
"""مصفوفةُ الأدوار — **صورةٌ مقيسة** لما يفعله كلُّ حسابٍ في شجرةٍ كشجرة قسم المتابعة.

قراراتُ المالك للمستويات 0–5 (2026‑11‑02) تتنزّل شرائح؛ وكلُّ شريحةٍ تقلب صفوفَها هنا
**عمداً وفي الإيداع نفسه**، فالفرقُ في هذا الملفّ هو ما تغيّر في الصلاحيّات، صفّاً صفّاً.
صفٌّ تغيّر بلا قصدٍ يُسقط هذا الاختبار — وهو حارسُ الدفعة كلِّها.

مصطلحاتُ الكتاب: V يرى · O يفتح · E يعدّل · A يتصرّف · S يوقّع · - لا شيء.
"""
import importlib

from django.apps import apps as django_apps
from django.contrib.auth.models import Group, User
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from core import scoping
from core.admin_service import create_department
from core.models import Book, BookReferral, BookSequence, Department, Notification, UserProfile
from core.referral_service import _notify
from core.roles import (ARCHIVE_ALL_GROUP_NAME, ARCHIVIST_GROUP_NAME, CONTROLLER_GROUP_NAME,
                        ENTRY_GROUP_NAME, EXECUTOR_GROUP_NAME, ensure_role_groups)
from core.signature_service import can_sign

PERSONAS = ('admin', 'prod_admin', 'head_office', 'head_q', 'mail_q', 'arch_q', 'entry_q', 'read_q',
            'head_s', 'entry_s', 'head_w', 'entry_w', 'exec_w', 'read_w', 'mail_far')
PAGES = ('dashboard', 'desk_mine', 'desk_board', 'desk_handover', 'desk_ledger', 'book_unified',
         'extraction-smart-desktop', 'dossier_list', 'reports', 'audit_log', 'admin_panel',
         'trash_list', 'mail_inbox', 'mail_sent', 'mail_compose', 'mail_templates', 'mail_settings',
         'entity_list', 'settings_hub', 'sequence_settings', 'backup_database', 'workstation_board',
         'notifications', 'system_roles')
GATES = ('can_operate_mail', 'can_send_book_mail', 'can_enter_book', 'can_use_entry_desk', 'can_reserve_number', 'can_add_entity',
         'can_use_desk', 'can_archive', 'can_manage_mail', 'can_view_audit',
         'can_view_reports', 'can_manage_departments', 'can_manage_accounts', 'can_manage_system')


def build_world():
    """مكتب ⟵ قسم (يمسك السجلّ) ⟵ شعبة ⟵ وحدتان، وقسمٌ آخر خارج الشجرة."""
    ensure_role_groups()
    Group.objects.get_or_create(name=ARCHIVE_ALL_GROUP_NAME)
    Group.objects.get_or_create(name=EXECUTOR_GROUP_NAME)

    def unit(name, code, parent=None, register=True):
        return Department.objects.create(name=name, code=code, parent=parent, holds_register=register)

    office = unit('مصفوفة مكتب', 'M-O')
    qsm = unit('مصفوفة قسم', 'M-Q', office)
    shb = unit('مصفوفة شعبة', 'M-S', qsm, register=False)
    wht = unit('مصفوفة وحدة', 'M-W', shb, register=False)
    wh2 = unit('مصفوفة وحدة أخت', 'M-W2', shb, register=False)
    far = unit('مصفوفة قسم بعيد', 'M-F')

    def person(name, dept=None, head=False, groups=(), su=False):
        user = User.objects.create_user('m-' + name, password='matrix-pass-123456',
                                        is_superuser=su, is_staff=su)
        UserProfile.objects.update_or_create(
            user=user, defaults={'department': dept, 'is_department_head': head})
        for group in groups:
            user.groups.add(Group.objects.get(name=group))
        return User.objects.get(pk=user.pk)

    people = {
        'admin': person('admin', su=True),
        # شكلُ حساب admin في الإنتاج: كلُّ شيءٍ معاً وبلا قسم
        'prod_admin': person('prod', head=True, su=True, groups=(
            ENTRY_GROUP_NAME, CONTROLLER_GROUP_NAME, ARCHIVIST_GROUP_NAME, ARCHIVE_ALL_GROUP_NAME)),
        'head_office': person('head-o', office, head=True),
        'head_q': person('head-q', qsm, head=True),
        'mail_q': person('mail-q', qsm, groups=(CONTROLLER_GROUP_NAME,)),
        'arch_q': person('arch-q', qsm, groups=(ARCHIVIST_GROUP_NAME,)),
        'entry_q': person('entry-q', qsm, groups=(ENTRY_GROUP_NAME,)),
        'read_q': person('read-q', qsm),
        'head_s': person('head-s', shb, head=True),
        'entry_s': person('entry-s', shb, groups=(ENTRY_GROUP_NAME,)),
        'head_w': person('head-w', wht, head=True),
        'entry_w': person('entry-w', wht, groups=(ENTRY_GROUP_NAME,)),
        'exec_w': person('exec-w', wht, groups=(EXECUTOR_GROUP_NAME,)),
        'read_w': person('read-w', wht),
        'mail_far': person('mail-f', far, groups=(CONTROLLER_GROUP_NAME,)),
    }
    today = timezone.localdate()

    def book(number, dept, secret='normal'):
        return Book.objects.create(kind='incoming_internal', title='كتاب ' + number, our_number=number,
                                   created_by=people['admin'], department=dept, date=today,
                                   secret_level=secret)

    def referred(number, to, secret='normal'):
        made = book(number, qsm, secret)
        BookReferral.objects.create(book=made, from_department=qsm, to_department=to,
                                    created_by=people['admin'], status='sent')
        return made

    books = {
        'normal_q': book('9001', qsm), 'secret_q': book('9002', qsm, 'secret'),
        'normal_s': book('9003', shb), 'secret_s': book('9004', shb, 'secret'),
        'normal_w': book('9005', wht), 'secret_w': book('9006', wht, 'secret'),
        'normal_w2': book('9007', wh2), 'normal_far': book('9008', far),
        'referred_w': referred('9009', wht), 'referred_secret_w': referred('9010', wht, 'secret'),
        'referred_far': referred('9011', far),
    }
    return people, books


def page_row(name, people):
    url = reverse(name)
    cells = []
    for key in PERSONAS:
        client = Client(raise_request_exception=False)
        client.force_login(people[key])
        cells.append(str(client.get(url).status_code))
    return ' '.join(cells)


def gate_row(gate, people):
    return ' '.join('1' if getattr(scoping, gate)(people[key]) else '0' for key in PERSONAS)


def book_row(book, people):
    cells = []
    for key in PERSONAS:
        user = people[key]
        cell = ''.join(letter for letter, allowed in (
            ('V', scoping.can_view_book(book, user)),
            ('O', scoping.can_open_content(book, user)),
            ('E', scoping.can_edit_book(book, user)),
            ('A', scoping.can_link_book(book, user)),
            ('S', can_sign(user, book))) if allowed)
        cells.append(cell or '-')
    return ' '.join(cells)


# ── المصفوفةُ المقيسة ── (ترتيبُ الخانات = PERSONAS)
EXPECTED_PAGES = {
    'dashboard':                '200 200 200 200 200 200 200 200 200 200 200 200 200 200 200',
    'desk_mine':                '403 403 403 403 403 403 403 403 200 403 200 403 403 403 403',
    'desk_board':               '200 200 200 200 200 403 403 403 403 403 403 403 200 403 200',
    'desk_handover':            '200 200 200 200 200 403 403 403 403 403 403 403 403 403 200',
    'desk_ledger':              '200 200 200 200 200 403 403 403 403 403 403 403 403 403 200',
    'book_unified':             '200 200 200 200 200 200 200 200 200 200 200 200 200 200 200',
    'extraction-smart-desktop': '200 200 200 200 200 200 200 403 403 200 403 200 403 403 200',
    'dossier_list':             '200 200 200 200 200 200 200 200 200 200 200 200 200 200 200',
    'reports':                  '200 200 200 200 404 404 404 404 200 404 200 404 404 404 404',
    'audit_log':                '200 200 200 200 403 403 403 403 200 403 200 403 403 403 403',
    'admin_panel':              '200 200 200 200 403 403 403 403 200 403 200 403 403 403 403',
    'trash_list':               '200 200 200 200 200 200 403 403 403 403 403 403 403 403 200',
    'mail_inbox':               '200 200 200 200 200 200 200 200 200 200 200 200 200 200 200',
    'mail_sent':                '200 200 200 200 200 200 200 200 200 200 200 200 200 200 200',
    'mail_compose':             '200 200 403 403 200 403 403 403 403 403 403 403 403 403 200',
    'mail_templates':           '200 200 403 403 200 403 403 403 403 403 403 403 403 403 200',
    'mail_settings':            '200 200 403 403 403 403 403 403 403 403 403 403 403 403 403',
    'entity_list':              '200 200 403 403 403 403 403 403 403 403 403 403 403 403 403',
    'settings_hub':             '200 200 403 403 403 403 403 403 403 403 403 403 403 403 403',
    'sequence_settings':        '200 200 403 403 403 403 403 403 403 403 403 403 403 403 403',
    'backup_database':          '200 200 403 403 403 403 403 403 403 403 403 403 403 403 403',
    'workstation_board':        '200 200 403 403 403 403 403 403 403 403 403 403 403 403 403',
    'notifications':            '200 200 200 200 200 200 200 200 200 200 200 200 200 200 200',
    'system_roles':             '200 200 403 403 403 403 403 403 403 403 403 403 403 403 403',
}
EXPECTED_GATES = {
    'can_operate_mail':       '1 1 0 0 1 0 0 0 0 0 0 0 0 0 1',
    'can_send_book_mail':     '1 1 0 0 1 0 0 0 0 0 0 0 0 0 1',
    'can_enter_book':         '1 1 1 1 1 1 1 0 0 1 0 1 0 0 1',
    'can_use_entry_desk':     '1 1 1 1 1 1 1 0 0 1 0 1 0 0 1',
    'can_reserve_number':     '1 1 1 1 1 1 1 0 0 1 0 1 0 0 1',
    'can_add_entity':         '1 1 1 1 1 1 1 0 0 1 0 1 0 0 1',
    'can_use_desk':           '1 1 1 1 1 0 0 0 0 0 0 0 1 0 1',
    'can_archive':            '1 1 0 0 0 1 0 0 0 0 0 0 0 0 0',
    'can_manage_mail':        '1 1 0 0 0 0 0 0 0 0 0 0 0 0 0',
    'can_view_audit':         '1 1 1 1 0 0 0 0 1 0 1 0 0 0 0',
    'can_view_reports':       '1 1 1 1 0 0 0 0 1 0 1 0 0 0 0',
    'can_manage_departments': '1 1 1 1 0 0 0 0 1 0 1 0 0 0 0',
    'can_manage_accounts':    '1 1 0 0 0 0 0 0 0 0 0 0 0 0 0',
    'can_manage_system':      '1 1 0 0 0 0 0 0 0 0 0 0 0 0 0',
}
EXPECTED_BOOKS = {
    'normal_q':          'VOEAS VOEAS VOEA VOEAS VOEA VOEA VOEA VO - - - - - - -',
    'secret_q':          'VOEAS VOEAS V VOEAS VOEA VOEA V V - - - - - - -',
    'normal_s':          'VOEAS VOEAS VOEA VOEA VOEA VOEA VOEA VO VOS VOEA - - - - -',
    'secret_s':          'VOEAS VOEAS V V V V V V V V - - - - -',
    'normal_w':          'VOEAS VOEAS VOEA VOEA VOEA VOEA VOEA VO VO VOEA VOS VOEA VO VO -',
    'secret_w':          'VOEAS VOEAS V V V V V V V V V V V V -',
    'normal_w2':         'VOEAS VOEAS VOEA VOEA VOEA VOEA VOEA VO VO VOEA - - - - -',
    'normal_far':        'VOEAS VOEAS - - - - - - - - - - - - VOEA',
    'referred_w':        'VOEAS VOEAS VOEA VOEAS VOEA VOEA VOEA VO VO VOA VO VOA VO VO -',
    'referred_secret_w': 'VOEAS VOEAS V VOEAS VOEA VOEA V V V V V V V V -',
    'referred_far':      'VOEAS VOEAS VOEA VOEAS VOEA VOEA VOEA VO - - - - - - VOA',
}


class RoleMatrixTests(TestCase):
    maxDiff = None

    @classmethod
    def setUpTestData(cls):
        cls.people, cls.books = build_world()

    def test_every_page_answers_every_persona_as_recorded(self):
        for name in PAGES:
            with self.subTest(page=name):
                self.assertEqual(page_row(name, self.people), EXPECTED_PAGES[name])

    def test_every_gate_answers_every_persona_as_recorded(self):
        for gate in GATES:
            with self.subTest(gate=gate):
                self.assertEqual(gate_row(gate, self.people), EXPECTED_GATES[gate])

    def test_every_book_answers_every_persona_as_recorded(self):
        for key, book in self.books.items():
            with self.subTest(book=key):
                self.assertEqual(book_row(book, self.people), EXPECTED_BOOKS[key])


class HoldsRegisterTests(TestCase):
    """الوحدةُ غيرُ السجلّ — البذرُ لا يُسقط السجلَّ عمّن له كتبٌ أو عدّادٌ استُعمل."""

    def _seed(self):
        migration = importlib.import_module('core.migrations.0089_department_holds_register')
        migration.seed(django_apps, None)

    def _unit(self, name, code, parent=None):
        return Department.objects.create(name=name, code=code, parent=parent)

    def test_the_seed_touches_only_empty_sections_and_units_under_a_parent(self):
        root = self._unit('بذر قسم', 'B-Q')
        child_section = self._unit('شعبة بذر', 'B-S', root)
        self._unit('وحدة بذر', 'B-W', child_section)
        self._unit('شعبة بذر جذر', 'B-R')          # جذر: يبقى ماسكاً
        self._unit('قسم بذر تابع', 'B-D', root)       # «قسم» وله أب: يبقى ماسكاً
        with_book = self._unit('وحدة بذر بكتب', 'B-K', root)
        owner = User.objects.create_user('m-seed', password='matrix-pass-123456')
        Book.objects.create(kind='incoming_internal', title='ك', our_number='1', department=with_book,
                            created_by=owner, date=timezone.localdate())
        with_counter = self._unit('وحدة بذر بعدّاد', 'B-C', root)
        BookSequence.objects.create(kind='incoming_internal', department=with_counter,
                                    next_number=2, year=2026)
        unused_counter = self._unit('وحدة بذر بعدّاد فارغ', 'B-U', root)
        BookSequence.objects.create(kind='incoming_internal', department=unused_counter,
                                    next_number=1, year=2026)
        self._seed()
        holds = dict(Department.objects.filter(code__startswith='B-').values_list('code', 'holds_register'))
        self.assertEqual(holds, {
            'B-Q': True, 'B-S': False, 'B-W': False, 'B-R': True, 'B-D': True,
            'B-K': True, 'B-C': True, 'B-U': False,
        })

    def test_the_seed_creates_the_executor_group(self):
        Group.objects.filter(name=EXECUTOR_GROUP_NAME).delete()
        self._seed()
        self.assertTrue(Group.objects.filter(name=EXECUTOR_GROUP_NAME).exists())

    def test_a_new_department_gets_the_default(self):
        admin = User.objects.create_superuser('m-new', 'n@x.co', 'matrix-pass-123456')
        qsm = create_department(name='قسم جديد للمصفوفة', code='N-Q', by=admin)
        section = create_department(name='شعبة جديدة للمصفوفة', code='N-S', parent=qsm, by=admin)
        unit = create_department(name='وحدة جديدة للمصفوفة', code='N-W', parent=section, by=admin)
        lone = create_department(name='شعبة جذر جديدة', code='N-R', by=admin)
        self.assertEqual((qsm.holds_register, section.holds_register, unit.holds_register, lone.holds_register),
                         (True, False, False, True))


class SecretTitleStaysOutOfNotificationsTests(TestCase):
    """التنبيهُ يصل كلَّ موظّفي الوحدة — فعنوانُ السرّيّ لا يدخله."""

    @classmethod
    def setUpTestData(cls):
        cls.unit = Department.objects.create(name='وحدة تنبيه', code='T-W')
        cls.sender = User.objects.create_user('t-sender', password='matrix-pass-123456')
        cls.member = User.objects.create_user('t-member', password='matrix-pass-123456')
        UserProfile.objects.update_or_create(user=cls.member, defaults={'department': cls.unit})

    def _notify(self, secret):
        book = Book.objects.create(kind='incoming_internal', title='عنوانٌ لا يُكشف', date=timezone.localdate(),
                                   created_by=self.sender, secret_level=secret,
                                   our_number='7711' if secret == 'secret' else '7712')
        referral = BookReferral.objects.create(book=book, from_department=self.unit, to_department=self.unit,
                                               created_by=self.sender, status='sent')
        _notify([referral], book, self.sender)
        return Notification.objects.filter(user=self.member).latest('pk').message

    def test_a_secret_title_is_masked(self):
        self.assertEqual(self._notify('secret'), scoping.STUB_TITLE)

    def test_a_normal_title_is_kept(self):
        self.assertEqual(self._notify('normal'), 'عنوانٌ لا يُكشف')
