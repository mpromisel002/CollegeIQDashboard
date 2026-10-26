"""Fetch schools from all sources and merge into CollegeRecords.

run_all: the curated registry, school by school. run_search: every four-year college in some states.

Runs inside one asyncio event loop (a worker thread's asyncio.run); never on the Qt main thread.
"""

from __future__ import annotations

import asyncio
import logging
import os
import threading
from collections.abc import Callable
from concurrent.futures import Executor, ProcessPoolExecutor
from dataclasses import dataclass, field
from typing import Any

from cfa import config
from cfa.aggregate import merge
from cfa.models.college import CollegeRecord
from cfa.models.field_value import Status
from cfa.sources.base import FetchResult, SourceAdapter
from cfa.sources.cds.adapter import SOURCE as CDS_SOURCE
from cfa.sources.cds.adapter import CdsAdapter
from cfa.sources.http import HttpClient
from cfa.sources.registry import Registry, School
from cfa.sources.scorecard import ScorecardAdapter
from cfa.sources.urban_ipeds import TOPICS, UrbanIpedsAdapter, is_candidate_college
from cfa.states import STATE_FIPS

log = logging.getLogger(__name__)

ProgressFn = Callable[[int, int, str], None]


@dataclass
class RunResult:
    records: list[CollegeRecord] = field(default_factory=list)
    cancelled: bool = False
    health: dict[str, Status] = field(default_factory=dict)
    note: str = ""  # shown to the advisor, e.g. a fallback
    searched_states: list[str] | None = None  # set by run_search; [] means every state


def school_links(school: School) -> dict[str, str]:
    links = {k: v for k, v in school.links.model_dump().items() if v}
    if school.latest_cds:
        links["cds"] = school.latest_cds.url
    return links


_POOL: ProcessPoolExecutor | None = None
_POOL_LOCK = threading.Lock()


def parse_pool() -> Executor | None:
    """Process pool for CPU-bound CDS parsing; None (thread executor) if processes are unavailable."""
    global _POOL
    if os.environ.get("CFA_NO_PROCESS_POOL"):
        return None
    with _POOL_LOCK:
        if _POOL is None:
            try:
                _POOL = ProcessPoolExecutor(max_workers=max(1, min(4, (os.cpu_count() or 2) - 1)))
            except (OSError, NotImplementedError, ValueError):
                return None
        return _POOL


def shutdown_pool() -> None:
    global _POOL
    with _POOL_LOCK:
        if _POOL is not None:
            _POOL.shutdown(wait=False, cancel_futures=True)
            _POOL = None


async def fetch_school(school: School, adapters: list[SourceAdapter]) -> CollegeRecord:
    results: list[FetchResult] = await asyncio.gather(*(a.fetch(school.unitid) for a in adapters))
    return merge(school.unitid, school.name, list(results), school_links(school))


CDS_LOADING = "Reading the Common Data Set…"
RecordsFn = Callable[[list[CollegeRecord]], None]
RecordFn = Callable[[CollegeRecord], None]


async def _drain(
    tasks: dict[asyncio.Task, tuple[int, str, dict[str, str]]],
    on_done: Callable[[tuple[int, str, dict[str, str]], Any], None],
    on_error: Callable[[tuple[int, str, dict[str, str]]], None],
    progress: ProgressFn | None,
    label: Callable[[str], str],
    cancel: threading.Event | None,
) -> bool:
    """Wait for tasks, reporting progress as each lands. Returns False if cancelled."""
    done, total = 0, len(tasks)
    pending = set(tasks)
    while pending:
        finished, pending = await asyncio.wait(pending, timeout=0.25, return_when=asyncio.FIRST_COMPLETED)
        if cancel is not None and cancel.is_set():
            for t in pending:
                t.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            return False
        for t in finished:
            item = tasks[t]
            done += 1
            if t.exception() is not None:  # defensive: adapters should never raise
                log.error("Unexpected error for unitid %s: %s", item[0], type(t.exception()).__name__)
                on_error(item)
            else:
                on_done(item, t.result())
            if progress:
                progress(done, total, label(item[1]))
    return True


