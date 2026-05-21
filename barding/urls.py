from django.urls import path

from . import views


app_name = 'barding'

urlpatterns = [
    path('',                       views.index,           name='index'),

    # Comparative-study pages.
    path('harnesses/',                  views.harness_list,    name='harness_list'),
    path('harnesses/<slug:slug>/',      views.harness_detail,  name='harness_detail'),
    path('techniques/',                 views.technique_list,  name='technique_list'),
    path('techniques/<slug:slug>/',     views.technique_detail, name='technique_detail'),
    path('compare/',                    views.compare_grid,    name='compare_grid'),
    path('distill/',                    views.distill_plan,    name='distill_plan'),

    # Claude-Code-specific operator tools (original barding scope).
    path('scope/<int:scope_id>/',  views.edit_scope,      name='edit_scope'),
    path('bundle-patches/',        views.bundle_patches,  name='bundle_patches'),
    path('version/',               views.version_status,  name='version_status'),
    path('binary/',                views.binary_index,    name='binary_index'),
    path('binary/hex/',            views.binary_hex,      name='binary_hex'),
]
