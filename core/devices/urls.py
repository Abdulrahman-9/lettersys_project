from django.urls import path

from . import views

page_urlpatterns = [
    path('join/', views.join_page, name='device_join'),
]

api_urlpatterns = [
    path('me/', views.api_me, name='device_me'),
    path('join/check/', views.api_join_check, name='device_join_check'),
    path('join/finish/', views.api_join_finish, name='device_join_finish'),
    path('join/request/', views.api_join_request, name='device_join_request'),
    path('declare/start/', views.api_declare_start, name='device_declare_start'),
    path('declare/finish/', views.api_declare_finish, name='device_declare_finish'),
    path('report/', views.api_report, name='device_report'),
    path('board/', views.api_board, name='device_board'),
    path('codes/', views.api_issue_code, name='device_issue_code'),
    path('codes/<int:pk>/', views.api_code_state, name='device_code_state'),
    path('codes/<int:pk>/cancel/', views.api_cancel_code, name='device_cancel_code'),
    path('mode/', views.api_mode, name='device_mode'),
    path('<uuid:pk>/<slug:action>/', views.api_device_action, name='device_action'),
]
