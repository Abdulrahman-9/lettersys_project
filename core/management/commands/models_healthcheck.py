# -*- coding: utf-8 -*-
"""فحصُ عتاد النماذج قبل الإقلاع — الأوزانُ وأطقمُ المحارف والمحرّك الخارجيّ.

**لماذا**: `var/` كلُّه خارج git، فالنسخةُ الجديدة تصل بلا أوزان وتبدو سليمة:
الصفحاتُ تُفتح والاختباراتُ تخضرّ (مجموعةُ الاختبار لا تلمس `var/models` إطلاقاً)
والاستخراجُ يعيد حقولاً فارغة. والحالةُ الملتبسة: **طقمُ محارفَ مفقودٌ ونموذجُه
حاضر** ⟵ يسقط الطقمُ إلى `'0123456789'` الافتراضيّ. والعشرةُ الأولى تتطابق
فهرسةً (فادّعاءُ «انزياحِ الخرائط» نُقض بالفحص)، لكنّ طقمَ التاريخ فيه «/» عند
الفهرس 11 ⟵ `charset[10]` يرفع `IndexError` خارجَ حارس القارئ فيسقط اقتراحُ
التاريخ في أكثر المستندات صامتاً. لذا يُفحَص الطقمُ مضموناً لا وجوداً فقط.

**العقد**: القائمةُ في `core/extraction/artifacts.py` هي نفسُها التي يقرأ منها
الكودُ الحيُّ مساراتِه — فلا يفحص هذا الأمرُ شيئاً غيرَ الذي يُحمَّل فعلاً.

    python manage.py models_healthcheck            # تحذيرٌ وخروجٌ 0 (جهاز تطوير)
    python manage.py models_healthcheck --strict   # عطبٌ وخروجٌ 1 (بوّابةُ نشر)
    python manage.py models_healthcheck --load     # يفتح جلسات ONNX فعلاً
    python manage.py models_healthcheck --hash     # بصمةُ sha256 لكلّ ملفّ
"""
import hashlib
import json
import os
import shutil

from django.conf import settings
from django.core.management import BaseCommand, CommandError

from core.extraction.artifacts import ARTIFACTS


def _sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()[:16]


def _human(n):
    return '%.1f MB' % (n / 1048576.0) if n >= 1048576 else '%d B' % n


