from django.urls import path

from . import views


app_name = 'mailroom'

urlpatterns = [
    path('',                       views.inbox_list,         name='list'),
    path('<int:pk>/',              views.inbox_detail,       name='detail'),
    path('<int:pk>/delete/',       views.inbox_delete,       name='delete'),
    path('<int:pk>/unread/',       views.inbox_mark_unread,  name='mark_unread'),
    path('<int:pk>/handled/',      views.inbox_mark_handled, name='mark_handled'),
    path('poll/<int:mailbox_pk>/', views.poll_mailbox,       name='poll_mailbox'),
]
