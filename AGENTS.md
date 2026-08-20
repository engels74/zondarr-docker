# AGENTS.md

This file provides guidance to AI coding agents when working with code in this
repository.

## Scope

Packaging-only repository for the `zondarr` Docker image. No application source lives here — both
Dockerfiles fetch `https://github.com/engels74/zondarr/archive/${VERSION}.tar.gz` at build time.
Backend (Python/Litestar) and frontend (SvelteKit/Bun) changes belong in `engels74/zondarr`. This
repo owns the two Dockerfiles, the s6 services under `root/`, and `meta.json`.

## Branches are release channels

`release` is the default branch. There is no `master` (the `blob/master/...` links in `README.md`
are stale).

| Branch    | `version` resolves to                | `latest` |
|-----------|--------------------------------------|----------|
| `release` | newest tag of `engels74/zondarr`     | `true`   |
| `nightly` | HEAD commit SHA of upstream `main`   | `false`  |

Branches are never merged; a fix lands only on the branch you commit it to. They have already
drifted in ways that are legitimate (`meta.json`, `README.md`, `renovate.json` release-only,
`packages.txt` nightly-only) *and* in ways that are not — nightly carries backend/frontend service
changes and a different startup env contract (`INTERNAL_API_URL` in place of the `PUBLIC_API_URL`
default, plus `BOOTSTRAP_TOKEN` and `GRANIAN_WORKERS`). Run `git diff origin/release origin/nightly`
before porting anything, and port structural fixes to both channels explicitly.

## Commands

No test suite, linter, formatter, or typechecker exists here. Validation is the image build plus an
HTTP smoke test.

```sh
./build.sh amd64     # -> local image "zondarr-docker-amd64"; needs docker + jq + a git checkout
./build.sh arm64
jq -r 'to_entries[]|[(.key|ascii_upcase),.value]|join("=")' < meta.json  # build args build.sh sends
eval "$(jq -r '.version__command' < meta.json)"                         # re-run the version probe
```

Reproduce CI's smoke test: `docker run --rm --network host zondarr-docker-amd64`, then
`curl -fsSL http://localhost:3000` (the `test_url` from `meta.json`).

**`./build.sh` fails on `release` today.** `engels74/zondarr` has no tags, so `meta.json` holds
`"version": "null"` and the build fetches `.../archive/null.tar.gz`. To build locally, either point
`version` at a real ref temporarily (do not commit it) or build from `nightly`, where `version` is a
commit SHA.

## meta.json is the build contract

- Every key becomes an uppercase `--build-arg`. The Dockerfiles consume only `VERSION`,
  `UPSTREAM_IMAGE`, `UPSTREAM_TAG_SHA`, and `IMAGE_STATS`; CI reads the rest itself. `IMAGE_STATS` is
  injected by CI and is deliberately absent from `meta.json`.
- `*__command` values are shell snippets the hourly update workflow `eval`s, writing the result back
  to the same key minus the suffix. To change how a version is discovered, edit the `__command` —
  the resolved value is overwritten on the next run.
- `version` and `upstream_tag_sha` are bot-maintained; hand edits are lost. Most commits in this
  repo are those bot updates, titled `Modified: meta.json`.
- `latest: true` publishes `:latest`; `test_amd64`/`test_arm64`/`test_url` gate the smoke test.
- To add a build argument: add a lowercase key here *and* a matching `ARG` in both Dockerfiles.

## CI lives in another repository

`.github/workflows/call-build.yml` and `call-update.yml` are thin callers into
`engels74/base-image/.github/workflows/{build-on-call,update-on-call}.yml@workflows`. All build,
publish, manifest, and tagging logic is there — change that repo, not this one.

Any push to any branch except `workflows` triggers a full build and publish. amd64 builds on
`ubuntu-24.04` and arm64 on `ubuntu-24.04-arm` — native, no cross-compilation, so a divergence
between the two Dockerfiles ships one broken architecture. `packages.txt` is bot-generated; never
hand-edit it, and don't create one on `release`, where CI has correctly produced none.

## Container runtime contract

`APP_DIR=/app`, `CONFIG_DIR=/config`, the `XDG_*` vars, `PUID`/`PGID`/`UMASK`/`TZ`, the `hotio` user
(uid/gid 1000), the `/init` entrypoint, and all VPN services come from
`ghcr.io/engels74/base-image:alpinevpn`. Use the variables; do not redefine them or hardcode `/app`
or `/config`.

