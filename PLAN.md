# PLAN.md — College Fit Advisor (Windows desktop app)

> **For Claude Code.** Read this whole file before writing code. Do the phases in order. Don't start a phase until the previous phase's acceptance criteria pass. If something here turns out to be wrong (an endpoint moved, a field got renamed), stop, write down what you found in `docs/DATA_SOURCES.md`, and adjust. Don't guess.

---

## 0. What we are building

A Windows desktop app for a **college advisor**. The advisor enters a student's profile (GPA, test scores, preferences) and gets a ranked list of colleges that fit in two ways:

1. **Academic fit**: Safety / Target / Reach, based on the school's admit rate, GPA distribution, and SAT/ACT ranges.
2. **Culture fit**: Greek life participation, campus setting, size, housing, athletics, and similar factors, weighted by what the student cares about.

**Hard requirements**

| # | Requirement | How this plan meets it |
|---|---|---|
| R1 | Standalone Windows app | Python 3.12 + PySide6 (Qt) GUI, packaged with PyInstaller into a `.exe`. GitHub Actions builds it on `windows-latest`. |
| R2 | College data is **not stored in the app**; it's pulled from the internet | Every college data point is fetched live at runtime and held in an in-memory cache that's cleared when the app closes. No college database ships with the app. The only things in the repo are a *source registry* (which URLs to fetch, not the data at those URLs) and code. |
| R3 | No errors in data collection | Only official APIs and primary-source documents are used (no scraping of sites that block or forbid it). Every fetch has timeouts, retries, schema validation, fallbacks, and a per-field status. The UI never crashes because a source failed. CI tests run against recorded fixtures, and a scheduled live smoke test catches upstream changes early. |
| R4 | Deployable to the GitHub repo | Git repo with CI, tests, and a tagged-release workflow that attaches the Windows build. Repo URL: https://github.com/mpromisel002/CollegeIQDashboard (the owner fills this in). |

---

## 1. Data source decisions (researched; follow them)

Each source the owner listed was checked for an API, its terms of use, and how reliable it is.

| Source | Public API? | Scraping allowed? | Decision |
|---|---|---|---|
| **IPEDS** (NCES) | No direct REST API from NCES. Two free official mirrors exist: **Urban Institute Education Data Portal API** (IPEDS tables, no key needed) and **College Scorecard API** (U.S. Dept. of Education, free api.data.gov key, 1,000 requests/hour). | Not needed | ✅ **Use APIs.** Primary: Urban API for IPEDS tables. Secondary/fallback: College Scorecard API. |
| **Common Data Set (CDS)** | None. Each college posts its own CDS as PDF or XLSX on its Institutional Research site. There's no central repository. | These are public documents meant for distribution; downloading them is fine. | ✅ **Fetch the documents directly** from URLs listed in a curated **source registry** (see §4), then parse them. This is the only source for ED/EA counts, GPA distribution, admission-factor weights, and Greek life %. |
| **Peterson's** | None | ❌ Terms of Use exclude "data mining, robots ('bots') or similar data gathering or extraction methods." | 🚫 **Do not fetch.** Show a **"View on Peterson's" link-out button** only. |
| **Niche** | None | ❌ User Agreement forbids copying/derivative works without written permission, and bypassing security measures. The site uses anti-bot protection, so scraping would break often. | 🚫 **Do not fetch.** Link-out button only. |
| **College Board (BigFuture)** | None public | ❌ Not permitted, and the content is JS-rendered and protected. | 🚫 **Do not fetch.** Link-out button only. Get SAT/ACT ranges from IPEDS (via Urban/Scorecard) and CDS §C9 instead. Same numbers, primary source. |
| **College Transitions Greek Life Dataverse** | None (plain HTML table, ~400 schools, keyed by IPEDS UnitID) | ❌ Terms say: "You may not obtain or attempt to obtain any materials or information through any means not intentionally made available…" and forbid derivative works. Content "is not for resale," which conflicts with a licensable product. | 🚫 **Do not scrape.** Their own page says the data comes from **CDS** forms. Get Greek life % directly from **CDS §F1** (the primary source). Link-out button only. |

