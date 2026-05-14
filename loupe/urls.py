from django.urls import path

from . import views


app_name = 'loupe'

urlpatterns = [
    path('',                  views.index,    name='index'),
    path('walks/',            views.walks_list,    name='walks'),
    path('walks/save/',       views.save_walk,     name='save_walk'),
    path('walks/save-many/',  views.save_walks,    name='save_walks'),
    path('w/<slug:slug>/',    views.walk_detail,   name='walk_detail'),
    path('w/<slug:slug>/delete/', views.walk_delete, name='walk_delete'),
    path('w/<slug:slug>/render.png',  views.walk_png,
                                       name='walk_png'),
    path('mandel.png',        views.mandelbrot_png, name='mandel_png'),
]
