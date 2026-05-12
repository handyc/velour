from django.urls import path

from . import views

app_name = 'tessera'

urlpatterns = [
    path('',                          views.index,        name='index'),
    path('new/',                      views.create_set,   name='create'),
    path('bake-ca/',                  views.bake_ca,      name='bake-ca'),
    path('<slug:slug>/',              views.detail,       name='detail'),
    path('<slug:slug>/tiling/',       views.tiling_test,  name='tiling'),
    path('<slug:slug>/source/<int:color_idx>.png',
                                      views.source_png,   name='source-png'),
    path('<slug:slug>/tile/<str:tile_id>.png',
                                      views.tile_png,     name='tile-png'),
    path('<slug:slug>/swap-source/<int:color_idx>/',
                                      views.swap_source,  name='swap-source'),
    path('<slug:slug>/swap-palette/<int:color_idx>/',
                                      views.swap_palette, name='swap-palette'),
]
