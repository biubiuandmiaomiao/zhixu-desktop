# Zhixu 0.3 before-change audit

Date: 2026-10-25. Baseline: `3077d78f54f81c8608dba2f6cf02edb3befbd2d7` in `D:\rea-tools\video-knowledge-desktop`.

This is a source/test audit of the approved single-user learning workflow, not an Obsidian plugin/cloud parity assessment. No REA session was used by this worker because the independent Obsidian investigation owns that shared session. Evidence below is explicitly static source inspection or an isolated executable probe. No production code, normal application data, credentials, or machine environment was changed. No real online model was invoked. Source references are to the baseline, before other workers' changes.

## Implemented versus absent

| Area | Observed baseline behavior | Missing or limited behavior | Evidence |
| --- | --- | --- | --- |
| Markdown import/export | Native open/save dialogs; UTF-8 Markdown body survives an ordinary import/export. SQLite is authoritative. | Export contains only the body; no stable document/source IDs, source URL, raw evidence, timestamps, attachments, tags, or relationships. Reimport creates new IDs. No directory/vault import or external-file watcher. | `D:\rea-tools\video-knowledge-desktop\desktop\main.cjs:93-108`; `D:\rea-tools\video-knowledge-desktop\backend\knowledge.py:57-65`; `D:\rea-tools\video-knowledge-desktop\backend\store.py:95-109` |
| Markdown reading | Headings 1–4, bold, inline/fenced code, bullet-like paragraphs; raw HTML is escaped. | Ordinary Markdown links, images, tables, blockquotes, nested lists, task lists and heading anchors do not render as their respective structures. | `D:\rea-tools\video-knowledge-desktop\src\main.ts:48-59` |
| Wiki links/backlinks | Separate application document-relation records exist. | `[[Note]]`, aliases, heading/block links and Markdown note links have no resolver or reverse-link index. A relation suggestion is not a textual backlink. | Renderer `D:\rea-tools\video-knowledge-desktop\src\main.ts:48-59`; complete baseline schema `D:\rea-tools\video-knowledge-desktop\backend\store.py:40-76`; dispatch `D:\rea-tools\video-knowledge-desktop\backend\service.py:21-94` |
| Source references | UUIDs for documents/segments; original segments survive AI tutorial generation. QA/quiz citations and relation evidence can open an original passage. Imported subtitles retain grouped start times. | `[来源:UUID]` inside tutorial body is plain text, so the main reading flow cannot follow its own citation. Export/reimport loses the UUID-to-original mapping. Only grouped starts, not subtitle end times, are stored. | `D:\rea-tools\video-knowledge-desktop\backend\knowledge.py:42-49,99-116,204-213`; `D:\rea-tools\video-knowledge-desktop\src\main.ts:112,121-122,137-138,284-285`; schema `D:\rea-tools\video-knowledge-desktop\backend\store.py:47-49` |
| Tags/search/favorites | Chinese-bigram/Latin-token SQLite FTS search, optional mem0 recall with notice, favorite text and source-segment favorites, favorite-only quiz scope. | No tag field, parser, editor, tag list or tag filter. Displayed selection can silently be excluded from favorites quiz; see F1. No UI search filters beyond the submitted query and result limit of eight. | `D:\rea-tools\video-knowledge-desktop\backend\store.py:21-31,149-189,243-268`; `D:\rea-tools\video-knowledge-desktop\backend\knowledge.py:118-143`; `D:\rea-tools\video-knowledge-desktop\src\main.ts:181-182,266-270,288` |
| Relations/graph | Shared concept, directional prerequisite, supplement and difference suggestions with evidence; accept/reject persists. | No manual relation creation UI; no graph view; no normalized concepts/aliases/knowledge-point aggregation page. | `D:\rea-tools\video-knowledge-desktop\backend\store.py:211-241`; `D:\rea-tools\video-knowledge-desktop\backend\knowledge.py:145-180`; `D:\rea-tools\video-knowledge-desktop\src\main.ts:125-128` |
| Video acquisition | Validates full Bilibili BV URLs. yt-dlp requests metadata and first supported subtitle, prioritizing Chinese. Failure is persisted and does not create a fake successful document. | No short-link expansion/AV links, cookie/login UI, local media input, audio download/ASR fallback, or alternative-candidate retry. Manual subtitle picker does not ask for the original video URL, so that fallback loses navigable video provenance. | `D:\rea-tools\video-knowledge-desktop\backend\knowledge.py:11-16,67-97`; `D:\rea-tools\video-knowledge-desktop\desktop\main.cjs:93-99`; `D:\rea-tools\video-knowledge-desktop\src\main.ts:188-189,286,308` |
| Local video/audio ASR | None. yt-dlp is already installed. | No RPC, native file filter, backend transcriber, model setting/cache, cancellation or progress. FFmpeg exists system-wide but is not bundled in the app. App venv lacks both Whisper packages checked. | Baseline action whitelist `D:\rea-tools\video-knowledge-desktop\desktop\main.cjs:20-22`; backend dispatch `D:\rea-tools\video-knowledge-desktop\backend\service.py:21-94`; import implementation `D:\rea-tools\video-knowledge-desktop\backend\knowledge.py:67-97`; dependency checks below |
| Screenshots/timecode links | Source/citation modal can launch HTTPS Bilibili URL with `t=floor(start)` externally. | No local player, screenshot extraction/capture, image asset management or image renderer. Source time links are unavailable after body-only export/reimport or manual subtitles without URL. | `D:\rea-tools\video-knowledge-desktop\src\main.ts:112,200,285`; `D:\rea-tools\video-knowledge-desktop\desktop\main.cjs:110-114`; renderer `D:\rea-tools\video-knowledge-desktop\src\main.ts:48-59` |
| Tutorial styles/formats | One Chinese Markdown tutorial prompt: overview, sections, source-supported steps, concepts, exercises; reads personal preferences. Guards length and source IDs. | No selected style/detail/language, concise/detailed/outline modes, transcript export or configurable output format. A repeated generation overwrites current body; per-section evidence is requested by prompt but not enforced beyond existence/validity of cited IDs. | `D:\rea-tools\video-knowledge-desktop\backend\knowledge.py:99-116`; `D:\rea-tools\video-knowledge-desktop\src\main.ts:114,293`; `D:\rea-tools\video-knowledge-desktop\backend\store.py:127-147` |
| Version history | Original video/AI tutorial source segments are retained. User preference records have superseded versions. | Document bodies have no revision table, hashes, saved Markdown paths, history UI or restore action. Plain-text edits replace raw segments and invalidate dependent quiz/QA. README accurately admits lack of complete restoration UI. | `D:\rea-tools\video-knowledge-desktop\backend\store.py:40-76,127-147,191-205`; `D:\rea-tools\video-knowledge-desktop\README.md:32` |
| Durable tasks | Video job stores kind/payload/status/error; interrupted `running` jobs are marked failed at startup. | No stages/attempt count/idempotency key, resume/retry dispatch, or job-list UI. Retry currently means starting another import manually. | `D:\rea-tools\video-knowledge-desktop\backend\store.py:311-323`; `D:\rea-tools\video-knowledge-desktop\backend\service.py:12,31`; `D:\rea-tools\video-knowledge-desktop\src\main.ts` has no job rendering/use |

