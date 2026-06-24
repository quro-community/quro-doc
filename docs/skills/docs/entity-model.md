# quro-doc Entity Model

Entity types, storage layout, technology stack, and source map.
For how-to procedures, see `../skills/`.

---

## What quro-doc Is

quro-doc is a **lightweight cognitive document system** that serves as an **LLM inference cache layer**. It stores raw documents append-only, rebuilds all derived data (indices, distills, links) from those raw documents, and decouples writes from computation.

### System Positioning

- **LLM inference cache** — stores document context so LLMs can retrieve structured knowledge without re-inference.
- **Replaceable pipeline** — every pipeline stage (index, distill, link, query, materialize) is swappable. The core does not depend on any specific vector store, LLM, or retriever.
- **Not a knowledge base** — quro-doc does not build a global knowledge graph. It maintains a local append-only document store with rebuildable derived data.
- **Not a real-time inference system** — writes are accepted immediately and processed asynchronously. Writes never block on model inference.

## Entity Types

quro-doc manages three distinct entity types:

| Entity | Nature | Storage | Mutability |
|--------|--------|---------|------------|
| **Document** | Canonical text + metadata | `{root}/docs/{id}.txt` + `.json` | Append-only |
| **Asset** | Opaque binary blob (images, PDFs) | `{root}/assets/{id}` + `.meta.json` | Append-only |
| **Artifact** | Derived pipeline output (JSON) | `{root}/artifacts/{type}/{id}.json` | Rebuildable, evictable |

## Storage Layout

```
${QURO_STORAGE_ROOT}/
├── docs/          — canonical document store (new writes)
│   └── {doc_id}.txt / .json
├── raw/           — legacy document store (read-only fallback)
│   └── {doc_id}.txt / .json
├── assets/        — binary asset store
│   └── {asset_id} / .meta.json
├── index/         — vector index data
│   └── {ns}/
├── distill/       — LLM intent/signature output
├── link/          — relation detection output
├── jobs/          — deferred job queue
│   └── {job_id}.json
├── registry/      — document registry
├── events/        — change event store
├── artifacts/     — derived pipeline artifacts
│   └── {type}/{id}.json
└── projects/      — multi-tenant project root (optional)
    └── {project}/
```

### Runtime Data Location (Hermes)

```
hermes/quro-doc/storage/
├── docs/              # Current raw document location (<id>.txt + <id>.json)
├── raw/               # Legacy raw document location (pre-storage-refactor)
├── index/             # Vector indexes (via Haystack adapter)
├── distill/           # LLM-generated summaries, intents, signatures
├── link/              # Document relationship links
├── jobs/              # Async job queue
├── artifacts/         # Processed artifacts (features, provenance, schemas)
├── events/            # Change events
│   └── {date}/        # event-{seq}.json per day
├── registry/          # Consumer dependency declarations
├── assets/            # Asset files
├── logs/              # Runtime logs
└── projects/          # Multi-tenant: one subdirectory per project
    └── {project}/
        ├── docs/
        ├── index/
        ├── distill/
        ├── link/
        ├── jobs/
        ├── events/
        └── registry/
```

## Technology Stack

| Layer | Technology |
|-------|-----------|
| **Embedding** | LLM embedding API (configurable endpoint) |
| **Vector Store** | FAISS (local) or pluggable adapter |
| **Job Queue** | Redis list or filesystem-based fallback |
| **MCP Server** | `mcp.server.fastmcp.FastMCP` |
| **Config** | `dotenv` → `.env` file |
| **Doc Lifecycle** | `status`: draft → active → deprecated → archived |
| **Versioning** | `version` (semver) + `supersedes` (doc_id chain) |

## Source Map

