from django.urls import path

from . import views

app_name = 'agents'

urlpatterns = [
    path('',                  views.index,        name='index'),
    path('town/<slug:slug>/', views.town_detail,  name='town_detail'),
    path('<slug:slug>/',      views.agent_detail, name='detail'),
]
