from django.urls import path

from . import views


app_name = 'det'

urlpatterns = [
    path('', views.index, name='index'),
    path('search/new/', views.create_search, name='create_search'),
    path('search/<int:pk>/', views.search_detail, name='search_detail'),
    path('candidate/<int:pk>/', views.candidate_detail,
         name='candidate_detail'),
    path('candidate/<int:pk>/promote/', views.promote_candidate,
         name='promote_candidate'),
    path('candidate/<int:pk>/promote-to-evolution/',
         views.promote_candidate_to_evolution,
         name='promote_to_evolution'),
    path('candidate/<int:pk>/json/', views.candidate_json,
         name='candidate_json'),
    path('import-from-evolution/', views.import_agent_from_evolution,
         name='import_from_evolution'),
    path('import-search-job/<slug:job_slug>/', views.import_search_job,
         name='import_search_job'),

    path('tournaments/', views.tournament_list, name='tournament_list'),
    path('tournaments/new/', views.tournament_create,
         name='tournament_create'),
    path('tournaments/<int:pk>/', views.tournament_detail,
         name='tournament_detail'),
    path('tournaments/<int:pk>/add/', views.tournament_add,
         name='tournament_add'),
    path('tournaments/<int:pk>/run/', views.tournament_run,
         name='tournament_run'),
    path('tournaments/<int:pk>/entries/<int:entry_pk>/promote/',
         views.tournament_promote, name='tournament_promote'),
]
