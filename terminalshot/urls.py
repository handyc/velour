from django.urls import path

from . import views

app_name = 'terminalshot'

urlpatterns = [
    path('',              views.index,  name='index'),
    path('upload/',       views.upload, name='upload'),
    path('<slug:slug>/',  views.detail, name='detail'),
]