**Rule for Claude Code:** don't write any HTTP client, headless browser, or parser that targets niche.com, petersons.com, collegeboard.org, or collegetransitions.com. Those sites only appear as URLs opened in the user's default browser (`QDesktopServices.openUrl`).

> If the owner later gets written permission or a data license from any of those sites, add a new adapter behind the same `SourceAdapter` interface (§5.2). Nothing else needs to change.

---

## 2. Field map (from the owner's "Data Fields" spec + culture layer)

Use the first available source and fall back in order. Every value shown in the UI carries `source`, `year`, and `status`.

### 2.1 General
| Field | Primary | Fallback |
|---|---|---|
| Street address, City, State, Postal code, Phone | Urban `ipeds/directory` | Scorecard `school.*` (no address/phone; city/state/zip only) |
| Degree of urbanization | Urban `ipeds/directory` → `urban_centric_locale` (map codes to labels: City/Suburb/Town/Rural × size) | Scorecard `school.locale` |

### 2.2 Applicants / Admits
| Field | Primary | Fallback |
|---|---|---|
| Applicants (total, women, men, another gender) | CDS **C1** | Urban `ipeds/admissions-enrollment` (by sex) |
| Admitted (total, women, men, another gender) | CDS **C1** | Urban `ipeds/admissions-enrollment` |
| Acceptance rate | Computed: admitted ÷ applicants | Scorecard `latest.admissions.admission_rate.overall` |
| Has ED plan? / ED applicants / ED admitted / ED rate | CDS **C21** | none (show "Not reported") |
| Has EA plan? / EA applicants / EA admitted / EA rate | CDS **C22** (the counts appear only if the school reports them) | none |
| RD applicants / admitted / rate | **Derived:** total − ED − EA (only when all inputs exist). Label it "Estimated" in the UI. | none |

> "Non-binary" in the owner's spec = CDS "Another Gender" column. Check the exact label in the current CDS template during Phase 1 and handle older templates that don't have it (return `NOT_REPORTED`, not 0).

