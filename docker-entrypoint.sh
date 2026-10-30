#!/bin/sh
set -e

if [ "$APP" = "members" ]; then
    export DJANGO_SETTINGS_MODULE=config.settings_portal
    WSGI=config.wsgi_portal:application
else
    export DJANGO_SETTINGS_MODULE=config.settings
    WSGI=config.wsgi:application
    # The admin app owns the database schema: migrate and make sure defaults exist.
    python manage.py migrate --noinput
    # Safe on every start: only fills in what's missing. The country preset applies on first setup only.
    python manage.py setup_church \
        ${CHURCH_COUNTRY:+--country "$CHURCH_COUNTRY"} \
        ${ADMIN_USERNAME:+--admin-username "$ADMIN_USERNAME"} \
        ${ADMIN_PASSWORD:+--admin-password "$ADMIN_PASSWORD"} \
        ${ADMIN_EMAIL:+--admin-email "$ADMIN_EMAIL"}
    # A public demo server starts with the sample church (reset it nightly with "manage.py reset_demo").
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
