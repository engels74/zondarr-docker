# syntax=docker/dockerfile:1
# check=skip=InvalidDefaultArgInFrom
ARG UPSTREAM_IMAGE
ARG UPSTREAM_DIGEST_AMD64
ARG UPSTREAM_DIGEST_ARM64
ARG BUN_IMAGE=oven/bun:1.4.2-alpine@sha256:d888c0ae6c86d7866ff10c5aafdd9077b36aee6455b33dd270fb93c0dd5cef6f
ARG UV_IMAGE=ghcr.io/astral-sh/uv:0.12.10-alpine@sha256:3d372c685653f7c66ed18c4395a3099e33f9dd9a9b3a8d43238c319918b9e182

FROM ${BUN_IMAGE} AS bun

# Fetch and verify the application once for both builders.
FROM bun AS source
RUN apk add --no-cache curl
ARG VERSION
ARG SOURCE_SHA256
RUN mkdir /source && \
    curl -fsSL "https://github.com/edbfi/zondarr/archive/${VERSION}.tar.gz" -o /tmp/source.tar.gz && \
    echo "${SOURCE_SHA256}  /tmp/source.tar.gz" | sha256sum -c - && \
    tar xzf /tmp/source.tar.gz -C /source --strip-components=1 && \
    rm /tmp/source.tar.gz

FROM bun AS frontend-dependencies
WORKDIR /build/frontend
COPY --from=source /source/frontend/package.json /source/frontend/bun.lock ./
# Defer only the project's prepare hook until its Svelte config is available.
RUN bun -e 'const p = await Bun.file("package.json").json(); delete p.scripts.prepare; await Bun.write("package.json", JSON.stringify(p));'
RUN bun install --frozen-lockfile

FROM frontend-dependencies AS frontend-builder
COPY --from=source /source/frontend/ ./
RUN bun run prepare && bun run build

FROM bun AS frontend-production-dependencies
WORKDIR /build/frontend
COPY --from=frontend-dependencies /build/frontend/package.json /build/frontend/bun.lock ./
RUN bun install --production --frozen-lockfile

FROM ${UV_IMAGE} AS backend-builder
WORKDIR /build/backend
ENV UV_PYTHON_INSTALL_DIR=/opt/python
COPY --from=source /source/backend/ ./
RUN uv sync --python 3.14.7 --no-dev --frozen --compile-bytecode --no-editable

FROM ${UPSTREAM_IMAGE}@${UPSTREAM_DIGEST_AMD64}
ARG IMAGE_STATS
ENV IMAGE_STATS=${IMAGE_STATS} \
    NODE_ENV=production \
    FRONTEND_PORT=3000 \
    BACKEND_PORT=8000 \
    WEBUI_PORTS="3000/tcp,3000/udp,8000/tcp,8000/udp"
EXPOSE ${FRONTEND_PORT} ${BACKEND_PORT}

COPY --from=bun /usr/local/bin/bun /usr/local/bin/bun

# Retain the standalone interpreter path used by the virtual environment.
COPY --from=backend-builder /opt/python /opt/python
# Services invoke this interpreter with -m; installed console-script shebangs
# reference the build path and are not runtime entry points.
COPY --from=backend-builder /build/backend/.venv "${APP_DIR}/backend/.venv"
COPY --from=backend-builder /build/backend/migrations "${APP_DIR}/backend/migrations"
COPY --from=backend-builder /build/backend/alembic.ini "${APP_DIR}/backend/alembic.ini"
COPY --from=backend-builder /build/backend/pyproject.toml "${APP_DIR}/backend/pyproject.toml"

COPY --from=frontend-builder /build/frontend/build "${APP_DIR}/frontend/build"
COPY --from=frontend-production-dependencies /build/frontend/node_modules "${APP_DIR}/frontend/node_modules"
COPY --from=source /source/frontend/package.json "${APP_DIR}/frontend/package.json"

RUN mkdir -p "${CONFIG_DIR}/data" && \
    chmod -R u=rwX,go=rX "${APP_DIR}"

COPY root/ /
RUN find /etc/s6-overlay/s6-rc.d -name "run*" -execdir chmod +x {} +
