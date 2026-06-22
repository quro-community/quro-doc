# quro-doc — Lightweight Cognitive Document System

> **LLM inference cache layer that turns ephemeral reasoning into reusable cognitive assets.**

quro-doc is an append-only document system designed as a **cognitive cache** for LLM workflows. Instead of re-inferring the same knowledge, agents store structured documents once and retrieve them via semantic search — with async pipelines for vector indexing, media materialization, and relationship linking.

---

## 1. What quro-doc Does

```
LLM Inference (ephemeral)
    │
    ▼
┌─────────────────────────────────────────────┐
│  quro_doc_add(payload)                      │
│  │                                          │
│  ├─ MarkdownWriter — media extraction       │
│  │   (MarkdownMediaParser → AssetPromise)   │
│  ├─ Append-only raw document storage        │
│  └─ Returns {status, doc_id, job_id}        │
├─────────────────────────────────────────────┤
│  Background Pipelines (worker)              │
│  ├─ Index pipeline (chunk → embed → FAISS)  │
│  └─ Materialize pipeline                    │
│      ├─ httpx (default, fast-path)          │
│      └─ Aria2 (QURO_MATERIALIZER=aria2)     │
├─────────────────────────────────────────────┤
│  quro_doc_search(query)                     │
│  ├─ Query pipeline: retrieve → score → view │
│  └─ View Layer: default (JSON) / standard   │
│      (formatted TXT with sections/budget)   │
├─────────────────────────────────────────────┤
│  Inspection Layer (MetadataInspector)        │
│  ├─ quro_doc_get / list_doc_ids             │
│  ├─ get_metadata / list_metadata_keys       │
│  └─ query_by_metadata (AND filters)         │
├─────────────────────────────────────────────┤
│  Asset Management                           │
│  ├─ get_asset / delete_asset                │
│  └─ Materialize: pending → downloaded       │
└─────────────────────────────────────────────┘
```

### Core Principles

| Principle | Description |
|-----------|-------------|
| **Append-only** | Raw documents are immutable once written. Updates require a new `doc_id` with `supersedes`. |
| **Rebuildable derived data** | Indices and links can be regenerated from raw documents at any time. |
| **Write-compute decoupling** | `quro_doc_add` returns immediately; pipelines run asynchronously via a job queue. |
| **Filesystem-native** | All storage is flat files on disk — no database dependency. |
| **MCP-first interface** | Primary interface is through MCP tools; CLI wraps the same API. |
| **Adapter isolation** | All Haystack interactions go through `adapters/haystack_adapter.py`. |

---

## 2. Quick Start

### Prerequisites

- Python >= 3.11
- pip

### Setup

```bash
# Clone and enter the project
git clone <repo-url> quro-doc
cd quro-doc

# Create virtual environment
python3 -m venv .venv && source .venv/bin/activate

# Install in editable mode
pip install -e ".[dev]"

# Or with Redis queue support
pip install -e ".[dev,redis]"

# Configure
cp .env.example .env
# Edit .env as needed
```

### CLI Usage

```bash
# Add a document
quro-doc add --body "Your content" --title "My Doc" --topic "design" --intent "specification" --tag "arch"

# Search documents
quro-doc search "your query" --top-k 5

# Retrieve by doc_id
quro-doc get <doc_id>

# OKF bundle: ingest a knowledge bundle from disk
quro-doc okf ingest --bundle ./my-bundle/ --project my-project

# OKF bundle: export a project as an OKF bundle
quro-doc okf export --project my-project --out ./exported-bundle/

# Materialize pending assets for a document
quro-doc materialize run <doc_id>

# Run materialize as a continuous worker
quro-doc materialize worker --poll-interval 10

# Vector pipeline (scan, index, search, stats)
quro-doc vec scan <doc_id>
quro-doc vec index --all

# Run MCP server (stdio mode)
quro-doc mcp --transport stdio
```

### Running the Worker

```bash
# File-based queue (default)
quro-doc worker

# Redis-backed queue
docker run -p 6379:6379 -d redis:6
quro-doc worker --queue redis
```

---

## 3. MCP Tools

quro-doc exposes the following MCP tools for LLM agent integration:

### Core Tools

| Tool | Description |
|------|-------------|
| `quro_doc_add(payload)` | Store a document. Returns `{status, doc_id, job_id, message}`. |
| `quro_doc_search(query)` | Semantic search. Supports `view` parameter: `"default"` (raw JSON), `"standard"` (formatted TXT with sections/token budget), `"debug"` (verbose). Returns `[{doc_id, score, snippet, tags, content, ...}]`. |