Scope distinction: global graph was explicitly deferred in `D:\rea-tools\video-knowledge-desktop\docs\design.md:55`; first-preview ASR deferral was explicitly recorded in `D:\rea-tools\video-knowledge-desktop\docs\progress.md:5`. Absence is not evidence that those were falsely advertised as delivered. The newer competitor-comparison request can prioritize a bounded graph and practical ASR, but should not imply full Obsidian parity. Screenshot support, document versions and durable recovery appear in the original broader design yet were not delivered by preview 0.3; source-preserving Markdown roundtrip is necessary to carry the current learning workflow between installations but was not separately specified by the original import/export requirement.

## Reproduced defects and misleading outcomes

### F1 — Favorites can be saved successfully but excluded from favorite-only review (high priority)

The reader uses rendered selection text and sends only `document_id` and `text` (`D:\rea-tools\video-knowledge-desktop\src\main.ts:266-270`). `sample_sources('__cards__')` requires either a segment ID or the entire selected string to be a substring of one original segment and silently skips anything else (`D:\rea-tools\video-knowledge-desktop\backend\store.py:248-251`).

Reproduced on original Markdown with bold markup removed by display, on a generated tutorial paraphrase, and on a favorite whose original text is later edited. A long selection spanning 900-character segmentation boundaries is also vulnerable by inspection. The UI success toast says the original source is retained, while a valid favorite may provide no review evidence. A favorites-only quiz then reports fewer than 200 source characters (`D:\rea-tools\video-knowledge-desktop\backend\review.py:77-79`). Existing `test_favorites_scope_uses_only_saved_excerpts` supplies an explicit segment ID, so it does not cover the real selection flow.

Minimal executed reproduction, only temporary SQLite:

```python
import tempfile
from backend.store import Store
with tempfile.TemporaryDirectory() as directory:
    store = Store(directory)
    doc = store.add_document('Markdown', '**闭包**捕获外部变量。' * 40)
    store.add_card(doc['id'], '闭包捕获外部变量。' * 20)
    assert len(store.cards()) == 1
    assert store.sample_sources('__cards__') == []
    store.close()
```

