from django.urls import path

from . import views

app_name = 'officelab'

urlpatterns = [
    path('',                  views.index,         name='index'),
    path('budget/',           views.budget,        name='budget'),
    path('treemap/',          views.treemap,       name='treemap'),
    path('diff/',             views.diff_view,     name='diff'),
    path('planner/',          views.planner,       name='planner'),
    path('rebuild/',          views.rebuild,       name='rebuild'),
    # `str` (default) converter allows dots in officerpgc version
    # tags like "v1.7"; slug would 404 on those.
    path('v/<str:version>/', views.version_view,  name='version'),
]
