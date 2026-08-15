FROM ghcr.io/astral-sh/uv:0.10.12-python3.14-trixie-slim AS builder
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
RUN uv sync --frozen --no-dev

FROM python:3.14-slim-trixie
# Runtime only ever runs uvicorn from the already-built /app/.venv — it never invokes pip. The
# base image's own system Python still ships pip/setuptools/wheel (vendoring their own copies of
# transitive libs like msgpack), which are unused here but do show up as fixable CVEs in image
# scans; strip them instead of chasing a base-image tag bump for a package we never call.
RUN find /usr/local/lib -maxdepth 3 -type d \
      \( -name "pip" -o -name "pip-*" -o -name "setuptools" -o -name "setuptools-*" \
         -o -name "pkg_resources" -o -name "wheel" -o -name "wheel-*" -o -name "_distutils_hack" \) \
      -exec rm -rf {} + \
    && rm -f /usr/local/bin/pip /usr/local/bin/pip3 /usr/local/bin/pip3.* /usr/local/lib/python3.14/site-packages/distutils-precedence.pth
RUN useradd --create-home --uid 10001 capataz
WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/src /app/src
ENV PATH="/app/.venv/bin:$PATH" PYTHONPATH=/app/src PYTHONDONTWRITEBYTECODE=1
USER capataz
EXPOSE 8000
CMD ["uvicorn", "capataz_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
