"""يكتب نسخةً مستقلّة من «دليل التشغيل والمشكلات» تفتحها لوحةُ التشغيل من القرص حين يتوقّف النظام.

الدليلُ نصٌّ واحد (``core/server_status/_guide_body.html``) يُضمَّن في صفحة التطبيق وهنا؛ فيُشغَّل هذا
الأمرُ مع كلّ نشرٍ كي لا تبقى النسخةُ المحفوظة على نصٍّ قديم. الكتابةُ في ``core.server_status.offline_guide``.
"""
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from core.server_status.offline_guide import write_offline_guide


class Command(BaseCommand):
    help = 'يكتب نسخةً مستقلّة من دليل التشغيل لتفتحها لوحةُ التشغيل حين يتوقّف النظام.'

    def add_arguments(self, parser):
        parser.add_argument('--out', default=None, help='مسارُ الملفّ (افتراضيّاً SERVER_GUIDE_EXPORT_PATH)')
        parser.add_argument('--official-url', default=None,
                            help='رابطُ الموظّفين في النصّ والروابط (افتراضيّاً LETTERSYS_OFFICIAL_URL) — لازم')

    def handle(self, *args, **options):
        official = (options['official_url'] or settings.LETTERSYS_OFFICIAL_URL or '').strip()
        if not official:
            # الدليلُ يُفتح من القرص: بلا رابطٍ تصير روابطُه ‎file:///D:/books/…‎ ميّتة (فيبل 11-22)
            raise CommandError('رابطُ الموظّفين لازم: مرّر --official-url (مثلاً http://follow2:1312) '
                               'أو اضبط LETTERSYS_OFFICIAL_URL. لم يُكتب شيء.')
        out = write_offline_guide(official, options['out'])
        self.stdout.write(f'GUIDE_EXPORTED {out}')
