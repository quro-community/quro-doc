# SKILL: Explore (File Search Specialist)
版本：v1 — 与 quro-doc 当前设计对齐

说明
---
此 SKILL.md 为专门用于在 quro-doc 仓库中执行“探索 / 文件检索 / 代码脉络追踪”的操作规范。它把原先 ICCCS 风格的探索流程与 quro-doc 的实现约束（MCP 接口、存储根、pipeline、adapter）结合起来，确保每次探索都能产出可回放、可演化的知识提交（icccs_commit）并明确哪些旧知识被 supersede（取代）。

请在每次探索任务中严格遵守“Query → Explore → Commit”流程（不可跳过任何步骤）。

前置条件
---
- 熟悉 quro-doc 设计约束（查看：docs/prototypes/00-prototype.md、docs/prototypes/00-tasks.md、docs/designs/QURO-DESIGN.md）
- 仓库关键路径（必须重点检查）：
  - src/quro_doc/api.py (quro_doc_add, quro_doc_search)
  - src/quro_doc/storage.py (QURO_STORAGE_ROOT, raw/index/distill/link/jobs)
  - src/quro_doc/adapters/haystack_adapter.py
  - src/quro_doc/pipelines/*.py (index/distill/link)
  - src/quro_doc/workers/worker.py
  - .quro_context/docs/（运行时存储根；QURO_STORAGE_ROOT）
  - docs/api/quro_mcp_api.md（MCP API 规范）
  - docs/designs/QURO-DESIGN.md（设计文档）
  - .env.example（配置集中化）
- ICCCS 工具：icccs_query / icccs_commit（下面用法示例）

核心约束（必须遵守）
---
1. 每次探索“必须先”运行 icccs_query(mode="active_only")，以获取当前被接受的“活跃”知识。
2. 探索完成后“必须”运行 icccs_commit(...) 把发现提交到知识图谱，明确指出 supersedes（若适用）。
3. 提交里必须列出确切文件路径、被引用的函数/逻辑片段，以及形成结论的证据片段（行号/代码片段或 JSON）。
4. 若发现新知识取代旧知识，supersedes 必须包含被取代 commit id（或 atom id）。

流程（强制三步）
---

STEP 1 — Query ICCCS（必需）
- 目的：在开始探索前读取“当前被接受的事实/假设”。
- 调用示例：
  icccs_query(question="验证 quro_doc_add 的幂等语义与 jobs 流程", mode="active_only")
- 解析：检查 icccs_query 返回的 active context_files 与 diff，确定已有结论与侧重点（例如：之前结论“quro_doc_add 返回 job_id”是否仍为 active）。

注意：
- 只在确定需要历史上下文时使用 mode="full_history"。
- 记录 icccs_query 返回的 context_files 列表（用于后续 icccs_commit 的 context_files 字段）。

STEP 2 — Explore（必需）
- 以 icccs_query 返回的“活跃知识”为基线进行文件搜索与代码阅读。仅当基线不完整/不一致时才扩大搜索到历史（full_history）。
- 优先目标（按优先级）：
  1. 验证 MCP 接口实现与 docs/api/quro_mcp_api.md 的一致性
     - 匹配点：函数名、输入/输出字段、错误码、幂等语义、job 写入位置
     - 关键路径：src/quro_doc/api.py -> quro_doc_add, quro_doc_search
  2. 验证 Raw 存储与 QURO_STORAGE_ROOT 的使用
     - 关键路径：src/quro_doc/storage.py 与 .env.example 中 QURO_STORAGE_ROOT
     - 检查 raw/<doc_id>.txt 与 raw/<doc_id>.json 的写入逻辑
  3. 验证 Job lifecycle 与 worker 行为
     - 关键路径：src/quro_doc/api.py (enqueue)、src/quro_doc/workers/worker.py（pop/process）
     - 检查 jobs 存放（${QURO_STORAGE_ROOT}/jobs/<job_id>.json）与 Redis fallback 逻辑
  4. 验证 pipelines 与适配器
     - 关键路径：src/quro_doc/pipelines/*.py、src/quro_doc/adapters/haystack_adapter.py
     - 搜索 embedding/向量存储占位、distill 写入路径、link pipeline 输出（link relations）
  5. 验证 docs 一致性（设计文档与实现）
     - docs/designs/QURO-DESIGN.md, docs/api/quro_mcp_api.md, README.md, .env.example

- 推荐搜索命令/模式（示例）
  - Glob（查找文件）
    - src/quro_doc/**/*.py
    - docs/**/*.md
  - grep / regex（查找行为）
    - 查找 job 写入：grep -R "jobs" src/quro_doc
    - 查找 enqueue/redis：grep -R "redis" src/quro_doc
    - 查找 QURO_STORAGE_ROOT：grep -R "QURO_STORAGE_ROOT" -n
    - 查找 quro_doc_add 定义：grep -n "def quro_doc_add" -R
  - 精准正则示例（查找 doc link 模式）：
    - r"re.finditer\(r\"doc:([a-f0-9\\-]+)\""  （用来定位 link_pipeline 中的 naive 模式）
  - 关键函数/变量直接打开定位：
    - src/quro_doc/api.py:quro_doc_add
    - src/quro_doc/storage.py:write_raw_doc, read_raw_doc
    - src/quro_doc/workers/worker.py:run_worker,_pop_job_from_dir,_pop_job_from_redis
    - src/quro_doc/adapters/haystack_adapter.py:to_haystack,from_haystack

