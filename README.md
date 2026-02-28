# Zondarr Docker Image

<p align="center">
  <img src="https://engels74.net/img/image-logos/zondarr.svg" alt="zondarr" style="width: 30%;"/>
</p>

<p align="center">
  <a href="https://github.com/engels74/zondarr-docker/blob/master/LICENSE"><img src="https://img.shields.io/badge/License%20(Image)-GPL--3.0-orange" alt="License (Image)"></a>
  <a href="https://github.com/engels74/zondarr"><img src="https://img.shields.io/badge/License%20(App)-AGPL--3.0-blue" alt="License (App)"></a>
  <a href="https://github.com/engels74/zondarr/stargazers"><img src="https://img.shields.io/github/stars/engels74/zondarr.svg" alt="GitHub Stars"></a>
</p>

## About

Zondarr is a full-stack application with a Python/Litestar backend and SvelteKit/Bun frontend. This Docker image runs both services using s6-overlay process supervision.

## Docker Compose

```yaml
services:
  zondarr:
    container_name: zondarr
    image: ghcr.io/engels74/zondarr:latest
    ports:
      - 3000:3000   # Frontend (SvelteKit SSR)
      - 8000:8000   # Backend API (Litestar/Granian)
    environment:
      - PUID=1000
      - PGID=1000
      - UMASK=002
      - TZ=Etc/UTC
      # - SECRET_KEY=           # Auto-generated on first run, persisted to /config/data/.secret_key
      # - DATABASE_URL=         # Default: SQLite at /config/data/zondarr.db
      # - PUBLIC_API_URL=       # Default: http://localhost:8000 (override for remote/reverse-proxy setups)
      # - SECURE_COOKIES=true   # Set when serving over HTTPS (enforces Secure flag on cookies)
      # - CSRF_ORIGIN=https://zondarr.example.com  # Required for HTTPS with a custom domain
    volumes:
      - ./config:/config
    restart: unless-stopped
```

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `PUID` | `1000` | User ID for file permissions |
| `PGID` | `1000` | Group ID for file permissions |
| `UMASK` | `002` | File creation mask |
| `TZ` | `Etc/UTC` | Timezone |
| `SECRET_KEY` | *(auto-generated)* | JWT signing key. Auto-generated on first run and persisted to `/config/data/.secret_key`. Set explicitly to override. |
| `DATABASE_URL` | `sqlite+aiosqlite:///config/data/zondarr.db` | Database connection string. Supports SQLite (default) and PostgreSQL. |
| `PUBLIC_API_URL` | `http://localhost:8000` | URL the frontend SSR server uses to reach the backend. Override when using a reverse proxy or remote deployment. |
| `SECURE_COOKIES` | `false` | Set to `true` when serving over HTTPS to enforce the Secure flag on cookies. |
| `CSRF_ORIGIN` | *(none)* | Trusted origin for CSRF protection (e.g., `https://zondarr.example.com`). Required for HTTPS with a custom domain. |

## Ports

| Port | Service |
|---|---|
| `3000` | Frontend — SvelteKit SSR server (Bun) |
| `8000` | Backend — Litestar API server (Granian) |

## Data Persistence

All persistent data is stored in `/config/data/`:
- `zondarr.db` — SQLite database (default)
- `.secret_key` — Auto-generated JWT signing key

Database migrations (Alembic) run automatically on every container startup.

## License

- **Docker Image**: Licensed under the GPL-3.0 License. See the [LICENSE](https://github.com/engels74/zondarr-docker/blob/master/LICENSE) file for details.
- **Zondarr Application**: Licensed under the AGPL-3.0 License. See the [zondarr repository](https://github.com/engels74/zondarr) for details.
