# quro-doc System Architecture

System design reference — boundaries, invariants, component map, and lifecycle.
For how-to procedures, see `../skills/`.

---

## Prototype

quro-doc is a **local-first, append-only document store with async pipeline processing**. It accepts documents via MCP/CLI, stores them immutably, and uses a background worker to build searchable derived data (vectors, LLM intents, link relations).

The system has **no database**. All storage is filesystem-based under `QURO_STORAGE_ROOT`. The job queue defaults to Redis with a filesystem-based fallback.

## Core Principles

| Principle | Implementation |
|-----------|---------------|
| **Append-only** | Raw documents are immutable once written. Updates require new `doc_id` + `supersedes` chain. |
| **Write-compute decoupling** | `quro_doc_add` writes raw immediately; pipelines (index/distill/link) run async via worker. |
| **Derived data rebuildable** | Indices, distills, links, artifacts — all can be regenerated from raw documents. |
| **Adapter isolation** | All external framework interactions (Haystack, FAISS, Redis) go through adapter layers. Core has zero direct dependency on these frameworks. |
| **Environment-driven config** | All settings via `QURO_*` env vars and `.env` file. No hardcoded paths or credentials. |
| **MCP-first interface** | Primary interface is MCP tools. CLI is a convenience wrapper. |

## System Boundaries

```
                    MCP Client / CLI
                         │
                   ┌─────▼──────┐
                   │  MCP Server │  ← cli/mcp.py (FastMCP)
                   │  CLI entry  │  ← cli/__init__.py
                   └──┬───┬───┬─┘
                      │   │   │
              ┌───────┘   │   └──────────┐
              ▼           ▼              ▼
        ┌──────────┐ ┌─────────┐  ┌───────────┐
        │  Writer  │ │ Reader  │  │ Inspector │  ← ext/ layer (media, asset resolution)
        └────┬─────┘ └────┬────┘  └─────┬─────┘
             │            │             │
             ▼            ▼             ▼
        ┌──────────────────────────────────────┐
        │            Core API Layer             │
        │  quro_doc_add / quro_doc_search       │
        │  quro_doc_get / asset CRUD            │
        │  api.py — single entry point          │
        └──────┬──────────────┬────────────────┘
               │              │
               ▼              ▼
        ┌──────────┐  ┌─────────────────┐
        │ Storage  │  │ Query Pipeline   │
        │ storage. │  │ query_pipeline.  │
        │ py       │  │ py               │
        └────┬─────┘  └────────┬────────┘
             │                 │
             ▼                 ▼
    ┌────────────┐   ┌──────────────────┐
    │ Filesystem │   │  Vector Adapter   │
    │ (docs/raw/ │   │  (FAISS/pluggable)│
    │  assets/)  │   │  Scoring/Reranker │
    └────────────┘   └──────────────────┘

        ┌──────────────────────────────────────┐
        │           Async Worker                │
        │  workers/worker.py                    │
        │  pops jobs from Redis queue           │
        │  runs index/materialize pipelines     │
        └──────────────────────────────────────┘
```

### What is IN the system

- Document CRUD (append-only write, read, list)
- Binary asset CRUD
- Vector indexing and search
- LLM-based distill/signature extraction (async)
- Link detection (async)
- Materialization (asset download) (async)
- Metadata inspection and filtering
- Search trace capture
- Change event emission
- Multi-project tenant isolation via `StorageLayer`

### Protocol Enforcement Boundaries

The Inspector (extension layer) enforces the **Inspect Protocol v1.0.0** at its entry points:

- `get_metadata(doc_id, metadata_set?)` — validates `metadata_set` against `metadata_set_v1.json` schema before data access if provided
- `list_metadata_keys(...)` — validates `metadata_set` against same schema before data access if provided

Violations return a structured error with `protocol_version: "1.0.0"`, `protocol_violated: "metadata_set_v1"`, and `validation_errors[]`. This is independent of the Core API's `"2.0.0-draft"` protocol version.

### What is OUT of the system

- Real-time LLM inference during write
- Global knowledge graph
- User authentication/authorization
- HTTP API endpoints (MCP is the primary transport)
- Database (no SQL/NoSQL — filesystem only)
- Real-time collaborative editing

## Invariants

These MUST hold at all times — violations are bugs.

| # | Invariant | Enforced By |
|---|-----------|-------------|
| I1 | A `doc_id` maps to exactly one raw document body. Once written, body never changes. | `storage.py` — `write_raw_doc` returns `False` if `.txt` exists |
| I2 | Every `quro_doc_add` call either creates a new document or returns `status: "exists"`. No partial writes. | `api.py` — atomic check-write |
| I3 | `QURO_STORAGE_ROOT` is the single source of truth for all filesystem paths. | `storage_layer.py` — `StorageLayer.resolve_storage_root()` |
| I4 | All Haystack interactions go through `adapters/haystack_adapter.py`. Core never imports Haystack directly. | Adapter pattern, `config.py` — `enable_haystack` flag |
| I5 | Derived data (index, distill, link, artifact) is always rebuildable from raw documents. No derived data is canonical. | Design constraint — all pipelines are idempotent |
| I6 | Writes never block on model inference. `quro_doc_add` returns immediately. | `api.py` — no async/await, no LLM calls |
| I7 | All configuration derives from `.env` (with `.env.example` as template). No hardcoded credentials or paths. | `config.py` — `QuroConfig.load()` |
| I8 | Protocol version is included in every response. Core API uses `"2.0.0-draft"`; the Inspect Protocol (Inspector extension) uses `"1.0.0"`. Different subsystems may have independent protocol versions, each carrying a `protocol_version` field. | `api.py` (core), `ext/inspector.py` (inspect) |

