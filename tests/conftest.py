from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("CFA_NO_PROCESS_POOL", "1")
os.environ.pop("CFA_SCORECARD_API_KEY", None)

from cfa.cache import CACHE
from cfa.models.college import CollegeRecord
from cfa.models.field_value import FieldValue, Status
from cfa.sources.http import HttpClient

FIXTURES = Path(__file__).parent / "fixtures"
API = FIXTURES / "api"
CDS = FIXTURES / "cds"


@pytest.fixture(autouse=True)
def _clear_cache():
    CACHE.clear()
    yield
    CACHE.clear()


def no_wait(_state) -> float:
    return 0.0


@pytest.fixture
async def http():
    async with HttpClient(wait=no_wait) as client:
        yield client


def make_record(unitid: int = 1, name: str = "Test U", **values) -> CollegeRecord:
    """A CollegeRecord with the given OK values; everything else NOT_REPORTED."""
    fields = {k: FieldValue.of(v, "Test", "2025") for k, v in values.items()}
    rec = CollegeRecord(unitid, name, fields)
    rec.source_status = {"Test": FieldValue(None, "Test", None, Status.OK)}
    return rec
