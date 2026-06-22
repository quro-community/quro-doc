"""
DEPRECATED: Use ArtifactFeatureExtractor + RankingPolicy instead.

This module creates score soup by collapsing observation and decision into
a single weighted scoring step. New code must NOT import from this module.

Migration target:
  - ArtifactFeatureExtractor (src/quro_doc/artifacts/feature_extractor.py)
  - RankingPolicy (src/quro_doc/ranking/policy.py)
"""

import os
import json
from typing import Dict, Any, List, Optional, Tuple
from .base import Scorer
from .vector_scorer import VectorScorer
from .tag_scorer import TagScorer

SCORER_REGISTRY = {
    "vector": VectorScorer,
    "tag": TagScorer,
}

class ScoringEngine:
    def __init__(self, scorers: List[Scorer]):
        self.scorers = scorers

    def score(self, query: str, doc: Dict[str, Any], context: Dict[str, Any]) -> Tuple[Optional[float], Dict[str, float]]:
        total = 0.0
        total_weight = 0.0
        breakdown = {}

        for scorer in self.scorers:
            try:
                s = scorer.score(query, doc, context)
            except Exception:
                s = None

            if s is None:
                if scorer.required:
                    return None, {}
                continue

            total += scorer.weight * s
            total_weight += scorer.weight
            breakdown[scorer.name] = s

        if total_weight == 0:
            return 0.0, breakdown
        return total / total_weight, breakdown

    @classmethod
    def from_central(cls, central) -> "ScoringEngine":
        scorers = []
        for sw in central.scorer_weights:
            name = sw.name
            cls_scorer = SCORER_REGISTRY.get(name)
            if cls_scorer is None:
                continue
            scorer = cls_scorer()
            scorer.weight = sw.weight
            scorer.required = sw.required
            scorers.append(scorer)
        return cls(scorers)

    @staticmethod
    def from_env() -> "ScoringEngine":
        raw = os.getenv("QUERY_SCORER_WEIGHTS", '[{"name":"vector","weight":1.0,"required":true}]')
        try:
            configs = json.loads(raw)
        except Exception:
            configs = [{"name": "vector", "weight": 1.0, "required": True}]

        scorers = []
        for cfg in configs:
            name = cfg.get("name", "")
            cls = SCORER_REGISTRY.get(name)
            if cls is None:
                continue
            scorer = cls()
            scorer.weight = float(cfg.get("weight", 1.0))
            scorer.required = bool(cfg.get("required", False))
            scorers.append(scorer)

        return ScoringEngine(scorers)
