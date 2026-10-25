# REA Feature Parity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use subagent-driven-development for independent notebook/media modules; root integrates desktop, renderer, evidence and final review. Preserve user authorization to implement directly without another permission round.

**Goal:** Verify BiliNote/Obsidian using actual REA evidence, then close the personal-learning workflow gaps in Zhixu.

**Architecture:** SQLite remains canonical. Notebook and media ingestion have separate bounded modules; links and source provenance remain distinct from mem0 semantic recommendations. The renderer consumes explicit scoped APIs, and file reads/writes stay behind native dialogs and managed paths. Media tasks run asynchronously, with independent SQLite connections and durable progress.

**Tech Stack:** Electron/TypeScript, Python/SQLite, mem0 2.2.1, REA 6.7, safe Markdown rendering, FFmpeg and faster-whisper CPU.

## Task 1: Evidence and regression baseline

- [x] Inventory/analyze local Obsidian 1.14.5 via REA; export evidence and report.
- [x] Analyze current Zhixu shipped ASAR via REA; audit source and reproduce broken favorites/portable citations with temporary data.
- [x] Analyze verified BiliNote 2.4.5 package/runtime and save version/digest/Evidence-backed findings.
- [x] Fix inherited-proxy initialization regression with a focused failing native-mem0 test, leaving machine environment unchanged.

## Task 2: Notebook backend and provenance (independent worker)

Files: backend/notebook.py, backend/store.py, tests/test_notebook.py; no renderer/service/media edits.

- [x] Reproduce missing link/backlink/tag/bookmark/version APIs and favorite-source/portable-export defects as failing tests.
- [x] Implement source-preserving cards and portable import/export; explicit stale-source behavior; active link/tag indexes, source-aware revisions, bookmarks, and bounded graph.
- [x] Expose documented store.notebook methods and extend add_card with validated source_ids. Run focused tests and original store/review/reliability tests.

## Task 3: Media backend (independent worker)

Files: backend/media.py, tests/test_media.py; root owns service/knowledge/desktop integration.

- [x] Test path admission, progress/retry, FFmpeg screenshots/timecodes and transcript/source persistence before implementation.
- [x] Implement asynchronous managed-media jobs, caption-first Bilibili ingestion and local faster-whisper fallback, managed frames and cancellation. Define start/status/retry/assets interfaces for root.
- [x] Verify with temporary generated media and fake ASR at the external model boundary; perform a separate real local ASR check when dependencies/model are available.

## Task 4: Desktop and renderer integration (root)

Files: backend/service.py, backend/knowledge.py, desktop/main.cjs, desktop/preload.cjs, desktop/paths.cjs, src/main.ts, src/style.css, safe Markdown helper and smoke scripts.

- [x] Add safe native note/vault/media import/export and managed-asset APIs; renderer cannot supply arbitrary filesystem paths. Add documented --data-dir profile support for isolated runtime audits.
- [x] Replace limited renderer with sanitized Markdown links/images/tables and safe source/wiki buttons. Add backlinks/tags/bookmarks, graph, version history/restore, media progress/retry and style selectors.
- [x] Preserve citations, quiz answer isolation, mem0 deletion/version rules and direct personal preferences.
- [x] Extend UI regression to roundtrip provenance, displayed favorites, links/backlinks/tags/graph, media tasks and version restore.

## Task 5: Review, package and actual REA runtime verification

- [x] Install and lock necessary dependencies and model in D-managed locations; include runtime dependencies and licenses in Windows build as needed.
- [x] Run all relevant tests and real media checks; review independently and fix material findings.
- [x] Back up business DB, build backend/renderer and Windows package; run full packaged smoke in isolated profile.
- [x] Capture declared runtime scenarios with REA against the updated app; export evidence. Update feature matrix with coverage and remaining limits.
- [x] Commit changes, reopen existing desktop shortcut and provide a concise truthful completion report.

Review focus: source authority during favorites/revisions/import, no arbitrary file reads or unsafe HTML/actions, duplicate/ambiguous wiki targets, accurate graph provenance, background SQLite/thread lifecycle, task cancellation/retry, environment proxy isolation, no invented media content and no user-credential model tests.
