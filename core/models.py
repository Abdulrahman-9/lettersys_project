from datetime import timedelta

from django.contrib.auth.models import User
from django.contrib.auth.hashers import make_password, check_password
from django.db import models
from django.utils import timezone

from . import numbering
from .extraction.kinds import BOOK_KIND_CHOICES, EXTRACTION_KIND_CHOICES


# النماذج الأساسية: Entity (الجهات)، Book (الكتب)، Attachment (المرفقات)، BookHistory (السجل الزمني)
# نموذج الجهة (اسم، رمز، نوع مصدِّر/مستلم/كلاهما)
class Entity(models.Model):
    """
    نموذج الجهة - تخزين بيانات الجهات (جهات إصدار/استقبال الكتب)
    """
    
    TYPE_CHOICES = (
        ("issuer", "مصدّرة"),
        ("receiver", "مستلمة"),
        ("both", "كلاهما"),
    )

    name     = models.CharField(max_length=255, unique=True)
    code     = models.CharField(max_length=50, unique=True, blank=True, null=True)
    etype    = models.CharField(max_length=10, choices=TYPE_CHOICES, default="both")
    is_active = models.BooleanField(default=True)

    # عند دمج جهة مكرّرة ضمن جهة أمّ: تشير إلى الأمّ وتُضبط is_active=False.
    merged_into = models.ForeignKey(
        'self', null=True, blank=True, on_delete=models.SET_NULL,
        related_name='merged_from', verbose_name='مدموجة في',
        help_text='الجهة الأمّ التي استوعبت هذه الجهة عند إزالة التكرار',
    )

    # ── بيانات الاتصال ──
    email          = models.EmailField("البريد الإلكتروني", blank=True, default="",
                                       help_text="بريد الجهة للمراسلات الرسمية (اختياري)")
    email_cc       = models.CharField("نسخة إلى (CC)", max_length=500, blank=True, default="",
                                      help_text="عناوين بريد إضافية مفصولة بفاصلة (اختيارية)")
    phone          = models.CharField("الهاتف", max_length=50, blank=True, default="")
    address        = models.CharField("العنوان البريدي", max_length=300, blank=True, default="")
    contact_person = models.CharField("مسؤول الاتصال", max_length=100, blank=True, default="")
    notes          = models.TextField("ملاحظات", blank=True, default="")

    # ── تفضيلات الإشعارات ──
    notify_on_receive = models.BooleanField(
        "إشعار عند استلام كتاب منها", default=False,
        help_text="يُرسَل بريد تلقائي للجهة عند تسجيل كتاب وارد منها"
    )
    notify_on_send = models.BooleanField(
        "إشعار عند إرسال كتاب إليها", default=False,
        help_text="يُرسَل بريد تلقائي للجهة عند تسجيل كتاب صادر إليها"
    )

    class Meta:
        verbose_name = "جهة"
        verbose_name_plural = "الجهات"
        indexes = [
            models.Index(fields=['name']),
            models.Index(fields=['code']),
            models.Index(fields=['is_active', 'name']),
            models.Index(fields=['is_active', 'code']),
        ]

    def __str__(self):
        return self.name

    def get_cc_list(self):
        """إرجاع قائمة عناوين CC كـ list بعد تنظيفها."""
        if not self.email_cc:
            return []
        return [e.strip() for e in self.email_cc.split(',') if e.strip()]


def book_attachment_path(instance, filename):
    # يدعم Attachment (instance.book) وAttachmentVersion (instance.attachment.book)
    book = getattr(instance, 'book', None)
    if book is None:
        book = getattr(getattr(instance, 'attachment', None), 'book', None)
    y = book.date.year if book and book.date else timezone.localdate().year
    our_number = (book.our_number if book else '') or 'no-num'
    return f"books/{y}/{our_number}_{filename}"


