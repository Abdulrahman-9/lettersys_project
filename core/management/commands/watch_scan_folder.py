# -*- coding: utf-8 -*-
"""
core.management.commands.watch_scan_folder
==========================================
مراقب مجلد المسح الضوئي (Hot Folder Watcher)

يراقب مجلداً محدداً بشكل مستمر. عند وصول ملف PDF أو صورة جديدة
(من CaptureOnTouch أو أي ماسح آخر) يقوم بـ:

  1. الانتظار حتى اكتمال كتابة الملف
  2. تشغيل مسار AI extraction كاملاً
  3. تخزين النتيجة في Django cache (30 دقيقة)
  4. فتح المتصفح على واجهة الاستخراج مع ملء الحقول تلقائياً
  5. نقل الملف إلى مجلد processed/YYYY-MM-DD/

الاستخدام:
    python manage.py watch_scan_folder
    python manage.py watch_scan_folder --folder "C:\\Scans" --url "http://localhost:8000"
    python manage.py watch_scan_folder --folder "C:\\Scans" --no-browser
"""

import os
import sys
import uuid
import time
import shutil
import logging
import webbrowser
from datetime import date
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

logger = logging.getLogger('lettersys')

SUPPORTED_EXTENSIONS = {'.pdf', '.jpg', '.jpeg', '.png', '.tif', '.tiff'}
STABLE_WAIT_SEC = 2.0   # ثوانٍ انتظار بعد آخر تعديل (ملف مكتمل الكتابة)
POLL_INTERVAL_SEC = 2   # ثوانٍ بين كل جولة فحص
SCAN_TOKEN_TTL = 1800   # 30 دقيقة


