from django.urls import path

from . import views

app_name = 'quill'

urlpatterns = [
    path('',                                         views.list_view,    name='list'),
    path('new/',                                     views.new,          name='new'),
    path('<slug:slug>/',                             views.detail,       name='detail'),
    path('<slug:slug>/delete/',                      views.delete,       name='delete'),
    path('<slug:slug>/languages/',                   views.document_languages, name='document_languages'),
    path('<slug:slug>/section/add/',                 views.section_add,  name='section_add'),
    path('<slug:slug>/section/<int:pk>/edit/',       views.section_edit, name='section_edit'),
    path('<slug:slug>/section/<int:pk>/delete/',     views.section_delete, name='section_delete'),
    path('<slug:slug>/section/<int:pk>/save/',       views.api_section_save, name='api_section_save'),
    path('<slug:slug>/style/add/',                   views.style_add,    name='style_add'),
]
