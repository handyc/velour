from django.urls import path

from . import views


app_name = 'retrogames'

urlpatterns = [
    path('',                       views.index,    name='index'),
    path('platform/<slug:slug>/',  views.platform, name='platform'),
    path('game/<int:pid>/<slug:slug>/', views.game, name='game'),
]