async def _fetch_many(
    schools: list[tuple[int, str, dict[str, str]]],
    adapters: list[SourceAdapter],
    out: RunResult,
    progress: ProgressFn | None,
    cancel: threading.Event | None,
    *,
    cds: SourceAdapter | None = None,
    on_partial: RecordsFn | None = None,
    on_update: RecordFn | None = None,
) -> None:
    """Fetch and merge (unitid, fallback name, links) in parallel.

    Two phases: every school from the fast sources first, then the Common Data Sets (seconds each to
    read). on_partial gets the records after phase one, with "still loading" CDS fields, so results
    can be shown straight away; on_update gets each record again once its CDS is in.
    """
    fast: dict[int, list[FetchResult]] = {}
    slow = [s for s in schools if cds is not None and s[2].get("cds")]
    slow_ids = {s[0] for s in slow}
    loading = FetchResult(CDS_SOURCE, Status.NOT_REPORTED, note=CDS_LOADING)

    async def phase_one(unitid: int, name: str, links: dict[str, str]) -> CollegeRecord:
        results = list(await asyncio.gather(*(a.fetch(unitid) for a in adapters)))
        if cds is not None and unitid not in slow_ids:
            results.append(await cds.fetch(unitid))  # instant: no document listed
        fast[unitid] = results
        return merge(unitid, name, results + ([loading] if unitid in slow_ids else []), links)

    def keep(item: tuple[int, str, dict[str, str]], record: Any) -> None:
        out.records.append(record)

    def broken(item: tuple[int, str, dict[str, str]]) -> None:
        out.records.append(merge(item[0], item[1], [], item[2]))

    if progress:
        progress(0, len(schools), "Fetching schools")
    tasks: dict[asyncio.Task, tuple[int, str, dict[str, str]]] = {
        asyncio.create_task(phase_one(*s)): s for s in schools
    }
    finished = await _drain(tasks, keep, broken, progress, lambda name: name, cancel)
    order = {s[0]: i for i, s in enumerate(schools)}
    out.records.sort(key=lambda r: order.get(r.unitid, 0))
    if not finished:
        out.cancelled = True
        return
    if not slow or cds is None:
        return
    if on_partial:
        on_partial(list(out.records))
    where = {r.unitid: i for i, r in enumerate(out.records)}
    reader = cds

    def update(item: tuple[int, str, dict[str, str]], result: Any) -> None:
        unitid, name, links = item
        record = merge(unitid, name, [*fast.get(unitid, []), result], links)
        out.records[where[unitid]] = record
        if on_update:
            on_update(record)

    def failed(item: tuple[int, str, dict[str, str]]) -> None:
        note = FetchResult(CDS_SOURCE, Status.SOURCE_UNAVAILABLE, note="Could not read the document")
        update(item, note)

    reads: dict[asyncio.Task, tuple[int, str, dict[str, str]]] = {
        asyncio.create_task(reader.fetch(s[0])): s for s in slow
    }
    if not await _drain(
        reads, update, failed, progress, lambda name: f"Reading Common Data Sets: {name}", cancel
    ):
        out.cancelled = True


async def run_all(
    registry: Registry,
    *,
    api_key: str | None = None,
    progress: ProgressFn | None = None,
    cancel: threading.Event | None = None,
    http: HttpClient | None = None,
    executor: Executor | None = None,
    on_partial: RecordsFn | None = None,
    on_update: RecordFn | None = None,
    unitids: list[int] | None = None,
) -> RunResult:
    """The curated list only (or just `unitids`): every source, school by school."""
    schools = [s for s in registry.schools if unitids is None or s.unitid in unitids]
    out = RunResult()
    own_http = http is None
    client = http or HttpClient()
    if own_http:
        await client.__aenter__()
    try:
        adapters: list[SourceAdapter] = [
            UrbanIpedsAdapter(client),
            ScorecardAdapter(client, api_key),
            CdsAdapter(client, registry, executor=executor),
        ]
        items = [(s.unitid, s.name, school_links(s)) for s in schools]
        listed = {s.unitid for s in registry.schools}
        # A school found by run_search (not on the list) can be retried too; IPEDS supplies its name.
        items += [(u, f"UnitID {u}", {}) for u in (unitids or []) if u not in listed]
        await _fetch_many(
            items,
            adapters[:2],
            out,
            progress,
            cancel,
            cds=adapters[2],
            on_partial=on_partial,
            on_update=on_update,
        )
    finally:
        if own_http:
            await client.__aexit__(None, None, None)
    return out


