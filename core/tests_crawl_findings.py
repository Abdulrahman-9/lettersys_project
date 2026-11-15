"""ما كشفته جولةُ الألوان الشاملة (11-15) من أعطابٍ غير لونيّة — كلٌّ بحارسه.

١. **«جهةٌ جديدة» و«تعديلُ جهة» يسقطان 500** حين يُفتحان بلا ‎?next=‎ — ورابطُ «جهة جديدة» في قائمة الجهات
   نفسُه بلا next: ‎request.GET.next‎ وسيطاً لمرشِّح ‎default‎ يرفع ‎VariableDoesNotExist‎ (لا يُطوى إلى فراغ).
"""
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from core.models import Entity


class EntityFormOpensWithoutNextTests(TestCase):

    def setUp(self):
        self.client.force_login(User.objects.create_superuser('crawl-entity', password='pw-crawl-1115'))
        self.entity = Entity.objects.create(name='جهةٌ لجولة الألوان')

    def test_create_and_edit_open_without_next(self):
        for url in (reverse('entity_create'), reverse('entity_edit', args=[self.entity.pk])):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_next_is_still_carried_when_given(self):
        r = self.client.get(reverse('entity_create') + '?next=/books/entities/')
        self.assertContains(r, 'name="next" value="/books/entities/"')
