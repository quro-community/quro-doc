from typing import Any


def format_survey_report(data: dict[str, Any], fmt: str = "text") -> str:
    if data.get("status") == "no_data":
        return "No gap topology data available. Run gap topology pipeline first."

    if fmt == "json":
        import json
        return json.dumps(data, ensure_ascii=False, indent=2)

    lines = []
    summary = data.get("summary", {})
    lines.append(f"QA Coverage Survey: {data.get('survey_type', 'globally_missing')}")
    lines.append(f"Generated: {data.get('generated_at', 'N/A')}")
    lines.append(f"Artifact: {data.get('artifact_ref', 'N/A')}")
    lines.append("")
    lines.append(f"Total Globally Missing: {summary.get('total_globally_missing', 0)}")
    lines.append(f"Discoverability Weak: {summary.get('discoverability_weak', 0)}")
    lines.append("")

    categories = summary.get("categories", [])
    if categories:
        lines.append("Categories:")
        for cat in categories:
            examples = ", ".join(cat.get("example_intents", [])[:3])
            lines.append(f"  {cat['category']}: {cat['count']}")
            if examples:
                lines.append(f"    examples: {examples}")
        lines.append("")

    entries = data.get("entries", [])
    if entries:
        lines.append("Entries:")
        for e in entries:
            lines.append(f"  [{e.get('topology_category', 'other')}] {e.get('intent_id', 'N/A')}")
            lines.append(f"    Q: {e.get('canonical_question', 'N/A')}")
            lines.append(f"    source: {e.get('source_chunk_ref', 'N/A')}")
            lines.append(f"    notes: {e.get('discoverability_notes', 'N/A')}")
            lines.append("")

    if not lines:
        return "No survey data."

    return "\n".join(lines)
