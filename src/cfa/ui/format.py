"""Display formatting for FieldValues (shared by the table, detail view and exports)."""

from __future__ import annotations

from cfa.models.college import FIELDS, Kind
from cfa.models.field_value import FieldValue, Status


def fmt_value(key: str, fv: FieldValue) -> str:
    if not fv.ok:
        if fv.status in (Status.SOURCE_UNAVAILABLE, Status.RATE_LIMITED):
            return "Source unavailable"
        if fv.status is Status.PARSE_FAILED:
            return "Could not be read reliably"
        if fv.status is Status.AUTH_MISSING:
            return "Needs API key"
        return "Not reported"
    v = fv.value
    kind = FIELDS[key].kind if key in FIELDS else Kind.TEXT
    if kind is Kind.PERCENT:
        text = f"{v:.1f}%".replace(".0%", "%")
        if key.startswith("greek") and v == 0:
            text = "0% (no Greek life reported)"
    elif kind is Kind.MONEY:
        text = f"${int(v):,}"
    elif key == "net_price_by_income" and isinstance(v, dict):
        text = " · ".join(f"{k}: ${int(val):,}" for k, val in v.items())
    elif kind is Kind.COUNT:
        text = f"{int(v):,}"
    elif kind is Kind.GPA:
        text = f"{v:.2f}"
    elif kind is Kind.BOOL:
        text = "Yes" if v else "No"
    elif kind is Kind.MAP:
        text = ", ".join(f"{k}: {val}" for k, val in v.items()) if isinstance(v, dict) else str(v)
    else:
        text = str(v)
    if fv.estimated:
        text += " (estimated)"
    return text


def badge(fv: FieldValue) -> str:
    if fv.ok:
        return f"{fv.source} · {fv.year}" if fv.year else fv.source
    return fv.source or ""
