# quro-doc Maintainer Skill

**Role**: Maintainer/Operator — deploying, configuring, running, and troubleshooting quro-doc.
**For system design understanding, see**: `../docs/architecture.md`

---

## Configuration

All configuration via environment variables loaded by `QuroConfig.load()` at `src/quro_doc/config.py`.

### Required Env Vars

| Variable | Default | Description |
|----------|---------|-------------|
| `QURO_STORAGE_ROOT` | `.quro_context/docs` | Storage root directory — **critical**, must be set in MCP config |
| `EMBEDDING_API_URL` | `http://localhost:20128/v1/embeddings` | Embedding service endpoint |
| `EMBEDDING_MODEL` | `llama/embeddinggemma` | Embedding model name |

### Optional Env Vars

| Variable | Default | Description |
|----------|---------|-------------|
| `QUEUE_BACKEND` | `redis` | `"redis"` or `"file"` |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis connection string |
| `QUERY_USE_SCORING` | `true` | Enable scoring engine |
| `QUERY_USE_RERANKER` | `false` | Enable cross-encoder reranker |
| `RERANK_API_URL` | `http://localhost:8002/v1/rerank` | Reranker endpoint |
| `RERANK_MODEL` | `gpustack/bge-reranker-v2-m3` | Reranker model |
| `RERANK_TOP_K` | `20` | Reranker candidate count |
| `VIEW_NAME` | `default-view` | `"default-view"` or `"standard"` |
| `STANDARD_VIEW_ENABLED` | `true` | Enable standard view renderer |
| `STANDARD_VIEW_TOKEN_BUDGET` | `1200` | Max tokens for standard view |
| `QURO_ARTIFACT_STORE_ENABLED` | `false` | Enable artifact store |
| `QURO_ARTIFACT_FEATURE_WEIGHT` | `0.0` | Artifact feature weight in ranking |
| `QURO_TRACE_RETENTION_DAYS` | `90` | Trace TTL |
| `QURO_HOT_DOC_SCAN_INTERVAL_MINUTES` | `360` | Hot doc scan interval |
| `QURO_LOG_DIR` | `.quro_context/logs/quro-docs` | Log directory |
| `LOG_LEVEL` | `INFO` | Log level |

Template: `.env.example` at project root.

## MCP Server Deployment

Two independent MCP servers — configure both in `~/.hermes/config.yaml`:

### 1. Standard quro-doc MCP (project-level, 10 tools)

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

### 2. Hermes cross-project MCP (8 tools)

```yaml
mcp_servers:
  hermes-quro-doc:
    command: /path/to/quro-doc      # absolute path to quro-doc executable
    args:
    - hermes-mcp
    - --projects-root
    - /path/to/projects/root        # parent of projects/ directories
    env:
      QURO_STORAGE_ROOT: /path/to/legacy/root
    enabled: true
    hidden: true
```

### Verify deployment

```bash
hermes mcp test quro-doc          # expect 10 tools
hermes mcp test hermes-quro-doc   # expect 8 tools
```

### Add a new project

```bash
mkdir -p {QURO_STORAGE_ROOT}/projects/{project_name}/{docs,index,distill,link,jobs,events,registry}
```

## Background Worker

The worker processes async jobs (indexing, materialization):

```bash
# Via package CLI:
quro-doc worker --poll-interval 2

# Via script:
cd /path/to/quro-doc
source .venv/bin/activate
python scripts/quro-worker --poll-interval 5
```

Worker loop:
1. Pop job from Redis list `"quro_jobs"` (or scan `jobs/*.json` if filesystem backend)
2. Resolve storage root for project
3. Run tasks: `run_index_pipeline(doc_id)` or `run_materialize_pipeline_for_assets(doc_id, assets)`
4. Sleep `poll_interval` seconds, repeat

## Troubleshooting

### hermes_vec_scan broken (2026-06-09)

**Symptom**: `Error executing tool hermes_vec_scan: run_index_pipeline() missing 1 required positional argument: 'doc_id'`

**Workaround**: Write raw files directly, trigger per-doc indexing:
```bash
export QURO_STORAGE_ROOT=/data/hermes/quro-doc/storage
quro-doc vec index --project mlx-lm <doc_id>
```

