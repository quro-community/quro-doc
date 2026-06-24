# quro-doc Agent Skill

**Role**: Agent — using quro-doc tools from an AI agent session.
**For system design understanding, see**: `../docs/entity-model.md`, `../docs/architecture.md`, `../docs/dataflow.md`

---

## Quick Start

Load this skill in a session to have quro-doc MCP tools available (tools are auto-discovered from Hermes config).

**Search for context:**
```python
results = mcp_quro_doc_quro_doc_search({"query": "relevant topic", "top_k": 5})
```

**Retrieve a known doc by ID (bypasses search):**
```python
mcp_quro_doc_quro_doc_get(doc_id="proto-quro-spec-v2.1")

# Cross-project variant:
mcp_hermes_quro_doc_hermes_get(project="quro-infra", doc_id="proto-quro-imspec-v2")
```

**Add a document:**
```python
write_file(path="/tmp/my-doc.md", content="# Title\n\nFull content...")

mcp_quro_doc_quro_doc_add(
    file_path="/tmp/my-doc.md",
    title="Document Title",
    topic="engineering",
    intent="analysis",
    tags=["tag1", "tag2"],
    metadata={"discovered_date": "YYYY-MM-DD", "language": "en"},
)

# Hermes cross-project:
mcp_hermes_quro_doc_hermes_add(
    project="my-project",
    file_path="/tmp/my-doc.md",
    title="Document Title",
    topic="engineering",
    intent="analysis",
    tags=["tag1", "tag2"],
)
```

## When to Store a Document

- **After codebase analysis** — save analysis as a document with topic matching the codebase area
- **After design decisions** — save the reasoning, options considered, and final choice
- **Research output** — save summaries, findings, and references
- **Design drafts** — save proposals with refs to related documents
- **Any long-form content you want to search later**

## When NOT to Store

- Transient single-turn context
- Data better suited to `quro-memory` (episodic memory, user preferences)
- Self-evident / easily re-derived facts

## MCP Tool Reference

### Two-Level Scoping

| Level | Tools | When |
|-------|-------|------|
| **Project** | `quro_doc_*` | Inside a specific project, MCP scoped to one `QURO_STORAGE_ROOT` |
| **Hermes** | `hermes_*` | Cross-project, `project` param targets each operation |

### Project-Level Tools (`mcp_quro_doc_*`)

| Tool | Purpose | Key Parameters |
|------|---------|----------------|
| `quro_doc_add` | Add a document (append-only) | `file_path` (required), `title`, `topic`, `intent`, `tags` (all required), `doc_id` (optional for idempotency), `metadata`, `refs`, `source` |
| `quro_doc_search` | Semantic search | `query` dict with `query` text key, `top_k`, `trace_id` |
| `quro_doc_get` | Retrieve by doc_id (bypasses search) | `doc_id` (required) |
| `quro_doc_list_doc_ids` | List documents with metadata | `limit` (default 100), `offset` |
| `quro_doc_get_metadata` | Full metadata for one doc | `doc_id`, `metadata_set` (optional — see schema contract below) |
| `quro_doc_list_metadata_keys` | Discover metadata fields | `min_coverage` (0.0 = all keys), `metadata_set` (optional — see schema contract below) |
| `quro_doc_query_by_metadata` | Filter by metadata criteria | `filters` list (AND-combined), `limit`, `offset` |
| `quro_doc_get_asset` | Retrieve binary asset | `asset_id` |
| `quro_doc_delete_asset` | Delete binary asset | `asset_id` |

### Hermes Cross-Project Tools (`mcp_hermes_quro_doc_*`)

| Tool | Purpose | Key Parameters |
|------|---------|----------------|
| `hermes_add` | Add doc to a project | `project` (required), + same as `quro_doc_add` |
| `hermes_search` | Search within a project | `project` (required), `query` dict |
| `hermes_search_all` | Search ALL projects | `query` dict. Results tagged with `_project` |
| `hermes_get` | Retrieve from a project | `project`, `doc_id` (both required) |
| `hermes_put_asset` | Store binary asset in project | `project`, `asset_id`, `file_path` |
| `hermes_get_asset` | Retrieve asset from project | `project`, `asset_id` |
| `hermes_delete_asset` | Delete asset from project | `project`, `asset_id` |
| `hermes_vec_scan` | Re-index project(s) | `project` (optional — omit to scan all) |

### Response Semantics

- **add** returns `{status, doc_id, message, protocol_version}`
  - `status: "accepted"` → document written, event emitted
  - `status: "exists"` → doc_id already exists (append-only)
  - `status: "error"` → validation failure (check `missing_fields`)
- **search** returns `[{doc_id, chunk_id, score, snippet, tags, content}]`
- **get** returns `{doc_id, body, meta}` on success; `{status: "not_found"}` on miss
- **search_all** same as search, each result annotated `{..., _project: "project-name"}`

### Protocol-Violation Error Response (metadata_set)

Applies to `quro_doc_get_metadata` and `quro_doc_list_metadata_keys` when `metadata_set` is provided with an invalid structure.

**Schema contract for `metadata_set` items:**
- `key`: **required**, string, `minLength` 1
- `description`: optional, string
- `domain`: optional, string
- `map_to`: optional, string
- No additional properties allowed per item
- Array must have at least 1 item (empty list is rejected)
- Non-string types for optional fields are rejected

