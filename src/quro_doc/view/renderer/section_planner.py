from __future__ import annotations
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, field
from ..candidate import EvidenceCandidate
from .base import QueryContext
from .standard_ast import Section, STANDARD_SECTIONS


SECTION_KEYWORDS: Dict[str, List[str]] = {
    "Goal": ["goal", "purpose", "objective", "why", "motivation"],
    "Summary": ["summary", "overview", "introduction", "background"],
    "Architecture": ["architecture", "design", "system", "module", "component", "pattern"],
    "Dir Structure": ["directory", "structure", "layout", "project", "src/"],
    "DataFlow": ["flow", "pipeline", "stream", "process", "data", "pipeline"],
    "Files": ["file", "src/", "class", "function", "method", "def "],
}


SECTION_TAG_MAP: Dict[str, List[str]] = {
    "Architecture": ["architecture", "design", "system-design"],
    "DataFlow": ["dataflow", "flow", "pipeline"],
    "Files": ["code", "implementation"],
}


@dataclass
class StandardViewConfig:
    sections: List[str] = field(default_factory=lambda: list(STANDARD_SECTIONS))
    planner_strategy: str = "heuristic"
    max_sections: int = 5
    min_evidence_per_section: int = 1
    max_evidence_per_section: int = 5
    token_budget: int = 1200
    enable_summarization: bool = False

    @classmethod
    def from_central(cls, central) -> "StandardViewConfig":
        return cls(
            sections=central.standard_view_sections,
            planner_strategy=central.standard_view_planner_strategy,
            max_sections=central.standard_view_max_sections,
            min_evidence_per_section=central.standard_view_min_evidence_per_section,
            max_evidence_per_section=central.standard_view_max_evidence_per_section,
            token_budget=central.standard_view_token_budget,
            enable_summarization=central.standard_view_enable_summarization,
        )

    @classmethod
    def from_env(cls) -> "StandardViewConfig":
        import os, json
        sections_raw = os.getenv(
            "STANDARD_VIEW_SECTIONS",
            '["Goal","Summary","Architecture","Dir Structure","DataFlow","Files"]',
        )
        try:
            sections = json.loads(sections_raw)
        except Exception:
            sections = list(STANDARD_SECTIONS)

        return cls(
            sections=sections,
            planner_strategy=os.getenv("STANDARD_VIEW_PLANNER_STRATEGY", "heuristic"),
            max_sections=int(os.getenv("STANDARD_VIEW_MAX_SECTIONS", "5")),
            min_evidence_per_section=int(os.getenv("STANDARD_VIEW_MIN_EVIDENCE_PER_SECTION", "1")),
            max_evidence_per_section=int(os.getenv("STANDARD_VIEW_MAX_EVIDENCE_PER_SECTION", "5")),
            token_budget=int(os.getenv("STANDARD_VIEW_TOKEN_BUDGET", "1200")),
            enable_summarization=os.getenv("STANDARD_VIEW_ENABLE_SUMMARIZATION", "false").lower() == "true",
        )


TOKEN_ALLOCATION: Dict[str, float] = {
    "Goal": 0.10,
    "Summary": 0.20,
    "Architecture": 0.25,
    "Dir Structure": 0.10,
    "DataFlow": 0.15,
    "Files": 0.20,
}

SECTION_PRIORITY: Dict[str, int] = {
    "Goal": 6,
    "Summary": 5,
    "Files": 4,
    "Architecture": 3,
    "DataFlow": 2,
    "Dir Structure": 1,
}


