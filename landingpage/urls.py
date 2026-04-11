from django.urls import path

from . import views

app_name = 'landingpage'

urlpatterns = [
    path('', views.landing, name='home'),
    path('article/<int:pk>/', views.article_detail, name='article'),
    path('section/<slug:slug>/', views.section_view, name='section'),
]
