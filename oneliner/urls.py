from django.urls import path

from . import views


app_name = 'oneliner'

urlpatterns = [
    path('',                         views.index,         name='index'),
    path('new/',                     views.create,        name='create'),
    path('<slug:slug>/',             views.detail,        name='detail'),
    path('<slug:slug>/edit/',        views.edit,          name='edit'),
    path('<slug:slug>/compile/',     views.compile_view,  name='compile'),
    path('<slug:slug>/run/',         views.run_view,      name='run'),
    path('<slug:slug>/delete/',      views.delete,        name='delete'),
]
