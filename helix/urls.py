from django.urls import path

from . import views

app_name = 'helix'

urlpatterns = [
    path('',                    views.list_view,      name='list'),
    path('upload/',             views.upload,         name='upload'),
    path('<int:pk>/',           views.detail,         name='detail'),
    path('<int:pk>/delete/',    views.delete,         name='delete'),
    path('<int:pk>/fasta/',     views.download_fasta, name='download_fasta'),
    path('<int:pk>/sequence/',  views.sequence_range, name='sequence_range'),
    path('<int:pk>/gc-profile/',views.gc_profile,     name='gc_profile'),
    path('<int:pk>/evolve/',    views.to_evolution,   name='to_evolution'),
    path('feature/<int:feature_pk>/qualifiers/',
                                views.feature_qualifiers, name='feature_qualifiers'),
]
