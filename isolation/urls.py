from django.urls import path

from . import views


app_name = 'isolation'

urlpatterns = [
    path('', views.index, name='index'),
    path('new/', views.create, name='create'),
    path('<slug:slug>/', views.detail, name='detail'),
    path('<slug:slug>/edit/', views.edit, name='edit'),
    path('<slug:slug>/delete/', views.delete, name='delete'),
    path('<slug:slug>/stage/new/', views.stage_create, name='stage_create'),
    path('<slug:slug>/stage/<int:pk>/edit/', views.stage_edit, name='stage_edit'),
    path('<slug:slug>/stage/<int:pk>/delete/', views.stage_delete, name='stage_delete'),
    path('<slug:slug>/target/<int:pk>/edit/', views.target_edit, name='target_edit'),
]
