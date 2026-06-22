from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any
from pathlib import Path
import json


class SchemaValidationError(Exception):
    pass


@dataclass
class ArtifactFieldDef:
    name: str
    type: str


@dataclass
class ArtifactSchemaVersion:
    version: str
    fields: list[ArtifactFieldDef] = field(default_factory=list)
    migration_from: str | None = None
    migration_notes: str = ""


@dataclass
class ArtifactTypeSchema:
    artifact_type: str
    versions: list[ArtifactSchemaVersion] = field(default_factory=list)


_TYPE_MAP = {
    "string": str,
    "list<string>": list,
    "float": float,
    "int": int,
    "bool": bool,
    "Entity": dict,
    "list<Entity>": list,
}


class ArtifactSchemaRegistry:
    _schemas: dict[str, dict[str, ArtifactSchemaVersion]] = {}

    def register(self, schema: ArtifactTypeSchema) -> None:
        by_version: dict[str, ArtifactSchemaVersion] = {}
        for v in schema.versions:
            by_version[v.version] = v
        self._schemas[schema.artifact_type] = by_version

    def get_schema(self, artifact_type: str, version: str) -> ArtifactSchemaVersion | None:
        by_version = self._schemas.get(artifact_type)
        if by_version is None:
            return None
        return by_version.get(version)

    def list_types(self) -> list[str]:
        return list(self._schemas.keys())

    def load_from_path(self, path: str | Path) -> None:
        path = Path(path)
        if not path.exists():
            return
        for fpath in sorted(path.glob("*.json")):
            try:
                data = json.loads(fpath.read_text(encoding="utf-8"))
                versions = [
                    ArtifactSchemaVersion(
                        version=v["version"],
                        fields=[ArtifactFieldDef(**f) for f in v.get("fields", [])],
                        migration_from=v.get("migration_from"),
                        migration_notes=v.get("migration_notes", ""),
                    )
                    for v in data.get("versions", [])
                ]
                schema = ArtifactTypeSchema(
                    artifact_type=data["artifact_type"],
                    versions=versions,
                )
                self.register(schema)
            except Exception:
                continue

    def validate_payload(
        self,
        artifact_type: str,
        schema_version: str,
        payload: dict[str, Any],
    ) -> bool:
        by_version = self._schemas.get(artifact_type)
        if by_version is None:
            raise SchemaValidationError(f"Unknown artifact type: {artifact_type}")
        sv = by_version.get(schema_version)
        if sv is None:
            raise SchemaValidationError(
                f"Unknown schema version {schema_version} for type {artifact_type}"
            )
        for field_def in sv.fields:
            if field_def.name not in payload:
                raise SchemaValidationError(
                    f"Missing required field '{field_def.name}' in {artifact_type}@{schema_version}"
                )
            val = payload[field_def.name]
            expected = _TYPE_MAP.get(field_def.type)
            if expected and val is not None and not isinstance(val, expected):
                raise SchemaValidationError(
                    f"Field '{field_def.name}' expected {field_def.type}, got {type(val).__name__}"
                )
        return True


def register_canonical_question_schema(registry: ArtifactSchemaRegistry) -> None:
    registry.register(ArtifactTypeSchema(
        artifact_type="quro.canonical_question.doc",
        versions=[
            ArtifactSchemaVersion(
                version="1.0",
                fields=[
                    ArtifactFieldDef(name="questions", type="list<Entity>"),
                ],
            ),
            ArtifactSchemaVersion(
                version="1.1",
                fields=[
                    ArtifactFieldDef(name="questions", type="list<Entity>"),
                    ArtifactFieldDef(name="entities", type="list<Entity>"),
                    ArtifactFieldDef(name="edges", type="list<Entity>"),
                ],
                migration_from="1.0",
                migration_notes="Top-level entities+edges replace per-question source_span. Edges reference entities by name.",
            ),
        ],
    ))


def register_not_what_is_schemas(registry: ArtifactSchemaRegistry) -> None:
    registry.register(ArtifactTypeSchema(
        artifact_type="quro.not_what_is.chunk",
        versions=[
            ArtifactSchemaVersion(
                version="1.2",
                fields=[
                    ArtifactFieldDef(name="id", type="string"),
                    ArtifactFieldDef(name="chunk_ref", type="string"),
                    ArtifactFieldDef(name="schema_version", type="string"),
                    ArtifactFieldDef(name="generation_info", type="dict"),
                    ArtifactFieldDef(name="unanswered", type="list<dict>"),
                    ArtifactFieldDef(name="supersedes", type="string"),
                    ArtifactFieldDef(name="created_at", type="string"),
                ],
            ),
        ],
    ))
    registry.register(ArtifactTypeSchema(
        artifact_type="quro.coverage.resolved",
        versions=[
            ArtifactSchemaVersion(
                version="1.0",
                fields=[
                    ArtifactFieldDef(name="intent_id", type="string"),
                    ArtifactFieldDef(name="canonical_question", type="string"),
                    ArtifactFieldDef(name="source_chunk_ref", type="string"),
                    ArtifactFieldDef(name="coverage_state", type="string"),
                    ArtifactFieldDef(name="answered_in_chunks", type="list<string>"),
                    ArtifactFieldDef(name="discoverability_notes", type="string"),
                ],
            ),
        ],
    ))
    registry.register(ArtifactTypeSchema(
        artifact_type="quro.supplement.proposed",
        versions=[
            ArtifactSchemaVersion(
                version="1.0",
                fields=[
                    ArtifactFieldDef(name="artifact_id", type="string"),
                    ArtifactFieldDef(name="intent_id", type="string"),
                    ArtifactFieldDef(name="source_chunk_refs", type="list<string>"),
                    ArtifactFieldDef(name="generated_answer", type="string"),
                    ArtifactFieldDef(name="confidence", type="string"),
                    ArtifactFieldDef(name="generation_info", type="dict"),
                    ArtifactFieldDef(name="review_status", type="string"),
                    ArtifactFieldDef(name="created_at", type="string"),
                ],
            ),
        ],
    ))
    registry.register(ArtifactTypeSchema(
        artifact_type="quro.gap.topology",
        versions=[
            ArtifactSchemaVersion(
                version="1.0",
                fields=[
                    ArtifactFieldDef(name="project", type="string"),
                    ArtifactFieldDef(name="generated_at", type="string"),
                    ArtifactFieldDef(name="globally_missing_categories", type="list<dict>"),
                    ArtifactFieldDef(name="discoverability_weak_intents", type="list<dict>"),
                ],
            ),
        ],
    ))
