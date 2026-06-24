# quro-doc Data Flow

Data flow reference — write path, read path, asset flow, async pipeline, events, and traces.
For how-to procedures, see `../skills/`.

---

## Write Path

```
CLI / MCP call
     │
     ▼
ext/writer.py (PlainTextWriter or MarkdownWriter)
     │
     ├── file_path → read file content (writer.py)
     ├── body has media? → MarkdownMediaParser.extract()
     │   └── for each media URL → AssetPromiseModel.register()
     │       └── rewrite URL to asset://{id}
     │
     ▼
api.py:quro_doc_add(payload)
     │
     ├── validate required fields
     ├── protocol validator (JSON Schema)
     ├── determine doc_id (UUID or provided)
     ├── construct RawDocument from payload (model.py)
     │   └── RawDocument.new() → typed object with all fields
     ├── build storage metadata dict via doc.to_dict()
     │   └── exclude doc_id, body, context_files (non-persisted envelope keys)
     ├── write_raw_doc(doc_id, body, metadata)
     │   │
     │   └── storage.py
     │       ├── check existence (docs/ OR raw/)
     │       ├── write {doc_id}.txt (body)
     │       └── write {doc_id}.json (metadata)
     │
     ├── emit change event (best-effort)
     └── return {status: "accepted", doc_id}

Note: quro_doc_add does NOT enqueue jobs directly.
Job creation is handled at the Writer layer or by external callers.
```

## Read Path (Search)

```
quro_doc_search(query)
     │
     ▼
query_pipeline.py:search(query_dict)
     │
     ├── normalize query
     ├── check storage has docs
     │
     ├── _legacy_search_with_evidence()
     │   │
     │   ├── _small_retriever(q, top_k*2)
     │   │   └── vector_adapter.query_vectors() or []
     │   │
     │   ├── fallback: _raw_scan()
     │   │   └── scan docs/*.json + docs/*.txt for text match
     │   │
     │   ├── _score_hits() (if QUERY_USE_SCORING=true)
     │   │   └── ScoringEngine.score(query, doc, context)
     │   │
     │   ├── _rerank_hits() (if QUERY_USE_RERANKER=true)
     │   │   └── RerankerClient.rerank()
     │   │
     │   ├── _run_artifact_pipeline() (if artifact_store_enabled)
     │   │   └── ArtifactFeatureExtractor.extract() → RankingPolicy.evaluate()
     │   │
     │   └── _assemble(hits, top_k)
     │       └── format results: doc_id, score, snippet, tags, content
     │
     ├── view layer rendering
     │   └── if view="standard" → ViewLayerOrchestrator.render()
     │
     ├── trace capture (non-blocking)
     │   └── TraceStore.save(trace)
     │
     └── return results or rendered view
```

## Read Path (Direct Lookup)

```
quro_doc_get(doc_id)
     │
     ▼
storage.py:read_raw_doc(doc_id)
     │
     ├── _resolve_doc_path(doc_id)
     │   ├── check docs/{doc_id}.txt
     │   └── fallback raw/{doc_id}.txt
     │
     ├── read {doc_id}.txt
     └── read {doc_id}.json (metadata)
```

## Asset Flow

### Asset Write (via MarkdownWriter)

```
Markdown body
     │
     ▼
MarkdownMediaParser.extract(body)
     │
     ├── finds ![alt](url) and [text](url) links
     └── returns list[MediaRef]
     │
     ▼
AssetPromiseModel.register(url, type)
     │
     ├── SHA-256(url)[:24] → asset_id
     ├── writes .quro_context/assets/{asset_id}.promise.json
     └── returns AssetPromise
     │
     ▼
Writer rewrites URL → asset://{asset_id}
     └── only if promise status != "ready"
```

### Asset Read (via MarkdownReader)

```
quro_doc_get(doc_id)
     │
     ▼
_resolve_asset_urls(body)
     │
     ├── regex: asset://([a-f0-9]{24})
     └── replace with file path if exists on disk
```

