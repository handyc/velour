"""Public URL routes for the Displacement app.

Mounted at /displace/ in velour/urls.py. Slugs are used in URLs,
not zotonic ids — but the legacy zotonic /id/<n> path is also
accepted so old links keep working.
"""

from django.urls import path

from . import views

app_name = 'displacer'

urlpatterns = [
    path('', views.home, name='home'),
    path('themas/', views.theme_list, name='theme_list'),
    path('themas/<slug:slug>/', views.theme_detail, name='theme_detail'),
    path('verhalen/', views.article_list, name='article_list'),
    path('verhaal/<slug:slug>/', views.article_detail, name='article_detail'),
    path('verify/', views.verify, name='verify'),
    path('id/<int:zotonic_id>/', views.legacy_zotonic, name='legacy_zotonic'),
    # /displace/<slug>/ catches static editor pages (About, Privacy, etc.)
    # — kept last so the more specific routes above win first.
    path('<slug:slug>/', views.page_detail, name='page_detail'),
]
