#!/bin/sh
# Renders frontend/nginx/config.js.template into a writable tmpfs (/config-runtime, mounted by
# docker-compose.yml) using envsubst, so the frontend container's runtime config is driven by
# ordinary environment variables instead of being baked in at `docker build` time. Runs on every
# container start via nginx's own /docker-entrypoint.d/ convention (any executable *.sh there is
# sourced by the base image's docker-entrypoint.sh before nginx starts).
#
# See docs/adr/007-runtime-frontend-config.en.md. The main filesystem is mounted read_only: true
# (docker-compose.yml) on purpose — only this one small tmpfs is writable, so a compromised
# request handler can't tamper with the served application bundle, only this config file.
set -eu

: "${CAPATAZ_FRONTEND_API_BASE_URL:=/api/v1}"
: "${CAPATAZ_FRONTEND_USE_MSW:=false}"
: "${CAPATAZ_FRONTEND_DEV_USER:=ana.admin}"
: "${CAPATAZ_FRONTEND_OIDC_ISSUER:=}"
: "${CAPATAZ_FRONTEND_OIDC_CLIENT_ID:=}"
: "${CAPATAZ_FRONTEND_OIDC_SCOPE:=openid profile email groups}"

# envsubst does not escape its replacement values, so none of the above may contain a double
# quote or backslash — they would break the generated JS. All six are operator-controlled
# deployment config (URLs, a scope, a username, a boolean), never end-user input, so this is a
# documented constraint, not a sanitization gap: see docs/adr/007-runtime-frontend-config.en.md.
export CAPATAZ_FRONTEND_API_BASE_URL CAPATAZ_FRONTEND_USE_MSW CAPATAZ_FRONTEND_DEV_USER \
  CAPATAZ_FRONTEND_OIDC_ISSUER CAPATAZ_FRONTEND_OIDC_CLIENT_ID CAPATAZ_FRONTEND_OIDC_SCOPE

mkdir -p /config-runtime
envsubst \
  '${CAPATAZ_FRONTEND_API_BASE_URL} ${CAPATAZ_FRONTEND_USE_MSW} ${CAPATAZ_FRONTEND_DEV_USER} ${CAPATAZ_FRONTEND_OIDC_ISSUER} ${CAPATAZ_FRONTEND_OIDC_CLIENT_ID} ${CAPATAZ_FRONTEND_OIDC_SCOPE}' \
  < /etc/nginx/runtime-config-template/config.js.template \
  > /config-runtime/config.js
