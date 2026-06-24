# quro-doc Developer Skill

**Role**: Developer — extending quro-doc with new CLI subcommands, MCP tools, pipelines, and extensions.
**For system design understanding, see**: `../docs/architecture.md`

---

## CLI Architecture

The `quro-doc` command is a multi-subcommand CLI built with `argparse`. Each subcommand lives in its own module under `src/quro_doc/cli/`.

### Adding a New Subcommand

1. Create `src/quro_doc/cli/<name>.py`:

```python
"""quro-doc <name> — Description."""

from __future__ import annotations

import argparse
from quro_doc.storage import ensure_dirs


def cmd_example(args: argparse.Namespace) -> None:
    ensure_dirs()
    # ... handler logic ...


def build_parser(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser("example", help="Short help text")
    p.add_argument("--flag", help="...")
    p.set_defaults(func=cmd_example)
```

2. Register it in `src/quro_doc/cli/__init__.py`:
   - Add `from . import <name>` inside `build_parser()`
   - Add `<name>.build_parser(sub)` after existing entries

3. `.env` is loaded from CWD automatically before dispatch:
   ```python
   from dotenv import load_dotenv
   load_dotenv(os.path.join(os.getcwd(), ".env"))
   ```

### Existing Subcommands

| Module | Command | Purpose |
|--------|---------|---------|
| `add.py` | `quro-doc add` | Add document via CLI |
| `get.py` | `quro-doc get` | Retrieve by doc_id |
| `search.py` | `quro-doc search` | Search documents |
| `mcp.py` | `quro-doc mcp` | Run project-level MCP server (10 tools) |
| `vec.py` | `quro-doc vec` | Vector pipeline (scan, index, search, stats) |
| `hermes_mcp.py` | `quro-doc hermes-mcp` | Run cross-project MCP server (8 tools) |
| `okf.py` | `quro-doc okf` | OKF bundle ingest/export |
| `materialize.py` | `quro-doc materialize` | Asset download (run/worker) |

### Scripts are thin wrappers

Standalone scripts under `scripts/` delegate to the installed package — do NOT use `sys.path.insert`:

```python
# scripts/my_script.py
from dotenv import load_dotenv
load_dotenv(os.path.join(os.getcwd(), ".env"))

from quro_doc.cli.example import cmd_example
```

## MCP Tool Registration

All tools are registered on `FastMCP` instances in `cli/mcp.py` and `cli/hermes_mcp.py`.

### Adding a Project-Level MCP Tool

In `src/quro_doc/cli/mcp.py`:

```python
@mcp.tool(name="quro_doc_my_tool", description="Description")
async def quro_doc_my_tool(some_param: str) -> dict:
    """My tool description."""
    return quro_doc.my_function(some_param)
```

### Project-Level Tools (cli/mcp.py)

| Tool | Handler |
|------|---------|
| `quro_doc_add` | Wraps `api.quro_doc_add`, uses `PlainTextWriter` |
| `quro_doc_search` | Wraps `api.quro_doc_search` |
| `quro_doc_get` | Wraps `api.quro_doc_get` |
| `quro_doc_get_asset` | Wraps `api.quro_doc_get_asset` |
| `quro_doc_delete_asset` | Wraps `api.quro_doc_delete_asset` |
| `quro_doc_list_doc_ids` | Wraps `Inspector.list_doc_ids()` |
| `quro_doc_get_metadata` | Wraps `Inspector.get_metadata()` |
| `quro_doc_list_metadata_keys` | Wraps `Inspector.list_metadata_keys()` |
| `quro_doc_query_by_metadata` | Wraps `Inspector.query_by_metadata()` |

### Hermes Cross-Project Tools (cli/hermes_mcp.py)

| Tool | Handler |
|------|---------|
| `hermes_add` | Wraps `hermes_api.hermes_add` with project routing |
| `hermes_search` | Wraps `hermes_api.hermes_search` |
| `hermes_search_all` | Queries all projects, merges results with `_project` |
| `hermes_get` | Wraps `hermes_api.hermes_get` |
| `hermes_put_asset` | Wraps `hermes_api.hermes_put_asset` |
| `hermes_get_asset` | Wraps `hermes_api.hermes_get_asset` |
| `hermes_delete_asset` | Wraps `hermes_api.hermes_delete_asset` |
| `hermes_vec_scan` | Calls `run_index_pipeline` per project |

## API Contracts

### Core API (src/quro_doc/api.py)

