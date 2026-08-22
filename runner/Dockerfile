# syntax=docker/dockerfile:1.7
FROM ghcr.io/astral-sh/uv:0.12.5 AS uv

FROM python:3.14-slim-bookworm AS builder
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY --from=uv /uv /uvx /bin/
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

FROM python:3.14-slim-bookworm AS runtime
RUN apt-get update \
    && apt-get install -y --no-install-recommends openssh-client rsync git \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 --shell /usr/sbin/nologin capataz
# Runtime only ever runs celery from the already-built /app/.venv — it never invokes pip. The
# base image's own system Python still ships pip/setuptools/wheel (vendoring their own copies of
# transitive libs like msgpack), which are unused here but do show up as fixable CVEs in image
# scans; strip them instead of chasing a base-image tag bump for a package we never call.
RUN find /usr/local/lib -maxdepth 3 -type d \
      \( -name "pip" -o -name "pip-*" -o -name "setuptools" -o -name "setuptools-*" \
         -o -name "pkg_resources" -o -name "wheel" -o -name "wheel-*" -o -name "_distutils_hack" \) \
      -exec rm -rf {} + \
    && rm -f /usr/local/bin/pip /usr/local/bin/pip3 /usr/local/bin/pip3.* /usr/local/lib/python3.14/site-packages/distutils-precedence.pth
WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
COPY --chown=capataz:capataz src /app/src
COPY --chown=capataz:capataz playbooks /app/playbooks
COPY --chown=capataz:capataz inventories /app/inventories
ENV PATH="/app/.venv/bin:$PATH" PYTHONPATH="/app/src" CAPATAZ_PROJECT_ROOT=/app PYTHONDONTWRITEBYTECODE=1
USER capataz
# -B embeds the beat scheduler (only the reap-stuck-executions periodic task, see celery_app.py)
# in the same process; --schedule points its state file at the writable /tmp tmpfs since the
# container filesystem is otherwise read-only (see docker-compose.yml).
CMD ["celery", "-A", "capataz_runner.celery_app:app", "worker", "--loglevel=INFO", "--queues=automation", "-B", "--schedule=/tmp/celerybeat-schedule"]
