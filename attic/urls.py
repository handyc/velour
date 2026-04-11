from django.urls import path

from . import views


app_name = 'attic'

urlpatterns = [
    path('',                  views.attic_list,    name='list'),
    path('upload/',           views.attic_upload,  name='upload'),
    path('<slug:slug>/',      views.attic_detail,  name='detail'),
    path('<slug:slug>/edit/', views.attic_edit,    name='edit'),
    path('<slug:slug>/delete/', views.attic_delete, name='delete'),
]
