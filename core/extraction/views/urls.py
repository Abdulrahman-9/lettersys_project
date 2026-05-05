"""
core.extraction.views.urls
===========================
URL routing for extraction UI views.
"""

from django.urls import path
from .ui import (
    extraction_quick_start,
    extraction_wizard,
    extraction_smart_desktop,
    extraction_results,
)

urlpatterns = [
    path('quick-start/',          extraction_quick_start,   name='extraction-quick-start'),
    path('wizard/',               extraction_wizard,         name='extraction-wizard'),
    path('smart-desktop/',        extraction_smart_desktop,  name='extraction-smart-desktop'),
    path('results/<int:extraction_id>/', extraction_results, name='extraction-results-ui'),
]
