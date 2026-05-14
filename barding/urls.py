from django.urls import path

from . import views


app_name = 'barding'

urlpatterns = [
    path('',                       views.index,           name='index'),
    path('scope/<int:scope_id>/',  views.edit_scope,      name='edit_scope'),
    path('bundle-patches/',        views.bundle_patches,  name='bundle_patches'),
    path('version/',               views.version_status,  name='version_status'),
]
