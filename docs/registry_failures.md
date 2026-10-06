# Registry candidates that did not qualify

Checked 2026-10-06 with `python -m cfa.tools.validate_registry` rules (C1 + C11/C12 + F1 must parse).
Entries here are **not** in `registry/schools.yaml`.

| School (UnitID) | Document tried | Reason |
|---|---|---|
| Dartmouth College (182670) | dartmouth.edu/oir/pdfs/cds_2025-26.pdf | C11 and C12 left blank (no GPA reported) |
| Rice University (227757) | ideas.rice.edu …/CDS_2025-26_WEBSITE_Updated_9-28-2026.pdf | C11/C12 not reported |
| Duke University (198419) | ir.provost.duke.edu …/CDS_PDF_2025-2026-…pdf | C11/C12 not reported |
| Bowdoin College (161004) | bowdoin.edu/ir/pdf/bowdoin-cds_2025-2026.pdf | C11/C12 not reported |
| Washington and Lee University (234207) | my.wlu.edu/document/2025-common-data-set | C11/C12 not reported (F1 parses: 71 % / 73 % Greek) |
| Swarthmore College (216287) | swarthmore.edu …/Swarthmore-CDS-2025-26.pdf | C11/C12 not reported |
| Baylor University (223232) | ir.web.baylor.edu …/cds-pdf-2025-2026-final.pdf | C11/C12 blank; F1 Greek rows blank |
| Texas Christian University (228875) | ir.tcu.edu …/CDS-2025-26-TCU.pdf | C11/C12 not reported |
| Lehigh University (213543) | data.lehigh.edu …/682026_CDS-2025-26_Revised_Published.pdf | C11/C12 not reported |
| Brigham Young University (230038) | data.byu.edu …/cds-2025-2026-pdf | F1 left blank |
| University of Cincinnati 2025-26 (201885) | uc.edu …/CDS 2025 2026 Clifton Final 06FEB26.pdf | C1 women applicants typed as 180,508 (fails consistency check); the 2024-25 file is used instead |
| University of Miami (135726) | irsa.miami.edu/cds2425.pdf | C1 not found (no usable text layer for that section) |
| College of William & Mary (231624) | wm.edu …/cds-2024-2025_a.pdf | file contains Section A only |
| Louisiana State University (159391) | lsu.edu/data/common-data-set/2024/… | published as one PDF per section (registry supports one file per year) |
| University of Oklahoma (207500) | ou.edu …/IRR CDS-C.pdf | published as one PDF per section |
| University of Mississippi (176017) | olemiss.box.com/… | hosted on box.com, not the school's own domain |
| Auburn University (100858) | auburn.edu/administration/ir/common-data-set/… | published as HTML pages, not PDF/XLSX |
| Clemson University (217882) | open.clemson.edu/cgi/viewcontent.cgi?… | server refuses automated downloads (HTTP 403) |
| Boston College (164924) | bc.edu …/Boston_College_CDS_2024-2025_Final.pdf | server refuses automated downloads (HTTP 406) |
| Wake Forest University (199847) | prod.wp.cdn.aws.wfu.edu …/CDS_2023-2024-1.pdf | HTTP 403; also outdated |
| University of Illinois (145637) | dmi.illinois.edu/stuenr/misc/cds_2025_2026.xlsx | URL returns an HTML page |
| Miami University (204024) | miamioh.edu/oir/data/_documents/cds/cds2024-25.xlsx | redirects to an HTML page (site moved) |
| Williams College (168342) | williams.edu …/Williams-CDS-2025-2026-V2.pdf | HTTP 403 |
