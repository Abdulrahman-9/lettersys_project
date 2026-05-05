# -*- coding: utf-8 -*-
"""
Unified Forms Utilities - أدوات النماذج الموحدة
توفر أساس موحد لكل النماذج المخصصة مع حفظ تصميم Bootstrap
"""

from django import forms
from django.core.exceptions import ValidationError as DjangoValidationError


class UnifiedForm(forms.Form):
    """
    النموذج الأساسي الموحد - جميع النماذج ترث منه
    يحافظ على تصميم Bootstrap ويوفر وظائف مشتركة
    
    الميزات:
    - Bootstrap form-control تطبيق تلقائي
    - رسائل خطأ موحدة
    - معالجة أخطاء مركزية
    - تصميم responsive محسّن
    """
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._apply_bootstrap_classes()
    
    def _apply_bootstrap_classes(self):
        """تطبيق Bootstrap classes على جميع الحقول"""
        for field_name, field in self.fields.items():
            if isinstance(field.widget, forms.CheckboxInput):
                # CheckBox - استخدم form-check-input
                field.widget.attrs['class'] = 'form-check-input'
            elif isinstance(field.widget, forms.RadioSelect):
                # RadioSelect - استخدم form-check-input
                field.widget.attrs['class'] = 'form-check-input'
            elif isinstance(field.widget, forms.Select):
                # Select - استخدم form-select
                field.widget.attrs['class'] = 'form-select'
            elif isinstance(field.widget, forms.Textarea):
                # Textarea - استخدم form-control
                field.widget.attrs['class'] = 'form-control'
                field.widget.attrs['rows'] = 5
            else:
                # جميع الحقول الأخرى - استخدم form-control
                field.widget.attrs['class'] = 'form-control'
            
            # إضافة placeholder من label إذا لم يكن موجوداً
            if 'placeholder' not in field.widget.attrs and field.label:
                field.widget.attrs['placeholder'] = field.label
    
    def get_field_errors(self, field_name):
        """
        استرجاع الأخطاء لحقل معين
        
        Args:
            field_name: اسم الحقل
        
        Returns:
            قائمة الأخطاء
        """
        return self.errors.get(field_name, [])
    
    def is_field_valid(self, field_name):
        """
        التحقق من صحة حقل معين
        
        Args:
            field_name: اسم الحقل
        
        Returns:
            True إذا كان الحقل صحيحاً
        """
        return field_name not in self.errors
    
    def add_error_message(self, message):
        """
        إضافة رسالة خطأ عامة للنموذج
        
        Args:
            message: رسالة الخطأ
        """
        if '__all__' not in self.errors:
            self.add_error(None, message)
        else:
            self.add_error(None, message)
    
    def get_cleaned_values(self):
        """
        استرجاع جميع القيم المنظفة
        
        Returns:
            قاموس القيم المنظفة
        """
        if self.is_valid():
            return self.cleaned_data
        return {}


class UnifiedModelForm(forms.ModelForm):
    """
    نموذج Model موحد - لجميع نماذج النماذج المخصصة
    يرث من UnifiedForm ويضيف وظائف Model محددة
    
    مثال:
        class BookForm(UnifiedModelForm):
            class Meta:
                model = Book
                fields = ['title', 'author', 'isbn']
    """
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._apply_bootstrap_classes()
    
    def _apply_bootstrap_classes(self):
        """تطبيق Bootstrap classes على جميع الحقول"""
        for field_name, field in self.fields.items():
            if isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs['class'] = 'form-check-input'
            elif isinstance(field.widget, forms.RadioSelect):
                field.widget.attrs['class'] = 'form-check-input'
            elif isinstance(field.widget, forms.Select):
                field.widget.attrs['class'] = 'form-select'
            elif isinstance(field.widget, forms.Textarea):
                field.widget.attrs['class'] = 'form-control'
                field.widget.attrs['rows'] = 5
            else:
                field.widget.attrs['class'] = 'form-control'
            
            # إضافة placeholder
            if 'placeholder' not in field.widget.attrs and field.label:
                field.widget.attrs['placeholder'] = field.label
    
    def get_field_errors(self, field_name):
        """استرجاع الأخطاء لحقل معين"""
        return self.errors.get(field_name, [])
    
    def is_field_valid(self, field_name):
        """التحقق من صحة حقل معين"""
        return field_name not in self.errors


