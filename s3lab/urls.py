from django.urls import path

from . import views


app_name = 's3lab'

urlpatterns = [
    path('', views.index, name='index'),
]
