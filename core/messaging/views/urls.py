"""
core.messaging.views.urls
==========================
URL routing for the mail web UI section.
Mounted at /mail/ in lettersys/urls.py (or core/urls.py).
"""

from django.urls import path
from .ui import (
    mail_hub,
    mail_sent,
    mail_inbox,
    mail_compose,
    mail_thread,
    mail_settings,
    mail_templates,
    mail_template_edit,
    mail_template_delete,
)

urlpatterns = [
    path('',                             mail_hub,               name='mail_hub'),
    path('sent/',                        mail_sent,              name='mail_sent'),
    path('inbox/',                       mail_inbox,             name='mail_inbox'),
    path('compose/',                     mail_compose,           name='mail_compose'),
    path('compose/<int:book_id>/',       mail_compose,           name='mail_compose_book'),
    path('thread/<int:thread_id>/',      mail_thread,            name='mail_thread'),
    path('settings/',                    mail_settings,          name='mail_settings'),
    path('templates/',                   mail_templates,         name='mail_templates'),
    path('templates/new/',               mail_template_edit,     name='mail_template_new'),
    path('templates/<int:template_id>/edit/',   mail_template_edit,   name='mail_template_edit'),
    path('templates/<int:template_id>/delete/', mail_template_delete, name='mail_template_delete'),
]
