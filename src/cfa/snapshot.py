"""The weekly data file: every college's source results, pre-fetched so searches take seconds.

.github/workflows/data-snapshot.yml runs `python -m cfa.tools.build_snapshot` once a week. It loads
IPEDS and College Scorecard for every four-year college and reads the curated schools' Common Data
Sets, exactly as a live search would, and publishes the results to the public registry repo. The
app downloads that one file at startup and answers searches from it; anything the file lacks (or a
file that is missing or too old) falls back to the live sources.

The file holds each source's own results (values, years, statuses, notes), not merged records, so
merging, scoring and the source badges work exactly as with live data.
"""

from __future__ import annotations

import gzip
import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from cfa import __version__, config
from cfa.models.field_value import FieldValue, Status
from cfa.sources.base import FetchResult, SourceAdapter
from cfa.sources.http import HttpClient
from cfa.sources.registry import Registry

log = logging.getLogger(__name__)

SCHEMA_VERSION = 1
MAX_BYTES = 40 * 1024 * 1024  # compressed; a nationwide file is a few MB


class SnapshotError(Exception):
    pass


def _encode_field(fv: FieldValue) -> list[Any]:
    return [fv.value, fv.source, fv.year, fv.status.value, fv.note, fv.estimated]


def _decode_field(v: list[Any]) -> FieldValue:
    value, source, year, status, note, estimated = v
    return FieldValue(value, source, year, Status(status), note, bool(estimated))


def _encode_result(r: FetchResult) -> dict[str, Any]:
    return {
        "source": r.source,
        "status": r.status.value,
        "note": r.note,
        "year": r.year,
        "details": r.details,
        "data": {k: _encode_field(fv) for k, fv in r.data.items()},
    }


def _decode_result(d: dict[str, Any]) -> FetchResult:
    return FetchResult(
        d["source"],
        Status(d["status"]),
        {k: _decode_field(v) for k, v in d["data"].items()},
        d.get("note") or "",
        d.get("year"),
        details=dict(d.get("details") or {}),
    )


@dataclass
class SnapshotSchool:
    unitid: int
    name: str
    state: str
    candidate: bool  # a four-year college run_search lists (curated schools are always listed)
    cds_url: str | None  # the document the Common Data Set result was read from
    results: dict[str, FetchResult] = field(default_factory=dict)


@dataclass
class Snapshot:
    built_at: datetime
    schools: dict[int, SnapshotSchool]
    sources: list[str]  # sources that answered when the file was built
    states: list[str] = field(default_factory=list)  # [] = every state (a partial file is for testing)

    def covers(self, states: list[str]) -> bool:
        """Whether a search of `states` ([] = every state) can be answered from this file."""
        return not self.states or (bool(states) and set(states) <= set(self.states))

    def age(self, now: datetime | None = None) -> timedelta:
        return (now or datetime.now(UTC)) - self.built_at

    def result(self, unitid: int, source: str) -> FetchResult | None:
        school = self.schools.get(unitid)
        return school.results.get(source) if school else None

    def has_source(self, source: str) -> bool:
        return source in self.sources


def encode(snapshot: Snapshot) -> bytes:
    doc = {
        "schema_version": SCHEMA_VERSION,
        "built_at": snapshot.built_at.isoformat(),
        "built_by": f"College Fit Advisor {__version__}",
        "sources": snapshot.sources,
        "states": snapshot.states,
        "schools": [
            {
                "unitid": s.unitid,
                "name": s.name,
                "state": s.state,
                "candidate": s.candidate,
                "cds_url": s.cds_url,
                "results": [_encode_result(r) for r in s.results.values()],
            }
            for s in sorted(snapshot.schools.values(), key=lambda s: s.unitid)
        ],
    }
    raw = json.dumps(doc, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return gzip.compress(raw, compresslevel=9, mtime=0)


def decode(content: bytes) -> Snapshot:
    try:
        doc = json.loads(gzip.decompress(content))
    except (OSError, EOFError, ValueError) as exc:
        raise SnapshotError(f"unreadable ({type(exc).__name__})") from exc
    if not isinstance(doc, dict) or doc.get("schema_version") != SCHEMA_VERSION:
        raise SnapshotError("unsupported format version")
    try:
        built = datetime.fromisoformat(doc["built_at"])
        if built.tzinfo is None:
            built = built.replace(tzinfo=UTC)
        schools: dict[int, SnapshotSchool] = {}
        for s in doc["schools"]:
            results = [_decode_result(r) for r in s["results"]]
            schools[int(s["unitid"])] = SnapshotSchool(
                int(s["unitid"]),
                str(s["name"]),
                str(s.get("state") or ""),
                bool(s.get("candidate")),
                s.get("cds_url"),
                {r.source: r for r in results},
            )
        return Snapshot(
            built,
            schools,
            [str(x) for x in doc.get("sources", [])],
            [str(x) for x in doc.get("states", [])],
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise SnapshotError(f"malformed ({type(exc).__name__})") from exc


@dataclass
class SnapshotLoad:
    snapshot: Snapshot | None
    note: str = ""  # why there is none, for the log and the header tooltip


async def load_snapshot(
    http: HttpClient, url: str = config.SNAPSHOT_URL, max_age_days: int = config.SNAPSHOT_MAX_AGE_DAYS
) -> SnapshotLoad:
    res = await http.get(url, max_bytes=MAX_BYTES)
    if not res.ok:
        log.info("Weekly data file unavailable: %s %s", res.status.value, res.note)
        return SnapshotLoad(None, "The weekly data file could not be downloaded; searches use live data.")
    try:
        snap = decode(res.content)
    except SnapshotError as exc:
        log.warning("Weekly data file rejected: %s", exc)
        return SnapshotLoad(None, "The weekly data file is unreadable; searches use live data.")
    if snap.age() > timedelta(days=max_age_days):
        log.warning("Weekly data file is %d days old; not used", snap.age().days)
        return SnapshotLoad(None, "The weekly data file is out of date; searches use live data.")
    log.info("Weekly data file: %d schools, built %s", len(snap.schools), snap.built_at.isoformat())
    return SnapshotLoad(snap)


class FromSnapshot:
    """An adapter that answers from the weekly file, and asks the live adapter for anything else.

    For the Common Data Set the stored result is used only when it was read from the document the
    registry lists now; a school whose document changed since the file was built is read live.
    """

    def __init__(self, live: SourceAdapter, snapshot: Snapshot, registry: Registry | None = None) -> None:
        self.live = live
        self.name = live.name
        self.snapshot = snapshot
        self.registry = registry

    def has(self, unitid: int) -> bool:
        stored = self.snapshot.result(unitid, self.name)
        if stored is None:
            return False
        if self.registry is None:
            return True
        school = self.registry.get(unitid)
        doc = school.latest_cds if school else None
        return (doc.url if doc else None) == self.snapshot.schools[unitid].cds_url

    async def fetch(self, unitid: int) -> FetchResult:
        if self.has(unitid):
            stored = self.snapshot.result(unitid, self.name)
            assert stored is not None
            return stored
        return await self.live.fetch(unitid)

    async def health_check(self) -> FetchResult:
        return await self.live.health_check()
