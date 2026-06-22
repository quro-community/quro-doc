from __future__ import annotations
import os
import json
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional, Callable

from ..config import QuroConfig
from .provenance import ArtifactProvenance


class SchemaValidationError(Exception):
    pass


class ImmutabilityError(Exception):
    pass


@dataclass
class Artifact:
    artifact_id: str
    artifact_type: str
    schema_version: str = ""
    kind: str = "evidence"
    source_docs: list[str] | None = None
    content: str = ""
    embedding: list[float] | None = None
    confidence: float = 0.0
    freshness: float = 0.0
    created_at: datetime | None = None
    model_version: str = ""
    expires_at: datetime | None = None
    ttl_days: int | None = None
    provenance: ArtifactProvenance | None = None
    supersedes: str | None = None

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now(timezone.utc)
        if self.source_docs is None:
            self.source_docs = []
        if not self.schema_version:
            self.schema_version = "1.0"
        if self.ttl_days is None and self.expires_at is None:
            self.ttl_days = 365
        if self.ttl_days is not None and self.expires_at is None:
            self.expires_at = self.created_at + timedelta(days=self.ttl_days)


PER_DOC_CAP = 20
TYPE_QUOTA_RATIO = 0.5


class ArtifactStore:
    def __init__(self, config: Optional[QuroConfig] = None):
        self.config = config or QuroConfig.load()
        self.root = Path(self.config.storage_root) / "artifacts"

    def _artifact_path(self, artifact_type: str, artifact_id: str) -> Path:
        tdir = self.root / artifact_type
        tdir.mkdir(parents=True, exist_ok=True)
        return tdir / f"{artifact_id}.json"

    def save(self, artifact: Artifact) -> str:
        self._validate_schema(artifact)
        self._enforce_immutability(artifact)
        self._evict_if_needed(artifact)
        path = self._artifact_path(artifact.artifact_type, artifact.artifact_id)
        data = asdict(artifact)
        data["created_at"] = artifact.created_at.isoformat().replace("+00:00", "Z") if artifact.created_at else None
        data["expires_at"] = artifact.expires_at.isoformat().replace("+00:00", "Z") if artifact.expires_at else None
        if artifact.provenance:
            data["provenance"] = asdict(artifact.provenance)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return artifact.artifact_id

    def _validate_schema(self, artifact: Artifact) -> None:
        if not artifact.schema_version:
            raise SchemaValidationError(
                f"schema_version required for artifact {artifact.artifact_id}"
            )

    def _enforce_immutability(self, artifact: Artifact) -> None:
        path = self._artifact_path(artifact.artifact_type, artifact.artifact_id)
        if path.exists():
            existing = self._deserialize(path)
            if existing.artifact_id == artifact.artifact_id:
                return

    def load(self, artifact_id: str) -> Artifact | None:
        for tdir in self.root.iterdir():
            if not tdir.is_dir():
                continue
            path = tdir / f"{artifact_id}.json"
            if path.exists():
                return self._deserialize(path)
        return None

    def list_by_type(self, artifact_type: str) -> list[Artifact]:
        if not self.root.exists():
            return []
        tdir = self.root / artifact_type
        if not tdir.exists():
            return []
        results = []
        for path in sorted(tdir.glob("*.json")):
            try:
                results.append(self._deserialize(path))
            except Exception:
                continue
        return results

    def list_by_doc(self, doc_id: str) -> list[Artifact]:
        if not self.root.exists():
            return []
        results = []
        for tdir in self.root.iterdir():
            if not tdir.is_dir():
                continue
            for path in tdir.glob("*.json"):
                try:
                    art = self._deserialize(path)
                    if doc_id in (art.source_docs or []):
                        results.append(art)
                except Exception:
                    continue
        return results

    def rebuild_type(
        self,
        artifact_type: str,
        new_version: str,
        source_fn: Callable[[str, Artifact | None], Artifact],
    ) -> int:
        old_artifacts = self.list_by_type(artifact_type)
        count = 0
        for old in old_artifacts:
            new = source_fn(artifact_type, old)
            new.schema_version = new_version
            if old and old.artifact_id:
                new.supersedes = old.artifact_id
            self.save(new)
            count += 1
        return count

    def _deserialize(self, path: Path) -> Artifact:
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("created_at"):
            data["created_at"] = datetime.fromisoformat(data["created_at"].replace("Z", "+00:00"))
        if data.get("expires_at"):
            data["expires_at"] = datetime.fromisoformat(data["expires_at"].replace("Z", "+00:00"))
        if data.get("provenance"):
            from .provenance import ArtifactProvenance
            data["provenance"] = ArtifactProvenance(**data["provenance"])
        return Artifact(**data)

    def _evict_if_needed(self, incoming: Artifact) -> None:
        for doc_id in (incoming.source_docs or []):
            by_doc = self.list_by_doc(doc_id)
            if len(by_doc) >= PER_DOC_CAP:
                by_doc.sort(key=lambda a: a.confidence * a.freshness)
                for old in by_doc[:len(by_doc) - PER_DOC_CAP + 1]:
                    path = self._artifact_path(old.artifact_type, old.artifact_id)
                    if path.exists():
                        path.unlink()

        by_type = self.list_by_type(incoming.artifact_type)
        quota = int(PER_DOC_CAP * TYPE_QUOTA_RATIO)
        if len(by_type) >= quota:
            by_type.sort(key=lambda a: a.confidence * a.freshness)
            for old in by_type[:len(by_type) - quota + 1]:
                path = self._artifact_path(old.artifact_type, old.artifact_id)
                if path.exists() and old.artifact_id not in (incoming.source_docs or []):
                    path.unlink()
