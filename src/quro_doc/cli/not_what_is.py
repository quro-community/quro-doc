from __future__ import annotations
import json
import argparse
import sys

from ..config import QuroConfig
from ..pipelines.offline.not_what_is import run_not_what_is_pipeline
from ..pipelines.offline.coverage_resolver import run_coverage_resolution
from ..pipelines.offline.gap_topology import run_gap_topology
from ..pipelines.offline.supplement_generator import run_supplement_generation
from ..artifacts.store import ArtifactStore
from ..artifacts.schema import ArtifactSchemaRegistry, register_not_what_is_schemas


def _init_schemas(config: QuroConfig) -> None:
    registry = ArtifactSchemaRegistry()
    register_not_what_is_schemas(registry)
    schema_path = config.artifact_schema_registry_path
    if schema_path:
        registry.load_from_path(schema_path)


def cmd_extract(args: argparse.Namespace) -> None:
    config = QuroConfig.load()
    _init_schemas(config)
    result = run_not_what_is_pipeline(
        config=config,
        chunk_refs=args.chunk_refs,
        dry_run=args.dry_run,
    )
    print(json.dumps(result, indent=2))


def cmd_resolve(args: argparse.Namespace) -> None:
    config = QuroConfig.load()
    _init_schemas(config)
    result = run_coverage_resolution(config=config)
    print(json.dumps(result, indent=2))


def cmd_topology(args: argparse.Namespace) -> None:
    config = QuroConfig.load()
    _init_schemas(config)
    result = run_gap_topology(config=config)

    if result.get("status") == "disabled":
        print(json.dumps(result, indent=2))
        return

    print("=== Gap Topology Report ===")
    print("\nGlobally Missing Categories:")
    for cat in result.get("globally_missing_categories", []):
        print(f"  {cat['category']}: {cat['count']}")
        for ex in cat.get("example_intents", []):
            print(f"    - {ex}")

    print("\nDiscoverability-Weak Intents:")
    for entry in result.get("discoverability_weak_intents", []):
        print(f"  {entry['intent_id']}")
        print(f"    located in: {entry.get('located_in', 'unknown')}")
        print(f"    note: {entry.get('note', '')}")


def cmd_supplement(args: argparse.Namespace) -> None:
    config = QuroConfig.load()
    _init_schemas(config)
    result = run_supplement_generation(config=config)
    print(json.dumps(result, indent=2))


def cmd_report(args: argparse.Namespace) -> None:
    config = QuroConfig.load()
    _init_schemas(config)
    artifact_store = ArtifactStore(config)

    nwi_count = len(artifact_store.list_by_type("quro.not_what_is.chunk"))
    cr_count = len(artifact_store.list_by_type("quro.coverage.resolved"))
    sup_count = len(artifact_store.list_by_type("quro.supplement.proposed"))
    gt_count = len(artifact_store.list_by_type("quro.gap.topology"))

    print("=== Not-What-Is Diagnostic Summary ===")
    print(f"  Feature gate (not_what_is_enabled): {config.not_what_is_enabled}")
    print(f"  Coverage resolver enabled: {config.coverage_resolver_enabled}")
    print(f"  Gap topology enabled: {config.gap_topology_enabled}")
    print(f"  Supplement generation enabled: {config.not_what_is_supplement_enabled}")
    print("\n  Artifacts:")
    print(f"    quro.not_what_is.chunk:    {nwi_count}")
    print(f"    quro.coverage.resolved:   {cr_count}")
    print(f"    quro.supplement.proposed:  {sup_count}")
    print(f"    quro.gap.topology:         {gt_count}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Not-What-Is Knowledge Diagnostics")
    sub = parser.add_subparsers(dest="command")

    p_extract = sub.add_parser("extract", help="Run NotWhatIsExtractor for chunks")
    p_extract.add_argument("--chunk-refs", nargs="*", default=None)
    p_extract.add_argument("--dry-run", action="store_true")

    sub.add_parser("resolve", help="Run CoverageResolver against full KB")

    sub.add_parser("topology", help="Run GapTopologyAnalyzer, print report")

    sub.add_parser(
        "supplement", help="Run SupplementGenerator for globally_missing intents"
    )

    sub.add_parser("report", help="Print aggregated diagnostic summary")

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)

    cmd_map = {
        "extract": cmd_extract,
        "resolve": cmd_resolve,
        "topology": cmd_topology,
        "supplement": cmd_supplement,
        "report": cmd_report,
    }

    if args.command in cmd_map:
        cmd_map[args.command](args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
