from django.urls import path

from . import views

app_name = 'agora'

urlpatterns = [
    path('',                                    views.index,              name='index'),
    path('universities/',                       views.university_list,    name='university_list'),
    path('universities/<slug:slug>/',           views.university_detail,  name='university_detail'),
    path('departments/',                        views.department_list,    name='department_list'),
    path('departments/<slug:slug>/',            views.department_detail,  name='department_detail'),
    path('courses/',                            views.course_list,        name='course_list'),
    path('courses/<slug:slug>/',                views.course_detail,      name='course_detail'),
    path('sections/<int:pk>/',                  views.section_detail,     name='section_detail'),
    path('sections/<int:pk>/enroll/',           views.section_enroll,     name='section_enroll'),
    path('sections/<int:pk>/withdraw/',         views.section_withdraw,   name='section_withdraw'),
    path('sections/<int:pk>/resources/add/',    views.resource_add,       name='resource_add'),
    path('sections/<int:pk>/resources/<int:rpk>/delete/',
                                                views.resource_delete,    name='resource_delete'),
    path('sections/<int:pk>/grades/',           views.grades_edit,        name='grades_edit'),
    path('terms/',                              views.term_list,          name='term_list'),
]
