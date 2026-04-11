from django.urls import path

from . import views

app_name = 'sysinfo'

urlpatterns = [
    path('', views.sysinfo_home, name='home'),
    path('health.json', views.health_json, name='health_json'),
]