class Department(models.Model):
    """قسمٌ داخليٌّ في الشركة — بُعدُ النطاق الذي يقوم عليه التعميم.

    لم يكن للنظام كيانُ «قسم» إطلاقاً: الأقسام كانت جهاتِ مراسلةٍ (``Entity``)
    في فضاءٍ واحدٍ مع الوزارات والشركات الأجنبيّة، والرؤية بمُنشئ الكتاب وحده.

    **حدُّ القسم بقرار المالك:** الوحداتُ الداخليّة المرمّزة برموز السجلّ
    العربيّة (ش13 المتابعة، ش5 العقود، د الموارد البشرية…) — 42 وحدةً مقيسةً
    في القاعدة الحيّة. أمّا الجهات بلا رمز (364) فتبقى أطرافَ مراسلةٍ لا أقساماً
    مالكة، والرموز اللاتينيّة شركاتٌ خارجيّة.

    ``entity`` يربط القسم بجهته في الدليل — وهو ما يجعله **طرف مراسلةٍ** أيضاً
    (الإحالات والبريد الداخليّ في المرحلة ج)، ويحسم سؤال الأضابير المؤجَّل:
    الجهةُ الداخليّة هي التي لها قسم.
    """

    name       = models.CharField("اسم القسم", max_length=200, unique=True)
    code       = models.CharField("رمز السجلّ", max_length=20, unique=True,
                                  help_text="رمز الوارد المطبوع على الختم — مثل ش13")
    parent     = models.ForeignKey('self', null=True, blank=True, on_delete=models.PROTECT,
                                   related_name='children', verbose_name="يتبع")
    entity     = models.OneToOneField('Entity', null=True, blank=True, on_delete=models.SET_NULL,
                                      related_name='department', verbose_name="الجهة المقابلة")
    is_active  = models.BooleanField("نشط", default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'قسم'
        verbose_name_plural = 'الأقسام'
        ordering = ['code']

    def __str__(self):
        return f"{self.code} — {self.name}"


class UserProfile(models.Model):
    """امتدادُ المستخدم: قسمُه وصفتُه فيه.

    كان ``UserPassword`` الامتدادَ الوحيد لـ``User``، ولا شيء يربط موظّفاً بقسم.
    """

    user       = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    department = models.ForeignKey(Department, null=True, blank=True, on_delete=models.PROTECT,
                                   related_name='members', verbose_name="القسم")
    job_title  = models.CharField("المسمّى الوظيفي", max_length=120, blank=True, default="")
    # رئيس القسم يرى سرّيّات قسمه — انظر ``core.scoping``.
    is_department_head = models.BooleanField("رئيس القسم", default=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'ملف مستخدم'
        verbose_name_plural = 'ملفات المستخدمين'

    def __str__(self):
        return f"{self.user.get_username()} — {self.department or 'بلا قسم'}"


class Tag(models.Model):
    """وَسم مرن للكتب — يسمح بتصنيف ديناميكي بدون إضافة حقول جديدة."""

    name  = models.CharField('الاسم', max_length=50, unique=True)
    slug  = models.SlugField('المعرّف', max_length=60, unique=True,
                             help_text='يُستخدم في URLs (يُولَّد تلقائياً من name لو ترك فارغاً)')
    color = models.CharField(
        'اللون', max_length=7, blank=True, default='',
        help_text='رمز hex مثل #ff5722 (اختياري للعرض)'
    )
    description = models.CharField('الوصف', max_length=200, blank=True, default='')
    is_active   = models.BooleanField('مفعّل', default=True)
    created_by  = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='created_tags', verbose_name='أنشأه'
    )
    created_at  = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'وَسم'
        verbose_name_plural = 'الوُسوم'
        ordering = ['name']
        indexes = [
            models.Index(fields=['is_active', 'name']),
        ]

    def save(self, *args, **kwargs):
        if not self.slug:
            from django.utils.text import slugify
            base = slugify(self.name, allow_unicode=True) or f'tag-{timezone.now().timestamp():.0f}'
            self.slug = base[:60]
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


# حدود سنة الوسم في `core/numbering.py` وحده (MIN_YEAR/MAX_YEAR). أُزيلت إعادة
# التصدير من هنا بعد أن استغنى عنها آخر متّصل: وجودُ اسمين لحدٍّ واحد هو تحديداً
# ما جعله 2020 في موضع و2000 في آخر، فتُقرأ كتب 2000/2007/2014 قراءتين متناقضتين.


class SoftDeleteManager(models.Manager):
    """المدير الافتراضي للنماذج ذات الحذف الناعم — لا يرى المحذوف.

    كان الحذف الناعم قاعدةً منسوخة يدويّاً: ``is_deleted=False`` مكتوبة **73
    مرّة** في كود الإنتاج وصفر managers مخصّصة. قاعدةٌ بهذا الانتشار تفشل
    بالصمت: استعلامٌ واحد ينسى الشرط يُظهر ما حُذف، ولا اختبارَ يلتقطه لأنّ
    النسيان لا يُخطئ — يُظهر فقط.

    الافتراض الآن آمن، و``all_objects`` هو المخرج **الصريح** لسلّة المحذوفات
    والاستعادة والتفريغ. وسمُ الصراحة مقصود: من يريد المحذوف يقوله.

    ملاحظة: ``_base_manager`` يبقى مديراً عادياً غير مُرشَّح (جانغو يُنشئه
    تلقائيّاً ما لم يُضبط ``Meta.base_manager_name``) — فاجتياز المفتاح الأجنبي
    إلى صفٍّ محذوف (``attachment.book``) يظلّ يعمل ولا ينكسر.
    """

    def get_queryset(self):
        return super().get_queryset().filter(is_deleted=False)


class Book(models.Model):
    """
    نموذج الكتاب - تخزين معلومات الكتب الواردة والصادرة
    يدعم أربعة تصنيفات: صادر داخلي/خارجي، وارد داخلي/خارجي
    """

    SECRET_CHOICES = (
        ("normal", "اعتيادي"),
        ("secret", "سري"),
        ("topsecret", "سري للغاية"),
    )
    KIND_CHOICES = BOOK_KIND_CHOICES

    # ── حالات المتابعة الأربع الموحّدة (حصرية متبادلة، محسوبة من due_date + is_archived) ──
    # archived : ابتدائياً عند الإدخال بدون فترة متابعة، أو يدوياً عند إنهاء المتابعة
    # pending  : due_date > today  — قيد المتابعة (المهلة في المستقبل)
    # due_today: due_date == today — مستحق اليوم
    # overdue  : due_date <  today — متأخر
    FOLLOWUP_STATE_CHOICES = (
        ("pending",   "قيد المتابعة"),
        ("due_today", "مستحق اليوم"),
        ("overdue",   "متأخر"),
        ("archived",  "مؤرشف"),
    )
    FOLLOWUP_COLOR = {
        "pending":   "#2563eb",  # أزرق
        "due_today": "#d97706",  # برتقالي
        "overdue":   "#dc2626",  # أحمر
        "archived":  "#64748b",  # رمادي
    }

    kind = models.CharField(max_length=20, choices=KIND_CHOICES, default="incoming_internal")

    # ── أرقام الكتاب ──
    # الصادر: our_number = رقم الصادر الخاص بنا
    # الوارد: our_number = رقم الوارد الخاص بنا، sender_number = رقم صادر الجهة المرسلة
    # صيغة `our_number` وتحليلها وعرضها كلّها في `core/numbering.py` — المصدر الوحيد.
    our_number = models.CharField("رقمنا (صادر/وارد)", max_length=50, default="", db_index=True)
    sender_number = models.CharField("رقم صادر الجهة", max_length=50, blank=True, default="")
    # ── حقول التطبيع ──
    legacy_number = models.CharField(
        "الرقم الأصلي قبل التطبيع",
        max_length=80, blank=True, default="",
        help_text="يحفظ النص الأصلي للرقم قبل عملية التطبيع — للتوافق التاريخي",
    )
    # هوية السجل في قاعدة المصدر — للدمج/التحديث عند إعادة الاستعادة (مثل "IIMAIL_2025#1234")
    # فارغ = كتاب أُضيف داخل التطبيق ولا يُلمَس أثناء الاستعادة
    source_ref = models.CharField(
        "هوية المصدر",
        max_length=40, blank=True, default="", db_index=True,
        help_text='"{TABLE}#{ID}" في قاعدة المصدر — يربط الكتاب بصفّه الأصلي للدمج المستقبلي',
    )
    is_training = models.BooleanField(
        "كتاب تدريب",
        default=False, db_index=True,
        help_text=(
            "أُدخل أثناء فترة التدريب. رقمه من فضاء منفصل (T…) فلا يستهلك السلسلة "
            "الرسمية، ويُحذف كلّه عند التدشين لأن أصله موجود في النظام القديم."
        ),
    )
    # للأرقام المركّبة قديم-X-Y: series_no = X (السلسلة)، version = Y (الرقم الفرعي)
    series_no = models.PositiveIntegerField(
        "رقم السلسلة",
        null=True, blank=True, db_index=True,
        help_text="الجزء الأول من الرقم المركّب (X في X-Y)",
    )
    version = models.PositiveSmallIntegerField(
        "الرقم الفرعي",
        null=True, blank=True,
        help_text="الجزء الثاني من الرقم المركّب (Y في X-Y)",
    )

    title = models.CharField("العنوان", max_length=300)
    document_type = models.CharField("تصنيف المستند", max_length=100, blank=True, default="")
    secret_level = models.CharField(max_length=10, choices=SECRET_CHOICES, default="normal")

    # ── التواريخ ──
    date = models.DateField("تاريخنا", default=timezone.localdate)
    sender_date = models.DateField("تاريخ الجهة المصدرة", blank=True, null=True)

    margin = models.TextField("ملاحظات", blank=True)

    # ── الجهات (M2M — يدعم جهات متعددة كـ Tags) ──
    issuing_entities = models.ManyToManyField(
        Entity, related_name="issued_books", blank=True, verbose_name="الجهات المصدرة"
    )
    receiving_entities = models.ManyToManyField(
        Entity, related_name="received_books", blank=True, verbose_name="الجهات المستلمة"
    )

    # ── أرشيف أسماء الجهات المحذوفة (نصّ فقط) ──
    # عند حذف جهة نهائياً، نحفظ اسمها هنا قبل قطع الـ M2M،
    # ليبقى السجل التاريخي للكتاب مقروءاً ولا تُفقَد المعلومة.
    archived_issuing_names = models.JSONField(
        "أسماء جهات مُصدِرة محذوفة (أرشيف)", default=list, blank=True
    )
    archived_receiving_names = models.JSONField(
        "أسماء جهات مُستلمة محذوفة (أرشيف)", default=list, blank=True
    )

    # ── الوُسوم (M2M اختياري — تصنيف ديناميكي) ──
    tags = models.ManyToManyField(
        Tag, related_name="books", blank=True, verbose_name="الوُسوم"
    )

    # ── المتابعة (موحّدة) ──
    # تاريخ المتابعة: فارغ = لا متابعة (الكتاب مؤرشف ابتداءً)
    due_date = models.DateField("تاريخ المتابعة", blank=True, null=True)
    # علم الأرشفة اليدوية: True عند إنهاء المتابعة أو الإدخال بلا due_date
    is_archived = models.BooleanField("مؤرشف", default=True)

    # ── التدقيق ──
    created_by = models.ForeignKey(User, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    # بُعدُ النطاق. اختياريّ في المخطّط ومُعبَّأ بالكامل في الواقع (هجرة 0064):
    # تنصيبٌ جديدٌ قبل بذر الأقسام يجب أن يعمل، وصفٌّ بلا قسمٍ يراه المدير فقط.
    department = models.ForeignKey('Department', null=True, blank=True, on_delete=models.PROTECT,
                                   related_name='books', verbose_name='القسم')
    # «بعهدة مَن» الآن — **مؤشّرٌ إلى آخر صفّ عهدة، لا نسخةٌ ثانيةٌ للحقيقة.**
    # الاسمُ والقسمُ والوقتُ كلُّها في `CustodyEvent`؛ ولو نُسخت هنا لانفرجت
    # عنه عند أوّل كتابةٍ على جنب — وهو ما يُضيع المستند. يكتبه
    # `custody_service.record_custody` وحدَه.
    current_custody = models.ForeignKey('CustodyEvent', null=True, blank=True,
                                        on_delete=models.SET_NULL, related_name='+',
                                        verbose_name='بعهدة')
    is_deleted = models.BooleanField(default=False)

    deleted_at = models.DateTimeField(null=True, blank=True)
    deleted_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="deleted_books")

    def save(self, *args, **kwargs):
        # تطبيع نوع المستند بمصدر واحد (يغلق legacy_restore/Admin وأي مسار يتجاوز BookForm.clean_document_type)
        if self.document_type:
            from core.document_types import normalize_document_type_value
            self.document_type = normalize_document_type_value(self.document_type)
        # القاعدة الذهبية: لا due_date ⇒ مؤرشف تلقائياً
        if not self.due_date:
            self.is_archived = True
        super().save(*args, **kwargs)

    @property
    def followup_state(self):
        """
        حالة المتابعة المحسوبة (مصدر الحقيقة الوحيد).
        Returns one of: 'pending', 'due_today', 'overdue', 'archived'.
        """
        if self.is_archived or not self.due_date:
            return "archived"
        today = timezone.localdate()
        if self.due_date < today:
            return "overdue"
        if self.due_date == today:
            return "due_today"
        return "pending"

    @property
    def followup_label(self):
        """التسمية العربية لحالة المتابعة الحالية."""
        return dict(self.FOLLOWUP_STATE_CHOICES).get(self.followup_state, "")

    @property
    def delay_days(self):
        """عدد الأيام منذ/حتى تاريخ الاستحقاق (موجب دائماً)."""
        if not self.due_date or self.is_archived:
            return 0
        return abs((timezone.localdate() - self.due_date).days)

    @property
    def is_incoming(self):
        return self.kind in ("incoming_internal", "incoming_external")

    @property
    def is_outgoing(self):
        return self.kind in ("outgoing_internal", "outgoing_external")

    @property
    def is_internal(self):
        return self.kind in ("outgoing_internal", "incoming_internal")

    @property
    def kind_direction(self):
        """Returns 'incoming' or 'outgoing' for backward compatibility."""
        return "incoming" if self.is_incoming else "outgoing"

    @property
    def kind_scope(self):
        """Returns 'internal' or 'external'."""
        return "internal" if self.is_internal else "external"

    @property
    def kind_label(self):
        """Arabic label for display."""
        labels = dict(self.KIND_CHOICES)
        return labels.get(self.kind, self.kind)

    @property
    def attachment(self):
        """Latest non-deleted attachment — uses prefetch cache when available."""
        try:
            cache = self._prefetched_objects_cache.get('attachments')
            if cache is not None:
                active = [a for a in cache if not a.is_deleted]
                return active[0] if active else None
        except AttributeError:
            pass
        return self.attachments.filter(is_deleted=False).first()

    @property
    def first_issuing_entity(self):
        """First issuing entity for template display."""
        entities = self.issuing_entities.all()
        return entities[0] if entities else None

    @property
    def first_receiving_entity(self):
        """First receiving entity for template display."""
        entities = self.receiving_entities.all()
        return entities[0] if entities else None


    # ── رقم القيد: كل التحليل والعرض من `core/numbering.py` وحده ──
    #
    # القاعدة (قرار المالك): سلسلةٌ واحدة لا نهائية أساسها أرقام 2026 بلا تصفير
    # سنوي، وبيانات 2025 وما قبلها موسومةٌ بسنة إضافتها، ولا بادئة سجلّ في الرقم
    # إطلاقاً — النوع يحمله عمود `kind`. الخصائص أدناه واجهةُ عرضٍ رفيعة فوق
    # الوحدة؛ لا تُعِد كتابة قاعدةٍ هنا.

    @property
    def our_number_year(self):
        """وسم السنة للكتب المنقولة من سجلّات ما قبل 2026، وإلا '' للسلسلة الجارية."""
        return numbering.year_tag(self.our_number)

    @property
    def our_number_sequence(self):
        """الرقم المجرّد كما هو مكتوب على الورق — بلا سنة وبلا بادئة."""
        return numbering.display(self.our_number)

    @property
    def our_number_display(self):
        """
        الرقم كسطرٍ واحد للعرض في أي مكان: «2433» أو «825/2025» أو «T131» أو ''.

        القائمة الموحّدة تفصل الجزأين في عنصرَين لتُصغّر الوسم بصرياً؛ وكل موضعٍ
        آخر (التفاصيل، التقارير، الأضابير، البريد، المهملات) يستعمل هذا. بدونه
        كانت تلك الصفحات تعرض المخزَّن الخام «20250825» فيخالف ما تعرضه القائمة
        وما هو مطبوع على الورقة.
        """
        seq = numbering.display(self.our_number)
        if not seq:
            return ''
        tag = numbering.year_tag(self.our_number)
        return f'{seq}/{tag}' if tag else seq

    @property
    def our_number_register_label(self):
        """تسمية السجلّ — من نوع الكتاب لا من الرقم (البادئة أُلغيت)."""
        return dict(BOOK_KIND_CHOICES).get(self.kind, '')

    @property
    def our_number_is_compound(self):
        """الصيغة المركّبة (X-Y) انتهت بإعادة البناء؛ تبقى للبيانات غير المُرحَّلة."""
        return self.series_no is not None and self.version is not None

    @property
    def our_number_is_numberless(self):
        """كتاب بلا رقم رسمي — استثناءٌ معتمَد في النظام (الحقل فارغ)."""
        return numbering.parse(self.our_number).kind_of == 'blank'

    @property
    def our_number_is_training(self):
        """كتاب أُدخل في فترة التدريب (فضاء T) — يُحذف عند التدشين."""
        return numbering.parse(self.our_number).kind_of == 'training'

    @property
    def our_number_explained(self):
        """شرحٌ نصّيّ لرقم القيد، لتلميح الواجهة — يميّز **رقمنا** عن رقم الجهة."""
        p = numbering.parse(self.our_number)
        label = self.our_number_register_label

        if p.kind_of == 'blank':
            return 'كتاب بلا رقم قيد — استثناء معتمَد في النظام.'
        if p.kind_of == 'training':
            return (f'كتاب تدريب رقم {p.seq} — خارج السلسلة الرسمية، '
                    f'ويُحذف عند تدشين النظام.')
        if p.kind_of == 'tagged':
            return (f'رقم قيدنا: {p.seq} من سجلّ سنة {p.year} · {label} — '
                    f'الوسم السنوي يفصله عن رقم السلسلة الجارية. '
                    f'هذا رقمنا نحن، وليس العدد المطبوع على المستند.')
        if self.kind in numbering.MANUAL_KINDS:
            return (f'رقم الصادر: {p.raw} — يصدر من مكتب السيد المدير العام، '
                    f'ولا يخضع لسلسلة النظام.')
        return (f'رقم قيدنا: {p.raw} · {label} — من السلسلة الجارية المستمرّة '
                f'بلا تصفير سنوي. هذا رقمنا نحن، وليس العدد المطبوع على المستند.')

    def __str__(self):
        return f"{self.our_number} - {self.title}"


    #: الافتراضيّ لا يرى المحذوف؛ ``all_objects`` مخرجٌ صريح للسلّة والاستعادة.
    objects = SoftDeleteManager()
    all_objects = models.Manager()

    class Meta:
        verbose_name = "كتاب"
        verbose_name_plural = "الكتب"
        ordering = ['-date']
        indexes = [
            models.Index(fields=['is_deleted', 'created_by', '-date'], name='book_list_main_idx'),
            models.Index(fields=['is_deleted', 'kind', 'is_archived'], name='book_filters_idx'),
            models.Index(fields=['our_number'], name='our_number_idx'),
            models.Index(fields=['legacy_number'], name='legacy_number_idx'),
            models.Index(fields=['sender_number'], name='sender_number_idx'),
            models.Index(fields=['title'], name='title_idx'),
            models.Index(fields=['due_date', 'is_archived'], name='due_date_idx'),
            models.Index(fields=['created_by', 'is_deleted'], name='user_deleted_idx'),
            models.Index(fields=['is_archived', 'due_date'], name='followup_idx'),
            # فهرس مركّب لتسريع الفلترة بحالة المتابعة + النوع (للجداول الكبيرة >50k)
            models.Index(fields=['is_archived', 'due_date', 'kind'], name='followup_kind_idx'),
            # ─ فهارس جديدة (Phase 2) ─
            models.Index(fields=['is_deleted'], name='book_is_deleted_idx'),
            models.Index(fields=['kind'], name='book_kind_idx'),
            models.Index(fields=['is_deleted', 'created_by', 'is_archived'], name='book_user_status_idx'),
            # فهرس التاريخ — يسرّع الفرز الافتراضي order_by('-date') في كل قوائم الكتب والأضابير
            models.Index(fields=['-date', '-id'], name='book_date_idx'),
        ]
        constraints = [
            # التفرّد ضمانةٌ على ما **يُصدره النظام**، لا على ما يُسجّله من الورق.
            #
            # ثلاثة استثناءات، كلٌّ منها مفروضٌ بدليل مقيس:
            #  • `source_ref` غير فارغ = صفٌّ منقولٌ من سجلّ ورقيّ. وذلك السجلّ فيه
            #    تكرارٌ حقيقي: الكاتب كتب «٨٢٥» على مستندين مختلفين في اليوم نفسه
            #    (مُتحقَّق بالعين على المستندين). فرضُ التفرّد عليه يُجبرنا على
            #    تزوير أحدهما.
            #  • الصادر الخارجي رقمه من مكتب المدير العام لا من سلسلتنا، وتكراره
            #    مشروع (بياناته: 0، 109، 1555، 27189 — بلا تسلسل).
            #  • المحذوف لا يحجز رقمه: كتابٌ حُذف كان يمنع إعادة إدخال رقمه
            #    الشرعي، فيعجز الموظّف عن تصحيح خطئه.
            models.UniqueConstraint(
                fields=['department', 'our_number', 'kind'],
                condition=(~models.Q(our_number='')
                           & models.Q(source_ref='')
                           & ~models.Q(kind='outgoing_external')
                           & models.Q(is_deleted=False)),
                name='uniq_book_number_kind_dept',
            ),
        ]


class Attachment(models.Model):
    """
    نموذج المرفق - تخزين الملفات المرفوعة مع الكتب
    """
    
    book = models.ForeignKey(Book, on_delete=models.PROTECT, related_name="attachments")
    file = models.FileField(upload_to=book_attachment_path)
    uploaded_at = models.DateTimeField(auto_now_add=True)
    is_deleted = models.BooleanField(default=False)

    deleted_at = models.DateTimeField(null=True, blank=True)
    deleted_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="deleted_attachments")


    #: الافتراضيّ لا يرى المحذوف؛ ``all_objects`` مخرجٌ صريح للسلّة والاستعادة.
    objects = SoftDeleteManager()
    all_objects = models.Manager()

    class Meta:
        indexes = [
            models.Index(fields=['book', 'is_deleted']),
            models.Index(fields=['-uploaded_at']),
        ]

    def __str__(self):
        return self.file.name

    @property
    def filename(self):
        """اسم الملف المجرّد (دون مسار التخزين) للعرض."""
        import os
        return os.path.basename(self.file.name) if self.file else ""


class AttachmentVersion(models.Model):
    """نموذج الإصدار المحسّن لتتبع التغييرات والدمج"""
    MERGE_TYPE_CHOICES = (
        ('none', 'بدون دمج'),
        ('pdf', 'دمج PDF'),
        ('image', 'دمج صور'),
        ('mixed', 'دمج مختلط'),
    )
    
    attachment = models.ForeignKey(Attachment, on_delete=models.CASCADE, related_name="versions")
    file = models.FileField(upload_to=book_attachment_path)
    version_number = models.PositiveIntegerField(default=1)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    note = models.CharField(max_length=255, blank=True)
    
    # حقول جديدة للدمج الذكي
    merge_type = models.CharField(max_length=20, choices=MERGE_TYPE_CHOICES, default='none')
    merged_from_version = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True, related_name='merged_to')
    file_size = models.BigIntegerField(default=0)  # حجم الملف بالبايت
    page_count = models.PositiveIntegerField(null=True, blank=True)  # عدد الصفحات (للـ PDFs)
    is_merged = models.BooleanField(default=False)  # هل هذا الإصدار نتيجة دمج
    merge_metadata = models.JSONField(default=dict, blank=True)  # بيانات وصفية للدمج

    class Meta:
        ordering = ["-version_number", "-created_at"]
        indexes = [
            models.Index(fields=['attachment', '-version_number']),
            models.Index(fields=['is_merged', 'created_at']),
        ]

    def __str__(self):
        return f"{self.attachment_id} v{self.version_number}"


class MergeLog(models.Model):
    """تسجيل عمليات الدمج للتتبع والتدقيق"""
    MERGE_ACTION_CHOICES = (
        ('merge', 'دمج ملفات'),
        ('delete', 'حذف ملف'),
        ('upload', 'رفع ملف'),
        ('restore', 'استعادة نسخة'),
    )
    
    attachment = models.ForeignKey(Attachment, on_delete=models.SET_NULL, null=True, blank=True, related_name="merge_logs")
    action = models.CharField(max_length=20, choices=MERGE_ACTION_CHOICES)
    performed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    performed_at = models.DateTimeField(auto_now_add=True)
    
    # معلومات الدمج
    source_version = models.ForeignKey(AttachmentVersion, on_delete=models.SET_NULL, null=True, blank=True, related_name='as_source')
    target_version = models.ForeignKey(AttachmentVersion, on_delete=models.SET_NULL, null=True, blank=True, related_name='as_target')
    
    # تفاصيل العملية
    description = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=(('success', 'نجح'), ('failed', 'فشل'), ('pending', 'قيد التنفيذ')), default='pending')
    error_message = models.TextField(blank=True)
    
    class Meta:
        ordering = ['-performed_at']
        indexes = [
            models.Index(fields=['attachment', '-performed_at']),
            models.Index(fields=['action', 'status']),
        ]
    
    def __str__(self):
        return f"{self.get_action_display()} - {self.attachment_id} by {self.performed_by}"


