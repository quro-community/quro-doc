from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Protocol, Any
import os, json


class HasConfig(Protocol):
    @classmethod
    def from_central(cls, central: QuroConfig) -> HasConfig:
        ...


@dataclass
class ScoreWeight:
    name: str
    weight: float
    required: bool = False


@dataclass
class QuroConfig:
    # ── Storage ──
    storage_root: str = ".quro_context/docs"
    log_dir: str = ".quro_context/logs/quro-docs"

    # ── Embedding ──
    embedding_model: str = "llama/embeddinggemma"
    embedding_api_url: str = "http://localhost:20128/v1/embeddings"

    # ── Queue ──
    queue_backend: str = "redis"
    redis_url: str = "redis://localhost:6379/0"

    # ── Query Pipeline ──
    use_scoring: bool = True
    use_reranker: bool = False
    scorer_weights: List[ScoreWeight] = field(default_factory=lambda: [
        ScoreWeight(name="vector", weight=1.0, required=True),
        ScoreWeight(name="tag", weight=0.3),
    ])
    rerank_model: str = "gpustack/bge-reranker-v2-m3"
    rerank_api_url: str = "http://localhost:8002/v1/rerank"
    rerank_top_k: int = 20

    # ── View ──
    view_name: str = "default-view"

    # ── Standard View ──
    standard_view_enabled: bool = True
    standard_view_sections: List[str] = field(default_factory=lambda: [
        "Goal", "Summary", "Architecture", "Dir Structure", "DataFlow", "Files"
    ])
    standard_view_planner_strategy: str = "heuristic"
    standard_view_max_sections: int = 5
    standard_view_min_evidence_per_section: int = 1
    standard_view_max_evidence_per_section: int = 5
    standard_view_enable_summarization: bool = False
    standard_view_token_budget: int = 1200

    # ── Artifact ──
    artifact_store_enabled: bool = False
    artifact_feature_weight: float = 0.0
    artifact_schema_registry_path: str = ""
    artifact_rebuild_on_migration: bool = False
    artifact_retention_aligned_with_replay: bool = True

    # ── Trace ──
    trace_retention_days: int = 90
    hot_doc_scan_interval_minutes: int = 360

    # ── Misc ──
    enable_haystack: bool = True
    log_level: str = "INFO"

    def snapshot(self) -> "RuntimePolicy":
        from .trace.model import RuntimePolicy
        return RuntimePolicy(
            scorer_weights={w.name: w.weight for w in self.scorer_weights},
            pruner_strategy="topk_mmr",
            pruner_params={"top_k": 12, "lambda": 0.7},
            token_budget=self.standard_view_token_budget,
            diversity_lambda=None,
            artifact_feature_weight=self.artifact_feature_weight,
        )

    def to_runtime_versions(self) -> "RuntimeVersions":
        from .trace.model import RuntimeVersions
        return RuntimeVersions(
            embedding_model=self.embedding_model,
            reranker_model=self.rerank_model,
            prompt_template_version="standard_view_v1",
            artifact_pipeline_version="1.0.0",
            scoring_engine_version="v1",
        )

    @classmethod
    def load(cls, env_file: Optional[str] = None) -> QuroConfig:
        from dotenv import load_dotenv
        if env_file:
            load_dotenv(env_file)
        else:
            _root = os.path.abspath(os.path.join(
                os.path.dirname(__file__), "..", ".."
            ))
            candidate = os.path.join(_root, ".env")
            if os.path.exists(candidate):
                load_dotenv(candidate)

        sections_raw = os.getenv("STANDARD_VIEW_SECTIONS",
            '["Goal","Summary","Architecture","Dir Structure","DataFlow","Files"]')
        try:
            sections = json.loads(sections_raw)
        except Exception:
            sections = ["Goal", "Summary", "Architecture", "Dir Structure", "DataFlow", "Files"]

        weights_raw = os.getenv("QUERY_SCORER_WEIGHTS",
            '[{"name":"vector","weight":1.0,"required":true},{"name":"tag","weight":0.3}]')
        try:
            weights = [ScoreWeight(**w) for w in json.loads(weights_raw)]
        except Exception:
            weights = [ScoreWeight(name="vector", weight=1.0, required=True)]

        return cls(
            storage_root=os.getenv("QURO_STORAGE_ROOT", ".quro_context/docs"),
            log_dir=os.getenv("QURO_LOG_DIR", ".quro_context/logs/quro-docs"),
            embedding_model=os.getenv("EMBEDDING_MODEL", "llama/embeddinggemma"),
            embedding_api_url=os.getenv("EMBEDDING_API_URL", "http://localhost:20128/v1/embeddings"),
            queue_backend=os.getenv("QUEUE_BACKEND", "redis"),
            redis_url=os.getenv("REDIS_URL", "redis://localhost:6379/0"),
            use_scoring=os.getenv("QUERY_USE_SCORING", "true").lower() == "true",
            use_reranker=os.getenv("QUERY_USE_RERANKER", "false").lower() == "true",
            scorer_weights=weights,
            rerank_model=os.getenv("RERANK_MODEL", "gpustack/bge-reranker-v2-m3"),
            rerank_api_url=os.getenv("RERANK_API_URL", "http://localhost:8002/v1/rerank"),
            rerank_top_k=int(os.getenv("RERANK_TOP_K", "20")),
            view_name=os.getenv("VIEW_NAME", "default-view"),
            standard_view_enabled=os.getenv("STANDARD_VIEW_ENABLED", "true").lower() == "true",
            standard_view_sections=sections,
            standard_view_planner_strategy=os.getenv("STANDARD_VIEW_PLANNER_STRATEGY", "heuristic"),
            standard_view_max_sections=int(os.getenv("STANDARD_VIEW_MAX_SECTIONS", "5")),
            standard_view_min_evidence_per_section=int(os.getenv("STANDARD_VIEW_MIN_EVIDENCE_PER_SECTION", "1")),
            standard_view_max_evidence_per_section=int(os.getenv("STANDARD_VIEW_MAX_EVIDENCE_PER_SECTION", "5")),
            standard_view_enable_summarization=os.getenv("STANDARD_VIEW_ENABLE_SUMMARIZATION", "false").lower() == "true",
            standard_view_token_budget=int(os.getenv("STANDARD_VIEW_TOKEN_BUDGET", "1200")),
            artifact_store_enabled=os.getenv("QURO_ARTIFACT_STORE_ENABLED", "false").lower() == "true",
            artifact_feature_weight=float(os.getenv("QURO_ARTIFACT_FEATURE_WEIGHT", "0.0")),
            artifact_schema_registry_path=os.getenv("QURO_ARTIFACT_SCHEMA_REGISTRY_PATH", ""),
            artifact_rebuild_on_migration=os.getenv("QURO_ARTIFACT_REBUILD_ON_MIGRATION", "false").lower() == "true",
            artifact_retention_aligned_with_replay=os.getenv("QURO_ARTIFACT_RETENTION_ALIGNED_WITH_REPLAY", "true").lower() == "true",
            trace_retention_days=int(os.getenv("QURO_TRACE_RETENTION_DAYS", "90")),
            hot_doc_scan_interval_minutes=int(os.getenv("QURO_HOT_DOC_SCAN_INTERVAL_MINUTES", "360")),
            enable_haystack=os.getenv("ENABLE_HAYSTACK", "true").lower() == "true",
            log_level=os.getenv("LOG_LEVEL", "INFO"),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "storage_root": self.storage_root,
            "log_dir": self.log_dir,
            "embedding_model": self.embedding_model,
            "queue_backend": self.queue_backend,
            "use_scoring": self.use_scoring,
            "use_reranker": self.use_reranker,
            "scorer_weights": [vars(w) for w in self.scorer_weights],
            "view_name": self.view_name,
            "standard_view_enabled": self.standard_view_enabled,
            "standard_view_sections": self.standard_view_sections,
            "standard_view_planner_strategy": self.standard_view_planner_strategy,
            "standard_view_max_sections": self.standard_view_max_sections,
            "standard_view_min_evidence_per_section": self.standard_view_min_evidence_per_section,
            "standard_view_max_evidence_per_section": self.standard_view_max_evidence_per_section,
            "standard_view_token_budget": self.standard_view_token_budget,
            "artifact_store_enabled": self.artifact_store_enabled,
            "artifact_feature_weight": self.artifact_feature_weight,
            "artifact_schema_registry_path": self.artifact_schema_registry_path,
            "artifact_rebuild_on_migration": self.artifact_rebuild_on_migration,
            "artifact_retention_aligned_with_replay": self.artifact_retention_aligned_with_replay,
            "trace_retention_days": self.trace_retention_days,
            "hot_doc_scan_interval_minutes": self.hot_doc_scan_interval_minutes,
            "log_level": self.log_level,
        }
