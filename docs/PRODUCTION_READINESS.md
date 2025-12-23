# Production Readiness & Gap Assessment

This document outlines the outstanding work to take S3Gateway from the current proof‑of‑concept to a robust, operable system. Items are split into bare‑minimum (mandatory) functionality and additional work required to run safely in production.

## Bare Minimum (Mandatory)

- Replication worker v1
  - Deterministic, idempotent jobs for create/update/delete, with backfill and periodic reconciliation. Verify ETag/size/version on targets and respect `replica-count`/residency policy.
- SigV4 router essentials
  - Support PUT/GET/DELETE/HEAD plus multipart upload (init, upload part, complete, abort). Implement range/conditional requests and map errors to S3 codes. Clock‑skew tolerance and canonicalization.
- Namespace hashing & mappings
  - Deterministic per‑tenant hashing, uniqueness guarantees, migration path for legacy buckets, and validation endpoints to inspect mappings.
- Metadata model & migrations
  - Finalize schema for tenants, buckets, objects, jobs. Add indexes/foreign keys and Alembic migrations; define retention for job history.
- Minimal authN/authZ
  - Admin API key separation, tenant credential registration, encrypted at rest (replace placeholder crypto with libsodium/OpenSSL wrapper if not using KMS yet).
- Basic observability
  - Structured logs with request IDs, health/readiness endpoints, baseline Prometheus metrics (request latency, error rate).

## Operating in Production

- Durable metadata & backups
  - Move from SQLite to PostgreSQL; connection pooling, migrations in CI, automated backups and point‑in‑time recovery. DR runbooks and restore tests.
- Secrets & key management
  - KMS/Vault integration for tenant credential encryption, rotation policies, audit trails, and envelope encryption for stored secrets.
- Replication at scale
  - Durable queue (e.g., Redis/Rabbit/Kafka/SQS), retry/backoff with dead‑letter queues, deduplication, sharded workers, and repair flows when a backend is degraded or retired.
- Security hardening
  - TLS everywhere, mTLS to backends, strict CORS, request canonicalization + replay protection for SigV4, HSTS, WAF/rate limiting at the edge, header size limits.
- Multi‑tenant controls
  - Per‑tenant quotas, rate limiting, isolation of metadata rows, and scoped admin roles (operator vs viewer). Audit logging for policy/credential changes.
- Observability & SRE
  - Metrics: replication lag, queue depth, success rate, tail latencies, error budgets. Tracing for proxy hops. Alerting + dashboards. Structured, redact‑safe logs.
- Protocol completeness
  - SSE‑S3/SSE‑KMS, CopyObject, tagging/ACLs/policy mapping, pre‑signed URLs, lifecycle compatibility, versioning behavior parity across providers.
- Resilience & performance
  - Async proxy path, connection pools, circuit breakers/backpressure, cache for mappings/policies, horizontal scaling of gateway and workers.
- Compliance & governance
  - Data residency attestations, configurable retention for audit logs, DPIA/SoA docs as needed. Document how policy enforces regional constraints.
- CI/CD & release
  - E2E tests across multiple S3 backends, load/soak tests, image signing + SBOM + vulnerability scans, staged rollouts and rollbacks.

See README and docs/PROTOCOL.md for current capabilities. The items above should be turned into tracked issues with owners, acceptance criteria, and milestones.

