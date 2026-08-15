FROM node:26.7.0-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginxinc/nginx-unprivileged:1.28.0-alpine3.21
USER root
# gettext provides envsubst, used to render runtime config.js from CAPATAZ_FRONTEND_* env vars
# at container start — see frontend/nginx/40-render-runtime-config.sh and
# docs/adr/007-runtime-frontend-config.en.md. No VITE_* build args here on purpose: this image is
# meant to be built once and configured per environment at `docker run`/compose time, not
# rebuilt per environment.
RUN apk add --no-cache libcap gettext && setcap cap_net_bind_service=+ep /usr/sbin/nginx
COPY nginx/default.conf /etc/nginx/conf.d/default.conf
COPY nginx/config.js.template /etc/nginx/runtime-config-template/config.js.template
COPY nginx/40-render-runtime-config.sh /docker-entrypoint.d/40-render-runtime-config.sh
RUN chmod +x /docker-entrypoint.d/40-render-runtime-config.sh
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
USER 101
