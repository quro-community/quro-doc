---
name: quro-doc-materialize
description: "quro-doc add → materialize workflow for documents containing images/assets: CLI-based add with image media extraction, proxy workaround, and asset download verification"
version: 1.0.0
author: quro
license: MIT
platforms: [macos, linux]
metadata:
  hermes:
    tags: [quro-doc, materialize, assets, images, proxy, skill]
    related_skills: [quro-doc]
---

# quro-doc-materialize — Asset Materialization Workflow

This skill covers the end-to-end workflow for adding a document **with images or other media assets** to a quro-doc project using the CLI, then downloading those assets via `materialize`.

Use this skill when:
- The source document contains `![Image](https://...)` or similar media references
- You need to use `quro-doc add` CLI (not MCP)
- Previous attempts hit the `socksio` / SOCKS proxy error during materialize

## One-Time Prerequisites

### quro-doc CLI binary
```bash
# The CLI lives at:
quro/bin/quro-doc

# Or set in PATH as needed.
```

### QURO_STORAGE_ROOT
Must point to the project's storage root, e.g.:
```bash
export QURO_STORAGE_ROOT=hermes/quro-doc/storage/projects/notebook
```

The project directory must already have the expected subdirectory structure:
```
{QURO_STORAGE_ROOT}/
├── docs/       # Written documents (.txt body + .json metadata)
├── raw/        # Legacy documents
├── assets/     # Downloaded media files
├── index/      # Vector indexes
├── jobs/       # Async job queue
├── events/     # Change events
└── ...
```

## Workflow: Add Document with Images

### Step 1 — Read the source file

Inspect the markdown file to extract metadata from YAML frontmatter / code block:

```bash
head -20 /path/to/source.md
```

Required fields for `quro-doc add`:
- `--title` — display title (required)
- `--topic` — main subject area (required)
- `--intent` — one of: `specification`, `analysis`, `how-to`, `reference`, `design`, `tutorial`, `troubleshooting`, `overview`, `api-reference`, `configuration`, `testing`, `deployment`, `security`, `performance`, `migration`
- `--tag` — can be repeated (required, at least 1)

**Important**: `--intent` is restricted to the enum above. Long descriptive strings from YAML are rejected with a validation error. Pick the closest match manually.

**Important**: `--body-file` does NOT parse YAML frontmatter. The entire file is read as body. Metadata must be passed via CLI flags.

### Step 2 — Run quro-doc add

```bash
QURO_STORAGE_ROOT=/path/to/project/storage \
quro/bin/quro-doc add \
  --body-file /path/to/source.md \
  --title "Document Title" \
  --topic "Topic Area" \
  --intent "reference" \
  --tag "Tag1" \
  --tag "Tag2" \
  ...
```

On success, returns:
```json
{
  "status": "accepted",
  "doc_id": "<uuid>",
  "message": "Document accepted.",
  "protocol_version": "2.0.0-draft"
}
```

The `MarkdownWriter` automatically:
- Parses the markdown for `![Image](url)` references
- Registers each URL as an **AssetPromise**
- Rewrites URLs to `asset://{asset_id}` placeholders in the stored body
- Returns the doc_id for subsequent materialization

### Step 3 — Verify the write

```bash
ls -la {QURO_STORAGE_ROOT}/docs/{doc_id}.*
wc -c {QURO_STORAGE_ROOT}/docs/{doc_id}.txt
```

Expect: `{doc_id}.txt` (body) + `{doc_id}.json` (metadata).

### Step 4 — Materialize assets

**Syntax**: uses `--doc-id` as a *flag*, NOT a positional argument:

```bash
# WRONG (unrecognized arguments error):
quro-doc materialize run {doc_id}

# RIGHT:
QURO_STORAGE_ROOT=/path/to/project/storage \
quro/bin/quro-doc materialize run --doc-id {doc_id}
```

## Known Pitfalls

### SOCKS proxy → `socksio` not installed

If the environment has `all_proxy=socks5://127.0.0.1:7890`, `httpx` (the default materializer) fails with:

```
Using SOCKS proxy, but the 'socksio' package is not installed.
```

**Two solutions:**

1. **Unset proxy vars for materialize** (quick, no install):
   ```bash
   unset http_proxy https_proxy all_proxy HTTP_PROXY HTTPS_PROXY ALL_PROXY
   ```

2. **Install socksio** (permanent):
   ```bash
   pip install socksio
   # or pip install httpx[socks]
   ```

Choose based on whether you want proxy tunnel or direct download.

### HTTP_PROXY vars: check both uppercase and lowercase
Always check both:
```bash
echo "http_proxy=$http_proxy"
echo "HTTP_PROXY=$HTTP_PROXY"
echo "all_proxy=$all_proxy"
echo "ALL_PROXY=$ALL_PROXY"
```
`httpx` reads the lower-case vars.

### `materialize run --doc-id` is a flag, not positional
If you pass the doc_id as a positional argument, you get:
```
quro-doc: error: unrecognized arguments: <uuid>
```
Always use `--doc-id <uuid>`.

## Verification — Assets Downloaded

After successful materialize:
```bash
ls -la {QURO_STORAGE_ROOT}/assets/ | head -20
```

Each asset has two files:
- `{asset_id}` — the raw binary data (JPEG, PNG, etc.)
- `{asset_id}.meta.json` — metadata (source_url, content_type, size)

Confirm the count matches the images in the document.

## Implementation Detail: How Materialize Works

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

## Differences from MCP add

| Aspect | CLI (`quro-doc add`) | MCP (`quro_doc_add`) |
|--------|-----------------------|----------------------|
| Media extraction | Automatic via MarkdownWriter | Same code path |
| Body source | `--body-file` or `--body` | `file_path` or `body` in payload |
| Asset handling | Auto-register + URL rewrite | Auto-register + URL rewrite |
| After add | Run `materialize run --doc-id` manually | Worker picks up job queue |
| Env setup | Set `QURO_STORAGE_ROOT` per command | From MCP config |
