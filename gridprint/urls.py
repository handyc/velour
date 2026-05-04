from django.urls import path

from . import views

app_name = 'gridprint'

urlpatterns = [
    path('',         views.index,      name='index'),
    path('grid.svg', views.grid_svg,   name='grid_svg'),
    path('print/',   views.print_view, name='print'),
]
