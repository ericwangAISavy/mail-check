# Paste deduplication and shared confirmations

**Goal:** Remove duplicate incoming job links and check every eligible row matching a confirmation's mailbox, company and role, including different job IDs, as explicitly requested.

**Design:** Reuse the server's existing incoming-row filters for clipboard, grid and CSV imports. Normalize known ATS job identities; BrassRing identity is partner ID plus job ID, independent of site ID and tracking. Preserve existing rows and keep distinct job IDs. Broaden role-qualified matches from one row to every candidate in the existing winning matching tier and date window. Share saved confirmation proof only when the existing binding still matches that candidate set. Company-only ambiguity, mailbox isolation, checked-row protection and date boundaries remain enforced.

**Approaches:** URL equality alone missed BrassRing variants. Deduplication by company/title would delete different jobs. Use ATS identity for deduplication and the user's chosen company/role rule for confirmation sharing instead.

**Implementation plan (inline execution):**

- [x] Add failing identity, paste, manual/global verification, saved-proof sharing and boundary regression tests.
- [x] Extend `sourcing_postings.specification` and `sourcing_filters.link_key` for shared ATS identity.
- [x] Broaden role-qualified plans in `sourcing_verification` and additive fallbacks; retain saved proof and deterministic earliest receipts.
- [x] Run sourcing, payment and activity regression tests; document the new behavior.
- [x] Add one minor release, run release checks and frontend production build.

**Verification:** Production application databases remain read-only. Tests use isolated databases, including reconstructed historical duplicates that bypass new paste filtering.

**Results:** 221 backend tests and 21 subtests passed; 43 focused frontend tests passed; production build and release checks passed for 3.28.0. Independent review found two edge cases (HTTP identity equality and explicit links blocking alias matches), both reproduced with failing tests and fixed. A read-only checkpoint replay matched both actual Kendra Scott rows, with zero database changes.
