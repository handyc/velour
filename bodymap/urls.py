from django.urls import path

from . import attiny_views, flash_views, views


app_name = 'bodymap'

urlpatterns = [
    path('',                                 views.bodymap_list,              name='list'),
    path('api/segment/',                     views.api_report_segment,        name='api_segment'),
    path('api/config/<slug:slug>/',          views.api_node_config,           name='api_config'),
    path('config/<slug:slug>/',              views.bodymap_node_config,       name='node_config'),
    path('flash/',                           flash_views.flash_page,          name='flash'),
    path('flash/devices/',                   flash_views.flash_devices,       name='flash_devices'),
    path('flash/run/',                       flash_views.flash_run,           name='flash_run'),
    path('flash/log/<slug:job_id>/',         flash_views.flash_log,           name='flash_log'),
    path('flash/build/',                     flash_views.flash_build,         name='flash_build'),

    path('attiny/',                          attiny_views.attiny_index,             name='attiny_index'),
    path('attiny/emulate/',                  attiny_views.attiny_emulate,           name='attiny_emulate'),
    path('attiny/emulate/<slug:slug>/',      attiny_views.attiny_emulate,           name='attiny_emulate_slug'),
    path('attiny/template/<slug:slug>/',     attiny_views.attiny_template_detail,   name='attiny_template'),
    path('attiny/template/<slug:slug>/fork/', attiny_views.attiny_fork_template,    name='attiny_fork'),
    path('attiny/design/<slug:slug>/',       attiny_views.attiny_design_detail,     name='attiny_design'),
    path('attiny/design/<slug:slug>/save/',  attiny_views.attiny_design_save,       name='attiny_design_save'),
    path('attiny/design/<slug:slug>/build/', attiny_views.attiny_design_build,      name='attiny_design_build'),
    path('attiny/design/<slug:slug>/hex/',   attiny_views.attiny_design_hex,        name='attiny_design_hex'),
    path('attiny/design/<slug:slug>/delete/', attiny_views.attiny_design_delete,    name='attiny_design_delete'),

    path('<slug:experiment_slug>/',          views.bodymap_diagram,                 name='diagram'),
]
