from django.urls import path

from . import views

app_name = 'identity'

urlpatterns = [
    path('', views.identity_home, name='home'),
    path('journal/', views.identity_journal, name='journal'),
    path('update/', views.identity_update, name='update'),
    path('mood-data/', views.mood_data, name='mood_data'),
    path('state.json', views.state_json, name='state_json'),
    path('tick/', views.tick_now, name='tick_now'),
    path('ticks/', views.tick_log, name='tick_log'),
    path('concerns/', views.concerns_list, name='concerns_list'),
    path('concerns/<int:pk>/close/', views.concern_close, name='concern_close'),
    path('reflections/', views.reflections_list, name='reflections_list'),
    path('reflections/<int:pk>/', views.reflection_detail, name='reflection_detail'),
    path('reflections/compose/', views.reflection_compose, name='reflection_compose'),
    path('meditations/', views.meditations_list, name='meditations_list'),
    path('meditations/<int:pk>/', views.meditation_detail, name='meditation_detail'),
    path('meditations/compose/', views.meditation_compose, name='meditation_compose'),
    path('cron/run-now/', views.cron_run_now, name='cron_run_now'),
    path('toggles/', views.toggles_update, name='toggles_update'),
    path('document/', views.identity_document, name='identity_document'),
    path('document/regenerate/', views.identity_document_regenerate,
         name='identity_document_regenerate'),
    path('ticks/<int:tick_pk>/feedback/', views.rumination_feedback,
         name='rumination_feedback'),
]
