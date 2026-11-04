# OfferPath release tracking

Version history starts at 2.1.0. Read the latest entry in releases.json for the current version; do not use a fixed historical baseline.

For future changes to runtime features or behavior:
- Automatically add a release before completing the task, without asking for version-update confirmation. New backward-compatible features use a minor bump; fixes, performance improvements, and behavior corrections use a patch bump. Breaking changes use a major bump. An explicit user version takes precedence.
- Run `python tools/release.py minor --title "Short title" --note "User-facing change"` (or patch/major). Use multiple --note arguments for several changes. Bump once per completed change, not once per edited file or commit. Do not bump again for a commit/push-only request.
- The command updates releases.json, Python/frontend versions, the npm lockfile, and docs/CHANGELOG.md together. Do not edit generated CHANGELOG.md by hand or rewrite published entries.
- Run `python tools/release.py --check`, relevant tests, and the frontend production build when UI/release history changes. Include regenerated frontend_dist files in the same commit.
- Documentation/test-only changes need no bump unless runtime behavior also changes.
- Never modify application databases, stored statuses, credentials, or user settings to update an application version.

When restoring an older implementation for commit/push, preserve published Git and release history and record the restoration as a new patch release above the latest published version, unless the user explicitly requests a historical version number or history rewrite. Keep the requested checkpoint behavior while retaining the release metadata needed for the new version.
