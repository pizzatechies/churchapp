"""
Settings for Ecclesia Connect, the members app.

It shares the database and code with the admin app but has its own URLs,
templates, login and session cookie, and contains no financial screens.
Run it with:  DJANGO_SETTINGS_MODULE=config.settings_portal
"""

from .settings import *  # noqa: F401,F403

ROOT_URLCONF = "config.urls_portal"
WSGI_APPLICATION = "config.wsgi_portal.application"

APP_NAME = "Ecclesia Connect"
APP_TAGLINE = "Fellowships, groups & sermons"

# Separate cookies so members and staff sessions never mix, even on one domain.
SESSION_COOKIE_NAME = "connect_sessionid"
CSRF_COOKIE_NAME = "connect_csrftoken"

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "portal:home"
LOGOUT_REDIRECT_URL = "login"
