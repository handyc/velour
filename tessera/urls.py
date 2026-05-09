from django.urls import path

from . import views

app_name = 'tessera'

urlpatterns = [
    path('',                          views.index,        name='index'),
    path('new/',                      views.create_set,   name='create'),
    path('<slug:slug>/',              views.detail,       name='detail'),
    path('<slug:slug>/tiling/',       views.tiling_test,  name='tiling'),
    path('<slug:slug>/source/<int:color_idx>.png',
                                      views.source_png,   name='source-png'),
    path('<slug:slug>/tile/<str:tile_id>.png',
                                      views.tile_png,     name='tile-png'),
]
