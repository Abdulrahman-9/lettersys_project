# -*- coding: utf-8 -*-
"""اختبارات واجهة الاستخراج الذكية (طبقة العرض):
- ودجة «آخر الكتب»: نطاق الوصول (created_by) + الترتيب (-created_at) + السقف + الغياب في التعديل.
- زر الإلغاء: بنية <button> + backTarget مُصلَّب + تتبّع dirty + beforeunload.
- بطاقتا P1 (quality-hero + needs_review) حاضرتان في وضع الإدخال.
"""
from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import timezone

from .models import Book

URL = "extraction-smart-desktop"


class RecentBooksWidgetTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser("a", "a@x.com", "pass1234")
        self.clerk = User.objects.create_user("c", "c@x.com", "pass1234")
        self.other = User.objects.create_user("o", "o@x.com", "pass1234")
        self.today = timezone.now().date()

    def _book(self, num, owner):
        return Book.objects.create(our_number=num, title="ك" + num, date=self.today, created_by=owner)

    def test_scope_regular_user_sees_only_own(self):
        self._book("c1", self.clerk)
        self._book("o1", self.other)
        self.client.force_login(self.clerk)
        nums = {b.our_number for b in self.client.get(reverse(URL)).context["recent_books"]}
        self.assertIn("c1", nums)
        self.assertNotIn("o1", nums)          # لا تسرّب كتب مستخدم آخر

    def test_scope_superuser_sees_all(self):
        self._book("c1", self.clerk)
        self._book("o1", self.other)
        self.client.force_login(self.admin)
        nums = {b.our_number for b in self.client.get(reverse(URL)).context["recent_books"]}
        self.assertTrue({"c1", "o1"} <= nums)

    def test_ordering_newest_registered_first(self):
        self.client.force_login(self.admin)
        self._book("old", self.admin)
        self._book("new", self.admin)
        rb = self.client.get(reverse(URL)).context["recent_books"]
        self.assertEqual(rb[0].our_number, "new")   # -created_at

    def test_capped_at_four(self):
        self.client.force_login(self.admin)
        for i in range(6):
            self._book("n%d" % i, self.admin)
        self.assertLessEqual(len(self.client.get(reverse(URL)).context["recent_books"]), 4)

    def test_absent_in_edit_mode(self):
        b = self._book("e1", self.admin)
        self.client.force_login(self.admin)
        rb = self.client.get(reverse(URL) + "?edit_pk=%d" % b.id).context["recent_books"]
        self.assertEqual(list(rb), [])


class CancelButtonStructureTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser("a", "a@x.com", "pass1234")
        self.client.force_login(self.admin)

    def test_button_and_guards_present(self):
        body = self.client.get(reverse(URL)).content.decode()
        self.assertIn('<button type="button" class="btn-action-neutral" id="cancelEditButton"', body)
        self.assertIn("bi bi-x-lg", body)
        self.assertNotIn("✕ إلغاء", body)
        self.assertIn("new URL(ref).origin === window.location.origin", body)   # backTarget مُصلَّب
        self.assertIn("__setExtractionBaseline", body)                          # تتبّع dirty
        self.assertIn("addEventListener('beforeunload'", body)                  # شبكة أمان


class ExtractionP1CardsTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser("a", "a@x.com", "pass1234")
        self.client.force_login(self.admin)

    def test_p1_cards_present_in_create_mode(self):
        body = self.client.get(reverse(URL)).content.decode()
        self.assertIn('id="qualityHero"', body)
        self.assertIn('id="needsReviewCard"', body)


