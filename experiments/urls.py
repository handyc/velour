from django.urls import path

from . import views


app_name = 'experiments'

urlpatterns = [
    path('',                   views.experiment_list,   name='list'),
    path('add/',               views.experiment_add,    name='add'),
    path('<slug:slug>/',       views.experiment_detail, name='detail'),
    path('<slug:slug>/edit/',  views.experiment_edit,   name='edit'),
    path('<slug:slug>/delete/',views.experiment_delete, name='delete'),
]
