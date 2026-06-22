from __future__ import annotations
import argparse
import json
import sys
from .store import FeedbackStore
from .aggregator import FeedbackReviewAggregator


def main() -> None:
    parser = argparse.ArgumentParser(prog="quro feedback")
    sub = parser.add_subparsers(dest="command", required=True)

    submit_p = sub.add_parser("submit", help="Submit quality feedback")
    submit_p.add_argument("--artifact-type", required=True, help="Artifact type (e.g. quro.canonical_question.doc)")
    submit_p.add_argument("--artifact-id", default="", help="Artifact ID")
    submit_p.add_argument("--question-id", default="", help="Question ID")
    submit_p.add_argument("--intent-id", default="", help="Intent ID")
    submit_p.add_argument("--query", required=True, help="Query text")
    submit_p.add_argument("--response-snippet", default="", help="Response snippet")
    submit_p.add_argument("--reason", default="", help="Reason for feedback")
    submit_p.add_argument("--flag-hallucinated", action="store_true")
    submit_p.add_argument("--flag-not-grounded", action="store_true")
    submit_p.add_argument("--flag-vague", action="store_true")
    submit_p.add_argument("--flag-ambiguous", action="store_true")
    submit_p.add_argument("--flag-wrong-intent", action="store_true")
    submit_p.add_argument("--wrong-intent-proposed", default="")
    submit_p.add_argument("--reviewer", default="human", choices=["human", "system"])

    review_p = sub.add_parser("review", help="Show aggregated review for intent")
    review_p.add_argument("--intent-id", default="", help="Filter by intent ID")

    report_p = sub.add_parser("report", help="Show all high-priority reviews")
    report_p.add_argument("--since", default="7d", help="Time window (ignored in v1)")

    args = parser.parse_args()

    if args.command == "submit":
        payload = {
            "target": {
                "artifact_type": args.artifact_type,
                "artifact_id": args.artifact_id,
                "question_id": args.question_id,
                "intent_id": args.intent_id,
            },
            "qa_pair": {
                "query": args.query,
                "response_snippet": args.response_snippet,
            },
            "quality_flags": {
                "is_hallucinated": args.flag_hallucinated,
                "is_not_grounded": args.flag_not_grounded,
                "is_vague": args.flag_vague,
                "is_ambiguous": args.flag_ambiguous,
                "has_wrong_intent": args.flag_wrong_intent,
                "wrong_intent_proposed": args.wrong_intent_proposed,
            },
            "reviewer": args.reviewer,
            "reason": args.reason,
        }
        store = FeedbackStore()
        result = store.submit(payload)
        print(json.dumps(result, ensure_ascii=False, indent=2))

    elif args.command == "review":
        aggregator = FeedbackReviewAggregator()
        result = aggregator.aggregate(intent_id=args.intent_id or None)
        print(json.dumps(result, ensure_ascii=False, indent=2))

    elif args.command == "report":
        aggregator = FeedbackReviewAggregator()
        result = aggregator.aggregate()
        high_priority = [r for r in result.get("reviews", []) if r["investigation_priority"] == "high"]
        print(json.dumps({
            "status": "ok",
            "since": args.since,
            "total_reviews": len(result.get("reviews", [])),
            "high_priority_count": len(high_priority),
            "high_priority_reviews": high_priority,
        }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
