# conftest.py
# ===========
# إعداد pytest لمشروع LetterSys.
#
# ملاحظة: pytest-django غير مثبت — استخدم manage.py test لتشغيل الاختبارات:
#   python manage.py test --settings=lettersys.settings_test
#   python manage.py test core.tests_books_views --settings=lettersys.settings_test
#
# إذا أردت pytest، ثبّت pytest-django أولاً:
#   pip install pytest-django
#   ثم أضف pytest.ini مع: DJANGO_SETTINGS_MODULE = lettersys.settings_test

import django
import os

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'lettersys.settings_test')
os.environ.setdefault(
    'DJANGO_SECRET_KEY',
    'test-only-key-not-for-production-xR9kL2mPvQw7nR3eY8jHfTuZ6dAbC0sI4gN1oW5p'
)


def pytest_configure(config):
    """استدعاء pytest قبل بدء جمع الاختبارات."""
    django.setup()
