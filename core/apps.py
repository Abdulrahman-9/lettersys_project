import logging
import threading

from django.apps import AppConfig

logger = logging.getLogger('lettersys')


class CoreConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'core'

    def ready(self):
        from . import signals  # noqa: F401
        from . import logging_models  # noqa: F401
        # فحصُ عتاد النماذج (تحذيرٌ لا خطأ) — يجعل نسخةً بلا أوزانٍ تُعلن عن
        # نفسها مع كلّ أمرٍ بدل أن تبدو سليمةً وهي عمياء.
        from . import checks  # noqa: F401

        # في dev runserver يُشغّل Django process أصل ثم يُولّد child reloader.
        # ready() يُستدعى في كليهما — نُهمل process الأصل لمنع تحميل مزدوج.
        # استثناء: مع --noreload لا توجد child، فالمستقبل الوحيد هو الـ main.
        import os
        import sys as _sys
        argv = _sys.argv
        if 'runserver' in argv:
            is_reloader_parent = (
                os.environ.get('RUN_MAIN') != 'true'
                and '--noreload' not in argv
            )
            if is_reloader_parent:
                return

        self._warm_ocr_in_background()

    def _warm_ocr_in_background(self):
        """
        تحميل نموذج EasyOCR في الخلفية — فقط إذا AI_PRELOAD_OCR=True.
        الـ guard في ready() يضمن عدم التحميل المزدوج مع autoreloader.
        """
        from django.conf import settings as django_settings
        if not getattr(django_settings, 'AI_PRELOAD_OCR', False):
            return

        def _load():
            try:
                logger.info('[OCR-Preload] بدء تحميل نموذج EasyOCR في الخلفية...')
                from core.extraction.ocr.service import _get_reader
                _get_reader()
                logger.info('[OCR-Preload] تم تحميل نموذج EasyOCR — جاهز للاستخدام')
            except Exception as exc:
                logger.warning('[OCR-Preload] فشل التحميل المسبق: %s', exc)

        t = threading.Thread(target=_load, daemon=True, name='ocr-preload')
        t.start()
