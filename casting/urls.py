from django.urls import path

from . import views

app_name = 'casting'

urlpatterns = [
    path('', views.index, name='index'),
    path('<slug:slug>/', views.detail, name='detail'),
    path('<slug:slug>/source', views.source, name='source'),
]
