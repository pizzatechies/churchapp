"""
Settings for the LifeSource Church finance app.

Everything that differs between a laptop and a production server is read from
environment variables (see .env.example). With no variables set the app runs
in development mode against a local SQLite database.
"""

import os
import sys
import warnings
from pathlib import Path

import dj_database_url
from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent


def env_bool(name, default=False):
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_list(name, default=""):
    return [item.strip() for item in os.environ.get(name, default).split(",") if item.strip()]


SECRET_KEY = os.environ.get("SECRET_KEY", "")
# Development mode is the default only when no secret key has been configured.
DEBUG = env_bool("DEBUG", default=not SECRET_KEY)
TESTING = len(sys.argv) > 1 and sys.argv[1] == "test"

if not SECRET_KEY:
    if not DEBUG:
        raise ImproperlyConfigured("Set the SECRET_KEY environment variable when DEBUG is off.")
    SECRET_KEY = "django-insecure-development-only-key-do-not-use-in-production"

ALLOWED_HOSTS = env_list("ALLOWED_HOSTS", "localhost,127.0.0.1,[::1]" + (",testserver" if DEBUG else ""))
CSRF_TRUSTED_ORIGINS = env_list("CSRF_TRUSTED_ORIGINS")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    "core",
    "ledger",
    "giving",
    "expenses",
    "payroll",
    "fixedassets",
    "reports",
    "members",
    "portal",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.auth.middleware.LoginRequiredMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "core.middleware.CurrentUserMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "core.context_processors.church",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# PostgreSQL is the supported database. Point DATABASE_URL at your server, e.g.
#   postgres://USER:PASSWORD@HOST:5432/DBNAME
DATABASES = {
    "default": dj_database_url.config(
        default="postgres://church:church@localhost:5432/church_finance",
        conn_max_age=int(os.environ.get("DB_CONN_MAX_AGE", "60")),
        conn_health_checks=True,
        ssl_require=env_bool("DB_SSL_REQUIRE", False),
    )
}
if not DATABASES["default"]["ENGINE"].endswith("postgresql"):
    raise ImproperlyConfigured("DATABASE_URL must point to a PostgreSQL database (postgres://...).")
# Every request runs in one transaction: a failure part-way never leaves half-posted books.
DATABASES["default"]["ATOMIC_REQUESTS"] = True

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 10}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = os.environ.get("TIME_ZONE", "Africa/Nairobi")
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]

# Receipts, bank statements and other attachments. They are served only through
# a login-protected view, never directly by the web server.
MEDIA_ROOT = Path(os.environ.get("MEDIA_ROOT", BASE_DIR / "media"))
MEDIA_URL = "/media/"
MAX_UPLOAD_SIZE = int(os.environ.get("MAX_UPLOAD_MB", "15")) * 1024 * 1024
SERMON_MAX_UPLOAD_SIZE = int(os.environ.get("SERMON_MAX_UPLOAD_MB", "300")) * 1024 * 1024
# Large sermon uploads are streamed to a temporary file rather than held in memory.
FILE_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": (
            "django.contrib.staticfiles.storage.StaticFilesStorage"
            if DEBUG or TESTING
            else "whitenoise.storage.CompressedManifestStaticFilesStorage"
        )
    },
}

if DEBUG or TESTING:
    # Serve static files straight from the source folders; `collectstatic` is only needed in production.
    WHITENOISE_USE_FINDERS = True
    WHITENOISE_AUTOREFRESH = True
    warnings.filterwarnings("ignore", message="No directory at", module="whitenoise.base")

# Uploaded files (receipts, sermons) live on the local disk by default. When the admin app and
# the members app run on separate servers, point both at the same S3-compatible bucket instead
# (AWS S3, Cloudflare R2, DigitalOcean Spaces, Backblaze B2...). Files stay private: links are
# signed and expire after an hour.
if os.environ.get("S3_BUCKET"):
    STORAGES["default"] = {
        "BACKEND": "storages.backends.s3.S3Storage",
        "OPTIONS": {
            "bucket_name": os.environ["S3_BUCKET"],
            "endpoint_url": os.environ.get("S3_ENDPOINT_URL") or None,
            "region_name": os.environ.get("S3_REGION") or None,
            "access_key": os.environ.get("S3_ACCESS_KEY_ID"),
            "secret_key": os.environ.get("S3_SECRET_ACCESS_KEY"),
            "default_acl": None,
            "querystring_auth": True,
            "querystring_expire": 3600,
            "file_overwrite": False,
        },
    }

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Product identity. The members app (config.settings_portal) overrides APP_NAME.
PRODUCT_NAME = "Ecclesia"
APP_NAME = "Ecclesia Admin"
APP_TAGLINE = "Church management & finance"
VENDOR_NAME = "Pizza Technologies"

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "dashboard"
LOGOUT_REDIRECT_URL = "login"

# Large grids (budgets, reconciliations, payroll) post many fields at once.
DATA_UPLOAD_MAX_NUMBER_FIELDS = 20000

CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}

SESSION_COOKIE_AGE = int(os.environ.get("SESSION_HOURS", "12")) * 3600

if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SESSION_COOKIE_SECURE = env_bool("SECURE_COOKIES", True)
    CSRF_COOKIE_SECURE = env_bool("SECURE_COOKIES", True)
    SECURE_SSL_REDIRECT = env_bool("SECURE_SSL_REDIRECT", False)
    SECURE_HSTS_SECONDS = int(os.environ.get("SECURE_HSTS_SECONDS", "0"))
    SECURE_CONTENT_TYPE_NOSNIFF = True
    X_FRAME_OPTIONS = "DENY"

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": os.environ.get("LOG_LEVEL", "INFO")},
    # Permission tests deliberately trigger 403s; keep the test output readable.
    "loggers": {"django.request": {"level": "ERROR" if TESTING else "WARNING"}},
}
