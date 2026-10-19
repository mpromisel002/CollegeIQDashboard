"""U.S. Dept. of Education College Scorecard adapter (free api.data.gov key)."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError

from cfa import config
from cfa.cache import CACHE, SessionCache
from cfa.models.field_value import FieldValue, Status
from cfa.sources import sentinels
from cfa.sources.base import FetchResult
from cfa.sources.http import HttpClient
from cfa.sources.labels import SCORECARD_TEST_POLICY, locale_label

SOURCE = "College Scorecard"
YEAR = "latest"
PER_PAGE = 100  # the API's maximum page size

# Scorecard dotted field name -> our field key
FIELD_MAP: dict[str, str] = {
    "school.name": "name",
    "school.city": "city",
    "school.state": "state",
    "school.zip": "zip",
    "school.school_url": "website",
    "school.locale": "locale",
    "latest.student.size": "undergrad_size",
    "latest.admissions.admission_rate.overall": "acceptance_rate",
    "latest.admissions.sat_scores.25th_percentile.critical_reading": "sat_ebrw_25",
    "latest.admissions.sat_scores.75th_percentile.critical_reading": "sat_ebrw_75",
    "latest.admissions.sat_scores.25th_percentile.math": "sat_math_25",
    "latest.admissions.sat_scores.75th_percentile.math": "sat_math_75",
    "latest.admissions.act_scores.25th_percentile.cumulative": "act_25",
    "latest.admissions.act_scores.75th_percentile.cumulative": "act_75",
    "latest.admissions.test_requirements": "test_policy",
    "latest.student.retention_rate.four_year.full_time": "retention_rate",
    "latest.completion.completion_rate_4yr_150nt": "grad_rate_6yr",
}


class _Envelope(BaseModel):
    model_config = ConfigDict(extra="ignore")
    results: list[dict[str, Any]]


def _score(lo: int, hi: int) -> Callable[[Any], Any]:
    def f(v: Any) -> int | None:
        n = sentinels.scorecard_num(v)
        return int(n) if n is not None and lo <= n <= hi else None

    return f


def _rate(v: Any) -> float | None:
    n = sentinels.scorecard_num(v)
    return round(n * 100, 1) if n is not None and 0 <= n <= 1 else None


def _text(v: Any) -> str | None:
    v = sentinels.scorecard(v)
    return str(v).strip() if v is not None else None


def _size(v: Any) -> int | None:
    n = sentinels.scorecard_num(v)
    return int(n) if n is not None else None


def _zip(v: Any) -> str | None:
    t = _text(v)
    return t.split("-")[0] if t else None


def _policy(v: Any) -> str | None:
    n = sentinels.scorecard_num(v)
    return SCORECARD_TEST_POLICY.get(int(n)) if n is not None else None


CONVERTERS: dict[str, Callable[[Any], Any]] = {
    "name": _text,
    "city": _text,
    "state": _text,
    "zip": _zip,
    "website": _text,
    "undergrad_size": _size,
    "acceptance_rate": _rate,
    "sat_ebrw_25": _score(200, 800),
    "sat_ebrw_75": _score(200, 800),
    "sat_math_25": _score(200, 800),
    "sat_math_75": _score(200, 800),
    "act_25": _score(1, 36),
    "act_75": _score(1, 36),
    "test_policy": _policy,
    "retention_rate": _rate,
    "grad_rate_6yr": _rate,
}


def parse_school(row: dict[str, Any]) -> dict[str, FieldValue]:
    out: dict[str, FieldValue] = {}
    for api_name, key in FIELD_MAP.items():
        raw = row.get(api_name)
        if key == "locale":
            n = sentinels.scorecard_num(raw)
            label, setting = locale_label(int(n) if n is not None else None)
            out["locale"] = FieldValue.of(label, SOURCE, YEAR)
            out["setting"] = FieldValue.of(setting, SOURCE, YEAR)
            continue
        out[key] = FieldValue.of(CONVERTERS[key](raw), SOURCE, YEAR)
    return out


class ScorecardAdapter:
    name = SOURCE

    def __init__(
        self,
        http: HttpClient,
        api_key: str | None = None,
        cache: SessionCache = CACHE,
        base_url: str = config.SCORECARD_BASE_URL,
    ) -> None:
        self.http = http
        self.api_key = api_key
        self.cache = cache
        self.base_url = base_url
        self._bulk: dict[int, FetchResult] = {}  # filled by prefetch(), for this run only

    def _all_missing(self, status: Status, note: str) -> dict[str, FieldValue]:
        keys = [*FIELD_MAP.values(), "setting"]
        return {k: FieldValue.missing(SOURCE, status, note) for k in keys}

    async def fetch(self, unitid: int) -> FetchResult:
        if not self.api_key:
            note = "No College Scorecard API key set (Settings)"
            return FetchResult(
                SOURCE, Status.AUTH_MISSING, self._all_missing(Status.AUTH_MISSING, note), note
            )
        cached = self.cache.get(("scorecard", unitid)) or self._bulk.get(unitid)
        if cached is not None:
            return cached
        start = time.monotonic()
        params = {"id": unitid, "fields": ",".join(["id", *FIELD_MAP]), "api_key": self.api_key}
        res = await self.http.get(self.base_url, params=params)
        if not res.ok:
            return FetchResult(
                SOURCE, res.status, self._all_missing(res.status, res.note), res.note, elapsed_s=res.elapsed_s
            )
        try:
            env = _Envelope.model_validate(res.json())
        except (ValueError, ValidationError):
            note = "Unexpected response format"
            return FetchResult(
                SOURCE, Status.PARSE_FAILED, self._all_missing(Status.PARSE_FAILED, note), note
            )
        if not env.results:
            note = "School not found in Scorecard"
            return FetchResult(
                SOURCE, Status.NOT_REPORTED, self._all_missing(Status.NOT_REPORTED, note), note
            )
        data = parse_school(env.results[0])
        status = Status.OK if all(fv.ok for fv in data.values()) else Status.PARTIAL
        out = FetchResult(SOURCE, status, data, year=YEAR, elapsed_s=time.monotonic() - start)
        self.cache.set(("scorecard", unitid), out)
        return out

    async def prefetch(self, unitids: list[int], progress: Callable[[str], None] | None = None) -> None:
        """Load many schools with one request per 100 (the API's page limit) instead of one each."""
        if not self.api_key:
            return
        todo = [u for u in unitids if self.cache.get(("scorecard", u)) is None]
        chunks = [todo[i : i + PER_PAGE] for i in range(0, len(todo), PER_PAGE)]

        async def one(chunk: list[int]) -> None:
            start = time.monotonic()
            params = {
                "id": ",".join(str(u) for u in chunk),
                "fields": ",".join(["id", *FIELD_MAP]),
                "per_page": PER_PAGE,
                "api_key": self.api_key,
            }
            res = await self.http.get(self.base_url, params=params)
            try:
                env = _Envelope.model_validate(res.json()) if res.ok else None
            except (ValueError, ValidationError):
                env = None
            if env is None:
                status = res.status if not res.ok else Status.PARSE_FAILED
                note = res.note or "Unexpected response format"
                for u in chunk:  # remembered for this run only, so a later Retry asks again
                    self._bulk[u] = FetchResult(SOURCE, status, self._all_missing(status, note), note)
                return
            seen: set[int] = set()
            for row in env.results:
                uid = row.get("id")
                if not isinstance(uid, int):
                    continue
                seen.add(uid)
                data = parse_school(row)
                ok = all(fv.ok for fv in data.values())
                out = FetchResult(
                    SOURCE,
                    Status.OK if ok else Status.PARTIAL,
                    data,
                    year=YEAR,
                    elapsed_s=time.monotonic() - start,
                )
                self.cache.set(("scorecard", uid), out)
            for u in chunk:
                if u not in seen:
                    note = "School not found in Scorecard"
                    self._bulk[u] = FetchResult(
                        SOURCE, Status.NOT_REPORTED, self._all_missing(Status.NOT_REPORTED, note), note
                    )
            if progress:
                progress("scorecard")

        await asyncio.gather(*(one(c) for c in chunks))

    async def health_check(self) -> FetchResult:
        if not self.api_key:
            return FetchResult(SOURCE, Status.AUTH_MISSING, note="No API key set")
        res = await self.http.get(
            self.base_url, params={"id": 166027, "fields": "id", "api_key": self.api_key}
        )
        return FetchResult(
            SOURCE, Status.OK if res.ok else res.status, note=res.note or "Reachable", elapsed_s=res.elapsed_s
        )
