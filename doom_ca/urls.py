from django.urls import path

from . import views


app_name = 'doom_ca'

urlpatterns = [
    path('',                   views.index,  name='index'),
    path('new/',               views.create, name='create'),
    path('evolve/',            views.evolve, name='evolve'),
    path('evolve/materialize/', views.materialize_agent, name='materialize'),
    path('<slug:slug>/',       views.play,   name='play'),
    path('<slug:slug>/delete/', views.delete, name='delete'),
    path('<slug:slug>/export/', views.export, name='export'),
]
