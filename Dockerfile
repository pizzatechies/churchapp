# One image runs either app:
#   APP=admin    -> Ecclesia Admin   (church management & finance)
#   APP=members  -> Ecclesia Connect (members app)
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

# Collect static files at build time (a throwaway key is fine: nothing is signed during the build).
RUN SECRET_KEY=build-only DEBUG=0 python manage.py collectstatic --noinput \
    && useradd --create-home --uid 1000 ecclesia \
    && mkdir -p /app/media \
    && chown -R ecclesia:ecclesia /app/media \
    && chmod +x /app/docker-entrypoint.sh

USER ecclesia
EXPOSE 8000
ENTRYPOINT ["/app/docker-entrypoint.sh"]
