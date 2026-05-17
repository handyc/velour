from django.urls import path
from . import views

app_name = 'optikon'

urlpatterns = [
    path('',                  views.index,        name='index'),
    path('depth/upload/',     views.depth_upload, name='depth_upload'),
    path('autostereogram/decode/', views.autostereogram_decode,
                                              name='autostereogram_decode'),
    path('<slug:slug>/',      views.detail,       name='detail'),
    path('<slug:slug>/svg',   views.svg,          name='svg'),
    path('<slug:slug>/print', views.print_view,   name='print'),
]
