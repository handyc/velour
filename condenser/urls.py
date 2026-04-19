from django.urls import path

from . import views


app_name = 'condenser'

urlpatterns = [
    path('',                       views.condenser_home,       name='home'),
    path('distill/tiles/',         views.distill_tiles,        name='distill_tiles'),
    path('distill/tiles-esp/',     views.distill_tiles_esp,    name='distill_tiles_esp'),
    path('distill/tiles-attiny/',  views.distill_tiles_attiny, name='distill_tiles_attiny'),
    path('distill/tiles-circuit/', views.distill_tiles_circuit, name='distill_tiles_circuit'),
    path('distill/full-chain/',    views.distill_full_chain,   name='distill_full_chain'),
    path('distill/velour/',        views.distill_velour,       name='distill_velour'),
    path('distill/det-attiny13a/', views.distill_det_attiny13a, name='distill_det_attiny13a'),
    path('distill/det-attiny85/',  views.distill_det_attiny85,  name='distill_det_attiny85'),
    path('distill/det-esp8266/',   views.distill_det_esp8266,   name='distill_det_esp8266'),
    path('distill/det-esp32s3/',   views.distill_det_esp32s3,   name='distill_det_esp32s3'),
    path('distill/aether/<slug:slug>/stereokit/', views.distill_aether_stereokit, name='distill_aether_stereokit'),
    path('decision-tree/',             views.decision_tree_form,   name='decision_tree'),
    path('decision-tree/555/',         views.decision_tree_555,    name='decision_tree_555'),
    path('live/<str:app_label>/',  views.live_condense,        name='live'),
    path('<slug:slug>/',           views.distillation_view,    name='detail'),
    path('<slug:slug>/raw',        views.distillation_raw,     name='raw'),
    path('<slug:slug>/download',   views.distillation_download, name='download'),
    path('<slug:slug>/emulate',    views.emulate_attiny,       name='emulate_attiny'),
]
