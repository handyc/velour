from django.urls import path
from . import views

app_name = 'optikon'

urlpatterns = [
    path('',                  views.index,        name='index'),
    path('<slug:slug>/',      views.detail,       name='detail'),
    path('<slug:slug>/svg',   views.svg,          name='svg'),
    path('<slug:slug>/print', views.print_view,   name='print'),
]