- Shared bash helpers: `source /etc/s6-overlay/scripts/bash-functions` (`log_inf`, `log_wrn`,
  `log_err`, `mask`, ...).
- Long-running services drop privileges: `exec s6-setuidgid hotio ...`.
- Persistent state lives in `${CONFIG_DIR}/data/` (`zondarr.db`, `.secret_key`), created and chowned
  to `hotio` by `init-setup-app/run`. Alembic `upgrade head` runs there on **every** container
  start, before the backend — an upstream schema change needs no change in this repo.
- Startup chain: `init-setup` (base) → `init-setup-app` → `service-zondarr-backend` (also ordered
  after `init-wireguard`) → `service-zondarr-frontend`.

## Adding or changing an s6 service

1. `root/etc/s6-overlay/s6-rc.d/<name>/type` containing `oneshot` or `longrun`.
2. `run` starting with `#!/command/with-contenv bash`; for `oneshot` also add `up` holding the
   absolute in-container path of that `run` (see `init-setup-app/up`).
3. Ordering: an empty marker file at `<name>/dependencies.d/<dependency>`.
4. Enable it with an empty marker at `root/etc/s6-overlay/user-bundles.d/user/contents.d/<name>` —
   not `s6-rc.d/user/contents.d/`, which stopped working at s6-overlay 3.2.3.1 and makes the service
   silently never start (commit `83de859`).
5. No `chmod` needed; both Dockerfiles end with
   `find /etc/s6-overlay/s6-rc.d -name "run*" -execdir chmod +x {} +`.

Marker files under `dependencies.d/` and `contents.d/` are empty on purpose — create them with
`touch`; content is not how s6 reads them.

`dependencies.d/` only orders *starts*; it does not wait for readiness. If a service needs the
backend to answer, poll it in `run` (nightly's `service-zondarr-frontend/run` polls
`/health/live`) rather than relying on the dependency marker.

## Passing values between s6 services

A `oneshot` runs in its own process, so `export` does not reach later services. Write to the s6
container environment directory as well — the established pattern in `init-setup-app/run`:

```bash
printf '%s' "${DATABASE_URL}" > /var/run/s6/container_environment/DATABASE_URL
```

| Situation                              | Where it goes                                              |
|----------------------------------------|------------------------------------------------------------|
| Static default known at build time     | `ENV` in both Dockerfiles (e.g. `FRONTEND_PORT`)             |
| Computed or derived at startup         | `init-setup-app/run` + `/var/run/s6/container_environment/`  |
| Secret generated on first run          | same, persisted under `${CONFIG_DIR}/data/` with `chmod 600` |

## Gotchas

- **Edit both Dockerfiles together.** `linux-amd64.Dockerfile` and `linux-arm64.Dockerfile` are
  byte-identical on `release`; CI builds each on its own runner.
- **Keep both header lines.** `# check=skip=InvalidDefaultArgInFrom` suppresses the BuildKit check
  that `FROM ${UPSTREAM_IMAGE}:${UPSTREAM_TAG_SHA}` would otherwise fail.
- **Changing a port touches five places:** `ENV FRONTEND_PORT`/`BACKEND_PORT`/`WEBUI_PORTS` in both
  Dockerfiles, the `!= "3000" || != "8000"` guard in `init-setup-app/run` that rewrites
  `WEBUI_PORTS`, `test_url` in `meta.json`, and the compose example plus tables in `README.md`. Miss
  `test_url` and the smoke test fails the build.
- Human commits use Conventional Commits. `Modified: <files>` is the bot's format — don't imitate it.

## Reference

- `README.md` — user-facing compose example and env/port tables. Branch-specific; update it in the
  same commit whenever you change a port, volume, or environment variable.
- `engels74/base-image` branch `alpinevpn` — what the base layer already provides (env vars, the
  `hotio` user, `bash-functions`, `init-setup`, `init-wireguard`). Read before adding something that
  may already exist.
- `engels74/base-image` branch `workflows` — `build-on-call.yml` / `update-on-call.yml`. Read before
  changing how the image is built, tagged, published, or how `meta.json` is consumed.
