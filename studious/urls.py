from django.urls import path

from . import views

app_name = 'studious'

urlpatterns = [
    path('', views.index, name='index'),

    path('scholars/',                 views.scholar_list,   name='scholar_list'),
    path('scholar/add/',              views.scholar_add,    name='scholar_add'),
    path('scholar/<slug:slug>/',      views.scholar_detail, name='scholar_detail'),
    path('scholar/<slug:slug>/edit/', views.scholar_edit,   name='scholar_edit'),
    path('scholar/<slug:slug>/delete/', views.scholar_delete, name='scholar_delete'),

    path('work/add/',                 views.work_add,           name='work_add'),
    path('work/<slug:slug>/',         views.work_detail,        name='work_detail'),
    path('work/<slug:slug>/edit/',    views.work_edit,          name='work_edit'),
    path('work/<slug:slug>/delete/',  views.work_delete,        name='work_delete'),
    path('work/<slug:slug>/analyze/', views.work_analyze,       name='work_analyze'),
    path('work/<slug:slug>/extract-claims/',
         views.work_extract_claims, name='work_extract_claims'),

    path('claims/',                   views.claim_list,    name='claim_list'),
    path('claim/add/<slug:slug>/',    views.claim_add,     name='claim_add'),
    path('claim/<int:pk>/edit/',      views.claim_edit,    name='claim_edit'),
    path('claim/<int:pk>/delete/',    views.claim_delete,  name='claim_delete'),

    path('arguments/',                views.argument_list,   name='argument_list'),
    path('argument/new/',             views.argument_new,    name='argument_new'),
    path('argument/<slug:slug>/',     views.argument_detail, name='argument_detail'),
    path('argument/<slug:slug>/edit/', views.argument_edit,  name='argument_edit'),
    path('argument/<slug:slug>/delete/', views.argument_delete, name='argument_delete'),

    path('domain/add/',               views.domain_add,    name='domain_add'),
    path('domain/<slug:slug>/delete/', views.domain_delete, name='domain_delete'),
]
