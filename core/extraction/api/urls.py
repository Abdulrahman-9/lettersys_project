"""
core.extraction.api.urls
=========================
URL routing for extraction REST API endpoints.
"""

from django.urls import path
from .endpoints import (
    start_extraction,
    get_extraction_result,
    submit_feedback,
    review_extraction,
    extraction_statistics,
    smart_extract_direct,
    suggestions_api,
)

urlpatterns = [
    path('extract/smart/',                         smart_extract_direct,    name='ext_smart_extract'),
    path('suggestions/',                           suggestions_api,          name='ext_suggestions'),
    path('extract/',                               start_extraction,         name='ext_start'),
    path('extract/<int:attachment_id>/',           get_extraction_result,    name='ext_get_result'),
    path('extract/<int:extraction_id>/feedback/',  submit_feedback,          name='ext_feedback'),
    path('extract/<int:extraction_id>/review/',    review_extraction,        name='ext_review'),
    path('extract/statistics/',                    extraction_statistics,    name='ext_statistics'),
]
