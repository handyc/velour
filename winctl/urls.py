from django.urls import path

from . import views

app_name = 'winctl'

urlpatterns = [
    path('', views.winctl_home, name='home'),
    path('api/processes/', views.win_processes, name='processes'),
    path('api/services/', views.win_services, name='services'),
    path('api/disks/', views.win_disks, name='disks'),
    path('api/network/', views.win_network, name='network'),
    path('api/installed/', views.win_installed, name='installed'),
    path('api/startup/', views.win_startup, name='startup'),
    path('api/eventlog/', views.win_eventlog, name='eventlog'),
    path('api/env/', views.win_env, name='env'),
    path('api/tasks/', views.win_scheduled_tasks, name='tasks'),
    path('api/firewall/', views.win_firewall, name='firewall'),
    path('api/run/', views.win_run, name='run'),
]
