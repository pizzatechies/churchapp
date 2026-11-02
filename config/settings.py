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
# A public demo server: shows demo logins and blocks password/login changes (see core/demo.py).
DEMO_MODE = env_bool("ECCLESIA_DEMO_MODE")
DEMO_PASSWORD = os.environ.get("ECCLESIA_DEMO_PASSWORD", "ChurchDemo-2026")

if not SECRET_KEY:
    if not DEBUG:
        raise ImproperlyConfigured("Set the SECRET_KEY environment variable when DEBUG is off.")
    SECRET_KEY = "django-insecure-development-only-key-do-not-use-in-production"

ALLOWED_HOSTS = env_list("ALLOWED_HOSTS", "localhost,127.0.0.1,[::1]" + (",testserver" if DEBUG else ""))
CSRF_TRUSTED_ORIGINS = env_list("CSRF_TRUSTED_ORIGINS")

# Each church has its own PostgreSQL schema (django-tenants). SHARED_APPS live in the
# "public" schema used by the platform console; TENANT_APPS are created in every church.
SHARED_APPS = [
    "django_tenants",
    "tenants",
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
]
TENANT_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "django.contrib.sessions",
    "django.contrib.admin",
    "core",
    "ledger",
    "giving",
    "expenses",
    "payroll",
    "fixedassets",
    "reports",
    "members",
    "portal",
    "bankfeeds",
]
INSTALLED_APPS = SHARED_APPS + [app for app in TENANT_APPS if app not in SHARED_APPS]

TENANT_MODEL = "tenants.Church"
TENANT_DOMAIN_MODEL = "tenants.Domain"
DATABASE_ROUTERS = ["django_tenants.routers.TenantSyncRouter"]
# A church's addresses: <app address>/church/<slug>/ (or its own domain on the Kingdom plan).
CHURCH_URL_PREFIX = "church"
PUBLIC_SCHEMA_URLCONF = "config.urls_platform"
# Where each app is reached, for the links the platform console shows. Optional.
ADMIN_APP_URL = os.environ.get("ADMIN_APP_URL", "").rstrip("/")
MEMBERS_APP_URL = os.environ.get("MEMBERS_APP_URL", "").rstrip("/")

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    # Picks the church from the address and switches to its schema. Must come before anything that reads the database.
    "tenants.middleware.ChurchMiddleware",
    "tenants.middleware.ChurchSessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.auth.middleware.LoginRequiredMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "core.middleware.CurrentUserMiddleware",
    "tenants.middleware.PasswordChangeRequiredMiddleware",
    "core.demo.DemoModeMiddleware",
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
DATABASES["default"]["ENGINE"] = "django_tenants.postgresql_backend"
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

STATIC_URL = "/static/"  # absolute: the same files serve every church's addresses
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]

# Receipts, bank statements and other attachments. They are served only through
# a login-protected view, never directly by the web server.
MEDIA_ROOT = Path(os.environ.get("MEDIA_ROOT", BASE_DIR / "media"))
MEDIA_URL = "/media/"
MAX_UPLOAD_SIZE = int(os.environ.get("MAX_UPLOAD_MB", "15")) * 1024 * 1024
SERMON_MAX_UPLOAD_SIZE = int(os.environ.get("SERMON_MAX_UPLOAD_MB", "300")) * 1024 * 1024

# Bank feeds: M-Pesa Paybill/Till payments arrive live from Safaricom's Daraja API.
# The keys are only needed to register the payment address from inside Ecclesia.
MPESA_CONSUMER_KEY = os.environ.get("MPESA_CONSUMER_KEY", "").strip()
MPESA_CONSUMER_SECRET = os.environ.get("MPESA_CONSUMER_SECRET", "").strip()
MPESA_ENVIRONMENT = os.environ.get("MPESA_ENVIRONMENT", "production").strip().lower()
# Optional: only accept payment notifications from these IP addresses (Safaricom's published list).
MPESA_ALLOWED_IPS = env_list("MPESA_ALLOWED_IPS")
# Render's free web services sleep after 15 minutes; Safaricom's payment notices can't wake them in time.
# Set ALWAYS_ON=1 once the admin app runs on an always-on plan.
ON_FREE_HOSTING = env_bool("RENDER") and not env_bool("ALWAYS_ON")
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
# "none" or "-" count as not set, for hosts that insist on a value when asking for it.
S3_BUCKET = os.environ.get("S3_BUCKET", "").strip()
if S3_BUCKET.lower() in {"none", "-"}:
    S3_BUCKET = ""