**Error response format:**
```json
{
  "status": "error",
  "message": "metadata_set violates inspect protocol v1.0.0: 'key' is a required property",
  "error": "metadata_set violates inspect protocol v1.0.0: 'key' is a required property",
  "protocol_version": "1.0.0",
  "protocol_violated": "metadata_set_v1",
  "validation_errors": ["'key' is a required property"]
}
```

**Backward compatibility:**
- `metadata_set=None` (not provided) — behavior unchanged, no validation
- `metadata_set` with valid items — behavior unchanged, validated silently

### Required Fields (always)

`title`, `topic`, `tags` (non-empty list), and `intent` are enforced at write time. Missing fields return `{status: "error", missing_fields: [...]}`.

### Metadata Field Semantics — Critical

| Field | Meaning | Set by |
|-------|---------|--------|
| `path` | **Original file ingested** — absolute path, auto-set from `file_path` | MCP tools |
| `source.path` | **Source code provenance** — file that was analyzed to produce this doc | Caller explicitly |

Do NOT use `source.path` for file links — use `path`.

## Search Fallback Workflow

When `quro_doc_search` fails or returns empty:

1. **Try direct doc-id retrieval** — if you know a doc_id:
   ```python
   mcp_quro_doc_quro_doc_get(doc_id="known-doc-id")
   mcp_hermes_quro_doc_hermes_get(project="proj", doc_id="known-doc-id")
   ```

2. **Fall back to raw filesystem** — if tools unavailable:
   ```bash
   ls hermes/quro-doc/storage/raw/
   ```
   Docs are `{doc_id}.txt` (body) + `{doc_id}.json` (metadata). Read with `read_file()`.

3. **Research codebase directly** — read project files, explore sources.

4. **Submit knowledge** via `quro_doc_add` / `hermes_add`.
   - Write body to a temp file first
   - Then call add with the `file_path`
   - Verify: check `wc -c {doc_id}.txt` in storage root's `docs/` directory

## Known Limitations

### hermes_vec_scan broken (2026-06-09)
`run_index_pipeline() missing 1 required positional argument: 'doc_id'`. Affects all projects. Workaround: write raw files, then index per-doc via CLI:
```bash
export QURO_STORAGE_ROOT=/data/hermes/quro-doc/storage
quro-doc vec index --project mlx-lm <doc_id>
```

### Two separate MCP servers — not interchangeable
`quro-doc` (project-level, 10 tools) and `hermes-quro-doc` (cross-project, 8 tools) are independent servers. Verify with:
```bash
hermes mcp test quro-doc          # 10 tools
hermes mcp test hermes-quro-doc   # 8 tools
```

### QURO_STORAGE_ROOT must be in MCP config
If missing from `~/.hermes/config.yaml`'s `mcp_servers.quro-doc.env`, storage defaults to `.quro_context/docs` under CWD — silently writing to wrong location. Verify:
```bash
grep -A8 "quro-doc:" ~/.hermes/config.yaml | grep QURO_STORAGE_ROOT
```

### Storage refactor (2026-06)
New writes go to `docs/`, legacy docs remain in `raw/`. When verifying files on disk, check `docs/` first, then `raw/`.

## Integration Config

### Standard quro-doc MCP (project-level)

```yaml
mcp_servers:
  quro-doc:
    command: quro-doc
    args: [mcp]
    env:
      QURO_STORAGE_ROOT: hermes/quro-doc/storage
      EMBEDDING_API_URL: http://127.0.0.1:8001/v1
      QUEUE_BACKEND: filesystem
      QURO_LOG_DIR: hermes/quro-doc/logs
    enabled: true
```

### Hermes-specific MCP (cross-project)

```yaml
mcp_servers:
  hermes-quro-doc:
    command: /path/to/quro-doc
    args:
    - hermes-mcp
    - --projects-root
    - /path/to/projects/root
    env:
      QURO_STORAGE_ROOT: /path/to/legacy/root
    enabled: true
    hidden: true
```

## Session Startup Protocol

At session start, load this skill. MCP tools are auto-discovered from Hermes config.

For task-specific context:
```python
results = mcp_quro_doc_quro_doc_search({"query": "<relevant topic>", "top_k": 5})
```

## Post-Write Verification

After `quro_doc_add`/`hermes_add` returns `accepted`, always verify:
1. Check the file landed: `ls {QURO_STORAGE_ROOT}/docs/{doc_id}.txt`
2. Check file size is reasonable: `wc -c {QURO_STORAGE_ROOT}/docs/{doc_id}.txt`
3. Check metadata: `cat {QURO_STORAGE_ROOT}/docs/{doc_id}.json | python -m json.tool`

## Further Reading

- `../docs/entity-model.md` — entity types, storage layout, tech stack, source map
- `../docs/architecture.md` — boundaries, invariants, component map, lifecycle
- `../docs/dataflow.md` — write/read/asset/async/event paths
- `../skills/quro-doc-developer.md` — extending quro-doc with CLI/MCP/pipelines
- `../skills/quro-doc-maintainer.md` — deploying, configuring, troubleshooting
- `../skills/quro-doc-designer.md` — architecture decisions, extension patterns
