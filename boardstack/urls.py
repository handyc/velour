from django.urls import path
from . import views

app_name = 'boardstack'

urlpatterns = [
    path('', views.index, name='index'),
]