if S3_BUCKET:
    S3_ENDPOINT_URL = os.environ.get("S3_ENDPOINT_URL", "").strip() or None
    # Some S3-compatible services reject the checksums newer boto3 adds to every upload;
    # send them only when the service requires them.
    os.environ.setdefault("AWS_REQUEST_CHECKSUM_CALCULATION", "when_required")
    os.environ.setdefault("AWS_RESPONSE_CHECKSUM_VALIDATION", "when_required")
    STORAGES["default"] = {
        "BACKEND": "storages.backends.s3.S3Storage",
        "OPTIONS": {
            "bucket_name": S3_BUCKET,
            "endpoint_url": S3_ENDPOINT_URL,
            # Cloudflare R2 expects the region "auto".
            "region_name": os.environ.get("S3_REGION") or ("auto" if S3_ENDPOINT_URL and "r2.cloudflarestorage.com" in S3_ENDPOINT_URL else None),
            "access_key": os.environ.get("S3_ACCESS_KEY_ID"),
            "secret_key": os.environ.get("S3_SECRET_ACCESS_KEY"),
            "default_acl": None,
            # Signed links in the current format (Signature Version 4), which R2, B2 and
            # newer AWS regions require.
            "signature_version": "s3v4",
            "querystring_auth": True,
            "querystring_expire": 3600,
            "file_overwrite": False,
        },
    }

# On hosts whose disk is wiped on every restart (Render sets RENDER=true) and with no bucket
# configured, uploads would silently disappear: administrators see a warning.
MEDIA_IS_TEMPORARY = env_bool("RENDER") and not S3_BUCKET

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Product identity. The members app (config.settings_portal) overrides APP_NAME.
PRODUCT_NAME = "Ecclesia"
APP_NAME = "Ecclesia Admin"
APP_SHORT_NAME = "Ecclesia Admin"
APP_TAGLINE = "Church management & finance"
VENDOR_NAME = "Pizza Technologies"

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "dashboard"
LOGOUT_REDIRECT_URL = "login"

# Large grids (budgets, reconciliations, payroll) post many fields at once.
DATA_UPLOAD_MAX_NUMBER_FIELDS = 20000

# Cache keys carry the church's schema, so one church's cached settings never show in another.
CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "KEY_FUNCTION": "django_tenants.cache.make_key"}}

# Email, for "Forgot password". Any SMTP service works (Gmail with an app password, Brevo, Mailgun, Zoho...).
EMAIL_HOST = os.environ.get("EMAIL_HOST", "").strip()
EMAIL_PORT = int(os.environ.get("EMAIL_PORT", "587"))
EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER", "").strip()
EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD", "").strip()
EMAIL_USE_TLS = env_bool("EMAIL_USE_TLS", EMAIL_PORT == 587)
EMAIL_USE_SSL = env_bool("EMAIL_USE_SSL", EMAIL_PORT == 465)
EMAIL_TIMEOUT = 20
EMAIL_CONFIGURED = bool(EMAIL_HOST)
EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend" if EMAIL_CONFIGURED else "django.core.mail.backends.console.EmailBackend"
DEFAULT_FROM_EMAIL = os.environ.get("DEFAULT_FROM_EMAIL", "").strip() or (f"Ecclesia <{EMAIL_HOST_USER}>" if "@" in EMAIL_HOST_USER else "Ecclesia <no-reply@pizzatechnologies.co.ke>")
PASSWORD_RESET_TIMEOUT = 60 * 60 * 24  # reset links work for a day

# Slowing down password guessing: after this many wrong passwords for one login, wait LOGIN_LOCKOUT_MINUTES.
LOGIN_MAX_FAILURES = int(os.environ.get("LOGIN_MAX_FAILURES", "5"))
LOGIN_MAX_FAILURES_PER_IP = int(os.environ.get("LOGIN_MAX_FAILURES_PER_IP", "30"))
LOGIN_LOCKOUT_MINUTES = int(os.environ.get("LOGIN_LOCKOUT_MINUTES", "15"))

TEST_RUNNER = "tenants.testing.ChurchTestRunner"

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
