from django.urls import path

from . import views


app_name = 'muka'

urlpatterns = [
    path('',                          views.index,               name='index'),
    path('sentences/',                views.sentence_index,      name='sentence_index'),
    path('lang/random/',              views.add_random_language, name='add_random'),
    path('lang/search/',              views.search_glottolog,    name='search_glottolog'),
    path('lang/add/<str:glottocode>/', views.add_by_glottocode,  name='add_by_glottocode'),
    path('lang/<slug:slug>/',         views.language_detail,     name='language_detail'),
    path('new/',                      views.create,              name='create'),
    path('preview/',                  views.preview,             name='preview'),
    path('<slug:slug>/',              views.detail,              name='detail'),
    path('<slug:slug>/edit/',         views.edit,                name='edit'),
    path('<slug:slug>/delete/',       views.delete,              name='delete'),
    path('<slug:slug>/to-deck/',      views.add_sentence_to_deck, name='add_sentence_to_deck'),
    path('lang/<slug:slug>/to-deck/', views.add_language_to_deck, name='add_language_to_deck'),
]
