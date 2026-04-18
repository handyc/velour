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
    path('stillness/', views.stillness_now, name='stillness_now'),
    path('cron/run-now/', views.cron_run_now, name='cron_run_now'),
    path('toggles/', views.toggles_update, name='toggles_update'),
    path('ruminate.json', views.rumination_json, name='rumination_json'),
    path('dialogue.json', views.internal_dialogue_json, name='internal_dialogue_json'),
    path('who/', views.who_is_velour, name='who'),
    path('continuity/', views.continuity_timeline, name='continuity'),
    path('state-machine/', views.state_machine_view, name='state_machine'),
    path('document/', views.identity_document, name='identity_document'),
    path('document/regenerate/', views.identity_document_regenerate,
         name='identity_document_regenerate'),
    path('chat/', views.llm_chat, name='llm_chat'),
    path('chat/send/', views.llm_chat_send, name='llm_chat_send'),
    path('chat/<int:pk>/ingest/', views.llm_exchange_ingest,
         name='llm_exchange_ingest'),
    path('ticks/<int:tick_pk>/feedback/', views.rumination_feedback,
         name='rumination_feedback'),

    path('mental-health/', views.mental_health, name='mental_health'),

    # Session-reflection — close-of-day loop, manual and continuous.
    path('session-reflect/',
         views.session_reflect_home, name='session_reflect'),
    path('session-reflect/run/',
         views.session_reflect_run, name='session_reflect_run'),
    path('session-reflect/<int:pk>/',
         views.session_reflect_detail, name='session_reflect_detail'),
    path('session-reflect/loop/toggle/',
         views.session_reflect_loop_toggle, name='session_reflect_loop_toggle'),
    path('session-reflect/loop/tick/',
         views.session_reflect_loop_tick, name='session_reflect_loop_tick'),

    # Hofstadter routes — absorbed from the standalone hofstadter app.
    path('hofstadter/', views.hof_home, name='hof_home'),
    path('hofstadter/experiments/', views.hof_experiment_list, name='hof_experiment_list'),
    path('hofstadter/experiments/<slug:slug>/', views.hof_experiment_detail, name='hof_experiment_detail'),
    path('hofstadter/experiments/<slug:slug>/run/', views.hof_experiment_run, name='hof_experiment_run'),
    path('hofstadter/loops/<slug:slug>/', views.hof_loop_detail, name='hof_loop_detail'),
    path('hofstadter/loops/<slug:slug>/traverse/', views.hof_loop_traverse, name='hof_loop_traverse'),
]