class Notification(models.Model):
    """إشعار داخل التطبيق — يدعم التصنيف، الأولوية، والإحالة لكيان."""

    CATEGORY_CHOICES = (
        ('book',       'كتاب'),
        ('attachment', 'مرفق'),
        ('extraction', 'استخراج بيانات'),
        ('merge',      'دمج ملفات'),
        ('email',      'بريد إلكتروني'),
        ('system',     'نظام'),
    )

    PRIORITY_INFO    = 'info'
    PRIORITY_WARNING = 'warning'
    PRIORITY_URGENT  = 'urgent'
    PRIORITY_CHOICES = (
        (PRIORITY_INFO,    'معلومة'),
        (PRIORITY_WARNING, 'تحذير'),
        (PRIORITY_URGENT,  'عاجل'),
    )

    user        = models.ForeignKey(User, on_delete=models.CASCADE, related_name="notifications")
    title       = models.CharField('العنوان', max_length=200, blank=True, default='')
    message     = models.TextField()
    category    = models.CharField('الفئة', max_length=20, choices=CATEGORY_CHOICES, default='system')
    priority    = models.CharField('الأولوية', max_length=10, choices=PRIORITY_CHOICES, default=PRIORITY_INFO)
    link_url    = models.CharField('الرابط', max_length=500, blank=True, default='',
                                   help_text='URL للإحالة عند النقر على الإشعار')
    is_read     = models.BooleanField(default=False)
    read_at     = models.DateTimeField('تاريخ القراءة', null=True, blank=True)
    created_at  = models.DateTimeField(auto_now_add=True)
    attachment  = models.ForeignKey('Attachment', on_delete=models.CASCADE, null=True, blank=True, related_name='notifications')

    class Meta:
        verbose_name = 'إشعار'
        verbose_name_plural = 'الإشعارات'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'is_read', '-created_at'], name='notif_user_unread_idx'),
            models.Index(fields=['category', '-created_at'], name='notif_category_idx'),
            models.Index(fields=['priority', '-created_at'], name='notif_priority_idx'),
        ]

    def __str__(self):
        return f"[{self.get_priority_display()}] {self.title or self.message[:40]}"

    def mark_read(self):
        if not self.is_read:
            self.is_read = True
            self.read_at = timezone.now()
            self.save(update_fields=['is_read', 'read_at'])


class UserPassword(models.Model):
    """حفظ كلمات المرور المؤقتة للمستخدمين الجدد - محفوظة بشكل آمن بالـ hashing"""
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="temp_password")
    password_hash = models.CharField(max_length=255)  # كلمة المرور مشفرة بـ Django's make_password
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    is_viewed = models.BooleanField(default=False)
    
    def set_password(self, raw_password):
        """تعيين كلمة مرور بشكل آمن باستخدام hashing"""
        self.password_hash = make_password(raw_password)
    
    def check_password(self, raw_password):
        """التحقق من كلمة المرور بمقارنتها مع الـ hash"""
        return check_password(raw_password, self.password_hash)
    
    def is_expired(self):
        return timezone.now() > self.expires_at
    
    def __str__(self):
        return f"كلمة مرور {self.user.username}"


class BookComment(models.Model):
    """تعليقات المستخدمين على الكتب — يحتفظ بـ snapshot للاسم لحفظ التدقيق عند حذف المستخدم."""
    book = models.ForeignKey(Book, on_delete=models.CASCADE, related_name='comments', verbose_name='الكتاب')
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='book_comments', verbose_name='المستخدم'
    )
    author_snapshot = models.CharField(
        'اسم الكاتب (snapshot)', max_length=150, blank=True, default='',
        help_text='يُحفظ عند الإنشاء ويبقى حتى لو حُذف المستخدم'
    )
    content = models.TextField(verbose_name='محتوى التعليق')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='تاريخ الإنشاء')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='تاريخ التعديل')
    is_edited = models.BooleanField(default=False, verbose_name='تم التعديل')

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'تعليق'
        verbose_name_plural = 'التعليقات'
        indexes = [
            models.Index(fields=['book', '-created_at']),
        ]

    def save(self, *args, **kwargs):
        # ملء snapshot عند الإنشاء فقط
        if not self.pk and self.created_by_id and not self.author_snapshot:
            self.author_snapshot = (self.created_by.get_full_name() or self.created_by.username)[:150]
        super().save(*args, **kwargs)

    @property
    def author_display(self):
        if self.created_by_id and self.created_by:
            return self.created_by.get_full_name() or self.created_by.username
        return self.author_snapshot or 'محذوف'

    def __str__(self):
        return f"تعليق {self.author_display} على {self.book.our_number}"


class BookHistory(models.Model):
    """سجل تاريخي لكل عمل على كتاب — audit trail."""

    ACTION_CHOICES = (
        ('create',             'إنشاء'),
        ('edit',               'تعديل'),
        ('update_notes',       'تحديث ملاحظات'),
        ('status',             'تغيير الحالة'),
        ('delete',             'حذف (soft)'),
        ('restore',            'استعادة'),
        ('overdue',            'تجاوز الاستحقاق'),
        ('attach',             'إرفاق ملف'),
        ('attach-fail',        'فشل إرفاق'),
        ('delete-attachment',  'حذف مرفق'),
        ('replace-attachment', 'استبدال مرفق'),
        ('restore-attachment', 'استعادة مرفق'),
        ('merge',              'دمج ملفات'),
        ('merge-pages',        'دمج صفحات'),
        ('remove-pages',       'إزالة صفحات'),
        # ── نسيجُ الوثائق (BookLink) ──
        ('link-added',         'ربط بكتاب'),
        ('link-removed',       'فكّ ربط'),
        # ── عمودُ التسيير (BookReferral) ──
        ('referral',           'تفريق/إحالة'),
        ('referral-received',  'استلام الإحالة'),
        ('referral-done',      'إنجاز الإحالة'),
        ('referral-returned',  'إعادة الإحالة'),
        ('reminder',           'تنبيه'),
        # ── العهدة (CustodyEvent) ──
        ('custody',            'انتقال عهدة'),
        # ── القيدُ في دفترِ قسم (BookRegistration) ──
        ('registered',         'قُيّد في دفتر قسم'),
    )

    book = models.ForeignKey(Book, on_delete=models.CASCADE, related_name="history")
    action = models.CharField(max_length=50, choices=ACTION_CHOICES, db_index=True)
    by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    by_snapshot = models.CharField(
        'اسم المنفّذ (snapshot)', max_length=150, blank=True, default='',
        help_text='يُحفظ عند الإنشاء لضمان بقاء سجل التدقيق حتى بعد حذف المستخدم'
    )
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    attachment = models.ForeignKey('Attachment', on_delete=models.SET_NULL, null=True, blank=True, related_name='histories')

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['book', '-created_at']),
            models.Index(fields=['action', '-created_at']),
        ]

    def save(self, *args, **kwargs):
        if not self.pk and self.by_id and not self.by_snapshot:
            self.by_snapshot = (self.by.get_full_name() or self.by.username)[:150]
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.book_id} · {self.get_action_display()} · {self.created_at:%Y-%m-%d %H:%M}"


class ScanJob(models.Model):
    STATUS_CHOICES = (
        ("captured", "تم الالتقاط"),
        ("attached", "تم الربط"),
        ("failed", "فشل"),
        ("canceled", "ملغي"),
    )

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="scan_jobs")
    book = models.ForeignKey(Book, on_delete=models.SET_NULL, null=True, blank=True, related_name="scan_jobs")
    attachment = models.ForeignKey(Attachment, on_delete=models.SET_NULL, null=True, blank=True, related_name="scan_jobs")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="captured")
    file_name = models.CharField(max_length=255)
    inbox_path = models.CharField(max_length=500)
    created_at = models.DateTimeField(auto_now_add=True)
    accepted_at = models.DateTimeField(null=True, blank=True)
    error_message = models.TextField(blank=True)

    def __str__(self):
        return f"ScanJob({self.id}) {self.status} - {self.file_name}"


class RestoreJob(models.Model):
    """
    مهمّة دمج بيانات من المصدر القديم — تعمل خارج دورة الطلب.

    لماذا صفّ في قاعدة البيانات لا متغيّر في الذاكرة: الدمج يستغرق دقائق إلى
    ساعات، فلا يجوز أن يحمله طلب HTTP (ينتهي المهلة والمتصفّح يظنّ أنه فشل بينما
    هو يعمل). وبجعل الحالة صفّاً مشتركاً: يستطيع المستخدم إغلاق الصفحة والعودة،
    ويراها زميله، وتبقى الخلاصة بعد الانتهاء.

    الاعتماد **لا يُحفظ هنا أبداً** — يُمرَّر إلى العملية الابنة عبر بيئتها.
    """
    STATUS_QUEUED = 'queued'
    STATUS_RUNNING = 'running'
    STATUS_DONE = 'done'
    STATUS_FAILED = 'failed'
    STATUS_CANCELLED = 'cancelled'
    STATUS_CHOICES = (
        (STATUS_QUEUED, 'في الانتظار'),
        (STATUS_RUNNING, 'قيد التنفيذ'),
        (STATUS_DONE, 'انتهت'),
        (STATUS_FAILED, 'فشلت'),
        (STATUS_CANCELLED, 'أُلغيت'),
    )
    LIVE_STATUSES = (STATUS_QUEUED, STATUS_RUNNING)

    status = models.CharField('الحالة', max_length=12, choices=STATUS_CHOICES,
                              default=STATUS_QUEUED, db_index=True)
    phase = models.CharField('المرحلة', max_length=200, blank=True, default='')
    done_count = models.PositiveIntegerField('المُنجَز', default=0)
    total_count = models.PositiveIntegerField('الإجمالي', default=0)
    params = models.JSONField('المعاملات (بلا اعتماد)', default=dict, blank=True)
    summary = models.JSONField('الخلاصة', default=dict, blank=True)
    error_message = models.TextField('الخطأ', blank=True, default='')
    cancel_requested = models.BooleanField('طُلب الإلغاء', default=False)
    pid = models.PositiveIntegerField('معرّف العملية', null=True, blank=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name='restore_jobs')
    created_at = models.DateTimeField('أُنشئت', auto_now_add=True)
    updated_at = models.DateTimeField('آخر تحديث', auto_now=True)
    finished_at = models.DateTimeField('انتهت في', null=True, blank=True)

    class Meta:
        verbose_name = 'مهمّة دمج'
        verbose_name_plural = 'مهامّ الدمج'
        ordering = ['-created_at']

    def __str__(self):
        return f"RestoreJob({self.id}) {self.status} — {self.phase or '—'}"

    @property
    def is_live(self):
        return self.status in self.LIVE_STATUSES

    @property
    def percent(self):
        if not self.total_count:
            return 0
        return min(100, round(100 * self.done_count / self.total_count))

    @classmethod
    def running(cls):
        """المهمّة الحيّة إن وُجدت — تمنع تشغيل دمجَين على المصدر نفسه."""
        return cls.objects.filter(status__in=cls.LIVE_STATUSES).order_by('-created_at').first()

    def touch(self, *, phase=None, done=None, total=None):
        """تحديث تقدّم خفيف — يُكتب بـUPDATE مباشر ولا يقرأ الصفّ."""
        fields = {'updated_at': timezone.now()}
        if phase is not None:
            fields['phase'] = phase[:200]
        if done is not None:
            fields['done_count'] = done
        if total is not None:
            fields['total_count'] = total
        type(self).objects.filter(pk=self.pk).update(**fields)


# ===================================================
# AI Data Extraction Models
# ===================================================

class OCRResult(models.Model):
    """
    نتيجة الاستخراج الضوئي (OCR)
    تخزين النص المستخرج من الصورة
    """
    
    STATUS_CHOICES = [
        ('pending', 'قيد المعالجة'),
        ('completed', 'مكتمل'),
        ('failed', 'فشل'),
        ('manual_review', 'تحت المراجعة'),
    ]
    
    attachment = models.OneToOneField(Attachment, on_delete=models.SET_NULL, null=True, blank=True, related_name='ocr_result')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    
    # النص المستخرج
    raw_text = models.TextField(blank=True, null=True, help_text='النص الخام من OCR')
    cleaned_text = models.TextField(blank=True, null=True, help_text='النص المنظف والمصحح')
    
    # معلومات المعالجة
    confidence_score = models.FloatField(default=0.0, help_text='ثقة OCR (0-100)')
    processing_time = models.FloatField(default=0.0, help_text='وقت المعالجة بالثواني')
    
    # البيانات الوصفية
    language = models.CharField(max_length=50, default='ar', help_text='اللغة المكتشفة')
    num_characters = models.IntegerField(default=0, help_text='عدد الأحرف المستخرجة')
    
    # التتبع
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    processed_by = models.CharField(max_length=100, default='easyocr', help_text='محرك OCR المستخدم')
    error_message = models.TextField(blank=True, null=True, help_text='رسالة الخطأ إن وجدت')
    
    class Meta:
        verbose_name = 'نتيجة OCR'
        verbose_name_plural = 'نتائج OCR'
        ordering = ['-created_at']
    
    def __str__(self):
        name = self.attachment.file.name if self.attachment_id and self.attachment else 'deleted'
        return f"OCR - {name} ({self.status})"


class DataExtractionResult(models.Model):
    """
    نتائج استخراج البيانات المنظمة
    """
    
    STATUS_CHOICES = [
        ('pending', 'قيد المعالجة'),
        ('extracted', 'مستخرج'),
        ('reviewed', 'تم المراجعة'),
        ('approved', 'موافق عليه'),
        ('rejected', 'مرفوض'),
    ]
    
    ocr_result = models.OneToOneField(OCRResult, on_delete=models.SET_NULL, null=True, blank=True, related_name='extraction')
    attachment = models.OneToOneField(Attachment, on_delete=models.SET_NULL, null=True, blank=True, related_name='data_extraction')
    book = models.ForeignKey(Book, on_delete=models.SET_NULL, related_name='extractions', null=True, blank=True)
    
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending', db_index=True)

    # البيانات المستخرجة
    book_number = models.CharField(max_length=50, blank=True, null=True)
    book_number_confidence = models.FloatField(default=0.0)
    
    book_date = models.DateField(blank=True, null=True)
    book_date_confidence = models.FloatField(default=0.0)
    
    title = models.CharField(max_length=500, blank=True, null=True)
    title_confidence = models.FloatField(default=0.0)
    
    margin_text = models.TextField(blank=True, null=True)
    margin_confidence = models.FloatField(default=0.0)
    
    secret_level = models.CharField(max_length=20, choices=[('normal', 'اعتيادي'), ('secret', 'سري'), ('topsecret', 'سري للغاية')], blank=True, null=True)
    secret_level_confidence = models.FloatField(default=0.0)
    
    book_kind = models.CharField(max_length=20, choices=EXTRACTION_KIND_CHOICES, blank=True, null=True)
    book_kind_confidence = models.FloatField(default=0.0)
    
    # الجهات
    issuing_entity_candidates = models.JSONField(default=list)
    receiving_entity_candidates = models.JSONField(default=list)
    issuing_entity = models.ForeignKey(
        Entity,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='+',
        db_column='issuing_entity_id',
    )
    receiving_entity = models.ForeignKey(
        Entity,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='+',
        db_column='receiving_entity_id',
    )
    
    additional_data = models.JSONField(default=dict, blank=True)
    overall_confidence = models.FloatField(default=0.0)
    notes = models.TextField(blank=True, null=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    reviewed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='reviewed_extractions')
    reviewed_at = models.DateTimeField(blank=True, null=True)
    approved_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='approved_extractions')
    approved_at = models.DateTimeField(blank=True, null=True)
    
    class Meta:
        verbose_name = 'نتيجة استخراج البيانات'
        verbose_name_plural = 'نتائج استخراج البيانات'
        ordering = ['-created_at']
    
    def __str__(self):
        return f"Extraction - {self.book_number or 'N/A'} ({self.status})"


