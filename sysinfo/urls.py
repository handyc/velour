from django.urls import path

from . import views

app_name = 'sysinfo'

urlpatterns = [
    path('', views.sysinfo_home, name='home'),
    path('snapshot.json', views.sysinfo_snapshot, name='snapshot'),
    path('health.json', views.health_json, name='health_json'),
]
