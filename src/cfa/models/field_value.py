"""A single displayed value plus where it came from."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class Status(StrEnum):
    OK = "OK"
    PARTIAL = "PARTIAL"
    NOT_REPORTED = "NOT_REPORTED"
    SOURCE_UNAVAILABLE = "SOURCE_UNAVAILABLE"
    PARSE_FAILED = "PARSE_FAILED"
    RATE_LIMITED = "RATE_LIMITED"
    AUTH_MISSING = "AUTH_MISSING"


@dataclass(frozen=True)
class FieldValue:
    value: Any = None
    source: str = ""
    year: str | None = None
    status: Status = Status.NOT_REPORTED
    note: str = ""
    estimated: bool = False

    @property
    def ok(self) -> bool:
        return self.status is Status.OK and self.value is not None

    @classmethod
    def of(
        cls, value: Any, source: str, year: str | None, note: str = "", estimated: bool = False
    ) -> FieldValue:
        if value is None:
            return cls(None, source, year, Status.NOT_REPORTED, note)
        return cls(value, source, year, Status.OK, note, estimated)

    @classmethod
    def missing(
        cls, source: str = "", status: Status = Status.NOT_REPORTED, note: str = "", year: str | None = None
    ) -> FieldValue:
        return cls(None, source, year, status, note)

    def badge(self) -> str:
        if self.ok:
            return f"{self.source} {self.year}" if self.year else self.source
        return {
            Status.NOT_REPORTED: "Not reported",
            Status.SOURCE_UNAVAILABLE: "Source unavailable",
            Status.PARSE_FAILED: "Could not be read reliably",
            Status.RATE_LIMITED: "Rate limited",
            Status.AUTH_MISSING: "API key missing",
            Status.PARTIAL: "Partial",
        }.get(self.status, str(self.status))
