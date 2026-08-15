# syntax=docker/dockerfile:1.7
FROM ghcr.io/astral-sh/uv:0.6.5 AS uv

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
