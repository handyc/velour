from django.urls import path

from . import views

app_name = 'forge'

urlpatterns = [
    path('',                  views.circuit_list,    name='list'),
    path('new/',              views.circuit_new,     name='new'),
    path('<slug:slug>/',      views.circuit_detail,  name='detail'),
    path('<slug:slug>/save/', views.circuit_save,    name='save'),
    path('<slug:slug>/run/',  views.circuit_run,     name='run'),
    path('<slug:slug>/delete/', views.circuit_delete, name='delete'),
]
