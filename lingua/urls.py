from django.urls import path

from . import views

app_name = 'lingua'

urlpatterns = [
    path('',                         views.home,            name='home'),
    path('translate/',               views.translate,       name='translate'),
    path('bootstrap/',               views.bootstrap,       name='bootstrap'),
    path('flashcards/',              views.flashcards,      name='flashcards'),
    path('flashcards/study/<str:lang>/', views.study,       name='study'),
    path('flashcards/grade/',        views.grade,           name='grade'),
]
