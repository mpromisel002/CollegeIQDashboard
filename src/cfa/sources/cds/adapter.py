"""Common Data Set adapter: registry URL -> in-memory download -> parse -> section extractors."""

from __future__ import annotations

import asyncio
import logging
import time
from concurrent.futures import Executor

from cfa.cache import CACHE, SessionCache
from cfa.models.field_value import FieldValue, Status
from cfa.sources.base import FetchResult
from cfa.sources.cds.fetch import fetch_cds
from cfa.sources.cds.layout import Document
from cfa.sources.cds.parse_pdf import PdfError, parse_pdf
from cfa.sources.cds.parse_xlsx import XlsxError, parse_xlsx
from cfa.sources.cds.sections import SOURCE, SectionResult, extract_all
from cfa.sources.http import HttpClient
from cfa.sources.registry import Registry

log = logging.getLogger(__name__)

CDS_KEYS = (
    "applicants_total",
    "applicants_men",
    "applicants_women",
    "applicants_another",
    "admits_total",
    "admits_men",
    "admits_women",
    "admits_another",
    "ed_offered",
    "ed_applicants",
    "ed_admits",
    "ed_rate",
    "ea_offered",
    "ea_applicants",
    "ea_admits",
    "ea_rate",
    "gpa_avg",
    "gpa_dist",
    "sat_ebrw_25",
    "sat_ebrw_75",
    "sat_math_25",
    "sat_math_75",
    "act_25",
    "act_75",
    "sat_submit_pct",
    "act_submit_pct",
    "test_policy",
    "greek_men_pct",
    "greek_women_pct",
    "housing_pct",
    "study_abroad",
    "retention_rate",
    "grad_rate_6yr",
    "admission_factors",
)


def parse_document(content: bytes, fmt: str, year: str | None) -> tuple[dict[str, SectionResult], str]:
    """CPU-bound; safe to run in a worker process. Returns (sections, error note)."""
    try:
        doc: Document = parse_pdf(content) if fmt == "pdf" else parse_xlsx(content)
    except (PdfError, XlsxError) as exc:
        return {}, str(exc)
    except Exception as exc:  # malformed files must never crash the app
        return {}, f"Could not read the document ({type(exc).__name__})"
    return extract_all(doc, year), ""


class CdsAdapter:
    name = SOURCE

    def __init__(
        self,
        http: HttpClient,
        registry: Registry,
        cache: SessionCache = CACHE,
        executor: Executor | None = None,
    ) -> None:
        self.http = http
        self.registry = registry
        self.cache = cache
        self.executor = executor

    def _missing(self, status: Status, note: str, year: str | None = None) -> dict[str, FieldValue]:
        return {k: FieldValue.missing(SOURCE, status, note, year) for k in CDS_KEYS}

    async def fetch(self, unitid: int) -> FetchResult:
        school = self.registry.get(unitid)
        doc = school.latest_cds if school else None
        if doc is None:
            note = "No Common Data Set listed for this school"
            return FetchResult(SOURCE, Status.NOT_REPORTED, self._missing(Status.NOT_REPORTED, note), note)
        key = ("cds", doc.url)
        cached = self.cache.get(key)
        if cached is not None:
            return cached
        start = time.monotonic()
        status, content, note = await fetch_cds(self.http, doc.url, doc.format)
        if status is not Status.OK or content is None:
            return FetchResult(
                SOURCE,
                status,
                self._missing(status, note, doc.year),
                note,
                doc.year,
                time.monotonic() - start,
            )
        loop = asyncio.get_running_loop()
        try:
            sections, err = await loop.run_in_executor(
                self.executor, parse_document, content, doc.format, doc.year
            )
        except Exception as exc:  # e.g. a broken process pool
            log.warning("CDS parse executor failed: %s", type(exc).__name__)
            sections, err = parse_document(content, doc.format, doc.year)
        if err:
            out = FetchResult(
                SOURCE,
                Status.PARSE_FAILED,
                self._missing(Status.PARSE_FAILED, err, doc.year),
                err,
                doc.year,
                time.monotonic() - start,
            )
            self.cache.set(key, out)
            return out
        data: dict[str, FieldValue] = {}
        for sec in sections.values():
            data.update(sec.fields)
        for k in CDS_KEYS:
            data.setdefault(k, FieldValue.missing(SOURCE, Status.NOT_REPORTED, "", doc.year))
        statuses = [s.status for s in sections.values()]
        if all(s is Status.OK for s in statuses):
            overall = Status.OK
        elif any(s in (Status.OK, Status.PARTIAL) for s in statuses):
            overall = Status.PARTIAL
        else:
            overall = Status.PARSE_FAILED
        out = FetchResult(SOURCE, overall, data, "", doc.year, time.monotonic() - start)
        out.details = {code: s.status.value for code, s in sections.items()}
        self.cache.set(key, out)
        return out

    async def health_check(self) -> FetchResult:
        school = next((s for s in self.registry.schools if s.latest_cds), None)
        if school is None or school.latest_cds is None:
            return FetchResult(SOURCE, Status.NOT_REPORTED, note="Registry lists no CDS documents")
        res = await self.http.get(school.latest_cds.url, max_bytes=1)
        # A size-cap rejection means the server answered with a real file: reachable.
        ok = res.ok or res.status is Status.PARSE_FAILED
        return FetchResult(
            SOURCE,
            Status.OK if ok else res.status,
            note="Reachable" if ok else res.note,
            elapsed_s=res.elapsed_s,
        )
