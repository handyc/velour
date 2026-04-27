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
    # Deep-time browsing (Phase 2d)
    path('calendar/year/<int:year>/',
         views.calendar_year, name='calendar_year'),
    path('calendar/decade/<int:decade_start>/',
         views.calendar_decade, name='calendar_decade'),
    path('calendar/century/<int:century_start>/',
         views.calendar_century, name='calendar_century'),
    path('calendar/millennium/<int:millennium_start>/',
         views.calendar_millennium, name='calendar_millennium'),
    path('calendar/10ky/<int:start>/',
         views.calendar_ten_ky, name='calendar_ten_ky'),
    path('calendar/100ky/<int:start>/',
         views.calendar_hundred_ky, name='calendar_hundred_ky'),

    path('events/add/',              views.event_add,    name='event_add'),
    path('events/<slug:slug>/edit/', views.event_edit,   name='event_edit'),
    path('events/<slug:slug>/delete/', views.event_delete, name='event_delete'),

    path('resync/', views.resync_calendar, name='resync'),

    # Sky tracking (Phase 2f).
    # /chronos/sky/ = dome (default visual view).
    # /chronos/sky/table/ = structured drill-down (must come before the
    # generic <slug> route or Django would route 'table' as a slug).
    path('sky/',                   views.sky,          name='sky'),
    path('sky/table/',             views.sky_table,    name='sky_table'),
    path('sky/digest/',            views.sky_digest,   name='sky_digest'),
    path('sky/transits/',          views.sky_transits, name='sky_transits'),
    path('sky/feed.ics',           views.sky_feed_ics, name='sky_feed_ics'),
    path('sky/subscribe/',         views.sky_subscribe, name='sky_subscribe'),
    path('sky.json',               views.sky_json,     name='sky_json'),
    path('sky/<slug:slug>/',       views.sky_object,   name='sky_object'),

    # Space weather (Phase 6) — solar + geomagnetic activity dashboard.
    path('space-weather/',         views.space_weather, name='space_weather'),

    # Local environment (Phase 7) — air quality + UV + pollen.
    path('local/',                 views.local_environment, name='local'),

    # Weather (Phase 8) — temp / clouds / precipitation forecast.
    path('weather/',               views.weather,         name='weather'),

    # Tasks + briefing (Phase 2e)
    path('briefing/',              views.briefing,     name='briefing'),
    path('tasks/',                 views.task_list,    name='task_list'),
    path('tasks/add/',             views.task_add,     name='task_add'),
    path('tasks/<int:pk>/edit/',   views.task_edit,    name='task_edit'),
    path('tasks/<int:pk>/done/',   views.task_done,    name='task_done'),
    path('tasks/<int:pk>/reopen/', views.task_reopen,  name='task_reopen'),
    path('tasks/<int:pk>/delete/', views.task_delete,  name='task_delete'),
]
