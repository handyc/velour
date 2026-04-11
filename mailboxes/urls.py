from django.urls import path

from . import views


app_name = 'mailboxes'

urlpatterns = [
    path('',                    views.mailbox_list,   name='list'),
    path('add/',                views.mailbox_add,    name='add'),
    path('relay/',              views.relay_send,     name='relay_send'),
    path('<int:pk>/',           views.mailbox_detail, name='detail'),
    path('<int:pk>/edit/',      views.mailbox_edit,   name='edit'),
    path('<int:pk>/delete/',    views.mailbox_delete, name='delete'),
    path('<int:pk>/test/',      views.mailbox_test,   name='test'),
]
