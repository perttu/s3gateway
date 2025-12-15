# Repository Guidelines

## Project Structure & Module Organization
The FastAPI backend sits in `backend/`, where `main.py` holds all endpoints and `snapshots/` stores git-ignored discovery JSON. Static assets live in `frontend/` and are served via the Nginx config at `frontend/nginx.conf`, while container tooling lives under `docker/` (per-service Dockerfiles, base Compose file, and dev overrides used by the Makefile). Long-form docs and plans now live under `docs/`, data sources under `data/providers/`, helper utilities under `scripts/`, and sanitized templates under `examples/`. Historical code under `archive/s3gateway/` is read-only; do not modify it when working on the current proxy.

## Build, Test, and Development Commands
- `make up` — build (if needed) and launch the stack with docker-compose.
- `make dev` — uses `docker-compose.dev.yml` for reloadable FastAPI plus bind-mounted frontend assets.
- `make logs-backend` / `make logs-frontend` — follow container output when troubleshooting ingest or UI issues.
- `cd backend && uvicorn main:app --reload` or `cd frontend && python -m http.server 8080` — run individual tiers without Docker for fast iteration.

## Coding Style & Naming Conventions
Backend Python should follow PEP 8 with 4-space indentation, type-annotated Pydantic models, and helpers colocated with the endpoints they support while reusing the shared module logger. Frontend JavaScript stays camelCase inside snake-case filenames; keep functions small and composable so state updates remain traceable. Formatting is contributor-managed, but running `python -m black backend` and `npx prettier frontend/*.js` (when installed) avoids noisy diffs.

## Testing Guidelines
No automated suite is checked in, so add `pytest` coverage under `backend/tests/` for every new endpoint or boto3 helper and mock AWS clients to cover invalid credentials, pagination, and snapshot persistence. Run `cd backend && pytest -q` before raising a PR. For UI work, document manual checks—start the stack, hit `http://localhost:8000/health`, submit credentials, and verify `backend/snapshots/` gains the expected JSON.

## Commit & Pull Request Guidelines
History favors short, imperative commit titles such as “allow usage of remote host ip,” so keep each commit focused and explain migrations or data impacts in the body. Pull requests must include a concise summary, linked issues, evidence of tests or screenshots, and a callout for new env vars or secrets; split backend and frontend refactors unless they must land together.

## Security & Configuration Tips
Never commit credentials—copy `.env` from `env.example`, inject real secrets via Docker or your shell, and document handling notes in `docs/PLAN.md` instead of source control. Keep deployments HTTPS-terminated, sanitize logs that mention bucket names, store generated artifacts under `backend/snapshots/` so they stay ignored, and call out IAM or firewall changes whenever provider-facing code shifts. Snapshot retention is capped by `MAX_SNAPSHOT_BUCKETS`, `MAX_SNAPSHOT_FILES`, and `MAX_FILES_PER_BUCKET`; bump these env vars (plus `ALLOWED_ORIGINS` for CORS) explicitly when deployments require wider coverage.