Or skip vector indexing entirely — use `hermes_get` for retrieval by known doc_id.

### QURO_STORAGE_ROOT not in MCP config

**Symptom**: Documents land in `.quro_context/docs/` under CWD instead of expected location.

**Fix**: Verify Hermes MCP config has QURO_STORAGE_ROOT:
```bash
grep -A8 "quro-doc:" ~/.hermes/config.yaml | grep QURO_STORAGE_ROOT
```
If missing, add it under `env:` and restart MCP server.

### MCP server confusion — wrong server tested

**Symptom**: `hermes mcp test quro-doc` shows 10 tools but no `hermes_*` tools visible.

**Fix**: `hermes_*` tools live on `hermes-quro-doc` server. Test correct server:
```bash
hermes mcp test hermes-quro-doc
```

### Storage refactor — docs/ vs raw/

New writes go to `docs/`, legacy docs in `raw/`. When files appear missing:
```bash
ls {QURO_STORAGE_ROOT}/docs/       # new docs
ls {QURO_STORAGE_ROOT}/raw/        # legacy docs
```

### quro_doc_search returns empty

Check vector index:
```bash
quro-doc vec stats
```

Rebuild if needed:
```bash
quro-doc vec scan
```

### Worker not processing jobs

Check queue:
```bash
ls {QURO_STORAGE_ROOT}/jobs/
```

Run worker manually and watch output:
```bash
cd /path/to/quro-doc && source .venv/bin/activate
python -m src.quro_doc.workers.worker
```

## Storage Management

### Runtime data location (Hermes)

```
hermes/quro-doc/storage/
├── docs/              # Current writes (<id>.txt + <id>.json)
├── raw/               # Legacy documents (read-only fallback)
├── assets/            # Binary assets
├── index/             # Vector indexes
├── distill/           # LLM summaries
├── link/              # Document relations
├── jobs/              # Pending async jobs
├── events/            # Change event log
├── registry/          # Consumer declarations
├── logs/              # Runtime logs
└── projects/          # Multi-tenant project root
```

### Post-write verification

After `quro_doc_add` returns `accepted`, verify:
```bash
# Check file exists
ls {QURO_STORAGE_ROOT}/docs/{doc_id}.txt

# Check file size
wc -c {QURO_STORAGE_ROOT}/docs/{doc_id}.txt

# Check metadata
cat {QURO_STORAGE_ROOT}/docs/{doc_id}.json | python -m json.tool | head -20
```

### Project management

List all documents in a project:
```bash
# Via MCP:
mcp_quro_doc_quro_doc_list_doc_ids(limit=100)

# Via filesystem:
ls {QURO_STORAGE_ROOT}/docs/
```

List all projects:
```bash
ls {QURO_STORAGE_ROOT}/projects/
```

## CLI Reference

```bash
# Add document
quro-doc add --body "text" --title "Title" --topic "topic" --intent "analysis" --tag "tag1"

# Add from file
quro-doc add --body-file path.md --title "Title" --topic "topic" --intent "analysis" --tag "tag"

# Add with explicit doc_id
quro-doc add --doc-id my-id --body "text" --title "T" --topic "t" --intent "i" --tag "x"

# Search
quro-doc search "query text" --top-k 5

# Get by ID
quro-doc get <doc_id>

# Vector operations
quro-doc vec stats
quro-doc vec scan
quro-doc vec index <doc_id>
quro-doc vec query "query text" --top-k 5

# Start MCP server
quro-doc mcp --transport stdio
quro-doc hermes-mcp --transport stdio

# Asset materialization
quro-doc materialize run --doc-id <id>
quro-doc materialize worker --interval 5

# OKF operations
quro-doc okf ingest --bundle /path/to/bundle --project my-project
quro-doc okf export --project my-project --out /path/to/output

# Worker
quro-doc worker --poll-interval 5
```

## Further Reading

- `../docs/architecture.md` — boundaries, invariants, component map
- `../docs/dataflow.md` — write/read/asset/async paths
- `../docs/entity-model.md` — entities, storage, source map
- `../skills/quro-doc-agent.md` — agent usage guide
- `../skills/quro-doc-developer.md` — extending quro-doc
