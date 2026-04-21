from django.urls import path

from . import views


app_name = 'konso'

urlpatterns = [
    path('',                    views.index,   name='index'),
    path('new/',                views.create,  name='create'),
    path('preview/',            views.preview, name='preview'),
    path('<slug:slug>/',        views.detail,  name='detail'),
    path('<slug:slug>/edit/',   views.edit,    name='edit'),
    path('<slug:slug>/delete/', views.delete,  name='delete'),
]
