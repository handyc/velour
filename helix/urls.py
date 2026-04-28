from django.urls import path

from . import views

app_name = 'helix'

urlpatterns = [
    path('',                    views.list_view,      name='list'),
    path('upload/',             views.upload,         name='upload'),
    path('<int:pk>/',           views.detail,         name='detail'),
    path('<int:pk>/delete/',    views.delete,         name='delete'),
    path('<int:pk>/fasta/',     views.download_fasta, name='download_fasta'),
]
