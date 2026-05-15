from django.urls import path

from . import views

app_name = 'scriptorium'

urlpatterns = [
    path('', views.home, name='home'),
    path('p/<slug:slug>/', views.project_detail, name='project'),
    path('p/<slug:slug>/ingest/', views.ingest_page, name='ingest'),
    path('p/<slug:slug>/ingest/run/', views.ingest_run, name='ingest_run'),
    path('p/<slug:slug>/deploy/', views.deploy_page, name='deploy'),
    path('p/<slug:slug>/deploy/run/', views.deploy_run, name='deploy_run'),
    path('p/<slug:slug>/remote-ingest/', views.remote_ingest_run, name='remote_ingest_run'),
    path('p/<slug:slug>/backups/', views.backups_page, name='backups'),
    path('p/<slug:slug>/backups/local/new/', views.local_backup_now, name='local_backup_now'),
    path('p/<slug:slug>/backups/remote/new/', views.remote_backup_now, name='remote_backup_now'),
    path('p/<slug:slug>/backups/restore/', views.restore_backup, name='restore_backup'),
    path('p/<slug:slug>/backups/download/<str:name>/', views.download_backup, name='download_backup'),
    path('runs/<int:run_id>/', views.run_detail, name='run_detail'),
]
