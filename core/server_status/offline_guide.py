"""نسخةُ «دليل التشغيل والمشكلات» المحفوظة على القرص — تفتحها «لوحة التشغيل» حين يتوقّف النظام.

الكتابةُ هنا وحدها، ولها كاتبان: ``export_server_guide`` مع كلّ نشر، و«حالة الخادم» بعد حفظ جهة التبليغ
(وإلّا بقي في النسخة المحفوظة اسمٌ قديم حتّى النشر القادم — فيبل 11-22).
"""
import os
import tempfile
from pathlib import Path

from django.conf import settings
from django.template.loader import render_to_string
from django.utils import timezone

from .checks import format_when, notify_contact


def write_offline_guide(official_url, out=None):
    """يكتب الدليلَ كاملاً أو لا يكتب شيئاً، ويعيد مسارَه؛ و``OSError`` لمن يستدعيه.

    ``official_url`` رابطُ الموظّفين في نصّه وأصلُ روابطه: يُفتح الملفّ من القرص، فبلا رابطٍ تصير روابطُه
    ‎file:///D:/books/…‎ ميّتة (الحارسُ عند المستدعي). ملفٌّ مؤقّتٌ فريدٌ في المجلّد نفسه ثمّ ``replace``:
    اللوحةُ لا تفتح نصفَ ملفّ، والنشرُ والحفظُ معاً لا يتشاركان اسماً مؤقّتاً واحداً."""
    official = official_url.rstrip('/')
    out = Path(out or settings.SERVER_GUIDE_EXPORT_PATH)
    html = render_to_string('core/server_status/guide_offline.html', {
        'official_url': official, 'base_url': official, **notify_contact(),
        'generated_at': format_when(timezone.now()),
    })
    out.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=out.parent, prefix=out.name + '.', suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            handle.write(html)
        os.replace(tmp, out)
    finally:
        Path(tmp).unlink(missing_ok=True)     # بعد replace لا شيء؛ وقبله لا يبقى مؤقّتٌ يتيمٌ بجوار الدليل
    return out