### 2.3 GPA
| Field | Primary |
|---|---|
| Average HS GPA | CDS **C12** |
| % with GPA 4.0, 3.75–3.99, 3.50–3.74, 3.25–3.49, 3.00–3.24, 2.50–2.99, 2.00–2.49, 1.00–1.99, <1.00 | CDS **C11** (these bins match the owner's spec exactly) |

### 2.4 Test scores (replaces College Board as a data source)
| Field | Primary | Fallback |
|---|---|---|
| SAT EBRW/Math 25th/75th, ACT Composite 25th/75th, % submitting | Urban `ipeds/admissions-requirements` | CDS **C9**, then Scorecard `latest.admissions.sat_scores.*` / `act_scores.*` |
| Test policy (required/optional/blind) | CDS **C8** | Urban `ipeds/admissions-requirements` |

### 2.5 Culture layer
| Field | Primary | Notes |
|---|---|---|
| % men in fraternities, % women in sororities | CDS **F1** | Replaces College Transitions. Show "No Greek life" if the school reports 0 or N/A. |
| % undergrads living in college housing | CDS **F1** | |
| Campus setting | IPEDS locale (§2.1) | |
| Undergrad size | Scorecard `latest.student.size` | or Urban `ipeds/fall-enrollment` |
| Athletics level (NCAA D-I/II/III, NAIA) | Urban `ipeds/institutional-characteristics` (verify the variable exists in Phase 1) | If it isn't available, hide this filter. Don't guess. |
| Study abroad offered | CDS **E1** (special study options checkbox) | Yes/No only |
| Retention / 6-yr graduation rate | CDS **B22 / B10–B11** | Urban `ipeds/fall-retention`, `ipeds/grad-rates` |
| Admission factor importance (rigor, GPA, essay, ECs, interview, etc.) | CDS **C7** | Powers the "Selectivity profile" panel (§7, Phase 5) |
| Political lean | **No reliable public structured source.** | Excluded from v1. Optional advisor-entered note (§6.4). |

---

## 3. Tech stack (pinned so the build works)

- **Python 3.12** (64-bit)
- **PySide6** for the GUI (LGPL, mature PyInstaller support)
- **httpx** for HTTP, **tenacity** for retries/backoff
- **pydantic v2** for response/record schemas
- **pdfplumber** for CDS PDFs, **openpyxl** for CDS XLSX
- **cachetools** `TTLCache` for the in-memory session cache (no disk cache for college data)
- **keyring** to store the Scorecard API key in Windows Credential Manager
- **matplotlib** (QtAgg backend) for charts
- **pytest**, **pytest-qt**, **respx** (mock httpx), **ruff**, **mypy**
- **PyInstaller** (one-folder build, then zipped) for packaging

Pin exact versions in `requirements.txt` and `requirements-dev.txt`. Commit a lock (`pip freeze > requirements.lock`) once it all builds.

---

## 4. The Source Registry (how CDS works without storing data)

CDS documents live on 100+ different college websites, and their URLs change every year. Searching for them at runtime would be unreliable, so they're listed in a curated **registry**:

- File: `registry/schools.yaml`, versioned in the repo.
- **At runtime the app downloads the latest registry** from `https://raw.githubusercontent.com/<owner>/<repo>/main/registry/schools.yaml`. The copy bundled in the exe is a fallback if GitHub can't be reached. This lets the owner fix a broken CDS link by pushing to GitHub, with no rebuild.
- The registry holds **pointers only** (IDs, URLs), not college data. That keeps R2 intact.

```yaml
schema_version: 1
schools:
  - unitid: 166027            # IPEDS UnitID (primary key everywhere)
    name: Harvard University
    cds:
      - year: "2024-2025"
        url: https://.../CDS_2024-2025.pdf
        format: pdf            # pdf | xlsx
    links:                     # optional, opened in browser only
      niche: https://www.niche.com/colleges/harvard-university/
      petersons: null
      bigfuture: null
      collegetransitions_greek: https://www.collegetransitions.com/dataverse/greek-life
```

**Seeding the registry (Phase 1 task for Claude Code):**
1. Start with **25 schools** across selectivity levels and Greek-life levels. Include several heavy-Greek schools (e.g., large SEC/Big Ten publics), several with no Greek life, and a mix of PDF and XLSX publishers.
2. For each school, find the official CDS URL on the school's own `.edu` domain (web search is fine here; this is a dev-time task, not runtime).
3. Run `python -m cfa.tools.validate_registry`. It must HEAD/GET each URL, confirm HTTP 200 and the right content type, parse it, and print a coverage report (which fields were extracted per school).
4. Only commit entries where the URL resolves **and** C1 + C11/C12 + F1 parse. Write any failures to `docs/registry_failures.md` with the reason.
5. Document how the owner adds schools in `docs/ADDING_SCHOOLS.md` (target: 100–150 schools over time, as in the proposal).

The registry schema is validated with pydantic on load. A malformed registry is rejected and the bundled fallback is used, with a banner shown.

---

## 5. Architecture

```
college-fit-advisor/
├─ src/cfa/
│  ├─ app.py                  # entry point (QApplication)
│  ├─ config.py               # settings, API key via keyring, constants (timeouts, TTLs)
│  ├─ models/
│  │  ├─ student.py           # StudentProfile (pydantic)
│  │  ├─ college.py           # CollegeRecord: every field is a FieldValue
│  │  └─ field_value.py       # FieldValue{value, source, year, status, note}
│  ├─ sources/
│  │  ├─ base.py              # SourceAdapter protocol + FetchResult
│  │  ├─ http.py              # shared httpx client, retries, timeouts, User-Agent
│  │  ├─ urban_ipeds.py       # Urban Education Data Portal adapter
│  │  ├─ scorecard.py         # College Scorecard adapter
│  │  ├─ cds/
│  │  │  ├─ fetch.py          # downloads CDS doc into memory (BytesIO), size cap
│  │  │  ├─ parse_xlsx.py     # template-cell-based extraction
│  │  │  ├─ parse_pdf.py      # section-anchored text/table extraction
│  │  │  └─ sections.py       # C1, C7, C8, C9, C11, C12, C21, C22, E1, F1, B22 extractors
│  │  └─ registry.py          # remote-then-bundled registry loader
│  ├─ aggregate.py            # merges adapters per field using §2 priority order
│  ├─ cache.py                # in-memory TTLCache; cleared on exit
│  ├─ scoring/
│  │  ├─ academic.py          # Safety/Target/Reach
│  │  └─ culture.py           # weighted culture fit
│  ├─ ui/
│  │  ├─ main_window.py
│  │  ├─ student_panel.py     # profile entry + save/load JSON
│  │  ├─ results_table.py     # ranked list, sort/filter
│  │  ├─ college_detail.py    # all fields, source badges, link-out buttons
│  │  ├─ charts.py            # GPA distribution, admit-rate by round
│  │  ├─ settings_dialog.py   # API key, network test
│  │  └─ workers.py           # QThreadPool workers; UI thread never blocks
│  └─ tools/
│     ├─ validate_registry.py
│     └─ live_smoke.py
├─ registry/schools.yaml
├─ tests/ (unit, adapters with respx fixtures, parsers with sample CDS files, ui with pytest-qt)
├─ tests/fixtures/ (recorded API JSON + 6–8 sample CDS PDFs/XLSX — test-only, not shipped)
├─ docs/ (DATA_SOURCES.md, ADDING_SCHOOLS.md, USER_GUIDE.md, registry_failures.md)
├─ packaging/cfa.spec         # PyInstaller spec
├─ .github/workflows/ (ci.yml, release.yml, live-smoke.yml)
├─ requirements*.txt, pyproject.toml, README.md, LICENSE (proprietary, all rights reserved)
```

> Test fixtures are small samples used only so tests run offline. They're excluded from the PyInstaller build (verify this in the spec), so R2 holds for the shipped app.

### 5.1 The error-handling contract (this is what makes R3 work)

1. **No adapter raises to the caller.** Every adapter method returns `FetchResult` with `status ∈ {OK, PARTIAL, NOT_REPORTED, SOURCE_UNAVAILABLE, PARSE_FAILED, RATE_LIMITED, AUTH_MISSING}` plus the data and a human-readable `note`.
2. **HTTP rules** (`sources/http.py`): connect timeout 10s, read timeout 30s; up to 3 retries with exponential backoff and jitter on connection errors, 429, and 5xx; honor `Retry-After`; never retry other 4xx; a descriptive `User-Agent` (`CollegeFitAdvisor/<version> (+repo URL)`); max concurrency of 4 requests per host.
3. **Schema validation:** every API response goes through a pydantic model. Unknown extra fields are ignored. Missing expected fields → `PARTIAL`, with the field marked `NOT_REPORTED`.
4. **Sentinel handling:** Urban API uses negative codes (−1, −2, −3) for missing/not applicable; Scorecard uses `null` and `"PrivacySuppressed"`. Convert all of these to `NOT_REPORTED`. **Never display them as numbers.**
5. **Latest-year discovery:** for each Urban endpoint, try the current year minus 1 and walk back up to 4 years until results are non-empty. Cache the discovered year per endpoint for the session. Never hardcode a year.
6. **CDS parsing:** each section extractor is independent. One failed section doesn't fail the others. Every extracted number gets a sanity check (percentages 0–100; GPA bins sum to 95–105%; admits ≤ applicants; ED admits ≤ ED applicants). Values that fail are dropped as `PARSE_FAILED` instead of being shown wrong.
7. **Download caps:** CDS files over 25 MB are rejected. Content type must match the registry format. Everything is read into memory only, never written to disk.
8. **Fallback merge** (`aggregate.py`): for each field, take the first source in the §2 order whose status is OK. Record which source won.
9. **UI:** every value has a small badge (source + year). Missing values say "Not reported" or "Source unavailable — Retry". A status bar summarizes source health. Uncaught exceptions in workers are caught, logged, and shown as a non-blocking toast.
10. **Logging:** rotating log at `%LOCALAPPDATA%\CollegeFitAdvisor\logs\` (no student PII and no college data in logs, just source, status, and timing).

### 5.2 `SourceAdapter` interface
```python
class SourceAdapter(Protocol):
    name: str
    async def fetch(self, unitid: int) -> FetchResult: ...
    async def health_check(self) -> FetchResult: ...
```
Use `asyncio` inside a worker thread (`qasync` is optional; a `QRunnable` running `asyncio.run(...)` is fine and simpler).

---

## 6. Scoring logic (transparent; the advisor can see the math)

### 6.1 Student profile
Unweighted GPA (4.0 scale), optional weighted GPA, SAT (EBRW + Math) and/or ACT, test-submit intent, intended major (free text, informational in v1), preferred regions/states, size preference, setting preference, Greek life importance (0–3) and direction (wants / neutral / avoids), housing importance, athletics preference, ED/EA willingness, and notes. Profiles are saved/loaded as JSON files **wherever the advisor chooses**. That's student data owned by the advisor, not college data.

### 6.2 Academic fit (`scoring/academic.py`)
- **GPA percentile:** place the student's GPA in the school's C11 distribution to get the estimated share of admitted students below them.
- **Test position:** below 25th / 25–75th / above 75th percentile (if the student submits tests and the school reports them).
- **Admit rate** from §2.2.
- **Classification:**
  - **Reach**: admit rate < 15% (always, regardless of stats), *or* the student is below the 25th percentile on tests or in the bottom 25% of GPA.
  - **Safety**: admit rate ≥ 50% *and* the student is above the 75th percentile on tests (or test-optional and above median GPA) *and* in the top 25% of GPA.
  - **Target**: everything else.
  - If data is insufficient → **"Unclassified (insufficient data)"**. Never guess.
- Show the reason string, e.g. "Reach: admit rate 9% (<15%)".
- Put the thresholds in `config.py` so the owner can tune them. Unit-test each branch.

### 6.3 Culture fit (`scoring/culture.py`)
Score 0–100 = weighted average of the sub-scores the student cares about (weight = importance 0–3; importance 0 drops that factor):
- **Greek:** average of frat/sorority %. If the student wants Greek life, higher is better (scaled so ≥30% = 100). If the student avoids it, inverted. Neutral = excluded.
- **Setting:** 100 if it matches, 50 if adjacent (City↔Suburb, Suburb↔Town, Town↔Rural), else 0.
- **Size:** banded (<5k, 5–15k, 15–30k, >30k); 100 if it matches, 50 if adjacent.
- **Housing:** % living on campus, scaled.
- **Athletics / Region / Study abroad:** match = 100, else 0.
- Factors with `NOT_REPORTED` data are excluded from the denominator and listed as "not scored" so they don't silently count against a school.

### 6.4 Optional advisor notes (off by default)
A per-school free-text and tags field (e.g., "political lean: left-leaning per campus visit"), saved in a JSON file the advisor chooses. It's the advisor's own information, kept separate from fetched data, and clearly labeled "Advisor note."

---

## 7. Phases & acceptance criteria

### Phase 0: Repo & skeleton
- `git init`, add the structure from §5, `pyproject.toml`, pinned requirements, ruff/mypy config, a README with a placeholder screenshot, and a proprietary LICENSE ("All rights reserved — [Owner Business Name]").
- Add `.github/workflows/ci.yml` (windows-latest + ubuntu-latest; ruff, mypy, pytest with `QT_QPA_PLATFORM=offscreen`).
- `git remote add origin <YOUR_GITHUB_REPO_URL>`, create a branch, push, and open a PR with `gh`.
- ✅ CI green. `python -m cfa` opens an empty main window.

### Phase 1: Verify sources & write `docs/DATA_SOURCES.md` (do this before writing adapters)
- With live network access, call each endpoint for 3 known UnitIDs and **record the exact URL patterns, field names, sentinel values, and latest available years** that actually come back:
  - Urban: `https://educationdata.urban.org/api/v1/college-university/ipeds/{topic}/{year}/?unitid={id}` for `directory`, `admissions-enrollment`, `admissions-requirements`, `institutional-characteristics`, `fall-retention`, `grad-rates`. Handle the paginated `{"count","next","results"}` envelope.
  - Scorecard: `https://api.data.gov/ed/collegescorecard/v1/schools?id={id}&fields=...&api_key=...`. Confirm field names against the official data dictionary.
- Save the real responses as fixtures in `tests/fixtures/api/`.
- Get the current CDS template (from commondataset.org) and confirm the exact labels for C1 (including the "Another Gender" column), C11, C12, C21, C22, F1, C7, C8, C9, E1.
- Seed and validate the registry (§4).
- ✅ `DATA_SOURCES.md` lists every field in §2 with its verified path. `validate_registry` passes for every committed school.

### Phase 2: Data layer
- Implement `http.py`, `urban_ipeds.py`, `scorecard.py`, the `cds/` parsers, `registry.py`, `aggregate.py`, and `cache.py`, following §5.1 exactly.
- **CDS XLSX:** locate values by finding the section label text in the sheet (e.g., "C1" row headers), not by fixed cell coordinates, because schools modify templates.
- **CDS PDF:** use `pdfplumber` to extract text and tables per page. Find the section by its code and heading text (e.g., `C11` + "Percentage of all enrolled"). Pull numbers with regex scoped to that section's text window. Prefer table extraction when the table is detected; otherwise fall back to text.
- Tests: respx-mocked adapter tests covering 200, empty results, 429→retry→200, 500×3→`SOURCE_UNAVAILABLE`, timeout, bad JSON, sentinels, and PrivacySuppressed. Parser tests run on ≥6 real sample CDS files (mix of PDF/XLSX), with expected values hand-verified and written into the test.
- ✅ `python -m cfa.tools.live_smoke` fetches all registry schools with zero unhandled exceptions, and prints a per-field coverage table. Test coverage of `sources/` ≥ 90%.

### Phase 3: Fit Finder UI (Module A)
- Student panel → "Run Match" → workers fetch all registry schools in parallel (with a progress bar and a cancel button) → results table with columns for Name, State, Academic tier, Culture score, Admit rate, Greek %, Setting, and Size. Sortable, with filters (tier, state, Greek yes/no, setting, size).
- College detail view: every §2 field with source badges, a GPA distribution bar chart, an admit-rate by round chart (ED / EA / RD-estimated), and link-out buttons (Niche, Peterson's, BigFuture, College Transitions, the school's CDS document). The link-out buttons open the system browser.
- Settings: Scorecard API key (stored with keyring), a "Test connections" button showing each source's health, and a "Reload registry" button.
- Export the results list to CSV/PDF **on demand to a location the user picks**. It's a report, not an app data store.
- ✅ pytest-qt tests cover profile entry, the run flow with mocked adapters, and the detail view rendering with a mix of missing fields. Turning off the network mid-run shows "Source unavailable" badges and doesn't crash.

### Phase 4: Windows packaging & release
- `packaging/cfa.spec`: one-folder build, windowed (no console), app icon, includes the bundled `registry/schools.yaml`, **excludes `tests/`**, and includes the PySide6 plugins it needs (platforms, styles, imageformats). Include certifi's CA bundle so HTTPS works on clean Windows installs.
- `.github/workflows/release.yml`: on tag `v*` → windows-latest → install, run tests, build with PyInstaller, smoke-launch the exe with a `--self-test` flag (loads the registry, pings each source, exits 0/1), zip `dist/CollegeFitAdvisor/`, and attach it to the GitHub Release.
- Note in the README: unsigned exes trigger Windows SmartScreen ("More info → Run anyway"). Code signing is a later, paid step.
- ✅ Tag `v0.1.0` produces a Release containing `CollegeFitAdvisor-win64.zip`. On a clean Windows machine, unzipping and running the exe works without Python installed.

### Phase 5: Selectivity profile (feasible slice of Module B)
- In the detail view, a "What this school weighs" panel built from CDS **C7** (Very Important / Important / Considered / Not Considered for each factor), plus test policy (C8) and the ED/EA advantage (ED admit rate vs. overall).
- ✅ Renders for all registry schools where C7 parsed. Others show "Not reported."

### Phase 6: Upstream-change monitoring
- `.github/workflows/live-smoke.yml`: weekly scheduled run of `live_smoke` against real sources. Fail if any source health check fails or field coverage drops more than 10% from the committed baseline (`docs/coverage_baseline.json`). If the GitHub token permits, it opens an issue automatically on failure.
- ✅ The workflow runs and reports correctly (test this by temporarily pointing at a bad URL).

---

## 8. Explicitly out of scope for v1 (and why)

| Proposal item | Why it's excluded | Possible path later |
|---|---|---|
| Module B: "what rigor/EC patterns correlate with admits, by school and major" | No public dataset has admit outcomes by applicant profile or by major. Any numbers would be invented. | Only possible with the owner's own historical client outcome data. |
| Module C: Essay Alignment Tool | Needs "priority profiles" built from mission statements (unstructured, varies by school) and an LLM. Results can't be verified as error-free, and student essays involve sensitive data from minors. | A separate phase using the Claude API with the advisor's own key and explicit consent. It would stay diagnostic only and never rewrite essays, as the proposal requires. |
| Political lean, "athletics culture" beyond NCAA division | No reliable public structured source | Advisor notes (§6.4) |
| Any data from Niche, Peterson's, College Board, College Transitions | Terms of use forbid automated extraction; anti-bot measures make it break often | Link-outs now; a licensed feed later if permission is obtained |
| Tableau version | Replaced by a desktop app per the owner's requirements | — |

---

## 9. Working rules for Claude Code

1. Do the phases in order. Commit after each logical step with clear messages. Use one branch + PR per phase; merge when CI is green.
2. Never hardcode a data year, a field value, or a college statistic in source code. Tests may contain expected values; app code may not.
3. Never write fetched college data to disk (no SQLite, no pickle, no JSON cache). The in-memory `TTLCache` only.
4. Don't add scraping for the 🚫 sites in §1, even as a "fallback."
5. When a verification in Phase 1 contradicts this plan, update `docs/DATA_SOURCES.md`, adjust the code, and add a note to this file's changelog section below.
6. Keep the UI responsive: no network calls on the Qt main thread.
7. Before declaring any phase done, run `ruff check`, `mypy src`, and `pytest`, and confirm CI passes on windows-latest.

## Changelog
- v1: initial plan.
- v1.1 (2026-10-06, Phase 1 verification — details in `docs/DATA_SOURCES.md`):
  - **Test-score priority changed to CDS C9 → IPEDS → Scorecard.** IPEDS `admissions-requirements`
    has no data after 2022 (verified), while the registry's CDS files are 2024-26.
  - **Athletics:** IPEDS `institutional-characteristics` has NCAA/NAIA membership flags but no
    division. The filter is NCAA / NAIA / none; divisions are not shown (never guessed).
  - **Study abroad** gets an IPEDS fallback (`institutional-characteristics.study_abroad`).
  - **Undergrad size fallback** uses `enrollment-headcount/{year}/undergraduate/`; the plan's
    `fall-enrollment` path only returns credit-hour/FTE rows.
  - **C1 "another gender":** the 2025-26 CDS template replaced it with "unknown sex". Older templates
    still populate `applicants_another`; newer ones show "Not reported". The printed total row
    (which includes unknown sex) is used when it agrees with the parts.
  - **Extra R3 guards** beyond the plan: men/women admit-rate consistency check in C1, CDS-vs-IPEDS
    applicant cross-check in `aggregate.py`, and refusal to guess a C11/F1 column when a school filled
    only some columns.
  - **Registry bar:** many selective privates (Dartmouth, Rice, Duke, Bowdoin, W&L, …) publish no
    GPA (C11/C12), so they fail the plan's C1 + C11/C12 + F1 rule; see `docs/registry_failures.md`.
  - **Link-outs** without a registry URL open a site-restricted web search instead of a guessed URL.
  - Work was delivered on a single branch/PR (`claude/relaxed-davinci-536zjd`) rather than one PR per
    phase, as required by the session's branch rules.
- v1.2 (2026-10-06): the app repo stays private, so `raw.githubusercontent.com` URLs into it return 404.
  The registry is mirrored to the public repo `mpromisel002/mpromisel002-CollegeIQDashboard-registry` by
  `.github/workflows/registry-sync.yml`, and `REGISTRY_REMOTE_URL` points there.
- v1.3 (2026-10-19, advisor feedback):
  - **Preferred states are a hard filter by default.** A profile's preferred states now hide schools
    in other states (and schools whose state could not be confirmed); "Only show schools in these
    states" turns it off, after which states only feed the Region culture factor. Codes and full
    names are both accepted; unrecognized entries are flagged, not silently dropped. Old profiles
    without the new `only_preferred_states` field load with filtering on.
  - **UI redesign** modelled on CollegePlannerPro's college search: header bar, Student/Filters
    sidebar with checkbox filter groups, result cards (badges, stat grid, reasoning) with a table
    toggle and a sort menu. Fixed light theme (Fusion + stylesheet in `ui/theme.py`).
  - New `control` field (Public / Private nonprofit / Private for-profit) from the IPEDS directory,
    shown as a badge and offered as a filter.
- v1.4 (2026-10-20): **search every four-year college, not only the registry.** "All four-year
  colleges" (default) lists colleges from the IPEDS directory for the preferred states (or the whole
  country) and loads IPEDS/Scorecard in bulk; the registry still supplies CDS documents, so those
  schools show "Full data" and the rest "Federal data only". R2 is unchanged (nothing stored). Scoring
  changes needed for schools without a CDS: Safety may rest on tests + admit rate when the school
  publishes no GPA distribution, and SAT/ACT ranges are ignored when under 5 % of enrollees submitted
  that test. Cards are paged (20 per page).
- v1.5 (2026-10-26): **registry bar is C1 + C11/C12** (admissions and GPA). F1 (Greek life,
  housing) is optional: schools that publish GPA but leave F1 blank now qualify and show "Not
  reported" for Greek life. Registry entries are found with `python -m cfa.tools.find_cds`, which
  looks only on each college's own website (robots.txt respected) and keeps a document only if it
  passes the same check as `validate_registry`. CDS PDFs are pre-scanned with pdfium so only parts
  B–F are laid out (about twice as fast, identical results on all registry documents).
- v1.6 (2026-10-27): **cost and scholarships.** College Scorecard adds tuition, cost of attendance,
  net price (average and by family income), Pell share and median debt; IPEDS tuition is the
  fallback without a key. Scholarship data comes from CDS H2/H2A (need-based grants, need met, and
  merit aid for students without need) because Scorecard has none and IPEDS grant data in the Urban
  API ends in 2021. Shown on cards, in a "Cost and aid" detail section, as a net-price sort and filter,
  and in CSV export.
