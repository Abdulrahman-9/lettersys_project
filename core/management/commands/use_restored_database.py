# -*- coding: utf-8 -*-
"""use_restored_database — يبدّل النظامَ إلى قاعدةٍ استُعيدت (``lettersys_r_…``) أو يرجع عنها (11-22).

    python manage.py use_restored_database lettersys_r_20261122_1015
    python manage.py use_restored_database --undo

قرارُ المالك (2026‑10‑07) باقٍ: الاستعادةُ إلى قاعدةٍ جديدة والحيّةُ لا تُمسّ، والتبديلُ فعلٌ صريحٌ من المدير.
الأمرُ يجعله سطراً يُلصق بدل تحرير ملفٍّ بيد: يكتب سطرَ ``DB_NAME=`` وحده في ``.env`` (كتابةٌ ذرّيّة، وبقيّةُ
الملفّ كما هي)، ويحفظ الاسمَ السابق في ``var/db_switch.json`` — **لا نسخةً من ``.env``**: فيه كلمةُ مرور
القاعدة صريحة. لا يعيد تشغيل الخدمة، والتبديلُ لا يسري قبل إعادة التشغيل.
"""
import json
import os
import re
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from core.system_restore_service import TARGET_RE, count_books, database_exists

LINE_RE = re.compile(r'(?m)^DB_NAME=([^\r\n]*)')


def env_path():
    return Path(settings.BASE_DIR) / '.env'


def state_path():
    return Path(settings.BASE_DIR) / 'var' / 'db_switch.json'


def read_db_name(text):
    """قيمةُ ``DB_NAME`` في نصّ ``.env`` — سطرٌ واحدٌ بالضبط، وإلّا رفضٌ (لا تخمينَ أيّها يُبدَّل)."""
    found = LINE_RE.findall(text)
    if len(found) != 1:
        raise CommandError(f'في ملفّ البيئة {len(found)} سطرٍ يبدأ بـ DB_NAME= — المتوقَّعُ سطرٌ واحد. لم يتغيّر شيء.')
    return found[0].strip()


BOM = b'\xef\xbb\xbf'


def read_env(path):
    """نصُّ ``.env`` كما هو بايتاً بايتاً: نهاياتُ الأسطر وعلامةُ BOM إن وُجدت (لا تحويلَ للأسطر)."""
    raw = path.read_bytes()
    return raw.decode('utf-8-sig'), raw.startswith(BOM)


def write_db_name(path, text, name, bom=False):
    """يستبدل قيمةَ ``DB_NAME`` وحدها ويكتب الملفَّ ذرّيّاً (نهاياتُ الأسطر وBOM وبقيّةُ القيم كما هي)."""
    temp = path.with_name(path.name + '.switching')
    temp.write_bytes((BOM if bom else b'') + LINE_RE.sub('DB_NAME=' + name, text, count=1).encode('utf-8'))
    os.replace(temp, path)


def check_usable(name):
    """القاعدةُ موجودةٌ وفيها كتب — وإلّا لا تبديل إليها."""
    if not database_exists(name):
        raise CommandError(f'لا قاعدةَ باسم «{name}» في PostgreSQL. لم يتغيّر شيء.')
    books = count_books(name)
    if not books:
        raise CommandError(f'القاعدةُ «{name}» بلا كتب — لن يُبدَّل إليها. لم يتغيّر شيء.')
    return books


class Command(BaseCommand):
    help = 'يبدّل النظامَ إلى قاعدةٍ مستعادة (lettersys_r_…)، أو يرجع بـ --undo.'

    def add_arguments(self, parser):
        parser.add_argument('name', nargs='?', help='اسمُ القاعدة المستعادة (lettersys_r_YYYYMMDD_HHMM)')
        parser.add_argument('--undo', action='store_true', help='الرجوعُ إلى القاعدة التي كانت قبل آخر تبديل')

    def handle(self, *args, **options):
        path = env_path()
        if not path.is_file():
            raise CommandError(f'لا ملفَّ بيئة في {path}. لم يتغيّر شيء.')
        text, bom = read_env(path)
        current = read_db_name(text)
        state_file = state_path()

        if options['undo']:
            if options['name']:
                raise CommandError('إمّا اسمُ قاعدة وإمّا --undo، لا الاثنان.')
            if not state_file.is_file():
                raise CommandError('لا تبديلَ سابقاً يُرجع عنه (var/db_switch.json غائب). لم يتغيّر شيء.')
            state = json.loads(state_file.read_text(encoding='utf-8'))
            if state.get('current') != current:
                raise CommandError(
                    f'ملفُّ البيئة يقول «{current}» لا «{state.get("current")}» الذي بدّل إليه الأمر — تغيّر بعده بيدٍ أخرى. '
                    'لم يتغيّر شيء؛ صحّح DB_NAME بيدك.')
            target = state['previous']
        else:
            target = (options['name'] or '').strip()
            if not TARGET_RE.match(target):
                raise CommandError('الاسمُ ليس قاعدةً مستعادة (lettersys_r_YYYYMMDD_HHMM). لم يتغيّر شيء.')
            if target == current:
                raise CommandError(f'النظامُ على «{target}» أصلاً. لم يتغيّر شيء.')

        books = check_usable(target)
        write_db_name(path, text, target, bom)
        if options['undo']:
            state_file.unlink()
        else:
            state_file.parent.mkdir(parents=True, exist_ok=True)
            state_file.write_text(json.dumps({'previous': current, 'current': target,
                                              'at': timezone.localtime().isoformat()}), encoding='utf-8')
        self.stdout.write(self.style.SUCCESS(f'بُدّل: DB_NAME={current} ⟵ DB_NAME={target} ({books} كتاباً).'))
        self.stdout.write('أعد تشغيل خدمة LetterSys ليسري. ثمّ افتح «استعادة نسخة النظام»: يجب أن تذكر '
                          f'القاعدةَ الحاليّة «{target}» — وإن بقيت «{current}» فـ DB_NAME مضبوطٌ في بيئة الخدمة نفسها.')
        if not options['undo']:
            self.stdout.write('للرجوع: الأمرُ نفسُه بـ --undo ثمّ إعادةُ التشغيل.')
