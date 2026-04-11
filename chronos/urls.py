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
]
