"""Fetch every registry school from the real sources and print per-field coverage.

    python -m cfa.tools.live_smoke [--baseline docs/coverage_baseline.json] [--write-baseline]

Exit code 1 when an exception escapes, a source health check fails, or overall field
coverage drops more than 10% below the committed baseline (PLAN §7 Phase 6).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

from cfa import config
from cfa.models.college import FIELDS
from cfa.models.field_value import Status
from cfa.pipeline import health_checks, parse_pool, run_all, shutdown_pool
from cfa.sources.http import HttpClient
from cfa.sources.registry import load_registry

MAX_DROP = 0.10  # relative drop in overall coverage that fails the run


class _ErrorCounter(logging.Handler):
    def __init__(self) -> None:
        super().__init__(logging.ERROR)
        self.count = 0

    def emit(self, record: logging.LogRecord) -> None:
        self.count += 1


async def run(registry_url: str | None, require_remote: bool = False) -> tuple[dict, dict, int]:
    async with HttpClient() as http:
        load = await load_registry(http, registry_url or config.REGISTRY_REMOTE_URL)
    print(
        f"Registry: {load.origin} ({len(load.registry.schools)} schools)"
        + (f" - {load.warning}" if load.warning else "")
    )
    if require_remote and load.origin != "remote":
        raise RuntimeError(f"registry could not be loaded from {registry_url}")
    key = config.scorecard_api_key()
    health = await health_checks(load.registry, key)
    result = await run_all(
        load.registry,
        api_key=key,
        executor=parse_pool(),
        progress=lambda d, t, n: print(f"  [{d}/{t}] {n}", flush=True),
    )
    coverage = {k: 0 for k in FIELDS}
    for rec in result.records:
        for k, ok in rec.coverage().items():
            coverage[k] += int(ok)
    n = max(1, len(result.records))
    cov = {k: round(v / n, 3) for k, v in coverage.items()}
    return cov, {s: h.status.value for s, h in health.items()}, len(result.records)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--baseline", type=Path, default=None)
    ap.add_argument("--write-baseline", action="store_true")
    ap.add_argument("--registry-url", default=None)
    ap.add_argument(
        "--require-remote-registry",
        action="store_true",
        help="fail if the registry URL cannot be loaded (used to test failure reporting)",
    )
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    counter = _ErrorCounter()
    logging.getLogger().addHandler(counter)
    try:
        cov, health, n = asyncio.run(run(args.registry_url, args.require_remote_registry))
    except Exception as exc:  # the whole point: nothing may escape
        print(f"FAIL: {type(exc).__name__}: {exc}")
        return 1
    finally:
        shutdown_pool()

    print("\nSource health:")
    for src, st in health.items():
        print(f"  {src:22} {st}")
    print(f"\nField coverage across {n} schools:")
    for k, v in cov.items():
        print(f"  {FIELDS[k].label:36} {v * 100:5.1f}%")
    overall = sum(cov.values()) / len(cov)
    print(f"\nOverall coverage: {overall * 100:.1f}%   unhandled errors logged: {counter.count}")

    failed = counter.count > 0
    for src, st in health.items():
        # A missing Scorecard key is a configuration choice, not an upstream failure.
        if st not in (Status.OK.value, Status.AUTH_MISSING.value):
            print(f"FAIL: {src} health check returned {st}")
            failed = True
    if args.baseline and args.baseline.exists() and not args.write_baseline:
        base = json.loads(args.baseline.read_text(encoding="utf-8"))
        b_overall = base.get("overall", 0)
        if b_overall and overall < b_overall * (1 - MAX_DROP):
            print(f"FAIL: overall coverage {overall:.3f} dropped >10% below baseline {b_overall:.3f}")
            failed = True
        for k, v in cov.items():
            bv = base.get("fields", {}).get(k)
            if bv is not None and v < bv - 0.10:
                print(f"  warning: {k} coverage {v:.2f} vs baseline {bv:.2f}")
    if args.write_baseline and args.baseline:
        args.baseline.write_text(
            json.dumps({"overall": round(overall, 3), "fields": cov}, indent=2) + "\n", encoding="utf-8"
        )
        print(f"Baseline written to {args.baseline}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
