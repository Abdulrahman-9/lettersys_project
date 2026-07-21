# -*- coding: utf-8 -*-
"""اختبارات واجهة الاستخراج الذكية (طبقة العرض):
- ودجة «آخر الكتب»: نطاق الوصول (created_by) + الترتيب (-created_at) + السقف + الغياب في التعديل.
- زر الإلغاء: بنية <button> + backTarget مُصلَّب + تتبّع dirty + beforeunload.
- بطاقتا P1 (quality-hero + needs_review) حاضرتان في وضع الإدخال.
"""
from django.contrib.auth.models import User
from django.test import TestCase
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
