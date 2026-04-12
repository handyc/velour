from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path

from dashboard.views import landing

urlpatterns = [
    path('', landing, name='landing'),
    path('dashboard/', include('dashboard.urls')),
    path('terminal/', include('terminal.urls')),
    path('apps/', include('app_factory.urls')),
    path('sysinfo/', include('sysinfo.urls')),
    path('agricola/', include('agricola.urls')),
    path('graphs/', include('graphs.urls')),
    path('services/', include('services.urls')),
    path('logs/', include('logs.urls')),
    path('identity/', include('identity.urls')),
    path('security/', include('security.urls')),
    path('news/', include('landingpage.urls')),
    path('windows/', include('winctl.urls')),
    path('maintenance/', include('maintenance.urls')),
    path('hosts/', include('hosts.urls')),
    path('mail/', include('mail.urls')),
    path('nodes/', include('nodes.urls')),
    path('api/nodes/', include('nodes.api_urls')),
    path('experiments/', include('experiments.urls')),
    path('chronos/', include('chronos.urls')),
    path('databases/', include('databases.urls')),
    path('codex/', include('codex.urls')),
    path('attic/', include('attic.urls')),
    path('cartography/', include('cartography.urls')),
    path('hpc/', include('hpc.urls')),
    path('tiles/', include('tiles.urls')),
    path('condenser/', include('condenser.urls')),

    path('admin/', admin.site.urls),
    path('accounts/login/', auth_views.LoginView.as_view(), name='login'),
    path('accounts/logout/', auth_views.LogoutView.as_view(), name='logout'),
    # Password reset flow — uses Django's built-in views. The actual email
    # goes out via EMAIL_BACKEND = 'mail.backends.DynamicMailboxBackend',
    # so whatever MailAccount is marked default sends the reset message.
    path('accounts/password_reset/',
         auth_views.PasswordResetView.as_view(),
         name='password_reset'),
    path('accounts/password_reset/done/',
         auth_views.PasswordResetDoneView.as_view(),
         name='password_reset_done'),
    path('accounts/reset/<uidb64>/<token>/',
         auth_views.PasswordResetConfirmView.as_view(),
         name='password_reset_confirm'),
    path('accounts/reset/done/',
         auth_views.PasswordResetCompleteView.as_view(),
         name='password_reset_complete'),
]

# Serve uploaded media files (codex figures, etc.) in dev. In production
# nginx is responsible for /media/ — see app_factory deploy templates.
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
