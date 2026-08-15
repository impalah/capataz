FROM ghcr.io/astral-sh/uv:0.10.12-python3.14-trixie-slim AS builder
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
RUN uv sync --frozen --no-dev

FROM python:3.14-slim-trixie
RUN useradd --create-home --uid 10001 capataz
WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/src /app/src
ENV PATH="/app/.venv/bin:$PATH" PYTHONPATH=/app/src PYTHONDONTWRITEBYTECODE=1
USER capataz
EXPOSE 8000
CMD ["uvicorn", "capataz_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
