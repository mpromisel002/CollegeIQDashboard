import pytest

from cfa.models.field_value import Status
from cfa.sources.cds.adapter import parse_document
from cfa.sources.cds.layout import Document, Row, Token, parse_number
from cfa.sources.cds.sections import extract_c1, extract_c11, extract_f1


@pytest.mark.parametrize(
    "text,value",
    [
        ("61,994", 61994),
        ("88.0%", 88.0),
        ("3.85", 3.85),
        ("(5)", -5),
        ("$1,200", 1200),
        ("abc", None),
        ("-", None),
        ("2025-26", None),
    ],
)
def test_parse_number(text, value):
    assert parse_number(text) == value


def doc_from_lines(lines: list[str], fmt: str = "pdf") -> Document:
    """Build a Document where every word sits 30pt apart so numbers are separate tokens."""
    rows = []
    for i, line in enumerate(lines):
        toks, x = [], 50.0
        for w in line.split():
            toks.append(Token(w, x, x + 6 * len(w)))
            x += 6 * len(w) + 4
        rows.append(Row(toks, float(i * 12), 0))
    return Document(rows, fmt)


def test_c1_inconsistent_gender_rates_rejected():
    doc = doc_from_lines(
        [
            "C1 First-time, first-year students",
            "Total first-time, first-year men who applied 15233",
            "Total first-time, first-year women who applied 180508",
            "Total first-time, first-year men who were admitted 13470",
            "Total first-time, first-year women who were admitted 16240",
        ]
    )
    res = extract_c1(doc, "2025-2026")
    assert res.status is Status.PARSE_FAILED
    assert all(fv.status is Status.PARSE_FAILED for fv in res.fields.values())


def test_c1_admits_over_applicants_rejected():
    doc = doc_from_lines(
        [
            "C1 First-time",
            "Total first-time, first-year men who applied 100",
            "Total first-time, first-year women who applied 100",
            "Total first-time, first-year men who were admitted 150",
            "Total first-time, first-year women who were admitted 90",
        ]
    )
    out = extract_c1(doc, None).fields
    assert out["admits_men"].status is Status.PARSE_FAILED
    assert out["applicants_women"].value == 100


def test_c11_bad_sum_rejected():
    lines = ["C11 Percentage of all enrolled"] + [
        f"Percent who had GPA {label} {v}"
        for label, v in [("of 4.0", 50), ("between 3.75 and 3.99", 50), ("between 3.50 and 3.74", 50)]
    ]
    res = extract_c11(doc_from_lines(lines), None)
    assert res.status is Status.PARSE_FAILED


def test_f1_single_value_without_header_is_not_guessed():
    doc = doc_from_lines(["F1 Percentages", "Percent of men who join fraternities 20%"])
    out = extract_f1(doc, None).fields
    assert not out["greek_men_pct"].ok


def test_f1_less_than_one_percent():
    doc = doc_from_lines(["F1 Percentages", "Percent of males who join fraternities <1% <1%"])
    out = extract_f1(doc, None).fields
    assert out["greek_men_pct"].value == 0.5 and "less than 1%" in out["greek_men_pct"].note


def test_garbage_documents_do_not_raise():
    assert parse_document(b"%PDF-1.4 nonsense", "pdf", None)[1]
    assert parse_document(b"PK\x03\x04 nonsense", "xlsx", None)[1]
