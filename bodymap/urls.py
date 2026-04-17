from django.urls import path

from . import flash_views, views


app_name = 'bodymap'

urlpatterns = [
    path('',                        views.bodymap_list,       name='list'),
    path('api/segment/',            views.api_report_segment, name='api_segment'),
    path('flash/',                  flash_views.flash_page,   name='flash'),
    path('flash/devices/',          flash_views.flash_devices,name='flash_devices'),
    path('flash/run/',              flash_views.flash_run,    name='flash_run'),
    path('flash/log/<slug:job_id>/',flash_views.flash_log,    name='flash_log'),
    path('flash/build/',            flash_views.flash_build,  name='flash_build'),
    path('<slug:experiment_slug>/', views.bodymap_diagram,    name='diagram'),
]
