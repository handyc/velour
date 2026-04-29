from django.urls import path

from . import views

app_name = 'graphs'

urlpatterns = [
    path('', views.graphs_home, name='home'),
    path('sample/', views.sample, name='sample'),
    path('history/json/', views.history, name='history_json'),
    path('data/', views.graph_data, name='data'),
    path('save/', views.graph_save, name='save'),
    path('pdf/', views.graph_pdf, name='pdf'),
    path('history/', views.graph_history, name='history'),
    path('history/<int:pk>/', views.graph_history_detail, name='history_detail'),
    path('history/<int:pk>/data/', views.graph_history_data, name='history_data'),
    path('history/<int:pk>/pdf/', views.graph_pdf, name='history_pdf'),
]
