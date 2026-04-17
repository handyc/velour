from django.urls import path

from . import views


app_name = 'bodymap'

urlpatterns = [
    path('',                        views.bodymap_list,      name='list'),
    path('api/segment/',            views.api_report_segment, name='api_segment'),
    path('<slug:experiment_slug>/', views.bodymap_diagram,   name='diagram'),
]
