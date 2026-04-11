from django.urls import path

from . import views

app_name = 'app_factory'

urlpatterns = [
    path('', views.app_list, name='list'),
    path('create/', views.app_create, name='create'),
    path('<int:pk>/', views.app_detail, name='detail'),
    path('<int:pk>/approve/', views.app_approve, name='approve'),
    path('<int:pk>/rename/', views.app_rename, name='rename'),
    path('<int:pk>/delete/', views.app_delete, name='delete'),
    path('<int:pk>/deploy/', views.app_deploy, name='deploy'),
    path('<int:pk>/stop/', views.app_stop, name='stop'),
    path('<int:pk>/cloud/', views.app_cloud_deploy, name='cloud_deploy'),
    path('<int:pk>/cloud/run/', views.app_cloud_deploy_run, name='cloud_deploy_run'),
]
