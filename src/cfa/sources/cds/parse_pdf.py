"""CDS PDF -> layout Document using pdfplumber (text layer + filled form fields)."""

from __future__ import annotations

import io
import logging
import re
import threading
from typing import Any

from cfa.sources.cds.layout import EMPTY_BOX_CHARS, MARK_CHARS, Document, Row, Token

log = logging.getLogger(__name__)

LINE_TOLERANCE = 3.0  # points; words whose vertical centers are this close share a row
WORD_JOIN_GAP = 0.0  # tokens are kept as individual words; Row handles phrase matching
MAX_PAGES = 120


class PdfError(Exception):
    pass


def _decode(v: Any) -> str | None:
    if v is None:
        return None
    if isinstance(v, bytes):
        for enc in ("utf-16", "latin-1") if v.startswith(b"\xfe\xff") else ("utf-8", "latin-1"):
            try:
                return v.decode(enc)
            except UnicodeDecodeError:
                continue
        return None
    name = getattr(v, "name", None)  # pdfminer PSLiteral
    if isinstance(name, str | bytes):
        return name.decode("latin-1") if isinstance(name, bytes) else name
    return str(v)


def _annotation_words(page: Any) -> list[dict[str, Any]]:
    """Filled AcroForm values become positioned words; checked boxes become an 'X' mark."""
    out: list[dict[str, Any]] = []
    try:
        annots = page.annots or []
    except Exception:
        return out
    from pdfminer.pdftypes import resolve1

    for a in annots:
        data = a.get("data") or {}
        if _decode(data.get("Subtype")) not in (None, "Widget"):
            continue
        parent: dict[str, Any] = {}
        if data.get("Parent") is not None:
            try:
                resolved = resolve1(data["Parent"])
                parent = resolved if isinstance(resolved, dict) else {}
            except Exception:
                parent = {}
        ft = _decode(data.get("FT") or parent.get("FT"))
        value = _decode(data.get("V") if data.get("V") is not None else parent.get("V"))
        state = _decode(data.get("AS"))
        text: str | None = None
        if state is not None and state.strip("/") not in ("Off", ""):
            text = "X"
        elif ft in ("Tx", "Ch", None) and value and value.strip() and state is None:
            text = value.strip()
        if not text:
            continue
        for i, part in enumerate(text.split()):
            out.append(
                {
                    "text": part,
                    "x0": a["x0"] + i * 0.01,
                    "x1": a["x1"],
                    "top": a["top"],
                    "bottom": a["bottom"],
                }
            )
    return out


def _duplicates_text(a: dict[str, Any], words: list[dict[str, Any]]) -> bool:
    """A filled field whose value is also printed inside the field's box (flattened copies)."""
    for w in words:
        if w["text"] != a["text"]:
            continue
        xc = (w["x0"] + w["x1"]) / 2
        yc = (w["top"] + w["bottom"]) / 2
        if a["x0"] - 2 <= xc <= a["x1"] + 2 and a["top"] - 4 <= yc <= a["bottom"] + 4:
            return True
    return False


def _page_rows(page: Any, page_no: int) -> list[Row]:
    words = list(
        page.extract_words(keep_blank_chars=False, use_text_flow=False, x_tolerance=1.5, y_tolerance=2)
    )
    words += [a for a in _annotation_words(page) if not _duplicates_text(a, words)]
    cleaned: list[dict[str, Any]] = []
    for w in words:
        text = str(w["text"])
        # Split glued glyph marks (e.g. "record") off the end of words.
        if len(text) > 1 and text[-1] in MARK_CHARS - set("xX") and text[:-1].strip():
            width = (w["x1"] - w["x0"]) / len(text)
            cleaned.append({**w, "text": text[:-1], "x1": w["x1"] - width})
            cleaned.append({**w, "text": text[-1], "x0": w["x1"] - width})
            continue
        if all(ch in EMPTY_BOX_CHARS for ch in text):
            continue
        cleaned.append(w)
    cleaned.sort(key=lambda w: ((w["top"] + w["bottom"]) / 2, w["x0"]))
    rows: list[Row] = []
    current: list[dict[str, Any]] = []
    center = None
    for w in cleaned:
        c = (w["top"] + w["bottom"]) / 2
        if center is None or abs(c - center) <= LINE_TOLERANCE:
            current.append(w)
            center = c if center is None else (center * (len(current) - 1) + c) / len(current)
        else:
            rows.append(_row(current, page_no))
            current, center = [w], c
    if current:
        rows.append(_row(current, page_no))
    return rows


def _row(words: list[dict[str, Any]], page_no: int) -> Row:
    top = min(w["top"] for w in words)
    return Row([Token(str(w["text"]), float(w["x0"]), float(w["x1"])) for w in words], top, page_no)


# pdfium is not thread-safe (concurrent use crashes the process), and documents may be parsed on
# several threads when no process pool is available. Every pdfium call goes through this lock.
PDFIUM_LOCK = threading.Lock()

# A page's section is the letter of most numbered headings on it ("C1 Applications", "F1. Percent…").
_HEADING = re.compile(r"(?m)^\s*([A-J])\d{1,2}\s*[.:)]?\s+[A-Z]")
# The extractors read sections in parts B, C, E and F only (see sections.EXTRACTORS).
_FIRST, _LAST = "B", "F"


def needed_pages(content: bytes, n_pages: int) -> range:
    """Pages from the first part-B page to the last part-F page, found from the fast text layer.

    Laying out a page is the slow step (seconds per document); parts G-J (expenses, financial aid,
    faculty, degrees) are often half of a CDS and are never read. Falls back to every page when
    the parts can't be told apart.
    """
    try:
        import pypdfium2 as pdfium

        letters = []
        with PDFIUM_LOCK:
            pdf = pdfium.PdfDocument(content)
            try:
                for i in range(min(len(pdf), n_pages)):
                    page = pdf[i]
                    textpage = page.get_textpage()
                    text = textpage.get_text_range()
                    textpage.close()
                    page.close()
                    found = [m.group(1) for m in _HEADING.finditer(text)]
                    letters.append(max(set(found), key=found.count) if found else "")
            finally:
                pdf.close()
    except Exception as exc:  # the fast pass is an optimisation only
        log.info("CDS page pre-scan skipped: %s", type(exc).__name__)
        return range(n_pages)
    if "C" not in letters or "F" not in letters:
        return range(n_pages)
    first = letters.index(_FIRST) if _FIRST in letters else 0
    first = min(first, letters.index("C"))
    last = len(letters) - 1 - letters[::-1].index(_LAST)
    return range(first, min(n_pages, last + 2))  # +1 page: a section can run onto the next page


def parse_pdf(content: bytes) -> Document:
    import pdfplumber

    try:
        pdf = pdfplumber.open(io.BytesIO(content))
    except Exception as exc:
        raise PdfError(f"Not a readable PDF ({type(exc).__name__})") from exc
    rows: list[Row] = []
    try:
        pages = pdf.pages[:MAX_PAGES]
        keep = needed_pages(content, len(pages))
        for i, page in enumerate(pages):
            if i not in keep:
                continue
            try:
                rows.extend(_page_rows(page, i))
            except Exception as exc:  # one bad page must not sink the document
                log.warning("CDS PDF page %d unreadable: %s", i, type(exc).__name__)
            finally:
                page.close()
    finally:
        pdf.close()
    if sum(len(r.tokens) for r in rows) < 200:
        raise PdfError("PDF has no usable text layer (scanned image?)")
    return Document(rows, "pdf")
