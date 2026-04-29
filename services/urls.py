from django.urls import path

from . import views

app_name = 'services'

urlpatterns = [
    path('', views.services_home, name='home'),
    path('local-nginx/toggle/', views.local_nginx_toggle,
         name='local_nginx_toggle'),
]
