# Repository Guidelines

## Project Structure & Module Organization
- Backend (FastAPI) in `backend/` (`main.py`, `app/` modules); JSON snapshots saved under `backend/snapshots/` (git-ignored).
- Frontend static UI in `frontend/` (`index.html`, `app.js`, `metadata-viewer.js`); Nginx config in `frontend/nginx.conf`.
- Containers under `docker/` with base compose `docker/docker-compose.yml` and dev override `docker/dev/docker-compose.dev.yml`.
- Data in `data/providers/`, utilities in `scripts/`, docs in `docs/`, examples in `examples/`.

## Build, Test, and Development Commands
- `make up` start stack; `make down` stop; `make logs[-backend|-frontend]` tail logs; `make clean` remove containers/volumes.
- `make dev` hot reload with bind mounts. Local only: `cd backend && uvicorn main:app --reload`; `cd frontend && python -m http.server 8080`.

## Coding Style & Naming Conventions
- Python: PEP 8, 4 spaces, type-annotated Pydantic models, helpers colocated with endpoints; reuse the shared module logger.
- JavaScript: camelCase in code, snake-case filenames; keep functions small and composable.
- Formatters (recommended): `python -m black backend`; `npx prettier frontend/*.js` to avoid noisy diffs.

## Testing Guidelines
- Use `pytest`; place tests under `backend/tests/`. Mock boto3/S3; cover invalid credentials, pagination, and snapshot persistence.
- Run `cd backend && pytest -q` before PRs. For UI, document manual checks: start stack, hit `http://localhost:8000/health`, submit credentials, verify new JSON in `backend/snapshots/`.

## Commit & Pull Request Guidelines
- Commits: short, imperative titles (e.g., "allow usage of remote host ip"); one logical change per commit.
- PRs: clear description, linked issues, tests or screenshots, and callouts for new env vars/secrets. Split backend and frontend changes when feasible.

## Security & Configuration Tips
- Never commit secrets. Copy `.env` from `env.example`; inject real values via env/compose.
- Tune CORS via `ALLOWED_ORIGINS`. Snapshot caps: `MAX_SNAPSHOT_BUCKETS`, `MAX_SNAPSHOT_FILES`, `MAX_FILES_PER_BUCKET`.
- Prefer HTTPS at the edge; sanitize logs containing bucket/object names.

For deeper detail, see `docs/CONTRIBUTING.md`.
