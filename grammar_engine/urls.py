from django.urls import path

from . import views

app_name = 'grammar_engine'

urlpatterns = [
    path('', views.language_list, name='list'),
    path('new/', views.language_new, name='new'),
    path('<slug:slug>/', views.language_detail, name='detail'),
    path('<slug:slug>/regenerate/', views.language_regenerate, name='regenerate'),
    path('<slug:slug>/delete/', views.language_delete, name='delete'),
    path('<slug:slug>/spec.json', views.language_spec, name='spec'),
]
