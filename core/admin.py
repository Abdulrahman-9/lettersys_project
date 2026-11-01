from django.contrib import admin
from .auth_views import LOGIN_RATE_LIMIT
from .decorators import rate_limit
from .models import Entity, Book, Attachment, Notification, BookHistory, AIIntegrationSettings, BookEmailLog, EmailSettings, EmailThread, IncomingEmail, EmailTemplate
from .scoping import is_privileged

# لوحةُ Django لا تعرف الأقسام ولا السرّيّة ولا BookHistory: ما يُعدَّل منها يتخطّى
# ``core/scoping.py`` وسجلَّ الحركات. فهي لمدير النظام وحدَه — لا لكلّ حاملِ
# ``is_staff`` تمنحه مجموعةُ دورٍ صلاحيّةَ نموذج (``roles.ensure_role_groups``).
admin.site.has_permission = lambda request: request.user.is_active and is_privileged(request.user)

_admin_login = admin.site.login
_admin_login_limited = rate_limit('login', **LOGIN_RATE_LIMIT)(_admin_login)


def _admin_login_with_limit(request, extra_context=None):
    """بابُ /admin/login/ يقاسم /login/ دلوَ محاولاته — والحدُّ على الإرسال وحدَه كأخيه."""
    if request.method == 'POST':
        return _admin_login_limited(request, extra_context)
    return _admin_login(request, extra_context)


admin.site.login = _admin_login_with_limit

@admin.register(Entity)
class EntityAdmin(admin.ModelAdmin):
    list_display  = ('name', 'code', 'etype', 'email', 'notify_on_receive', 'notify_on_send', 'is_active')
    search_fields = ('name', 'code', 'email')
    list_filter   = ('etype', 'is_active', 'notify_on_receive', 'notify_on_send')
    fieldsets = (
        ('معلومات أساسية', {'fields': ('name', 'code', 'etype', 'is_active')}),
        ('بيانات الاتصال', {'fields': ('email', 'email_cc', 'phone', 'address', 'contact_person', 'notes')}),
        ('إعدادات الإشعارات', {'fields': ('notify_on_receive', 'notify_on_send')}),
    )

class AttachmentInline(admin.TabularInline):
    model = Attachment
    extra = 0

@admin.register(Book)
class BookAdmin(admin.ModelAdmin):
    list_display = ('our_number','sender_number','document_type','kind','date','due_date','is_archived')
    list_filter = ('kind','is_archived','secret_level','date')
    search_fields = ('our_number','sender_number','title','document_type')
    inlines = [AttachmentInline]

@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ('user','message','is_read','created_at')
    list_filter = ('is_read',)

@admin.register(BookHistory)
class BookHistoryAdmin(admin.ModelAdmin):
    """سجلُّ أفعال الكتاب أثرٌ لا مسودّة: يُقرأ ولا يُضاف إليه ولا يُعدَّل ولا يُحذف."""
    list_display = ('book','action','by','created_at')
    list_filter = ('action',)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(BookEmailLog)
class BookEmailLogAdmin(admin.ModelAdmin):
    list_display  = ('book', 'to_address', 'subject', 'status', 'trigger', 'sent_at')
    list_filter   = ('status', 'trigger', 'sent_at')
    search_fields = ('to_address', 'subject', 'book__our_number')
    readonly_fields = ('sent_at', 'delivered_at')


@admin.register(EmailSettings)
class EmailSettingsAdmin(admin.ModelAdmin):
    list_display  = ('org_name', 'org_email', 'smtp_host', 'smtp_port', 'is_active', 'send_on_save', 'imap_sync_enabled', 'updated_at')
    readonly_fields = ('singleton', 'updated_at', 'imap_last_sync')
    fieldsets = (
        ('هوية المؤسسة', {'fields': ('org_name', 'org_email', 'reply_to', 'email_signature')}),
        ('SMTP', {'fields': ('smtp_host', 'smtp_port', 'smtp_use_tls', 'smtp_use_ssl', 'smtp_user', 'smtp_password')}),
        ('IMAP (استقبال الردود)', {'fields': ('imap_host', 'imap_port', 'imap_use_ssl', 'imap_user', 'imap_password', 'imap_folder', 'imap_sync_enabled', 'imap_last_sync')}),
        ('التفعيل', {'fields': ('is_active', 'send_on_save', 'singleton', 'updated_at')}),
    )


@admin.register(EmailThread)
class EmailThreadAdmin(admin.ModelAdmin):
    list_display  = ('subject', 'status', 'entity', 'book', 'created_by', 'last_activity')
    list_filter   = ('status',)
    search_fields = ('subject',)
    readonly_fields = ('created_at', 'last_activity')
    raw_id_fields = ('book', 'entity', 'created_by')


@admin.register(IncomingEmail)
class IncomingEmailAdmin(admin.ModelAdmin):
    list_display  = ('from_address', 'subject', 'thread', 'is_read', 'received_at')
    list_filter   = ('is_read', 'is_spam')
    search_fields = ('from_address', 'subject', 'message_id')
    readonly_fields = ('synced_at', 'received_at', 'message_id', 'imap_uid')
    raw_id_fields = ('thread',)


@admin.register(EmailTemplate)
class EmailTemplateAdmin(admin.ModelAdmin):
    list_display  = ('name', 'slug', 'applicable_kind', 'is_active', 'is_default', 'created_by')
    list_filter   = ('applicable_kind', 'is_active')
    search_fields = ('name', 'slug', 'subject_template')
    readonly_fields = ('created_at', 'updated_at')
    prepopulated_fields = {'slug': ('name',)}


@admin.register(AIIntegrationSettings)
class AIIntegrationSettingsAdmin(admin.ModelAdmin):
    list_display = ('provider','enabled','fallback_on_low_confidence','low_confidence_threshold','updated_at')
    readonly_fields = ('singleton',)
    fieldsets = (
        (None, {
            'fields': ('singleton','enabled','provider','fallback_on_low_confidence','low_confidence_threshold')
        }),
        ('Azure', {
            'fields': ('azure_endpoint','azure_key'),
            'description': 'Azure Computer Vision Read API'
        }),
    )