class LetterheadMemory(models.Model):
    """ذاكرة (ترويسة مستند → جهة مؤكَّدة) — تتعلّم من كلّ كتاب ممسوح يُحفَظ.

    تكسر سقف «الوحدات الداخلية غير المطبوعة»: حتى لو لم يُطبع اسمُ القسم على الورقة،
    فمستندات نفس المُرسِل تُسنَد دوماً لنفس الجهة؛ ومطابقة ترويسة مستندٍ جديد بترويسات
    سابقة تكشف جهته المؤكَّدة. مقيسٌ بترك-واحد على بيانات حقيقية: hit@3 ≈ 85% مقابل
    ≈16% لمطابقة اسم الجهة وحدها. تُملأ من حلقة الالتقاط عند الحفظ + أمر backfill.
    """
    letterhead = models.TextField(help_text='نصّ أعلى المستند (الترويسة) — مصدر التشابه')
    issuing_entity = models.ForeignKey(
        Entity, on_delete=models.CASCADE, null=True, blank=True,
        related_name='letterhead_as_issuer', verbose_name='الجهة المُصدِرة المؤكَّدة')
    receiving_entity = models.ForeignKey(
        Entity, on_delete=models.CASCADE, null=True, blank=True,
        related_name='letterhead_as_receiver', verbose_name='الجهة المستقبِلة المؤكَّدة')
    book = models.ForeignKey(Book, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'ذاكرة ترويسة'
        verbose_name_plural = 'ذاكرة الترويسات'
        ordering = ['-created_at']

    def __str__(self):
        return f"LetterheadMemory#{self.pk} → issuer={self.issuing_entity_id}"


class ExtractionFeedback(models.Model):
    """
    ملاحظات المستخدم لتحسين النموذج
    """
    
    FEEDBACK_TYPE_CHOICES = [
        ('correct', 'صحيح'),
        ('incorrect', 'خاطئ'),
        ('partial', 'جزئي'),
    ]
    
    extraction = models.ForeignKey(DataExtractionResult, on_delete=models.CASCADE, related_name='feedbacks')
    field_name = models.CharField(max_length=100)
    feedback_type = models.CharField(max_length=20, choices=FEEDBACK_TYPE_CHOICES)
    original_value = models.TextField()
    corrected_value = models.TextField(blank=True, null=True)
    reason = models.TextField(blank=True, null=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='extraction_feedbacks')
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        verbose_name = 'ملاحظة الاستخراج'
        verbose_name_plural = 'ملاحظات الاستخراج'
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.extraction} - {self.field_name}"


class ExtractionStatistics(models.Model):
    """إحصائيات أداء نظام الاستخراج"""
    date = models.DateField(auto_now_add=True)
    total_images_processed = models.IntegerField(default=0)
    successful_extractions = models.IntegerField(default=0)
    failed_extractions = models.IntegerField(default=0)
    manual_review_required = models.IntegerField(default=0)
    average_confidence = models.FloatField(default=0.0)
    median_confidence = models.FloatField(default=0.0)
    field_stats = models.JSONField(default=dict)
    average_processing_time = models.FloatField(default=0.0)
    min_processing_time = models.FloatField(default=0.0)
    max_processing_time = models.FloatField(default=0.0)
    
    class Meta:
        verbose_name = 'إحصائية الاستخراج'
        verbose_name_plural = 'إحصائيات الاستخراج'
        ordering = ['-date']
    
    def __str__(self):
        return f"Statistics - {self.date}"


class ScanPayload(models.Model):
    """حمولةُ اقتراحات المسح **دائمةً** — لأن ذهب التدريب لا يجوز أن يعبر كاشاً متطايراً.

    الجذر المقيس (2026-08-18): `_mint_scan_token` كان يضع الحمولة في الكاش وحده، وبلا
    `REDIS_CACHE_URL` يكون الكاش `LocMemCache` — **نسخةٌ لكلّ عمليّة**. فرمزٌ يُسكّ في
    عاملٍ لا يراه عاملٌ آخر يستقبل الحفظ، وكلّ إعادة تشغيلٍ تمحو المعلّق. والنتيجة
    ضياعُ زوج (قصاصة، حقيقة) **بلا رجعة** — وهو الحقل الوحيد الذي خسارتُه لا تُعوَّض:
    نصٌّ خاطئ يُعاد حسابه غداً، وقيمةٌ كتبها الكاتب بيده تضيع إلى الأبد.

    وقيمتها ارتفعت اليوم تحديداً: بإسكات اقتراح العدد صارت القيمة النهائيّة **ذهباً
    نظيفاً** — كتبها الكاتب وهو ينظر إلى الورقة، بلا انحياز قبولٍ لاقتراحٍ معروض.
    (قاعدةٌ عامّة: نهائيّاتُ حقلٍ تصلح تدريباً **ما دام ملؤه التلقائيّ مُطفأً**.)

    الكاش يبقى مسارَ السرعة، وهذا الجدول مسارُ الحقيقة: يُقرأ حين يخيب.
    """

    token = models.CharField(max_length=64, unique=True, db_index=True)
    data = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = 'حمولة مسح'
        verbose_name_plural = 'حمولات المسح'
        indexes = [models.Index(fields=['-created_at'])]

    def __str__(self):
        return f'ScanPayload({self.token[:12]}…)'


class ExtractionCache(models.Model):
    """ذاكرة تخزين مؤقت لنتائج الاستخراج"""
    image_hash = models.CharField(max_length=256, unique=True, db_index=True)
    cached_extraction = models.JSONField()
    hit_count = models.IntegerField(default=1)
    last_used = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        verbose_name = 'ذاكرة التخزين المؤقت'
        verbose_name_plural = 'ذاكرات التخزين المؤقت'
        ordering = ['-last_used']
    
    def __str__(self):
        return f"Cache - {self.image_hash[:16]}"


class SuggestionCategory(models.Model):
    """فئات الاقتراحات (مثلاً جهات إصدار، جهات استقبال)."""

    key = models.CharField(max_length=50, unique=True)
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'فئة اقتراح'
        verbose_name_plural = 'فئات الاقتراحات'
        ordering = ['key']

    def __str__(self):
        return self.name


class SuggestionItem(models.Model):
    """القيم المقترحة لكل فئة."""

    category = models.ForeignKey(SuggestionCategory, on_delete=models.CASCADE, related_name='items')
    value = models.CharField(max_length=255)
    order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'عنصر اقتراح'
        verbose_name_plural = 'عناصر الاقتراح'
        ordering = ['order', 'value']
        unique_together = ('category', 'value')

    def __str__(self):
        return f"{self.category.key}: {self.value}"


# =============================
# AI Integration Settings
# =============================
class EncryptedFieldsMixin(models.Model):
    """تشفيرٌ شفّاف لحقولٍ نصّيّة حسّاسة — مصدرٌ واحد للقاعدة.

    كان النمط مكتوباً داخل ``EmailSettings`` وحدها، بينما ``azure_key`` نصٌّ صريح
    في القاعدة — ازدواجُ معيارٍ في الملف نفسه. نسخُ النمط مرّةً ثانية كان
    سيُثبّت الازدواج بدل أن يرفعه، فوُحِّد هنا.

    العقد: القيمة في الذاكرة **دائماً** نصّ صريح، وفي القاعدة **دائماً** مشفّرة
    ببادئة ``enc::``؛ والمشفَّر مسبقاً لا يُشفَّر مرّتين.

    حدٌّ مقيس (``encrypt_text``): مدخلُ 32 محرفاً ⟵ 145، و84 ⟵ 209، و120 ⟵ 253.
    فـ``max_length=255`` يسع كلّ مفاتيح Azure الواقعيّة (32 أو 84) بهامش، ويضيق
    عند ~121 محرفاً فأكثر — عندها يلزم توسيع العمود بهجرة.
    """

    #: أسماء الحقول التي تُشفَّر — يعرّفها كل نموذج.
    ENCRYPTED_FIELDS: tuple = ()

    class Meta:
        abstract = True

    @classmethod
    def from_db(cls, db, field_names, values):
        from .encryption import decrypt_text, is_encrypted

        instance = super().from_db(db, field_names, values)
        for name in cls.ENCRYPTED_FIELDS:
            value = getattr(instance, name, '')
            if is_encrypted(value):
                try:
                    setattr(instance, name, decrypt_text(value))
                except Exception:
                    # مفتاحٌ مفقود أو مُبدَّل: نترك القيمة مشفّرة كما هي ليظهر
                    # العطل عند الاستعمال، لا أن يُبتلع صامتاً هنا.
                    pass
        return instance

    def save(self, *args, **kwargs):
        from .encryption import encrypt_text, is_encrypted

        plaintexts = {}
        for name in self.ENCRYPTED_FIELDS:
            value = getattr(self, name, '') or ''
            if value and not is_encrypted(value):
                plaintexts[name] = value
                setattr(self, name, encrypt_text(value))

        super().save(*args, **kwargs)

        # نُعيد النصّ الصريح إلى الكائن كي يبقى صالحاً للاستعمال بعد الحفظ.
        for name, plaintext in plaintexts.items():
            setattr(self, name, plaintext)


class AIIntegrationSettings(EncryptedFieldsMixin):
    """إعدادات ربط مزودات الذكاء الاصطناعي عبر الإنترنت.
    نخزّن اختيار المزود والمفاتيح ونمط العمل (تعطيل/تمكين/بديل عند ثقة منخفضة).
    """

    ENCRYPTED_FIELDS = ('azure_key',)

    PROVIDER_CHOICES = (
        ('offline', 'Offline (EasyOCR)'),
        ('azure', 'Azure Computer Vision'),
    )

    # Singleton pattern via unique row
    singleton = models.BooleanField(default=True, unique=True)

    enabled = models.BooleanField(default=False, help_text='تفعيل الربط بمزود أونلاين')
    provider = models.CharField(max_length=20, choices=PROVIDER_CHOICES, default='offline')
    fallback_on_low_confidence = models.BooleanField(
        default=True,
        help_text='استخدم المزود الأونلاين تلقائياً عند انخفاض الثقة من المزود المحلي'
    )
    low_confidence_threshold = models.FloatField(default=0.4, help_text='الحد الأدنى للثقة (0-1)')

    # Azure fields
    azure_endpoint = models.CharField(max_length=255, blank=True, help_text='مثال: https://<res>.cognitiveservices.azure.com')
    azure_key = models.CharField(max_length=255, blank=True)

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'إعدادات الذكاء الاصطناعي'
        verbose_name_plural = 'إعدادات الذكاء الاصطناعي'

    def __str__(self):
        return 'إعدادات الذكاء الاصطناعي (واحدة)'

    @classmethod
    def get_active_settings(cls) -> dict:
        """إرجاع dict جاهز للبناء على أساسه المزود."""
        from django.conf import settings as dj_settings
        data = {
            'AI_PROVIDER': getattr(dj_settings, 'AI_PROVIDER', 'offline'),
            'AI_FALLBACK_ON_LOW_CONFIDENCE': getattr(dj_settings, 'AI_FALLBACK_ON_LOW_CONFIDENCE', True),
            'AI_LOW_CONFIDENCE_THRESHOLD': float(getattr(dj_settings, 'AI_LOW_CONFIDENCE_THRESHOLD', 0.4)),
            'AI_AZURE_ENDPOINT': getattr(dj_settings, 'AI_AZURE_ENDPOINT', ''),
            'AI_AZURE_KEY': getattr(dj_settings, 'AI_AZURE_KEY', ''),
        }
        try:
            obj = cls.objects.first()
            if obj and obj.enabled:
                data['AI_PROVIDER'] = obj.provider
                data['AI_FALLBACK_ON_LOW_CONFIDENCE'] = obj.fallback_on_low_confidence
                data['AI_LOW_CONFIDENCE_THRESHOLD'] = obj.low_confidence_threshold
                if obj.azure_endpoint:
                    data['AI_AZURE_ENDPOINT'] = obj.azure_endpoint
                if obj.azure_key:
                    data['AI_AZURE_KEY'] = obj.azure_key
        except Exception:
            pass
        return data

class OCRFeedback(models.Model):
    """
    نموذج لحفظ التصحيحات اليدوية على نتائج OCR
    يُستخدم لبناء dataset للتدريب المستمر
    """
    LANGUAGE_CHOICES = (
        ('ar', 'عربي'),
        ('en', 'إنجليزي'),
        ('mixed', 'مختلط'),
    )
    
    # البيانات الأصلية
    image_path = models.CharField(max_length=500, help_text='مسار الصورة الأصلية')
    original_text = models.TextField(help_text='النص المستخرج من OCR')
    corrected_text = models.TextField(help_text='النص المصحح يدوياً')
    
    # البيانات الوصفية
    language = models.CharField(max_length=10, choices=LANGUAGE_CHOICES, default='ar')
    original_confidence = models.FloatField(default=0.0, help_text='ثقة OCR الأصلية')
    correction_type = models.CharField(
        max_length=50,
        choices=(
            ('minor', 'تصحيح بسيط'),
            ('moderate', 'تصحيح متوسط'),
            ('major', 'تصحيح كبير'),
        ),
        default='minor'
    )
    
    # معلومات المستخدم
    corrected_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='ocr_corrections'
    )
    corrected_at = models.DateTimeField(auto_now_add=True)
    
    # التدريب
    used_for_training = models.BooleanField(default=False, help_text='هل تم استخدامه في التدريب؟')
    training_date = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        verbose_name = 'تصحيح OCR'
        verbose_name_plural = 'تصحيحات OCR'
        ordering = ['-corrected_at']
        indexes = [
            models.Index(fields=['used_for_training', 'language']),
            models.Index(fields=['corrected_at']),
        ]
    
    def __str__(self):
        return f"تصحيح {self.id} - {self.language} - {self.correction_type}"
    
    @property
    def needs_training(self):
        """هل يحتاج هذا التصحيح إلى تدريب؟"""
        return not self.used_for_training and self.corrected_text.strip()
    
    def calculate_correction_type(self):
        """حساب نوع التصحيح تلقائياً"""
        from difflib import SequenceMatcher
        ratio = SequenceMatcher(None, self.original_text, self.corrected_text).ratio()
        
        if ratio > 0.9:
            self.correction_type = 'minor'
        elif ratio > 0.7:
            self.correction_type = 'moderate'
        else:
            self.correction_type = 'major'


class TrainingDataset(models.Model):
    """
    نموذج لإدارة datasets التدريب
    """
    DATASET_TYPE_CHOICES = (
        ('feedback', 'من التصحيحات اليدوية'),
        ('archive', 'من الأرشيف القديم'),
        ('synthetic', 'بيانات مولدة'),
    )
    
    STATUS_CHOICES = (
        ('pending', 'معلق'),
        ('processing', 'قيد المعالجة'),
        ('ready', 'جاهز'),
        ('used', 'مستخدم في التدريب'),
    )
    
    name = models.CharField(max_length=200, help_text='اسم Dataset')
    dataset_type = models.CharField(max_length=20, choices=DATASET_TYPE_CHOICES, default='feedback')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    
    # إحصائيات
    total_samples = models.IntegerField(default=0, help_text='عدد العينات')
    arabic_samples = models.IntegerField(default=0, help_text='عينات عربية')
    english_samples = models.IntegerField(default=0, help_text='عينات إنجليزية')
    
    # البيانات
    data_file = models.FileField(upload_to='training_datasets/', null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True, help_text='معلومات إضافية')
    
    # التواريخ
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    trained_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        verbose_name = 'Dataset تدريب'
        verbose_name_plural = 'Datasets التدريب'
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.name} ({self.status}) - {self.total_samples} عينة"


