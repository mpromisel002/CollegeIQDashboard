"""Format-neutral layout model shared by the PDF and XLSX parsers.

Both parsers turn a CDS document into visual rows of positioned tokens. Section extractors
(sections.py) then find rows by their label text, never by fixed coordinates, because
schools modify the template.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# Glyphs that schools use for a checked box. Wingdings/Symbol private-use checks included.
MARK_CHARS = set("xX✓✔✗✘☑☒■●◼")
# Glyphs for an empty box; dropped.
EMPTY_BOX_CHARS = set("☐□○◻")

_NUM_RE = re.compile(r"^\(?[-–]?\$?(\d{1,3}(,\d{3})+|\d+)?(\.\d+)?%?\)?[*]?$")


@dataclass
class Token:
    text: str
    x0: float
    x1: float

    @property
    def is_mark(self) -> bool:
        t = self.text.strip()
        return bool(t) and len(t) <= 2 and all(ch in MARK_CHARS for ch in t)

    @property
    def number(self) -> float | None:
        return parse_number(self.text)

    @property
    def is_percent(self) -> bool:
        return self.text.strip().rstrip("*").endswith("%")

    @property
    def xc(self) -> float:
        return (self.x0 + self.x1) / 2


@dataclass
class Row:
    tokens: list[Token]
    top: float
    page: int
    _text: str = field(default="", repr=False)
    _starts: list[int] = field(default_factory=list, repr=False)

    def __post_init__(self) -> None:
        self.tokens.sort(key=lambda t: t.x0)
        parts: list[str] = []
        pos = 0
        for t in self.tokens:
            self._starts.append(pos)
            parts.append(t.text)
            pos += len(t.text) + 1
        self._text = " ".join(parts)

    @property
    def text(self) -> str:
        return self._text

    def token_index_at(self, char_pos: int) -> int:
        """Index of the first token that starts at or after char_pos."""
        for i, s in enumerate(self._starts):
            if s >= char_pos:
                return i
        return len(self.tokens)

    def search(self, pattern: re.Pattern[str]) -> re.Match[str] | None:
        return pattern.search(self._text)

    def numbers_after(self, char_pos: int) -> list[Token]:
        """Numeric tokens after a label match (stops at the next non-numeric text token)."""
        out: list[Token] = []
        for t in self.tokens[self.token_index_at(char_pos) :]:
            if t.is_mark:
                continue
            if t.number is not None:
                out.append(t)
            elif out and _is_word(t.text):
                break
        return out

    def marks_after(self, char_pos: int) -> list[Token]:
        return [t for t in self.tokens[self.token_index_at(char_pos) :] if t.is_mark]

    def label_x1(self, char_pos: int) -> float:
        i = self.token_index_at(char_pos)
        return self.tokens[i - 1].x1 if i > 0 else 0.0


def _is_word(s: str) -> bool:
    return any(ch.isalpha() for ch in s) and not all(ch in MARK_CHARS for ch in s.strip())


def parse_number(text: str) -> float | None:
    s = text.strip()
    if not s or not _NUM_RE.match(s) or not any(ch.isdigit() for ch in s):
        return None
    neg = s.startswith(("(", "-", "–")) and any(ch.isdigit() for ch in s)
    s = s.strip("()*").lstrip("-–$").replace(",", "").rstrip("%")
    try:
        v = float(s)
    except ValueError:
        return None
    return -v if neg else v


@dataclass
class Document:
    rows: list[Row]
    fmt: str
    note: str = ""

    def find(
        self, pattern: re.Pattern[str], start: int = 0, end: int | None = None
    ) -> tuple[int, re.Match[str]] | None:
        stop = len(self.rows) if end is None else min(end, len(self.rows))
        for i in range(start, stop):
            m = self.rows[i].search(pattern)
            if m:
                return i, m
        return None

    def find_all(
        self, pattern: re.Pattern[str], start: int = 0, end: int | None = None
    ) -> list[tuple[int, re.Match[str]]]:
        stop = len(self.rows) if end is None else min(end, len(self.rows))
        out = []
        for i in range(start, stop):
            m = self.rows[i].search(pattern)
            if m:
                out.append((i, m))
        return out