class Command(BaseCommand):
    help = 'يراقب مجلد المسح الضوئي ويُشغّل OCR تلقائياً على الملفات الجديدة'

    def add_arguments(self, parser):
        parser.add_argument(
            '--folder',
            type=str,
            default='',
            help='مسار مجلد المسح (افتراضي: SCAN_WATCH_FOLDER من settings)',
        )
        parser.add_argument(
            '--url',
            type=str,
            default='',
            help='عنوان Django المحلي (افتراضي: SCAN_API_URL أو http://localhost:8000)',
        )
        parser.add_argument(
            '--no-browser',
            action='store_true',
            help='لا تفتح المتصفح تلقائياً — اطبع الرابط فقط',
        )
        parser.add_argument(
            '--once',
            action='store_true',
            help='معالجة الملفات الموجودة حالياً ثم الخروج (للاختبار)',
        )

    def handle(self, *args, **options):
        # Priority: CLI arg → DB (ScanSettings) → env/settings
        watch_folder = options['folder']
        base_url = options['url']

        if not watch_folder or not base_url:
            try:
                from core.models import ScanSettings
                db_cfg = ScanSettings.get()
                watch_folder = watch_folder or db_cfg.watch_folder.strip()
                base_url = base_url or db_cfg.server_url.strip()
            except Exception:
                pass  # table may not exist yet before migrate

        watch_folder = watch_folder or getattr(settings, 'SCAN_WATCH_FOLDER', '')
        if not watch_folder:
            raise CommandError(
                'حدّد مجلد المراقبة عبر --folder، أو احفظه في صفحة إعدادات الماسح، '
                'أو عبر SCAN_WATCH_FOLDER في settings/.env'
            )

        watch_path = Path(watch_folder)
        if not watch_path.exists():
            raise CommandError(f'المجلد غير موجود: {watch_path}')

        base_url = (
            base_url
            or getattr(settings, 'SCAN_API_URL', '')
            or 'http://localhost:8000'
        ).rstrip('/')

        open_browser = not options['no_browser']
        run_once = options['once']

        self.stdout.write(self.style.SUCCESS(
            f'\n[HotFolder] مراقبة: {watch_path}'
        ))
        self.stdout.write(f'[HotFolder] واجهة الاستخراج: {base_url}/books/extract/smart-desktop/\n')
        if run_once:
            self.stdout.write('[HotFolder] وضع --once: معالجة الملفات الموجودة ثم الخروج\n')
        else:
            self.stdout.write('[HotFolder] اضغط Ctrl+C للإيقاف\n\n')

        seen_files: set = set()

        try:
            while True:
                try:
                    new_files = self._scan_for_new_files(watch_path, seen_files)
                    for file_path in new_files:
                        seen_files.add(file_path)
                        self._handle_new_file(file_path, base_url, open_browser)
                except KeyboardInterrupt:
                    raise
                except Exception as exc:
                    logger.error('[HotFolder] خطأ في دورة المراقبة: %s', exc)
                    self.stderr.write(f'[HotFolder] خطأ: {exc}')

                if run_once:
                    break
                time.sleep(POLL_INTERVAL_SEC)

        except KeyboardInterrupt:
            self.stdout.write(self.style.WARNING('\n[HotFolder] تم الإيقاف.\n'))

    # ─── مساعدات داخلية ────────────────────────────────────────────────────────

    def _scan_for_new_files(self, folder: Path, seen: set) -> list:
        """البحث عن ملفات جديدة غير مرصودة مع التحقق من اكتمال الكتابة."""
        found = []
        try:
            entries = list(folder.iterdir())
        except PermissionError:
            return found

        for entry in entries:
            if not entry.is_file():
                continue
            if entry.suffix.lower() not in SUPPORTED_EXTENSIONS:
                continue
            if entry in seen:
                continue
            if not self._is_stable(entry):
                continue
            found.append(entry)

        return found

    def _is_stable(self, file_path: Path) -> bool:
        """يتحقق أن الملف مكتمل الكتابة (لم يتغير حجمه خلال STABLE_WAIT_SEC)."""
        try:
            size1 = file_path.stat().st_size
            time.sleep(STABLE_WAIT_SEC)
            size2 = file_path.stat().st_size
            return size1 == size2 and size1 > 0
        except OSError:
            return False

    def _handle_new_file(self, file_path: Path, base_url: str, open_browser: bool):
        """معالجة ملف جديد: OCR → نقل → cache → متصفح."""
        self.stdout.write(f'\n[HotFolder] ملف جديد: {file_path.name}')

        # ─ تشغيل AI extraction ─────────────────────────────────────────────────
        self.stdout.write('[HotFolder] ⟳ جاري تشغيل OCR...')
        start = time.time()

        extraction_data = self._run_extraction(file_path)

        elapsed = time.time() - start
        self.stdout.write(
            f'[HotFolder] ✓ اكتمل في {elapsed:.1f}s — '
            f"ثقة {int((extraction_data.get('overall_confidence', 0)) * 100)}%"
        )

        if extraction_data.get('needs_review'):
            self.stdout.write(
                self.style.WARNING('[HotFolder] ⚠ ثقة منخفضة — يُوصى بمراجعة الحقول يدوياً')
            )

        # ─ نقل الملف أولاً لالتقاط المسار النهائي ────────────────────────────
        processed_path = self._move_to_processed(file_path)
        if processed_path:
            extraction_data['processed_path'] = str(processed_path)

        # ─ حفظ في Django cache مع رمز مؤقت ───────────────────────────────────
        token = uuid.uuid4().hex
        self._save_to_cache(token, extraction_data)

        # ─ تحديث مفاتيح watcher في الكاش (للـ browser poll) ─────────────────
        try:
            from django.core.cache import cache as _cache
            count = (_cache.get('scan_watcher_file_count') or 0) + 1
            _cache.set('scan_watcher_status',     'running',      timeout=SCAN_TOKEN_TTL)
            _cache.set('scan_watcher_last_file',  file_path.name, timeout=SCAN_TOKEN_TTL)
            _cache.set('scan_watcher_file_count', count,          timeout=SCAN_TOKEN_TTL)
            _cache.set('scan_watcher_last_token', token,          timeout=SCAN_TOKEN_TTL)
        except Exception:
            pass

        # ─ فتح المتصفح ─────────────────────────────────────────────────────────
        extract_url = f'{base_url}/books/extract/smart-desktop/?scan_token={token}'
        if open_browser:
            try:
                webbrowser.open(extract_url)
                self.stdout.write(f'[HotFolder] ✓ تم فتح المتصفح: {extract_url}')
            except Exception as exc:
                self.stdout.write(f'[HotFolder] تعذّر فتح المتصفح: {exc}')
                self.stdout.write(f'[HotFolder] الرابط: {extract_url}')
        else:
            self.stdout.write(f'[HotFolder] الرابط: {extract_url}')

    def _run_extraction(self, file_path: Path) -> dict:
        """تشغيل AIExtractionService مباشرة داخل Django context."""
        try:
            from core.extraction.pipeline import AIExtractionService
            service = AIExtractionService()

            def _on_progress(stage: str):
                stage_labels = {
                    'cache_check': 'فحص الكاش',
                    'image_enhancement': 'تحسين الصورة',
                    'ocr': 'قراءة النص (EasyOCR)',
                    'ocr_azure_fallback': 'تحسين القراءة (Azure)',
                    'pattern_matching': 'تحليل البيانات',
                    'entity_matching': 'مطابقة الجهات',
                    'confidence': 'حساب الثقة',
                }
                label = stage_labels.get(stage, stage)
                self.stdout.write(f'  [{label}]', ending='\r')
                sys.stdout.flush()

            result = service.process_image(str(file_path), on_progress=_on_progress)
            self.stdout.write('')  # سطر جديد بعد \r

            return {
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
                'ocr_engine': result.ocr_engine,
                'source_file': file_path.name,
                'user_message': result.user_message,
            }

        except Exception as exc:
            logger.error('[HotFolder] فشل الاستخراج: %s', exc, exc_info=True)
            self.stderr.write(f'[HotFolder] خطأ في الاستخراج: {exc}')
            return {
                'overall_confidence': 0.0,
                'needs_review': True,
                'source_file': file_path.name,
                'user_message': 'فشل الاستخراج — حاول مرة أخرى أو ارفع الملف يدوياً',
                '_error': str(exc),
            }

    def _save_to_cache(self, token: str, data: dict):
        """حفظ بيانات الاستخراج في Django cache مع TTL 30 دقيقة."""
        try:
            from django.core.cache import cache
            cache.set(f'scan_token:{token}', data, timeout=SCAN_TOKEN_TTL)
            logger.debug('[HotFolder] saved scan token: %s', token)
        except Exception as exc:
            logger.warning('[HotFolder] cache save failed: %s', exc)

    def _move_to_processed(self, file_path: Path) -> 'Path | None':
        """نقل الملف إلى {folder}/processed/YYYY-MM-DD/ ويعيد المسار الجديد."""
        processed_dir = file_path.parent / 'processed' / date.today().isoformat()
        processed_dir.mkdir(parents=True, exist_ok=True)
        dest = processed_dir / file_path.name
        # تجنب التعارض إذا كان الاسم موجوداً مسبقاً
        if dest.exists():
            stem = file_path.stem
            suffix = file_path.suffix
            dest = processed_dir / f'{stem}_{uuid.uuid4().hex[:6]}{suffix}'
        try:
            shutil.move(str(file_path), str(dest))
            self.stdout.write(f'[HotFolder] ✓ نُقل إلى: {dest.relative_to(file_path.parent.parent)}')
            return dest
        except OSError as exc:
            self.stderr.write(f'[HotFolder] تعذّر نقل الملف: {exc}')
            return None
