from django.urls import path
from lime_app.views import index, typeurl_view
urlpatterns = [
    path('', index),
    path('typeurl/', typeurl_view),
]
