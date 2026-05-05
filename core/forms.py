from django import forms


class MultipleFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True

from .models import Attachment, Book, Entity

## ALLOWED_EXTS = {"pdf", "jpg", "jpeg", "png"}  // لم يعد هناك تحقق نوع


class EntityForm(forms.ModelForm):
    class Meta:
        model = Entity
        fields = [
            "name", "code", "etype", "is_active",
            "email", "email_cc", "phone", "address", "contact_person", "notes",
            "notify_on_receive", "notify_on_send",
        ]
        labels = {
            "name":             "اسم الجهة",
            "code":             "رمز الجهة",
            "etype":            "نوع الجهة",
            "is_active":        "نشطة",
            "email":            "البريد الإلكتروني",
            "email_cc":         "نسخة إلى (CC)",
            "phone":            "الهاتف",
            "address":          "العنوان البريدي",
            "contact_person":   "مسؤول الاتصال",
            "notes":            "ملاحظات",
            "notify_on_receive": "إشعار عند استلام كتاب منها",
            "notify_on_send":   "إشعار عند إرسال كتاب إليها",
        }
        widgets = {
            "name":           forms.TextInput(attrs={"class": "form-control"}),
            "code":           forms.TextInput(attrs={"class": "form-control"}),
            "etype":          forms.Select(attrs={"class": "form-select"}),
            "email":          forms.EmailInput(attrs={"class": "form-control", "dir": "ltr", "placeholder": "example@domain.com"}),
            "email_cc":       forms.TextInput(attrs={"class": "form-control", "dir": "ltr", "placeholder": "addr1@domain.com, addr2@domain.com"}),
            "phone":          forms.TextInput(attrs={"class": "form-control", "dir": "ltr"}),
            "address":        forms.TextInput(attrs={"class": "form-control"}),
            "contact_person": forms.TextInput(attrs={"class": "form-control"}),
            "notes":          forms.Textarea(attrs={"class": "form-control", "rows": 3}),
        }


class BookForm(forms.ModelForm):
    class Meta:
        model = Book
        fields = [
            "kind",
            "our_number",
            "sender_number",
            "title",
            "document_type",
            "secret_level",
            "date",
            "sender_date",
            "margin",
            "needs_followup",
            "due_date",
            "final_status",
        ]
        labels = {
            "kind": "نوع الكتاب",
            "our_number": "رقمنا (صادر/وارد)",
            "sender_number": "رقم صادر الجهة",
            "title": "عنوان الكتاب",
            "document_type": "نوع المستند",
            "secret_level": "مستوى السرية",
            "date": "تاريخنا",
            "sender_date": "تاريخ الجهة المصدرة",
            "margin": "ملاحظات",
            "needs_followup": "يحتاج متابعة",
            "due_date": "تاريخ المتابعة",
            "final_status": "الحالة النهائية",
        }
        widgets = {
            "our_number": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "مثال: 89 أو 01-2026",
                "type": "text"
            }),
            "sender_number": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "رقم صادر الجهة المرسلة (اختياري)",
                "type": "text"
            }),
            "document_type": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "مثال: مذكرة داخلية",
                "type": "text",
                "list": "documentTypeSuggestions",
            }),
            "date": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "sender_date": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "due_date": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "margin": forms.TextInput(attrs={"class": "form-control"}),
            "needs_followup": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # إضافة class للحقول التي لا تحتوي عليها
        for name, field in self.fields.items():
            widget = field.widget
            if widget.attrs.get("class"):
                continue
            if hasattr(widget, "input_type") and widget.input_type in ("date", "file"):
                widget.attrs["class"] = "form-control"
            elif widget.__class__.__name__ in ("Select", "SelectMultiple"):
                widget.attrs["class"] = "form-select"
            else:
                widget.attrs["class"] = "form-control"
    
    def clean_title(self):
        """تحقق server-side من طول العنوان"""
        title = self.cleaned_data.get('title', '')
        if len(title) > 300:
            raise forms.ValidationError("عنوان الكتاب يجب ألا يتجاوز 300 حرف.")
        return title
    
    def clean_margin(self):
        """تحقق server-side من طول الهامش"""
        margin = self.cleaned_data.get('margin', '')
        if len(margin) > 500:
            raise forms.ValidationError("هامش الكتاب يجب ألا يتجاوز 500 حرف.")
        return margin
    
    def clean(self):
        """تحقق من منطقية التواريخ"""
        cleaned_data = super().clean()
        date = cleaned_data.get('date')
        due_date = cleaned_data.get('due_date')
        
        if date and due_date and due_date < date:
            raise forms.ValidationError("تاريخ الاستحقاق يجب أن يكون بعد تاريخ الكتاب.")
        
        return cleaned_data


class AttachmentForm(forms.ModelForm):
    class Meta:
        model = Attachment
        fields = ["file"]
        labels = {"file": "إرفاق ملف (PDF/JPG/PNG)"}

    def clean_file(self):
        import magic
        f = self.cleaned_data.get("file")
        if f:
            # تحقق من الحجم
            if f.size > 10 * 1024 * 1024:
                raise forms.ValidationError("حجم الملف يتجاوز الحد الأقصى 10MB.")
            
            # تحقق من MIME type الفعلي (ليس فقط الامتداد)
            try:
                # قراءة أول 2048 بايت للتحقق من Magic Bytes
                file_content = f.read(2048)
                f.seek(0)  # إعادة المؤشر للبداية
                
                # استخدام python-magic للتحقق من النوع الحقيقي
                mime = magic.from_buffer(file_content, mime=True)
                
                allowed_mimes = [
                    'application/pdf',
                    'image/jpeg',
                    'image/png',
                    'image/jpg'
                ]
                
                if mime not in allowed_mimes:
                    raise forms.ValidationError(
                        f"نوع الملف غير مسموح ({mime}). الأنواع المسموحة: PDF, JPG, PNG فقط."
                    )
            except ImportError:
                # إذا لم تكن مكتبة python-magic مثبتة، استخدم التحقق من الامتداد فقط
                import os
                ext = os.path.splitext(f.name)[1].lower()
                if ext not in ['.pdf', '.jpg', '.jpeg', '.png']:
                    raise forms.ValidationError("نوع الملف غير مسموح. الأنواع المسموحة: PDF, JPG, PNG فقط.")
            except Exception as e:
                # في حالة خطأ غير متوقع، سجله واستمر
                import logging
                logging.warning(f"File validation warning: {e}")
        
        return f


class AttachmentReplaceForm(forms.Form):
    file = forms.FileField(label="استبدال الملف")

    def clean_file(self):
        f = self.cleaned_data.get("file")
        if f and f.size > 10 * 1024 * 1024:
            raise forms.ValidationError("حجم الملف يتجاوز الحد الأقصى 10MB.")
        return f


class AttachmentMergeForm(forms.Form):
    merge_files = forms.FileField(label="ملفات لدمجها", widget=MultipleFileInput(attrs={"multiple": True}))

    def clean_merge_files(self):
        files = self.files.getlist("merge_files")
        if not files:
            raise forms.ValidationError("يرجى اختيار ملفات للدمج.")
        for f in files:
            if f.size > 10 * 1024 * 1024:
                raise forms.ValidationError("أحد الملفات يتجاوز الحد الأقصى 10MB.")
        return files


class AttachmentRemovePagesForm(forms.Form):
    pages = forms.CharField(label="صفحات للحذف", help_text="مثال: 1,3-5")
