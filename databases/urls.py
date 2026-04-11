from django.urls import path

from . import views


app_name = 'databases'

urlpatterns = [
    path('',                    views.database_list,   name='list'),
    path('add/',                views.database_add,    name='add'),
    path('<slug:slug>/',        views.database_detail, name='detail'),
    path('<slug:slug>/edit/',   views.database_edit,   name='edit'),
    path('<slug:slug>/delete/', views.database_delete, name='delete'),
    path('<slug:slug>/test/',   views.database_test,   name='test'),
]
