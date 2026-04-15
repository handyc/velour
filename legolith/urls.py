from django.urls import path

from . import views

app_name = 'legolith'

urlpatterns = [
    path('', views.world_list, name='list'),
    path('generate/', views.world_generate, name='generate'),
    path('pdf/math/', views.pdf_math_book, name='pdf_math'),
    path('pdf/gallery/', views.pdf_worlds_gallery, name='pdf_gallery'),
    path('pdf/detailed/', views.pdf_worlds_detailed, name='pdf_detailed'),
    path('library/', views.library_list, name='library_list'),
    path('library/new/', views.library_new, name='library_new'),
    path('library/random/', views.library_random, name='library_random'),
    path('library/<slug:slug>/', views.library_detail, name='library_detail'),
    path('library/<slug:slug>/edit/', views.library_edit, name='library_edit'),
    path('library/<slug:slug>/delete/', views.library_delete, name='library_delete'),
    path('library/<slug:slug>/preview.png', views.library_preview_png, name='library_preview'),
    path('library/<slug:slug>/bricks.json', views.library_bricks_json, name='library_bricks'),
    path('<slug:slug>/', views.world_detail, name='detail'),
    path('<slug:slug>/delete/', views.world_delete, name='delete'),
    path('<slug:slug>/image.png', views.world_png, name='png'),
]
