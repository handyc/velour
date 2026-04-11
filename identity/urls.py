from django.urls import path

from . import views

app_name = 'identity'

urlpatterns = [
    path('', views.identity_home, name='home'),
    path('journal/', views.identity_journal, name='journal'),
    path('update/', views.identity_update, name='update'),
    path('mood-data/', views.mood_data, name='mood_data'),
]
