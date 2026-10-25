---
title: Preserve notebook source identity through history and portable export
type: decision
status: open
decided: 2026-10-25
project: main
---

# Preserve notebook source identity through history and portable export

The user authorized REA comparison with BiliNote and Obsidian and implementation of missing personal-learning workflows. Static/runtime evidence exposed the need for explicit links, notebook revisions and source-preserving favorites/export. Semantic similarity alone cannot establish that an old link still names the same source.

SQLite remains canonical for original segments, explicit notebook links, revisions, tombstones and portable provenance. Native mem0 retrieves knowledge and learning events; it does not replace deterministic link resolution. A link binds to the first proven target identity, which remains distinct from its current title or export path. Restoring a version or importing a cohort must retain that identity, including deleted or missing targets. Legacy history without proof reports history_unknown rather than guessing. Imports create fresh document/source IDs and remap only proven imported identities; they do not overwrite existing notes.

Name-only resolution on every read was rejected because deleting B and creating an unrelated new B would silently rewrite history. Putting all references in mem0 was rejected because approximate recall cannot enforce exact identities, deletions and source scope. Copying raw old IDs without cohort remapping was rejected because imported notebooks would point outside their copied material. Plain Markdown without portable provenance remains importable, but cannot promise original citation identity.

The cost is additive schema and bounded metadata validation. Stable behavior is covered by cohort, self-link, ambiguity, deletion/restore, portable export, 8.2 MB Chinese and 10,001-caption regressions. Full body/source snapshots remain recoverable, while UI version previews are bounded in SQL. The checked-in audit, design and implementation plan are authoritative; ignored machine-local REA bundles supplement them.

## Observations

- [decision] Separate deterministic notebook/source identity from semantic mem0 retrieval; preserve explicit identity through history and export.
- [consequence] Deleted or unverifiable historical links remain unresolved instead of silently targeting new same-name material.
- [verification] Full 123-test backend suite and independent probes pass; actual packaged source roundtrip retains 10,001 segments and their timestamps.

## References

- docs/audits/2026-10-25-feature-parity.md
- docs/superpowers/specs/2026-10-25-rea-feature-parity-design.md
- backend/notebook.py, backend/store.py, backend/media.py and tests/test_notebook.py
