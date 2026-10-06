"""Urban Institute Education Data Portal adapter (IPEDS tables, no key needed)."""

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
from cfa.sources.base import FetchResult, worst
from cfa.sources.http import HttpClient
from cfa.sources.labels import URBAN_TEST_POLICY, format_phone, locale_label

SOURCE = "IPEDS (Urban)"
MAX_PAGES = 5


class _Envelope(BaseModel):
    model_config = ConfigDict(extra="ignore")
    count: int | None = None
    next: str | None = None
    results: list[dict[str, Any]]


class _Directory(BaseModel):
    model_config = ConfigDict(extra="ignore")
    inst_name: str | None = None
    address: str | None = None
    city: str | None = None
    state_abbr: str | None = None
    zip: str | None = None
    phone_number: str | None = None
    url_school: str | None = None
    urban_centric_locale: int | None = None


class _AdmEnroll(BaseModel):
    model_config = ConfigDict(extra="ignore")
    sex: int
    number_applied: float | None = None
    number_admitted: float | None = None


class _AdmReq(BaseModel):
    model_config = ConfigDict(extra="ignore")
    sat_crit_read_25_pctl: float | None = None
    sat_crit_read_75_pctl: float | None = None
    sat_math_25_pctl: float | None = None
    sat_math_75_pctl: float | None = None
    act_composite_25_pctl: float | None = None
    act_composite_75_pctl: float | None = None
    sat_percent_submitting: float | None = None
    act_percent_submitting: float | None = None
    reqt_test_scores: int | None = None


class _IC(BaseModel):
    model_config = ConfigDict(extra="ignore")
    member_ncaa: int | None = None
    member_naia: int | None = None
    study_abroad: int | None = None


class _Retention(BaseModel):
    model_config = ConfigDict(extra="ignore")
    ftpt: int | None = None
    retention_rate: float | None = None


class _GradRate(BaseModel):
    model_config = ConfigDict(extra="ignore")
    subcohort: int | None = None
    race: int | None = None
    sex: int | None = None
    completion_rate_150pct: float | None = None


class _Headcount(BaseModel):
    model_config = ConfigDict(extra="ignore")
    race: int | None = None
    sex: int | None = None
    ftpt: int | None = None
    degree_seeking: int | None = None
    class_level: int | None = None
    headcount: float | None = None


def _clean_row(row: dict[str, Any]) -> dict[str, Any]:
    return {k: sentinels.urban(v) for k, v in row.items()}


def _fv(value: Any, year: str, note: str = "") -> FieldValue:
    return FieldValue.of(value, SOURCE, year, note)


# Each topic: (path template, parser). The parser returns a dict of FieldValues.
Parser = Callable[[list[dict[str, Any]], str], dict[str, FieldValue]]


def _parse_directory(rows: list[dict[str, Any]], year: str) -> dict[str, FieldValue]:
    d = _Directory.model_validate(_clean_row(rows[0]))
    label, setting = locale_label(d.urban_centric_locale)
    zip_code = d.zip.split("-")[0] if d.zip else None
    return {
        "name": _fv(d.inst_name, year),
        "address": _fv(d.address, year),
        "city": _fv(d.city, year),
        "state": _fv(d.state_abbr, year),
        "zip": _fv(zip_code, year),
        "phone": _fv(format_phone(d.phone_number), year),
        "website": _fv(d.url_school, year),
        "locale": _fv(label, year),
        "setting": _fv(setting, year),
    }


def _parse_adm_enroll(rows: list[dict[str, Any]], year: str) -> dict[str, FieldValue]:
    by_sex: dict[int, _AdmEnroll] = {}
    for r in rows:
        rec = _AdmEnroll.model_validate(_clean_row(r))
        by_sex[rec.sex] = rec
    out: dict[str, FieldValue] = {}
    for code, suffix in ((99, "total"), (1, "men"), (2, "women"), (3, "another")):
        m = by_sex.get(code)
        app = int(m.number_applied) if m and m.number_applied is not None else None
        adm = int(m.number_admitted) if m and m.number_admitted is not None else None
        if app is not None and adm is not None and adm > app:
            out[f"applicants_{suffix}"] = FieldValue.missing(
                SOURCE, Status.PARSE_FAILED, "admits > applicants", year
            )
            out[f"admits_{suffix}"] = FieldValue.missing(
                SOURCE, Status.PARSE_FAILED, "admits > applicants", year
            )
            continue
        out[f"applicants_{suffix}"] = _fv(app, year)
        out[f"admits_{suffix}"] = _fv(adm, year)
    return out


