from django.urls import path

from . import views


app_name = 'hpc'

urlpatterns = [
    path('',                    views.cluster_list,   name='list'),
    path('add/',                views.cluster_add,    name='add'),
    path('<slug:slug>/',        views.cluster_detail, name='detail'),
    path('<slug:slug>/edit/',   views.cluster_edit,   name='edit'),
    path('<slug:slug>/delete/', views.cluster_delete, name='delete'),
]
