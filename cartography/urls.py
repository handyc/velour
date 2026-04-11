from django.urls import path

from . import views


app_name = 'cartography'

urlpatterns = [
    path('',           views.cartography_home,  name='home'),
    path('mars/',      views.cartography_mars,  name='mars'),
    path('moon/',      views.cartography_moon,  name='moon'),
    path('sky/',       views.cartography_sky,   name='sky'),
    path('solar/',     views.cartography_solar, name='solar'),

    path('places/',                  views.place_list,   name='place_list'),
    path('places/add/',              views.place_add,    name='place_add'),
    path('places/<slug:slug>/edit/', views.place_edit,   name='place_edit'),
    path('places/<slug:slug>/delete/', views.place_delete, name='place_delete'),
    path('places.json',              views.places_json,  name='places_json'),
]
