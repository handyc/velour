from django.urls import path

from . import views


app_name = 'bagicha'

urlpatterns = [
    path('',                       views.index,        name='index'),
    path('bibliography/',          views.bibliography, name='bibliography'),
    path('resources/',             views.resources,    name='resources'),
    path('word/<str:key>/',        views.word_detail,  name='word'),
]
