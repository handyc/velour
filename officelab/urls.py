from django.urls import path

from . import views

app_name = 'officelab'

urlpatterns = [
    path('',                  views.index,         name='index'),
    path('budget/',           views.budget,        name='budget'),
    path('diff/',             views.diff_view,     name='diff'),
    path('planner/',          views.planner,       name='planner'),
    path('rebuild/',          views.rebuild,       name='rebuild'),
    path('v/<slug:version>/', views.version_view,  name='version'),
]
