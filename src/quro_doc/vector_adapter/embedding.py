"""Embedding client: calls OpenAI-compatible embeddings API.

Configured via env (.env or environment):
  EMBEDDING_API_URL  (default: http://localhost:20128/v1/embeddings)
  EMBEDDING_API_KEY  (default: empty / no auth)
  EMBEDDING_MODEL    (default: llama/embeddinggemma)

All configs are read lazily so that dotenv is loaded before first use.
"""

import os
import numpy as np
from typing import List, Optional
from openai import OpenAI

_client: Optional[OpenAI] = None
_dotenv_loaded: bool = False


def _ensure_dotenv():
    global _dotenv_loaded
    if not _dotenv_loaded:
        from dotenv import load_dotenv
        _root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
        load_dotenv(os.path.join(_root, '.env'))
        _dotenv_loaded = True


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _ensure_dotenv()
        api_key = os.getenv("EMBEDDING_API_KEY", "")
        _client = OpenAI(
            base_url=os.getenv("EMBEDDING_API_URL", "http://localhost:20128/v1/embeddings"),
            api_key=api_key or None,
        )
    return _client


def embed_text(text: str, model: Optional[str] = None) -> List[float]:
    client = _get_client()
    resp = client.embeddings.create(
        model=model or os.getenv("EMBEDDING_MODEL", "llama/embeddinggemma"),
        input=text,
    )
    return resp.data[0].embedding


def embed_texts(texts: List[str], model: Optional[str] = None) -> List[List[float]]:
    client = _get_client()
    resp = client.embeddings.create(
        model=model or os.getenv("EMBEDDING_MODEL", "llama/embeddinggemma"),
        input=texts,
    )
    sorted_data = sorted(resp.data, key=lambda d: d.index)
    return [d.embedding for d in sorted_data]
