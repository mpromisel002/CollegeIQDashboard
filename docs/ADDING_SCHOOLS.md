# Adding schools to the registry

The registry (`registry/schools.yaml`) holds pointers only: a school's IPEDS UnitID and the URL of its
own Common Data Set. Target: 100–150 schools.

Because this repository is private, the app cannot read the file from here. When a change to
`registry/schools.yaml` lands on `main`, `.github/workflows/registry-sync.yml` validates it and copies
it to the public repo
[`mpromisel002/mpromisel002-CollegeIQDashboard-registry`](https://github.com/mpromisel002/mpromisel002-CollegeIQDashboard-registry),
which every installed copy downloads at startup. A fix therefore reaches users without a rebuild.
Always edit the file here, never in the public repo. If the download fails, the app uses the copy
bundled into the exe and shows a banner.

### One-time setup

1. Create the **public** repository `mpromisel002/mpromisel002-CollegeIQDashboard-registry`.
2. Create a fine-grained personal access token (GitHub → Settings → Developer settings) limited to
   that one repository with **Contents: Read and write**.
3. In this repository: Settings → Secrets and variables → Actions → new secret
   `REGISTRY_SYNC_TOKEN` with that token.
4. Run *Actions → Registry sync → Run workflow* once to publish the current list.

## Steps

1. **Find the UnitID.** Search the school on <https://nces.ed.gov/collegenavigator/> — the UnitID is
   the `id=` value in the URL — or check `https://educationdata.urban.org/api/v1/college-university/ipeds/directory/2023/?unitid=NNNNNN`
   returns the right name. Use the main campus.
2. **Find the CDS.** On the school's own `.edu` site (usually Institutional Research), copy the direct
   link to the newest *complete* CDS file. Prefer a single file with all sections. Skip third-party
   mirrors and files split by section.
3. **Add an entry** (newest year first is not required; the app picks the latest `year`):

   ```yaml
   - unitid: 100751
     name: The University of Alabama
     cds:
       - year: "2025-2026"
         url: https://oira.ua.edu/.../CDS%202025-26%20FINAL.pdf
         format: pdf        # pdf | xlsx
     links:                 # optional; opened in the browser only
       niche: https://www.niche.com/colleges/the-university-of-alabama/
   ```

4. **Validate:** `python -m cfa.tools.validate_registry`. A school must show `PASS`
   (C1 parses and C11 or C12 parses; F1 is optional). If it fails, do not commit it — add it
   to `docs/registry_failures.md` with the reason.
5. Open a PR. CI checks the YAML schema; the weekly live smoke run re-validates every link.

## Yearly update

Each fall, schools publish a new CDS. Add the new `year` entry above the old one (or replace the URL),
run the validator, and push. Old entries can stay as a record but only the latest year is used.

## Common problems

- *"The link now returns a web page"* — the file moved; find the new URL.
- *"PDF has no usable text layer"* — a scanned image; it cannot be read reliably. Look for an XLSX.
- *C11/C12 not reported* — many selective private colleges do not publish GPA; such schools do not
  meet the registry bar.
- Some fonts extract as `(cid:NN)` garbage; those sections show "Not reported".

## Finding CDS documents in bulk (`find_cds`)

`python -m cfa.tools.find_cds` proposes registry entries for colleges the registry lacks:

1. `find_cds list --states PA,NY --out todo.json` lists the four-year colleges (IPEDS directory)
   that are not on the registry, with each college's own web domain.
2. Add a `urls` list to each entry: pages or files on that college's own site that look like its
   CDS. Sources used so far: a web search limited to the college's domain (one query per college,
   "<name> common data set"), and the `source_url`s in collegedata.fyi's public document index
   (`/rest/v1/cds_manifest`). Never scrape search-engine result pages.
3. `find_cds check --input todo.json --out found.yaml --report report.json` opens those pages
   (robots.txt and HTTP 403 respected; Google Drive/SharePoint/Box refused), finds CDS files and
   per-year CDS pages, reads each document's year, and keeps the newest document that passes the
   registry rule. It rejects a document whose C1 applicant count is more than 1.5x off IPEDS for
   that college (usually another campus's CDS) and never assigns one document to two colleges.
4. Review `found.yaml` (names vs file names: branch campuses and online divisions must not get the
   main campus's file), paste it under `schools:`, and run `validate_registry` on the new entries.

As of October 2026 every four-year college in IPEDS has been checked once this way; 333 schools
qualify. Most others publish no CDS, publish one without GPA (C11/C12), host it off-site, block
automated downloads, or use a layout the parser can't read.