### Asset Materialization (Async)

```
Worker pops materialize_asset job
     │
     ▼
run_materialize_pipeline_for_assets()
     │
     ├── read asset promise
     ├── download from source URL (HTTP/file)
     ├── write to {root}/assets/{asset_id}
     ├── update promise status → "ready"
     └── notify CrawlerProtocol callbacks
```

## Async Pipeline Flow

```
Worker (workers/worker.py)
     │
     ├── poll Redis list "quro_jobs"
     └── fallback: scan jobs/ directory
     │
     ▼
process_job(job)
     │
     ├── resolve storage root for project
     └── _run_tasks(doc_id, tasks)
         │
         ├── "index" → run_index_pipeline(doc_id)
         │   └── chunk → embed → write to vector store
         │
         └── "materialize_asset" → run_materialize_pipeline_for_assets(doc_id, assets)
             └── download assets, update promise status
```

## Trace Capture Flow

```
Every search automatically captures a Trace (best-effort, non-blocking):
     │
     ▼
_capture_and_save_trace()
     │
     ├── build EvidenceFlow (candidates before/after rerank)
     ├── build Trace with telemetry
     └── TraceStore.save(trace)
         └── {root}/traces/{trace_id}.json
```

## Event Flow

```
quro_doc_add → _derive_change_type(payload)
     │
     ▼
EventStore.emit(doc_id, change_type, summary)
     │
     ▼
events/store.py
     └── {root}/events/{doc_id}.json
         └── append event entry with timestamp
```

Event types:
- `supersedes` present → `"version_bump"`
- `status == "deprecated"` → `"deprecated"`
- `status == "archived"` → `"archived"`
- default → `"created"`

## Protocol Boundary Enforcement

### Core API Validation

```
quro_doc_add(payload)
  → ProtocolValidator.validate_input() — reject invalid at boundary
  → write_raw_doc() — append-only, unchanged
  → EventStore.emit(artifact_id, change_type, summary) — best-effort
  → change_type derived from payload
```

### Inspector Protocol Validation

The Inspector extension validates caller-declared `metadata_set` against the **Inspect Protocol v1.0.0** before data access, providing independent protocol enforcement from the Core API:

```
get_metadata(doc_id, metadata_set?)
  → if metadata_set is not None:
      _validate_metadata_set(metadata_set)
        → ProtocolValidator.validate_metadata_set()
          → validates against metadata_set_v1.json schema
            (items: key required, description/domain/map_to optional,
             no additional properties, min 1 item)
        → on ValidationError:
            return structured error with:
              protocol_version: "1.0.0"
              protocol_violated: "metadata_set_v1"
              validation_errors: [...]

list_metadata_keys(min_coverage, metadata_set?)
  → if metadata_set is not None:
      _validate_metadata_set(metadata_set)
        → (same flow as above)
```

On success, `_validate_metadata_set` returns `None` and normal data access proceeds. On failure, the structured error is returned immediately — no storage access occurs.

### Metadata Fields (protocol-enforced)

| Field | Values | Effect |
|-------|--------|--------|
| `status` | `draft` / `active` / `deprecated` / `archived` | Controls lifecycle semantics; `deprecated` emits `deprecated` event |
| `version` | semver string (`"0.1.0"`) | Stored in metadata; included in event summary |
| `supersedes` | doc_id string | Triggers `version_bump` event instead of `created`; forms version chain |

## Execution Order Guarantees

| Guarantee | Mechanism |
|-----------|-----------|
| Write completes before ack | Synchronous `write_raw_doc` before return |
| No write-blocking inference | `quro_doc_add` has zero model calls |
| Search never mutates storage | `query_pipeline` is read-only |
| Traces never block search | `_capture_and_save_trace` catches all exceptions |
| Events never block write | `EventStore.emit` wrapped in try/except |
| Asset promises idempotent | SHA-256 based asset_id is deterministic |
