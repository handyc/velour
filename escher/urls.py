from django.urls import path

from . import views


app_name = 'escher'

urlpatterns = [
    path('',               views.index,        name='index'),
    path('groups.svg',     views.groups_grid,  name='groups_grid'),
    path('render.svg',     views.render_svg,   name='render_svg'),
    path('g/<slug:slug>/', views.group_detail, name='group_detail'),
    path('uploads/',       views.upload_list,  name='uploads'),
]
