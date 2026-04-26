SECRET_KEY = 'test-only'
DEBUG = True
ROOT_URLCONF = 'lime_django.urls'
ALLOWED_HOSTS = ['*']
DATABASES = {'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': '/tmp/lime_django/db.sqlite3'}}
INSTALLED_APPS = ['django.contrib.contenttypes', 'django.contrib.auth', 'lime_app']
USE_TZ = True
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
