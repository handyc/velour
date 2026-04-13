from django.urls import path

from . import views

app_name = 'oracle'

urlpatterns = [
    path('', views.home, name='home'),
    path('labels/', views.labels, name='labels'),
    path('lobe/<str:name>/', views.lobe_detail, name='lobe_detail'),
    path('label/<int:pk>/verdict/', views.label_verdict, name='label_verdict'),
]
