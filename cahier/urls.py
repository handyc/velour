from django.urls import path

from . import views

app_name = 'cahier'

urlpatterns = [
    path('',                     views.index,    name='index'),
    path('<slug:slug>/',         views.detail,   name='detail'),
    path('<slug:slug>/raw/',     views.raw,      name='raw'),
    path('<slug:slug>/html/',    views.html,     name='html'),
    path('<slug:slug>/download/', views.download, name='download'),
]