For the generated case, create an original source, call `update_document(..., preserve_sources=True)` with a cited paraphrase, then save that displayed paraphrase without `segment_id`: the same empty result occurs. Do not repair this by silently treating AI paraphrases as original facts. Keep the selected excerpt, its rendered/document revision origin, and the underlying original evidence distinct. If mapping is unresolved, show that condition and a direct way to anchor it instead of silently omitting the favorite.

### F2 — Tutorial Markdown roundtrip retains citation tokens but loses their evidence (high priority)

The exporter writes exactly `data.document.content` (`D:\rea-tools\video-knowledge-desktop\desktop\main.cjs:107`). The importer interprets it as new plain text and invents new segment IDs; it has no frontmatter/source schema. A tutorial exported and imported elsewhere therefore displays apparently precise `[来源:old UUID]` text, but none of those tokens resolve to the imported source. Source URL and source times are also discarded.

Minimal executed reproduction using the same body that the native exporter writes:

```python
import re, tempfile
from pathlib import Path
from backend.store import Store
from backend.knowledge import Knowledge
from backend.provider import Provider
with tempfile.TemporaryDirectory() as directory:
    store = Store(directory)
    raw = '闭包保存外层变量。' * 40
    doc = store.add_document('视频', raw,
        'https://www.bilibili.com/video/BV1xx411c7mD/', kind='subtitle',
        segments=[{'text': raw, 'start': 72.5}])
    source_id = store.segments(doc['id'])[0]['id']
    body = '# 教程\n\n闭包示例。\n\n[来源:' + source_id + ']'
    store.update_document(doc['id'], doc['title'], body, preserve_sources=True)
    path = Path(directory) / '视频.md'
    path.write_text(store.document(doc['id'])['content'], encoding='utf8')
    restored = Knowledge(store, Provider({}), None).import_text(
        path.stem, path.read_text(encoding='utf8'))
    refs = re.findall(r'\[来源:([^\]]+)\]', restored['content'])
    ids = {s['id'] for s in store.segments(restored['id'])}
    assert refs and all(ref not in ids for ref in refs)
    assert restored['url'] == ''
    assert all(s['start'] is None for s in store.segments(restored['id']))
    store.close()
```

A repair should define a documented portable Markdown metadata/source format, preserve literal user frontmatter when possible, and decide ID collision/upsert behavior. A valid exported tutorial should remain readable outside this app and be restorable in a second isolated store with functioning citations/time links. Do not assume retaining the Markdown body alone is a knowledge roundtrip.

### F3 — Editing ordinary text leaves favorites without their original evidence (high priority)

`D:\rea-tools\video-knowledge-desktop\backend\store.py:138` deletes all old segments; foreign-key `ON DELETE SET NULL` at line 53 clears each favorite's source ID. The favorite text remains but its original evidence is gone and the UI offers only the current whole document. An isolated executed probe confirmed: old favorite is retained, `segment_id` becomes `None`, old text is absent from all new segments, and the favorite cannot be sampled unless it coincidentally matches new content. Retaining revisions/source snapshots would make preservation truthful and prevent stale favorites from being presented as current-document evidence.

### F4 — mem0 initialization can fail before the app's transport adapter is installed (environment-triggered)

Default-environment `python -m unittest discover -s tests -v` produced 38 passes, 2 failures and 14 errors. All failing paths lead through placeholder OpenAI SDK construction in `D:\rea-tools\video-knowledge-desktop\backend\mem0_engine.py:113-120`, before adapters are assigned. `httpx` parses inherited proxy exclusions and raises `InvalidURL: Invalid port: ':1]'`. The two generation failures then observe zero learning-memory count because their fallback path suppresses the init error.

Repeating the exact 54 tests with only proxy-related environment variables removed inside the child Python process passed all 54 in 40.438 seconds. No machine environment changed. This isolates an incidental SDK-construction dependency; it is not evidence that the real provider transport cannot use proxies. Avoid changing user transport behavior just to construct an unused placeholder SDK client. The root worker is addressing this separately.

## Focused acceptance tests for the next change

