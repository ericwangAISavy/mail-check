# Optional Docker microservice foundation

**Deployment decision (November 12, 2026):** The working application now targets native Windows services without Docker/WSL. This document describes the existing optional Docker foundation only. The native launcher and full business migration are not implemented yet; follow the [current migration plan](../../docs/superpowers/plans/2026-11-11-full-postgresql-migration.md).

This is the first implementation phase of the [architecture](../../docs/architecture/SINGLE_HOST_MICROSERVICES.md). It is **not a completed migration**. Authentication, business APIs, provider collection, Intelligence job execution and browser SSE are still supplied by the existing application until subsequent phases implement and validate their contracts. No current account/database/credential is imported or modified here.

## What runs

- Independent Core (two HTTP processes), Mail and Intelligence foundation images/entry points.
- PostgreSQL with separate service databases, non-login owners, restricted application roles and separate migration roles.
- Real migrations, transactional outboxes/jobs and a commit-ordered Core event journal.
- RabbitMQ with domain topic permissions, separate consumer groups and durable bounded reject-publish queues.
- A non-root, loopback-only edge on **127.0.0.1:52500**. The legacy application on 52400 is unchanged.
- Short dependency probes plus liveness independent of database/broker availability.

Foundation liveness is not business readiness. Every service reports `phase: foundation` and `business_ready: false`. Unmigrated business routes return HTTP 503 `migration_not_ready`. Do not route the public domain to this stack yet.

## Windows 11

Install Docker Desktop with Linux containers/WSL2 and confirm `docker compose version`. Use the existing Python installation/virtual environment from this project. From the repository root:

```powershell
.\tools\microservices.ps1 Init
.\tools\microservices.ps1 Doctor
.\tools\microservices.ps1 Up
.\tools\microservices.ps1 Verify
.\tools\microservices.ps1 Status
```

`Init` creates random local service credentials in `deployment/microservices/.local`, protected by Windows ACLs. Re-running validates fingerprints and preserves the files. An incomplete/changed directory fails closed; do not delete credentials to repair an initialized database. Keep this directory with the corresponding volumes; credentials are not recoverable from a database backup alone. Salted broker definition hashes are also local and ignored by Git.

`Down` removes only this Compose project's containers/network, keeping its named volumes and local state. Never run `down --volumes` on an installation containing data as an upgrade step. `start.bat` continues to run the existing app separately.

The doctor reports OS/CPU, Docker allocation, a bounded local model snapshot and **unverified** capacity/cold-boot gates. It is read-only and never certifies model peak RAM or unattended startup from a single snapshot. Use `-ModelUrl http://192.168.1.10:11434` only for an existing private model server. No prompts, tokens or model settings are changed. The diagnostic accepts only a private server root and refuses redirects to keep requests within the validated endpoint.

A Windows cold boot without interactive login, Docker recovery and real peak-model-memory/load tests remain mandatory before production use. Docker health checks report health; they do not automatically restart an otherwise running unhealthy process. Process exits follow the Compose restart policy. Do not use automatic Windows login or Docker socket mounts as a recovery workaround.

## Initialization diagnostics

`Init` safely initializes a missing or completely empty `.local` directory. Re-running it preserves and validates an existing installation. Repository paths containing spaces are supported.

On Windows, the launcher repairs owner/SYSTEM access before reading existing state and applies explicit ACLs to newly generated files. It does not change file ownership or credential contents. Empty file ACLs can otherwise prevent reading a manifest even when its parent folder grants Full Control.

If initialization fails, the JSON output includes a specific `code`, explanation and recovery `hint`. Filesystem failures also report the operation and numeric OS error codes without file contents or credential values. A populated directory without `manifest.json` reports `state_manifest_missing`; changed files report `state_files_changed`. Restore the matching state backup rather than deleting `.local` or generating new passwords for existing database/broker volumes. Never paste credential files into chat or logs.

## Linux/development equivalent

```sh
python -m mailcheck.services.manage init
export OFFERPATH_CONTAINER_UID="$(id -u)" OFFERPATH_CONTAINER_GID="$(id -g)"
# Fresh disposable service databases only; never point this at the existing app.
docker compose -f deployment/microservices/compose.yaml up --build -d --wait --wait-timeout 180
docker compose -f deployment/microservices/compose.yaml --profile tools run --rm verify
python -m mailcheck.services.verify_stack
```

The Linux UID/GID override lets non-root containers read owner-only secret files even when the host user is not UID 1000. Windows uses the launcher ACLs and the default container UID. Only the edge port is published. Database/broker/model ports are not. The edge's API network cannot reach the database network. Provider/model egress is reserved for the Mail/Intelligence runtimes; Core's infrastructure traffic stays on internal networks.

Role provisioning is a one-shot job with admin credentials. Migrations run in a separate one-shot job with domain migration credentials. Persistent runtime containers receive only their own application/broker files and cannot create tables or connect to another domain database. Generated service credentials are unrelated to production email/user credentials.

## Health and failure checks

- `GET /platform/live`: edge liveness (204).
- `GET /platform/core/live`: Core liveness, independent of dependencies.
- `GET /platform/{core,mail,intelligence}/dependencies`: connectivity/schema/all-owned-queue probes; 200 or sanitized 503.
- Any business path, including `/api/bootstrap`: explicit 503 migration state.

The edge resolves backend container names dynamically, avoiding permanent stale addresses after replacement. Dependency probes have short deadlines. Do not confuse dependency readiness with complete queue-binding/tenant/business correctness; the integration suite and future domain contracts cover those separately.

## Tests

Ordinary tests run without PostgreSQL/RabbitMQ or optional client packages. To run integration tests, install `pip install -e '.[services]'` and set `OFFERPATH_TEST_STACK` to an **ignored, disposable test-stack JSON** containing `host`, loopback-only `postgres_port`, `broker_port`, and the absolute `secrets` directory generated by `Init`. Initialize its isolated roles with `provision_domains` and run migrations. Never supply production addresses or credentials. Run:

```sh
OFFERPATH_TEST_STACK=/absolute/path/to/disposable-stack.json python -m pytest tests/test_service_postgres.py tests/test_service_broker.py -q
```

Tests verify migrations, runtime DDL denial/cross-domain isolation, rejection of elevated replication privileges, missing secondary consumer queues, reverse transaction ordering, replay retention, duplicate identity, atomic consumer rollback, outbox acknowledgement/retry, broker fanout/topic isolation and unroutable publication. The deployment test checks loopback port/secret isolation from the rendered Compose configuration. The service-foundation CI workflow builds and starts the isolated stack, verifies actual edge/dependency responses, and runs the real database/broker contracts. Its `compose.test.yaml` override publishes database/broker ports on loopback for disposable integration tests only; never include that override in a production startup.

Image builds keep TLS verification enabled. A corporate/session build CA can be supplied as an optional BuildKit secret named `proxy_ca`; it is mounted only for pip, not copied into image layers. The default deployment does not require this override.

## Remaining phases

Core auth/business persistence and SQLite importer; Mail/OAuth/Windows keyring migration; provider watches and durable scheduler; Intelligence execution and accepted-fact projections; authenticated SSE/client integration; capacity and cold-boot rehearsal; then an explicitly controlled data cutover/rollback rehearsal. The foundation deliberately does not simulate these features with empty successful responses.
