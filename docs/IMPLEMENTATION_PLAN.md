# S3 Proxy Implementation Plan (Remaining Phases)

Phases 1–4 (hashing extraction, metadata API, replication queue/worker foundation, legacy archival) are complete. The following phases cover the missing capabilities needed for a fully functioning proxy and validation suite.

---

## Phase 5 — SigV4 Proxy & Request Router

**Goals**
- Build a SigV4-compatible proxy service that authenticates requests, consults the metadata DB, and forwards calls to the hashed backend buckets.

**Tasks**
1. Implement an ASGI middleware or dedicated module (e.g., `backend/app/proxy_router.py`) that performs SigV4 verification using stored credentials.
2. Resolve backend buckets via `hash_utils.map_backends` and route to the correct S3 endpoint using boto3 or an HTTP client.
3. Handle basic S3 verbs (`GET`, `PUT`, `HEAD`, `DELETE`) plus error propagation.
4. Add integration tests (moto, MinIO) verifying successful request routing, auth failures, and missing bucket handling.

**Deliverables**
- Running proxy service exposing `/` (SigV4) alongside `/proxy/*`.
- Automated tests covering routing/auth paths.
- Docs explaining how to point clients at the proxy endpoint.
- *Status:* Implemented in `backend/app/proxy_router.py` with coverage in `backend/tests/test_proxy_router.py`. Currently targets a single configured backend endpoint; multi-backend routing remains future work.

---

## Phase 6 — Real Replication Engine

**Goals**
- Replace the stub replication handler with real object copying between S3-compatible backends, honoring residency and replica counts.

**Tasks**
1. Extend job schema to record source/target credentials or references.
2. Implement replication logic using boto3: download from source, upload to target, verify etags.
3. Add retry/backoff logic and idempotent checks (skip if replica already matches).
4. Integration tests using dockerized MinIO/Ceph containers exercising success/failure scenarios.

**Deliverables**
- Production-ready replication worker.
- Logging/metrics for job outcomes.
- Updated docs describing configuration of source/target backends and worker deployment.
- *Status:* Worker now copies objects using boto3 via shared backend clients (`backend/app/backend_clients.py`). Jobs store source backend IDs and look up target hashed buckets. Still pending: per-backend credentials/endpoints and resumable/cross-account copies.

---

## Phase 7 — Security & Admin UX

**Goals**
- Provide secure credential storage, tenant management, and policy editing.

**Tasks**
1. Introduce admin endpoints or UI for creating tenants, managing API keys, setting residency/replica policies.
2. Store secrets securely (encryption at rest, KMS/Vault integration).
3. Add authentication/authorization around `/proxy/*` routes (JWT, API keys, mTLS).
4. Tests ensuring RBAC enforcement and secret lifecycle management.

**Deliverables**
- Admin workflows with automated coverage.
- Security documentation and onboarding guide.
- *Status:* Credentials are still stored in plaintext inside `metadata.db` (sqlite). No UI/CLI exists for tenant/policy management, and `/proxy/*` routes are unauthenticated. This phase remains open.

---

## Phase 8 — Deployment & Observability

**Goals**
- Make the system demonstrable beyond docker-compose and observable enough for a proof of concept.

**Tasks**
1. Provide docker-compose override that runs the SigV4 proxy, worker, and metadata DB together (suitable for demos).
2. Add basic structured logging and `/health` checks for the proxy router and worker.
3. Document manual load validation steps (e.g., run `scripts/smoke_test.py` to push objects through the proxy and verify replication).

**Deliverables**
- docker-compose demo file with instructions.
- Logging + health-check docs.
- Manual smoke-test script/checklist (documented in README/docs/PLAN.md).
- *Status:* Implemented via `docker/demo/docker-compose.demo.yml` and `scripts/demo_smoke_test.py`, which provide a reproducible PoC environment. Production-grade manifests/monitoring remain future work.

---

## Phase 9 — End-to-End Validation

**Goals**
- Demonstrate the full concept (discovery → proxy → hashed backend → replication) works end-to-end.

**Tasks**
1. Build automated E2E tests (pytest harness or Playwright/Cypress) that stand up MinIO clusters, push data through the proxy, and assert replicas match policy.
2. Add UI regression tests for the discovery/metadata viewer.
3. Document manual QA checklist (smoke tests, failover, replication verification).

**Deliverables**
- CI job running E2E + UI tests on every PR.
- Test evidence proving data consistency and policy enforcement.

---

Future proxy work should extend the current `backend/`, `frontend/`, and `scripts/` modules rather than touching `archive/s3gateway/`. This plan highlights the remaining engineering work to move from concept to production-ready proxy services with comprehensive testing.*** End Patch
