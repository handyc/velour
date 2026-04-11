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
]
