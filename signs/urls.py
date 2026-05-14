from django.urls import path

from . import views


app_name = 'signs'

urlpatterns = [
    path('',                      views.index,   name='index'),
    path('view/<slug:slug>/',     views.viewer,  name='viewer'),
    path('<slug:slug>/frames.json', views.frames_json, name='frames_json'),
    path('<slug:slug>/',          views.detail,  name='detail'),
]
