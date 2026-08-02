# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Repository Is

Docker packaging for the Zondarr application. **No application source lives here.** The Dockerfiles
download the app as a tarball from `github.com/engels74/zondarr` at build time. Bugs in the Python
backend or SvelteKit frontend belong in that repository, not this one.

This repo owns three things: the two Dockerfiles, the s6-overlay service definitions under `root/`,
and `meta.json`.

## Branches Are Image Tags

There is no `main` or `master`. Each long-lived branch builds and publishes a Docker tag of the same name.

| Branch | Publishes | `meta.json` version source |
|---|---|---|
| `release` | `ghcr.io/engels74/zondarr:release` and `:latest` (`"latest": true`) | newest tag of `engels74/zondarr` |
| `nightly` | `ghcr.io/engels74/zondarr:nightly` (`"latest": false`) | HEAD commit SHA of `engels74/zondarr@main` |

**The branches are never merged.** Fixes are committed independently to each. The same change appears
twice in history under separate SHAs (e.g. `83de859` on `release`, `f612062` on `nightly`). They have
already drifted: `nightly`'s Dockerfile uses `uv sync ... --no-editable` and omits `COPY src`, while
`release` does the opposite. When fixing something structural, apply it to both branches and check
`git diff origin/nightly origin/release` first to see what else is out of sync.

## meta.json Drives Every Build Arg

`build.sh` and CI both uppercase every `meta.json` key and pass it as `--build-arg`. CI additionally
strips keys matching `__COMMAND`. To add a build argument: add a lowercase key to `meta.json` and a
matching `ARG` in both Dockerfiles. Nothing else wires them together.

Keys ending in `__command` are shell snippets. The shared hourly `update-on-call.yml` workflow `eval`s
each one and writes the result into the sibling key, then auto-commits as `Modified: meta.json`
(author `github-actions[bot]`). **Never hand-edit `version` or `upstream_tag_sha`** — edit the
`__command` that produces them. Most commits in this repo are these bot updates.

`test_amd64` / `test_arm64` / `test_url` control the CI smoke test: the built image runs with
`--network host` and CI curls `test_url` with retries. A container that fails to serve `http://localhost:3000`
fails the build.

## CI

Both workflows in `.github/workflows/` are two-line shims that call reusable workflows from the
`workflows` branch of `engels74/base-image`. Do not add build logic here — it lives in that repo.

- `call-build.yml` — every push to any branch except `workflows`. Matrix-builds `linux-amd64` on
  `ubuntu-24.04` and `linux-arm64` on `ubuntu-24.04-arm` (native, no cross-compilation), pushes
  manifests, then regenerates `packages.txt`.
- `call-update.yml` — hourly cron; runs the `__command` refresh across all branches.

`packages.txt` is generated and committed by CI (with `[skip ci]`). Do not create or edit it by hand.

## Dockerfile Structure

`linux-amd64.Dockerfile` and `linux-arm64.Dockerfile` are byte-identical on `release`. **Always change
both.** Three stages:

1. `frontend-builder` (`oven/bun:alpine`) — `bun run build`, then reinstall production-only deps.
2. `backend-builder` (`ghcr.io/astral-sh/uv:alpine`) — `uv sync --python 3.14 --frozen`, with the
   standalone interpreter placed in `/opt/python` via `UV_PYTHON_INSTALL_DIR`.
3. Runtime — `FROM ${UPSTREAM_IMAGE}:${UPSTREAM_TAG_SHA}`, copying artifacts from stages 1 and 2.

The runtime base is `ghcr.io/engels74/base-image:alpinevpn`, which already provides `APP_DIR=/app`,
`CONFIG_DIR=/config`, the `hotio` user, `PUID`/`PGID`/`UMASK`/`TZ`, the `/init` entrypoint, all VPN
services, and `/etc/s6-overlay/scripts/bash-functions` (source it for `log_inf`, `log_wrn`, `log_err`).
Do not redefine any of these.

## Adding or Changing an s6 Service

Service definitions live in `root/`, which is `COPY root/ /` into the image. To add a service:

1. Create `root/etc/s6-overlay/s6-rc.d/<name>/` containing `type` (`oneshot` or `longrun`) and `run`.
   A `oneshot` also needs an `up` file whose contents are the absolute path to its own `run`.
2. Create empty marker files at `root/etc/s6-overlay/s6-rc.d/<name>/dependencies.d/<dependency>` for
   each service that must start first.
3. Create an empty marker at `root/etc/s6-overlay/user-bundles.d/user/contents.d/<name>`. This
   location is mandatory for s6-overlay >= 3.2.3.1; the old `s6-rc.d/user/contents.d/` path silently
   fails to start the service (commit `83de859`).

File permissions are irrelevant — the Dockerfile runs
`find /etc/s6-overlay/s6-rc.d -name "run*" -execdir chmod +x {} +`.

Current startup chain: `init-setup` (base image) → `init-setup-app` → `service-zondarr-backend`
(also gated on `init-wireguard`) → `service-zondarr-frontend`.

## Passing Environment Variables Between s6 Services

A oneshot runs in its own process; `export` does not reach later services. Write to the s6 container
environment directory instead. This is the established pattern in `init-setup-app/run`:

```bash
if [[ -z "${DATABASE_URL}" ]]; then
    DATABASE_URL="sqlite+aiosqlite:///${CONFIG_DIR}/data/zondarr.db"
    export DATABASE_URL
    printf '%s' "${DATABASE_URL}" > /var/run/s6/container_environment/DATABASE_URL
fi
```

| Situation | Where it goes |
|---|---|
| Static default, known at build time | `ENV` in both Dockerfiles (e.g. `FRONTEND_PORT`) |
| Value computed or derived at startup | `init-setup-app/run`, written to `/var/run/s6/container_environment/` |
| Secret generated on first run | `init-setup-app/run`, persisted under `${CONFIG_DIR}/data/` with `chmod 600` |

Long-running services must `exec s6-setuidgid hotio ...` so the process drops to the mapped
`PUID`/`PGID` rather than running as root.

## Persistence and Migrations

Everything durable lives in `${CONFIG_DIR}/data/` (`zondarr.db`, `.secret_key`), created and chowned to
`hotio` by `init-setup-app/run`. Alembic `upgrade head` runs there on **every** container start, before
the backend service — a schema change in the upstream app needs no change here.

## Local Builds

```bash
./build.sh amd64     # or: ./build.sh arm64
```

Run from the repository root. It requires `jq` and `git`, reads every `meta.json` key as a build arg,
and tags the result `zondarr-docker-amd64`. There is no test suite, linter, or formatter configured in
this repository.

**On `release`, `meta.json` currently holds `"version": "null"`** because `engels74/zondarr` has no
tags yet, so `build.sh` will try to download `.../archive/null.tar.gz` and fail. To build locally from
`release`, temporarily point `version` at a real ref, or build from `nightly` where it is a commit SHA.

## Additional Documentation

- `README.md` — Read before changing any environment variable, port, or default; the user-facing table
  there must be updated in the same commit.
- `engels74/base-image` (`alpinevpn` branch) — Read when a change depends on base-image behaviour:
  `root/etc/s6-overlay/scripts/bash-functions` for logging helpers, `root/etc/s6-overlay/s6-rc.d/init-setup/run`
  for what already runs before `init-setup-app`.
- `engels74/base-image` (`workflows` branch) — Read `build-on-call.yml` or `update-on-call.yml` when
  diagnosing a CI failure or changing how `meta.json` is consumed.
