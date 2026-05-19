import os
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

        # في dev runserver يُشغّل Django process أصل ثم يُولّد child reloader.
        # ready() يُستدعى في كليهما — نُهمل process الأصل لمنع تحميل مزدوج.
        # استثناء: مع --noreload لا توجد child، فالمستقبل الوحيد هو الـ main.
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
        if os.environ.get('SCAN_WATCHER_ENABLED', 'true').lower() in ('true', '1', 'yes'):
            self._start_scan_watcher_thread()

    def _start_scan_watcher_thread(self):
        """
        يُشغّل Hot Folder Watcher كـ daemon thread مع بدء Django.
        يقرأ مجلد المراقبة من ScanSettings في DB — يتكيّف مع التغييرات تلقائياً.
        لا يعمل أثناء: migrate / collectstatic / test / shell.
        """
        _skip_commands = {'migrate', 'makemigrations', 'collectstatic', 'check', 'test', 'shell', 'dbshell'}
        import sys as _sys
        if any(cmd in _sys.argv for cmd in _skip_commands):
            return

        def _watcher_loop():
            import os as _os
            import time as _time
            from django.core.cache import cache

            # انتظر حتى يكتمل إعداد Django قبل الوصول إلى DB
            _time.sleep(3)

            logger.info('[ScanWatcher] بدء خيط مراقبة المجلد...')
            cache.set('scan_watcher_status', 'starting', timeout=None)
            cache.set('scan_watcher_pid', _os.getpid(), timeout=None)
            cache.set('scan_watcher_last_error', '', timeout=None)

            current_folder = None

            while True:
                try:
                    from django.db import OperationalError, ProgrammingError
                    try:
                        from core.models import ScanSettings
                        cfg = ScanSettings.get()
                    except (OperationalError, ProgrammingError):
                        # الجدول لا يوجد بعد (قبل migrate الأول) — أعد المحاولة لاحقاً
                        cache.set('scan_watcher_status', 'stopped', timeout=None)
                        cache.set('scan_watcher_last_error', 'جدول ScanSettings غير موجود — شغّل migrate', timeout=None)
                        _time.sleep(15)
                        continue

                    folder = cfg.watch_folder.strip() if cfg.watch_folder else ''

                    if not folder:
                        cache.set('scan_watcher_status', 'stopped', timeout=None)
                        cache.set('scan_watcher_last_error', 'مجلد المراقبة غير مكوّن في الإعدادات', timeout=None)
                        _time.sleep(10)
                        continue

                    if folder != current_folder:
                        logger.info('[ScanWatcher] مجلد المراقبة: %s', folder)
                        current_folder = folder
                        cache.set('scan_watcher_status', 'running', timeout=None)

                    _scan_one_cycle(folder, cfg, cache)
                    cache.set('scan_watcher_last_cycle_at', _time.time(), timeout=None)

                except Exception as exc:
                    logger.exception('[ScanWatcher] خطأ غير متوقّع في دورة المراقبة')
                    try:
                        from django.core.cache import cache as _c
                        _c.set('scan_watcher_status', 'error', timeout=None)
                        _c.set('scan_watcher_last_error', f'{type(exc).__name__}: {exc}', timeout=None)
                    except Exception:
                        pass

                _time.sleep(2)

        def _scan_one_cycle(folder, cfg, cache):
            """
            دورة واحدة لمسح المجلد. الإصلاحات الجذرية:
              • seen أصبح dict {path: (mtime, size)} بدلاً من set → كشف التغييرات.
              • تنظيف ذكي: إزالة كل مدخل لم يعد ملفه على القرص (بعد النقل لـ processed/).
              • استخدام time.time() بدلاً من monotonic() → يصمد عبر إعادات التشغيل.
              • رسائل خطأ واضحة عند فشل المجلد بدلاً من الصمت.
              • عدّادات تشخيص مستقلّة: seen_total, processed_total, skipped_total.
            """
            import os, uuid, shutil, webbrowser, time as _t
            from pathlib import Path
            from datetime import date

            EXTS   = {'.pdf', '.jpg', '.jpeg', '.png', '.tif', '.tiff'}
            STABLE = float(os.environ.get('SCAN_STABLE_SECONDS', '1.5'))

            seen_key       = 'scan_watcher_seen_files'      # dict {path_str: (mtime_int, size)}
            count_key      = 'scan_watcher_file_count'      # processed successfully
            seen_total_key = 'scan_watcher_files_seen'      # كل ملف رُئي في دورة (حتى لو تُجوهل)
            skipped_key    = 'scan_watcher_files_skipped'   # تُجوهل (غير مستقر، خطأ ...إلخ)
            last_key       = 'scan_watcher_last_file'

            # 1) تحميل seen القديم — معالجة الترحيل من set إلى dict
            raw_seen = cache.get(seen_key)
            if isinstance(raw_seen, dict):
                seen: dict = raw_seen
            elif isinstance(raw_seen, set):
                # ترحيل من النسخة القديمة: نتجاهل القيم (لا fingerprint) ونبدأ نظيفاً
                seen = {}
            else:
                seen = {}

            watch_path = Path(folder)

            # 2) فحص واضح للمجلد
            if not watch_path.exists():
                msg = f'المجلد المُراقَب غير موجود: {folder}'
                logger.warning('[ScanWatcher] %s', msg)
                cache.set('scan_watcher_status', 'error', timeout=None)
                cache.set('scan_watcher_last_error', msg, timeout=None)
                return
            if not watch_path.is_dir():
                msg = f'المسار المُراقَب ليس مجلداً: {folder}'
                logger.warning('[ScanWatcher] %s', msg)
                cache.set('scan_watcher_status', 'error', timeout=None)
                cache.set('scan_watcher_last_error', msg, timeout=None)
                return

            try:
                entries = list(watch_path.iterdir())
            except PermissionError as perm_exc:
                msg = f'لا توجد صلاحية لقراءة المجلد: {folder} ({perm_exc})'
                logger.warning('[ScanWatcher] %s', msg)
                cache.set('scan_watcher_status', 'error', timeout=None)
                cache.set('scan_watcher_last_error', msg, timeout=None)
                return

            # وصلنا هنا فالمجلد سليم
            cache.set('scan_watcher_status', 'running', timeout=None)
            cache.set('scan_watcher_last_error', '', timeout=None)

            # 3) تنظيف seen من المسارات التي لم تعد موجودة (بعد نقلها لـ processed/)
            #    هذا يحل bug تكرار الأسماء: scan_001.pdf مُنقَل → نُنظّفه من seen
            #    → عند ظهور scan_001.pdf جديد لاحقاً، سيُلتَقَط.
            stale = [p for p in seen if not Path(p).exists()]
            for p in stale:
                seen.pop(p, None)
            if stale:
                logger.debug('[ScanWatcher] نظّف %d مسار قديم من seen', len(stale))

            for entry in entries:
                if not entry.is_file() or entry.suffix.lower() not in EXTS:
                    continue

                # تحقق من اكتمال الكتابة (مرتين بفاصل STABLE)
                try:
                    st1 = entry.stat()
                    _t.sleep(STABLE)
                    st2 = entry.stat()
                    if st1.st_size != st2.st_size or st2.st_size == 0:
                        # ما زال يُكتَب — نتجاوز هذه الدورة
                        cache.set(skipped_key, (cache.get(skipped_key) or 0) + 1, timeout=None)
                        continue
                except OSError:
                    cache.set(skipped_key, (cache.get(skipped_key) or 0) + 1, timeout=None)
                    continue

                fingerprint = (int(st2.st_mtime), st2.st_size)
                path_str = str(entry)

                # تخطّى إذا رأيناه بنفس البصمة (لكن أعد المعالجة عند تغيّر mtime/size)
                if seen.get(path_str) == fingerprint:
                    continue

                # عدّاد "ملف جديد رُئي"
                cache.set(seen_total_key, (cache.get(seen_total_key) or 0) + 1, timeout=None)

                seen[path_str] = fingerprint
                cache.set(seen_key, seen, timeout=None)
                logger.info('[ScanWatcher] ملف جديد: %s (size=%d)', entry.name, st2.st_size)

                # تشغيل OCR
                try:
                    from core.extraction.pipeline import AIExtractionService
                    service = AIExtractionService()
                    result  = service.process_image(path_str)
                    data = {
                        'book_number': result.book_number,
                        'book_number_confidence': result.book_number_confidence,
                        'book_date': result.book_date,
                        'book_date_confidence': result.book_date_confidence,
                        'title': result.title,
                        'title_confidence': result.title_confidence,
                        'issuing_entity': result.issuing_entity_name,
                        'issuing_entity_confidence': result.issuing_entity_confidence,
                        'receiving_entity': result.receiving_entity_name,
                        'receiving_entity_confidence': result.receiving_entity_confidence,
                        'secret_level': result.secret_level,
                        'secret_level_confidence': result.secret_level_confidence,
                        'book_kind': result.book_kind,
                        'book_kind_confidence': result.book_kind_confidence,
                        'overall_confidence': result.overall_confidence,
                        'needs_review': result.status == 'manual_review',
                        'source_file': entry.name,
                        'user_message': result.user_message,
                    }
                except Exception as exc:
                    logger.exception('[ScanWatcher] OCR فشل على %s', entry.name)
                    data = {'needs_review': True, 'source_file': entry.name, '_error': str(exc)}
                    cache.set('scan_watcher_last_error', f'OCR فشل على {entry.name}: {exc}', timeout=None)

                token = uuid.uuid4().hex

                # نقل الملف للأرشيف. مهم: حتى لو فشل النقل (OneDrive sync conflict
                # أو الملف اختفى أثناء OCR)، نضمن أن processed_path يشير لأي مسار
                # موجود فعلاً على القرص — حتى يظهر الملف في dialog المتصفح.
                processed_dir = entry.parent / 'processed' / date.today().isoformat()
                moved = False
                try:
                    processed_dir.mkdir(parents=True, exist_ok=True)
                    dest = processed_dir / entry.name
                    if dest.exists():
                        dest = processed_dir / f'{entry.stem}_{token[:6]}{entry.suffix}'
                    shutil.move(path_str, str(dest))
                    data['processed_path'] = str(dest)
                    moved = True
                    seen.pop(path_str, None)
                    cache.set(seen_key, seen, timeout=None)
                except OSError as mv_exc:
                    logger.warning('[ScanWatcher] فشل نقل %s: %s', entry.name, mv_exc)
                    cache.set('scan_watcher_last_error',
                              f'فشل نقل {entry.name} (يبقى في مكانه): {mv_exc}',
                              timeout=None)

                # Fallback لـ processed_path: إذا فشل النقل، استخدم المسار الأصلي
                # ما دام الملف موجوداً، وإلا حاول مسار المعالجة كاحتمال أخير.
                if not moved:
                    if Path(path_str).exists():
                        data['processed_path'] = path_str
                    elif (processed_dir / entry.name).exists():
                        data['processed_path'] = str(processed_dir / entry.name)
                    else:
                        # لا الملف الأصلي ولا في processed — لن يظهر معاينة
                        logger.error('[ScanWatcher] %s اختفى تماماً — لا يمكن عرضه', entry.name)
                        data['processed_path'] = ''
                        data['_file_missing'] = True

                # حفظ في cache مع token (بعد ضمان processed_path)
                cache.set(f'scan_token:{token}', data, timeout=1800)
                cache.set('scan_watcher_last_token', token, timeout=1800)

                # تحديث عدادات الـ watcher (الناجحة فقط)
                count = (cache.get(count_key) or 0) + 1
                cache.set(count_key, count, timeout=None)
                cache.set(last_key, entry.name, timeout=None)

                # فتح المتصفح (بعد حفظ الكاش — يمنع race condition)
                if cfg.auto_open_browser:
                    url = f"{cfg.server_url.rstrip('/')}/books/extract/smart-desktop/?scan_token={token}"
                    try:
                        webbrowser.open(url)
                    except Exception as wb_exc:
                        logger.warning('[ScanWatcher] فتح المتصفح فشل: %s', wb_exc)

        t = threading.Thread(target=_watcher_loop, daemon=True, name='scan-watcher')
        t.start()
        logger.info('[ScanWatcher] خيط المراقبة بدأ في الخلفية')

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
