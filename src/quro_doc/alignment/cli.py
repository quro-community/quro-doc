from __future__ import annotations
import argparse
import json
from .scanner import IncrementalAlignmentScanner
from .re_resolver import CoverageReResolver


def main() -> None:
    parser = argparse.ArgumentParser(prog="quro alignment")
    sub = parser.add_subparsers(dest="command", required=True)

    scan_p = sub.add_parser("scan", help="Run incremental alignment scan")
    scan_p.add_argument("--batch-size", type=int, default=10)
    scan_p.add_argument("--dry-run", action="store_true", help="Detect matches without writing artifacts")

    resolve_p = sub.add_parser("re-resolve", help="Trigger coverage re-resolution on matched intents")

    status_p = sub.add_parser("status", help="Show alignment status")

    args = parser.parse_args()

    if args.command == "scan":
        scanner = IncrementalAlignmentScanner()
        result = scanner.run_scan(batch_size=args.batch_size, dry_run=args.dry_run)
        print(json.dumps(result, ensure_ascii=False, indent=2))

    elif args.command == "re-resolve":
        resolver = CoverageReResolver()
        result = resolver.run()
        print(json.dumps(result, ensure_ascii=False, indent=2))

    elif args.command == "status":
        from .store import AlignmentStore
        from ..config import QuroConfig
        config = QuroConfig.load()
        store = AlignmentStore(config)
        total = store.count_all_matches()
        aligned_ids = store.list_aligned_ids()
        print(f"Alignment enabled: {config.incremental_alignment_enabled}")
        print(f"Re-resolve threshold: {config.alignment_re_resolve_threshold}")
        print(f"Aligned docs: {len(aligned_ids)}")
        print(f"Total matches: {total}")
        print(f"Threshold reached: {total >= config.alignment_re_resolve_threshold}")


if __name__ == "__main__":
    main()