| Module | Path | Role |
|--------|------|------|
| Core API | `src/quro_doc/api.py` | `quro_doc_add`, `quro_doc_search`, `quro_doc_get`, asset CRUD |
| Data Model | `src/quro_doc/model.py` | `RawDocument` dataclass, typed dict-key constants (Field, PayloadKey, ResponseKey, MetaKey); `quro_doc_add` constructs via `RawDocument.new()` → `.to_dict()` |
| Storage | `src/quro_doc/storage.py` | File-based doc/asset CRUD |
| Storage Layer | `src/quro_doc/storage_layer.py` | Path derivation authority, multi-tenant root |
| Config | `src/quro_doc/config.py` | `QuroConfig` dataclass from env |
| Query Pipeline | `src/quro_doc/pipelines/query_pipeline.py` | Multi-level search pipeline |
| Index Pipeline | `src/quro_doc/pipelines/index_pipeline.py` | Chunk → embed → vector store |
| Materialize | `src/quro_doc/pipelines/materialize_pipeline.py` | Asset download pipeline |
| Worker | `src/quro_doc/workers/worker.py` | Job queue consumer |
| MCP Server | `src/quro_doc/cli/mcp.py` | FastMCP tool registrations (9 tools) |
| Hermes MCP | `src/quro_doc/cli/hermes_mcp.py` | Cross-project MCP server (8 tools) |
| CLI | `src/quro_doc/cli/__init__.py` | CLI entry point, subcommand dispatch |
| Ext Reader | `src/quro_doc/ext/reader.py` | Asset URL resolution, plain/markdown reader |
| Ext Writer | `src/quro_doc/ext/writer.py` | Media extraction, asset promise, plain/markdown writer |
| Ext Inspector | `src/quro_doc/ext/inspector.py` | Metadata query/list tools |
| Protocol Validator | `src/quro_doc/protocols/validator.py` | JSON Schema validation for I/O |
| Event Store | `src/quro_doc/events/store.py` | Change event emission |
| Artifact Store | `src/quro_doc/artifacts/store.py` | Derived artifact CRUD |
| Trace Store | `src/quro_doc/trace/store.py` | Search trace capture |
| Haystack Adapter | `src/quro_doc/adapters/haystack_adapter.py` | RawDocument ↔ Haystack Document |
| Vector Adapter | `src/quro_doc/vector_adapter/` | Pluggable vector store backends |

## Two-Level Mental Model

quro-doc operates at **two scopes**:

```
Hermes Level (cross-project)
  ├── hermes_add(project, file_path, title, topic, intent, tags, ...)
  ├── hermes_search(project, query)
  ├── hermes_search_all(query)
  ├── hermes_get(project, doc_id)
  └── hermes_vec_scan(project)

Project Level (single scope)
  ├── quro_doc_add(file_path, title, topic, intent, tags, ...)
  ├── quro_doc_search(query)
  └── quro_doc_get(doc_id)
```

**Hermes Level** — use when operating as Hermes Agent across different projects. You specify which project via the `project` parameter. Data lives in `{base}/projects/{project}/`.

**Project Level** — use when inside a specific project with quro-doc configured as that project's document store. No `project` parameter — the MCP server's `QURO_STORAGE_ROOT` env var scopes it.

## MCP Server Architecture

Two independent MCP servers, two different endpoints:

| `hermes mcp test` target | Tools | Server |
|--------------------------|-------|--------|
| `quro-doc` | `quro_doc_add`, `quro_doc_search`, `quro_doc_get`, `quro_doc_put_asset`, `quro_doc_get_asset`, `quro_doc_delete_asset`, `quro_doc_list_doc_ids`, `quro_doc_get_metadata`, `quro_doc_list_metadata_keys`, `quro_doc_query_by_metadata` (10 tools) | `cli/mcp.py` |
| `hermes-quro-doc` | `hermes_add`, `hermes_search`, `hermes_search_all`, `hermes_get`, `hermes_vec_scan`, `hermes_put_asset`, `hermes_get_asset`, `hermes_delete_asset` (8 tools) | `cli/hermes_mcp.py` |
