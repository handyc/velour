from django.urls import path

from . import views

app_name = 'officeforge'

urlpatterns = [
    path('',       views.index, name='index'),
    path('build/', views.build, name='build'),
]
