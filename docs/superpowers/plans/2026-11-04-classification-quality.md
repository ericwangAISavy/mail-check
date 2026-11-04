# Classification Quality Implementation Plan

> For agentic workers: use superpowers:executing-plans to implement task by task.

Goal: protect interview recall and application receipt precision with reversible changes.
Architecture: retain model and category IDs; harden prefilter, bounded evidence, prompt and result acceptance. No historical reclassification or data migration.
Tech Stack: Python, pytest, existing Ollama client.
Spec: docs/superpowers/specs/2026-11-04-classification-quality-proposal.md (approved).

## Global Constraints
- Rollback baseline: 496f48a, tag rollback/classifier-before-quality-2.13.2.
- Preserve configured body character budget, credentials, stored labels and checkpoint protections.
- Model accuracy requires actual inference; synthetic plumbing checks are not accuracy measurements.

## Review Focus
- Shared alert sender carrying a real receipt/interview must reach model.
- Interview advice and invitations to apply must not become receipts/interviews by keyword alone.
- Old quoted invitations must not override current rejection.
- Missing/invalid result fields must not become confident saved classifications.
- Rollback must restore code without destructive reset or data rewrite.

## Tasks
- [x] Add failing regression tests for sender evidence, exact categories, bounded long/calendar/sparse quote context and incomplete model output.
- [x] Implement conservative noise rules, context selection and explicit prompt precedence; version prompt.
- [x] Validate complete model responses with bounded retry and manual-review fallback, preserving busy/deadline behavior.
- [x] Add labelled synthetic evaluation corpus and opt-in current-model evaluator; record measured limitations.
- [x] Run complete suites, independent review, patch release/build; commit/push changes and rollback tag.

## Execution ledger
Plan approved via user's go-ahead. Execute inline in existing feature branch.

Regression cycle: original suite showed 13 failing new cases; those now pass.
Extra review cases reproduced partial-summary acceptance and short-decision quote
contamination; fixed with original-object completeness checks and quote guards.
Ruling: model endpoint absent — provide reproducible synthetic evaluator instead
of inventing before/after accuracy; live quality and latency remain unmeasured.
Ruling: no numeric confidence threshold without evidence — use explicit needs_review
signal; quality depends on model following that instruction.
Ruling: keep stored labels across prompt upgrades — existing mislabels remain until
separately approved reclassification, preserving rollback/data requirements.
Independent reviewer completed; both important findings fixed. Baseline evaluator
now allows historical marker overhead. Context-dependent corpus subjects are neutral.

Final verification: 639 backend tests + 84 subtests, 337 frontend tests passed;
production build and release consistency checks passed. The initial full suite
found a tiny-budget truncation-marker regression; fixed and final suite is green.
29 focused quality tests pass. Both baseline/current 26-case corpus validation
commands pass. Known existing Starlette deprecation and Vite chunk-size advisories
remain nonblocking. No minor findings deferred. Single commit with release2.13.3;
rollback baseline tag is published with the branch. Live inference is unmeasured.
