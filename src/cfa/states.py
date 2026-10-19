"""U.S. state and territory codes, and parsing of what an advisor types into a states field."""

from __future__ import annotations

import re

STATE_NAMES: dict[str, str] = {
    "AL": "Alabama",
    "AK": "Alaska",
    "AZ": "Arizona",
    "AR": "Arkansas",
    "CA": "California",
    "CO": "Colorado",
    "CT": "Connecticut",
    "DE": "Delaware",
    "DC": "District of Columbia",
    "FL": "Florida",
    "GA": "Georgia",
    "HI": "Hawaii",
    "ID": "Idaho",
    "IL": "Illinois",
    "IN": "Indiana",
    "IA": "Iowa",
    "KS": "Kansas",
    "KY": "Kentucky",
    "LA": "Louisiana",
    "ME": "Maine",
    "MD": "Maryland",
    "MA": "Massachusetts",
    "MI": "Michigan",
    "MN": "Minnesota",
    "MS": "Mississippi",
    "MO": "Missouri",
    "MT": "Montana",
    "NE": "Nebraska",
    "NV": "Nevada",
    "NH": "New Hampshire",
    "NJ": "New Jersey",
    "NM": "New Mexico",
    "NY": "New York",
    "NC": "North Carolina",
    "ND": "North Dakota",
    "OH": "Ohio",
    "OK": "Oklahoma",
    "OR": "Oregon",
    "PA": "Pennsylvania",
    "RI": "Rhode Island",
    "SC": "South Carolina",
    "SD": "South Dakota",
    "TN": "Tennessee",
    "TX": "Texas",
    "UT": "Utah",
    "VT": "Vermont",
    "VA": "Virginia",
    "WA": "Washington",
    "WV": "West Virginia",
    "WI": "Wisconsin",
    "WY": "Wyoming",
    "PR": "Puerto Rico",
    "GU": "Guam",
    "VI": "U.S. Virgin Islands",
    "AS": "American Samoa",
    "MP": "Northern Mariana Islands",
}

_BY_NAME = {name.lower(): code for code, name in STATE_NAMES.items()}
_BY_NAME.update({"washington dc": "DC", "washington d c": "DC", "virgin islands": "VI"})


def parse_states(text: str | list[str]) -> tuple[list[str], list[str]]:
    """Split typed input into (known codes in order, unrecognized entries).

    Accepts codes in any case ("pa"), full names ("Pennsylvania"), and commas, semicolons,
    slashes or plain spaces between codes ("PA NY MA").
    """
    items = text if isinstance(text, list) else re.split(r"[,;/\n]+", text)
    codes: list[str] = []
    unknown: list[str] = []
    for raw in items:
        token = " ".join(str(raw).replace(".", " ").split()).strip()
        if not token:
            continue
        found = _lookup(token)
        if found is None and " " in token:
            parts = token.split()
            if all(_lookup(p) for p in parts):
                found = [c for p in parts for c in _lookup(p) or []]
        if found is None:
            unknown.append(str(raw).strip())
            continue
        for code in found:
            if code not in codes:
                codes.append(code)
    return codes, unknown


def _lookup(token: str) -> list[str] | None:
    up = token.upper().replace(" ", "")
    if up in STATE_NAMES:
        return [up]
    code = _BY_NAME.get(token.lower())
    return [code] if code else None
