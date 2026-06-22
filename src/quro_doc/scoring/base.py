from typing import Dict, Any, Optional

class Scorer:
    name: str = ""
    weight: float = 1.0
    required: bool = False

    def score(self, query: str, doc: Dict[str, Any], context: Dict[str, Any]) -> Optional[float]:
        raise NotImplementedError
