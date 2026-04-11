from django.urls import path

from . import views

app_name = 'terminal'

urlpatterns = [
    path('', views.terminal_view, name='terminal'),
    path('execute/', views.terminal_execute, name='execute'),
]
