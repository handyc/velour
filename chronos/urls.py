from django.urls import path

from . import views


app_name = 'chronos'

urlpatterns = [
    path('',                       views.home,           name='home'),
    path('settings/',              views.settings_view,  name='settings'),
    path('watched/add/',           views.watched_add,    name='watched_add'),
    path('watched/<int:pk>/edit/', views.watched_edit,   name='watched_edit'),
    path('watched/<int:pk>/delete/', views.watched_delete, name='watched_delete'),
    path('now.json',               views.now_json,       name='now_json'),

    # Calendar (Phase 2a)
    path('calendar/',                views.calendar_month, name='calendar'),
    path('calendar/<int:year>/<int:month>/',
         views.calendar_month, name='calendar_month'),
    path('calendar/<int:year>/<int:month>/<int:day>/',
         views.calendar_day, name='calendar_day'),
    path('events/add/',              views.event_add,    name='event_add'),
    path('events/<slug:slug>/edit/', views.event_edit,   name='event_edit'),
    path('events/<slug:slug>/delete/', views.event_delete, name='event_delete'),
]
