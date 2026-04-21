from django.urls import path
from . import views

app_name = 'radiant'

urlpatterns = [
    path('', views.home, name='index'),
]
