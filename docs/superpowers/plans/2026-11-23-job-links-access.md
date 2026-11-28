# Owner-controlled Job links access

Goal: the original owner always has Job links access; every other admin needs an explicit owner grant.

- [x] Store a per-admin permission in the control registry, defaulting existing and new admins to denied. Preserve owner access regardless of stored flag.
- [x] Extend the owner-only admin update operation and audit trail. Permission-only changes retain active sessions and do not stop workspace workers.
- [x] Enforce access for the page and API, including trailing-slash routes. Disable workspace-worker copies of the library endpoint so gateway checks cannot be bypassed. The original single-admin deployment remains owner accessible.
- [x] Add an owner-facing permission toggle in Admin management. Hide Job links navigation and block direct client routes for unauthorized admins. Refresh permissions for active sessions and discard cached library results after revocation.
- [x] Verify default denial, upgrade behavior, grants/revocations without re-login, self-grant rejection, immutable owner access, worker-route denial, UI controls, navigation, and cache cleanup. Run the relevant backend checks, frontend suite, production build, and release consistency check. Add one minor release.

No live application databases or credentials are edited during implementation. The normal startup migration installs the new control-registry permission when the updated server starts.

Verification: 108 backend regression checks passed, followed by six focused permission tests covering the review additions and upgrade behavior. All 601 frontend tests passed with TZ=UTC. TypeScript, production build, release consistency and source whitespace checks passed. An independent read-only review found no important permission defect. Live grants were not written during implementation.
