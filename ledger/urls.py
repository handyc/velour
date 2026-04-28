from django.urls import path

from . import views

app_name = 'ledger'

urlpatterns = [
    path('',                                 views.list_view,    name='list'),
    path('new/',                             views.new,          name='new'),
    path('<slug:slug>/',                     views.detail,       name='detail'),
    path('<slug:slug>/delete/',              views.delete,       name='delete'),
    path('<slug:slug>/sheet/<int:sheet_pk>/cell/', views.api_set_cell, name='api_set_cell'),
]
