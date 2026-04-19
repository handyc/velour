from django.urls import path

from . import views

app_name = 'powerlab'

urlpatterns = [
    path('', views.index, name='index'),
    path('parts/', views.parts, name='parts'),
    path('parts/<slug:slug>/', views.part_detail, name='part_detail'),
    path('parts/<slug:slug>/price/',
         views.part_record_price, name='part_record_price'),
    path('<slug:slug>/', views.detail, name='detail'),
    path('<slug:slug>/compare/', views.compare, name='compare'),
    path('<slug:slug>/schematic/edit/',
         views.edit_schematic, name='edit_schematic'),
    path('<slug:slug>/schematic/save/',
         views.save_schematic, name='save_schematic'),
]
