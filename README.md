# CodeChef Contest Performance Reporting System

A completely free, open-source tool that turns a CodeChef contest's public
ranklist into a professional Excel report for a teacher/admin — one row per
student, with rank, problems solved, score, rating before/after, rating
change, and participation status. Built with Python 3, `requests`, and
`openpyxl`. Runs on your own laptop or for free on GitHub Actions.

---

## Table of Contents

1. [What this project does](#1-what-this-project-does)
2. [Features](#2-features)
3. [Requirements](#3-requirements)
4. [Installation](#4-installation)
5. [Folder structure](#5-folder-structure)
6. [Creating students.csv](#6-creating-studentscsv)
7. [Running locally](#7-running-locally)
8. [Running with a contest URL](#8-running-with-a-contest-url)
9. [Generating the Excel report](#9-generating-the-excel-report)
10. [Email configuration](#10-email-configuration)
11. [Gmail App Password setup](#11-gmail-app-password-setup)
12. [GitHub repository setup](#12-github-repository-setup)
13. [GitHub Secrets](#13-github-secrets)
14. [GitHub Actions setup](#14-github-actions-setup)
15. [Troubleshooting](#15-troubleshooting)
16. [CodeChef data limitations](#16-codechef-data-limitations)
17. [Security considerations](#17-security-considerations)
18. [How to run this in 5 minutes](#18-how-to-run-this-in-5-minutes)

---

## 1. What this project does

You give it:
* a CSV of your students' names and CodeChef usernames, and
* a CodeChef contest code or URL,

and it produces `reports/CodeChef_<CONTEST_CODE>_Report.xlsx`, a formatted
workbook you can email straight to a teacher, containing:

* **Contest Report** — rank, which division/contest code they were found
  in, problems solved, score, rating before/after, rating change, and
  participation status per student, with a summary at the top.
* **Problem Details** — a per-problem solved/not-solved grid (best-effort;
  see [limitations](#16-codechef-data-limitations)).
* **Not Participated** — students who didn't show up in the ranklist.
* **Contest Info** — contest name/code/URL, generation time, and headcounts.
* **Students** — the original roster, for reference.

It can also email that file automatically, and can run on a schedule for
free using GitHub Actions.

## 2. Features

* Accepts a bare contest code (`STARTERS200`) or a full URL
  (`https://www.codechef.com/STARTERS200`).
* Validates `students.csv`, normalizes usernames, detects duplicates, and
  clearly reports anything invalid.
* Never invents data: ratings that aren't available yet show as
  **"Pending"**, not a guess.
* Professional formatting: bold headers, frozen header row, autosized
  columns, filters, conditional colour-scale on rating change, highlighted
  non-participant rows.
* Clear, human-readable errors for every failure mode listed in the spec
  (bad contest code, contest not ended, network down, bad CSV, etc.) — see
  `exceptions.py`.
* Rotating log file under `logs/`.
* Optional email delivery via Gmail SMTP (or any SMTP server).
* Ready-made GitHub Actions workflow for manual or scheduled runs.
* Unit tests using mock data — no live contest required to run the test suite.

## 3. Requirements

* Python 3.9+
* Free GitHub account (only if you want automation)
* Free Gmail account (only if you want automatic emailing)
* No paid services of any kind.

## 4. Installation

```bash
git clone <your-fork-url> codechef-contest-report
cd codechef-contest-report
python3 -m venv .venv
source .venv/bin/activate        # On Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## 5. Folder structure

```
codechef-contest-report/
│
├── main.py              # CLI entry point
├── config.py            # all settings; secrets come from env vars only
├── codechef.py          # ALL CodeChef-specific fetching/parsing lives here
├── matching.py          # student <-> ranking matching logic
├── excel_report.py      # builds the formatted .xlsx report
├── email_report.py      # optional email delivery
├── utils.py             # logging, CSV loading, username normalization
├── exceptions.py        # shared custom exception types
├── students.csv         # your student roster (Name,Username; optional Register Number,Department,Section)
├── requirements.txt
├── .gitignore
├── README.md
│
├── reports/             # generated .xlsx files land here (git-ignored)
├── logs/                # rotating log files (git-ignored)
├── tests/               # unit tests (all use mock data)
│
└── .github/workflows/
    └── contest_report.yml
```

## 6. Creating students.csv

The required columns are still `Name` and `Username`. For the attendance-style Excel format, you can also add these optional columns:

```csv
Name,Username,Register Number,Department,Section
Rahul,rahul123,711524BCS001,CSE,B
Priya,priya07,711524BCS002,CSE,B
```

If the optional columns are not present, the report leaves those cells blank instead of inventing student details.

The first `Contest Report` sheet is formatted as:
`S.No | Register Number | Name of the student | Department | Section | DATE | Total Problems solved | Global Rank | Contest Rating | Div 1, Div 2, Div 3, Div 4 | ATTENDED Yes/No | IF NO Reason`


Two required columns, exactly named `Name` and `Username`:

```csv
Name,Username
Rahul,rahul123
Priya,priya07
Arun,arun22
Karthik,karthik123
```

Rules the loader enforces:
* Both columns must be present (any extra columns are ignored).
* Rows missing a name or username are skipped with a warning in the log.
* Usernames are matched case-insensitively and with a leading `@` stripped.
* If two students share the same CodeChef username, both are flagged with
  `(Duplicate username in students.csv)` in the report rather than silently
  merged or dropped.

## 7. Running locally

```bash
python main.py --contest STARTERS200
```

Options:

```bash
python main.py --contest STARTERS200 --students-csv my_class.csv
python main.py --contest STARTERS200 --output-dir /tmp/reports
python main.py --contest STARTERS200 --rankings-csv exported_ranklist.csv
python main.py --contest STARTERS200 --send-email
python main.py --contest STARTERS200 --no-email
python main.py --help
```

## 8. Running with a contest URL

Either of these work identically:

```bash
python main.py --contest STARTERS200
python main.py --contest https://www.codechef.com/STARTERS200
```

The tool extracts the contest code from the URL itself — see
`codechef.parse_contest_input()`.

### Importing a ranklist CSV (recommended)

CodeChef may reject automated requests to its web rankings endpoint. To create
a report reliably, export the ranklist to a UTF-8 CSV and run:

```bash
python main.py --contest STARTERS200 --rankings-csv exported_ranklist.csv
```

The CSV needs one username column named `Username`, `CodeChef Username`,
`Handle`, or `Code`. `Rank`, `Name`, `Score`, `Problems Solved`, `Rating`, and
`Rating Change` are optional and are included when present.

### Automatic browser fetching on Windows

With no `--rankings-csv` argument, the program opens the locally installed
Google Chrome browser, searches the CodeChef contest ranklist for each username
in `students.csv`, and builds the report automatically. Install the browser
component once after installing Python dependencies:

```bash
pip install -r requirements.txt
python -m playwright install chrome
```

Then run (and leave the short-lived Chrome window alone while it works):

```bash
python main.py --contest START253C --send-email
```

On Windows you can also double-click/use `run_report.bat START253C`; it runs the same report command and sends the Excel file when SMTP settings are configured.

The public ranklist provides rank and score. The browser fetcher also watches the JSON data requested by the current public ranklist page, so it is not tied to the old search-box UI. Ratings may not
be available there immediately after the contest; those cells will read
`Pending` until CodeChef publishes the relevant information.

## 9. Generating the Excel report

Just running `main.py` generates it — there's no separate step. The file
appears at:

```
reports/CodeChef_<CONTEST_CODE>_Report.xlsx
```

If rating-after isn't available yet (CodeChef hasn't finished
recalculating ratings after the contest), the cell shows **"Pending"**.
Re-run the tool later and it will pick up the final rating once CodeChef
publishes it.

## 10. Email configuration

Set three environment variables (locally, in a `.env` file you keep out of
git, or as GitHub Secrets for automation):

```bash
export SMTP_EMAIL="your.gmail.address@gmail.com"
export SMTP_PASSWORD="your-16-character-app-password"
export TEACHER_EMAIL="teacher@example.com"        # comma-separate for multiple recipients
```

If any of these are missing, the tool simply skips the email step — the
Excel report is still generated locally either way. Email is never
required.

## 11. Gmail App Password setup

Gmail no longer accepts your normal account password for SMTP. You need an
**App Password** (this is free, and does not require a paid Google
Workspace account):

1. Turn on 2-Step Verification: https://myaccount.google.com/signinoptions/two-step-verification
2. Go to https://myaccount.google.com/apppasswords
3. Create a new app password (name it e.g. "CodeChef Report").
4. Google shows you a 16-character password — copy it.
5. Use that value as `SMTP_PASSWORD` (not your normal Gmail password).

Never put this value in your source code — environment variables or
GitHub Secrets only.

## 12. GitHub repository setup

```bash
cd codechef-contest-report
git init
git add .
git commit -m "Initial commit: CodeChef contest reporting system"
git branch -M main
git remote add origin https://github.com/<your-username>/<your-repo>.git
git push -u origin main
```

`.gitignore` already excludes `.env`, generated `.xlsx` reports, and log
files, so you won't accidentally commit secrets or generated output.

## 13. GitHub Secrets

In your repo: **Settings → Secrets and variables → Actions → New repository secret**.
Add:

| Name             | Value                                   |
|------------------|------------------------------------------|
| `SMTP_EMAIL`     | your Gmail address                       |
| `SMTP_PASSWORD`  | the Gmail App Password from step 11      |
| `TEACHER_EMAIL`  | recipient email(s), comma-separated      |

## 14. GitHub Actions setup

The workflow is already at `.github/workflows/contest_report.yml`. To run
it manually:

1. Go to the **Actions** tab of your repo.
2. Select **"CodeChef Contest Report"**.
3. Click **"Run workflow"**, type the contest code or URL and the
   repository-relative path to an exported rankings CSV, then run.
4. Download the generated `.xlsx` from the workflow run's **Artifacts**
   section (it's also emailed if you configured Secrets).

**Limitations to know about (free tier):**
* GitHub Actions is free for public repositories with generous monthly
  minutes; private repositories get a smaller free monthly allowance.
* Scheduled runs are intentionally disabled to prevent repeated failed runs
  and duplicate report emails. Trigger the workflow manually after the contest
  ends and, where needed, provide an exported rankings CSV.

## 15. Troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| `students.csv not found` | Check `--students-csv` path, or that the file is in the project root. |
| `students.csv is missing required column(s)` | Header row must contain exactly `Name` and `Username`. |
| `CodeChef reports contest '...' was not found` | Check the contest code/URL for typos. |
| `CodeChef reports contest '...' has not ended yet` | Wait until the contest finishes, then re-run. |
| `CodeChef returned no ranking rows` | Contest may have had 0 participants, or the code is wrong. |
| `CodeChef did not return valid JSON...` | CodeChef's website structure may have changed — see `codechef.py`; this is the one file that should need updating. |
| Rating shows `Pending` | CodeChef hasn't finished re-rating yet. Re-run the tool later. |
| Email says "authentication failed" | You're using your normal Gmail password instead of an App Password — see section 11. |
| No email sent, no error shown | Email is optional and silently skipped if `SMTP_EMAIL`/`SMTP_PASSWORD`/`TEACHER_EMAIL` aren't all set — check `logs/contest_report.log`. |

Every run writes detailed logs to `logs/contest_report.log` (rotated
automatically) — check there first.

## 16. CodeChef data limitations

CodeChef does not publish an official, stable, documented public API for
contest results. This project reads the same JSON endpoint that
`https://www.codechef.com/rankings/<CONTEST_CODE>` itself calls in your
browser to render the public ranklist page — a public, unauthenticated,
read-only endpoint for contests whose ranklists are already publicly
visible. It does **not** log in, use any account's cookies, or attempt to
bypass CAPTCHAs, rate limits, or private/institution-restricted ranklists.
All of this logic is isolated in `codechef.py` so it's the only file that
should ever need updating if CodeChef changes its website.

Known limitations, by design:

1. **Contest metadata** (official name, start/end dates) isn't reliably
   present in this endpoint. The report shows "Unknown" rather than a
   guess where CodeChef doesn't provide it.
2. **Per-problem solve grid** (Problem A/B/C... columns) is not exposed by
   this endpoint. Building a real per-problem grid would require one extra
   request per student per problem via each student's individual
   submission page — slow, fragile at class/school scale, and easy to
   mistake for abusive scraping, so it is **off by default**
   (`codechef.fetch_problem_wise_status()` is a documented, opt-in stub).
   The report instead shows the total "Problems Solved" count, which *is*
   reliably available, and marks individual problem columns "Not
   available."
3. **Rating after contest** can take time to appear after a contest ends.
   If it's not ready yet, the report shows `Pending` and never invents a
   number — just re-run the tool later.

If CodeChef changes its ranklist JSON structure, this project fails loudly
with a `CodeChefStructureChangedError` rather than silently producing wrong
data — check `codechef.py`'s `_parse_ranking_row()` first.

## 17. Security considerations

* Secrets (`SMTP_PASSWORD`, etc.) are **only** ever read from environment
  variables / GitHub Secrets — never hard-coded, never logged.
* `.gitignore` excludes `.env`, generated reports, and log files.
* This project never attempts to bypass CodeChef authentication, CAPTCHAs,
  or rate limits, and only reads data that is already publicly visible on
  the ranklist page.
* A politeness delay (`REQUEST_DELAY_SECONDS`, default 1s) is applied
  between paginated requests to avoid hammering CodeChef's servers.
* Logging code is written to never include credentials in log lines —
  review any change to `email_report.py` / `config.py` with this in mind.

---

## 18. How to run this in 5 minutes

```bash
# 1. Get the code
git clone <your-fork-url> codechef-contest-report
cd codechef-contest-report

# 2. Install dependencies
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 3. Edit students.csv with your class's real names & CodeChef usernames

# 4. Run it (use a contest that has already ended!)
python main.py --contest STARTERS200

# 5. Open the file it just created
open reports/CodeChef_STARTERS200_Report.xlsx     # macOS
# or just double-click it in your file explorer
```

That's it — no server, no paid services, no signup beyond your existing
free GitHub/Gmail accounts.


## Important: CodeChef ranklist fetch behavior

The browser fetcher now treats an empty match as a **data-fetch failure**, not as proof that students did not participate. This prevents a CodeChef UI/API change from generating a report that incorrectly marks the whole class absent.

For a contest such as `START253C`, run:

```powershell
python main.py --contest https://www.codechef.com/START253C --no-email
```

If CodeChef changes its ranking page again and no roster usernames can be matched, the program stops with a clear error. It does not create a misleading participation report.

If CodeChef provides an exported ranking CSV, you can use it as a reliable fallback:

```powershell
python main.py --contest START253C --rankings-csv path\to\rankings.csv --send-email
```

The Gmail settings belong in `.env`; do not type `SMTP_EMAIL=...` as a PowerShell command. Copy `.env.example` to `.env` and fill in your values.


### No ranking data behavior
If the CodeChef ranking page returns no usable ranking rows (including an unavailable rankings page), the report treats the roster students as absent for that run. This is intentional: no ranking data means no student match. Network/configuration failures should still be reviewed in the log.


### Current CodeChef ranking search
The browser fetcher's **primary** data source is the CodeChef rankings page
(`https://www.codechef.com/rankings/<code>`) opened in Chrome through
Playwright. It observes the JSON request made by that page, which avoids the
HTTP 403 that can occur with a direct `requests` call. For divisioned
contests, each username is searched in Division 4 -> 3 -> 2 -> 1 and the
search stops immediately when that username is found. One browser/page is
reused for the whole roster run.


### Rating
For `--rating-type codechef`, the report uses the normal CodeChef rating fields.
For `--rating-type dsa`, the same browser ranklist workflow is used for the
DSA contest code (for example `DSAMONDAY018`), and the report uses the DSA
rating fields. The two rating systems remain separate. If CodeChef has not
published the relevant rating yet, the report shows `Pending`.

## Current implementation

- **Multi-division contests use first-match searching.** CodeChef
  Starters-style contests split entrants into several divisions (Div
  1-4), each with its **own contest code and its own ranklist**. The browser
  fetcher searches each username in `D`, then `C`, then `B`, then `A`, and
  stops immediately when the username is found. A username found in Div 4 is
  never searched again in Div 3/2/1. The Contest Report sheet shows the
  **Division/Contest** where the username was found.
  division each student's row came from.
- **"Problems Solved" was showing blank for everyone.** CodeChef's JSON
  ranklist endpoint (the primary, fast data source) doesn't include a
  problems-solved count at all -- only the rendered ranklist table does, as
  per-problem score cells. For any matched student still missing that count,
  the fetcher now looks up just their row via CodeChef's search URL to
  recover it, instead of only doing that for students who weren't found in
  the JSON data at all.
- **"Rating Before"/"Rating Change" was blank for most students.** The
  per-student CodeChef profile-page lookup that supplies these fields had no
  pause between requests, so firing off many profile-page loads back-to-back
  was getting most of them silently rate-limited/blocked after the first
  few succeeded. A politeness delay (`REQUEST_DELAY_SECONDS`) is now applied
  between each profile-page and each per-student search lookup.

## Current fixes (v13)

- **Fixed the "most of the class fails to fetch" bug.** The browser fetcher
  previously only ever requested **page 1** (the first `ITEMS_PER_PAGE`, i.e.
  top ~100 ranks) of the ranklist before relying on a per-student search
  fallback that depends on CodeChef's search UI behaving exactly as guessed.
  In a contest with hundreds/thousands of participants, a class of ~68
  students is almost always scattered well past rank 100 (see the
  `kit28csb184` example above, at rank 1751), so nearly everyone fell through
  to the unreliable fallback and came back "Did Not Participate" or
  "Username Not Found" even though they had participated.
  `codechef.py`'s `fetch_contest_rankings_browser()` now walks **every** page
  of the JSON ranklist endpoint first (`collect_all_pages_via_api`), and only
  falls back to DOM scraping / per-username search for any student still
  missing afterward — which should now be rare.

## Current fixes (v10)

- Uses the CodeChef user profile as the source of truth for contest **Rating After** and **Rating Change**.
- Derives **Rating Before = Rating After - Rating Change**.
- Correctly counts solved problems from the current ranking table layout.
- Includes verified metadata for **Starters 253 / START253C**: 26 August 2026, 8:00 PM--10:00 PM IST.
- Keeps unknown metadata as `Unknown` for contests that are not in the built-in metadata table.
- Includes `python-dotenv` in `requirements.txt` so `.env` is loaded automatically.

### Expected START253C result for kit28csb184

For the current contest data used during development, the report fields are:

- Rank: 1751
- Problems Solved: 3
- Total Score: 300
- Rating Before: 1424
- Rating After: 1435
- Rating Change: +11

Do not hard-code these student values in the program; they are shown here only as a validation example.


## v10 correctness fixes
- A failed/empty CodeChef ranking fetch can no longer be converted into a false
  report saying every student "Did Not Participate".
- Username searches allow more time for CodeChef's client-rendered ranking page
  to load.
- Added a rendered-text fallback for changed ranking-row HTML.
- If CodeChef data cannot be fetched, the program stops with a clear error so
  the teacher never receives a misleading all-absent report.

## Username / participation classification

The Excel report distinguishes roster username problems from genuine non-participation:

- **Participated**: the username appears in the contest ranklist.
- **Did Not Participate**: the username is verified as an existing CodeChef account, but it is absent from the contest ranklist. These rows are highlighted **yellow**.
- **Username Not Found**: CodeChef confirms that the roster username does not exist. These rows are highlighted **yellow** and do not count as contest non-participants.
- A single bad username never aborts report generation.

The browser performs profile verification only for roster usernames that are absent from the contest ranklist. A timeout or network failure while checking a profile is not treated as proof that the account is invalid.

## Rating type

The report supports two separate CodeChef rating systems:

- Default: `--rating-type codechef` — normal CodeChef Rating Graph.
- DSA: `--rating-type dsa` — DSA Rating Graph (`?rating=dsa-monday`).

The DSA option does not replace, modify, or mix with the normal CodeChef rating. For a Monday Munch DSA contest, run for example:

```powershell
python main.py --contest <MONDAY_MUNCH_CONTEST_CODE> --rating-type dsa --no-email
```

For normal Starters contests, keep the default:

```powershell
python main.py --contest START253C --no-email
```