- 探索目标产出（必须包含下列要素）
  - 所检文件的精确路径（例：src/quro_doc/api.py）
  - 关键行或函数名称（例：quro_doc_add — lines 1-100）
  - 所观察到的行为与与期望契约的差异（例如：幂等逻辑、错误码缺失、作业 status 未写回）
  - 若发现行为修正建议，写明改动片段（diff 样式或补丁示例）
  - 如果新发现使之前的 active 知识失效，记录被 supersede 的 commit id（若已知）

STEP 3 — Commit Findings（必需）
- 使用 icccs_commit 提交知识，同时说明是否 supersedes 之前的知识。
- 提交模板（必须严格遵循结构）：

icccs_commit(
  question="<精炼后的探索问题，例如 'quro_doc_add 是否实现幂等并写入 jobs dir' >",
  answer="<实现级别结论，包含证据、行为描述与建议>",
  diff="<可选：建议修复的补丁或代码段（尽可能精确）>",
  context_files=[
    "src/quro_doc/api.py",
    "src/quro_doc/storage.py",
    "src/quro_doc/workers/worker.py",
    "src/quro_doc/pipelines/link_pipeline.py",
    "docs/api/quro_mcp_api.md"
  ],
  topic="fact",
  supersedes=[ "<commit-id-如果本次发现取代先前结论, 否则 None或省略>" ]
)

- 提交要求（硬性）：
  - answer 必须包含具体实现证据（代码行/JSON snippet 或文件路径+行号）
  - context_files 列出所有引用到的文件路径（精确路径）
  - 若本次发现修正或更新了先前结论，一定要在 supersedes 数组中列出被取代的 commit id；若没有则 omit 或留空
  - diff 字段应包含用于修复问题的最小可行补丁（片段即可），便于后续自动化创建 PR

发现示例（结构化）
---
示例 1：发现 quro_doc_add 幂等问题
- question: "quro_doc_add 是否在 write_raw_doc 已存在时返回 exists？"
- answer: "quro_doc_add 在 src/quro_doc/api.py 中通过 write_raw_doc 返回布尔值判断是否写入。write_raw_doc 在 raw/<doc_id>.txt 存在时直接返回 False。结论：幂等通过 doc_id 存在检查实现。证据: src/quro_doc/storage.py write_raw_doc 行 12-28，src/quro_doc/api.py quro_doc_add 行 40-70。建议：添加 machine-readable code 字段 'code':'exists' 到返回值中。"
- context_files: ["src/quro_doc/api.py","src/quro_doc/storage.py"]
- diff: (提供小补丁)
- supersedes: [ "<之前的 commit-id>" ] if this invalidates prior claim

