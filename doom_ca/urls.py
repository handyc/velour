from django.urls import path

from . import views


app_name = 'doom_ca'

urlpatterns = [
    path('',                   views.index,  name='index'),
    path('new/',               views.create, name='create'),
    path('<slug:slug>/',       views.play,   name='play'),
    path('<slug:slug>/delete/', views.delete, name='delete'),
]
