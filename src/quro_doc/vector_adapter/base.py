"""Protocol-driven vector store adapter base class and factory.

All adapters must implement the methods defined here and conform to
the JSON Schema at docs/schemas/vector_protocol.schema.json.
"""

import os
import json
from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional

PROTOCOL_VERSION = "1.0.0"

ADAPTER_REGISTRY: Dict[str, type] = {}


def register_adapter(adapter_type: str):
    def decorator(cls):
        cls.adapter_type = adapter_type
        ADAPTER_REGISTRY[adapter_type] = cls
        return cls
    return decorator


class BaseVectorAdapter(ABC):
    adapter_type: str = "base"

    @abstractmethod
    def upsert_vectors(self, request: Dict[str, Any]) -> Dict[str, Any]:
        ...

    @abstractmethod
    def query_vectors(self, request: Dict[str, Any]) -> Dict[str, Any]:
        ...

    @abstractmethod
    def delete_vectors(self, ids: List[str]) -> Dict[str, Any]:
        ...

    @abstractmethod
    def persist(self, path: str) -> Dict[str, Any]:
        ...

    @abstractmethod
    def load(self, path: str) -> Dict[str, Any]:
        ...

    @abstractmethod
    def get_meta(self) -> Dict[str, Any]:
        ...


def get_adapter(adapter_type: Optional[str] = None) -> BaseVectorAdapter:
    from dotenv import load_dotenv
    _root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
    load_dotenv(os.path.join(_root, '.env'))

    at = adapter_type or os.getenv("VECTOR_STORE_TYPE", "fs")
    if at not in ADAPTER_REGISTRY:
        raise ValueError(
            f"Unknown vector store adapter type '{at}'. "
            f"Available: {list(ADAPTER_REGISTRY.keys())}"
        )
    return ADAPTER_REGISTRY[at]()
