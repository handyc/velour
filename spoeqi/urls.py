from django.urls import path

from . import views


app_name = 'spoeqi'

urlpatterns = [
    path('',                   views.index,    name='index'),
    path('new/',               views.create,   name='create'),
    path('<slug:slug>/',       views.detail,   name='detail'),
    path('<slug:slug>/delete/', views.delete,  name='delete'),
    path('<slug:slug>/export-tile/<int:component>/',
                                views.export_tile_to_automaton,
                                name='export_tile'),
]
