from django.urls import path

from . import views


app_name = 'mailserver'

urlpatterns = [
    path('',              views.inbox,          name='inbox'),
    path('<int:pk>/',     views.message_detail, name='detail'),
    path('<int:pk>/delete/', views.message_delete, name='delete'),
]
