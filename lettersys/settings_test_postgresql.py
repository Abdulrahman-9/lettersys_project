"""Opt-in PostgreSQL integration tests, with an explicit disposable database."""

import os
import re
from copy import deepcopy

from lettersys.settings import DATABASES as _runtime_databases
from lettersys.settings_test import *  # noqa: F401, F403

_test_name = os.environ.get("LETTERSYS_PG_TEST_DB", "")
if (
    not re.fullmatch(r"test_lettersys_[a-z0-9_]{1,40}", _test_name)
    or _test_name == _runtime_databases["default"]["NAME"]
):
    raise RuntimeError(
        "LETTERSYS_PG_TEST_DB must name a disposable database matching "
        "test_lettersys_[a-z0-9_]{1,40}, distinct from the runtime database."
    )

DATABASES = {"default": deepcopy(_runtime_databases["default"])}
DATABASES["default"]["CONN_MAX_AGE"] = 0
DATABASES["default"]["TEST"] = {"NAME": _test_name}
AI_PRELOAD_OCR = False
