from django.urls import path

from . import views

app_name = 'logs'

urlpatterns = [
    path('', views.logs_home, name='home'),
    path('view/', views.logs_view, name='view'),
    path('analyze/', views.logs_analyze, name='analyze'),
    path('viz/', views.logs_viz, name='viz'),
    path('pdf/', views.logs_pdf, name='pdf'),
    path('viz/pdf/', views.logs_viz_pdf, name='viz_pdf'),
]
