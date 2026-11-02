#!/bin/sh
set -e

if [ "$APP" = "members" ]; then
    export DJANGO_SETTINGS_MODULE=config.settings_portal
    WSGI=config.wsgi_portal:application
else
    export DJANGO_SETTINGS_MODULE=config.settings
    WSGI=config.wsgi:application
    # The admin app owns the database. Safe on every start:
    #  - moves a single-church database into its own church space the first time (one transaction),
    #  - migrates the platform and every church,
    #  - creates the platform super admin (PLATFORM_ADMIN_* or ADMIN_*) if missing,
    #  - on a brand-new server with ECCLESIA_DEFAULT_CHURCH set, creates the first church.
    python manage.py platform_setup
    # A public demo server starts with the sample church (rebuild it nightly with "manage.py reset_demo").
    case "$ECCLESIA_DEMO_MODE" in
        1|true|yes|on) python manage.py load_demo_data --if-empty --password "${ECCLESIA_DEMO_PASSWORD:-ChurchDemo-2026}" ;;
    esac
fi

exec gunicorn "$WSGI" \
    --bind "0.0.0.0:${PORT:-8000}" \
    --workers "${WEB_CONCURRENCY:-3}" \
    --timeout "${GUNICORN_TIMEOUT:-120}" \
    --access-logfile - \
    --forwarded-allow-ips "*"
