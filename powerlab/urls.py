from django.urls import path

from . import views

app_name = 'powerlab'

urlpatterns = [
    path('', views.index, name='index'),
    path('parts/', views.parts, name='parts'),
    path('parts/<slug:slug>/', views.part_detail, name='part_detail'),
    path('<slug:slug>/', views.detail, name='detail'),
]
