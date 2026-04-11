from django.urls import path

from . import views


app_name = 'hosts'

urlpatterns = [
    path('',                       views.host_list,         name='list'),
    path('add/',                   views.host_add,          name='add'),
    path('refresh-all/',           views.host_refresh_all,  name='refresh_all'),
    path('<int:pk>/',              views.host_detail,       name='detail'),
    path('<int:pk>/edit/',         views.host_edit,         name='edit'),
    path('<int:pk>/delete/',       views.host_delete,       name='delete'),
    path('<int:pk>/refresh/',      views.host_refresh,      name='refresh'),
]