class SectionPlanner:
    def __init__(self, config: StandardViewConfig):
        self.config = config

    def plan(
        self, candidates: List[EvidenceCandidate], query: QueryContext
    ) -> List[Section]:
        active_sections = self._check_relevance(candidates, query)
        if not active_sections:
            return self._fallback_flat(candidates)

        classified = self._classify_candidates(candidates)

        budget = self._allocate_budget(active_sections, candidates)

        sections = []
        for section_title in active_sections:
            if section_title not in classified or not classified[section_title]:
                continue
            evidence = classified[section_title]
            allowed = budget.get(section_title, 0)
            selected = self._select_evidence(evidence, allowed, section_title)
            if not selected:
                continue
            sections.append(Section(title=section_title, summary="", evidence=selected))

        sections.sort(key=lambda s: SECTION_PRIORITY.get(s.title, 0), reverse=True)
        sections = sections[: self.config.max_sections]

        return sections

    def _check_relevance(
        self, candidates: List[EvidenceCandidate], query: QueryContext
    ) -> List[str]:
        active = []
        for section in self.config.sections:
            if section == "Goal":
                active.append(section)
                continue
            if section == "Summary":
                active.append(section)
                continue

            if self._section_has_evidence(section, candidates):
                active.append(section)
                continue

            if self._query_matches_section(section, query.text):
                active.append(section)

        return active

    def _section_has_evidence(self, section: str, candidates: List[EvidenceCandidate]) -> bool:
        keywords = SECTION_KEYWORDS.get(section, [])
        tag_patterns = SECTION_TAG_MAP.get(section, [])
        for c in candidates:
            content_lower = c.content.lower()
            if any(kw in content_lower for kw in keywords):
                return True
            if c.metadata.get("doc_id", "").startswith("src/"):
                if section == "Dir Structure" or section == "Files":
                    return True
            cand_tags = c.metadata.get("tags", [])
            if any(t in cand_tags for t in tag_patterns):
                return True
        return False

    def _query_matches_section(self, section: str, query: str) -> bool:
        keywords = SECTION_KEYWORDS.get(section, [])
        return any(kw in query.lower() for kw in keywords)

    def _classify_candidates(
        self, candidates: List[EvidenceCandidate]
    ) -> Dict[str, List[EvidenceCandidate]]:
        classified: Dict[str, List[EvidenceCandidate]] = {}
        for c in candidates:
            best_section = self._classify_one(c)
            if best_section not in classified:
                classified[best_section] = []
            classified[best_section].append(c)

        # dedup: same candidate_id should not appear in multiple sections
        seen_ids: set = set()
        for section_title in list(classified.keys()):
            deduped = []
            for c in classified[section_title]:
                if c.candidate_id not in seen_ids:
                    seen_ids.add(c.candidate_id)
                    deduped.append(c)
            classified[section_title] = deduped

        return classified

    def _classify_one(self, candidate: EvidenceCandidate) -> str:
        tags = candidate.metadata.get("tags", [])
        for tag in tags:
            for section, patterns in SECTION_TAG_MAP.items():
                if tag in patterns:
                    return section

        doc_id = candidate.metadata.get("doc_id", "")
        if doc_id.startswith("src/"):
            if "/" in doc_id:
                return "Dir Structure"
            return "Files"

        content_lower = candidate.content.lower()
        for section, keywords in SECTION_KEYWORDS.items():
            if section in ("Goal", "Summary", "Dir Structure", "Files"):
                continue
            if any(kw in content_lower for kw in keywords):
                return section

        return "Summary"

    def _allocate_budget(
        self, active_sections: List[str], candidates: List[EvidenceCandidate]
    ) -> Dict[str, int]:
        total_tokens = sum(c.runtime_cost.get("token_cost", 0) for c in candidates)
        budget = min(self.config.token_budget, max(total_tokens, 100))

        allocation: Dict[str, int] = {}
        for section in active_sections:
            pct = TOKEN_ALLOCATION.get(section, 0.10)
            raw = int(budget * pct)
            allocation[section] = max(raw, 20)

        total_allocated = sum(allocation.values())
        if total_allocated > budget:
            overflow = total_allocated - budget
            for section in sorted(active_sections, key=lambda s: SECTION_PRIORITY.get(s, 0)):
                if overflow <= 0:
                    break
                reduction = min(allocation[section], overflow)
                allocation[section] -= reduction
                overflow -= reduction

        return allocation

    def _select_evidence(
        self, evidence: List[EvidenceCandidate], token_budget: int, section_title: str
    ) -> List[EvidenceCandidate]:
        sorted_ev = sorted(
            evidence, key=lambda c: c.retrieval_signal.get("rerank_relevance", 0.0), reverse=True
        )
        if not sorted_ev:
            return []

        selected = []
        token_count = 0
        remaining_budget = token_budget

        for c in sorted_ev:
            tokens = c.runtime_cost.get("token_cost", 0)
            if tokens > remaining_budget:
                if not selected:
                    selected.append(c)
                    token_count = tokens
                continue
            selected.append(c)
            token_count += tokens
            remaining_budget -= tokens
            if len(selected) >= self.config.max_evidence_per_section:
                break

        # Graceful degradation: if under min but evidence exists, show what we have
        if len(selected) < self.config.min_evidence_per_section and selected:
            selected[0].artifact_feature["evidence_warning"] = (
                f"Section '{section_title}': only {len(selected)} evidence(s) found, "
                f"minimum requested {self.config.min_evidence_per_section}"
            )

        return selected

    def _fallback_flat(
        self, candidates: List[EvidenceCandidate]
    ) -> List[Section]:
        sorted_cands = sorted(
            candidates, key=lambda c: c.retrieval_signal.get("rerank_relevance", 0.0), reverse=True
        )
        top = sorted_cands[: self.config.max_evidence_per_section]
        return [Section(title="Summary", summary="", evidence=top)] if top else []