1. **Favorite provenance:** Exercise actual displayed selections from formatted Markdown, a span across chunk boundaries, and a cited generated tutorial. Save, restart, reopen source, and generate favorites-only review. The chosen excerpt must not disappear; its generated/original status must remain visible and factual questions must retain original supporting evidence. After source edit, either resolve against a retained revision or mark it stale with a clear resolution action.
2. **Portable Markdown:** Export a tutorial with nonzero video start, two source IDs, user frontmatter, tags, wikilinks and an image. Import into a second fresh temporary store. Check title/body and safe metadata, stable or explicitly remapped citations, correct source URL/time, asset availability, and no unresolved references. Reimporting the same app-exported ID must not silently duplicate or overwrite changed notes.
3. **Markdown navigation:** Render a heading anchor, note link, alias, `[HTTPS](...)`, image and table while escaping/rejecting executable HTML and unsafe URL schemes. Clicking a tutorial `[来源:ID]` must open the exact original segment and time. Clicking `[[B]]` from A must open B; B must show A as backlink; rename B without losing links, and show missing/ambiguous targets explicitly.
4. **Version recovery:** Save/edit/generate at least three bodies; restart; inspect and restore an earlier revision. Restoring must record a new revision and keep original sources, card provenance, derived-memory validity and quiz invalidation behavior consistent.
5. **Video fallback:** Inject yt-dlp metadata where the first Chinese subtitle fails but a later candidate works. Separately return no subtitles and choose a local audio/video file. Verify meaningful state/error, real transcript starts and original URL provenance. A manual subtitle fallback must let the user attach the video URL. No test should need login cookies or real online models.
6. **ASR/screenshots:** Generate a tiny synthetic local clip with FFmpeg; run media inspection and screenshot extraction at a known second, ensuring the captured file is rendered/exported and a time link seeks correctly. For ASR use an explicitly installed model and record that identity; a fake transcript can test dispatch but cannot establish recognition quality. Distinguish absent-model/setup errors from successful transcription.
7. **Tags/graph:** Import/edit nested tags and filter notes by tag. A small graph can be a view of resolved note links plus confirmed relations; filters and clicks should resolve to the same document IDs. Rejected AI suggestions should not become factual confirmed edges. Do not gate the core workflow on a full concept ontology.
8. **Task recovery:** Interrupt a local task between acquisition and processing, restart, show its persisted state, retry it, and verify one document/result rather than duplicate assets. Model/network failure must preserve already acquired source data.

## Verification performed and local prerequisites

- **Baseline suite:** 54 tests executed with default inherited environment: 2 failures/14 errors, all downstream of the proxy-parser issue described in F4. With child-process-only proxy variables cleared: **54/54 passed**. These tests use temporary stores and injected/local model fixtures. Warnings correctly report optional spaCy/fastembed absence. No paid/real online model calls were made.
- **Desktop paths:** `node --test tests\paths.test.cjs`: **4/4 passed**.
- **Source probes:** Executed TemporaryDirectory-only probes confirmed F1, F2 and F3; interrupted job recovery changes status to `failed`, not resumed work. These probes were passed over stdin and did not add production/test implementation files.
- **Actual renderer function:** Evaluated the unchanged `markdown` function from `src\main.ts` in a Node VM with the same escaping behavior. Asserted no `<a>`, `<img>` or `<table>` for corresponding Markdown; wiki/source link syntax remains literal; raw `<script>` stays escaped. This is executable function evidence, not a full Electron UI test.
- **Available:** `.venv\Scripts\python.exe`, Node, Electron/Playwright dependencies, `yt-dlp==2026.10.21`, `qdrant-client==1.20.0`, `mem0ai==2.2.1`; native `C:\Program Files\ffmpeg\bin\ffmpeg.exe` and `ffprobe.exe`, version `2025-06-26-git-09cd38e9d5-full_build-www.gyan.dev`.
- **Absent from the app venv:** `faster_whisper`, `whisper`, `imageio_ffmpeg`. No ASR model was downloaded or searched in user directories. System FFmpeg availability does not prove a packaged copy exists or that ASR is usable.
- **Absent from package dependencies / checked node_modules locations:** `markdown-it`, `marked`, `dompurify`. The renderer is currently handwritten; choose and pin any new rendering dependency deliberately, or keep a tightly tested safe local implementation.
- **Not repeated:** Broad Electron smoke, packaged-product behavior and real Bilibili/model access. Prior docs record them, but this worker did not independently observe those claims. The root/other workers own competitor REA evidence and runtime observation.

## Recommended implementation order

First preserve and make sources navigable: repair favorite mapping, add document revisions, make tutorial citations clickable, and define Markdown roundtrip. Then complete ordinary Markdown links/images/tables, resolved note links/backlinks and tags. Add bounded media acquisition/local-file transcription and timestamped screenshot assets with honest prerequisite/progress states. A compact local graph is useful after links are canonical, but its absence does not invalidate the originally approved first preview. Keep cloud sync, collaboration and Obsidian plugin compatibility outside this personal workflow.
