"""Adapter protocol and result type (PLAN §5.1 rule 1, §5.2)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from cfa.models.field_value import FieldValue, Status


@dataclass
class FetchResult:
    source: str
    status: Status
    data: dict[str, FieldValue] = field(default_factory=dict)
    note: str = ""
    year: str | None = None
    elapsed_s: float = 0.0
    details: dict[str, str] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.status in (Status.OK, Status.PARTIAL)

    def as_field(self) -> FieldValue:
        return FieldValue(None, self.source, self.year, self.status, self.note)


class SourceAdapter(Protocol):
    name: str

    async def fetch(self, unitid: int) -> FetchResult: ...

    async def health_check(self) -> FetchResult: ...


def worst(statuses: list[Status]) -> Status:
    """Collapse several sub-request statuses into one adapter status."""
    if not statuses:
        return Status.NOT_REPORTED
    if all(s is Status.OK for s in statuses):
        return Status.OK
    for s in (Status.AUTH_MISSING, Status.RATE_LIMITED, Status.SOURCE_UNAVAILABLE):
        if all(x is s for x in statuses):
            return s
    if any(s is Status.OK for s in statuses):
        return Status.PARTIAL
    for s in (Status.AUTH_MISSING, Status.RATE_LIMITED, Status.SOURCE_UNAVAILABLE, Status.PARSE_FAILED):
        if s in statuses:
            return s
    return Status.NOT_REPORTED
