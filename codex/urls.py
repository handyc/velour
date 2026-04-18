from django.urls import path

from . import views


app_name = 'codex'

urlpatterns = [
    path('',                       views.manual_list,    name='list'),
    path('add/',                   views.manual_add,     name='manual_add'),
    path('import/',                views.manual_import,  name='manual_import'),

    # Volumes — must come before the <slug:slug>/ catch-all below, which
    # would otherwise swallow `volumes/` as a manual slug.
    path('volumes/',                    views.volume_list,           name='volume_list'),
    path('volumes/add/',                views.volume_add,            name='volume_add'),
    path('volumes/<slug:slug>/',        views.volume_detail,         name='volume_detail'),
    path('volumes/<slug:slug>/edit/',   views.volume_edit,           name='volume_edit'),
    path('volumes/<slug:slug>/delete/', views.volume_delete,         name='volume_delete'),
    path('volumes/<slug:slug>/pdf/',    views.volume_pdf,            name='volume_pdf'),
    path('volumes/<slug:slug>/manuals/add/',    views.volume_add_manual,    name='volume_add_manual'),
    path('volumes/<slug:slug>/manuals/<int:entry_pk>/remove/',
         views.volume_remove_manual,  name='volume_remove_manual'),
    path('volumes/<slug:slug>/reorder/', views.volume_reorder,       name='volume_reorder'),

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
    path('<slug:manual_slug>/sections/<slug:section_slug>/figures/add/',
         views.figure_add, name='figure_add'),
    path('<slug:manual_slug>/sections/<slug:section_slug>/figures/<slug:figure_slug>/edit/',
         views.figure_edit, name='figure_edit'),
    path('<slug:manual_slug>/sections/<slug:section_slug>/figures/<slug:figure_slug>/delete/',
         views.figure_delete, name='figure_delete'),
]
