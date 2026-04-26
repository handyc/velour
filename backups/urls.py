from django.urls import path
from . import views

app_name = 'backups'

urlpatterns = [
    path('', views.index, name='index'),
]
