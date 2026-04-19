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
    path('candidate/<int:pk>/json/', views.candidate_json,
         name='candidate_json'),
]