class OCRModelVersion(models.Model):
    """
    نموذج لتتبع إصدارات نموذج OCR
    """
    version = models.CharField(max_length=50, unique=True, help_text='رقم الإصدار')
    base_model = models.CharField(max_length=100, default='easyocr', help_text='النموذج الأساسي')
    
    # معلومات التدريب
    trained_on_dataset = models.ForeignKey(
        TrainingDataset,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='trained_models'
    )
    training_samples = models.IntegerField(default=0)
    training_duration = models.DurationField(null=True, blank=True)
    
    # مؤشرات الأداء
    avg_confidence = models.FloatField(default=0.0, help_text='متوسط الثقة')
    accuracy_arabic = models.FloatField(default=0.0, help_text='دقة العربية')
    accuracy_english = models.FloatField(default=0.0, help_text='دقة الإنجليزية')
    
    # الحالة
    is_active = models.BooleanField(default=False, help_text='النموذج النشط حالياً؟')
    is_production = models.BooleanField(default=False, help_text='جاهز للإنتاج؟')
    
    # البيانات
    model_file = models.FileField(upload_to='ocr_models/', null=True, blank=True)
    notes = models.TextField(blank=True, help_text='ملاحظات')
    
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        verbose_name = 'إصدار نموذج OCR'
        verbose_name_plural = 'إصدارات نماذج OCR'
        ordering = ['-created_at']
    
    def __str__(self):
        status = "نشط" if self.is_active else "غير نشط"
        return f"v{self.version} - {status}"
    
    def activate(self):
        """تفعيل هذا النموذج"""
        # إلغاء تفعيل جميع النماذج الأخرى
        OCRModelVersion.objects.filter(is_active=True).update(is_active=False)
        self.is_active = True
        self.save()


# =============================
# Book Sequence (Auto-numbering)
# =============================
class BookSequence(models.Model):
    """
    عدّاد تسلسلي **لا نهائي** لكل سجلّ — لا يتصفّر عند رأس السنة أبداً.

    أساسه أرقام سنة 2026 كما هي مثبَّتة في ختم الوارد: بعد 2432 يأتي 2433، في
    2027 و2028 وما بعدها. الرقم يُخزَّن مجرّداً بلا بادئة سجلّ وبلا سنة — النوع
    يحمله عمود `kind`، والتفرّد على (kind, our_number).

    الصادر الخارجي لا عدّاد له: رقمه يصدر من مكتب السيد المدير العام.
    وكتب السنوات السابقة موسومةٌ بسنتها ({السنة}{الرقم}) فهي خارج فضاء العدّاد.
    كل تحليلٍ أو تنسيق يمرّ عبر `core/numbering.py`.
    """
    #: السجلّات التي يمنحها النظام أرقاماً من سلسلته
    SERIES_KINDS = numbering.SERIES_KINDS

    # عدّادٌ لكلّ (قسم، نوع): كلّ قسمٍ يمسك دفتر ختمه الورقيّ الخاصّ به، وعدّادٌ
    # واحدٌ للشركة كان سيُجبر قسمين على تقاسم سلسلةٍ لا يتقاسمانها على الورق.
    department = models.ForeignKey('Department', null=True, on_delete=models.PROTECT,
                                   related_name='sequences', verbose_name='القسم')
    kind = models.CharField(
        max_length=20, choices=BOOK_KIND_CHOICES, verbose_name='نوع الكتاب'
    )
    prefix = models.CharField(
        max_length=20, blank=True, default='', verbose_name='البادئة (مهملة)',
        help_text='غير مستخدمة بعد التطبيع — يُحتفظ بها للتوافق'
    )
    year = models.PositiveSmallIntegerField(
        default=2026, verbose_name='سنة بدء العدّاد',
        help_text='سنة إنشاء/بذر العدّاد — للسجل فقط؛ لم يعد يُستخدم للتصفير (الترقيم دائم)'
    )
    next_number = models.PositiveIntegerField(
        default=1, verbose_name='الرقم التالي'
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('department', 'kind')
        verbose_name = 'عدّاد تسلسلي'
        verbose_name_plural = 'العدّادات التسلسلية'

    def __str__(self):
        label = dict(BOOK_KIND_CHOICES).get(self.kind, self.kind)
        return f"{label}: {self.format_number(self.kind, self.next_number)}"

    @classmethod
    def format_number(cls, kind, number, year=None, numberless=False):
        """الرقم كما يُكتب على الورق: مجرّد بلا بادئة ولا سنة.
        `numberless=True` ⇒ نصّ فارغ، فـ«بلا رقم» تعني لا رقم فعلاً.
        المعاملان `year`/`kind` يُقبلان للتوافق الرجعي ولا أثر لهما."""
        if numberless:
            return ''
        return numbering.format_series(number)

    @classmethod
    def resolve_department(cls, department=None):
        """القسمُ المقصود بالعدّاد — والافتراضيّ حين لا يُمرَّر.

        التوقيعُ متساهلٌ عمداً: مسارات الاستدعاء القديمة (الاستخراج، الحجز،
        شاشة العدّادات) لا تعرف القسم بعد، وإجبارها عليه اليوم يعني تعديلاً
        متزامناً في ملفّاتٍ تعمل عليها جلسةٌ أخرى. فتُسقَط إلى القسم الافتراضيّ
        — وهو الصواب حرفيّاً في وضع «قسم واحد».
        """
        if department is not None:
            return department
        from core.models import Department
        return Department.objects.filter(is_active=True).order_by('id').first()

    @classmethod
    def get_next(cls, kind, department=None):
        """إرجاع الرقم التالي دون استهلاكه (لا نهائي — لا تصفير سنوي)."""
        obj, _ = cls.objects.get_or_create(
            kind=kind, department=cls.resolve_department(department),
            defaults={'next_number': 1, 'year': timezone.now().year}
        )
        n = obj.next_number
        return {
            'kind': kind, 'number': n, 'year': obj.year,
            'formatted': cls.format_number(kind, n),
        }

    @classmethod
    def consume_next(cls, kind, numberless=False, department=None):
        """
        استهلاك الرقم الحالي — آمن من التسابق (SELECT FOR UPDATE)، بلا تصفير سنوي.

        `numberless=True` **لا يستهلك العدّاد**: الكتاب بلا رقم رسمي، فمنحه رقماً
        من السلسلة كان يبتلع رقماً لا يظهر على أي ورقة ويفتح فجوة في الدفتر.
        """
        if numberless:
            return {'kind': kind, 'number': None, 'year': None, 'formatted': ''}

        from django.db import transaction
        with transaction.atomic():
            obj = cls.objects.select_for_update().get_or_create(
                kind=kind, department=cls.resolve_department(department),
                defaults={'next_number': 1, 'year': timezone.now().year}
            )[0]
            current = obj.next_number
            obj.next_number += 1
            obj.save(update_fields=['next_number', 'updated_at'])
        return {
            'kind': kind, 'number': current, 'year': obj.year,
            'formatted': cls.format_number(kind, current),
        }


# =============================
# Book Number Reservation
# =============================
class BookNumberReservation(models.Model):
    """
    حجز رقم قيد لكتاب — يضمن عدم تعارض الأرقام بين المستخدمين.

    دورة الحياة:
        active    → المستخدم يكتب (محجوز، لم يُحفظ بعد)
        used      → تم الحفظ بنجاح
        voided    → ألغاه المستخدم يدوياً
        expired   → انتهت المهلة دون حفظ
        reactivated → أُعيد تفعيله بعد انتهاء الصلاحية
    """
    STATUS_ACTIVE      = 'active'
    STATUS_USED        = 'used'
    STATUS_VOIDED      = 'voided'
    STATUS_EXPIRED     = 'expired'
    STATUS_REACTIVATED = 'reactivated'
    STATUS_COOLDOWN    = 'cooldown'   # انقطاع قسريّ — محجوز لصاحبه أولوية 15د قبل التدوير

    STATUS_CHOICES = [
        (STATUS_ACTIVE,      'نشط'),
        (STATUS_USED,        'مُستخدم'),
        (STATUS_VOIDED,      'ملغي'),
        (STATUS_EXPIRED,     'منتهي الصلاحية'),
        (STATUS_REACTIVATED, 'مُعاد تفعيله'),
        (STATUS_COOLDOWN,    'فترة سماح'),
    ]

    VOID_REASON_CANCELLED   = 'user_cancelled'
    VOID_REASON_TIMEOUT     = 'timeout'
    VOID_REASON_YEAR_RESET  = 'year_reset'
    VOID_REASON_REACTIVATED = 'reactivated'
    VOID_REASON_FORCED      = 'forced_disconnect'   # انقطاع قسريّ (WS/heartbeat)
    VOID_REASON_RECYCLED    = 'recycled'            # سُحب وأُعيد تدويره لمستخدم آخر

    VOID_REASON_CHOICES = [
        (VOID_REASON_CANCELLED,   'ألغاه المستخدم'),
        (VOID_REASON_TIMEOUT,     'انتهت المهلة'),
        (VOID_REASON_YEAR_RESET,  'إعادة تعيين سنوية'),
        (VOID_REASON_REACTIVATED, 'أُعيد تفعيله'),
        (VOID_REASON_FORCED,      'انقطاع قسريّ'),
        (VOID_REASON_RECYCLED,    'أُعيد تدويره'),
    ]

    user         = models.ForeignKey(User, on_delete=models.CASCADE, verbose_name='المستخدم')
    kind         = models.CharField(max_length=20, choices=BOOK_KIND_CHOICES, verbose_name='نوع الكتاب')
    number       = models.PositiveIntegerField(verbose_name='رقم القيد')
    prefix       = models.CharField(max_length=20, blank=True, default='', verbose_name='البادئة')
    year         = models.PositiveSmallIntegerField(verbose_name='السنة')
    formatted    = models.CharField(max_length=60, verbose_name='الرقم المنسق')

    status       = models.CharField(max_length=15, choices=STATUS_CHOICES, default=STATUS_ACTIVE, verbose_name='الحالة', db_index=True)
    void_reason  = models.CharField(max_length=20, choices=VOID_REASON_CHOICES, blank=True, default='', verbose_name='سبب الإلغاء')
    note         = models.TextField(blank=True, default='', verbose_name='ملاحظة')

    # كتاب مرتبط (يُملأ عند الحفظ)
    book         = models.OneToOneField(
        'Book', null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='number_reservation',
        verbose_name='الكتاب المرتبط'
    )

    reserved_at  = models.DateTimeField(auto_now_add=True, verbose_name='وقت الحجز')
    expires_at   = models.DateTimeField(verbose_name='ينتهي في')
    used_at      = models.DateTimeField(null=True, blank=True, verbose_name='وقت الاستخدام')
    voided_at    = models.DateTimeField(null=True, blank=True, verbose_name='وقت الإلغاء')

    # ── الحضور اللحظيّ + إعادة التدوير بلا فجوات ──
    last_heartbeat = models.DateTimeField(null=True, blank=True, verbose_name='آخر نبضة حضور')
    cooldown_until = models.DateTimeField(null=True, blank=True, verbose_name='نهاية فترة السماح')
    is_recycled    = models.BooleanField(default=False, verbose_name='رقم مُدوّر')

    class Meta:
        verbose_name = 'حجز رقم قيد'
        verbose_name_plural = 'حجوزات أرقام القيود'
        ordering = ['-reserved_at']
        indexes = [
            models.Index(fields=['user', 'status']),
            models.Index(fields=['kind', 'year', 'number']),
        ]

    def __str__(self):
        return f"{self.formatted} [{self.get_status_display()}] - {self.user.username}"

    @property
    def is_live_status(self):
        return self.status in [self.STATUS_ACTIVE, self.STATUS_REACTIVATED]

    @property
    def is_expired(self):
        return self.is_live_status and timezone.now() > self.expires_at

    @property
    def remaining_seconds(self):
        if not self.is_live_status:
            return 0
        delta = self.expires_at - timezone.now()
        return max(0, int(delta.total_seconds()))

    def mark_used(self, book):
        self.status  = self.STATUS_USED
        self.book    = book
        self.used_at = timezone.now()
        self.save(update_fields=['status', 'book', 'used_at'])

    def mark_voided(self, reason=VOID_REASON_CANCELLED, note=''):
        self.status     = self.STATUS_VOIDED
        self.void_reason = reason
        self.note       = note
        self.voided_at  = timezone.now()
        self.save(update_fields=['status', 'void_reason', 'note', 'voided_at'])

    def mark_expired(self):
        self.status     = self.STATUS_EXPIRED
        self.void_reason = self.VOID_REASON_TIMEOUT
        self.voided_at  = timezone.now()
        self.save(update_fields=['status', 'void_reason', 'voided_at'])

    def reactivate(self, extra_minutes=45):
        """إعادة تفعيل حجز منتهي الصلاحية."""
        self.status    = self.STATUS_REACTIVATED
        self.expires_at = timezone.now() + timedelta(minutes=extra_minutes)
        self.void_reason = ''
        self.save(update_fields=['status', 'expires_at', 'void_reason'])

    def touch_heartbeat(self):
        """تحديث نبضة الحضور (WS/ping) — لا تُغيّر الحالة."""
        self.last_heartbeat = timezone.now()
        self.save(update_fields=['last_heartbeat'])

    def enter_cooldown(self, minutes):
        """انقطاع قسريّ: يبقى الرقم محجوزاً لصاحبه فترة سماح قبل التدوير لغيره."""
        now = timezone.now()
        self.status         = self.STATUS_COOLDOWN
        self.void_reason    = self.VOID_REASON_FORCED
        self.cooldown_until = now + timedelta(minutes=minutes)
        self.voided_at      = now
        self.save(update_fields=['status', 'void_reason', 'cooldown_until', 'voided_at'])

    @classmethod
    def get_active_for_user(cls, user, kind, department=None):
        """إرجاع الحجز النشط للمستخدم لنوع معين، أو None."""
        qs = cls.objects.filter(
            user=user, kind=kind,
            status__in=[cls.STATUS_ACTIVE, cls.STATUS_REACTIVATED]
        )
        if department is not None:
            qs = qs.filter(department=department)
        return qs.order_by('-reserved_at').first()

    @classmethod
    def reserve(cls, user, kind, expire_minutes=45):
        """حجز رقم آمن من التضارب وبلا فجوات — يفوّض لخدمة الحجز الموحّدة
        (أولوية عودة cooldown → إعادة تدوير أصغر رقم متروك → رقم جديد)."""
        from .reservation_service import reserve_number
        reservation, _outcome = reserve_number(user, kind, expire_minutes)
        return reservation


# ══════════════════════════════════════════════════════════════════
#  سجل إرسال الإيميل للكتب
# ══════════════════════════════════════════════════════════════════
class BookLink(models.Model):
    """ضلعٌ في نسيج الوثائق: هذا الكتاب **جوابُ** ذاك، أو **إلحاقٌ** به.

    كان النظام **عاجزاً بنيويّاً** عن التعبير عن هذا: مسحُ ``core/models.py``
    أظهر صفرَ علاقةٍ من كتابٍ إلى كتاب — كلُّ المفاتيح إلى ``Book`` تأتي من
    نماذجَ أخرى (مرفقات، تعليقات، تاريخ، بريد). فسؤالُ الكاتب «إلحاقاً
    بمذكّرتكم المرقّمة…» لم يكن له جواب.

    **حقيقةٌ ثابتةٌ لا حالةَ لها** — وهذا ما يفصلها عن الإحالة (سيرِ العمل):
    الضلعُ يقول «هذان متّصلان» ولا يقول «ما زال معلّقاً». الجدولان لا يُدمجان:
    خلطُ الدلالتين هو «الجدول الغامض».

    و``PROTECT`` على ``to_book`` مقصود: تفريغُ أصلٍ من السلّة **وهو مرجعُ
    غيرِه** يُرفض حتى يُفكّ الربط — حمايةُ سلسلة الإحالات من الانقطاع.
    """

    REPLY        = 'reply'
    FOLLOWUP     = 'followup'
    REFERS       = 'refers'
    CONFIRMATION = 'confirmation'
    RELATION_CHOICES = (
        (REPLY,        'جواب على'),
        (FOLLOWUP,     'إلحاقاً بـ'),
        (REFERS,       'إشارة إلى'),
        (CONFIRMATION, 'تأكيد على'),
    )

    from_book  = models.ForeignKey('Book', on_delete=models.CASCADE,
                                   related_name='links_out', verbose_name='من كتاب')
    to_book    = models.ForeignKey('Book', on_delete=models.PROTECT,
                                   related_name='links_in', verbose_name='إلى كتاب')
    relation   = models.CharField('العلاقة', max_length=16, choices=RELATION_CHOICES)
    note       = models.CharField('ملاحظة', max_length=255, blank=True, default='')
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True,
                                   related_name='book_links')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'رابط بين كتابين'
        verbose_name_plural = 'روابط الكتب'
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(fields=['from_book', 'to_book', 'relation'],
                                    name='uniq_book_link'),
            models.CheckConstraint(check=~models.Q(from_book=models.F('to_book')),
                                   name='book_link_not_self'),
        ]
        indexes = [
            # «مَن يجيب هذا الكتاب؟» — استعلامُ مصفوفة الردود ولوحة العلاقات
            models.Index(fields=['to_book', 'relation'], name='booklink_to_idx'),
            models.Index(fields=['from_book', 'relation'], name='booklink_from_idx'),
        ]

    def __str__(self):
        return f"{self.from_book_id} {self.get_relation_display()} {self.to_book_id}"


