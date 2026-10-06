"""Download a CDS document into memory (never to disk), with a size cap and format checks."""

from __future__ import annotations

from cfa import config
from cfa.models.field_value import Status
from cfa.sources.http import HttpClient

PDF_TYPES = {
    "application/pdf",
    "application/x-pdf",
    "application/octet-stream",
    "binary/octet-stream",
    "application/force-download",
    "application/download",
}
XLSX_TYPES = {
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/octet-stream",
    "binary/octet-stream",
    "application/zip",
    "application/x-zip-compressed",
    "application/force-download",
    "application/download",
}


def check_format(content: bytes, content_type: str | None, fmt: str) -> tuple[bool, str]:
    ctype = (content_type or "").split(";")[0].strip().lower()
    if fmt == "pdf":
        if not content.lstrip()[:5].startswith(b"%PDF"):
            if b"<html" in content[:2048].lower() or ctype.startswith("text/"):
                return False, "The link now returns a web page instead of a PDF (it may have moved)"
            return False, "The file is not a PDF"
        if ctype and ctype not in PDF_TYPES:
            return False, f"Unexpected content type {ctype!r} for a PDF"
        return True, ""
    if not content.startswith(b"PK"):
        if b"<html" in content[:2048].lower() or ctype.startswith("text/"):
            return False, "The link now returns a web page instead of a spreadsheet (it may have moved)"
        return False, "The file is not an XLSX workbook"
    if ctype and ctype not in XLSX_TYPES:
        return False, f"Unexpected content type {ctype!r} for an XLSX"
    return True, ""


async def fetch_cds(
    http: HttpClient, url: str, fmt: str, max_bytes: int = config.CDS_MAX_BYTES
) -> tuple[Status, bytes | None, str]:
    res = await http.get(url, max_bytes=max_bytes)
    if not res.ok:
        status = res.status if res.status is not Status.AUTH_MISSING else Status.SOURCE_UNAVAILABLE
        return status, None, res.note
    content = res.content
    ok, note = check_format(content, res.response.headers.get("Content-Type") if res.response else None, fmt)
    if not ok:
        return Status.SOURCE_UNAVAILABLE, None, note
    return Status.OK, content, ""
