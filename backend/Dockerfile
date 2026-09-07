# Backend image: Django + DRF served over ASGI.
#
# Built by .github/workflows/deploy.yml and pushed to GHCR as
# ghcr.io/<owner>/geo-portal-backend. docker-compose.dev.yml builds this same
# image for local work and only overrides the command, so what runs on a
# laptop is what ships.
FROM python:3.12-slim

# PYTHONUNBUFFERED: logs reach `docker logs` immediately rather than sitting in
# a block buffer, which is the difference between a debuggable deploy and a
# silent one.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# curl is the container's own health probe; deploy.sh checks from the host,
# but the compose healthcheck has to work from inside.
RUN apt-get update \
    && apt-get install --no-install-recommends -y curl \
    && rm -rf /var/lib/apt/lists/*

# Requirements first: this layer is cached until a pin actually changes.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Admin's static files are baked into the image, so rolling back to an older
# SHA gets that SHA's assets (docs/adr/007). No database is touched here, and
# DJANGO_SECRET_KEY's insecure default is enough for a build-time collect —
# the real key arrives from the host .env at run time.
RUN python manage.py collectstatic --noinput

# Django never runs as root in a container it did not build itself.
RUN useradd --create-home --uid 1001 portal \
    && chown -R portal:portal /app
USER portal

EXPOSE 8000

ENTRYPOINT ["./entrypoint.sh"]

# Gunicorn supervises uvicorn workers: ASGI from the start, so the SSE work in
# the Ask slice needs no change here (context/architecture.md).
CMD ["gunicorn", "config.asgi:application", \
     "--worker-class", "uvicorn.workers.UvicornWorker", \
     "--bind", "0.0.0.0:8000", \
     "--workers", "3", \
     "--access-logfile", "-"]
