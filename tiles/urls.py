from django.urls import path

from . import views


app_name = 'tiles'

urlpatterns = [
    path('',                        views.tileset_list,     name='list'),
    path('add/',                    views.tileset_add,      name='add'),
    path('<slug:slug>/',            views.tileset_detail,   name='detail'),
    path('<slug:slug>/delete/',     views.tileset_delete,   name='delete'),
    path('<slug:slug>/generate/',   views.tileset_generate, name='generate'),
]
