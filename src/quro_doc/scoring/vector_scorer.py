from typing import Dict, Any, Optional
from .base import Scorer

class VectorScorer(Scorer):
    name = "vector"

    def score(self, query: str, doc: Dict[str, Any], context: Dict[str, Any]) -> Optional[float]:
        raw = doc.get("score")
        if raw is None:
            return None
        return max(0.0, min(1.0, float(raw)))