async def run_search(
    registry: Registry,
    *,
    states: list[str] | None = None,
    api_key: str | None = None,
    progress: ProgressFn | None = None,
    cancel: threading.Event | None = None,
    http: HttpClient | None = None,
    executor: Executor | None = None,
    on_partial: RecordsFn | None = None,
    on_update: RecordFn | None = None,
) -> RunResult:
    """Every four-year college in `states` (all states if empty), not only the curated list.

    IPEDS and Scorecard are loaded in bulk (a few requests per state); the curated schools also get
    their Common Data Set. If IPEDS cannot list the colleges, falls back to the curated list.
    """
    fips = [STATE_FIPS[s] for s in (states or []) if s in STATE_FIPS] or None
    out = RunResult()
    own_http = http is None
    client = http or HttpClient()
    if own_http:
        await client.__aenter__()
    try:
        urban = UrbanIpedsAdapter(client)
        scorecard = ScorecardAdapter(client, api_key)
        cds = CdsAdapter(client, registry, executor=executor)
        where = ", ".join(states or []) or "all states"
        steps = [0]
        n_steps = len(TOPICS) + 1

        def tick(_what: str) -> None:
            steps[0] += 1
            if progress:
                progress(min(steps[0], n_steps), n_steps, f"Loading federal data for {where}")

        if progress:
            progress(0, n_steps, f"Finding four-year colleges in {where}")
        await urban.prefetch(fips, progress=tick)
        if cancel is not None and cancel.is_set():
            out.cancelled = True
            return out
        if not urban.directory_rows:
            out.note = (
                "Could not get the list of colleges from IPEDS right now; showing the curated list instead."
            )
            wanted = set(states or [])
            curated = await run_all(
                registry,
                api_key=api_key,
                progress=progress,
                cancel=cancel,
                http=client,
                executor=executor,
                on_partial=on_partial,
                on_update=on_update,
            )
            curated.note = out.note
            if wanted:
                curated.records = [r for r in curated.records if str(r.value("state") or "") in wanted]
            return curated

        in_scope = {r["unitid"]: r for r in urban.directory_rows if isinstance(r.get("unitid"), int)}
        picked = [uid for uid, row in in_scope.items() if is_candidate_college(row)]
        listed = {s.unitid: s for s in registry.schools}
        for uid in listed:  # curated schools always count, even if IPEDS classifies them oddly
            if uid not in picked and (uid in in_scope or fips is None):
                picked.append(uid)
        n_steps += (len(picked) + 99) // 100 if api_key else 0
        await scorecard.prefetch(picked, progress=tick)
        if cancel is not None and cancel.is_set():
            out.cancelled = True
            return out

        def name_of(uid: int) -> str:
            if uid in listed:
                return listed[uid].name
            return str(in_scope.get(uid, {}).get("inst_name") or f"UnitID {uid}")

        items = [
            (uid, name_of(uid), school_links(listed[uid]) if uid in listed else {})
            for uid in sorted(picked, key=lambda u: name_of(u).lower())
        ]
        out.searched_states = list(states or [])
        await _fetch_many(
            items,
            [urban, scorecard],
            out,
            progress,
            cancel,
            cds=cds,
            on_partial=on_partial,
            on_update=on_update,
        )
    finally:
        if own_http:
            await client.__aexit__(None, None, None)
    return out


async def health_checks(registry: Registry, api_key: str | None) -> dict[str, FetchResult]:
    async with HttpClient(max_retries=1) as client:
        adapters: list[SourceAdapter] = [
            UrbanIpedsAdapter(client),
            ScorecardAdapter(client, api_key),
            CdsAdapter(client, registry),
        ]
        results = await asyncio.gather(*(a.health_check() for a in adapters))
        return {r.source: r for r in results}


def default_api_key() -> str | None:
    return config.scorecard_api_key()
