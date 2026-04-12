from django.urls import path

from . import views


app_name = 'condenser'

urlpatterns = [
    path('',                       views.condenser_home,       name='home'),
    path('distill/tiles/',         views.distill_tiles,        name='distill_tiles'),
    path('distill/velour/',        views.distill_velour,       name='distill_velour'),
    path('<slug:slug>/',           views.distillation_view,    name='detail'),
    path('<slug:slug>/raw',        views.distillation_raw,     name='raw'),
    path('<slug:slug>/download',   views.distillation_download, name='download'),
]
