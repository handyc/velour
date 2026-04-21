from django.urls import path

from . import views

app_name = 'camlfornia'

urlpatterns = [
    path('',               views.index,    name='index'),
    path('<slug:slug>/',   views.lesson,   name='lesson'),
    path('<slug:slug>/run/', views.run_code, name='run'),
]
