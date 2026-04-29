from django.urls import path

from . import views


app_name = 'mail'

urlpatterns = [
    # --- mail home + compose ------------------------------------------
    path('',         views.mail_home,    name='home'),
    path('compose/', views.mail_compose, name='compose'),

    # --- accounts (from mailboxes) ------------------------------------
    path('accounts/',                    views.mailbox_list,   name='list'),
    path('accounts/add/',                views.mailbox_add,    name='add'),
    path('accounts/relay/',              views.relay_send,     name='relay_send'),
    path('accounts/<int:pk>/',           views.mailbox_detail, name='detail'),
    path('accounts/<int:pk>/edit/',      views.mailbox_edit,   name='edit'),
    path('accounts/<int:pk>/delete/',    views.mailbox_delete, name='delete'),
    path('accounts/<int:pk>/test/',      views.mailbox_test,   name='test'),

    # --- inbound (from mailroom) --------------------------------------
    path('inbound/',                          views.inbox_list,         name='inbound_list'),
    path('inbound/<int:pk>/',                 views.inbox_detail,       name='inbound_detail'),
    path('inbound/<int:pk>/delete/',          views.inbox_delete,       name='inbound_delete'),
    path('inbound/<int:pk>/unread/',          views.inbox_mark_unread,  name='inbound_mark_unread'),
    path('inbound/<int:pk>/handled/',         views.inbox_mark_handled, name='inbound_mark_handled'),
    path('inbound/poll/<int:mailbox_pk>/',    views.poll_mailbox,       name='poll_mailbox'),

    # --- server (from mailserver) -------------------------------------
    path('server/',                  views.server_inbox,  name='server_inbox'),
    path('server/<int:pk>/',         views.server_detail, name='server_detail'),
    path('server/<int:pk>/delete/',  views.server_delete, name='server_delete'),
]