class BookReferral(models.Model):
    """**التفريق** — الكتابُ يمشي إلى وحدةٍ أو قسمٍ أو جهةٍ خارجيّة، ومعه توجيه.

    شهادةُ موظّف البريد قلبت هذا من استثناءٍ إلى قاعدةٍ يوميّة: «نمسك الكتاب
    نذهب به للمدير ويكتب إمّا هامشَ الاطّلاع والحفظ أو إجابةً مباشرةً بالهامش
    أو **التوجيهَ للوحدات بأوامر مداولة**». فالكتابُ الواحد يُفرَّق على وحداتٍ
    عدّة، ولكلّ وحدةٍ توجيهُها ومدّتُها ومَن يتابعها.

    **لماذا صفٌّ لكلّ هدفٍ لا حقلٌ في الكتاب؟** لأنّ ما نطارده هو **حالةُ كلّ
    قفزةٍ على حدة**: سبعُ قفزاتٍ = سبعةُ هوامشَ مؤرَّخةٍ بأصحابها، وحقلٌ واحدٌ
    لا يبلغ ذلك إلّا بالكشط والإلحاق النصّيّ — وهو ما يُضيع المستند.

    **والمرساةُ دائماً ``book``:** الكتابُ يبقى لقسمٍ مالكٍ واحد، والصفوفُ
    نسخُ إحالةٍ لا نقلُ ملكيّة.
    """

    #: الهدفُ الواحد بالضبط — قسمٌ داخليّ أو جهةٌ خارجيّة، لا كلاهما ولا لا شيء.
    ACTION = 'action'
    INFO = 'info'
    PURPOSE_CHOICES = (
        (ACTION, 'للتنفيذ'),
        (INFO,   'للعلم'),
    )

    SENT = 'sent'
    RECEIVED = 'received'
    DONE = 'done'
    RETURNED = 'returned'
    STATUS_CHOICES = (
        (SENT,     'مُرسَل'),
        (RECEIVED, 'مستلَم'),
        (DONE,     'منجَز'),
        (RETURNED, 'مُعاد'),
    )
    #: الحالاتُ التي ما زال الصفُّ فيها التزاماً مفتوحاً يُطارَد.
    OPEN_STATUSES = (SENT, RECEIVED)

    book = models.ForeignKey(Book, on_delete=models.CASCADE, related_name='referrals',
                             verbose_name="الكتاب")
    from_department = models.ForeignKey(Department, on_delete=models.PROTECT,
                                        related_name='referrals_out', verbose_name="من قسم")
    to_department = models.ForeignKey(Department, on_delete=models.PROTECT, null=True, blank=True,
                                      related_name='referrals_in', verbose_name="إلى قسم/وحدة")
    to_entity = models.ForeignKey('Entity', on_delete=models.PROTECT, null=True, blank=True,
                                  related_name='referrals_in', verbose_name="إلى جهة خارجيّة")
    assignee = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True,
                                 related_name='referrals_assigned', verbose_name="المكلَّف")

    purpose = models.CharField("الغرض", max_length=8, choices=PURPOSE_CHOICES, default=ACTION)
    margin = models.TextField("التوجيه/الهامش", blank=True)
    #: قصاصةُ الهامش المكتوب بخطّ اليد: {attachment_id, page, bbox} — التوجيهُ
    #: يُكتب على وجه المعاملة بخطّ المدير، ونسخُه يدويّاً يُضيع الحجّة.
    margin_crop = models.JSONField("قصاصة الهامش", null=True, blank=True)
    via_book = models.ForeignKey(Book, on_delete=models.SET_NULL, null=True, blank=True,
                                 related_name='referrals_via', verbose_name="المذكّرة الصادرة")

    status = models.CharField("الحالة", max_length=10, choices=STATUS_CHOICES,
                              default=SENT, db_index=True)
    due_date = models.DateField("موعد الإنجاز", null=True, blank=True)
    last_reminder_at = models.DateTimeField("آخر تنبيه", null=True, blank=True)
    closed_by_link = models.ForeignKey('BookLink', on_delete=models.SET_NULL, null=True, blank=True,
                                       related_name='closes_referrals', verbose_name="أُقفل بالجواب")

    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name='referrals_created')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'إحالة'
        verbose_name_plural = 'الإحالات'
        ordering = ['-created_at']
        constraints = [
            # هدفٌ واحدٌ بالضبط: صفٌّ بلا هدفٍ التزامٌ لا يطارده أحد، وصفٌّ
            # بهدفين يُحتسب مرّتين في مصفوفة الردود.
            models.CheckConstraint(
                check=(models.Q(to_department__isnull=False, to_entity__isnull=True)
                       | models.Q(to_department__isnull=True, to_entity__isnull=False)),
                name='referral_exactly_one_target',
            ),
        ]
        indexes = [
            models.Index(fields=['to_department', 'status'], name='referral_dept_status_idx'),
            models.Index(fields=['status', 'purpose', 'due_date'], name='referral_queue_idx'),
            models.Index(fields=['book'], name='referral_book_idx'),
        ]

    def __str__(self):
        return f"{self.book_id} ⟵ {self.target_name} ({self.get_status_display()})"

    @property
    def target(self):
        """الهدفُ كائناً أيّاً كان نوعُه — القيدُ يضمن أنّ أحدَهما موجودٌ حتماً."""
        return self.to_department if self.to_department_id else self.to_entity

    @property
    def target_name(self):
        """**الاسمُ وحده بلا رمز.** ``Department.__str__`` يُصدّر «ش13 — المتابعة»
        وهو نافعٌ في قائمةٍ منسدلة، لكنّه ضجيجٌ حين يتكرّر في كلّ خليّةٍ من ورقةٍ
        يقارنها الكاتبُ بدفتره سطراً بسطر — والرمزُ في ترويسة الورقة أصلاً."""
        return self.target.name

    @property
    def is_open(self):
        return self.status in self.OPEN_STATUSES

    @property
    def is_overdue(self):
        """متأخّرٌ **للتنفيذ فقط**: «للعلم» لا يُطارَد ولا يُحتسب تأخيراً."""
        from django.utils import timezone as _tz

        return bool(
            self.is_open and self.purpose == self.ACTION
            and self.due_date and self.due_date < _tz.localdate()
        )


class CustodyEvent(models.Model):
    """**بعهدة مَن** — سجلُّ انتقال المستند من يدٍ إلى يد.

    سُئل الكاتبُ ما الذي يجعله يترك دفترَ التواقيع الورقيَّ فأجاب: «إذا كانت
    المهامُّ والمسؤوليّاتُ واضحةً ومقسّمةً على اليوزريّة وظاهرةً لي **كلُّ
    تفاصيل الاستلام وبعهدة مَن**: مَن استلم، ومَن أكّد، ومَن أعدّ… لاستغنينا
    عنه. **المهمّ الشفافيّة: لا يضيع مستندٌ أبداً ولا تفاصيله.**»

    فهذا الجدولُ هو **الميزةُ الحاكمة** في المشروع كلّه، ومقياسُ نجاحه بسيطٌ
    وقاسٍ: مستندٌ واحدٌ يضيع يُبطل الثقةَ كلَّها.

    **صفٌّ لكلّ انتقال — لا حقلٌ يُكشط:** «آخرُ عهدة» تُقرأ من الصفّ الأخير،
    والخطُّ الزمنيّ كلُّه محفوظ. وحقلُ ``Book.current_custody`` مؤشّرٌ إلى هذا
    الصفّ لا **نسخةٌ ثانيةٌ للحقيقة**.
    """

    INTAKE = 'intake'
    UNIT_RECEIPT = 'unit_receipt'
    ARCHIVE_DONE = 'archive_done'
    COURIER_PICKUP = 'courier_pickup'
    RETURN = 'return'
    EVENT_CHOICES = (
        (INTAKE,         'قيدٌ في السجلّ'),
        (UNIT_RECEIPT,   'استلامُ وحدة'),
        (ARCHIVE_DONE,   'تمامُ أرشفة'),
        (COURIER_PICKUP, 'تسليمٌ لمتعهّد البريد'),
        (RETURN,         'إعادة'),
    )

    PAPER = 'paper'
    DIGITAL = 'digital'
    SIGNATURE_MODES = (
        (PAPER,   'توقيعٌ ورقيّ'),
        (DIGITAL, 'إقرارٌ في النظام'),
    )

    book = models.ForeignKey(Book, on_delete=models.CASCADE, related_name='custody_events',
                             verbose_name="الكتاب")
    referral = models.ForeignKey('BookReferral', on_delete=models.SET_NULL, null=True, blank=True,
                                 related_name='custody_events', verbose_name="الإحالة")
    event = models.CharField("الحدث", max_length=20, choices=EVENT_CHOICES, db_index=True)

    to_holder_department = models.ForeignKey(Department, on_delete=models.PROTECT,
                                             null=True, blank=True,
                                             related_name='custody_held',
                                             verbose_name="بعهدة قسم/وحدة")
    to_holder_user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True,
                                       related_name='custody_held', verbose_name="بعهدة موظّف")
    #: نصٌّ حرٌّ لأنّ **متعهّد البريد ليس مستخدماً في النظام** — ولا يصحّ أن
    #: تنقطع سلسلةُ العهدة عند أوّل حاملٍ من خارج الحسابات.
    to_holder_name = models.CharField("بعهدة (اسم)", max_length=120, blank=True)

    signed_at = models.DateTimeField("وقت التوقيع", db_index=True)
    recorded_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True,
                                    related_name='custody_recorded', verbose_name="سجّله")
    signature_mode = models.CharField("نوعُ التوقيع", max_length=10,
                                      choices=SIGNATURE_MODES, default=PAPER)
    #: يحمل **مكانَ الحفظ** عند الأرشفة — وهو ما يسأل عنه الكاتبُ بعد سنة.
    note = models.CharField("ملاحظة", max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'حدث عهدة'
        verbose_name_plural = 'سجلّ العهدة'
        ordering = ['-signed_at', '-id']
        constraints = [
            # حاملٌ واحدٌ على الأقلّ: صفٌّ بلا حاملٍ يقول «انتقلت العهدة إلى
            # لا أحد» — وهو تماماً الضياعُ الذي وُجد الجدولُ لمنعه.
            models.CheckConstraint(
                check=(models.Q(to_holder_department__isnull=False)
                       | models.Q(to_holder_user__isnull=False)
                       | ~models.Q(to_holder_name='')),
                name='custody_has_a_holder',
            ),
        ]
        indexes = [
            models.Index(fields=['book', '-signed_at'], name='custody_book_idx'),
            models.Index(fields=['event', 'signed_at'], name='custody_event_idx'),
        ]

    def __str__(self):
        return '%s ⟵ %s' % (self.get_event_display(), self.holder_name)

    @property
    def holder_name(self):
        """اسمُ الحامل أيّاً كان نوعُه — القيدُ يضمن أنّ أحدَها موجود."""
        if self.to_holder_user_id:
            return self.to_holder_user.get_full_name() or self.to_holder_user.get_username()
        if self.to_holder_department_id:
            return self.to_holder_department.name
        return self.to_holder_name


class BookRegistration(models.Model):
    """قيدُ الكتاب الواحد في **دفترِ أكثرَ من قسم** — ولكلٍّ رقمُ واردِه.

    تصحيحُ المالك حرفيّاً: «عندما تأتي من الوزارة جهةٌ أعلى تخاطب الشركة
    بعنوانها فيوقّع المديرُ العامّ ويهمّش ويوجّه الكتاب… **ويدخل مرّةً بوارد
    مكتب المدير العامّ ثمّ مرّةً أخرى بوارد الأقسام المختصّة**»، و«ندخله برقم
    الكتاب الأصليّ… **ورقمِ واردٍ خاصٍّ بنا**».

    فالورقةُ الواحدة لها أرقامُ واردٍ بعددِ الدفاتر التي مرّت بها. وحقلُ
    ``Book.our_number`` يبقى **رقمَ القسم المالك** — وهذه الصفوفُ هي البقيّة،
    كلٌّ في دفتره. ولا يُختلق شيءٌ للماضي: القيدُ يُنشأ حين يُقيَّد فعلاً.
    """

    book = models.ForeignKey(Book, on_delete=models.CASCADE, related_name='registrations',
                             verbose_name="الكتاب")
    department = models.ForeignKey(Department, on_delete=models.PROTECT,
                                   related_name='registrations', verbose_name="القسم")
    #: من منظور **المقيِّد**: الكتابُ صادرٌ عند مُرسِله ووارِدٌ عند مُستلمه.
    direction = models.CharField("النوع", max_length=20, default='incoming_internal',
                                 choices=(('incoming_internal', 'وارد داخلي'),
                                          ('incoming_external', 'وارد خارجي')))
    number = models.CharField("رقم الوارد", max_length=20, blank=True)
    registered_at = models.DateTimeField("تاريخ القيد", default=timezone.now)
    registered_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True,
                                      related_name='registrations_made')
    via_referral = models.ForeignKey('BookReferral', on_delete=models.SET_NULL,
                                     null=True, blank=True, related_name='registrations',
                                     verbose_name="عن إحالة")

    class Meta:
        verbose_name = 'قيد في دفتر'
        verbose_name_plural = 'القيود'
        ordering = ['-registered_at']
        constraints = [
            # رقمٌ واحدٌ لا يتكرّر في دفترِ القسم الواحد — و«بلا رقم» مستثنىً
            # (استثناءٌ مدعومٌ في `numbering.py` ولا يستهلك عدّاداً).
            models.UniqueConstraint(
                fields=['department', 'direction', 'number'],
                condition=~models.Q(number=''),
                name='uniq_registration_per_department',
            ),
            models.UniqueConstraint(
                fields=['book', 'department'],
                name='uniq_registration_book_department',
            ),
        ]
        indexes = [
            models.Index(fields=['department', 'direction'], name='registration_dept_idx'),
        ]

    def __str__(self):
        return '%s: %s' % (self.department.code, self.number or '(بلا رقم)')


