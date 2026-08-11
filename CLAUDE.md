# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repository is

This is a self-hosted deployment of [InvenTree](https://inventree.org) (an open-source inventory
management system), configured for a "refurb" (refurbishment) use case. It is **not** a custom
application codebase — there is no application source code here. It is a Docker Compose stack plus
generated runtime data for an InvenTree instance, living in `inventree-refurb/`.

The actual InvenTree application source lives inside the `inventree/inventree` Docker images pulled
at deploy time — it is not checked out in this repository.

## Layout

- `inventree-refurb/docker-compose.yml` — defines the 5-container stack: `inventree-db` (Postgres 17),
  `inventree-cache` (Redis, ephemeral/no persistence), `inventree-server` (gunicorn web server),
  `inventree-worker` (django-q background worker), `inventree-proxy` (Caddy reverse proxy).
- `inventree-refurb/.env` — all environment-specific configuration (DB credentials, ports, image tag,
  site URL, etc.). **The docker-compose.yml should not need to be edited directly** — per its own
  comments, all customization is meant to go through `.env`.
- `inventree-refurb/Caddyfile` — reverse proxy config: serves `/static/*` and `/media/*` directly
  (media files require auth via `forward_auth` to the InvenTree server's `/auth/` endpoint), proxies
  everything else to `inventree-server`.
- `inventree-refurb/inventree-data/` — the external data volume mounted into the containers
  (`INVENTREE_EXT_VOLUME`). Contains generated/runtime state: `pgdb/` (Postgres data directory),
  `media/`, `static/`, `backup/`, `plugins/`, `caddy/`, plus `config.yaml`, `secret_key.txt`,
  `oidc.pem`. Treat everything under here as generated/runtime data, not source to hand-edit, except
  `config.yaml` and `plugins.txt` which are legitimate config surfaces.
- `inventree-refurb/inventree-data/plugins.txt` — pip-installable InvenTree plugin list (currently empty).
- `inventree-refurb/requirements.txt` — a small Python environment (`inventree` PyPI package, i.e. the
  InvenTree Python API client, plus `requests`) with a matching `.venv/`, for writing scripts against
  the InvenTree REST API. No such scripts exist yet.

## Common commands

Run from `inventree-refurb/` (where `docker-compose.yml` lives):

```
docker compose up -d          # start the stack
docker compose down           # stop the stack
docker compose logs -f <service>   # tail logs, e.g. inventree-server / inventree-worker / inventree-proxy
docker compose restart inventree-server
docker compose exec inventree-server invoke --list   # list InvenTree management (invoke) tasks
```

There is no build/lint/test tooling in this repository — those apply to the upstream InvenTree
project, not to this deployment config.

## Working in this repo

- Configuration changes belong in `.env` (and `Caddyfile` / `config.yaml` for proxy/app-level
  settings), not in `docker-compose.yml`.
- `.env`, `inventree-data/secret_key.txt`, and `inventree-data/oidc.pem` contain secrets/credentials —
  never print their contents or commit them anywhere.
- `inventree-data/pgdb`, `inventree-data/media`, `inventree-data/static`, `inventree-data/backup` are
  live application data (database files, uploaded media, backups). Treat deletion/modification here as
  destructive — it can destroy real inventory data, not just cache.