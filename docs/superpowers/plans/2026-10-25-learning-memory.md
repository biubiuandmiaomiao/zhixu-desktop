# Unified Learning Memory Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Read personal preferences directly before generation and use real mem0 to recall source-backed relationships, completed review observations and historical questions.

**Architecture:** SQLite remains authoritative. Deterministic learning-event snapshots are embedded by native Memory.add(infer=False), while source concepts retain infer=True; native Memory.search retrieves event context separately from factual evidence. Canonical source/version checks, deletion and legacy-personal cleanup keep the index rebuildable.

**Tech Stack:** Python 3.11, mem0ai 2.2.1, local Qdrant/SQLite, Electron/TypeScript.

---

### Task 1: Direct preferences and legacy cleanup

Files: backend/mem0_engine.py, backend/knowledge.py, backend/review.py; tests/test_mem0_engine.py, tests/test_generation_context.py.

- [x] Add tests asserting no `personal:` sync entities, active-only preferences in `preferences` payloads for ask/tutorial/quiz, and native legacy personal vectors/messages/history removed after reopen while SQLite records remain.
- [x] Run `.venv/Scripts/python.exe -X utf8 -m unittest tests.test_generation_context tests.test_mem0_engine -v`; expected new assertions fail on personal indexing/current payloads.
- [x] Remove personal snapshots and semantic preference retrieval. Add offline cleanup of tracked personal entities at engine initialization. Use `self.store.memories()` for explicit preferences immediately before each relevant model call; prompts constrain them to presentation/learning context, never source facts or grading authority.
- [x] Run the same tests; expected preferences/cleanup pass. Commit the behavior with tests.

### Task 2: Source-backed event snapshots and native sync/recall

Files: new backend/learning_memory.py; backend/mem0_engine.py, backend/service.py; tests/test_learning_memory.py.

- [x] Test confirmed relations with evidence, completed per-question review observations with timestamp/score, and historical question-only entries. Reject drafts, suggested/rejected relations and nonexistent sources; exclude AI answer text.
- [x] Run `.venv/Scripts/python.exe -X utf8 -m unittest tests.test_learning_memory -v`; expected missing snapshot/recall interface fails.
- [x] Build snapshots keyed `relation:<id>`, `review:<session>:<question>`, `conversation:<id>`, with lane, entity_id, source_ids, document_ids and timestamp. Add these to mem0 entities; sync event text with infer=False, original knowledge with infer=True. Expose `learning_context(query, provider, source_ids)` returning canonical text and source IDs for completed versions only, using native lane/source filters before top-k. Sync only event lanes on generation requests, retaining the existing 24-item/budget limits.
- [x] Remove document-dependent event scopes before deleting/replacing original sources; prune invalid versions and rejected relations. Keep native message/history removal across all namespaces.
- [x] Verify actual native recall, keyword-free queries, source scope, restart/no duplication, failure retry, deletion and pending-version exclusion. Run task test module, then all Python tests. Commit.

### Task 3: Generation context and desktop visibility

Files: backend/knowledge.py, backend/review.py, backend/service.py, src/main.ts, scripts/smoke.cjs; tests/test_generation_context.py.

- [x] Add recording-provider tests verifying relevant learning memories reach QA/quiz, preferences remain available without Embedding, memory errors do not cancel generation, prior answers are not source evidence, and quiz answer/rubric isolation remains intact.
- [x] Run focused test module; expected missing generation context assertions fail.
- [x] Pass a bounded `learning_memories` list independently of `sources` and `preferences`. Ask may use recalled original source IDs to find evidence within requested scope; quiz restricts recalled context to chosen source IDs and does not send past correct answers. Return/display counts and notices, not hidden quiz answers. Update settings counts for knowledge/relation/review/conversation plus direct preference count; explain sync behavior. Extend local HTTP fixture assertions for preference payloads and all event lanes.
- [x] Run all Python tests, four Node path tests, `npm run build`, and development Electron smoke; expected pass. Commit.

### Task 4: Package, review and reopen

Files: package versions, README.md, docs/design.md, docs/verification.md, docs/progress.md, decision note.

- [x] Close the visible app through its normal window-close path, back up the business SQLite database, build PyInstaller backend and Windows directory app, and run smoke with `ZHIXU_EXECUTABLE` pointing to that EXE. Expected actual native event memory counts, preference-only local behavior, ten-question grading/restart/deletion pass.
- [x] Request independent review of this change range; fix actionable findings with regressions, rerunning affected checks. Preserve existing data and desktop shortcut.
- [x] Update accepted decision/verification docs, mark completed steps, check staged diff and commit. Reopen D:/桌面/知序.lnk and verify the visible window.

Review Focus: scope filtering before semantic top-k; no draft/AI-answer knowledge pollution; never use pending old vectors; canonical deletion across namespaces; legacy personal cleanup offline; question answers hidden from renderer until submission; preference text never affects score rules or factual authority.

## Execution record

User approved inline implementation. Task 1 committed as fc9d9e5 after 16 focused tests passed. Tasks 2 and 3 share snapshot/recall interfaces and were completed together; final 54-test suite and development smoke passed. Independent review found the optional-sync time-budget issue, reproduced at 360 virtual seconds, fixed with transport-enforced 20/10 s phase budgets and a 240 s operation deadline, then independently rechecked. Four Node path tests, pip check, renderer/backend builds, directory packaging and packaged smoke passed. Scope and complete-quiz deletion rulings are in docs/progress.md. Business DB backed up before upgrade; existing desktop shortcut retained. No live user model credentials were used.