class SecretAccessGrant(models.Model):
    """تفويضُ الاطّلاع على كتابٍ سرّيٍّ **بعينه**.

    شهادةُ موظّف البريد: «فقط مسؤول إدارة البريد والأرشفة يحقّ لهم الاطّلاع،
    **أو تفويضُ موظّفٍ معيّنٍ للاطّلاع**». فالتفويضُ واقعةٌ في العمل لا ترفٌ
    تقنيّ.

    **لكتابٍ واحدٍ فقط — لا تفويضَ شامل:** أقلُّ امتيازٍ ممكن. ومن احتاج
    السرّيّ كلَّه فترقيتُه إلى دور مختصّ البريد قرارُ إنسانٍ أثقل، وهو الصواب:
    صلاحيةٌ دائمةٌ تُمنح بوعيٍ لا بضغطة زرّ في صفحة كتاب.
    """

    book       = models.ForeignKey('Book', on_delete=models.CASCADE, related_name='secret_grants')
    user       = models.ForeignKey(User, on_delete=models.CASCADE, related_name='secret_grants')
    granted_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True,
                                   related_name='secret_grants_given')
    granted_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField("ينتهي في", null=True, blank=True)
    revoked_at = models.DateTimeField("سُحب في", null=True, blank=True)
    reason     = models.CharField("السبب", max_length=255, blank=True, default="")

    class Meta:
        verbose_name = 'تفويض اطّلاع'
        verbose_name_plural = 'تفويضات الاطّلاع'
        constraints = [
            # منحةٌ ساريةٌ واحدة لكلّ (كتاب، مستخدم) — والمسحوبةُ تبقى للتاريخ.
            models.UniqueConstraint(
                fields=['book', 'user'], condition=models.Q(revoked_at__isnull=True),
                name='uniq_live_secret_grant',
            ),
        ]
        indexes = [models.Index(fields=['user'], name='secret_grant_user_idx')]

    def __str__(self):
        return f"{self.user.get_username()} ⟵ {self.book_id}"


class BookEmailLog(models.Model):
    """
    يسجّل كل إيميل يُرسَل مرتبطاً بكتاب —
    سواء كان إشعاراً تلقائياً، إعادة إرسال يدوياً، أو نسخة مؤرشفة.
    """

    TRIGGER_AUTO    = 'auto'       # إشعار تلقائي عند الحفظ
    TRIGGER_MANUAL  = 'manual'     # إرسال يدوي من المستخدم
    TRIGGER_REMINDER = 'reminder'  # تذكير بالمتابعة (Celery)
    TRIGGER_CHOICES = [
        (TRIGGER_AUTO,     'تلقائي عند الحفظ'),
        (TRIGGER_MANUAL,   'يدوي'),
        (TRIGGER_REMINDER, 'تذكير متابعة'),
    ]

    STATUS_SENT      = 'sent'
    STATUS_FAILED    = 'failed'
    STATUS_PENDING   = 'pending'
    STATUS_ABANDONED = 'abandoned'
    STATUS_CHOICES = [
        (STATUS_SENT,      'أُرسِل'),
        (STATUS_FAILED,    'فشل'),
        (STATUS_PENDING,   'في الانتظار'),
        (STATUS_ABANDONED, 'مُتروك بعد محاولات'),
    ]

    #: أقصى محاولاتٍ لإعادة الإرسال قبل الترك.
    MAX_RETRIES = 3

    # اختياريّ عمداً: رسالةٌ إداريّةٌ قد لا تخصّ كتاباً بعينه. كان الحقل إلزاميّاً
    # فسقط مسار الإنشاء إلى **أوّل كتابٍ في القاعدة** (``Book.objects.order_by('id')
    # .first()``) لمجرّد إرضاء القيد — فيُسجَّل بريدٌ على كتابٍ لا صلة له به.
    book       = models.ForeignKey('Book', null=True, blank=True, on_delete=models.CASCADE,
                                   related_name='email_logs', verbose_name='الكتاب')
    sent_by    = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL,
                                   verbose_name='أرسله')
    entity     = models.ForeignKey(Entity, null=True, blank=True, on_delete=models.SET_NULL,
                                   related_name='email_logs', verbose_name='الجهة')

    to_address  = models.CharField("إلى", max_length=255)
    cc_addresses = models.CharField("CC", max_length=500, blank=True, default="")
    subject     = models.CharField("الموضوع", max_length=255)
    body_html   = models.TextField("النص", blank=True, default="")

    trigger     = models.CharField(max_length=10, choices=TRIGGER_CHOICES, default=TRIGGER_AUTO)
    status      = models.CharField(max_length=10, choices=STATUS_CHOICES, default=STATUS_PENDING, db_index=True)
    error_msg   = models.TextField("رسالة الخطأ", blank=True, default="")

    # ربط بخيط المحادثة (يُعبَّأ عند الإرسال إن وُجد)
    thread       = models.ForeignKey(
        'EmailThread', null=True, blank=True, on_delete=models.SET_NULL,
        related_name='sent_emails', verbose_name='الخيط'
    )
    smtp_message_id = models.CharField("SMTP Message-ID", max_length=500, blank=True, default="",
                                        db_index=True,
                                        help_text="يُستخدم لربط الردود الواردة بهذا الإيميل")

    sent_at     = models.DateTimeField("أُرسِل في", auto_now_add=True)
    delivered_at = models.DateTimeField("تأكيد التسليم", null=True, blank=True)

    # ── إعادة الإرسال ──
    # كانت مهمّة الإعادة تدّعي في توثيقها «محاولةً واحدةً لكلّ سجلّ» ولا تنفّذه:
    # المُرسِل يُنشئ **صفّاً جديداً** لكلّ محاولة ولا يمسّ الأصل، فيبقى الأصل
    # `failed` أبداً ويُعاد إرساله كلّ تشغيل — والصفوف الجديدة تدخل الطابور
    # بدورها فينمو الحشد. هذه الحقول هي ما يجعل «مرّةً واحدة» صادقةً فعلاً.
    retry_count   = models.PositiveSmallIntegerField("عدد المحاولات", default=0)
    last_retry_at = models.DateTimeField("آخر محاولة", null=True, blank=True)
    retry_of      = models.ForeignKey(
        'self', null=True, blank=True, on_delete=models.SET_NULL,
        related_name='retries', verbose_name='محاولةٌ لـ',
        help_text='غير فارغ ⟵ هذا الصفّ محاولةُ إعادةٍ لا أصلاً: لا يدخل الطابور.',
    )

    class Meta:
        verbose_name = 'سجل إيميل'
        verbose_name_plural = 'سجلات الإيميل'
        ordering = ['-sent_at']
        indexes = [
            models.Index(fields=['book', 'status']),
            models.Index(fields=['sent_at']),
        ]

    def __str__(self):
        return f"[{self.get_status_display()}] {self.subject} → {self.to_address}"


# ══════════════════════════════════════════════════════════════════
#  إعدادات النظام العامة — هوية التطبيق المعروضة (Singleton)
# ══════════════════════════════════════════════════════════════════
class SystemSettings(models.Model):
    """
    هوية التطبيق المعروضة (اسم النظام وسطر الوصف) — سجل وحيد (Singleton).
    مستقلّة عن هوية المؤسسة في ``EmailSettings`` (تلك خاصّة بترويسة التقارير
    والبريد). تُعرَض في كل الصفحات عبر context processor ``system_settings``.
    """

    singleton      = models.PositiveSmallIntegerField(default=1, unique=True, editable=False)
    app_name       = models.CharField("اسم النظام", max_length=100, default="نظام الكتب")

    # وضعا تشغيلٍ من الكود نفسه: تنصيبُ قسمٍ واحد لا يرى تعقيد الأقسام أصلاً،
    # وتنصيبُ الشركة يُظهرها. القاعدة: كلّ سلوكٍ جديدٍ خلف ``company``.
    PROFILE_SINGLE  = 'single'
    PROFILE_COMPANY = 'company'
    PROFILE_CHOICES = [
        (PROFILE_SINGLE,  'قسم واحد'),
        (PROFILE_COMPANY, 'الشركة كاملةً'),
    ]
    deployment_profile = models.CharField(
        "وضع التشغيل", max_length=10, choices=PROFILE_CHOICES, default=PROFILE_SINGLE,
    )
    brand_subtitle = models.CharField(
        "سطر الوصف في الترويسة", max_length=200, blank=True,
        default="أرشفة موحدة ومتابعة تشغيلية ضمن واجهة ديسكتوب ثابتة",
    )
    updated_at     = models.DateTimeField(auto_now=True)

    # مفتاح كاش موحّد يستخدمه context processor أيضاً (مصدر واحد لتفادي التضارب).
    CACHE_KEY = "system_settings_singleton"

    class Meta:
        verbose_name = "إعدادات النظام"
        verbose_name_plural = "إعدادات النظام"

    def __str__(self):
        return self.app_name

    @classmethod
    def get(cls):
        """يعيد السجل الوحيد (ينشئه بالقيَم الافتراضية عند أول استدعاء)."""
        obj, _ = cls.objects.get_or_create(singleton=1)
        return obj

    def save(self, *args, **kwargs):
        self.singleton = 1
        super().save(*args, **kwargs)
        from django.core.cache import cache
        cache.delete(self.CACHE_KEY)


# ══════════════════════════════════════════════════════════════════
#  سياسة إشعارات تأخّر الكتب (Singleton)
# ══════════════════════════════════════════════════════════════════
class NotificationSettings(models.Model):
    """
    سياسة إشعارات التأخّر — سجل وحيد (Singleton).
    يقرؤها أمر ``notify_overdue_books`` عند كل تشغيل؛ كل حقل يغيّر سلوكه فعلاً.
    """

    singleton       = models.PositiveSmallIntegerField(default=1, unique=True, editable=False)
    overdue_enabled = models.BooleanField("تفعيل إشعارات التأخّر", default=True)
    notify_admins   = models.BooleanField("إشعار المدراء داخل النظام", default=True)
    notify_creator  = models.BooleanField("إشعار مُنشئ الكتاب", default=True)
    email_admins    = models.BooleanField("إرسال بريد ملخّص للمدراء", default=False,
                                          help_text="يتطلّب تفعيل إعدادات البريد")
    updated_at      = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "إعدادات الإشعارات"
        verbose_name_plural = "إعدادات الإشعارات"

    def __str__(self):
        return "إعدادات الإشعارات"

    @classmethod
    def get(cls):
        obj, _ = cls.objects.get_or_create(singleton=1)
        return obj

    def save(self, *args, **kwargs):
        self.singleton = 1
        super().save(*args, **kwargs)


# ══════════════════════════════════════════════════════════════════
#  إعدادات الأمان (Singleton)
# ══════════════════════════════════════════════════════════════════
class SecuritySettings(models.Model):
    """
    إعدادات الأمان — سجل وحيد (Singleton).
    ``password_min_length`` يُطبَّق فعلياً عند إنشاء المستخدمين في شاشة الأدوار.
    """

    singleton           = models.PositiveSmallIntegerField(default=1, unique=True, editable=False)
    password_min_length = models.PositiveSmallIntegerField("الحد الأدنى لطول كلمة المرور", default=8)
    updated_at          = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "إعدادات الأمان"
        verbose_name_plural = "إعدادات الأمان"

    def __str__(self):
        return "إعدادات الأمان"

    @classmethod
    def get(cls):
        obj, _ = cls.objects.get_or_create(singleton=1)
        return obj

    def save(self, *args, **kwargs):
        self.singleton = 1
        super().save(*args, **kwargs)


# ══════════════════════════════════════════════════════════════════
#  إعدادات النسخ الاحتياطي المجدول (Singleton)
# ══════════════════════════════════════════════════════════════════
class BackupSettings(models.Model):
    """
    إعدادات النسخ الاحتياطي المجدول — سجل وحيد (Singleton).
    تقرؤها مهمة Celery ``scheduled_backup`` عند كل تشغيل ساعي.
    """

    FREQ_DAILY = 'daily'
    FREQ_WEEKLY = 'weekly'
    FREQ_MONTHLY = 'monthly'
    FREQUENCY_CHOICES = [
        (FREQ_DAILY, 'يومي'),
        (FREQ_WEEKLY, 'أسبوعي'),
        (FREQ_MONTHLY, 'شهري'),
    ]

    singleton      = models.PositiveSmallIntegerField(default=1, unique=True, editable=False)
    enabled        = models.BooleanField("تفعيل النسخ التلقائي", default=False)
    frequency      = models.CharField("التكرار", max_length=10, choices=FREQUENCY_CHOICES, default=FREQ_DAILY)
    hour           = models.PositiveSmallIntegerField("ساعة التشغيل (0-23)", default=2)
    retention_days = models.PositiveSmallIntegerField("مدة الاحتفاظ (يوم)", default=30)
    last_run_at    = models.DateTimeField("آخر تشغيل ناجح", null=True, blank=True)
    updated_at     = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "إعدادات النسخ الاحتياطي"
        verbose_name_plural = "إعدادات النسخ الاحتياطي"

    def __str__(self):
        return "إعدادات النسخ الاحتياطي"

    @classmethod
    def get(cls):
        obj, _ = cls.objects.get_or_create(singleton=1)
        return obj

    def save(self, *args, **kwargs):
        self.singleton = 1
        super().save(*args, **kwargs)


