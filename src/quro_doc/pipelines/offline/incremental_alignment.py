from __future__ import annotations
from ...config import QuroConfig
from ...alignment.scanner import IncrementalAlignmentScanner
from ...alignment.re_resolver import CoverageReResolver


def run_incremental_alignment_scan(
    config: QuroConfig | None = None,
    batch_size: int = 10,
    dry_run: bool = False,
) -> dict:
    config = config or QuroConfig.load()
    if not config.incremental_alignment_enabled:
        return {"status": "disabled"}

    scanner = IncrementalAlignmentScanner(config)
    result = scanner.run_scan(batch_size=batch_size, dry_run=dry_run)

    if result.get("re_resolve_triggered"):
        resolver = CoverageReResolver(config)
        resolve_result = resolver.run()
        result["re_resolution"] = resolve_result

    return result


def run_coverage_recheck(config: QuroConfig | None = None) -> dict:
    config = config or QuroConfig.load()
    resolver = CoverageReResolver(config)
    return resolver.run()
