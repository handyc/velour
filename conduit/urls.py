from django.urls import path

from . import views


app_name = 'conduit'

urlpatterns = [
    path('',                               views.index,           name='index'),
    path('targets/',                       views.target_list,     name='target_list'),
    path('targets/new/',                   views.target_create,   name='target_create'),
    path('jobs/',                          views.job_list,        name='job_list'),
    path('jobs/new/',                      views.job_create,      name='job_create'),
    path('jobs/<slug:slug>/',              views.job_detail,      name='job_detail'),
    path('jobs/<slug:slug>/cancel/',       views.job_cancel,      name='job_cancel'),
    path('handoffs/',                      views.handoff_list,    name='handoff_list'),
    path('handoffs/<int:pk>/',             views.handoff_detail,  name='handoff_detail'),
    path('handoffs/<int:pk>/submit/',      views.handoff_submit,  name='handoff_submit'),
    path('handoffs/<int:pk>/complete/',    views.handoff_complete, name='handoff_complete'),
    path('notebooks/',                     views.notebook_list,     name='notebook_list'),
    path('notebooks/<slug:slug>.ipynb',    views.notebook_download, name='notebook_download'),
]
