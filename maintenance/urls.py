from django.urls import path

from . import views

app_name = 'maintenance'

urlpatterns = [
    path('', views.maintenance_home, name='home'),
    path('backup/', views.backup_create, name='backup_create'),
    path('restore/<int:pk>/', views.backup_restore, name='backup_restore'),
    path('download/<int:pk>/', views.backup_download, name='backup_download'),
    path('delete/<int:pk>/', views.backup_delete, name='backup_delete'),
    path('archive/<int:pk>/', views.backup_archive, name='backup_archive'),
]
