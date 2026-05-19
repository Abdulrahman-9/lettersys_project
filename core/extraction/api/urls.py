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
    scan_token_retrieve,
    suggestions_api,
)

urlpatterns = [
    path('extract/smart/',                         smart_extract_direct,    name='ai_smart_extract'),
    path('extract/scan-token/<str:token>/',        scan_token_retrieve,     name='ai_scan_token'),
    path('suggestions/',                           suggestions_api,          name='ai_suggestions'),
    path('extract/',                               start_extraction,         name='ai_start_extraction'),
    path('extract/<int:attachment_id>/',           get_extraction_result,    name='ai_get_extraction'),
    path('extract/<int:extraction_id>/feedback/',  submit_feedback,          name='ai_submit_feedback'),
    path('extract/<int:extraction_id>/review/',    review_extraction,        name='ai_review_extraction'),
    path('extract/statistics/',                    extraction_statistics,    name='ai_extraction_statistics'),
]
