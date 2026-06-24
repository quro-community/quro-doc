# quro-doc Designer Skill

**Role**: Designer/Architect — understanding quro-doc's system design, boundaries, invariants, and extension patterns.
**For detailed system design, see**: `../docs/architecture.md`

---

## System Identity

quro-doc is a **lightweight cognitive document system** serving as an **LLM inference cache layer**. It stores raw documents append-only, rebuilds all derived data from those raw documents, and decouples writes from computation.

Key design constraints:
- **Not a knowledge base** — local append-only store, no global graph
- **Not a real-time system** — writes return immediately, pipelines run async
- **Not a database** — filesystem-only storage, no SQL/NoSQL
- **LLM inference cache** — structured document retrieval without re-inference

## Architecture Boundaries

### What is IN

- Document CRUD (append-only)
- Binary asset CRUD
- Vector indexing and search
- LLM-based distill/signature extraction (async)
- Link detection (async)
- Materialization (asset download) (async)
- Metadata inspection and filtering
- Search trace capture
- Change event emission
- Multi-project tenant isolation

### What is OUT

- Real-time LLM inference during write
- Global knowledge graph
- User authentication/authorization
- HTTP API endpoints (MCP is primary transport)
- Database (filesystem only)
- Real-time collaborative editing

## Invariants (Must Hold)

| # | Invariant | Rationale |
|---|-----------|-----------|
| I1 | `doc_id` → exactly one body, immutable once written | Append-only truth source |
| I2 | Write is atomic: create or return `exists`, no partial writes | Data integrity |
| I3 | `QURO_STORAGE_ROOT` is single path authority | No scattered storage |
| I4 | All Haystack interactions through adapter | Core framework independence |
| I5 | All derived data rebuildable from raw | No canonical derived data |
| I6 | Writes never block on model inference | Latency independence |
| I7 | All config from `.env` / env vars | No hardcoded paths |
| I8 | Protocol version in every response. Core API uses `"2.0.0-draft"`; Inspect Protocol (Inspector extension) uses `"1.0.0"`. Different subsystems may have independent protocol versions. | Versioned API contracts per subsystem |

## Design Decisions

| Decision | Why |
|----------|-----|
| Filesystem over database | Zero-infrastructure, local-first, easy inspection |
| Append-only raw documents | Immutable truth source, simple concurrency, audit trail |
| Async pipeline processing | Write latency independent of model inference cost |
| Adapter isolation | Core portable across frameworks |
| MCP over HTTP | Agent-native interface, no auth layer |
| `QURO_STORAGE_ROOT` env var | Single config point, trivial relocation |

## Extension Patterns

### Core / External Boundary

```
Target architecture:
MCP Server → Extension(Reader/Writer) → Core Protocol(api.py) → Storage

Current architecture (MCP tools):
MCP Server → api.py → storage.py   (bypasses extension layer)
```

| In Core | Externalized |
|---------|-------------|
| Document storage (append-only) | Distillation (LLM-dependent) |
| Asset storage | Link detection |
| Basic vector indexing + search | Static HTML generation |
| Namespace routing | View rendering |
| Deferred job persistence | Content parsing (Writer) |
| Haystack adapter | Asset resolution (Reader) |

### Extension Layer

**Writers** — parse and transform content before storage:
- `PlainTextWriter` — passthrough, no media extraction
- `MarkdownWriter` — extracts media refs, registers asset promises, rewrites URLs

**Readers** — resolve references after retrieval:
- `PlainTextReader` — passthrough
- `MarkdownReader` — resolves `asset://{id}` → filesystem paths

**Inspector** — metadata query tools for app builders. Enforces **Inspect Protocol v1.0.0** at entry points: validates caller-declared `metadata_set` against `metadata_set_v1.json` schema before data access. Violations return structured errors with `protocol_version`, `protocol_violated`, and `validation_errors[]` — independent of the Core API protocol version.

### Asset Promise Model

When a document with embedded media is added via `MarkdownWriter`:

1. `MarkdownMediaParser` extracts media references from body
2. `AssetPromiseModel.register(source_url)` → deterministic `asset_id` (SHA-256[:24])
3. Writer rewrites URLs: `https://...` → `asset://{asset_id}`
4. Enqueues `materialize_asset` job
5. Worker/downloader fetches assets later, updates promise to `ready`
6. Reader resolves `asset://` placeholders to filesystem paths

**Key components:**
- `MarkdownMediaParser` (mistune-based AST parser)
- `AssetPromiseModel` (pure state machine, deterministic IDs)
- `CrawlerProtocol` (structural protocol for writer↔crawler communication)

### Protocol Boundary Enforcement

**Core API validation:**

```
quro_doc_add(payload)
  → ProtocolValidator.validate_input()  — reject invalid at boundary
  → write_raw_doc()                     — append-only
  → EventStore.emit()                   — best-effort change event
```

**Inspector (Inspect Protocol v1.0.0) validation:**

```
get_metadata(doc_id, metadata_set?)
list_metadata_keys(..., metadata_set?)
  → if metadata_set provided:
      _validate_metadata_set()
        → ProtocolValidator.validate_metadata_set()
        → on failure: return structured error with
            protocol_version: "1.0.0"
            protocol_violated: "metadata_set_v1"
            validation_errors: []
```

The Inspect Protocol is versioned independently from the Core API (which uses `"2.0.0-draft"`). Each subsystem carries its own `protocol_version` in responses.

Metadata fields:
- `status`: `draft` → `active` → `deprecated` → `archived`
- `version`: semver string
- `supersedes`: doc_id for version chains

## Multi-Tenant Design

Two scopes, two MCP servers:

| Scope | MCP Server | Tools | Routing |
|-------|-----------|-------|---------|
| Project | `quro-doc` | 10 `quro_doc_*` | `QURO_STORAGE_ROOT` env var |
| Cross-project | `hermes-quro-doc` | 8 `hermes_*` | `project` parameter |

Project isolation:
- Each project has its own `docs/`, `index/`, `distill/`, `link/`, `jobs/`, `events/`, `registry/`
- Search for project "A" never returns project "B" documents
- `hermes_search_all` queries each project independently, merges results with `_project` annotation

## Document Lifecycle

```
draft ──→ active ──→ deprecated ──→ archived
  │                                      │
  └── supersedes chain ──────────────────┘
```

Lifecycle transitions always create new `doc_id` (append-only). The `supersedes` chain forms a machine-traceable version history.

## Entity Model

Three distinct entity types:

| Entity | Storage | Mutability |
|--------|---------|------------|
| Document | `{root}/docs/{id}.txt` + `.json` | Append-only |
| Asset | `{root}/assets/{id}` + `.meta.json` | Append-only |
| Artifact | `{root}/artifacts/{type}/{id}.json` | Rebuildable, evictable |

## Further Reading

- `../docs/architecture.md` — full boundaries, invariants, component map
- `../docs/dataflow.md` — write/read/asset/async/event flows
- `../docs/entity-model.md` — entities, storage layout, tech stack
- `../skills/quro-doc-developer.md` — extending quro-doc
- `../skills/quro-doc-maintainer.md` — deployment and operations
- `../skills/quro-doc-agent.md` — agent usage guide
