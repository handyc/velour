from django.urls import path

from . import views

app_name = 'aggregator'

urlpatterns = [
    path('',                  views.index,         name='index'),
    path('feed/add/',         views.feed_add,      name='feed_add'),
    path('feed/<int:pk>/toggle/', views.feed_toggle, name='feed_toggle'),
    path('feed/<int:pk>/delete/', views.feed_delete, name='feed_delete'),
    path('fetch/',            views.fetch_now,     name='fetch_now'),
    path('compose/',          views.compose,       name='compose'),
    path('issues/',           views.issues,        name='issues'),
    path('issue/<slug:slug>/',        views.issue,        name='issue'),
    path('issue/<slug:slug>/delete/', views.issue_delete, name='issue_delete'),
    path('articles/',         views.articles,      name='articles'),
    path('article/<int:pk>/', views.article,       name='article'),
]
