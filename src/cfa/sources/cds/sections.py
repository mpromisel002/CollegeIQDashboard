"""Common Data Set section extractors.

Each extractor is independent: one failed section never fails the others (PLAN §5.1 rule 6).
Every number passes a sanity check; values that fail are dropped as PARSE_FAILED instead of
being shown wrong.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from dataclasses import dataclass, field

from cfa.models.college import GPA_BINS, IMPORTANCE_LEVELS
from cfa.models.field_value import FieldValue, Status
from cfa.sources.cds.layout import Document, Row, Token

log = logging.getLogger(__name__)

SOURCE = "Common Data Set"
IC = re.IGNORECASE


@dataclass
class SectionResult:
    status: Status
    fields: dict[str, FieldValue] = field(default_factory=dict)
    note: str = ""


class SectionError(Exception):
    """Raised inside an extractor when a sanity check fails."""


# --------------------------------------------------------------------------- helpers


def _anchor_re(code: str) -> re.Pattern[str]:
    return re.compile(rf"^\s*{code}(?![\d-])(?:[\s:.]|$)", IC)


_TOC = re.compile(r"\.{6,}|…{3,}")


def window(
    doc: Document, code: str, next_codes: tuple[str, ...], default_len: int = 80, lead: int = 3
) -> tuple[int, int]:
    """Row range for a section: from its code anchor up to the next section's anchor.

    Table-of-contents lines are skipped, and the range starts a few rows above the anchor
    because PDFs often center the section code vertically against a wrapped question.
    """
    pat = _anchor_re(code)
    anchor = None
    for i, row in enumerate(doc.rows):
        if pat.search(row.text) and not _TOC.search(row.text):
            anchor = i
            break
    if anchor is None:
        return 0, 0
    end = min(len(doc.rows), anchor + default_len)
    for nxt in next_codes:
        npat = _anchor_re(nxt)
        for i in range(anchor + 1, end):
            if npat.search(doc.rows[i].text) and not _TOC.search(doc.rows[i].text):
                end = i
                break
    return max(0, anchor - lead), end


def is_fraction_doc(doc: Document) -> bool:
    return doc.fmt == "xlsx"


def as_percent(tok: Token, doc: Document, allow_fraction: bool = False) -> float | None:
    """A percent 0-100. Bare fractions (0.42) in XLSX are only accepted when allow_fraction is set."""
    v = tok.number
    if v is None or v < 0:
        return None
    if tok.is_percent:
        return v if v <= 100 else None
    if v <= 1.0 and allow_fraction:
        return round(v * 100, 4)
    return v if v <= 100 else None


def value_near(
    doc: Document, idx: int, m: re.Match[str], ok: Callable[[Token], float | None], lookahead: int = 3
) -> float | None:
    """Value after a label on the same row, else the right-most number on nearby rows."""
    row = doc.rows[idx]
    for t in row.numbers_after(m.end()):
        v = ok(t)
        if v is not None:
            return v
    for j in [*range(idx + 1, min(len(doc.rows), idx + 1 + lookahead)), idx - 1]:
        if j < 0:
            continue
        r = doc.rows[j]
        if r.page != row.page:
            continue
        if r.tokens and r.tokens[-1].number is not None:
            v = ok(r.tokens[-1])
            if v is not None:
                return v
    return None


def _numeric_row(row: Row) -> bool:
    """A row of values only (allowing a one-letter line label such as "H")."""
    words = [t for t in row.tokens if t.number is None and not t.is_mark]
    return (
        bool(row.tokens)
        and len(words) <= 1
        and all(len(t.text) <= 2 or re.fullmatch(r"[A-J]\d{1,2}\.?", t.text) for t in words)
        and any(t.number is not None for t in row.tokens)
    )


def nums_near(doc: Document, idx: int, m: re.Match[str], max_dy: float = 14.0) -> list[Token]:
    """Numbers after a label; if the label row has none, the adjacent values-only row.

    Handles PDFs where a wrapped label is vertically centered against its values. The
    adjacent row is rejected when it sits closer to some other text row than to this label.
    """
    row = doc.rows[idx]
    nums = row.numbers_after(m.end())
    if nums or doc.fmt != "pdf":
        return nums
    nxt = doc.rows[idx + 1] if idx + 1 < len(doc.rows) else None
    if (
        nxt is not None
        and nxt.page == row.page
        and nxt.tokens
        and abs(nxt.top - row.top) <= max_dy
        and (nxt.tokens[0].text[:1].islower() or nxt.tokens[0].text[:1] in "-(")
    ):
        # wrapped label: "... college-owned, -operated, or -" / "affiliated housing 96 35"
        cont = nxt.numbers_after(0)
        if cont and all(t.x0 > row.label_x1(m.end()) - 5 for t in cont):
            return cont
    best: tuple[float, list[Token]] | None = None
    for j, other in ((idx - 1, idx - 2), (idx + 1, idx + 2)):
        if not 0 <= j < len(doc.rows):
            continue
        r = doc.rows[j]
        dy = abs(r.top - row.top)
        if r.page != row.page or dy > max_dy or not _numeric_row(r):
            continue
        if 0 <= other < len(doc.rows):
            o = doc.rows[other]
            starts_label = bool(o.tokens) and o.tokens[0].text[:1].isupper()
            if o.page == r.page and starts_label and not _numeric_row(o) and abs(o.top - r.top) + 1.0 < dy:
                continue
        cand = [t for t in r.tokens if t.number is not None and t.x0 > row.label_x1(m.end()) - 5]
        if cand and (best is None or dy < best[0]):
            best = (dy, cand)
    return best[1] if best else []


def _ok(value: object, year: str | None, note: str = "") -> FieldValue:
    return FieldValue.of(value, SOURCE, year, note)


def _fail(year: str | None, note: str) -> FieldValue:
    return FieldValue.missing(SOURCE, Status.PARSE_FAILED, note, year)


def _nr(year: str | None, note: str = "") -> FieldValue:
    return FieldValue.missing(SOURCE, Status.NOT_REPORTED, note, year)


def _int(v: float | None) -> int | None:
    if v is None or v < 0 or abs(v - round(v)) > 1e-6:
        return None
    return round(v)


def nearest_column(x: float, columns: list[float], max_ratio: float = 0.6) -> int | None:
    if not columns:
        return None
    dists = [abs(x - c) for c in columns]
    best = min(range(len(columns)), key=lambda i: dists[i])
    if len(columns) > 1:
        spacing = min(abs(columns[i + 1] - columns[i]) for i in range(len(columns) - 1)) or 1.0
        if dists[best] > spacing * max_ratio + 2:
            return None
    return best


# --------------------------------------------------------------------------- C1


_C1_RE = re.compile(
    r"total\s+first[-\s]?time,?\s+first[-\s]?year\s+(?:\(?degree[-\s]seeking\)?\s+)?(?:students\s+)?(?:of\s+)?"
    r"(men|males|women|females|another\s+gender|unknown\s+(?:gender|sex)|non[-\s]?binary)\s+who\s+"
    r"(applied|were\s+admitted)",
    IC,
)
_C1_TOTAL_RE = re.compile(
    r"total\s+first[-\s]?time,?\s+first[-\s]?year\s+students\s+who\s+(applied|were\s+admitted)", IC
)
_GENDER = {"men": "men", "males": "men", "women": "women", "females": "women"}


def extract_c1(doc: Document, year: str | None) -> SectionResult:
    start, end = window(doc, "C1", ("C2", "C3"), 70)
    if end == 0:
        start, end = 0, len(doc.rows)
    found: dict[tuple[str, str], int] = {}
    for idx, m in doc.find_all(_C1_RE, start, end):
        g = m.group(1).lower()
        gender = _GENDER.get(g) or ("unknown" if g.startswith("unknown") else "another")
        kind = "applicants" if m.group(2).lower() == "applied" else "admits"
        if (kind, gender) in found:
            continue
        nums = nums_near(doc, idx, m)
        n = _int(nums[0].number) if nums and not nums[0].is_percent else None
        if n is not None:
            found[(kind, gender)] = n
    printed_total: dict[str, int] = {}
    for idx, m in doc.find_all(_C1_TOTAL_RE, start, end):
        kind = "applicants" if m.group(1).lower() == "applied" else "admits"
        nums = nums_near(doc, idx, m)
        n = _int(nums[0].number) if nums and not nums[0].is_percent else None
        if n is not None and kind not in printed_total:
            printed_total[kind] = n
    if ("applicants", "men") not in found and ("applicants", "women") not in found:
        return SectionResult(Status.NOT_REPORTED, {}, "C1 applicant counts not found")
    # A single-gender college leaves the other row blank.
    single = ("applicants", "men") not in found or ("applicants", "women") not in found
    out: dict[str, FieldValue] = {}
    for kind in ("applicants", "admits"):
        parts = [found.get((kind, g)) for g in ("men", "women", "another", "unknown")]
        if (parts[0] is None or parts[1] is None) and not (single and (parts[0] or parts[1])):
            out[f"{kind}_total"] = _nr(year, "Men/women counts missing")
        else:
            total = sum(p for p in parts if p is not None)
            printed = printed_total.get(kind)
            if printed is not None and printed >= total and (printed - total) <= max(50, total * 0.02):
                total = printed  # the school's own total also counts students of unknown sex
            out[f"{kind}_total"] = _ok(total if total > 0 else None, year)
        for g in ("men", "women", "another"):
            v = found.get((kind, g))
            out[f"{kind}_{g}"] = _ok(v, year) if v is not None else _nr(year)
    for g in ("total", "men", "women", "another"):
        a, d = out[f"applicants_{g}"].value, out[f"admits_{g}"].value
        if a is not None and d is not None and d > a:
            out[f"applicants_{g}"] = _fail(year, "Admits exceed applicants")
            out[f"admits_{g}"] = _fail(year, "Admits exceed applicants")
    am, aw = found.get(("applicants", "men")), found.get(("applicants", "women"))
    dm, dw = found.get(("admits", "men")), found.get(("admits", "women"))
    if am and aw and dm and dw:
        rm, rw = dm / am, dw / aw
        if max(rm, rw) / min(rm, rw) > 3:  # a typo in one count (seen in real filings)
            note = "Men/women admit rates are inconsistent; counts look mistyped"
            return SectionResult(Status.PARSE_FAILED, {k: _fail(year, note) for k in out}, note)
    if not out["admits_total"].ok:
        return SectionResult(Status.PARTIAL, out, "C1 admit counts not found or invalid")
    return SectionResult(Status.OK, out)


# --------------------------------------------------------------------------- C7

FACTOR_PATTERNS: dict[str, str] = {
    "Rigor of secondary school record": r"rigor\s+of\s+secondary\s+school\s+record",
    "Class rank": r"class\s+rank",
    "Academic GPA": r"academic\s+gpa",
    "Standardized test scores": r"standardized\s+test\s+scores",
    "Application essay": r"application\s+essay",
    "Recommendation(s)": r"recommendation",
    "Interview": r"\binterview\b",
    "Extracurricular activities": r"extracurricular\s+activities",
    "Talent/ability": r"talent\s*/\s*ability",
    "Character/personal qualities": r"character\s*/\s*personal\s+qualities",
    "First generation": r"first\s+generation",
    "Alumni/ae relation": r"alumni\s*/?\s*(ae)?\s+relation",
    "Geographical residence": r"geographical\s+residence",
    "State residency": r"state\s+residency",
    "Religious affiliation/commitment": r"religious\s+affiliation",
    "Volunteer work": r"volunteer\s+work",
    "Work experience": r"work\s+experience",
    "Level of applicant's interest": r"level\s+of\s+applicant.{0,2}s?\s+interest",
}


def _c7_columns(doc: Document, start: int, end: int, first_factor: int) -> list[float] | None:
    """x of the Very Important / Important / Considered / Not Considered columns.

    The header may sit on one row or be wrapped over up to four rows.
    """
    want = ["important", "important", "considered", "considered"]
    for i in range(start, min(end, start + 14)):
        toks = [t for t in doc.rows[i].tokens if t.text.strip(".:").lower() in ("important", "considered")]
        if [t.text.strip(".:").lower() for t in toks] == want:
            return [t.xc for t in toks]
    lo = max(start, first_factor - 5)
    toks = [
        t
        for r in doc.rows[lo:first_factor]
        for t in r.tokens
        if t.text.strip(".:").lower() in ("important", "considered")
    ]
    toks.sort(key=lambda t: t.x0)
    if [t.text.strip(".:").lower() for t in toks] == want:
        return [t.xc for t in toks]
    return None


def extract_c7(doc: Document, year: str | None) -> SectionResult:
    start, end = window(doc, "C7", ("C8", "C8A"), 60)
    if end == 0:
        return SectionResult(Status.NOT_REPORTED, {"admission_factors": _nr(year)}, "C7 not found")
    rigor = doc.find(re.compile(FACTOR_PATTERNS["Rigor of secondary school record"], IC), start, end)
    cols = _c7_columns(doc, start, end, rigor[0] if rigor else start)
    if cols is None:
        return SectionResult(Status.PARSE_FAILED, {"admission_factors": _fail(year, "C7 header not found")})
    factors: dict[str, str] = {}
    for name, pat in FACTOR_PATTERNS.items():
        hit = doc.find(re.compile(pat, IC), start, end)
        if hit is None:
            continue
        idx, m = hit
        marks = doc.rows[idx].marks_after(m.end())
        levels = {nearest_column(t.xc, cols) for t in marks} - {None}
        if len(levels) == 1:
            factors[name] = IMPORTANCE_LEVELS[levels.pop()]  # type: ignore[index]
    if not factors:
        return SectionResult(Status.NOT_REPORTED, {"admission_factors": _nr(year, "No C7 marks found")})
    status = Status.OK if len(factors) >= 10 else Status.PARTIAL
    return SectionResult(status, {"admission_factors": _ok(factors, year)})


# --------------------------------------------------------------------------- C8

POLICY_CLASSES = (
    ("Not used (test-blind)", (r"not\s+used", r"not\s+considered", r"even\s+if")),
    (
        "Considered if submitted (test-optional)",
        (
            r"if\s+submitted",
            r"consider(ed)?\s+if",
        ),
    ),
    ("Required for some applicants", (r"\bsome\b",)),
    ("Recommended", (r"recommend",)),
    ("Required", (r"require",)),
)


def _is_sentence(row: Row, fmt: str) -> bool:
    """A line of running text (instructions), as opposed to a fragment of a table header."""
    if fmt == "xlsx":
        cells: dict[int, int] = {}
        for t in row.tokens:
            cells[round(t.x0)] = cells.get(round(t.x0), 0) + 1
        return max(cells.values(), default=0) >= 12
    if len(row.tokens) < 6:
        return False
    gaps = [b.x0 - a.x1 for a, b in zip(row.tokens, row.tokens[1:], strict=False)]
    return max(gaps) < 15


def _phrases(row: Row) -> list[tuple[float, float, str]]:
    """Split a row into phrases at gaps wider than a word space: (x0, x1, text)."""
    out: list[list[Token]] = []
    for t in row.tokens:
        if t.is_mark:
            continue
        if out and t.x0 - out[-1][-1].x1 <= 4.5:
            out[-1].append(t)
        else:
            out.append([t])
    return [(p[0].x0, p[-1].x1, " ".join(t.text for t in p)) for p in out]


def _heading_above(doc: Document, rows: list[int], mark: Token) -> str:
    """The column heading stacked above a mark (headings and marks are centered in their cells)."""
    if doc.fmt == "xlsx":
        return " ".join(
            t.text for k in rows for t in doc.rows[k].tokens if abs(t.x0 - mark.x0) < 1 and not t.is_mark
        ).lower()
    words = []
    for k in rows:
        for x0, x1, text in _phrases(doc.rows[k]):
            centered = abs((x0 + x1) / 2 - mark.xc) <= 18
            left_aligned = x0 - 4 <= mark.xc <= x1 + 4 and (x1 - x0) < 60
            if centered or left_aligned:
                words.append(text)
    return " ".join(words).lower()


def _classify_policy(phrase: str) -> str | None:
    for label, pats in POLICY_CLASSES:
        if any(re.search(p, phrase) for p in pats):
            return label
    return None


def extract_c8(doc: Document, year: str | None) -> SectionResult:
    start, end = window(doc, "C8", ("C9",), 60)
    if end == 0:
        return SectionResult(Status.NOT_REPORTED, {"test_policy": _nr(year)}, "C8 not found")
    hit = doc.find(re.compile(r"^\s*SAT\s+(or|and)\s+ACT\b(?!\s+(scores|policies))", IC), start, end)
    if hit is None:
        return SectionResult(Status.NOT_REPORTED, {"test_policy": _nr(year, "C8 policy grid not found")})
    idx, m = hit
    marks = doc.rows[idx].marks_after(m.end())
    if not marks:
        return SectionResult(Status.NOT_REPORTED, {"test_policy": _nr(year, "No C8 mark")})
    header_rows: list[int] = []
    for k in range(idx - 1, max(start, idx - 8) - 1, -1):
        if _is_sentence(doc.rows[k], doc.fmt) or doc.rows[k].page != doc.rows[idx].page:
            break
        header_rows.insert(0, k)
    labels = {_classify_policy(_heading_above(doc, header_rows, t)) for t in marks} - {None}
    if len(labels) != 1:
        return SectionResult(Status.NOT_REPORTED, {"test_policy": _nr(year, "C8 mark not readable")})
    return SectionResult(Status.OK, {"test_policy": _ok(labels.pop(), year)})


# --------------------------------------------------------------------------- C9


def _percentiles(lo: int, hi: int) -> Callable[[list[Token]], tuple[int, int] | None]:
    def pick(nums: list[Token]) -> tuple[int, int] | None:
        ints = [_int(t.number) for t in nums if not t.is_percent]
        vals = [v for v in ints if v is not None and lo <= v <= hi]
        if len(vals) < 2:
            return None
        p25, p75 = (vals[0], vals[2]) if len(vals) >= 3 else (vals[0], vals[1])
        if p25 > p75:
            return None
        return p25, p75

    return pick


def extract_c9(doc: Document, year: str | None) -> SectionResult:
    start, end = window(doc, "C9", ("C10",), 120)
    if end == 0:
        return SectionResult(Status.NOT_REPORTED, {}, "C9 not found")
    out: dict[str, FieldValue] = {}
    specs = (
        ("sat_ebrw", r"^\s*SAT\s+(Evidence[-\s]*Based|EBRW|ERW|Critical\s+Reading)", 200, 800),
        ("sat_math", r"^\s*SAT\s+Math\b", 200, 800),
        ("act", r"^\s*ACT\s+Composite\b", 1, 36),
    )
    for key, pat, lo, hi in specs:
        pick = _percentiles(lo, hi)
        val = None
        for idx, m in doc.find_all(re.compile(pat, IC), start, end):
            val = pick(nums_near(doc, idx, m))
            if val is not None:
                break
        if val is None:
            out[f"{key}_25"] = _nr(year)
            out[f"{key}_75"] = _nr(year)
        else:
            out[f"{key}_25"], out[f"{key}_75"] = _ok(val[0], year), _ok(val[1], year)
    for key, pat in (
        ("sat_submit_pct", r"submitting\s+SAT\s+scores"),
        ("act_submit_pct", r"submitting\s+ACT\s+scores"),
    ):
        hit = doc.find(re.compile(pat, IC), start, end)
        pct: float | None = None
        if hit:
            nums = nums_near(doc, hit[0], hit[1])
            if nums:
                pct = as_percent(
                    nums[0], doc, allow_fraction=is_fraction_doc(doc) and (nums[0].number or 0) <= 1
                )
        out[key] = _ok(round(pct, 1), year) if pct is not None else _nr(year)
    status = (
        Status.OK
        if all(fv.ok for fv in out.values())
        else (Status.PARTIAL if any(fv.ok for fv in out.values()) else Status.NOT_REPORTED)
    )
    return SectionResult(status, out)


# --------------------------------------------------------------------------- C11 / C12

C11_PATTERNS: dict[str, str] = {
    "4.0": r"GPA\s+of\s+4\.0",
    "3.75-3.99": r"between\s+3\.75\s+and\s+3\.99",
    "3.50-3.74": r"between\s+3\.50?\s+and\s+3\.74",
    "3.25-3.49": r"between\s+3\.25\s+and\s+3\.49",
    "3.00-3.24": r"between\s+3\.00?\s+and\s+3\.24",
    "2.50-2.99": r"between\s+2\.50?\s+and\s+2\.99",
    "2.00-2.49": r"between\s+2\.00?\s+and\s+2\.49",
    "1.00-1.99": r"between\s+1\.00?\s+and\s+1\.99",
    "<1.00": r"below\s+1\.0",
}


def _c11_all_column_x(doc: Document, start: int, first_bin: int) -> tuple[float, list[float]] | None:
    """For the 3-column template, the x of the 'All enrolled students' header and all header columns.

    The header is often wrapped over several rows, so tokens are collected across them.
    """
    rows = [i for i in range(max(start, first_bin - 8), first_bin) if not _is_sentence(doc.rows[i], doc.fmt)]
    toks = [t for i in rows for t in doc.rows[i].tokens]
    all_tok = next((t for t in reversed(toks) if t.text.strip("(") == "All"), None)
    if all_tok is None:
        return None
    if doc.fmt == "xlsx":
        cols = sorted({round(t.x0, 0) for t in toks if t.text.strip("(").lower() == "percent"})
        return all_tok.x0, [float(c) for c in cols] or [all_tok.x0]
    not_tok = next((t for t in reversed(toks) if t.text.lower() in ("not", "not)")), None)
    if not_tok is None:
        return None
    return all_tok.xc, [not_tok.xc, all_tok.xc]


def extract_c11(doc: Document, year: str | None) -> SectionResult:
    start, end = window(doc, "C11", ("C12", "C13"), 60)
    if end == 0:
        return SectionResult(Status.NOT_REPORTED, {"gpa_dist": _nr(year)}, "C11 not found")
    rows: dict[str, list[Token]] = {}
    first_bin = end
    for b, pat in C11_PATTERNS.items():
        hit = doc.find(re.compile(pat, IC), start, end)
        if hit is None:
            continue
        first_bin = min(first_bin, hit[0])
        rows[b] = doc.rows[hit[0]].numbers_after(hit[1].end())
    if not rows or all(not v for v in rows.values()):
        return SectionResult(Status.NOT_REPORTED, {"gpa_dist": _nr(year, "C11 left blank")})
    max_n = max(len(v) for v in rows.values())
    header = _c11_all_column_x(doc, start, first_bin)
    picked: dict[str, Token | None] = {}
    if max_n >= 3:
        # 3-column template: use the column x of rows that have all three numbers.
        col_x = [t.xc for t in next(v for v in rows.values() if len(v) >= 3)[-3:]]
        for b, toks in rows.items():
            cand = [t for t in toks if nearest_column(t.xc, col_x) == 2]
            picked[b] = cand[-1] if cand else None
    elif header is not None:
        all_x, cols = header
        for b, toks in rows.items():
            if doc.fmt == "xlsx":
                cand = [t for t in toks if abs(t.x0 - all_x) < 1]
            else:
                cand = [
                    t for t in toks if abs(t.xc - all_x) <= min((abs(t.xc - c) for c in cols), default=1e9)
                ]
            picked[b] = cand[-1] if cand else None
    elif max_n == 1:
        picked = {b: (v[0] if v else None) for b, v in rows.items()}
    else:
        return SectionResult(Status.PARSE_FAILED, {"gpa_dist": _fail(year, "Ambiguous C11 columns")})
    raw = {b: (t.number if t is not None else None) for b, t in picked.items()}
    values = [v for v in raw.values() if v is not None]
    if not values or sum(values) == 0:
        return SectionResult(Status.NOT_REPORTED, {"gpa_dist": _nr(year, "C11 left blank")})
    any_pct_sign = any(t is not None and t.is_percent for t in picked.values())
    if not any_pct_sign and all(v <= 1.0 for v in values) and 0.95 <= sum(values) <= 1.05:
        raw = {b: (v * 100 if v is not None else None) for b, v in raw.items()}
    dist = {b: round(raw.get(b) or 0.0, 2) for b in GPA_BINS}
    total = sum(dist.values())
    if not 95 <= total <= 105 or any(not 0 <= v <= 100 for v in dist.values()):
        return SectionResult(Status.PARSE_FAILED, {"gpa_dist": _fail(year, f"GPA bins sum to {total:.1f}%")})
    return SectionResult(Status.OK, {"gpa_dist": _ok(dist, year)})


_C12_RE = re.compile(r"average\s+high\s+school\s+GPA\s+of\s+all", IC)


def extract_c12(doc: Document, year: str | None) -> SectionResult:
    start, end = window(doc, "C12", ("C13",), 15)
    hit = doc.find(_C12_RE, start, end) if end else doc.find(_C12_RE)
    if hit is None:
        return SectionResult(Status.NOT_REPORTED, {"gpa_avg": _nr(year)}, "C12 not found")

    def ok(t: Token) -> float | None:
        v = t.number
        return v if v is not None and not t.is_percent and 1.0 <= v <= 5.0 else None

    v = value_near(doc, hit[0], hit[1], ok, lookahead=2)
    if v is None:
        return SectionResult(Status.NOT_REPORTED, {"gpa_avg": _nr(year)})
    return SectionResult(Status.OK, {"gpa_avg": _ok(round(v, 2), year)})


# --------------------------------------------------------------------------- C21 / C22


def _mark_answer(doc: Document, j: int, mark: Token) -> bool | None:
    """Which Yes/No label a check mark belongs to.

    Two layouts exist: the mark sits under a "Yes  No" header (column style), or a radio box
    sits immediately left of its own "Yes"/"No" label (template style).
    """
    labels: list[tuple[int, Token]] = []
    for k in range(max(0, j - 6), min(len(doc.rows), j + 3)):
        if doc.rows[k].page != doc.rows[j].page:
            continue
        for t in doc.rows[k].tokens:
            if t.text.strip(" .:").lower() in ("yes", "no"):
                labels.append((k, t))
    above = sorted((x for x in labels if x[0] <= j), key=lambda kt: j - kt[0])
    for _k, t in above:  # column style: mark centered under the nearest header label
        if t.x0 - 4 <= mark.xc <= t.x1 + 4:
            return t.text.strip(" .:").lower() == "yes"
    right = [(t.x0 - mark.x1, t) for k, t in labels if abs(k - j) <= 1 and 0 <= t.x0 - mark.x1 <= 20]
    if right:
        return min(right, key=lambda p: p[0])[1].text.strip(" .:").lower() == "yes"
    return None


def _yes_no(doc: Document, start: int, end: int, question: re.Pattern[str]) -> bool | None:
    hit = doc.find(question, start, end)
    if hit is None:
        return None
    q_idx = hit[0]
    # XLSX: a Yes/No answer cell on the question row or just below it.
    if doc.fmt == "xlsx":
        for j in range(q_idx, min(end, q_idx + 3)):
            r = doc.rows[j]
            after = r.tokens[r.token_index_at(hit[1].end()) :] if j == q_idx else r.tokens
            for t in after:
                w = t.text.strip().lower()
                if w in ("yes", "no"):
                    return w == "yes"
                if t.is_mark:
                    return None
        return None
    for j in range(max(start, q_idx - 2), min(end, q_idx + 7)):
        r = doc.rows[j]
        if j > q_idx and re.search(r"^\s*if\s+.?yes", r.text, IC):
            break
        for t in r.tokens:
            if t.is_mark:
                ans = _mark_answer(doc, j, t)
                if ans is not None:
                    return ans
    # Some schools type the answer ("Yes") under the Yes/No header instead of checking a box.
    header = None
    for j in range(max(start, q_idx - 3), min(end, q_idx + 2)):
        words = [t.text.strip(" .:").lower() for t in doc.rows[j].tokens]
        if "yes" in words and "no" in words:
            header = j
            break
    if header is not None:
        hx = min(t.x0 for t in doc.rows[header].tokens if t.text.strip(" .:").lower() in ("yes", "no"))
        for j in range(header + 1, min(end, q_idx + 7)):
            r = doc.rows[j]
            if j > q_idx and re.search(r"^\s*if\s+.?yes", r.text, IC):
                break
            answers = [
                t for t in r.tokens if t.text.strip(" .:").lower() in ("yes", "no") and t.x0 >= hx - 15
            ]
            if len(answers) == 1:
                return answers[0].text.strip(" .:").lower() == "yes"
    return None


def _count(doc: Document, start: int, end: int, pat: str) -> int | None:
    hit = doc.find(re.compile(pat, IC), start, end)
    if hit is None:
        return None
    nums = nums_near(doc, hit[0], hit[1])
    return _int(nums[0].number) if nums and not nums[0].is_percent else None


def _plan(
    doc: Document,
    year: str | None,
    code: str,
    nxt: tuple[str, ...],
    prefix: str,
    question: str,
    apps_pat: str,
    admits_pat: str,
) -> SectionResult:
    start, end = window(doc, code, nxt, 45)
    if end == 0:
        return SectionResult(Status.NOT_REPORTED, {f"{prefix}_offered": _nr(year)}, f"{code} not found")
    offered = _yes_no(doc, start, end, re.compile(question, IC))
    apps = _count(doc, start, end, apps_pat)
    admits = _count(doc, start, end, admits_pat)
    out: dict[str, FieldValue] = {}
    if apps is not None and admits is not None and admits > apps:
        out[f"{prefix}_applicants"] = _fail(year, "Admits exceed applicants")
        out[f"{prefix}_admits"] = _fail(year, "Admits exceed applicants")
        apps = admits = None
    else:
        out[f"{prefix}_applicants"] = _ok(apps, year) if apps else _nr(year)
        out[f"{prefix}_admits"] = _ok(admits, year) if apps else _nr(year)
    if apps and admits is not None:
        offered = True if offered is None else offered
        out[f"{prefix}_rate"] = _ok(round(100 * admits / apps, 1), year)
    else:
        out[f"{prefix}_rate"] = _nr(year)
    out[f"{prefix}_offered"] = _ok(offered, year) if offered is not None else _nr(year)
    status = Status.OK if offered is not None else Status.NOT_REPORTED
    return SectionResult(status, out)


def extract_c21(doc: Document, year: str | None) -> SectionResult:
    return _plan(
        doc,
        year,
        "C21",
        ("C22",),
        "ed",
        r"offer\s+an\s+early\s+decision\s+plan",
        r"number\s+of\s+early\s+decision\s+applications\s+received",
        r"number\s+of\s+applicants\s+admitted\s+under\s+early\s+decision",
    )


def extract_c22(doc: Document, year: str | None) -> SectionResult:
    return _plan(
        doc,
        year,
        "C22",
        ("D1", "D2", "D\\.", "C23"),
        "ea",
        r"nonbinding\s+early\s+action\s+plan",
        r"number\s+of\s+early\s+action\s+applications\s+received",
        r"number\s+of\s+applicants\s+admitted\s+under\s+early\s+action",
    )


# --------------------------------------------------------------------------- E1

_ABROAD = re.compile(r"study\s+abroad", IC)


def _mark_adjacent(row: Row, m: re.Match[str]) -> bool:
    i = row.token_index_at(m.start())
    j = row.token_index_at(m.end())
    if i > 0 and row.tokens[i - 1].is_mark:
        gap = row.tokens[i].x0 - row.tokens[i - 1].x1
        if gap < 40:
            return True
    for t in row.tokens[j:]:
        if t.is_mark:
            return True
        if any(ch.isalpha() for ch in t.text):
            return False
    return False


def extract_e1(doc: Document, year: str | None) -> SectionResult:
    start, end = window(doc, "E1", ("E2", "E3", "E4"), 45)
    if end == 0:
        return SectionResult(Status.NOT_REPORTED, {"study_abroad": _nr(year)}, "E1 not found")
    adjacent = 0
    abroad: bool | None = None
    for i in range(start, end):
        row = doc.rows[i]
        # count label rows that carry an adjacent mark, to know whether this layout is readable
        if any(t.is_mark for t in row.tokens) and any(
            ch.isalpha() for ch in row.text.replace("X", "").replace("x", "")
        ):
            adjacent += 1
        m = _ABROAD.search(row.text)
        if m and abroad is None:
            abroad = _mark_adjacent(row, m)
    if abroad is None or adjacent == 0:
        return SectionResult(Status.NOT_REPORTED, {"study_abroad": _nr(year, "E1 marks not readable")})
    return SectionResult(Status.OK, {"study_abroad": _ok(abroad, year)})


# --------------------------------------------------------------------------- F1


def _f1_ug_x(doc: Document, start: int, first_row: int) -> float | None:
    """x of the 'Undergraduates' column header closest above the first F1 data row."""
    for i in range(first_row - 1, start - 1, -1):
        row = doc.rows[i]
        if len(row.tokens) > 8:  # a sentence (the F1 question), not a header
            continue
        for t in row.tokens:
            if t.text.strip().lower().startswith("undergraduate"):
                return t.xc if doc.fmt == "pdf" else t.x0
    return None


F1_ROWS = {
    "greek_men_pct": r"percent\s+of\s+(men|males)\s+who\s+join\s+fraternities",
    "greek_women_pct": r"percent\s+of\s+(women|females)\s+who\s+join\s+sororities",
    "housing_pct": r"percent\s+who\s+live\s+in\s+college[-\s]owned",
}


def extract_f1(doc: Document, year: str | None) -> SectionResult:
    start, end = window(doc, "F1", ("F2",), 40)
    if end == 0:
        start, end = 0, len(doc.rows)
    hits = {k: doc.find(re.compile(p, IC), start, end) for k, p in F1_ROWS.items()}
    if not any(hits.values()):
        return SectionResult(Status.NOT_REPORTED, {k: _nr(year) for k in F1_ROWS}, "F1 not found")
    first = min((h[0] for h in hits.values() if h), default=end)
    ug_x = _f1_ug_x(doc, start, first)
    # Fractions (0.26) are only trusted in XLSX when the in-state/out-of-state rows confirm the scale.
    frac = False
    if doc.fmt == "xlsx":
        st = doc.find(re.compile(r"percent\s+who\s+are\s+from\s+in[-\s]state", IC), start, end)
        ost = doc.find(re.compile(r"percent\s+who\s+are\s+from\s+out[-\s]of[-\s]state", IC), start, end)
        if st and ost:
            a = doc.rows[st[0]].numbers_after(st[1].end())
            b = doc.rows[ost[0]].numbers_after(ost[1].end())
            if a and b and not a[0].is_percent and (a[0].number or 0) + (b[0].number or 0) <= 1.01:
                frac = True
    out: dict[str, FieldValue] = {}
    for key, hit in hits.items():
        if hit is None:
            out[key] = _nr(year)
            continue
        row = doc.rows[hit[0]]
        less_than_one = [
            t
            for t in row.tokens[row.token_index_at(hit[1].end()) :]
            if re.fullmatch(r"<\s*1(\.0+)?%?", t.text.strip())
        ]
        if less_than_one:
            out[key] = _ok(0.5, year, "Reported as less than 1%")
            continue
        nums = nums_near(doc, hit[0], hit[1])
        tok: Token | None = None
        if nums and ug_x is not None:
            x = (lambda t: t.xc) if doc.fmt == "pdf" else (lambda t: t.x0)
            near = min(nums, key=lambda t: abs(x(t) - ug_x))
            spread = max(abs(x(a) - x(b)) for a in nums for b in nums) if len(nums) > 1 else 0
            tol = max(spread * 0.4, 25.0 if doc.fmt == "pdf" else 1.0)
            if abs(x(near) - ug_x) <= tol:
                tok = near
        if tok is None and len(nums) == 2:
            tok = nums[1]  # template order: first-year, then undergraduates
        if tok is None:
            if nums:
                out[key] = _nr(year, "Undergraduate value not reported")
                continue
            rest = row.text[hit[1].end() :].strip().lower()
            if re.match(r"^(n/?a|none|not applicable|-+)\b", rest) and key != "housing_pct":
                out[key] = _ok(0.0, year, "Reported as N/A")
            else:
                out[key] = _nr(year)
            continue
        if (
            tok.number is not None
            and not tok.is_percent
            and tok.number <= 1.0
            and doc.fmt == "xlsx"
            and not frac
        ):
            out[key] = _fail(year, "Ambiguous percent scale")
            continue
        val = as_percent(tok, doc, allow_fraction=frac)
        out[key] = _ok(round(val, 1), year) if val is not None else _fail(year, "Out of range")
    status = (
        Status.OK
        if all(fv.ok for fv in out.values())
        else (Status.PARTIAL if any(fv.ok for fv in out.values()) else Status.NOT_REPORTED)
    )
    return SectionResult(status, out)


# --------------------------------------------------------------------------- B22 / B11


def extract_b22(doc: Document, year: str | None) -> SectionResult:
    start, end = window(doc, "B22", ("C1",), 45, lead=0)
    if end == 0:
        return SectionResult(Status.NOT_REPORTED, {"retention_rate": _nr(year)}, "B22 not found")
    for j in range(start, end):
        r = doc.rows[j]
        if not r.tokens:
            continue
        t = r.tokens[-1]
        v = t.number
        if v is None or not 0 < v <= 100:
            continue
        if t.is_percent:
            return SectionResult(Status.OK, {"retention_rate": _ok(round(v, 1), year)})
        if doc.fmt == "pdf" and "." in t.text and len(r.tokens) > 1:
            pct = v * 100 if v <= 1 else v
            return SectionResult(Status.OK, {"retention_rate": _ok(round(pct, 1), year)})
    return SectionResult(Status.NOT_REPORTED, {"retention_rate": _nr(year)})


def extract_b11(doc: Document, year: str | None) -> SectionResult:
    hit = doc.find(re.compile(r"six[-\s]year\s+graduation\s+rate\s+for\s+\d{4}\s+cohort", IC))
    if hit is None:
        return SectionResult(Status.NOT_REPORTED, {"grad_rate_6yr": _nr(year)}, "B11 not found")
    nums = nums_near(doc, hit[0], hit[1])
    if not nums:
        return SectionResult(Status.NOT_REPORTED, {"grad_rate_6yr": _nr(year)})
    t = nums[-1]
    v = t.number
    if v is None:
        return SectionResult(Status.NOT_REPORTED, {"grad_rate_6yr": _nr(year)})
    if not t.is_percent and v <= 1.0:
        v *= 100
    if not 0 < v <= 100:
        return SectionResult(Status.PARSE_FAILED, {"grad_rate_6yr": _fail(year, "Out of range")})
    return SectionResult(Status.OK, {"grad_rate_6yr": _ok(round(v, 1), year)})


EXTRACTORS: dict[str, Callable[[Document, str | None], SectionResult]] = {
    "C1": extract_c1,
    "C7": extract_c7,
    "C8": extract_c8,
    "C9": extract_c9,
    "C11": extract_c11,
    "C12": extract_c12,
    "C21": extract_c21,
    "C22": extract_c22,
    "E1": extract_e1,
    "F1": extract_f1,
    "B22": extract_b22,
    "B11": extract_b11,
}


def extract_all(doc: Document, year: str | None) -> dict[str, SectionResult]:
    out: dict[str, SectionResult] = {}
    for code, fn in EXTRACTORS.items():
        try:
            out[code] = fn(doc, year)
        except Exception as exc:  # independent sections: never let one sink the rest
            log.warning("CDS section %s failed: %s", code, type(exc).__name__)
            out[code] = SectionResult(Status.PARSE_FAILED, {}, f"{code} could not be read")
    return out
