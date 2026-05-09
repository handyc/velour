from django.urls import path

from . import views


app_name = 'h4kslnk'

urlpatterns = [
    path('',                  views.dashboard,    name='dashboard'),
    path('policy/<slug:slug>/', views.policy,    name='policy'),
    path('contact/<slug:nick>/', views.contact,  name='contact'),
    path('session/<int:pk>/', views.session,    name='session'),
    path('push/',             views.pushes,      name='pushes'),
]
