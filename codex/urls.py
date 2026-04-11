from django.urls import path

from . import views


app_name = 'codex'

urlpatterns = [
    path('',                       views.manual_list,    name='list'),
    path('add/',                   views.manual_add,     name='manual_add'),
    path('<slug:slug>/',           views.manual_detail,  name='manual_detail'),
    path('<slug:slug>/edit/',      views.manual_edit,    name='manual_edit'),
    path('<slug:slug>/delete/',    views.manual_delete,  name='manual_delete'),
    path('<slug:slug>/pdf/',       views.manual_pdf,     name='manual_pdf'),
    path('<slug:manual_slug>/sections/add/',
         views.section_add, name='section_add'),
    path('<slug:manual_slug>/sections/<slug:section_slug>/edit/',
         views.section_edit, name='section_edit'),
    path('<slug:manual_slug>/sections/<slug:section_slug>/delete/',
         views.section_delete, name='section_delete'),
]
