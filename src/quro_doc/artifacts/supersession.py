from __future__ import annotations
from datetime import datetime
from typing import Optional

from .store import ArtifactStore, Artifact


class SupersessionGraph:
    def __init__(self, store: ArtifactStore):
        self._store = store

    def resolve(
        self,
        artifact_id: str,
        at_time: datetime | None = None,
    ) -> Artifact | None:
        artifact = self._store.load(artifact_id)
        if artifact is None:
            return None

        if at_time is not None and artifact.created_at and artifact.created_at > at_time:
            candidates = self._superseding_path(artifact_id)
            for c in reversed(candidates):
                if c.created_at and c.created_at <= at_time:
                    return c
            return None

        latest = artifact
        while True:
            by_type = self._store.list_by_type(latest.artifact_type)
            next_art = None
            for a in by_type:
                if a.supersedes == latest.artifact_id:
                    if next_art is None or (a.created_at and next_art.created_at and a.created_at > next_art.created_at):
                        next_art = a
            if next_art is None:
                break
            latest = next_art

        return latest

    def lineage(self, artifact_id: str) -> list[Artifact]:
        artifact = self._store.load(artifact_id)
        if artifact is None:
            return []

        chain: list[Artifact] = []

        current = artifact
        seen: set[str] = set()
        while current and current.artifact_id not in seen:
            seen.add(current.artifact_id)
            chain.append(current)
            parent_id = current.supersedes
            if parent_id is None:
                break
            current = self._store.load(parent_id)

        chain.reverse()

        seen.clear()
        current = artifact
        while current and current.artifact_id not in seen:
            seen.add(current.artifact_id)
            by_type = self._store.list_by_type(current.artifact_type)
            next_art = None
            for a in by_type:
                if a.supersedes == current.artifact_id and a.artifact_id not in seen:
                    if next_art is None or (a.created_at and next_art.created_at and a.created_at > next_art.created_at):
                        next_art = a
            if next_art is None:
                break
            chain.append(next_art)
            current = next_art

        return chain

    def _superseding_path(self, artifact_id: str) -> list[Artifact]:
        result: list[Artifact] = []
        current = self._store.load(artifact_id)
        seen: set[str] = set()
        while current and current.artifact_id not in seen:
            seen.add(current.artifact_id)
            result.append(current)
            by_type = self._store.list_by_type(current.artifact_type)
            next_art = None
            for a in by_type:
                if a.supersedes == current.artifact_id:
                    if next_art is None or (a.created_at and next_art.created_at and a.created_at > next_art.created_at):
                        next_art = a
            current = next_art
        return result
