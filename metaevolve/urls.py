from django.urls import path

from . import views


app_name = 'metaevolve'

urlpatterns = [
    path('',         views.index,   name='index'),
    path('runner/',  views.runner,  name='runner'),
    path('archive/', views.archive, name='archive'),
    path('archive/<int:pk>/', views.archive_detail, name='archive_detail'),
    path('archive/<int:pk>/materialize/', views.materialize_winner, name='materialize'),
]
