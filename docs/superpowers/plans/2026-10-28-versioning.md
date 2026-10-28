# OfferPath Versioning Plan

**Goal:** Establish the user-selected 2.1.0 baseline, show update history beside the brand, and keep future versions and notes synchronized.

**Approach:** One releases.json feeds the React viewer and generated changelog. A standard-library release command updates Python/frontend/lockfile versions together. Build checks validate consistency; GitHub checks require bumps for future runtime changes. Persistent AGENTS.md explains minor/patch/major choices. No database changes.

- [x] Add release history and a brand version button with accessible dialog.
- [x] Synchronize all metadata at 2.1.0 and generate CHANGELOG.md.
- [x] Add release command, persistent contribution rules, and build/CI checks.
- [x] Verified release bumps, stale metadata/history rejection, UI interaction, production build, 402 backend tests plus 76 subtests, and 231 frontend tests.
