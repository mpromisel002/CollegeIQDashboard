"""Build the weekly data file the app searches from (see cfa.snapshot).

    python -m cfa.tools.build_snapshot --out snapshot.json.gz [--registry registry/schools.yaml]
                                       [--states PA,NY] [--require-scorecard] [--min-schools 1000]

Loads IPEDS and College Scorecard for every four-year college (or just --states) and reads every
curated school's Common Data Set, the same way a live search does. Results that failed for a
passing reason (source down, rate limited, no key) are left out, so the app asks for those live.

Exit code 1, and no file written, when IPEDS cannot list the colleges, fewer than --min-schools
colleges are found, or --require-scorecard is set and College Scorecard did not answer.
"""

from __future__ import annotations

import argparse
import asyncio
import collections
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path

from cfa import config
from cfa.models.field_value import Status
from cfa.pipeline import parse_pool, pick_colleges, shutdown_pool
from cfa.snapshot import Snapshot, SnapshotSchool, encode
from cfa.sources.base import FetchResult
from cfa.sources.cds.adapter import CdsAdapter
from cfa.sources.http import HttpClient
from cfa.sources.registry import Registry, load_bundled
from cfa.sources.scorecard import ScorecardAdapter
from cfa.sources.urban_ipeds import UrbanIpedsAdapter, is_candidate_college
from cfa.states import STATE_FIPS

log = logging.getLogger(__name__)

# Not worth keeping: the app retries these live instead of showing last week's failure.
PASSING = (Status.SOURCE_UNAVAILABLE, Status.RATE_LIMITED, Status.AUTH_MISSING)


class BuildError(Exception):
    pass


def _say(text: str) -> None:
    print(text, flush=True)


async def build(
    registry: Registry, *, states: list[str] | None = None, api_key: str | None = None
) -> Snapshot:
    fips = [STATE_FIPS[s] for s in (states or []) if s in STATE_FIPS] or None
    async with HttpClient() as http:
        urban = UrbanIpedsAdapter(http)
        scorecard = ScorecardAdapter(http, api_key)
        cds = CdsAdapter(http, registry, executor=parse_pool())

        _say(f"IPEDS: loading {', '.join(states or []) if fips else 'every state'}…")
        await urban.prefetch(fips, progress=lambda topic: _say(f"  {topic}"))
        if not urban.directory_rows:
            raise BuildError("IPEDS did not return the list of colleges")
        rows = {r["unitid"]: r for r in urban.directory_rows if isinstance(r.get("unitid"), int)}
        picked = pick_colleges(urban.directory_rows, registry, everywhere=fips is None)
        _say(f"{len(picked)} colleges")

        _say("College Scorecard…" if api_key else "College Scorecard: no key, skipped")
        await scorecard.prefetch(picked)
        fast = await asyncio.gather(*(asyncio.gather(urban.fetch(u), scorecard.fetch(u)) for u in picked))
        results: dict[int, list[FetchResult]] = {u: list(r) for u, r in zip(picked, fast, strict=True)}

        documents = [s for s in registry.schools if s.latest_cds and s.unitid in results]
        _say(f"Reading {len(documents)} Common Data Sets…")
        done = [0]

        async def read(unitid: int) -> FetchResult:
            res = await cds.fetch(unitid)
            done[0] += 1
            if done[0] % 25 == 0 or done[0] == len(documents):
                _say(f"  {done[0]}/{len(documents)}")
            return res

        read_all = await asyncio.gather(*(read(s.unitid) for s in documents))
        for school, doc_res in zip(documents, read_all, strict=True):
            results[school.unitid].append(doc_res)

    listed = {s.unitid: s for s in registry.schools}
    schools: dict[int, SnapshotSchool] = {}
    answered: set[str] = set()
    for uid, found in results.items():
        kept = {r.source: r for r in found if r.status not in PASSING}
        answered.update(s for s, r in kept.items() if r.ok)
        row = rows.get(uid, {})
        urban_res = kept.get(urban.name)
        name = urban_res.data.get("name") if urban_res else None
        state = urban_res.data.get("state") if urban_res else None
        doc = listed[uid].latest_cds if uid in listed else None
        schools[uid] = SnapshotSchool(
            uid,
            str(name.value) if name and name.ok else (listed[uid].name if uid in listed else str(uid)),
            str(state.value) if state and state.ok else str(row.get("state_abbr") or ""),
            bool(row) and is_candidate_college(row),
            doc.url if doc and cds.name in kept else None,
            kept,
        )
    return Snapshot(datetime.now(UTC), schools, sorted(answered), sorted(states or []) if fips else [])


def summary(snap: Snapshot) -> str:
    counts: dict[str, collections.Counter[str]] = collections.defaultdict(collections.Counter)
    for s in snap.schools.values():
        for src, r in s.results.items():
            counts[src][r.status.value] += 1
    lines = [f"{len(snap.schools)} colleges; sources answering: {', '.join(snap.sources) or 'none'}"]
    for src, c in sorted(counts.items()):
        lines.append(f"  {src}: " + ", ".join(f"{k} {v}" for k, v in c.most_common()))
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="build_snapshot", description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--registry", type=Path, default=None, help="default: registry/schools.yaml")
    parser.add_argument("--states", default="", help="comma-separated codes; default every state")
    parser.add_argument("--require-scorecard", action="store_true")
    parser.add_argument("--min-schools", type=int, default=0)
    args = parser.parse_args(argv)
    config.setup_logging(logging.WARNING)

    registry = load_bundled(args.registry)
    states = [s.strip().upper() for s in args.states.split(",") if s.strip()]
    key = config.scorecard_api_key()
    if args.require_scorecard and not key:
        _say(f"error: --require-scorecard but {config.SCORECARD_KEY_ENV} is not set")
        return 1
    try:
        snap = asyncio.run(build(registry, states=states, api_key=key))
    except BuildError as exc:
        _say(f"error: {exc}; no file written")
        return 1
    finally:
        shutdown_pool()
    _say(summary(snap))
    if len(snap.schools) < args.min_schools:
        n, want = len(snap.schools), args.min_schools
        _say(f"error: only {n} colleges (expected at least {want}); no file written")
        return 1
    if args.require_scorecard and ScorecardAdapter.name not in snap.sources:
        _say("error: College Scorecard did not answer; no file written")
        return 1
    data = encode(snap)
    args.out.write_bytes(data)
    _say(f"Wrote {args.out} ({len(data) / 1e6:.1f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
