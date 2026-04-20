from django.urls import path

from . import views


app_name = 'naiad'

urlpatterns = [
    path('',                       views.index,        name='index'),
    path('catalog/',               views.catalog,      name='catalog'),
    path('new/',                   views.create_system, name='create_system'),
    path('<slug:slug>/',           views.system_detail, name='system_detail'),
    path('<slug:slug>/stage/add/', views.add_stage,    name='add_stage'),
    path('<slug:slug>/stage/<int:stage_id>/delete/',
         views.remove_stage, name='remove_stage'),
    path('<slug:slug>/test/',      views.run_test,     name='run_test'),
    path('test/<int:pk>/',         views.test_detail,  name='test_detail'),
]
