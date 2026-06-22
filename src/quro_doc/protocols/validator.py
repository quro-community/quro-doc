"""ProtocolValidator — validates input/output against JSON schemas.

IMSPEC: Must NOT import storage/, pipelines/, config.
Only jsonschema + json + os.path + pathlib.
"""
from __future__ import annotations

import json
import os.path
from pathlib import Path
from typing import Optional

from jsonschema import validate, ValidationError


class ProtocolValidator:
    """Validates input payloads and output results against versioned JSON schemas.

    Schema files are read from the schemas/ directory via open(path, 'r') only.
    """

    def __init__(self, schemas_dir: Optional[str] = None):
        if schemas_dir is None:
            schemas_dir = os.path.join(os.path.dirname(__file__), "schemas")
        self._schemas_dir = Path(schemas_dir)
        self._cache: dict[str, dict] = {}

    def _load_schema(self, name: str) -> dict:
        if name not in self._cache:
            schema_path = self._schemas_dir / f"{name}.json"
            with open(schema_path, "r", encoding="utf-8") as fh:
                self._cache[name] = json.load(fh)
        return self._cache[name]

    def validate_input(self, payload: dict, schema_version: str = "2.0") -> dict:
        """Validate an add-request payload against add_request_v2.json.

        Returns the payload unchanged on success (does not mutate).
        Raises ValidationError on failure.
        """
        schema = self._load_schema("add_request_v2")
        validate(instance=payload, schema=schema)
        return payload

    def validate_output(self, candidates: list, schema_version: str = "2.0") -> list:
        """Validate search results against search_response_v2.json (EvidenceModel).

        Each candidate must have: doc_id, score, snippet.
        Returns candidates unchanged on success (does not mutate).
        Raises ValidationError on failure.
        """
        schema = self._load_schema("search_response_v2")
        validate(instance=candidates, schema=schema)
        return candidates

    def validate_metadata_set(self, metadata_set: list) -> list:
        """Validate a caller-declared metadata_set against metadata_set_v1.json.

        Each item must have: key (required, string, minLength 1).
        Optional: description, domain, map_to (all strings).
        No additional properties allowed per item.

        Returns the metadata_set unchanged on success.
        Raises ValidationError on failure (caught by MetadataInspector
        to produce a versioned protocol-violation error).
        """
        schema = self._load_schema("metadata_set_v1")
        validate(instance=metadata_set, schema=schema)
        return metadata_set
