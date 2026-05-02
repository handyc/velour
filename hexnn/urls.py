from django.urls import path

from . import views


app_name = 'hexnn'

urlpatterns = [
    path('',     views.index,        name='index'),
    path('tft/', views.tft_emulator, name='tft_emulator'),
]