```python
def quro_doc_add(payload: dict) -> dict:
    """
    Required fields: file_path, title, topic, intent, tags (non-empty)
    Returns: {status, doc_id, message, protocol_version}
    """

def quro_doc_search(query: dict) -> list[dict]:
    """
    query: {query: str, top_k?: int, trace_id?: str, view?: str}
    Returns: [{doc_id, chunk_id, score, snippet, tags, content}]
    """

def quro_doc_get(doc_id: str) -> dict:
    """
    Returns: {doc_id, body, meta, protocol_version} | {status: "not_found"}
    """

def quro_doc_put_asset(asset_id: str, data: bytes, content_type?: str) -> dict:
def quro_doc_get_asset(asset_id: str) -> dict:
def quro_doc_delete_asset(asset_id: str) -> dict:
```

### Protocol Version

| Domain | Version |
|--------|---------|
| Core API (add/search/get) | `"2.0.0-draft"` |
| Inspect Protocol (metadata inspection) | `"1.0.0"` |

The Inspect Protocol version is self-reported in every Inspector response; it is
independent from the Core API version and may evolve on its own cadence.

### Validation

Input/output validated against JSON Schema at `protocols/validator.py`:
- `validator.validate_input(payload, "2.0")`
- `validator.validate_output(results, "2.0")`
- `validator.validate_metadata_set(metadata_set)` — validates caller-declared metadata field declarations

Schemas:
- `protocols/schemas/add_request_v2.json` — add request payload
- `protocols/schemas/search_response_v2.json` — search response
- `protocols/schemas/metadata_set_v1.json` — Inspect Protocol `metadata_set` (see below)

## Extension Layer

### Writers (ext/writer.py)

Delegate content parsing before storage:

| Writer | Phase | Description |
|--------|-------|-------------|
| `PlainTextWriter` | 1 | Passthrough — reads file, calls `quro_doc_add` |
| `MarkdownWriter` | 3 | Extracts media refs via `MarkdownMediaParser`, registers `AssetPromise`, rewrites URLs, enqueues materialize jobs |

MCP tools use `PlainTextWriter`. CLI `add` uses `MarkdownWriter`.

**Writer pattern:**
```python
from quro_doc.model import PayloadKey, Field

class MyWriter:
    def add(self, payload: dict) -> dict:
        body = self._read_file(payload[PayloadKey.FILE_PATH])
        # ... transform body ...
        return quro_doc_add({**payload, Field.BODY: body})
```

### Readers (ext/reader.py)

Delegate asset resolution after retrieval:

| Reader | Phase | Description |
|--------|-------|-------------|
| `PlainTextReader` | 1 | Passthrough — pure delegation to API |
| `MarkdownReader` | 3 | Resolves `asset://{id}` placeholders to filesystem paths |

### Inspector (ext/inspector.py)

Metadata query tools for app builders:

```python
from quro_doc.ext.inspector import MetadataInspector

inspector = MetadataInspector(storage_root)
inspector.list_doc_ids(limit=100, offset=0)          # → DocSummary[]
inspector.get_metadata(doc_id, metadata_set=None)     # → full metadata
inspector.list_metadata_keys(min_coverage=0.0)        # → field names
inspector.query_by_metadata(filters, limit=100)       # → filtered results
```

**Always use Inspector** over `storage.list_raw_docs()` — the internal function returns `meta.meta.*` nested structures requiring manual unwrapping. Inspector returns clean, flat metadata.

#### metadata_set Validation (Inspect Protocol v1.0.0)

`get_metadata()` and `list_metadata_keys()` accept an optional `metadata_set`
parameter — a list of caller-declared metadata field declarations. This
parameter is now validated against `metadata_set_v1.json` at the entry point
*before* any data access.

**Schema contract** (each item):

| Field | Required | Type | Constraints |
|-------|----------|------|-------------|
| `key` | Yes | `string` | `minLength: 1` |
| `description` | No | `string` | |
| `domain` | No | `string` | |
| `map_to` | No | `string` | |

- The array must have at least one item (`minItems: 1`).
- Items must NOT have any properties beyond the four listed above.

**Behavior**:

- `metadata_set=None` (the default) — no validation, backward compatible.
- `metadata_set=<valid list>` — validation passes silently, proceeds normally.
- `metadata_set=<invalid list>` — returns a structured error dict immediately:

```python
{
    "status": "error",
    "message": "metadata_set violates inspect protocol v1.0.0: ...",
    "error": "metadata_set violates inspect protocol v1.0.0: ...",
    "protocol_version": "1.0.0",
    "protocol_violated": "metadata_set_v1",
    "validation_errors": [
        "'key' is a required property",
        ...
    ],
}
```

This fail-fast behavior prevents `KeyError` crashes or silent data corruption
from malformed caller input. The error is versioned, identifying exactly which
schema was violated, enabling cross-system debugging.

#### Extending the Inspect Protocol

When adding new validation rules or changing the metadata_set schema:

1. **Create a new schema version** in `protocols/schemas/` (e.g. `metadata_set_v2.json`)
2. **Add a new method** in `protocols/validator.py` (e.g. `validate_metadata_set_v2()`)
3. **Update `_validate_metadata_set()`** in `ext/inspector.py` — it lives at line 150, delegates to `ProtocolValidator`, catches `ValidationError`, and returns the structured error dict shown above.
4. **Bump `PROTOCOL_VERSION`** on the `MetadataInspector` class (currently `"1.0.0"`)
5. **Update the `protocol_violated` field** in the error dict to reference the new schema name

The `_validate_metadata_set()` helper method pattern:

```python
from jsonschema import ValidationError

def _validate_metadata_set(self, metadata_set: list) -> dict | None:
    from ..protocols.validator import ProtocolValidator
    try:
        validator = ProtocolValidator()
        validator.validate_metadata_set(metadata_set)
    except ValidationError as e:
        errors = []
        current = e
        while current:
            errors.append(current.message)
            current = current.context[0] if current.context else None
        return {
            "status": "error",
            "message": (
                f"metadata_set violates inspect protocol "
                f"v{self.PROTOCOL_VERSION}: {'; '.join(errors)}"
            ),
            "error": (
                f"metadata_set violates inspect protocol "
                f"v{self.PROTOCOL_VERSION}: {'; '.join(errors)}"
            ),
            "protocol_version": self.PROTOCOL_VERSION,
            "protocol_violated": "metadata_set_v1",
            "validation_errors": errors,
        }
    return None
```

All Inspector methods that accept `metadata_set` must call
`_validate_metadata_set()` at their entry point before any data access —
following the fail-fast pattern shown in `get_metadata()` and
`list_metadata_keys()`.

## Pipeline Development

### Search Pipeline (query_pipeline.py)

Multi-level pipeline: `normalize → retrieve → score → rerank → assemble → view render → trace capture`

Entry: `search(query_dict)` → returns list of results.

### Index Pipeline (index_pipeline.py)

`run_index_pipeline(doc_id)` — chunk → embed → write to vector store.

### Materialize Pipeline (materialize_pipeline.py)

`run_materialize_pipeline(doc_id)` — reads pending assets, downloads, stores.

`run_materialize_pipeline_for_assets(doc_id, assets)` — downloads specific assets (used by worker).

## Code Conventions

- **Append-only writes**: Raw documents immutable once written. Updates = new `doc_id` + `supersedes`.
- **Adapter pattern**: All Haystack interactions go through `adapters/haystack_adapter.py`. Core never imports Haystack.
- **Environment-driven config**: All settings via `QURO_*` env vars. Template: `.env.example`.
- **MCP-first interface**: Primary interface is MCP. CLI wraps MCP tools.
- **No database**: All storage is filesystem-based.
- **Write-compute decoupling**: `quro_doc_add` returns immediately. Pipelines run async via worker.
- **Typed string constants for dict keys**: All dict key access in production code
  (`api.py`, `pipelines/`, `ext/`, `cli/`) MUST use typed `str` constant classes
  from `src/quro_doc/model.py` — never bare string literals. This eliminates
  implicit schema coupling that causes silent data loss when a field is renamed.

  Four constant classes are defined:

  | Class | Purpose | Example |
  |-------|---------|---------|
  | `Field` | RawDocument field name constants | `Field.DOC_ID`, `Field.BODY`, `Field.TITLE` |
  | `PayloadKey` | Protocol-level payload keys not mapped to RawDocument fields | `PayloadKey.FILE_PATH`, `PayloadKey.STATUS`, `PayloadKey.VERSION` |
  | `ResponseKey` | Response dict keys + status string values | `ResponseKey.MESSAGE`, `ResponseKey.ERROR`, `ResponseKey.OK` |
  | `MetaKey` | Storage-layer meta wrapper key | `MetaKey.META` |

  ```python
  # ✅ Correct — typed constant
  from quro_doc.model import Field, PayloadKey, ResponseKey

  doc_id = response[ResponseKey.DOC_ID]
  body = payload[Field.BODY]

  # ❌ Incorrect — bare string literal
  doc_id = response["doc_id"]   # will break silently if key is renamed
  body = payload["body"]
  ```

  The `Field` class also provides `Field.all()` (returns the set of all
  RawDocument field names, validated against the dataclass at import time) and
  `Field.REQUIRED` (frozenset of fields that must be non-empty for document
  creation).

## Further Reading

- `../docs/architecture.md` — boundaries, invariants, component map
- `../docs/dataflow.md` — write/read/asset/async paths
- `../docs/entity-model.md` — entities, storage, source map
- `../skills/quro-doc-agent.md` — agent usage guide
- `../skills/quro-doc-maintainer.md` — deployment and troubleshooting