# ══════════════════════════════════════════════════════════════════
#  إعدادات البريد الإلكتروني للمؤسسة (Singleton)
# ══════════════════════════════════════════════════════════════════
class EmailSettings(EncryptedFieldsMixin):
    """
    إعدادات SMTP الخاصة بالمؤسسة — سجل وحيد (Singleton).
    يُفعَّل/يُعطَّل الإرسال من هنا دون تعديل settings.py.
    """

    ENCRYPTED_FIELDS = ('smtp_password', 'imap_password')

    # ── هوية المؤسسة (تُستخدم في ترويسة التقارير المطبوعة + البريد) ──
    org_name        = models.CharField("اسم الشركة/المؤسسة", max_length=200, default="")
    org_section     = models.CharField("اسم القسم", max_length=200, blank=True, default="",
                                       help_text="يظهر في ترويسة التقارير المطبوعة")
    org_unit        = models.CharField("اسم الوحدة", max_length=200, blank=True, default="",
                                       help_text="يظهر في ترويسة التقارير المطبوعة")
    org_email       = models.EmailField("بريد المؤسسة الرسمي", blank=True, default="",
                                        help_text="يُستخدم كـ From address في جميع الإيميلات")
    reply_to        = models.EmailField("الرد على", blank=True, default="",
                                        help_text="إذا تُرك فارغاً يُستخدم org_email")
    email_signature = models.TextField("التوقيع", blank=True, default="",
                                       help_text="يُضاف في نهاية كل إيميل (HTML مدعوم)")

    # ── SMTP ──
    smtp_host       = models.CharField("خادم SMTP", max_length=200, blank=True, default="smtp.gmail.com")
    smtp_port       = models.PositiveSmallIntegerField("المنفذ", default=587)
    smtp_use_tls    = models.BooleanField("TLS", default=True)
    smtp_use_ssl    = models.BooleanField("SSL", default=False)
    smtp_user       = models.CharField("المستخدم", max_length=200, blank=True, default="")
    smtp_password   = models.CharField("كلمة المرور", max_length=200, blank=True, default="",
                                       help_text="تُخزَّن مشفرة")

    # ── IMAP (استقبال الردود) ──
    imap_host        = models.CharField("خادم IMAP", max_length=200, blank=True, default="",
                                        help_text="مثال: imap.gmail.com")
    imap_port        = models.PositiveSmallIntegerField("منفذ IMAP", default=993)
    imap_use_ssl     = models.BooleanField("SSL للـ IMAP", default=True)
    imap_user        = models.CharField("مستخدم IMAP", max_length=200, blank=True, default="")
    imap_password    = models.CharField("كلمة مرور IMAP", max_length=200, blank=True, default="")
    imap_folder      = models.CharField("المجلد", max_length=100, blank=True, default="INBOX")
    imap_sync_enabled = models.BooleanField("تفعيل استقبال الردود تلقائياً", default=False)
    imap_last_sync   = models.DateTimeField("آخر مزامنة", null=True, blank=True)

    # ── تفعيل/تعطيل ──
    is_active       = models.BooleanField("تفعيل إرسال الإيميل", default=False)
    send_on_save    = models.BooleanField("إرسال تلقائي عند حفظ كتاب", default=False)

    # ── Singleton guard ──
    singleton       = models.PositiveSmallIntegerField(default=1, unique=True, editable=False)

    updated_at      = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'إعدادات البريد'
        verbose_name_plural = 'إعدادات البريد'

    def __str__(self):
        status = "مفعّل" if self.is_active else "معطّل"
        return f"إعدادات البريد ({status})"

    @classmethod
    def get(cls):
        """أحضر السجل الوحيد أو أنشئه بالقيم الافتراضية."""
        obj, _ = cls.objects.get_or_create(singleton=1)
        return obj


# ══════════════════════════════════════════════════════════════════
#  نظام المراسلات البريدية — خيوط المحادثة
# ══════════════════════════════════════════════════════════════════
class EmailThread(models.Model):
    """
    يجمع رسائل الصادر والردود الواردة في خيط محادثة واحد
    مرتبط اختيارياً بكتاب وجهة.
    """

    STATUS_OPEN    = 'open'
    STATUS_WAITING = 'waiting'   # أُرسِل وننتظر رداً
    STATUS_REPLIED = 'replied'   # وصل رد
    STATUS_CLOSED  = 'closed'
    STATUS_CHOICES = [
        (STATUS_OPEN,    'مفتوح'),
        (STATUS_WAITING, 'بانتظار رد'),
        (STATUS_REPLIED, 'تم الرد'),
        (STATUS_CLOSED,  'مغلق'),
    ]

    book    = models.ForeignKey('Book', null=True, blank=True, on_delete=models.SET_NULL,
                                related_name='email_threads', verbose_name='الكتاب المرتبط')
    entity  = models.ForeignKey(Entity, null=True, blank=True, on_delete=models.SET_NULL,
                                related_name='email_threads', verbose_name='الجهة')
    created_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL,
                                   related_name='created_threads', verbose_name='أنشأه')

    subject       = models.CharField("الموضوع", max_length=300)
    status        = models.CharField(max_length=10, choices=STATUS_CHOICES,
                                     default=STATUS_OPEN, db_index=True)
    ref_message_id = models.CharField("Message-ID الأصلي", max_length=500, blank=True, default="",
                                      help_text="Message-ID للإيميل الأول — يُستخدم لربط الردود الواردة")

    created_at    = models.DateTimeField("تاريخ الإنشاء", auto_now_add=True)
    last_activity = models.DateTimeField("آخر نشاط", auto_now=True)

    class Meta:
        verbose_name = 'خيط مراسلة'
        verbose_name_plural = 'خيوط المراسلات'
        ordering = ['-last_activity']
        indexes = [
            models.Index(fields=['status', '-last_activity']),
            models.Index(fields=['book']),
            models.Index(fields=['entity']),
        ]

    def __str__(self):
        return f"[{self.get_status_display()}] {self.subject}"

    @property
    def unread_count(self):
        return self.incoming_emails.filter(is_read=False).count()


class IncomingEmail(models.Model):
    """
    إيميل وارد (رد من جهة) — مستقبَل عبر IMAP.
    يُربط بخيط المحادثة تلقائياً عبر In-Reply-To header.
    """

    thread        = models.ForeignKey(EmailThread, on_delete=models.CASCADE,
                                      related_name='incoming_emails', verbose_name='الخيط')

    from_address  = models.CharField("من", max_length=255)
    from_name     = models.CharField("اسم المرسل", max_length=200, blank=True, default="")
    reply_to      = models.CharField("الرد على", max_length=255, blank=True, default="")

    subject       = models.CharField("الموضوع", max_length=300, blank=True, default="")
    body_html     = models.TextField("النص HTML", blank=True, default="")
    body_text     = models.TextField("النص العادي", blank=True, default="")

    message_id    = models.CharField("Message-ID", max_length=500, unique=True,
                                     help_text="لمنع التكرار عند المزامنة")
    in_reply_to   = models.CharField("In-Reply-To", max_length=500, blank=True, default="")

    imap_uid      = models.PositiveIntegerField("IMAP UID", null=True, blank=True)
    received_at   = models.DateTimeField("استُلِم في", db_index=True)
    synced_at     = models.DateTimeField("وقت المزامنة", auto_now_add=True)

    is_read       = models.BooleanField("مقروء", default=False, db_index=True)
    is_spam       = models.BooleanField("بريد مزعج", default=False)

    class Meta:
        verbose_name = 'إيميل وارد'
        verbose_name_plural = 'الإيميلات الواردة'
        ordering = ['-received_at']
        indexes = [
            models.Index(fields=['thread', 'is_read']),
            models.Index(fields=['received_at']),
        ]

    def __str__(self):
        return f"{self.from_address} → {self.subject}"


class EmailTemplate(models.Model):
    """
    قوالب قابلة لإعادة الاستخدام لإيميلات المراسلات الرسمية.
    تدعم متغيرات: {{book.number}}, {{book.title}}, {{entity.name}}, {{user.get_full_name}}.
    """

    KIND_ANY      = 'any'
    KIND_INCOMING = 'incoming'
    KIND_OUTGOING = 'outgoing'
    KIND_CHOICES = [
        (KIND_ANY,      'كل الأنواع'),
        (KIND_INCOMING, 'وارد فقط'),
        (KIND_OUTGOING, 'صادر فقط'),
    ]

    name             = models.CharField("اسم القالب", max_length=200)
    slug             = models.SlugField(max_length=100, unique=True,
                                        help_text="معرّف فريد للاستخدام البرمجي")
    applicable_kind  = models.CharField("يُطبَّق على", max_length=10,
                                        choices=KIND_CHOICES, default=KIND_ANY)

    subject_template = models.CharField(
        "موضوع الإيميل", max_length=300,
        help_text="يدعم: {{book.our_number}}, {{book.title}}, {{entity.name}}"
    )
    body_html        = models.TextField(
        "نص الإيميل (HTML)",
        help_text="يدعم: {{book.our_number}}, {{book.title}}, {{entity.name}}, {{user.get_full_name}}"
    )

    is_active        = models.BooleanField("مفعّل", default=True)
    is_default       = models.BooleanField("افتراضي لهذا النوع", default=False)
    created_by       = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL,
                                         verbose_name='أنشأه')
    created_at       = models.DateTimeField(auto_now_add=True)
    updated_at       = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'قالب إيميل'
        verbose_name_plural = 'قوالب الإيميلات'
        ordering = ['name']

    def __str__(self):
        return self.name

    def render_subject(self, context: dict) -> str:
        """استبدال المتغيرات في موضوع الإيميل — context مقيّد بمفاتيح آمنة فقط."""
        from django.template import Template, Context
        safe_context = {k: v for k, v in context.items() if k in ('book', 'entity', 'user')}
        try:
            return Template(self.subject_template).render(Context(safe_context))
        except Exception as exc:
            import logging
            logging.getLogger('lettersys').error('[EmailTemplate] render_subject error: %s', exc)
            return self.subject_template

    def render_body(self, context: dict) -> str:
        """استبدال المتغيرات في نص الإيميل — context مقيّد بمفاتيح آمنة فقط."""
        from django.template import Template, Context
        safe_context = {k: v for k, v in context.items() if k in ('book', 'entity', 'user')}
        try:
            return Template(self.body_html).render(Context(safe_context))
        except Exception as exc:
            import logging
            logging.getLogger('lettersys').error('[EmailTemplate] render_body error: %s', exc)
            return self.body_html or ''   # fallback للنص الخام بدل None (يمنع إرسال "None")


# ══════════════════════════════════════════════════════════════════
#  الربط الشبكي — Network Binding
#  يُتيح مشاركة قاعدة البيانات بين أجهزة متعددة على نفس الشبكة.
#  الماستر: يشغّل PostgreSQL  |  التابع: يتصل بقاعدة بيانات الماستر
# ══════════════════════════════════════════════════════════════════

class NetworkSettings(models.Model):
    """
    إعدادات الشبكة لهذا الجهاز — Singleton (id=1 دائماً).
    يخزن دور الجهاز وبيانات الاتصال بالماستر للأجهزة التابعة.
    """
    ROLE_STANDALONE = 'standalone'
    ROLE_MASTER     = 'master'
    ROLE_SLAVE      = 'slave'
    ROLE_CHOICES    = [
        (ROLE_STANDALONE, 'مستقل'),
        (ROLE_MASTER,     'ماستر (رئيسي)'),
        (ROLE_SLAVE,      'تابع'),
    ]

    role              = models.CharField(max_length=20, choices=ROLE_CHOICES, default=ROLE_STANDALONE)
    device_name       = models.CharField(max_length=100, blank=True, help_text='اسم ودّي لهذا الجهاز')
    this_host         = models.GenericIPAddressField(protocol='IPv4', null=True, blank=True)
    app_port          = models.PositiveSmallIntegerField(default=8000)

    # بيانات اتصال الماستر — تُستخدم في الأجهزة التابعة فقط
    master_host           = models.CharField(max_length=100, blank=True)
    master_db_port        = models.PositiveSmallIntegerField(default=5432)
    master_db_name        = models.CharField(max_length=100, blank=True, default='lettersys')
    master_db_user        = models.CharField(max_length=100, blank=True, default='lettersys_user')
    master_db_password_enc = models.CharField(
        max_length=500, blank=True, db_column='master_db_password',
        help_text='كلمة المرور مشفّرة بـ django.core.signing'
    )

    is_configured  = models.BooleanField(default=False)
    configured_at  = models.DateTimeField(null=True, blank=True)
    configured_by  = models.ForeignKey(
        'auth.User', null=True, blank=True,
        on_delete=models.SET_NULL, related_name='+'
    )

    class Meta:
        verbose_name        = 'إعدادات الشبكة'
        verbose_name_plural = 'إعدادات الشبكة'

    def __str__(self):
        return f'إعدادات الشبكة ({self.get_role_display()})'

    @classmethod
    def get(cls):
        """يعيد الـ Singleton، ويُنشئه إذا لم يكن موجوداً."""
        obj, _ = cls.objects.get_or_create(id=1)
        return obj

    # ── تشفير / فك تشفير كلمة مرور قاعدة البيانات ────────────────────────────
    def set_db_password(self, plain: str):
        """يشفّر كلمة المرور ويحفظها."""
        if plain:
            from django.core import signing
            self.master_db_password_enc = signing.dumps(plain, salt='lettersys_net_db_pw')
        else:
            self.master_db_password_enc = ''

    def get_db_password(self) -> str:
        """يفكّ تشفير كلمة المرور ويعيدها."""
        if not self.master_db_password_enc:
            return ''
        try:
            from django.core import signing
            return signing.loads(self.master_db_password_enc, salt='lettersys_net_db_pw')
        except Exception:
            return ''


class NetworkNode(models.Model):
    """
    جهاز مُسجَّل في شبكة LetterSys.
    يُخزَّن في قاعدة البيانات المشتركة ليراه جميع الأجهزة المتصلة،
    ويُشكّل سجلاً حياً لحالة كل جهاز على الشبكة.
    """
    ROLE_MASTER = 'master'
    ROLE_SLAVE  = 'slave'
    ROLE_CHOICES = [
        (ROLE_MASTER, 'ماستر'),
        (ROLE_SLAVE,  'تابع'),
    ]

    name          = models.CharField(max_length=100)
    ip_address    = models.GenericIPAddressField(protocol='IPv4')
    app_port      = models.PositiveSmallIntegerField(default=8000)
    role          = models.CharField(max_length=10, choices=ROLE_CHOICES, default=ROLE_SLAVE)
    is_online     = models.BooleanField(default=False, db_index=True)
    is_current    = models.BooleanField(default=False, help_text='هذا هو الجهاز الذي تعمل عليه')
    last_seen     = models.DateTimeField(null=True, blank=True)
    last_ping_ms  = models.PositiveIntegerField(null=True, blank=True, help_text='زمن الاستجابة بالميلي ثانية')
    app_version   = models.CharField(max_length=20, blank=True, default='1.0')
    registered_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name        = 'جهاز شبكي'
        verbose_name_plural = 'أجهزة الشبكة'
        unique_together     = [('ip_address', 'app_port')]
        ordering            = ['-is_online', '-is_current', 'name']

    def __str__(self):
        return f'{self.name} ({self.ip_address}:{self.app_port}) [{self.get_role_display()}]'

    @property
    def base_url(self) -> str:
        return f'http://{self.ip_address}:{self.app_port}'

    def update_status(self, is_online: bool, ping_ms: int = None):
        """يحدّث حالة الاتصال وزمن الاستجابة."""
        self.is_online = is_online
        if is_online:
            self.last_seen = timezone.now()
        if ping_ms is not None:
            self.last_ping_ms = ping_ms
        self.save(update_fields=['is_online', 'last_seen', 'last_ping_ms'])
