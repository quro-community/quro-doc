from __future__ import annotations
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any


@dataclass
class FeedbackTarget:
    artifact_type: str = ""
    artifact_id: str = ""
    question_id: str = ""
    question_text: str = ""
    intent_id: str = ""


@dataclass
class FeedbackQAPair:
    query: str = ""
    response_snippet: str = ""


@dataclass
class FeedbackQualityFlags:
    is_hallucinated: bool = False
    is_not_grounded: bool = False
    is_vague: bool = False
    is_ambiguous: bool = False
    has_wrong_intent: bool = False
    wrong_intent_proposed: str = ""


@dataclass
class FeedbackEntry:
    feedback_id: str = ""
    feedback_type: str = "low_quality_question"
    target: FeedbackTarget = field(default_factory=FeedbackTarget)
    qa_pair: FeedbackQAPair = field(default_factory=FeedbackQAPair)
    quality_flags: FeedbackQualityFlags = field(default_factory=FeedbackQualityFlags)
    reviewer: str = "human"
    reason: str = ""
    created_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["target"] = asdict(self.target)
        d["qa_pair"] = asdict(self.qa_pair)
        d["quality_flags"] = asdict(self.quality_flags)
        return d

    @classmethod
    def from_payload(cls, payload: dict) -> FeedbackEntry:
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        target_data = payload.get("target", {})
        qa_data = payload.get("qa_pair", {})
        flags_data = payload.get("quality_flags", {})

        return cls(
            feedback_id=payload.get("feedback_id", f"fb_{now}"),
            feedback_type=payload.get("feedback_type", "low_quality_question"),
            target=FeedbackTarget(**target_data),
            qa_pair=FeedbackQAPair(**qa_data),
            quality_flags=FeedbackQualityFlags(**flags_data),
            reviewer=payload.get("reviewer", "human"),
            reason=payload.get("reason", ""),
            created_at=now,
        )
