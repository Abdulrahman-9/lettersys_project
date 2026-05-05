from django.apps import AppConfig

class CoreConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'core'

    def ready(self):
        # تسجيل signals (إبطال الكاش عند تعديل Entity/Book)
        from . import signals  # noqa: F401
        # تسجيل نماذج السجلّات (UserActivityLog/PerformanceLog/ErrorLog/ClientLog)
        from . import logging_models  # noqa: F401
