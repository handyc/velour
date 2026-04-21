from django.urls import path

from . import views

app_name = 'lingua'

urlpatterns = [
    path('',                         views.home,            name='home'),
    path('translate/',               views.translate,       name='translate'),
    path('bootstrap/',               views.bootstrap,       name='bootstrap'),
    path('flashcards/',              views.flashcards,      name='flashcards'),
    path('flashcards/study/<str:lang>/',
         views.study, name='study'),
    path('flashcards/study/<str:lang>/<str:theme>/<str:level>/',
         views.study, name='study_theme'),
    path('flashcards/grade/',        views.grade,           name='grade'),
    path('speak/',                   views.speak,           name='speak'),
    path('concepts/',                views.concepts,        name='concepts'),
]
