# College Fit Advisor — user guide

## Install

1. Download `CollegeFitAdvisor-win64.zip` from the GitHub Releases page.
2. Unzip anywhere (for example `Documents\CollegeFitAdvisor`) and run `CollegeFitAdvisor.exe`.
3. Windows SmartScreen may say "Windows protected your PC" because the app is not code-signed yet:
   click **More info → Run anyway**.

Python is not needed. An internet connection is required: no college data is stored in the app.

## First run

*Tools → Settings*: paste a free College Scorecard key from <https://api.data.gov/signup> (it is
stored in Windows Credential Manager). Without it the app still works; undergraduate size and a few
fallbacks come from IPEDS instead. **Test connections** shows each source's health.

## Matching a student

1. Fill in the profile on the left: unweighted GPA, SAT and/or ACT (or untick "Will submit test
   scores"), preferred states, and how much each culture factor matters (0 = ignore … 3 = high).
2. **Run Match**. All schools are fetched in parallel (progress bar; **Cancel** stops early).
3. The table is sortable; filter by tier, state, Greek life, setting and size. Hover a tier or culture
   score to see the reasoning.
4. Double-click a school for every field with its source badge (source · year), the GPA chart, admit
   rate by round, what the school weighs (CDS C7), and buttons to open Niche, Peterson's, BigFuture,
   College Transitions, the CDS document and the school site in your browser.

Profiles are saved/loaded as JSON files wherever you choose (*File* menu). Results can be exported to
CSV or PDF on demand.

## How the tiers work

- **Reach** — admit rate under 15 % (always), or the student is below the school's 25th percentile on
  tests, or in the bottom 25 % of its GPA distribution.
- **Safety** — admit rate at least 50 %, tests above the 75th percentile (or not submitting tests with
  a GPA above the median), and GPA in the top 25 %.
- **Target** — everything else.
- **Unclassified** — not enough data (no admit rate, or neither GPA distribution nor comparable tests).

SAT comparisons add the section 25th/75th percentiles (an approximation of the composite range).
Thresholds are in `src/cfa/config.py`.

Culture fit is the importance-weighted average of the factors you set; factors a school does not
report are listed as "not scored" instead of counting against it.

## What the badges mean

| Badge / text | Meaning |
|---|---|
| `Common Data Set · 2025-2026` | value read from the school's CDS for that year |
| `IPEDS (Urban) · 2024` | federal IPEDS data for that year |
| `College Scorecard · latest` | Scorecard's most recent release |
| `Derived` / *(estimated)* | computed by the app, e.g. regular-decision counts |
| Not reported | the source does not report it |
| Source unavailable — Retry | the source could not be reached; **Retry** refetches that school |
| Could not be read reliably | the document had a value that failed a sanity check, so it is hidden |

Logs (no student or college data) are in `%LOCALAPPDATA%\CollegeFitAdvisor\logs\`.