class SmartExtractStreamTests(TestCase):
    """نقطة البثّ التدريجي: سطر NDJSON لكل مرحلة بحقولها المكتملة، ثم سطر نهائي."""

    def setUp(self):
        self.user = User.objects.create_user("streamer", "s@x.com", "pass1234")
        self.client.force_login(self.user)

    @staticmethod
    def _fake_process(path, on_progress=None, **kwargs):
        """يحاكي الأنبوب: يُعلن المراحل ويُمرّر لقطات متنامية كما يفعل _progress."""
        from core.extraction.pipeline import AIExtractionResult
        res = AIExtractionResult()
        if on_progress:
            on_progress("ocr", {})                                   # لا حقول بعد
            res.title, res.title_confidence = "موضوع تجريبي", 0.8
            on_progress("pattern_matching", {"title": res.title, "title_confidence": 0.8})
            res.issuing_entity_name, res.issuing_entity_confidence = "قسم الرقابة", 0.7
            on_progress("entity_matching", {"title": res.title, "title_confidence": 0.8,
                                            "issuing_entity": "قسم الرقابة"})
        res.status = "completed"
        res.overall_confidence = 0.75
        return res

    def _stream_lines(self):
        import json
        from django.core.files.uploadedfile import SimpleUploadedFile
        from unittest import mock
        with mock.patch("core.extraction.api.endpoints.AIExtractionService") as svc:
            svc.return_value.process_image.side_effect = self._fake_process
            resp = self.client.post(
                reverse("ai_smart_extract_stream"),
                data={"file": SimpleUploadedFile("a.png", b"\x89PNG\r\n\x1a\n" + b"0" * 64,
                                                 content_type="image/png")},
            )
            self.assertEqual(resp.status_code, 200)
            raw = b"".join(resp.streaming_content).decode("utf-8")
        return [json.loads(ln) for ln in raw.splitlines() if ln.strip()]

    def test_stream_emits_stages_with_growing_fields_then_done(self):
        events = self._stream_lines()
        stages = [e for e in events if e.get("type") == "stage"]
        self.assertGreaterEqual(len(stages), 3)
        # المراحل مُعنونة بالعربية للمستخدم (لا مفاتيح تقنية)
        self.assertEqual(stages[0]["label"], "قراءة النص")
        self.assertEqual(stages[0]["fields"], {})                    # لا شيء بعد
        # اللقطة تنمو: العنوان يصل قبل الجهة
        self.assertEqual(stages[1]["fields"]["title"], "موضوع تجريبي")
        self.assertNotIn("issuing_entity", stages[1]["fields"])
        self.assertEqual(stages[2]["fields"]["issuing_entity"], "قسم الرقابة")
        # السطر الأخير حصيلة كاملة
        done = events[-1]
        self.assertEqual(done["type"], "done")
        self.assertTrue(done["success"])
        self.assertEqual(done["title"], "موضوع تجريبي")

    def test_stream_reports_failure_as_error_line(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from unittest import mock
        import json
        with mock.patch("core.extraction.api.endpoints.AIExtractionService") as svc:
            svc.return_value.process_image.side_effect = RuntimeError("انفجار")
            resp = self.client.post(
                reverse("ai_smart_extract_stream"),
                data={"file": SimpleUploadedFile("a.png", b"\x89PNG\r\n\x1a\n" + b"0" * 64,
                                                 content_type="image/png")},
            )
            raw = b"".join(resp.streaming_content).decode("utf-8")
        last = json.loads(raw.splitlines()[-1])
        self.assertEqual(last["type"], "error")                       # فشل صادق لا صمت
        self.assertIn("انفجار", last["message"])

    def test_stream_rejects_unsupported_type(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        resp = self.client.post(
            reverse("ai_smart_extract_stream"),
            data={"file": SimpleUploadedFile("a.exe", b"MZ", content_type="application/x-msdownload")},
        )
        self.assertEqual(resp.status_code, 400)


class SmartDesktopEditGateTests(TestCase):
    """بوّابةُ **تعديل** كتابٍ قائم من الإدخال الذكيّ — `can_open_content` لا `is_staff`.

    الدَّينُ الذي يحرسه هذا الصفّ (T7.5‑2): كان الشرطُ نسخةً ثالثةً
    (`is_superuser or is_staff or created_by`) خارجَ `core/scoping.py`، فمسؤولُ
    الأرشفة — وهو **ليس staff** — يُدخل الكتابَ الجديدَ بلا مانع ثمّ يُمنع من
    تعديل كتابٍ من قسمه. والرمزُ **404 لا 403**: ممنوعٌ وغيرُ موجودٍ سواء.
    """

    @classmethod
    def setUpTestData(cls):
        from django.contrib.auth.models import Group
        from core.models import Department, UserProfile
        from core.roles import ARCHIVIST_GROUP_NAME

        cls.dept = Department.objects.create(name='قسم الإدخال الذكيّ', code='ذ.ق')
        cls.other = Department.objects.create(name='قسمٌ بعيد', code='ذ.ب')

        def member(name, dept, *, archivist=False):
            user = User.objects.create_user(name, name + '@x.co', 'pass1234')
            UserProfile.objects.update_or_create(user=user,
                                                 defaults={'department': dept})
            if archivist:
                user.groups.add(Group.objects.get_or_create(name=ARCHIVIST_GROUP_NAME)[0])
            return user

        cls.clerk = member('sd-clerk', cls.dept)
        cls.archivist = member('sd-arch', cls.dept, archivist=True)
        cls.stranger = member('sd-stranger', cls.other)

        cls.book = Book.objects.create(
            kind='incoming_external', title='كتابُ القسم', our_number='7100',
            department=cls.dept, created_by=cls.clerk)

    def _edit(self, user):
        self.client.force_login(user)
        return self.client.get(reverse(URL) + '?edit_pk=%d' % self.book.pk)

    def test_the_archivist_is_not_staff(self):
        """لولا هذا لكان الاختبارُ التالي يمرّ بالبابِ القديم لا بالجديد."""
        self.assertFalse(self.archivist.is_staff)
        self.assertFalse(self.archivist.is_superuser)

    def test_the_archivist_opens_the_edit_form_of_an_existing_book(self):
        res = self._edit(self.archivist)

        self.assertEqual(res.status_code, 200)
        self.assertIn('"pk": %d' % self.book.pk, res.context['edit_book_json'])

    def test_a_stranger_gets_404_not_403(self):
        self.assertEqual(self._edit(self.stranger).status_code, 404)

    def test_a_missing_book_is_404_too(self):
        """لا عرّافَ يفصل «ليس لك» عن «لا وجود له»."""
        self.client.force_login(self.archivist)

        res = self.client.get(reverse(URL) + '?edit_pk=%d' % (self.book.pk + 9999))

        self.assertEqual(res.status_code, 404)

    def test_the_recent_widget_shows_the_department_not_only_my_own(self):
        """النطاقُ صار نطاقَ القائمة — الأرشيفيُّ كان محبوساً في كتبه هو."""
        self.client.force_login(self.archivist)

        nums = {b.our_number for b in self.client.get(reverse(URL)).context['recent_books']}

        self.assertIn('7100', nums)

    def test_the_recent_widget_stubs_a_secret_title(self):
        """الصفُّ يُرى والمظروفُ مغلق — ولا يتحوّل توسيعُ النطاق إلى تسريب."""
        from core.models import UserProfile
        from core.scoping import STUB_TITLE

        Book.objects.create(kind='incoming_external', title='مناقصةٌ سرّيّة',
                            our_number='7101', secret_level='secret',
                            department=self.dept, created_by=self.clerk)
        plain = User.objects.create_user('sd-plain', 'p@x.co', 'pass1234')
        UserProfile.objects.update_or_create(user=plain,
                                             defaults={'department': self.dept})
        self.client.force_login(plain)

        rows = {b.our_number: b.title
                for b in self.client.get(reverse(URL)).context['recent_books']}

        self.assertEqual(rows.get('7101'), STUB_TITLE)
        self.assertEqual(rows.get('7100'), 'كتابُ القسم')


class StaleExtractionGuardTests(SimpleTestCase):
    """بلاغُ المالك 2026‑09‑15: نتيجةُ استخراجٍ لملفٍّ أُلغي كانت تُطبَّق على النموذج
    الجديد، و«تفريغُ الحقول» يمسح ثمّ يعود البثُّ فيملأ. الحارسُ: **رمزُ جيل**."""

    SRC = 'static/extraction_smart.js'

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        with open(cls.SRC, encoding='utf-8') as fh:
            cls.src = fh.read()

    def test_a_generation_token_exists_and_is_checked_before_every_apply(self):
        self.assertIn('_bumpExtractGen()', self.src)
        self.assertIn('_isStaleGen(gen)', self.src)
        # يُحجز عند بدء الاستخراج ويُمرَّر إلى البثّ
        self.assertIn('const gen = this._bumpExtractGen();', self.src)
        self.assertIn('this._streamExtract(gen)', self.src)
        self.assertIn('async _streamExtract(gen) {', self.src)

    def test_clearing_the_file_or_the_form_cancels_the_running_extraction(self):
        for fn in ('clearFile() {', 'clearForm() {'):
            i = self.src.index(fn)
            body = self.src[i:i + 900]
            self.assertIn('_cancelRunningExtraction()', body,
                          f'{fn} لا يوقف الاستخراجَ الجاري — سيعود البثُّ فيملأ الحقول')

    def test_cancelling_aborts_the_stream_and_resets_extraction_state(self):
        i = self.src.index('_cancelRunningExtraction() {')
        body = self.src[i:i + 1200]
        for marker in ('_extractAbort?.abort()', '_streamFilled = new Set()',
                       '_hideExtractionOverlay', 'scanToken = null', 'SubjectLocate?.hide'):
            self.assertIn(marker, body, f'الإلغاء لا يشمل: {marker}')

    def test_a_late_result_is_dropped_and_announced_not_swallowed(self):
        i = self.src.index('if (this._isStaleGen(gen)) {\n            // وصلت نتيجةُ ملفٍّ سابق')
        body = self.src[i:i + 500]
        self.assertIn('أُهملت', body)
        self.assertIn('return null;', body)


class ExtractionSaveReadinessSourceTests(SimpleTestCase):
    """حواجز بلاغ التراخيص 2026-10-08: القيم الظاهرة قابلة للحفظ ولا يُغلق الزر."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        with open('static/extraction_smart.js', encoding='utf-8') as fh:
            cls.js = fh.read()
        with open('templates/core/extraction_smart_desktop.html', encoding='utf-8') as fh:
            cls.template = fh.read()
        with open('static/extraction_smart.css', encoding='utf-8') as fh:
            cls.css = fh.read()

    def test_pending_entity_text_is_flushed_before_required_validation(self):
        save_start = self.js.index('    async saveBook() {')
        save_end = self.js.index('    /** يحلّ أي نصّ جهة', save_start)
        save = self.js[save_start:save_end]
        self.assertLess(
            save.index('await this._flushPendingEntities();'),
            save.index('const requiredFields ='),
        )

    def test_entity_validation_accepts_tags_after_the_input_is_cleared(self):
        start = self.js.index('    validateFieldValue(fieldId, value) {')
        body = self.js[start:self.js.index('\n    }\n', start)]
        self.assertIn("entityCount('issuing') > 0", body)
        self.assertIn("entityCount('receiving') > 0", body)

    def test_incomplete_form_keeps_save_enabled_for_inline_validation(self):
        self.assertNotIn('saveBtn.disabled = true', self.template)
        self.assertIn('saveBtn.disabled = false', self.template)

    def test_scan_messages_never_fall_back_to_native_alert(self):
        self.assertNotIn('alert(', self.js)
        self.assertIn('showExtractionNotice(', self.js)

    def test_extraction_sidebar_mini_rule_overrides_compact_desktop_width(self):
        self.assertIn(
            'body.app-shell-body .app-shell.sidebar-mini .app-sidebar',
            self.css,
        )


class ExtractionClosureSourceGuardTests(SimpleTestCase):
    """دفعةُ إغلاق صفحة الاستخراج (مذكّرة فيبل 10، موافقةُ المالك 2026‑09‑29) — حرّاسٌ على المصدر
    (لا مُشغّلَ اختباراتٍ لـJS في المشروع): نيلسن 1 و2 و3 و11."""

    SRC = 'static/extraction_smart.js'
    LOCATE = 'static/js/subject_locate.js'

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        with open(cls.SRC, encoding='utf-8') as fh:
            cls.src = fh.read()
        with open(cls.LOCATE, encoding='utf-8') as fh:
            cls.locate = fh.read()

    def _method(self, header):
        i = self.src.index(header)
        j = self.src.index('\n    }\n', i)
        return self.src[i:j]

    def test_escape_no_longer_clears_the_form(self):
        """نيلسن 1: Escape مفتاحُ إغلاق القوائم — كان يمسح الكتابَ ويُلغي الرقمَ المحجوز."""
        self.assertEqual(self.src.count('this.clearForm();'), 1)          # زرُّ «تفريغ الحقول» وحده
        i = self.src.index('this.clearForm();')
        self.assertIn('__isExtractionDirty', self.src[i - 400:i])          # بتأكيدٍ حين يوجد إدخال

    def test_clear_keeps_our_reservation_and_the_current_tab(self):
        body = self._method('    clearForm() {')
        self.assertNotIn('voidReservation', body)
        self.assertNotIn('applyInitialContext', body)
        self.assertIn("field.id === 'bookNumber' && field.dataset.reservationId", body)
        self.assertIn('this.syncKindUI(currentKind)', body)

    def test_previous_suggestions_are_reset_on_every_clear_path(self):
        """نيلسن 2: موضعٌ واحد يُفرغ سطوحَ الاقتراح، ويستدعيه التفريغُ والحذفُ والحفظ."""
        for header in ('    clearForm() {', '    clearFile() {', '    smartClearAndStay(kind) {'):
            self.assertIn('this.resetSuggestionSurfaces()', self._method(header), header)
        reset = self._method('    resetSuggestionSurfaces() {')
        for part in ('senderDateCrop', '_hideSenderDateSuggestion()', '.entity-candidates', 'titleSuggest',
                     'SubjectLocate.hide()'):
            self.assertIn(part, reset)

    def test_final_payload_never_overwrites_the_clerks_own_value(self):
        """نيلسن 3: ما كتبه الكاتبُ أو أكّده أثناء الاستخراج يبقى — في البثّ وفي حمولة done."""
        self.assertIn('if (input && !_clerkOwnsField(input))', self._method('    applyExtractionResult(data) {'))
        self.assertIn('if (_clerkOwnsField(el))', self._method('    _applyPartialFields(fields) {'))

    def test_focus_is_not_stolen_and_uses_the_servers_confidence_keys(self):
        focus = self._method('    _focusFirstReviewField(data) {')
        self.assertIn('document.activeElement', focus)
        self.assertIn("senderNumber: 'sender_number_confidence'", focus)
        self.assertNotIn('_confidence`]', focus)                            # المفتاحُ المركّب الخاطئ

    def test_use_it_in_where_is_the_subject_records_confirmed_not_typed(self):
        """نيلسن 11: نصٌّ آليٌّ أكّده الكاتبُ بنقرة لا يُسجَّل `typed` (حلقةُ التسميم الذاتيّ)."""
        i = self.locate.index('function applyText()')
        body = self.locate[i:self.locate.index('\n  }\n', i)]
        self.assertIn('window.codeFill(fire)', body)
        self.assertIn("els.title.dataset.provenance = 'confirmed'", body)

    # ── ما كشفه التحقّقُ العدائيّ للدفعة (تراجعاتٌ من صنعها، أُصلحت قبل التسليم) ──

    def _fn(self, header):
        i = self.src.index(header)
        return self.src[i:self.src.index('\n}\n', i)]

    def test_entity_provenance_does_not_leak_into_the_next_book(self):
        """C1: وسمُ `typed` على حقلَي الجهة (tag-text-input لا .form-control-smart) كان يبقى بعد
        الحفظ/التفريغ فتتخطّى بوّابةُ نيلسن 3 وسمَ `autofilled` بينما تُضاف جهةُ الآلة ⟵ تُحفظ
        `typed` وتتعلّم ذاكرةُ الترويسة من مخرجها هي."""
        for header in ('    clearForm() {', '    smartClearAndStay(kind) {'):
            self.assertIn('this._resetEntityProvenance()', self._method(header), header)
        reset = self._method('    _resetEntityProvenance() {')
        for part in ("'issuingEntity'", "'receivingEntity'", 'resetCaptureProvenance('):
            self.assertIn(part, reset)

    def test_a_new_document_releases_the_old_documents_confirmations(self):
        """C3: بعد حذف الملف كانت تأكيداتُ قراءاته تحجب قيمَ الملف الجديد بصمت (خلطُ مستندين،
        بلاغ 09‑15). `confirmed` ينزل إلى `autofilled` — لا حذفُ الوسم (فراغُه يُقرأ `typed`)."""
        release = self._fn('function _releaseDocBoundOwnership() {')
        self.assertIn('=== PROV_CONFIRMED', release)
        self.assertIn('= PROV_AUTOFILLED', release)
        self.assertNotIn('delete ', release)
        self.assertNotIn('PROV_TYPED', release)                            # يدُ الكاتب تبقى ملكاً
        self.assertIn('_releaseDocBoundOwnership();', self._method('    clearFile() {'))
        self.assertIn('_releaseDocBoundOwnership();', self._method('    processFile(file) {'))
        i = self.src.index('this._loadScanToken(ud.token')
        self.assertIn('_releaseDocBoundOwnership();', self.src[i - 200:i])   # مسحٌ جديد لا إلحاق

    def test_det2_card_never_shows_the_box_score_as_a_reading_confidence(self):
        """F4: ثقةُ صندوق الكاشف تموضعٌ لا قراءة — كانت تُعرض «87%» تحت «قراءةٌ ضعيفة»."""
        body = self._fn('function applyTitleSuggestion(data) {')
        self.assertIn("const boxOnly = sug.source === 'det2_crop';", body)
        self.assertIn('badge.hidden = boxOnly;', body)

    def test_scan_path_keeps_what_the_clerk_typed_during_the_scan(self):
        """C4 (قرارُ المالك 2026‑09‑29): مسارُ الماسح (`_fillExtractionFields`) كان الوحيدَ من مسارات
        الملء الثلاثة الذي يكتب فوق ما كتبته الكاتبةُ أثناء المسح — ثمّ يسمه `autofilled`."""
        body = self._method('    _fillExtractionFields(data) {')
        self.assertIn("val !== '' && !_clerkOwnsField(el)", body)
        self.assertIn('issuingInput && !_clerkOwnsField(issuingInput)', body)
        self.assertIn('receivingInput && !_clerkOwnsField(receivingInput)', body)
        self.assertIn("!_clerkOwnsField(document.getElementById(fid))", body)   # ولا حافّةُ ثقةٍ آليّة فوقها

    def test_ambiguous_choices_never_offer_a_date_after_the_entry_date(self):
        """C2: «غامض» يعني أنّ المرشّحَين خارج النافذة، فقد يقع أحدُهما بعد تاريخ القيد — ونقرةٌ
        عليه تصير `confirmed` في ذهب التدريب. الواجهةُ تُسقطه بتاريخ القيد الذي في الحقل الآن."""
        body = self._fn('function applySenderDateSuggestion(data) {')
        self.assertIn('const g = _senderDateGap(iso); return g === null || g >= 0;', body)
