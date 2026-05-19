# -*- coding: utf-8 -*-
"""
core.extraction.ocr.image
==========================
Image Processing Module — تحسين جودة الصور قبل OCR
"""

import cv2
import numpy as np
from PIL import Image, ImageEnhance
import io
from pathlib import Path
import fitz  # PyMuPDF (imported as fitz)
import logging

logger = logging.getLogger(__name__)


class ImageProcessor:
    """
    معالج الصور لتحسين جودتها قبل الاستخراج الضوئي
    """

    def __init__(self, image_path_or_bytes):
        """
        تهيئة معالج الصور

        Args:
            image_path_or_bytes: مسار الملف أو bytes من الصورة
        """
        self.image_path = None
        self.image = None
        self.original_image = None

        if isinstance(image_path_or_bytes, (str, Path)):
            self.image_path = str(image_path_or_bytes)

            # تحقق إذا كان الملف PDF
            if self.image_path.lower().endswith('.pdf'):
                logger.info(f"[ImageProcessor] Detected PDF file: {self.image_path}")
                self.image = self._convert_pdf_to_image(self.image_path)
            else:
                self.image = cv2.imread(self.image_path)
        else:
            # bytes or file-like object
            nparr = np.frombuffer(image_path_or_bytes.read() if hasattr(image_path_or_bytes, 'read') else image_path_or_bytes, np.uint8)
            self.image = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

        if self.image is None:
            raise ValueError("فشل تحميل الصورة")

        # تصغير الصور الكبيرة قبل OCR (CPU EasyOCR بطيء على صور > 2000px)
        # الحد 2000px على الجانب الأطول كافٍ لـ OCR الطباعي العربي/الإنجليزي.
        h, w = self.image.shape[:2]
        max_dim = max(h, w)
        MAX_OCR_DIM = 2000
        if max_dim > MAX_OCR_DIM:
            scale = MAX_OCR_DIM / max_dim
            new_w, new_h = int(w * scale), int(h * scale)
            logger.info('[ImageProcessor] downscale %dx%d → %dx%d (OCR speed)',
                        w, h, new_w, new_h)
            self.image = cv2.resize(self.image, (new_w, new_h),
                                    interpolation=cv2.INTER_AREA)

        self.original_image = None  # لا نحتفظ بنسخة لتوفير الذاكرة

    def _convert_pdf_to_image(self, pdf_path: str) -> np.ndarray:
        """
        تحويل أول صفحة من PDF إلى صورة بدقة عالية

        Args:
            pdf_path: مسار ملف PDF

        Returns:
            numpy array للصورة المحسّنة
        """
        try:
            logger.info(f"[ImageProcessor] Converting PDF to image: {pdf_path}")
            doc = fitz.open(pdf_path)

            if doc.page_count == 0:
                raise ValueError("PDF file is empty")

            # Get first page
            page = doc[0]

            # تحويل لصورة بدقة عالية (300 DPI للنص العربي)
            zoom = 300 / 72  # 72 DPI is default, نستخدم 300 لوضوح أفضل مع توفير الذاكرة
            mat = fitz.Matrix(zoom, zoom)
            pix = page.get_pixmap(matrix=mat, alpha=False)  # بدون alpha channel

            # تحويل لـ numpy array
            img_data = pix.tobytes("png")
            nparr = np.frombuffer(img_data, np.uint8)
            img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

            doc.close()
            logger.info(f"[ImageProcessor] PDF converted at 300 DPI, size: {img.shape}")

            # تحسين الصورة فوراً بعد التحويل
            img = self._preprocess_for_ocr(img)
            logger.info(f"[ImageProcessor] Image preprocessed for OCR")

            return img

        except Exception as e:
            logger.error(f"[ImageProcessor] Failed to convert PDF: {e}")
            raise ValueError(f"فشل تحويل PDF: {e}")

    def _preprocess_for_ocr(self, img: np.ndarray) -> np.ndarray:
        """
        معالجة مسبقة متقدمة للصورة قبل OCR (خاصة للعربية)

        خطوات:
        1. تحويل لرمادي مع conservation للألوان
        2. إزالة ضوضاء متقدمة
        3. زيادة التباين (CLAHE)
        4. تصحيح الزاوية (deskew)
        5. Morphological operations
        6. Binarization ذكية
        7. تحسين النص الضعيف

        Args:
            img: الصورة الأصلية (BGR)

        Returns:
            الصورة المحسّنة جاهزة للـ OCR
        """
        # 1. تحويل لرمادي بحرص
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

        # 2. إزالة ضوضاء قوية (خاصة للمستندات الممسوحة)
        # استخدام bilateral filter للحفاظ على الحواف
        denoised = cv2.bilateralFilter(gray, 9, 75, 75)

        # 3. زيادة التباين باستخدام CLAHE (تحسين محلي للتباين)
        clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
        enhanced = clahe.apply(denoised)

        # 4. تصحيح الزاوية إذا لزم الأمر
        enhanced = self._auto_deskew(enhanced)

        # 5. Morphological operations لتحسين النص المتصل
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
        enhanced = cv2.morphologyEx(enhanced, cv2.MORPH_CLOSE, kernel)  # إغلاق الفجوات
        enhanced = cv2.morphologyEx(enhanced, cv2.MORPH_OPEN, kernel)   # فتح الضوضاء الدقيقة

        # 6. Adaptive thresholding لـ بinarization أفضل
        # استخدام adaptive بدل Otsu لأنه أفضل مع النصوص المتغيرة
        binary = cv2.adaptiveThreshold(
            enhanced, 255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY,
            blockSize=11,  # حجم الـ block
            C=2  # constant subtracted
        )

        # 7. Dilation خفيفة لتقوية النص الضعيف (خاصة للعربي)
        kernel_dilate = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (1, 1))
        binary = cv2.dilate(binary, kernel_dilate, iterations=1)

        # تحويل رجوع لـ BGR لأن OCR يتوقع 3 channels
        result = cv2.cvtColor(binary, cv2.COLOR_GRAY2BGR)

        logger.info(f"[ImageProcessor] Preprocessing complete - shape: {result.shape}")
        return result

    def _auto_deskew(self, img: np.ndarray, angle_range=15) -> np.ndarray:
        """
        تصحيح الزاوية تلقائياً إذا لزم الأمر

        Args:
            img: الصورة الرمادية
            angle_range: نطاق الزوايا للبحث

        Returns:
            الصورة المصححة أو الأصلية إذا لم تكن بحاجة لتصحيح
        """
        try:
            # كشف الحواف
            edges = cv2.Canny(img, 100, 200)

            # استخدام Hough lines لكشف الزاوية
            lines = cv2.HoughLines(edges, 1, np.pi/180, 100)

            if lines is None or len(lines) == 0:
                return img  # لا توجد خطوط - الصورة مستقيمة

            # حساب الزاوية الأكثر شيوعاً
            angles = []
            for line in lines:
                rho, theta = line[0]
                angle = np.degrees(theta) - 90
                if -angle_range <= angle <= angle_range:
                    angles.append(angle)

            if not angles:
                return img

            # استخدام median للزاوية الأكثر شيوعاً
            angle = np.median(angles)

            # إذا كانت الزاوية صغيرة جداً، لا نفعل شيء
            if abs(angle) < 0.5:
                return img

            logger.info(f"[ImageProcessor] Auto-correcting skew angle: {angle:.2f}°")

            # تطبيق التصحيح
            h, w = img.shape[:2]
            center = (w // 2, h // 2)
            M = cv2.getRotationMatrix2D(center, angle, 1.0)
            corrected = cv2.warpAffine(img, M, (w, h), borderMode=cv2.BORDER_REPLICATE)

            return corrected

        except Exception as e:
            logger.warning(f"[ImageProcessor] Deskew failed: {e}, using original")
            return img

    def enhance_quality(self):
        """
        تحسين جودة الصورة العامة
        """
        # تحسين الحدة
        kernel = np.array([[-1, -1, -1],
                          [-1,  9, -1],
                          [-1, -1, -1]])
        self.image = cv2.filter2D(self.image, -1, kernel)

        # تقليل الضوضاء
        self.image = cv2.fastNlMeansDenoising(self.image, h=10)

        return self

    def denoise(self):
        """
        إزالة الضوضاء من الصورة
        """
        self.image = cv2.fastNlMeansDenoising(self.image, h=10, templateWindowSize=7, searchWindowSize=21)
        return self

    def increase_contrast(self, factor=1.5):
        """
        زيادة التباين
        """
        pil_image = Image.fromarray(cv2.cvtColor(self.image, cv2.COLOR_BGR2RGB))
        enhancer = ImageEnhance.Contrast(pil_image)
        pil_image = enhancer.enhance(factor)
        self.image = cv2.cvtColor(np.array(pil_image), cv2.COLOR_RGB2BGR)
        return self

    def increase_brightness(self, factor=1.2):
        """
        زيادة السطوع
        """
        pil_image = Image.fromarray(cv2.cvtColor(self.image, cv2.COLOR_BGR2RGB))
        enhancer = ImageEnhance.Brightness(pil_image)
        pil_image = enhancer.enhance(factor)
        self.image = cv2.cvtColor(np.array(pil_image), cv2.COLOR_RGB2BGR)
        return self

    def deskew(self):
        """
        تصحيح انحناء النص (تصحيح الزاوية)
        """
        gray = cv2.cvtColor(self.image, cv2.COLOR_BGR2GRAY)
        coords = np.column_stack(np.where(gray > gray.mean()))

        if len(coords) == 0:
            return self

        angle = cv2.minAreaRect(coords)[2]

        # الزاوية سالبة في الغالب
        if angle < -45:
            angle = 90 + angle
        elif angle > 45:
            angle = angle - 90

        # تدوير الصورة
        (h, w) = self.image.shape[:2]
        center = (w // 2, h // 2)
        M = cv2.getRotationMatrix2D(center, angle, 1.0)
        self.image = cv2.warpAffine(self.image, M, (w, h), borderMode=cv2.BORDER_REPLICATE)

        return self

    def upscale(self, scale=2):
        """
        تكبير الصورة لتحسين جودة OCR
        """
        height, width = self.image.shape[:2]
        new_width = width * scale
        new_height = height * scale
        self.image = cv2.resize(self.image, (new_width, new_height), interpolation=cv2.INTER_CUBIC)
        return self

    def convert_to_grayscale(self):
        """
        تحويل إلى صورة رمادية
        """
        self.image = cv2.cvtColor(self.image, cv2.COLOR_BGR2GRAY)
        return self

    def apply_threshold(self, method='adaptive'):
        """
        تطبيق حد للصورة لتحسين وضوح النص

        Args:
            method: 'adaptive', 'otsu', أو 'manual'
        """
        if len(self.image.shape) == 3:
            self.image = cv2.cvtColor(self.image, cv2.COLOR_BGR2GRAY)

        if method == 'adaptive':
            self.image = cv2.adaptiveThreshold(self.image, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                               cv2.THRESH_BINARY, 11, 2)
        elif method == 'otsu':
            _, self.image = cv2.threshold(self.image, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        else:
            _, self.image = cv2.threshold(self.image, 127, 255, cv2.THRESH_BINARY)

        return self

    def remove_borders(self, border_size=10):
        """
        إزالة الحدود من الصورة
        """
        h, w = self.image.shape[:2]
        self.image = self.image[border_size:h-border_size, border_size:w-border_size]
        return self

    def full_pipeline(self):
        """
        معالجة كاملة لتحسين الصورة للـ OCR
        Pipeline متكامل لأفضل النتائج
        """
        self.denoise()
        self.increase_contrast(1.3)
        self.increase_brightness(1.1)
        self.deskew()
        self.apply_threshold('adaptive')
        return self

    def get_image(self):
        """الحصول على الصورة المعالجة"""
        return self.image

    def get_image_bytes(self):
        """الحصول على الصورة كـ bytes"""
        success, buffer = cv2.imencode('.jpg', self.image)
        return buffer.tobytes() if success else None

    def get_image_pil(self):
        """الحصول على الصورة كـ PIL Image"""
        return Image.fromarray(cv2.cvtColor(self.image, cv2.COLOR_BGR2RGB))

    def save(self, output_path):
        """حفظ الصورة المعالجة"""
        output_path = Path(output_path)

        # إذا كان المسار الأصلي PDF، احفظ كـ PNG
        if output_path.suffix.lower() == '.pdf':
            output_path = output_path.with_suffix('.png')
            logger.info(f"[ImageProcessor] Converting PDF output to PNG: {output_path}")

        cv2.imwrite(str(output_path), self.image)
        logger.info(f"[ImageProcessor] Image saved to: {output_path}")
        return self

    def reset(self):
        """إعادة تعيين الصورة إلى الأصلية"""
        if self.original_image is not None:
            self.image = self.original_image.copy()
        return self

    def get_dimensions(self):
        """الحصول على أبعاد الصورة"""
        h, w = self.image.shape[:2]
        return {"width": w, "height": h}

    def get_info(self):
        """معلومات عن الصورة"""
        h, w = self.image.shape[:2]
        return {
            "width": w,
            "height": h,
            "channels": self.image.shape[2] if len(self.image.shape) == 3 else 1,
            "dtype": str(self.image.dtype),
            "size_mb": (self.image.nbytes / 1024 / 1024),
        }


class BatchImageProcessor:
    """
    معالج دفعي للصور
    معالجة عدة صور في نفس الوقت
    """

    def __init__(self, image_paths):
        """
        Args:
            image_paths: قائمة مسارات الصور
        """
        self.image_paths = image_paths
        self.processed_images = {}

    def process_all(self, pipeline='full'):
        """
        معالجة جميع الصور

        Args:
            pipeline: 'full', 'fast', 'quality'
        """
        results = []

        for path in self.image_paths:
            try:
                processor = ImageProcessor(path)

                if pipeline == 'full':
                    processor.full_pipeline()
                elif pipeline == 'fast':
                    processor.denoise().increase_contrast()
                elif pipeline == 'quality':
                    processor.full_pipeline()

                self.processed_images[str(path)] = processor.get_image()
                results.append({
                    'path': str(path),
                    'status': 'success',
                    'image': processor.get_image_bytes()
                })
            except Exception as e:
                results.append({
                    'path': str(path),
                    'status': 'error',
                    'error': str(e)
                })

        return results

    def save_all(self, output_dir):
        """حفظ جميع الصور المعالجة"""
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        for original_path, image in self.processed_images.items():
            filename = Path(original_path).stem + '_processed.jpg'
            cv2.imwrite(str(output_dir / filename), image)


# ===================================================
# Helper Functions
# ===================================================

def process_image_for_ocr(image_path_or_bytes, pipeline='full'):
    """
    دالة مساعدة سريعة لمعالجة صورة للـ OCR

    Args:
        image_path_or_bytes: مسار الصورة أو bytes
        pipeline: 'full', 'fast', 'quality'

    Returns:
        bytes من الصورة المعالجة
    """
    processor = ImageProcessor(image_path_or_bytes)

    if pipeline == 'full':
        processor.full_pipeline()
    elif pipeline == 'fast':
        processor.denoise().increase_contrast()
    elif pipeline == 'quality':
        processor.full_pipeline()

    return processor.get_image_bytes()


def compare_images(image1_bytes, image2_bytes):
    """
    مقارنة صورتين (للكشف عن الصور المتطابقة)

    Returns:
        درجة التشابه (0-1)
    """
    nparr1 = np.frombuffer(image1_bytes, np.uint8)
    img1 = cv2.imdecode(nparr1, cv2.IMREAD_GRAYSCALE)

    nparr2 = np.frombuffer(image2_bytes, np.uint8)
    img2 = cv2.imdecode(nparr2, cv2.IMREAD_GRAYSCALE)

    if img1.shape != img2.shape:
        img2 = cv2.resize(img2, (img1.shape[1], img1.shape[0]))

    # حساب الفرق
    difference = cv2.subtract(img1, img2)
    b, g, r = cv2.split(difference)

    if cv2.countNonZero(b) == 0 and cv2.countNonZero(g) == 0 and cv2.countNonZero(r) == 0:
        return 1.0  # صور متطابقة

    # Structural Similarity Index
    from skimage.metrics import structural_similarity as ssim
    score = ssim(img1, img2)
    return max(0, score)