def _score(v: float | None, lo: int, hi: int) -> int | None:
    if v is None or not (lo <= v <= hi):
        return None
    return int(v)


def _pct(v: float | None) -> float | None:
    if v is None or not (0 <= v <= 100):
        return None
    return float(v)


def _parse_adm_req(rows: list[dict[str, Any]], year: str) -> dict[str, FieldValue]:
    m = _AdmReq.model_validate(_clean_row(rows[0]))
    policy = URBAN_TEST_POLICY.get(m.reqt_test_scores) if m.reqt_test_scores is not None else None
    return {
        "sat_ebrw_25": _fv(_score(m.sat_crit_read_25_pctl, 200, 800), year),
        "sat_ebrw_75": _fv(_score(m.sat_crit_read_75_pctl, 200, 800), year),
        "sat_math_25": _fv(_score(m.sat_math_25_pctl, 200, 800), year),
        "sat_math_75": _fv(_score(m.sat_math_75_pctl, 200, 800), year),
        "act_25": _fv(_score(m.act_composite_25_pctl, 1, 36), year),
        "act_75": _fv(_score(m.act_composite_75_pctl, 1, 36), year),
        "sat_submit_pct": _fv(_pct(m.sat_percent_submitting), year),
        "act_submit_pct": _fv(_pct(m.act_percent_submitting), year),
        "test_policy": _fv(policy, year),
    }


def _parse_ic(rows: list[dict[str, Any]], year: str) -> dict[str, FieldValue]:
    m = _IC.model_validate(_clean_row(rows[0]))
    if m.member_ncaa is None and m.member_naia is None:
        athletics = None
    elif m.member_ncaa == 1:
        athletics = "NCAA"
    elif m.member_naia == 1:
        athletics = "NAIA"
    else:
        athletics = "None (not NCAA/NAIA)"
    abroad = None if m.study_abroad is None else m.study_abroad == 1
    return {"athletics": _fv(athletics, year), "study_abroad": _fv(abroad, year)}


def _parse_retention(rows: list[dict[str, Any]], year: str) -> dict[str, FieldValue]:
    for r in rows:
        m = _Retention.model_validate(_clean_row(r))
        if m.ftpt == 1 and m.retention_rate is not None and 0 <= m.retention_rate <= 1:
            return {"retention_rate": _fv(round(m.retention_rate * 100, 1), year)}
    return {"retention_rate": FieldValue.missing(SOURCE, year=year)}


def _parse_grad(rows: list[dict[str, Any]], year: str) -> dict[str, FieldValue]:
    for r in rows:
        m = _GradRate.model_validate(_clean_row(r))
        rate = m.completion_rate_150pct
        if (m.subcohort, m.race, m.sex) == (2, 99, 99) and rate is not None and 0 <= rate <= 1:
            return {"grad_rate_6yr": _fv(round(rate * 100, 1), year)}
    return {"grad_rate_6yr": FieldValue.missing(SOURCE, year=year)}


def _parse_headcount(rows: list[dict[str, Any]], year: str) -> dict[str, FieldValue]:
    for r in rows:
        m = _Headcount.model_validate(_clean_row(r))
        totals = (m.race, m.sex, m.ftpt, m.degree_seeking, m.class_level) == (99, 99, 99, 99, 99)
        if totals and m.headcount is not None:
            return {"undergrad_size": _fv(int(m.headcount), year)}
    return {"undergrad_size": FieldValue.missing(SOURCE, year=year)}


TOPICS: dict[str, tuple[str, Parser, tuple[str, ...]]] = {
    "directory": (
        "directory/{year}/",
        _parse_directory,
        ("name", "address", "city", "state", "zip", "phone", "website", "locale", "setting"),
    ),
    "admissions-enrollment": (
        "admissions-enrollment/{year}/",
        _parse_adm_enroll,
        (
            "applicants_total",
            "applicants_men",
            "applicants_women",
            "applicants_another",
            "admits_total",
            "admits_men",
            "admits_women",
            "admits_another",
        ),
    ),
    "admissions-requirements": (
        "admissions-requirements/{year}/",
        _parse_adm_req,
        (
            "sat_ebrw_25",
            "sat_ebrw_75",
            "sat_math_25",
            "sat_math_75",
            "act_25",
            "act_75",
            "sat_submit_pct",
            "act_submit_pct",
            "test_policy",
        ),
    ),
    "institutional-characteristics": (
        "institutional-characteristics/{year}/",
        _parse_ic,
        ("athletics", "study_abroad"),
    ),
    "fall-retention": ("fall-retention/{year}/", _parse_retention, ("retention_rate",)),
    "grad-rates": ("grad-rates/{year}/", _parse_grad, ("grad_rate_6yr",)),
    "enrollment-headcount": (
        "enrollment-headcount/{year}/undergraduate/",
        _parse_headcount,
        ("undergrad_size",),
    ),
}


