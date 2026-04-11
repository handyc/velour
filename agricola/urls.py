from django.urls import path

from . import views

app_name = 'agricola'

urlpatterns = [
    path('', views.game, name='game'),
]
