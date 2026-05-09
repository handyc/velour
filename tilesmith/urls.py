from django.urls import path

from . import views


app_name = 'tilesmith'

urlpatterns = [
    path('',                  views.index,    name='index'),
    path('new/',              views.create,   name='create'),
    path('<slug:slug>/',      views.edit,     name='edit'),
    path('<slug:slug>/save/', views.save,     name='save'),
    path('<slug:slug>/delete/', views.delete, name='delete'),
]
