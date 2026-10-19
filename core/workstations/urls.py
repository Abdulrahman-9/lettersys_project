from django.urls import path

from . import views

urlpatterns = [
    path('', views.device_board, name='workstation_board'),
    path('api/enroll/', views.enroll, name='workstation_enroll'),
    path('api/mine/', views.my_devices, name='workstation_mine'),
    path('api/status/', views.device_status, name='workstation_status'),
    path('api/heartbeat/', views.heartbeat, name='workstation_heartbeat'),
    path('api/<uuid:pk>/revoke/', views.revoke, name='workstation_revoke'),
    path('api/<uuid:pk>/unblock/', views.unblock, name='workstation_unblock'),
]