## Component Map

```
src/quro_doc/
├── api.py                         # Core: quro_doc_add, quro_doc_search, quro_doc_get, asset CRUD
├── model.py                       # RawDocument dataclass + typed key constants; wired into api.py write path via RawDocument.new() → to_dict()
├── storage.py                     # File-based doc/asset I/O
├── storage_layer.py               # Path derivation authority
├── config.py                      # QuroConfig from env
├── hermes_api.py                  # Multi-project Hermes sidecar API
├── cli/
│   ├── __init__.py                # CLI entry + subcommand dispatch
│   ├── add.py                     # quro-doc add
│   ├── get.py                     # quro-doc get
│   ├── search.py                  # quro-doc search
│   ├── mcp.py                     # quro-doc mcp (FastMCP server, 9 tools)
│   ├── vec.py                     # quro-doc vec (vector operations)
│   ├── materialize.py             # quro-doc materialize
│   ├── hermes_mcp.py              # Hermes MCP server (multi-tenant, 8 tools)
│   └── okf.py                     # OKF knowledge format tools
├── ext/
│   ├── reader.py                  # PlainTextReader / MarkdownReader (asset URL resolution)
│   ├── writer.py                  # PlainTextWriter / MarkdownWriter (media extraction)
│   └── inspector.py               # Metadata list/query/get tools
├── pipelines/
│   ├── query_pipeline.py          # Multi-level search: normalize → retrieve → score → rerank → assemble
│   ├── index_pipeline.py          # Chunk → embed → write to vector store
│   ├── materialize_pipeline.py    # Asset download pipeline
│   └── offline/                   # Offline analysis pipelines
├── workers/
│   └── worker.py                  # Job queue consumer (Redis or filesystem)
├── adapters/
│   └── haystack_adapter.py        # QuroDoc ↔ Haystack Document conversion
├── vector_adapter/                # Pluggable vector store (FAISS, filesystem)
├── artifacts/                     # Derived artifact store + feature extraction
├── protocols/                     # JSON Schema validation for I/O
├── events/                        # Change event store
├── trace/                         # Search trace capture + replay
├── scoring/                       # Multi-signal scoring engine
├── reranker/                      # Cross-encoder reranker client
├── parsers/                       # Markdown media parser (mistune)
├── helpers/                       # AssetPromise model
├── view/                          # View layer rendering (default, standard)
└── okf/                           # OKF knowledge format ingestion/export
```

## Document Lifecycle

```
draft ──→ active ──→ deprecated ──→ archived
  │                                      │
  └── supersedes chain ──────────────────┘
```

- `draft`: Work-in-progress, not yet formal.
- `active`: Canonical version, affects downstream pipelines.
- `deprecated`: No longer recommended, preserved for reference.
- `archived`: Preserved but inactive.

Status + `version` + `supersedes` are metadata fields set at write time. Because storage is append-only, transitioning status requires writing a new `doc_id` with `supersedes` pointing to the old one. Change events (`version_bump`, `deprecated`, `archived`) are emitted best-effort via `events/store.py`.

## Design Decisions

| Decision | Rationale |
|----------|----------|
| Filesystem over database | Zero-infrastructure, local-first, easy inspection/debugging |
| Append-only raw documents | Immutable truth source, simple concurrency, natural audit trail |
| Async pipeline processing | Write latency independent of model inference cost |
| Adapter isolation | Core portable across frameworks; Haystack, FAISS, Redis are optional |
| MCP over HTTP | Agent-native interface; no authentication layer needed |
| `QURO_STORAGE_ROOT` env var | Single configuration point for all paths; trivial to relocate |

## Core / External Boundary

The protocol design defines a clear boundary between core and extensions:

| In Core (quro-doc) | Externalized |
|-------------------|-------------|
| Document storage (append-only) | Distillation (LLM-dependent) |
| Asset storage (store/retrieve/delete) | Link detection |
| Basic vector indexing + search | Static HTML generation |
| Namespace routing | View rendering |
| Deferred job persistence | Content parsing (Writer) |
| Haystack adapter | Asset resolution (Reader) |

Target architecture:

```
MCP Server → Extension(Reader/Writer) → Core Protocol(api.py) → Storage
```

## Multi-Tenant Architecture

Each project is a fully isolated quro-doc instance:

```
{base}/projects/{project}/
├── docs/       ← project's documents only
├── index/      ← project's vectors only
├── distill/    ← project's derived data only
├── link/       ← project's relations only
├── jobs/       ← project's job queue
├── events/     ← project's change events
└── registry/   ← project's consumer declarations
```

A search for project "quro" will never return documents from project "hermes-agent".
`hermes_search_all` queries each project independently and merges results.
