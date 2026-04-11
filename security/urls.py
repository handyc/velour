from django.urls import path

from . import views

app_name = 'security'

urlpatterns = [
    path('', views.security_home, name='home'),
    path('audit/', views.security_audit, name='audit'),
    path('audit/stream/', views.security_audit_stream, name='audit_stream'),
]
