from django.urls import path

from . import views


app_name = 's3lab'

urlpatterns = [
    path('',                       views.index,           name='index'),
    path('gallery/',               views.gallery,         name='gallery'),
    path('compile/',               views.compile_page,    name='compile_page'),
    path('compile/run/',           views.compile_run,     name='compile_run'),
    path('compile/push/',          views.compile_push,    name='compile_push'),
    path('device/',                views.device_page,     name='device_page'),
    path('device/info/',           views.device_info,     name='device_info'),
    path('device/action/',         views.device_action,   name='device_action'),
    path('slots/',                 views.slots_list,      name='slots_list'),
    path('slots/<slug:slug>/',     views.slot_detail,     name='slot_detail'),
    path('slots/<slug:slug>/elf',  views.slot_download,   name='slot_download'),
    path('slots/<slug:slug>/repush/', views.slot_repush,  name='slot_repush'),
    path('cellular/to-tiles/',     views.cellular_to_tiles,    name='cellular_to_tiles'),
    path('cellular/to-zoetrope/',  views.cellular_to_zoetrope, name='cellular_to_zoetrope'),
    path('cellular/tft/',          views.cellular_tft,         name='cellular_tft'),
    path('<slug:slug>/',           views.sublab,          name='sublab'),
]
