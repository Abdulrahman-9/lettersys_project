# Temporary preview settings (deleted after the Playwright review).
from .settings_test import *  # noqa

import os as _os

DEBUG = True
ALLOWED_HOSTS = ['127.0.0.1', 'localhost']
DATABASES = {'default': {
    'ENGINE': 'django.db.backends.sqlite3',
    'NAME': _os.path.join(_os.environ.get('TEMP', '.'), 'lettersys_preview_lens.sqlite3'),
}}
