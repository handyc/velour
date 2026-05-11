from django.urls import path

from . import views

app_name = 'tableau'

urlpatterns = [
    path('',                       views.index,         name='index'),
    path('new/',                   views.world_new,     name='world_new'),
    path('w/<int:pk>/',             views.world_detail,  name='world_detail'),
    path('w/<int:pk>/state.json',   views.world_state,   name='world_state'),
    path('w/<int:pk>/blocks/',      views.blocks_post,   name='blocks_post'),
    path('w/<int:pk>/sentences/',   views.sentences_post,name='sentences_post'),
    path('w/<int:pk>/evaluate/',    views.evaluate_all,  name='evaluate_all'),
    path('w/<int:pk>/delete/',      views.world_delete,  name='world_delete'),
]