class SearchForm(UnifiedForm):
    """
    نموذج البحث الموحد
    يستخدم في جميع صفحات الفهرسة للبحث والفلترة
    
    مثال:
        form = SearchForm()
        if form.is_valid():
            query = form.cleaned_data['query']
    """
    
    query = forms.CharField(
        max_length=200,
        required=False,
        label="البحث",
        widget=forms.TextInput(attrs={
            'placeholder': 'ابحث هنا...'
        })
    )
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # تطبيق Bootstrap على حقل البحث
        self.fields['query'].widget.attrs['class'] = 'form-control'
        self.fields['query'].widget.attrs['aria-label'] = 'بحث'


class FilterForm(UnifiedForm):
    """
    نموذج التصفية الموحد
    يستخدم في الفهرسة المتقدمة
    """
    
    ORDER_CHOICES = [
        ('', 'الترتيب الافتراضي'),
        ('-created_at', 'الأحدث أولاً'),
        ('created_at', 'الأقدم أولاً'),
        ('title', 'الاسم (أ-ي)'),
        ('-title', 'الاسم (ي-أ)'),
    ]
    
    order_by = forms.ChoiceField(
        choices=ORDER_CHOICES,
        required=False,
        label="ترتيب"
    )
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['order_by'].widget.attrs['class'] = 'form-select'


class BulkActionForm(UnifiedForm):
    """
    نموذج الحركات الجماعية
    يستخدم للعمليات على عدة كائنات دفعة واحدة
    """
    
    ACTION_CHOICES = [
        ('', 'اختر حركة'),
        ('delete', 'حذف'),
        ('activate', 'تفعيل'),
        ('deactivate', 'تعطيل'),
    ]
    
    action = forms.ChoiceField(
        choices=ACTION_CHOICES,
        label="الحركة"
    )
    
    ids = forms.CharField(
        widget=forms.HiddenInput(),
        required=False
    )
    
    def get_selected_ids(self):
        """
        استرجاع قائمة المعرفات المختارة
        
        Returns:
            قائمة من المعرفات
        """
        if self.is_valid():
            ids_str = self.cleaned_data.get('ids', '')
            return [int(id_) for id_ in ids_str.split(',') if id_.strip()]
        return []
    
    def get_action(self):
        """استرجاع الحركة المختارة"""
        if self.is_valid():
            return self.cleaned_data.get('action')
        return None


def render_form_field(form, field_name, template_pack='bootstrap5'):
    """
    دالة مساعدة لتصيير حقل فردي من النموذج
    
    Args:
        form: النموذج
        field_name: اسم الحقل
        template_pack: إصدار Bootstrap
    
    Returns:
        HTML string لحقل النموذج
    """
    if field_name not in form.fields:
        return ""
    
    field = form[field_name]
    errors = form.get_field_errors(field_name)
    
    html = f'<div class="mb-3">'
    html += f'<label class="form-label" for="{field.id_for_label}">{field.label}</label>'
    html += str(field)
    
    if errors:
        html += '<div class="invalid-feedback d-block">'
        for error in errors:
            html += f'<span>{error}</span><br>'
        html += '</div>'
    
    html += '</div>'
    
    return html


def apply_form_classes(form, exclude_fields=None):
    """
    تطبيق Bootstrap classes على نموذج موجود
    مفيد للنماذج التي لا ترث من UnifiedForm
    
    Args:
        form: النموذج
        exclude_fields: قائمة الحقول المستثناة
    
    Returns:
        النموذج المعدل
    """
    exclude_fields = exclude_fields or []
    
    for field_name, field in form.fields.items():
        if field_name in exclude_fields:
            continue
        
        if isinstance(field.widget, forms.CheckboxInput):
            field.widget.attrs['class'] = 'form-check-input'
        elif isinstance(field.widget, forms.RadioSelect):
            field.widget.attrs['class'] = 'form-check-input'
        elif isinstance(field.widget, forms.Select):
            field.widget.attrs['class'] = 'form-select'
        elif isinstance(field.widget, forms.Textarea):
            field.widget.attrs['class'] = 'form-control'
        else:
            field.widget.attrs['class'] = 'form-control'
    
    return form
