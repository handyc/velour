"""Machine-facing HTTP API for field nodes.

Separated from nodes/urls.py (the human UI) so auth policies stay clean:
these endpoints use per-node Bearer tokens, never session/CSRF auth.
Mounted at /api/nodes/ in velour/urls.py.
"""

from django.urls import path

from . import views


app_name = 'nodes_api'

urlpatterns = [
    path('discover',                    views.api_discover,       name='discover'),
    path('register',                    views.api_register,       name='register'),
    path('<slug:slug>/report/',         views.api_report,         name='report'),
    path('<slug:slug>/firmware/check',  views.api_firmware_check, name='firmware_check'),
    path('<slug:slug>/firmware.bin',    views.api_firmware_bin,   name='firmware_bin'),
    path('<slug:slug>/model.json',      views.api_model_json,     name='model_json'),
    path('<slug:slug>/identity.json',   views.api_identity_json,  name='identity_json'),
]