### Document Management

| Tool | Description |
|------|-------------|
| `quro_doc_get(doc_id)` | Retrieve a document directly by ID. |
| `quro_doc_list_doc_ids(limit, offset)` | List all doc IDs with metadata summaries. |
| `quro_doc_get_metadata(doc_id, metadata_set)` | Retrieve full metadata for a document. |
| `quro_doc_list_metadata_keys(min_coverage)` | Discover all metadata field names across documents. |
| `quro_doc_query_by_metadata(filters, limit, offset)` | Filter documents by AND-combined metadata criteria. |

### Asset Management

| Tool | Description |
|------|-------------|
| `quro_doc_get_asset(asset_id)` | Retrieve a binary asset. |
| `quro_doc_delete_asset(asset_id)` | Delete a binary asset. |

MCP client configuration (e.g., `opencode.json` / `claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "quro-doc": {
      "command": "quro-doc",
      "args": ["mcp", "--transport", "stdio"]
    }
  }
}
```

---

## 4. Project Structure

```
AGENTS.md
README.md
pyproject.toml
.env.example
requirements.txt
src/quro_doc/
  ├── api.py                # Core API entry points
  ├── model.py              # RawDocument model + typed Field/PayloadKey constants
  ├── storage.py            # Append-only filesystem storage
  ├── config.py             # Environment-driven configuration
  ├── cli/                  # CLI subcommands (add, get, search, mcp,
  │                         #   vec, okf, materialize, hermes-mcp)
  ├── pipelines/            # Async pipelines (index, materialize, link, query)
  ├── view/                 # View Layer — search result rendering
  │   ├── engine.py         #   ViewLayerOrchestrator (dispatch by view name)
  │   └── renderer/         #   default (JSON), standard (TXT sections)
  ├── ext/                  # Extension layer — Writers & Readers
  │   ├── writer.py         #   MarkdownWriter, PlainTextWriter
  │   └── inspector.py      #   MetadataInspector
  ├── okf/                  # OKF bundle — ingest/export knowledge bundles
  │   ├── ingest.py         #   Bundle → quro-doc storage
  │   ├── export.py         #   quro-doc storage → Bundle
  │   ├── scanner.py        #   Directory tree walker
  │   ├── parser.py         #   YAML frontmatter parser
  │   └── source.py         #   QuroDocSource (OKF Source adapter)
  ├── materializers/        # Asset download backends
  │   ├── aria2_crawler.py  #   Aria2 RPC crawler
  │   ├── aria2_materializer.py  #   download_via_aria2
  │   └── http_crawler.py   #   HTTP crawler protocol
  ├── adapters/             # Haystack adapter layer (isolation boundary)
  ├── workers/              # Job queue consumer (file or Redis)
  ├── registry/             # Consumer dependency registry
  ├── events/               # Document change event emission
  ├── parsers/              # Content parsers (markdown media extractor)
  └── helpers/              # AssetPromiseModel and utilities
docs/
  ├── api/quro_mcp_api.md   # MCP tool API specification
  └── designs/              # Design documents
scripts/                    # Standalone CLI wrappers
tests/                      # Pytest test suite
```

---

## 5. Features Deep Dive

### 5.1 OKF Bundle Support

quro-doc supports **OKF (Open Knowledge Format)** bundles — structured directory trees of markdown concept files with YAML frontmatter.

```
my-bundle/
  ├── index.md           # Auto-generated on export
  ├── architecture/
  │   ├── overview.md
  │   └── dataflow.md
  └── api/
      └── reference.md
```

**CLI commands:**

```bash
quro-doc okf ingest --bundle ./bundle/ --project my-project
quro-doc okf export --project my-project --out ./bundle/
```

- **Ingest**: Scans bundle directory (`scan_bundle`), parses YAML frontmatter (`parse_frontmatter`), transforms each concept into a quro-doc document via `MarkdownWriter`, tags with `okf` + `okf:type:{type}`, preserves `_raw_frontmatter` for byte-perfect round-trip.
- **Export**: Reconstructs the directory tree from storage — regenerates `index.md`, restores original frontmatter from preserved `_raw_frontmatter`.
- **Source adapter**: `QuroDocSource` implements the OKF `Source` interface, routing `list_concepts()` through hermes search and `read_concept()` through hermes get.

**Modules:** `src/quro_doc/okf/` — `scanner.py`, `parser.py`, `ingest.py`, `export.py`, `source.py`.

---

### 5.2 Media Asset Support — Crawler / Materializer + Aria2

Documents can reference external media assets (images, files). quro-doc extracts these references during add, registers them as **AssetPromises**, and downloads them asynchronously.

**Flow:**

```
MarkdownWriter.add()
  └─ MarkdownMediaParser.extract(body) → MediaRef[]
      └─ AssetPromiseModel.register(url) → AssetPromise
          └─ URL rewritten: https://... → asset://{id}
              └─ quro_doc_add() → pending assets in metadata
                  └─ Worker → Materialize Pipeline
                      ├─ httpx (default, QURO_MATERIALIZER=httpx)
                      └─ Aria2 (QURO_MATERIALIZER=aria2)
```

**Backend selection:**

| Env | Backend | Description |
|-----|---------|-------------|
| `QURO_MATERIALIZER=httpx` (default) | `_materialize_via_httpx` | Simple HTTP GET via `httpx`, no external deps |
| `QURO_MATERIALIZER=aria2` | `download_via_aria2` | Uses `aria2c` via JSON-RPC — supports multi-connection, resumable downloads |

**Commands:**

```bash
# Manual materialize for a single document
quro-doc materialize run <doc_id>

# Continuous materialize worker
quro-doc materialize worker --poll-interval 10
```

**Modules:** `src/quro_doc/materializers/` — `aria2_crawler.py`, `aria2_materializer.py`, `http_crawler.py`.
**Pipeline:** `src/quro_doc/pipelines/materialize_pipeline.py`.

---

### 5.3 View Layer — Post-Search Rendering

The **View Layer** transforms raw search candidates into formatted responses. It sits between the query pipeline and the API response, supporting pluggable renderers.

**Architecture:**

```
Query Pipeline → EvidenceCandidate[]
                     │
                     ▼
     ViewLayerOrchestrator.render(view_name, candidates, query)
                     │
          ┌──────────┼──────────┐
          ▼          ▼          ▼
   "default"   "standard"   "debug"
   (JSON raw)  (TXT with    (verbose)
                sections/
                token budget)
```

| View | Renderer | Format | Description |
|------|----------|--------|-------------|
| `default` | `DefaultViewRenderer` | JSON | Raw candidates as JSON array (backward compatible) |
| `standard` | `StandardViewRenderer` | TXT | Section-planned output with token budget, evidence selection, section planning |
| `debug` | — | verbose | Debug-level detail |

**View orchestration:** `src/quro_doc/view/engine.py` — `ViewLayerOrchestrator`.
**Renderers:** `src/quro_doc/view/renderer/` — `default.py`, `standard.py`, `base.py` (protocol + data classes).

Set `view` parameter in `quro_doc_search(query_dict)`: `{"query": "...", "view": "standard"}`.

---

### 5.4 Distillation Pipeline (Legacy)

The distillation pipeline (`pipelines/distill_pipeline.py`) was an early experiment for LLM-based intent/signature extraction from raw documents. It is **no longer maintained** — the source file has been removed from the codebase. The concept of distillation (extracting structured summaries from document content) may be revisited in a future version, but there is currently no active implementation.

---

## 6. Project Status

quro-doc is currently in **Alpha** (v0.2.0). The core API surface is stable, but pipelines and worker infrastructure are still evolving. Breaking changes may occur.

---

## 7. License

This project is released under the **Unlicense** — free and unencumbered software released into the public domain.

See [LICENSE.txt](LICENSE.txt) for the full text.

---

## 8. Disclaimer

本软件按"原样"提供，不带有任何明示或暗示的担保。由于代码全由 AI 生成，作者未进行完备的生产环境测试。使用者需自行承担因运行本软件而导致的任何风险、损失或数据损坏。作者对代码的准确性、安全性和有效性不承担任何法律责任。

This software is provided "as is", without warranty of any kind, express or implied. Since all code is generated by AI, the authors have not performed comprehensive production testing. Users assume all risks, losses, or data corruption resulting from running this software. The authors assume no legal liability for the accuracy, security, or fitness of the code.

---

## 9. Acknowledgments

This project is entirely AI-driven. We thank the following large language models for providing core ideas, architectural design, and all code implementation (in no particular order):

- **Claude**
- **Gemini**
- **ChatGPT**
- **DeepSeek**
- **GLM**

Thank you to these technologies for their major contributions to this project.
