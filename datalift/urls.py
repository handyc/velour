from django.urls import path

from . import views

app_name = 'datalift'

urlpatterns = [
    path('', views.job_list, name='job_list'),
    path('add/', views.job_add, name='job_add'),
    path('anonymize/', views.anonymize_upload, name='anonymize_upload'),
    path('<slug:slug>/', views.job_detail, name='job_detail'),
    path('<slug:slug>/run/', views.job_run, name='job_run'),
    path('<slug:slug>/delete/', views.job_delete, name='job_delete'),
    path('<slug:slug>/models.py', views.download_models, name='download_models'),
    path('<slug:slug>/sqlite/', views.download_sqlite, name='download_sqlite'),
    path('<slug:slug>/anonymized/', views.download_anonymized, name='download_anonymized'),
]
