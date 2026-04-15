from django.urls import path

from . import views

app_name = 'bridge'

urlpatterns = [
    path('', views.home, name='home'),
    path('warp/', views.warp, name='warp'),
    path('library/', views.library, name='library'),
]
