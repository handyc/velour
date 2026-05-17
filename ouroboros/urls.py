from django.urls import path

from . import views


app_name = 'ouroboros'

urlpatterns = [
    path('',                    views.index,         name='index'),
    path('search/',             views.search,        name='search'),
    path('search/stop/',        views.search_stop,   name='search_stop'),
    path('search/tail/',        views.search_tail,   name='search_tail'),
    path('<int:pk>/',           views.detail,        name='detail'),
    path('<int:pk>/annotate/',  views.annotate,      name='annotate'),
    path('<int:pk>/seed.bin',   views.seed_bytes,    name='seed_bytes'),
    path('<int:pk>/ruleset.png', views.ruleset_png,  name='ruleset_png'),
    path('<int:pk>/L<int:level>.png',
                                views.chain_level_png,
                                name='chain_level_png'),
    path('<int:pk>/walk.json',  views.walk_json,     name='walk_json'),
]
