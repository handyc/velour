from django.urls import path

from . import views


app_name = 'nodes'

urlpatterns = [
    path('',                         views.node_list,       name='list'),
    path('add/',                     views.node_add,        name='add'),
    path('hardware/',                views.hardware_list,   name='hardware_list'),
    path('hardware/add/',            views.hardware_add,    name='hardware_add'),
    path('hardware/<int:pk>/edit/',  views.hardware_edit,   name='hardware_edit'),
    path('hardware/<int:pk>/delete/',views.hardware_delete, name='hardware_delete'),
    path('firmware/',                views.firmware_list,   name='firmware_list'),
    path('firmware/upload/',         views.firmware_upload, name='firmware_upload'),
    path('firmware/<int:pk>/activate/', views.firmware_activate, name='firmware_activate'),
    path('firmware/<int:pk>/delete/',   views.firmware_delete,   name='firmware_delete'),
    path('<slug:slug>/',             views.node_detail,     name='detail'),
    path('<slug:slug>/edit/',        views.node_edit,       name='edit'),
    path('<slug:slug>/delete/',      views.node_delete,     name='delete'),
    path('<slug:slug>/rotate-token/',views.node_rotate_token, name='rotate_token'),
    path('<slug:slug>/live.json',    views.node_live_json,  name='live_json'),
]
