from django.urls import path

from . import views


app_name = 'vampyrik'

urlpatterns = [
    path('',                          views.index,            name='index'),
    path('tradition/<slug:slug>/',    views.tradition_detail, name='tradition'),
    path('creature/<slug:slug>/',     views.creature_detail,  name='creature'),
    path('trait/<slug:slug>/',        views.trait_detail,     name='trait'),
    path('origin/<slug:slug>/',       views.origin_detail,    name='origin'),
    path('weakness/<slug:slug>/',     views.weakness_detail,  name='weakness'),
    path('taxonomy/',                 views.taxonomy,         name='taxonomy'),
]
