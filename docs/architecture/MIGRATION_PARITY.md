# Full migration parity baseline

The user selected full PostgreSQL migration before cutover. The current production application remains the legacy implementation. This document does not authorize cutover or indicate that business APIs have been ported.

## Coverage evidence

`python tools/service_migration_inventory.py` reads source without importing or starting the application. The current baseline contains 154 literal route declarations and 63 literal persisted table definitions. Repeated declarations across gateway/worker apps are counted separately; router prefixes and runtime registration still need runtime tests. Four asset mounts and two router registrations are explicitly listed for manual review.

[MIGRATION_CONTRACTS.json](MIGRATION_CONTRACTS.json) assigns proposed service ownership and import dispositions. Every route is pending. The census test fails if routes/tables are added or removed without updating the disposition manifest. It does not prove behavioral compatibility or data migration correctness.

## Ownership and preservation

- Core: identities and authorization; workspace registry; bidders/assignments; sourcing; payments/deductions; normalized calendar/manual edits; pipeline; accepted Mail-derived reporting projections.
- Mail: accounts, provider checkpoints, message/action state, accepted classification history, outgoing/reply records and provider calendar collection state. The legacy `classifications` table is accepted inbox history; new Intelligence results are distinct versioned proposals that Mail accepts before publishing facts.
- Intelligence: inference snapshots/results, calendar analysis work and scan provenance. Legacy inference history must retain source/model/prompt provenance, including records also represented in accepted Mail history.
- All source tables are preserved by default. Existing active sessions are intentionally invalidated; password hashes, disabled-account state and bidder access rules are preserved. Deprecated data is not silently discarded merely because its UI is hidden.
- Plain backup ZIPs omit OS keyring secrets, Cloudflare credentials and model files. Import must identify reconnect-required accounts and configuration dependencies explicitly.
- IDs are scoped by workspace and import generation. Two workspaces with message/account/bidder ID 1 must never collide.

## Still required before implementation can be called usable

1. A runtime route/response contract fixture for the full browser API and all mounted routers.
2. Representative complete owner/two-admin backup fixtures and actual schema/constraint coverage, including lazy tables.
3. PostgreSQL repositories/migrations, validated resumable import and generation activation, and Core/Mail/Intelligence business implementations.
4. Authenticated live updates and an edge that serves actual migrated features without proxying to the legacy app.
5. End-to-end feature/data parity, dependency recovery, target-host capacity/cold-boot measurement and an operator-reviewed cutover/rollback rehearsal.

See the [implementation plan](../superpowers/plans/2026-11-11-full-postgresql-migration.md). `business_ready` stays false until these gates pass. Changing a launcher or readiness flag is not a substitute for implementing them.