class Command(BaseCommand):
    help = 'فحصُ أوزان النماذج وأطقم المحارف ومحرّك OCR قبل الإقلاع.'

    def add_arguments(self, parser):
        parser.add_argument('--strict', action='store_true',
                            help='اجعل غيابَ أيّ نموذجٍ عطباً (بوّابةُ النشر).')
        parser.add_argument('--load', action='store_true',
                            help='افتح جلسةَ ONNX فعلاً — يكشف الملفَّ التالف أو غيرَ المتوافق.')
        parser.add_argument('--hash', action='store_true',
                            help='اطبع بصمةَ sha256 (16 خانة) لكلّ ملفٍّ موجود.')

    # ── الفحوص ───────────────────────────────────────────────────────────────
    def _check_artifact(self, art, opts, present_keys, hard, soft):
        path = art.path_fn()
        w = self.stdout.write
        if not os.path.exists(path):
            # نموذجٌ غائبٌ = ميزةٌ تسقط. وطقمُ محارفَ غائبٌ ونموذجُه حاضر = قراءةٌ
            # خاطئةٌ واثقة، وهي أسوأُ من الغياب — فتُعدّ عطباً دائماً.
            msg = '%s — مفقود (%s) ⟵ %s' % (art.label, path, art.breaks)
            if art.level == 'required' and (art.needs is None or art.needs in present_keys):
                hard.append(msg)
            elif art.level == 'degrades' and opts['strict']:
                hard.append(msg)
            else:
                soft.append(msg)
            return False
        size = os.path.getsize(path)
        extra = ''
        if size == 0:
            hard.append('%s — ملفٌّ فارغ (%s)' % (art.label, path))
            return False
        if art.kind in ('charset', 'json'):
            try:
                with open(path, encoding='utf-8') as f:
                    meta = json.load(f)
            except (OSError, ValueError) as exc:
                hard.append('%s — JSON غيرُ صالح (%s): %s' % (art.label, path, exc))
                return False
            if art.kind == 'charset':
                ok, why = self._check_charset(art, meta)
                if not ok:
                    hard.append('%s — %s (%s)' % (art.label, why, path))
                    return False
                extra = ' · طقم %r · blank %s' % (meta.get('charset'), meta.get('blank', 0))
        if art.kind == 'onnx' and opts['load']:
            try:
                import onnxruntime as ort
                sess = ort.InferenceSession(path, providers=['CPUExecutionProvider'])
                extra = ' · مُحمَّل (%s ⟵ %s)' % (
                    sess.get_inputs()[0].name,
                    ','.join(o.name for o in sess.get_outputs()))
                del sess
            except Exception as exc:          # noqa: BLE001 — أيُّ فشلِ تحميلٍ عطب
                hard.append('%s — لا يُحمَّل (%s): %s: %s'
                            % (art.label, path, type(exc).__name__, exc))
                return False
        if opts['hash']:
            extra += ' · sha256:%s' % _sha256(path)
        w(self.style.SUCCESS('سليم: %-22s %9s%s' % (art.label, _human(size), extra)))
        return True

    @staticmethod
    def _check_charset(art, meta):
        charset = meta.get('charset') or ''
        if not charset:
            return False, 'بلا مفتاح `charset`'
        if not isinstance(meta.get('blank', 0), int):
            return False, '`blank` ليس عدداً صحيحاً'
        if meta.get('blank', 0) > len(charset):
            return False, 'فهرسُ `blank` خارجَ الطقم'
        # طقمُ التاريخ يحوي الفاصل «/»؛ وسقوطُه إلى طقم الأرقام يُزيح الخريطةَ
        # كلَّها فتخرج تواريخُ خردةٍ بثقةٍ عالية. الشرطُ يمنع خلطَ الملفّين أيضاً.
        if art.key == 'date_charset' and '/' not in charset:
            return False, 'طقمُ التاريخ بلا «/» — يبدو طقمَ الأرقام في غير موضعه'
        return True, ''

    def _check_runtime_package(self, hard):
        """الحزمةُ نفسُها — كانت غائبةً عن `requirements.txt` كلّيّاً.

        الاستيرادُ كسولٌ في `detector.py` و`reader.py`، فغيابُها لا يكسر إقلاعاً
        ولا اختباراً: يُسجَّل تحذيرٌ في مُسجّلٍ بلا مُعالِج ويصمت المسارُ البصريُّ
        كلُّه. أي نسخةٌ مبنيّةٌ من `requirements.txt` قبل اليوم كانت بلا قراءةٍ
        يدويّةٍ إطلاقاً — والأوزانُ حاضرةٌ على القرص فيبدو كلُّ شيءٍ سليماً.
        """
        try:
            import onnxruntime as ort
            self.stdout.write(self.style.SUCCESS(
                'سليم: %-22s %s' % ('حزمة onnxruntime', ort.__version__)))
        except Exception as exc:      # noqa: BLE001
            hard.append('حزمة onnxruntime غيرُ مثبَّتة (%s) ⟵ الكاشفُ والقارئان '
                        'خاملون رغم وجود الأوزان' % type(exc).__name__)

    def _check_tesseract(self, hard, soft):
        w = self.stdout.write
        # **نفسُ مُحلِّل الإنتاج حرفيّاً** (`TesseractProvider._autodetect_cmd`):
        # فحصٌ بمُحلِّلٍ آخر يكذب في الاتّجاهين — `shutil.which` وحدَه أنكر محرّكاً
        # يجده الإنتاجُ في `C:/Program Files/Tesseract-OCR` (قِيس هنا).
        from core.extraction.ocr.providers import TesseractOCRProvider
        cmd = (getattr(settings, 'TESSERACT_CMD', '')
               or TesseractOCRProvider._autodetect_cmd())
        if cmd and (os.path.exists(cmd) or shutil.which(cmd)):
            w(self.style.SUCCESS('سليم: %-22s %s' % ('محرّك tesseract', cmd)))
        else:
            hard.append('محرّك tesseract غيرُ موجود (TESSERACT_CMD=%r) ⟵ صفرُ استخراجٍ '
                        'من أيّ مستند' % (cmd,))
        tdir = getattr(settings, 'TESSERACT_TESSDATA_DIR', '') or ''
        if not tdir:
            soft.append('TESSERACT_TESSDATA_DIR غيرُ مضبوط — يُعتمَد مسارُ tesseract '
                        'الافتراضيّ، وقد يخلو من العربيّة')
            return
        missing = [n for n in ('ara.traineddata', 'eng.traineddata')
                   if not os.path.exists(os.path.join(tdir, n))]
        if missing:
            hard.append('بياناتُ اللغة ناقصة في %s: %s ⟵ العربيّةُ لا تُقرأ'
                        % (tdir, '، '.join(missing)))
        else:
            w(self.style.SUCCESS('سليم: %-22s %s' % ('بياناتُ اللغة (ara+eng)', tdir)))

    # ── التنفيذ ──────────────────────────────────────────────────────────────
    def handle(self, *args, **options):
        w = self.stdout.write
        w(self.style.NOTICE('جذرُ المشروع: %s' % settings.BASE_DIR))
        if os.path.abspath(os.getcwd()) != os.path.abspath(str(settings.BASE_DIR)):
            w(self.style.NOTICE('مجلّدُ العمل مختلف: %s — المساراتُ مثبَّتةٌ على الجذر '
                                'فلا أثرَ لذلك (منذ 2026-09-01)' % os.getcwd()))
        hard, soft = [], []
        present = set()
        # النماذجُ أوّلاً كي يعرف فحصُ الطقم أنّ نموذجَه حاضر (حقل `needs`).
        for art in sorted(ARTIFACTS, key=lambda a: a.kind != 'onnx'):
            if self._check_artifact(art, options, present, hard, soft):
                present.add(art.key)
        self._check_runtime_package(hard)
        self._check_tesseract(hard, soft)

        for issue in soft:
            w(self.style.WARNING('تحذير: %s' % issue))
        if hard:
            for issue in hard:
                w(self.style.ERROR('عطب ⛔ %s' % issue))
            raise CommandError('فحصُ العتاد أخفق — %d عطباً و%d تحذيراً.'
                               % (len(hard), len(soft)))
        w(self.style.SUCCESS('فحصُ العتاد نجح%s.' % (' (بتحذيرات)' if soft else '')))
