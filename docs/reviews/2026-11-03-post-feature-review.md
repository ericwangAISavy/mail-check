# Post-feature bug and performance review

Reviewed the 2.13.0 changes and fixed the following in 2.13.1:

1. Cell editors allowed clipboard events to bubble into whole-row handlers. Copying
   selected editor text returned TSV instead, and pasting could become a sheet
   operation. Editor copy/paste now retains native input behavior; spreadsheet
   clipboard actions still apply outside editors.
2. Collapsed bidder cards mounted all forms and account option lists, with DOM cost
   proportional to bidders times accounts. Each editor now mounts only on first
   expansion; visited editors stay mounted to retain their unsaved drafts.
3. Email masking missed international/quoted addresses and could expose prefixes
   around Unicode symbols. Matching now covers complete unquoted UTF-8 local parts,
   quoted locals and international domains. Rendering still retains the requested
   first/last character and domain. This remains display masking, not API redaction.
4. Every small save loaded all checked rows in the tab. Protection queries now use
   incoming row IDs in batches of 500 inside the existing write transaction. Tab
   isolation, initial checked pastes, noops and mixed-batch rollback are preserved.

## Performance evidence

A representative SQLite protection query with 20,000 checked historical rows used
160,024 VM steps previously, versus 38 with the bounded lookup. This measures that
query only, not end-to-end save latency. A deterministic regression also confirms
that unrelated checked history does not increase one-row protection work. The
regression fails against the original implementation. Another test constrains
SQLite to 501 parameters and verifies protection in later batches and full rollback.

## Validation

- 609 backend tests and 83 subtests passed.
- 330 frontend tests passed across 40 files.
- Production build and release consistency checks passed.
- Chromium exercised real editor text copy/paste, whole-row TSV copying, checked-row
  locking, unchecked editing, row-number deletion and ordinary link-click selection.
- Independent reviews covered clipboard propagation, lazy panel lifetime, masking
  edge cases, transaction safety and batching. Their concrete findings are addressed.

Tests used synthetic accounts and rows. No user data, credentials or real mail was
changed or sent. Existing Starlette HTTP client deprecation and Vite bundle-size
advisories remain nonblocking. No claim is made that testing proves the absence of
every possible defect.
