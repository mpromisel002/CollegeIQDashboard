"""Check every registry entry: URL resolves, content type is right, document parses.

    python -m cfa.tools.validate_registry [--registry registry/schools.yaml] [--json out.json]

A school passes when C1 parses, C11 or C12 parses, and F1 yields at least one value
(PLAN §4). Exit code 1 if any school fails.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from cfa.models.field_value import Status
from cfa.sources.cds.adapter import parse_document
from cfa.sources.cds.fetch import fetch_cds
from cfa.sources.cds.sections import EXTRACTORS, SectionResult
from cfa.sources.http import HttpClient
from cfa.sources.registry import School, load_bundled

OK_STATES = (Status.OK, Status.PARTIAL)


def passes(sections: dict[str, SectionResult]) -> tuple[bool, str]:
    def ok(code: str) -> bool:
        return (
            code in sections
            and sections[code].status in OK_STATES
            and any(fv.ok for fv in sections[code].fields.values())
        )

    reasons = []
    if not (sections.get("C1") and sections["C1"].status is Status.OK):
        reasons.append("C1 did not parse")
    if not (ok("C11") or ok("C12")):
        reasons.append("neither C11 nor C12 parsed")
    if not ok("F1"):
        reasons.append("F1 did not parse")
    return not reasons, "; ".join(reasons)


async def check_school(http: HttpClient, school: School) -> dict:
    doc = school.latest_cds
    row: dict = {"unitid": school.unitid, "name": school.name}
    if doc is None:
        return {**row, "pass": False, "reason": "no CDS listed"}
    row.update(year=doc.year, format=doc.format, url=doc.url)
    status, content, note = await fetch_cds(http, doc.url, doc.format)
    if content is None:
        # HTTP 403 with no other change usually means the school's firewall refuses this network
        # (cloud CI runners are often blocked), not that the link broke. Reported separately.
        blocked = "HTTP 403" in note
        return {**row, "pass": False, "blocked": blocked, "reason": f"download: {status.value} {note}"}
    loop = asyncio.get_running_loop()
    sections, err = await loop.run_in_executor(None, parse_document, content, doc.format, doc.year)
    if err:
        return {**row, "pass": False, "reason": f"parse: {err}"}
    ok, reason = passes(sections)
    row["sections"] = {c: s.status.value for c, s in sections.items()}
    row["fields"] = {k: fv.value for s in sections.values() for k, fv in s.fields.items() if fv.ok}
    return {**row, "pass": ok, "reason": reason}


async def main_async(path: Path | None) -> list[dict]:
    registry = load_bundled(path)
    async with HttpClient() as http:
        sem = asyncio.Semaphore(4)

        async def one(s: School) -> dict:
            async with sem:
                return await check_school(http, s)

        return list(await asyncio.gather(*(one(s) for s in registry.schools)))


def print_report(rows: list[dict]) -> None:
    codes = list(EXTRACTORS)
    head = f"{'School':38} {'fmt':4} " + " ".join(f"{c:>4}" for c in codes) + "  result"
    print(head)
    print("-" * len(head))
    mark = {"OK": "ok", "PARTIAL": "part", "NOT_REPORTED": "-", "PARSE_FAILED": "FAIL"}
    for r in rows:
        secs = r.get("sections", {})
        cells = " ".join(f"{mark.get(secs.get(c, ''), '?'):>4}" for c in codes)
        if r["pass"]:
            result = "PASS"
        elif r.get("blocked"):
            result = f"BLOCKED ({r['reason']})"
        else:
            result = f"FAIL ({r['reason']})"
        print(f"{r['name'][:38]:38} {r.get('format', ''):4} {cells}  {result}")
    n_pass = sum(r["pass"] for r in rows)
    n_blocked = sum(bool(r.get("blocked")) for r in rows)
    print(f"\n{n_pass}/{len(rows)} schools pass" + (f", {n_blocked} blocked (HTTP 403)" if n_blocked else ""))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--registry", type=Path, default=None)
    ap.add_argument("--json", type=Path, default=None, help="write full results as JSON")
    ap.add_argument(
        "--allow-blocked",
        action="store_true",
        help="do not fail on HTTP 403 (school firewalls often block cloud CI runners)",
    )
    args = ap.parse_args(argv)
    rows = asyncio.run(main_async(args.registry))
    print_report(rows)
    if args.json:
        args.json.write_text(json.dumps(rows, indent=2, default=str), encoding="utf-8")
    return 0 if all(r["pass"] or (args.allow_blocked and r.get("blocked")) for r in rows) else 1


if __name__ == "__main__":
    sys.exit(main())
