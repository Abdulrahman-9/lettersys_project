from django.contrib import admin
from .models import Entity, Book, Attachment, Notification, BookHistory, AIIntegrationSettings, BookEmailLog, EmailSettings, EmailThread, IncomingEmail, EmailTemplate

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
    list_display = ('our_number','sender_number','document_type','kind','date','final_status','needs_followup','is_overdue')
    list_filter = ('kind','final_status','secret_level','date','is_overdue','needs_followup')
    search_fields = ('our_number','sender_number','title','document_type')
    inlines = [AttachmentInline]

@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ('user','message','is_read','created_at')
    list_filter = ('is_read',)

@admin.register(BookHistory)
class BookHistoryAdmin(admin.ModelAdmin):
    list_display = ('book','action','by','created_at')
    list_filter = ('action',)


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
