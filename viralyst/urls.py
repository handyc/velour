from django.urls import path

from . import views

app_name = 'viralyst'

urlpatterns = [
    path('', views.index, name='index'),
    path('corpus/<slug:slug>/', views.corpus_detail, name='corpus_detail'),
    path('language/<slug:slug>/', views.language_detail, name='language_detail'),
    path('sample/<slug:slug>/', views.sample_detail, name='sample_detail'),
    path('sample/<slug:slug>/raw/', views.sample_raw, name='sample_raw'),
]
