# syntax=docker/dockerfile:1
# check=skip=InvalidDefaultArgInFrom
ARG UPSTREAM_IMAGE
ARG UPSTREAM_TAG_SHA

# ── Stage 1: Frontend Builder ──────────────────────────────────────
FROM oven/bun:alpine AS frontend-builder
RUN apk add --no-cache curl
ARG VERSION
RUN mkdir /build && \
    curl -fsSL "https://github.com/engels74/zondarr/archive/${VERSION}.tar.gz" \
      | tar xzf - -C "/build" --strip-components=1
WORKDIR /build/frontend
RUN bun install --frozen-lockfile && \
    bun run build && \
    rm -rf node_modules && \
    bun install --production --frozen-lockfile

# ── Stage 2: Backend Builder ───────────────────────────────────────
FROM ghcr.io/astral-sh/uv:alpine AS backend-builder
RUN apk add --no-cache curl
ARG VERSION
RUN mkdir /build && \
    curl -fsSL "https://github.com/engels74/zondarr/archive/${VERSION}.tar.gz" \
      | tar xzf - -C "/build" --strip-components=1
WORKDIR /build/backend
ENV UV_PYTHON_INSTALL_DIR=/opt/python
RUN uv sync --python 3.14 --no-dev --frozen --compile-bytecode

# ── Stage 3: Runtime ───────────────────────────────────────────────
FROM ${UPSTREAM_IMAGE}:${UPSTREAM_TAG_SHA}
ARG IMAGE_STATS
ENV IMAGE_STATS=${IMAGE_STATS} \
    FRONTEND_PORT=3000 \
    BACKEND_PORT=8000 \
    WEBUI_PORTS="3000/tcp,3000/udp,8000/tcp,8000/udp"
EXPOSE ${FRONTEND_PORT} ${BACKEND_PORT}

# Bun runtime
RUN apk add --no-cache curl unzip && \
    curl -fsSL https://bun.sh/install | bash && \
    mv /root/.bun/bin/bun /usr/local/bin/ && \
    rm -rf /root/.bun

# Standalone Python 3.14 (musl) from builder
COPY --from=backend-builder /opt/python /opt/python

# Backend: venv + source + migrations
COPY --from=backend-builder /build/backend/.venv "${APP_DIR}/backend/.venv"
COPY --from=backend-builder /build/backend/src "${APP_DIR}/backend/src"
COPY --from=backend-builder /build/backend/migrations "${APP_DIR}/backend/migrations"
COPY --from=backend-builder /build/backend/alembic.ini "${APP_DIR}/backend/alembic.ini"
COPY --from=backend-builder /build/backend/pyproject.toml "${APP_DIR}/backend/pyproject.toml"

# Frontend: built SSR server + production node_modules
COPY --from=frontend-builder /build/frontend/build "${APP_DIR}/frontend/build"
COPY --from=frontend-builder /build/frontend/node_modules "${APP_DIR}/frontend/node_modules"
COPY --from=frontend-builder /build/frontend/package.json "${APP_DIR}/frontend/package.json"

# Data directory + permissions
RUN mkdir -p "${CONFIG_DIR}/data" && \
    chmod -R u=rwX,go=rX "${APP_DIR}"

# s6 services
COPY root/ /
RUN find /etc/s6-overlay/s6-rc.d -name "run*" -execdir chmod +x {} +