失败条件（若发生则作业无效）
---
- 未先运行 icccs_query 即开始探索。
- 探索结束却未执行 icccs_commit。
- icccs_commit 缺少 context_files 或 answer 不包含实现级证据（文件路径/行号）。
- 若本次结论取代旧结论却未在 supersedes 中列出对应 commit id。

检索/分析速查表（针对 quro-doc）
---
- 查找 MCP 接口实现与文档不一致：
  - grep -n "quro_doc_add" src | xargs -I{} sed -n '1,160p' {}
  - 打开 docs/api/quro_mcp_api.md 核对字段名（body/doc_id/job_id/status）
- 查找 jobs 写入与队列逻辑：
  - grep -R "jobs" src | grep -v "__pycache__"
  - 查看 src/quro_doc/api.py 中 _enqueue_job 的实现与 src/quro_doc/workers/worker.py 的读取逻辑
- 查找 storage 路径与 append-only 规则：
  - sed -n '1,200p' src/quro_doc/storage.py
  - 校验 raw/<doc_id>.txt 写入分支是否有覆盖逻辑
- 查找 haystack 适配器使用点（确保未作为核心模型）：
  - grep -R "to_haystack" -n
  - 确认 haystack_adapter.py 中 ENABLE_HAYSTACK 开关与降级路径
- 查找 link pipeline 的规则（是否有 naive 'doc:<id>' 模式）：
  - sed -n '1,200p' src/quro_doc/pipelines/link_pipeline.py
  - 正则匹配 r"doc:([a-f0-9\\-]+)"

提交范例（简短）
---
icccs_query(question="quro_doc_add 幂等实现是否完备？", mode="active_only")

...（分析）...

icccs_commit(
  question="quro_doc_add 在存在 doc 时是否正确返回 exists 并避免覆盖 raw body？",
  answer="是。证据：src/quro_doc/storage.py write_raw_doc 实现（见 lines 12-28），当 txt 存在时返回 False；src/quro_doc/api.py quro_doc_add 根据返回值返回 {'status':'exists', 'doc_id':...}。建议：在返回 payload 中添加 machine-readable 'code':'exists' 字段以便客户端 programmatic 识别。",
  diff="--- a/src/quro_doc/api.py\n+++ b/src/quro_doc/api.py\n@@\n-    if not wrote:\n-        return {\"status\": \"exists\", \"doc_id\": doc_id, \"message\": \"Document already exists. No new write performed.\"}\n+    if not wrote:\n+        return {\"status\": \"exists\", \"code\":\"exists\", \"doc_id\": doc_id, \"message\": \"Document already exists. No new write performed.\"}\n",
  context_files=[\"src/quro_doc/api.py\",\"src/quro_doc/storage.py\"],
  topic=\"fact\",
  supersedes=[\"commit-id-abc123\"]  # 若替代了之前的结论
)

尾声/最佳实践
---
- 探索时尽量小步提交（每次变更结论一个 icccs_commit）。这样更利于知识演化追踪与回滚。
- 在 icccs_commit 的 answer 中优先以事实为主（文件+行号+简短解释），避免模糊描述。
- 如果发现需要大范围修复（例如改变核心 contract），标注为高风险并建议关联一个 PR/issue（记录到 docs/designs/QURO-DESIGN.md 的变更草案）。

--- 
（结束）
此 SKILL.md 必须放置在仓库：skills/explore/SKILL.md，并作为探索 agent 的运行规范。任何不遵守“Query → Explore → Commit”流程的探索都视为失败。祝探索顺利。