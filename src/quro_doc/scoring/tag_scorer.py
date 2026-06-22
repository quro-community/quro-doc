from typing import Dict, Any, Optional
from .base import Scorer

class TagScorer(Scorer):
    name = "tag"

    def score(self, query: str, doc: Dict[str, Any], context: Dict[str, Any]) -> Optional[float]:
        doc_tags = doc.get("meta", {}).get("tags", [])
        query_tags = context.get("query_tags", [])

        if not doc_tags or not query_tags:
            return None

        doc_set = set(doc_tags)
        query_set = set(query_tags)
        overlap = len(doc_set & query_set)
        if overlap == 0:
            return 0.0
        return overlap / len(query_set)
