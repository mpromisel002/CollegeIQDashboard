# Data sources (verified)

Verified against the live services on **2026-10-06** while building Phase 1. Recorded responses
live in `tests/fixtures/api/` (test-only; never shipped). Where this file disagrees with PLAN.md,
this file wins and the PLAN changelog says why.

## 1. Urban Institute Education Data Portal (IPEDS mirror)

- Base: `https://educationdata.urban.org/api/v1/college-university/ipeds/{topic}/{year}/?unitid={id}`
- No key. Envelope: `{"count", "next", "previous", "results": [...]}`; `next` is followed (max 5 pages).
- Response times vary from 0.3 s to 30 s+; occasional timeouts were observed, so the shared
  client's retry/backoff matters here.
- **Sentinels:** `-1` missing, `-2` not applicable, `-3` suppressed (numbers *and* strings such as
  `"-2"`). All become `NOT_REPORTED`; never displayed. (Confirmed via
  `/api/v1/api-endpoint-varlist/?endpoint_id=N`.)
- **Latest-year discovery:** start at current year − 1 and walk back 4 more years until results are
  non-empty; the year found is cached per topic for the session.

| Topic (endpoint) | Latest year with data (Oct 2026) | Fields used → app field |
|---|---|---|
| `directory` | 2025 | `inst_name`, `address`, `city`, `state_abbr`, `zip` (ZIP+4 trimmed), `phone_number`, `url_school`, `urban_centric_locale` → name, address, city, state, zip, phone, website, locale + setting |
| `admissions-enrollment` | 2024 | rows by `sex`: `1` male, `2` female, `3` "gender not identified", `9` unknown, `99` total; `number_applied`, `number_admitted` → applicants_*/admits_* |
| `admissions-requirements` | **2022** (2023-2025 empty) | `sat_crit_read_25/75_pctl` (= EBRW), `sat_math_25/75_pctl`, `act_composite_25/75_pctl`, `sat_percent_submitting`, `act_percent_submitting`, `reqt_test_scores` (`0` neither, `1` required, `2` recommended, `3` considered) |
| `institutional-characteristics` | 2025 | `member_ncaa`, `member_naia` (1/0) → athletics; `study_abroad` (1/0) |
| `fall-retention` | 2024 | row `ftpt = 1`: `retention_rate` (fraction) |
| `grad-rates` | 2023 | row `subcohort = 2` (bachelor's), `race = 99`, `sex = 99`: `completion_rate_150pct` (= 6-year rate) |
| `enrollment-headcount/{year}/undergraduate/` | 2024 | row with `race, sex, ftpt, degree_seeking, class_level` all `99`: `headcount` |

`urban_centric_locale` codes: 11-13 City (large/midsize/small), 21-23 Suburb, 31-33 Town
(fringe/distant/remote), 41-43 Rural. Setting = the tens digit.

**Athletics:** `institutional-characteristics` has NCAA/NAIA *membership* flags but **no division**
(D-I/II/III). The app therefore offers NCAA / NAIA / none only; it never guesses a division.

**`fall-enrollment`** (named in the plan) only returns credit-hour/FTE rows at that path; headcount
comes from `enrollment-headcount/{year}/undergraduate/` instead.

## 2. College Scorecard

- `https://api.data.gov/ed/collegescorecard/v1/schools?id={id}&fields=...&api_key=...`
- Key: free from api.data.gov. No key → HTTP 403 `API_KEY_MISSING` → app shows `AUTH_MISSING`.
  `DEMO_KEY` works for development but allows only ~10 requests/hour.
- Unknown id → `200` with `results: []`. Missing values are `null` or `"PrivacySuppressed"`.

| Scorecard field | App field |
|---|---|
| `school.name`, `school.city`, `school.state`, `school.zip`, `school.school_url` | name, city, state, zip, website |
| `school.locale` (same NCES codes as above) | locale, setting |
| `latest.student.size` | undergrad_size (primary) |
| `latest.admissions.admission_rate.overall` (fraction) | acceptance_rate (fallback) |
| `latest.admissions.sat_scores.{25th,75th}_percentile.{critical_reading,math}` | SAT ranges (3rd choice) |
| `latest.admissions.act_scores.{25th,75th}_percentile.cumulative` | ACT range (3rd choice) |
| `latest.admissions.test_requirements` (`1` required, `2` recommended, `3` neither, `5` considered) | test_policy (3rd choice) |
| `latest.student.retention_rate.four_year.full_time` | retention_rate (3rd choice) |
| `latest.completion.completion_rate_4yr_150nt` | grad_rate_6yr (3rd choice) |

Scorecard does not expose a data year for `latest.*`; badges show "latest".

## 3. Common Data Set (each school's own PDF/XLSX)

Documents are listed in `registry/schools.yaml` and downloaded into memory at runtime (25 MB cap;
magic bytes and content type must match the registry's `format`; an HTML page in place of the file
is reported as "link may have moved").

Three layouts exist in the wild, and all three are handled by the same label-anchored extractors:

1. **Printed/flattened PDFs** — values are page text; check marks are glyphs (`X`, `x`, `✓`, `☒`,
   Wingdings ``, …).
2. **Filled AcroForm PDFs** (the official CDS template) — values live in form fields, not page text.
   Field values (including values stored on a parent field) are placed at the field's position and
   read like text; checked boxes become a mark. Fields whose value is also printed inside the box are
   de-duplicated.
3. **XLSX** (the official workbook) — labels are found by text, never by cell address. Percent cells
   are fractions (`0.351`) and are scaled using the cell's `%` number format. The workbook's
   machine-readable "answer sheet" columns (`C.101`, …) are ignored.

### Template labels confirmed (2024-25 and 2025-26 templates)

| Section | Label text the parser anchors on | Notes |
|---|---|---|
| C1 | "Total first-time, first-year {men\|males\|women\|females} who applied / were admitted" | 2025-26 replaced "another gender" with **"students of unknown sex"**; older templates have "another gender" (→ applicants_another). Missing rows → `NOT_REPORTED`, never 0. A printed "Total first-time, first-year students who applied" row is preferred when consistent. |
| C7 | factor rows ("Rigor of secondary school record", …) under Very Important / Important / Considered / Not Considered | header is often wrapped over several rows |
| C8 | "SAT or ACT" row under the policy grid | 2025-26 headings: "Required to be considered for admission", "Required for some", "Recommended", "Not required for admission, but considered if submitted", "Not considered for admission, even if submitted"; older: Require / Recommend / Require for Some / Consider if Submitted / Not Used |
| C9 | "Submitting SAT/ACT Scores"; "SAT Evidence-Based Reading and Writing", "SAT Math", "ACT Composite" rows (25th / 50th / 75th) | |
| C11 | "Percent who had GPA of 4.0", "… between 3.75 and 3.99" … "below 1.0" | current template has 3 columns (submitted scores / did not submit / **all enrolled**); only the "all" column is used |
| C12 | "Average high school GPA of all degree-seeking, first-time, first-year students who submitted GPA" | |
| C21 | "Does your institution offer an early decision plan…", "Number of early decision applications received…", "Number of applicants admitted under early decision plan" | |
| C22 | "…nonbinding early action plan…" (+ EA counts when a school reports them) | |
| E1 | "Study abroad" checkbox | |
| F1 | "Percent of {men\|males} who join fraternities", "Percent of {women\|females} who join sororities", "Percent who live in college-owned, -operated, or -affiliated housing" | **Undergraduates** column only |
| B22 | retention percentage | |
| B10-B11 | "Six-year graduation rate for {year} cohort" (Total column, most recent cohort) | |

### Sanity checks (values that fail are `PARSE_FAILED`, never shown)

- percentages 0–100; GPA bins sum to 95–105 %; admits ≤ applicants (overall, per gender, ED);
- men's and women's admit rates may not differ by more than 3× (catches a mistyped count — seen in a
  real 2025-26 filing that listed 180,508 women applicants);
- a CDS applicant total that differs from IPEDS by more than 1.5× is replaced by IPEDS (aggregate);
- a single F1 value is only used when its column can be identified; a 3-column C11 with only some
  columns filled is reported as not reported rather than guessed.

## 4. Field map as implemented (source priority, first OK wins)

| App field | Order |
|---|---|
| name, city, state, zip, website, locale, setting | IPEDS → Scorecard |
| address, phone | IPEDS |
| applicants/admits (total, men, women, another) | CDS C1 → IPEDS |
| acceptance rate | admitted ÷ applicants (same source) → Scorecard |
| ED/EA offered, counts, rates | CDS C21/C22 |
| RD applicants/admitted/rate | derived (total − ED − EA), labeled *Estimated* |
| average GPA, GPA distribution | CDS C12, C11 |
| SAT/ACT 25th/75th, % submitting | **CDS C9 → IPEDS → Scorecard** (see changelog) |
| test policy | CDS C8 → IPEDS → Scorecard |
| % fraternity / sorority, % in college housing | CDS F1 |
| undergraduate size | Scorecard → IPEDS |
| athletic association | IPEDS (NCAA / NAIA membership) |
| study abroad | CDS E1 → IPEDS |
| retention, 6-year graduation | CDS B22 / B11 → IPEDS → Scorecard |
| admission factors | CDS C7 |

## 5. Sites that are link-outs only

Niche, Peterson's, College Board BigFuture and College Transitions are never fetched. Buttons open
the registry's link if one is set, otherwise a web search limited to that site, in the system browser.
