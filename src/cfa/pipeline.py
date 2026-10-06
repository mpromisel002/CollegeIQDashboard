"""Fetch every registry school from all sources and merge into CollegeRecords.

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

from cfa import config
from cfa.aggregate import merge
from cfa.models.college import CollegeRecord
from cfa.models.field_value import Status
from cfa.sources.base import FetchResult, SourceAdapter
from cfa.sources.cds.adapter import CdsAdapter
from cfa.sources.http import HttpClient
from cfa.sources.registry import Registry, School
from cfa.sources.scorecard import ScorecardAdapter
from cfa.sources.urban_ipeds import UrbanIpedsAdapter

log = logging.getLogger(__name__)

ProgressFn = Callable[[int, int, str], None]


@dataclass
class RunResult:
    records: list[CollegeRecord] = field(default_factory=list)
    cancelled: bool = False
    health: dict[str, Status] = field(default_factory=dict)


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


async def run_all(
    registry: Registry,
    *,
    api_key: str | None = None,
    progress: ProgressFn | None = None,
    cancel: threading.Event | None = None,
    http: HttpClient | None = None,
    executor: Executor | None = None,
    unitids: list[int] | None = None,
) -> RunResult:
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
        done = 0
        total = len(schools)
        if progress:
            progress(0, total, "Starting")
        tasks = {asyncio.create_task(fetch_school(s, adapters)): s for s in schools}
        pending = set(tasks)
        while pending:
            finished, pending = await asyncio.wait(pending, timeout=0.25, return_when=asyncio.FIRST_COMPLETED)
            if cancel is not None and cancel.is_set():
                for t in pending:
                    t.cancel()
                await asyncio.gather(*pending, return_exceptions=True)
                out.cancelled = True
                break
            for t in finished:
                school = tasks[t]
                done += 1
                exc = t.exception()
                if exc is not None:  # defensive: adapters should never raise
                    log.error("Unexpected error for unitid %s: %s", school.unitid, type(exc).__name__)
                    out.records.append(merge(school.unitid, school.name, [], school_links(school)))
                else:
                    out.records.append(t.result())
                if progress:
                    progress(done, total, school.name)
    finally:
        if own_http:
            await client.__aexit__(None, None, None)
    order = {s.unitid: i for i, s in enumerate(schools)}
    out.records.sort(key=lambda r: order.get(r.unitid, 0))
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
