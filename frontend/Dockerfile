# syntax=docker/dockerfile:1.7
#
# The frontend is a static bundle. nginx serves it and proxies /api to the
# backend so the browser only ever sees one origin — which means no CORS
# preflight on every request and no third-party-cookie problems.

# ─── Build ───────────────────────────────────────────────────────────────────
FROM node:22-alpine AS builder

WORKDIR /build

# npm ci needs both files and is dramatically faster and more reproducible
# than npm install for a locked project.
COPY package.json package-lock.json* ./
RUN npm ci --no-audit --no-fund

COPY . .
RUN npm run build

# ─── Runtime ─────────────────────────────────────────────────────────────────
FROM nginx:1.27-alpine AS runtime

RUN rm /etc/nginx/conf.d/default.conf
COPY --from=builder /build/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/app.conf

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD wget -qO- http://localhost/ >/dev/null || exit 1

CMD ["nginx", "-g", "daemon off;"]
