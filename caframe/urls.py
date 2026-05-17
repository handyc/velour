from django.urls import path
from . import views

app_name = 'caframe'

urlpatterns = [
    path('',                       views.index,           name='index'),
    path('evolve/',                views.evolve_view,     name='evolve'),
    path('evolve/stream/',         views.evolve_stream,   name='evolve_stream'),
    path('evolve/save/',           views.evolve_save,     name='evolve_save'),
    path('quick.apng',             views.quick_apng,      name='quick_apng'),
    path('quick/save/',            views.quick_save,      name='quick_save'),
    path('import/',                views.import_source,   name='import_source'),
    path('<slug:slug>/',           views.sequence_detail, name='detail'),
    path('<slug:slug>.apng',       views.sequence_apng,   name='apng'),
    path('<slug:slug>.mp4',        views.sequence_mp4,    name='mp4'),
]
