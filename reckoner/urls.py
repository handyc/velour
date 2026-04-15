from django.urls import path

from . import views

app_name = 'reckoner'

urlpatterns = [
    path('', views.index, name='index'),
    path('apps/', views.apps, name='apps'),
    path('<slug:slug>/', views.detail, name='detail'),
]
