from django.urls import path

from . import views


app_name = 's3lab'

urlpatterns = [
    path('',                  views.index,         name='index'),
    path('compile/',          views.compile_page,  name='compile_page'),
    path('compile/run/',      views.compile_run,   name='compile_run'),
    path('compile/push/',     views.compile_push,  name='compile_push'),
    path('<slug:slug>/',      views.sublab,        name='sublab'),
]
