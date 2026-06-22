from __future__ import annotations
import argparse
import sys
from .engine import QaQualitySurvey
from .report import format_survey_report


def main() -> None:
    parser = argparse.ArgumentParser(prog="quro survey")
    sub = parser.add_subparsers(dest="command", required=True)

    survey_parser = sub.add_parser("globally-missing", help="Show globally missing questions summary")
    survey_parser.add_argument("--format", choices=["text", "json"], default="text")
    survey_parser.add_argument("--survey-type", default="globally_missing")

    sub.add_parser("status", help="Check if survey data exists")

    args = parser.parse_args()

    survey = QaQualitySurvey()

    if args.command == "globally-missing":
        data = survey.get_summary(survey_type=args.survey_type)
        if args.format == "json":
            import json
            print(json.dumps(data, ensure_ascii=False, indent=2))
            return
        print(format_survey_report(data, fmt=args.format))

    elif args.command == "status":
        data = survey.get_summary()
        if data.get("status") == "no_data":
            print("Status: NO_DATA — run gap topology pipeline first")
            sys.exit(1)
        else:
            print("Status: OK")
            print(f"  Total globally missing: {data['summary']['total_globally_missing']}")
            print(f"  Discoverability weak: {data['summary']['discoverability_weak']}")


if __name__ == "__main__":
    main()
