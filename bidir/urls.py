from django.urls import path

from . import views


app_name = 'bidir'

urlpatterns = [
    path('',                       views.index,           name='index'),
    path('feature/<slug:slug>/',   views.feature_detail,  name='feature_detail'),
    path('feature/<slug:slug>/set/', views.set_status,    name='set_status'),
    path('matrix/quickset/',       views.quickset_status, name='quickset_status'),
    path('builds/',                views.builds,          name='builds'),
]