class UrbanIpedsAdapter:
    name = SOURCE

    def __init__(
        self,
        http: HttpClient,
        cache: SessionCache = CACHE,
        base_url: str = config.URBAN_BASE_URL,
        this_year: int | None = None,
    ) -> None:
        self.http = http
        self.cache = cache
        self.base_url = base_url.rstrip("/")
        self.this_year = this_year or config.current_year()

    def _years(self, topic: str) -> list[int]:
        start = self.this_year - 1
        years = list(range(start, start - config.URBAN_YEAR_WALKBACK - 1, -1))
        known = self.cache.get(("urban-year", topic))
        if known in years:
            years.remove(known)
            years.insert(0, known)
        return years

    async def _rows(self, url: str) -> tuple[Status, list[dict[str, Any]], str]:
        rows: list[dict[str, Any]] = []
        next_url: str | None = url
        for _ in range(MAX_PAGES):
            if not next_url:
                break
            res = await self.http.get(next_url)
            if not res.ok:
                return res.status, [], res.note
            try:
                env = _Envelope.model_validate(res.json())
            except (ValueError, ValidationError):
                return Status.PARSE_FAILED, [], "Unexpected response format"
            rows.extend(env.results)
            next_url = env.next
        return Status.OK, rows, ""

    async def fetch_topic(
        self, topic: str, unitid: int
    ) -> tuple[Status, dict[str, FieldValue], str, str | None]:
        path, parser, keys = TOPICS[topic]
        last_status, last_note = Status.NOT_REPORTED, "No data in recent years"
        for year in self._years(topic):
            url = f"{self.base_url}/{path.format(year=year)}?unitid={unitid}"
            status, rows, note = await self._rows(url)
            if status is not Status.OK:
                # A failure for one year means the source is down/limited; don't keep walking.
                return status, {k: FieldValue.missing(SOURCE, status, note) for k in keys}, note, None
            if rows:
                self.cache.set(("urban-year", topic), year)
                try:
                    data = parser(rows, str(year))
                except (ValidationError, ValueError, TypeError, KeyError, IndexError):
                    return (
                        Status.PARSE_FAILED,
                        {
                            k: FieldValue.missing(SOURCE, Status.PARSE_FAILED, "Unexpected record format")
                            for k in keys
                        },
                        "Unexpected record format",
                        str(year),
                    )
                for k in keys:
                    data.setdefault(k, FieldValue.missing(SOURCE, year=str(year)))
                missing = [k for k in keys if not data[k].ok]
                return (Status.PARTIAL if missing else Status.OK), data, "", str(year)
        return last_status, {k: FieldValue.missing(SOURCE, note=last_note) for k in keys}, last_note, None

    async def fetch(self, unitid: int) -> FetchResult:
        cached = self.cache.get(("urban", unitid))
        if cached is not None:
            return cached
        start = time.monotonic()
        results = await asyncio.gather(*(self.fetch_topic(t, unitid) for t in TOPICS))
        data: dict[str, FieldValue] = {}
        statuses: list[Status] = []
        notes: list[str] = []
        for status, fields, note, _year in results:
            data.update(fields)
            statuses.append(Status.OK if status in (Status.OK, Status.PARTIAL) else status)
            if note:
                notes.append(note)
        status = worst(statuses)
        if status is Status.OK and any(s is Status.PARTIAL for s, *_ in results):
            status = Status.PARTIAL
        out = FetchResult(
            SOURCE, status, data, "; ".join(sorted(set(notes))), elapsed_s=time.monotonic() - start
        )
        if status not in (Status.SOURCE_UNAVAILABLE, Status.RATE_LIMITED):
            self.cache.set(("urban", unitid), out)
        return out

    async def health_check(self) -> FetchResult:
        url = f"{self.base_url.split('/college-university')[0]}/api-endpoints/?mode=R"
        res = await self.http.get(url)
        status = Status.OK if res.ok else res.status
        return FetchResult(SOURCE, status, note=res.note or "Reachable", elapsed_s=res.elapsed_s)
