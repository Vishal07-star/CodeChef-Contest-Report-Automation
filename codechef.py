"""
codechef.py
-----------
ALL CodeChef-specific logic lives in this one file, on purpose. If CodeChef
changes its website tomorrow, this is the only file that should need edits.

============================================================================
IMPORTANT -- read this before relying on this module (see README section
"CodeChef data limitations" for the full explanation):
============================================================================
CodeChef does not publish an official, stable, documented public API for
contest results. The normal report path uses a real Chrome browser through
Playwright and opens the public ranklist page:

    https://www.codechef.com/rankings/<CONTEST_CODE>

The browser observes the JSON request made by that page and parses the same
ranklist data. This is important because a direct unauthenticated HTTP
request can receive HTTP 403 even when the public ranklist works in Chrome.
The module:
  * does NOT log in or use cookies/tokens tied to any account,
  * does NOT attempt to bypass CAPTCHAs, rate limits, or private/institution
    -restricted ranklists,
  * reuses one browser/page for the whole roster run,
  * applies a politeness delay between searches,
  * fails loudly and clearly rather than silently guessing when the browser
    cannot obtain usable ranklist data.

The older direct JSON function is retained for explicit CSV/API-style use,
but the default ``main.py`` path uses the browser fetcher.

Known limitations of this data source (please read):
  1. Contest metadata (official contest name, start/end timestamps) is NOT
     reliably present in the rankings endpoint. This module extracts what
     it can and otherwise leaves fields as "Unknown" -- it never invents
     values.
  2. A per-problem, per-student solved/not-solved GRID (Problem A, B, C...)
     is NOT exposed by this endpoint. CodeChef only exposes that level of
     detail via each student's individual submission-status page, fetching
     which for every student would mean one extra HTTP request per student
     per problem -- slow, fragile, and easy to mistake for abusive
     scraping. This module therefore does NOT attempt that by default.
     `fetch_problem_wise_status()` is provided as an OPT-IN, best-effort
     function (disabled unless you explicitly call it / pass
     --with-problem-details) that is clearly documented as slow and
     unreliable. Excel_report.py fills the "Problem Details" sheet with the
     total problems-solved count (which IS available) and marks individual
     problem columns as unavailable unless that opt-in data was supplied.
  3. "Rating after contest" reflects the rating CodeChef shows at the time
     you run this tool. CodeChef often takes some time after a contest ends
     to finish recalculating ratings. If a student's rating looks
     unchanged right after the contest, their entry may simply not be
     rerated yet -- rerun the tool later. This module never invents a
     rating value; if it cannot compute one it reports "Pending".
============================================================================
"""

from __future__ import annotations

import re
import time
import csv
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse, urlencode

import requests

import config
from exceptions import (
    CodeChefNetworkError,
    CodeChefStructureChangedError,
    ContestNotEndedError,
    ContestNotFoundError,
    InvalidContestInputError,
    RankingsUnavailableError,
    RankingsFileError,
    BrowserFetchError,
)
from utils import logger, normalize_username

CONTEST_CODE_RE = re.compile(r"^[A-Za-z0-9_]{2,20}$")


# ---------------------------------------------------------------------------
# Contest input parsing (accepts either a bare code or a full URL)
# ---------------------------------------------------------------------------
def parse_contest_input(value: str) -> str:
    """
    Accepts either a contest code ("START200") or a CodeChef contest URL
    ("https://www.codechef.com/START200", with or without trailing slash /
    query string) and returns the bare, upper-cased contest code.

    Raises InvalidContestInputError if neither shape can be recognized.
    """
    if not value or not value.strip():
        raise InvalidContestInputError("No contest code or URL was provided.")

    value = value.strip()

    if value.lower().startswith("http://") or value.lower().startswith("https://"):
        parsed = urlparse(value)
        hostname = (parsed.hostname or "").lower()
        if hostname not in {"codechef.com", "www.codechef.com"}:
            raise InvalidContestInputError(
                f"'{value}' does not look like a codechef.com URL."
            )
        path_parts = [p for p in parsed.path.split("/") if p]
        if not path_parts:
            raise InvalidContestInputError(
                f"Could not find a contest code in the URL '{value}'."
            )
        candidate = path_parts[0]
    else:
        candidate = value

    candidate = candidate.strip().upper()

    if not CONTEST_CODE_RE.match(candidate):
        raise InvalidContestInputError(
            f"'{value}' does not look like a valid CodeChef contest code or URL. "
            f"Examples of valid input: 'STARTERS200' or "
            f"'https://www.codechef.com/STARTERS200'."
        )

    return candidate


DIVISION_CODE_RE = re.compile(r"^(.*\d)([A-D])$")


def expand_division_contest_codes(contest_code: str) -> List[str]:
    """Return every sibling division contest code for a CodeChef Starters-style contest.

    CodeChef Starters (and similar recurring contests) auto-assigns each
    participant to one of several divisions based on their rating, and each
    division runs as its *own* contest with its own contest code and its own
    ranklist -- e.g. a single "Starters 253" event is really four separate
    contests, START253A/B/C/D (Div 1-4). A student roster spanning a class
    will have students spread across several of these divisions, so checking
    only the one contest code a teacher was given misses everyone placed in
    a different division.

    If ``contest_code`` ends in a single division letter A-D immediately
    after a digit (e.g. "START253D"), this returns all four sibling codes in
    A, B, C, D order. Otherwise (a contest that isn't divisioned this way,
    or an already-bare code) it returns ``[contest_code]`` unchanged.
    """
    match = DIVISION_CODE_RE.match(contest_code)
    if not match:
        return [contest_code]
    prefix = match.group(1)
    return [f"{prefix}{letter}" for letter in "ABCD"]


# ---------------------------------------------------------------------------
# Data model for a single ranking row
# ---------------------------------------------------------------------------
@dataclass
class RankingEntry:
    rank: Optional[int]
    username: str            # normalized (lowercase)
    display_name: str        # name CodeChef has on file (NOT necessarily the student's real name)
    problems_solved: Optional[int]
    total_score: Optional[float]
    rating_after: Optional[int]
    rating_change: Optional[int]
    rating_before: Optional[int]  # derived: rating_after - rating_change, when both are known
    raw: dict = field(default_factory=dict, repr=False)
    source_contest: Optional[str] = None  # which division/contest code this row was found under


def derive_problems_solved_from_score(total_score: Optional[float]) -> Optional[int]:
    """Derive solved count from the contest score without extra CodeChef requests.

    For CodeChef contests in this project, each fully solved problem contributes
    100 points, so 400 -> 4 solved, 300 -> 3, 200 -> 2, etc. Partial scores are
    rounded to the nearest problem count rather than triggering another network
    request.
    """
    if total_score is None:
        return None
    try:
        return max(0, int(round(float(total_score) / 100.0)))
    except (TypeError, ValueError):
        return None


def division_label(contest_code: Optional[str]) -> str:
    """Map STARTxxxA/B/C/D to human-readable Division 1/2/3/4."""
    code = (contest_code or "").upper()
    if code.endswith("A"):
        return "Division 1"
    if code.endswith("B"):
        return "Division 2"
    if code.endswith("C"):
        return "Division 3"
    if code.endswith("D"):
        return "Division 4"
    return code or "Unknown"


@dataclass
class ContestMetadata:
    contest_code: str
    contest_name: str = "Unknown"
    contest_url: str = ""
    start_date: str = "Unknown"
    end_date: str = "Unknown"


# ---------------------------------------------------------------------------
# HTTP layer
# ---------------------------------------------------------------------------
def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update(
        {
            "User-Agent": config.HTTP_USER_AGENT,
            "Accept": "application/json, text/plain, */*",
        }
    )
    return s


def _get_json(session: requests.Session, url: str, params: dict) -> dict:
    """
    GET a URL expecting JSON, with retries/backoff for transient network
    errors. Raises CodeChefNetworkError / ContestNotFoundError as appropriate.
    """
    last_error = None
    for attempt in range(1, config.MAX_RETRIES + 1):
        try:
            resp = session.get(url, params=params, timeout=config.REQUEST_TIMEOUT_SECONDS)
        except requests.exceptions.Timeout as exc:
            last_error = exc
            logger.warning("Timeout on attempt %d/%d for %s", attempt, config.MAX_RETRIES, url)
        except requests.exceptions.ConnectionError as exc:
            last_error = exc
            logger.warning(
                "Network/connection error on attempt %d/%d for %s: %s",
                attempt, config.MAX_RETRIES, url, exc,
            )
        else:
            if resp.status_code == 404:
                raise ContestNotFoundError(
                    f"CodeChef returned 404 for this contest. Double-check the contest "
                    f"code/URL you provided."
                )
            if resp.status_code == 429:
                logger.warning("Rate limited by CodeChef (HTTP 429). Backing off.")
                time.sleep(config.RETRY_BACKOFF_SECONDS * attempt)
                continue
            if resp.status_code >= 500:
                last_error = RuntimeError(f"HTTP {resp.status_code} from CodeChef")
                logger.warning(
                    "Server error %s on attempt %d/%d for %s",
                    resp.status_code, attempt, config.MAX_RETRIES, url,
                )
            elif resp.status_code >= 400:
                raise RankingsUnavailableError(
                    f"CodeChef rejected the rankings request (HTTP {resp.status_code}). "
                    "Use --rankings-csv with an exported ranklist, or configure a "
                    "currently supported CodeChef data source."
                )
            else:
                try:
                    return resp.json()
                except ValueError as exc:
                    raise CodeChefStructureChangedError(
                        "CodeChef did not return valid JSON where JSON was expected. "
                        "The website may have changed its ranklist format -- this "
                        "module (codechef.py) likely needs an update."
                    ) from exc

        time.sleep(config.RETRY_BACKOFF_SECONDS * attempt)

    raise CodeChefNetworkError(
        f"Could not reach CodeChef after {config.MAX_RETRIES} attempts. "
        f"Check your internet connection and try again later. "
        f"(Last error: {last_error})"
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def fetch_contest_rankings(contest_code: str) -> List[RankingEntry]:
    """
    Fetch the full (paginated) ranklist for a contest.

    Raises:
        ContestNotFoundError
        ContestNotEndedError
        RankingsUnavailableError
        CodeChefStructureChangedError
        CodeChefNetworkError
    """
    session = _session()
    all_entries: List[RankingEntry] = []
    page = 0

    while page < config.MAX_PAGES:
        url = config.CODECHEF_RANKINGS_ENDPOINT.format(contest_code=contest_code)
        params = {
            "sortBy": "rank",
            "order": "asc",
            "page": page,
            "itemsPerPage": config.ITEMS_PER_PAGE,
        }
        logger.info("Fetching rankings for %s, page %d", contest_code, page)
        data = _get_json(session, url, params)

        status = data.get("status")
        if status is not None and status != "success":
            message = str(data.get("message", "")).lower()
            if "not found" in message or "invalid" in message:
                raise ContestNotFoundError(
                    f"CodeChef reports contest '{contest_code}' was not found: "
                    f"{data.get('message')}"
                )
            if "not over" in message or "not ended" in message or "live" in message:
                raise ContestNotEndedError(
                    f"CodeChef reports contest '{contest_code}' has not ended yet: "
                    f"{data.get('message')}"
                )
            raise RankingsUnavailableError(
                f"CodeChef did not return rankings for '{contest_code}': "
                f"{data.get('message', '(no message)')}"
            )

        rows = data.get("list")
        if rows is None:
            # 'list' is the field name this endpoint has historically used.
            # If it's missing entirely, the response shape has changed.
            raise CodeChefStructureChangedError(
                "Expected a 'list' field in CodeChef's rankings response but did not "
                "find one. CodeChef may have changed its ranklist JSON format -- "
                "update codechef.py's parsing logic."
            )

        if not rows:
            break  # no more pages

        for raw in rows:
            entry = _parse_ranking_row(raw)
            if entry is not None:
                all_entries.append(entry)

        if len(rows) < config.ITEMS_PER_PAGE:
            break  # last page

        page += 1
        time.sleep(config.REQUEST_DELAY_SECONDS)

    if not all_entries:
        raise RankingsUnavailableError(
            f"CodeChef returned no ranking rows for contest '{contest_code}'. "
            f"This can happen if the contest had zero participants, the "
            f"ranklist is private/institution-restricted, or the contest "
            f"code is wrong."
        )

    logger.info("Fetched %d ranking row(s) for %s", len(all_entries), contest_code)
    return all_entries


def _division_search_codes(contest_code: str, rating_type: str = "codechef") -> List[str]:
    """Return division contest codes in the fastest first-match order.

    For a divisioned contest, CodeChef keeps separate ranklists for A/B/C/D.
    We search Division 4 first, then 3, 2, and 1.  A username is searched in
    the next division only when it was not found in the previous one.
    """
    if rating_type.lower() == "dsa":
        return [contest_code.upper()]
    match = DIVISION_CODE_RE.match(contest_code.upper())
    if not match:
        return [contest_code.upper()]
    prefix = match.group(1)
    return [f"{prefix}{letter}" for letter in "DCBA"]


def _browser_search_urls(contest_code: str, username: str) -> List[str]:
    """Build the current CodeChef rankings search URL.

    CodeChef's current contest ranklist UI is served from ``/rankings/<code>``.
    The older alternate rankings route is intentionally not used because it
    can return a 404 even though the normal rankings page works in Chrome.
    """
    params = {
        "itemsPerPage": config.ITEMS_PER_PAGE,
        "order": "asc",
        "page": 1,
        "search": username,
        "sortBy": "rank",
    }
    return [
        f"{config.CODECHEF_RANKINGS_PAGE_URL.format(contest_code=contest_code)}?{urlencode(params)}"
    ]


def _browser_search_url(contest_code: str, username: str) -> str:
    """Return the single supported CodeChef rankings search URL."""
    return _browser_search_urls(contest_code, username)[0]


def _is_rendered_ranklist_page(text: str) -> bool:
    """Identify CodeChef's actual ranklist UI, not its generic landing page."""
    return "CodeChef Ranklist" in text and "Username" in text and "Total Score" in text


def _extract_ranking_rows_from_browser_response(response_json: Any) -> List[dict]:
    """Find ranking rows in CodeChef JSON, even when nested under ``data``/``result``.

    CodeChef has changed the shape of the rankings payload over time. The
    browser page can still receive valid rank data even when it is no longer
    exposed as a top-level ``list`` field, so walk nested dictionaries/lists
    and return the first list containing recognizable ranking rows.
    """
    username_keys = {"code", "username", "user_handle", "userHandle"}
    rank_keys = {"rank", "global_rank", "contestRank", "contest_rank"}

    def is_row(value: Any) -> bool:
        if not isinstance(value, dict):
            return False
        keys = set(value)
        return bool(keys & username_keys) and bool(keys & (rank_keys | {"score", "total_score", "points"}))

    def walk(value: Any, depth: int = 0) -> Optional[List[dict]]:
        if depth > 8:
            return None
        if isinstance(value, list):
            rows = [item for item in value if is_row(item)]
            if rows:
                return rows
            for item in value:
                found = walk(item, depth + 1)
                if found:
                    return found
        elif isinstance(value, dict):
            for key in ("list", "data", "result", "results", "rankings", "rows", "items"):
                if key in value:
                    found = walk(value[key], depth + 1)
                    if found:
                        return found
            for item in value.values():
                if isinstance(item, (dict, list)):
                    found = walk(item, depth + 1)
                    if found:
                        return found
        return None

    rows = walk(response_json)
    if rows is None:
        raise CodeChefStructureChangedError(
            "Could not find recognizable ranking rows in CodeChef's browser response."
        )
    return rows


def _is_explicit_rankings_payload(payload: Any) -> bool:
    """Return true for a ranklist JSON payload, including a valid empty list."""
    if isinstance(payload, dict):
        for key in ("list", "rankings", "rows", "items", "results"):
            if key in payload and isinstance(payload[key], list):
                return True
        return any(_is_explicit_rankings_payload(value) for value in payload.values())
    if isinstance(payload, list):
        return False
    return False


def _search_usernames_first_match(
    normalized_usernames: List[str],
    search_codes: List[str],
    fetcher,
) -> List[RankingEntry]:
    """Apply the D4 -> D3 -> D2 -> D1 first-match rule to any fetcher."""
    found_entries: List[RankingEntry] = []
    unresolved: List[str] = []
    for username in normalized_usernames:
        found = None
        had_ranklist_failure = False
        for division_code in search_codes:
            try:
                found = fetcher(division_code, username)
            except BrowserFetchError as exc:
                # A division page can be unavailable or can temporarily expose a
                # different frontend/API shape. That does NOT mean the student
                # is absent from the contest. Continue with the next division.
                logger.warning(
                    "Could not read ranklist for %s while searching %s: %s. Trying next division.",
                    division_code,
                    username,
                    exc,
                )
                had_ranklist_failure = True
                found = None
            if found is not None:
                logger.info(
                    "Username %s found in %s; stopping division search for this username.",
                    username,
                    division_code,
                )
                break
        if found is not None:
            found_entries.append(found)
        elif had_ranklist_failure:
            # An unavailable/timeout ranklist cannot prove absence.  Returning
            # an empty result here would turn this technical failure into a
            # false "Did Not Participate" row in Excel.
            unresolved.append(username)
        else:
            logger.info(
                "Username %s was not found in any searched division: %s",
                username,
                ", ".join(search_codes),
            )
    if unresolved:
        raise BrowserFetchError(
            "Could not conclusively search these username(s); no attendance "
            "status was written: " + ", ".join(unresolved)
        )
    return found_entries


def fetch_contest_rankings_browser(
    contest_code: str,
    usernames: List[str],
    rating_type: str = "codechef",
) -> List[RankingEntry]:
    """Fetch only the requested students from CodeChef's real rankings UI.

    The browser opens only ``/rankings/<contest>``.  For normal contests each
    username is checked in D4 -> D3 -> D2 -> D1 order and the first match wins.
    DSA contests use only the supplied contest code and never expand into
    divisions.

    The page is searched by its real ``search`` query parameter and, if needed,
    the visible search input.  We wait for the actual username text instead of
    sleeping a fixed number of seconds.  This makes the common case much faster
    while still giving the JavaScript-rendered ranklist time to appear.
    """
    normalized_usernames: List[str] = []
    seen = set()
    for username in usernames:
        normalized = normalize_username(username)
        if normalized and normalized not in seen:
            normalized_usernames.append(normalized)
            seen.add(normalized)

    if not normalized_usernames:
        raise RankingsUnavailableError("No valid student usernames were supplied.")

    search_codes = _division_search_codes(contest_code, rating_type=rating_type)
    found_entries: List[RankingEntry] = []

    try:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise BrowserFetchError(
            "Playwright is required for browser ranklist fetching. Install it with "
            "'pip install -r requirements.txt' and then run 'python -m playwright install chrome'."
        ) from exc

    def _dom_entry(page, wanted: str, division_code: str) -> Optional[RankingEntry]:
        """Extract one exact username from the rendered rankings row."""
        selectors = (
            "tr",
            '[role="row"]',
            '[data-testid*="row"]',
        )
        row_texts: List[str] = []
        for selector in selectors:
            try:
                row_texts.extend(page.locator(selector).all_inner_texts())
            except Exception:
                continue

        # Also walk up from the exact username element. This handles the
        # current React table/card markup even if its row has no stable class.
        try:
            exact = page.get_by_text(wanted, exact=True)
            count = min(exact.count(), 10)
            for idx in range(count):
                candidates = exact.nth(idx).evaluate(
                    """el => {
                        const out = [];
                        let node = el;
                        for (let i = 0; i < 8 && node; i++, node = node.parentElement) {
                            const text = (node.innerText || '').trim();
                            if (text) out.push(text);
                        }
                        return out;
                    }"""
                )
                row_texts.extend(candidates or [])
        except Exception:
            pass

        wanted_lower = wanted.lower()
        seen_rows = set()
        for text in row_texts:
            if not text or text in seen_rows:
                continue
            seen_rows.add(text)
            lines = [line.strip() for line in text.splitlines() if line.strip()]
            flat = " ".join(lines)
            if wanted_lower not in flat.lower():
                continue

            # Prefer the compact row containing the exact username.
            tokens = flat.split()
            try:
                pos = next(i for i, token in enumerate(tokens) if token.lower() == wanted_lower)
            except StopIteration:
                continue

            rank = _to_int(tokens[pos - 1]) if pos > 0 else None
            score = None
            for token in tokens[pos + 1:]:
                candidate = _to_float(token)
                if candidate is not None:
                    score = candidate
                    break

            if rank is None or score is None:
                # Fallback for markup that joins cells oddly.
                numbers = re.findall(r"(?<![A-Za-z])\d+(?:\.\d+)?", flat)
                if numbers:
                    rank = rank if rank is not None else _to_int(numbers[0])
                    if score is None and len(numbers) >= 2:
                        score = _to_float(numbers[1])

            if rank is None and score is None:
                continue

            return RankingEntry(
                rank=rank,
                username=wanted,
                display_name=wanted,
                problems_solved=derive_problems_solved_from_score(score),
                total_score=score,
                rating_after=None,
                rating_change=None,
                rating_before=None,
                raw={"dom_text": flat},
                source_contest=division_code.upper(),
            )
        return None

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                channel="chrome",
                headless=config.BROWSER_HEADLESS,
            )
            context = browser.new_context(viewport={"width": 1440, "height": 1000})
            page = context.new_page()
            page.set_default_timeout(config.BROWSER_TIMEOUT_MS)
            try:
                # DSA contests have exactly one ranklist.  Validate it once
                # before searching every student so an unpublished/invalid
                # contest code cannot generate 67 misleading absence checks.
                if rating_type.lower() == "dsa":
                    probe_url = (
                        f"{config.CODECHEF_RANKINGS_PAGE_URL.format(contest_code=search_codes[0])}"
                        "?itemsPerPage=100&order=asc&page=1&sortBy=rank"
                    )
                    logger.info("[RANKLIST] Validating DSA ranklist: %s", probe_url)
                    try:
                        probe = page.goto(
                            probe_url,
                            wait_until="domcontentloaded",
                            timeout=max(config.BROWSER_TIMEOUT_MS, 45_000),
                        )
                        probe_text = page.locator("body").inner_text()
                    except Exception as exc:
                        raise BrowserFetchError(
                            f"Could not open DSA ranklist for {search_codes[0]}: {probe_url}"
                        ) from exc
                    if probe is None or probe.status != 200 or not _is_rendered_ranklist_page(probe_text):
                        raise BrowserFetchError(
                            f"CodeChef did not publish a usable ranklist for {search_codes[0]}. "
                            "The page returned a generic/error page, so attendance cannot be verified yet."
                        )

                def browser_fetch(division_code: str, username: str) -> Optional[RankingEntry]:
                    search_url = _browser_search_url(division_code, username)
                    wanted = normalize_username(username)
                    logger.info("Searching %s for username %s: %s", division_code, username, search_url)

                    captured_payloads: List[Any] = []
                    response_status = None

                    def on_response(response):
                        nonlocal response_status
                        if response.status != 200:
                            if response.url.rstrip('/').endswith(f"/rankings/{division_code.lower()}") or "/rankings/" in response.url.lower():
                                response_status = response.status
                            return
                        try:
                            content_type = (response.headers.get("content-type") or "").lower()
                            if "json" not in content_type and "javascript" in content_type:
                                return
                            body = response.body()
                            text = body.decode("utf-8", errors="replace")
                            import json
                            payload = json.loads(text)
                            # Keep an explicitly empty ranklist payload as
                            # evidence of absence too.  It is different from a
                            # blank HTML page or a failed network request.
                            if _is_explicit_rankings_payload(payload):
                                captured_payloads.append(payload)
                        except Exception:
                            return

                    page.on("response", on_response)
                    try:
                        # Always navigate to CodeChef's canonical filtered URL.
                        # Filling the React search widget can leave stale results
                        # after several students, which incorrectly marks an
                        # entire roster as non-participants.
                        response = None
                        last_navigation_error = None
                        # CodeChef can reset a browser connection or return a
                        # throttled incomplete page. Retry the same direct,
                        # filtered URL; never fall back to the stale in-page
                        # search widget.
                        for attempt in range(1, 4):
                            try:
                                response = page.goto(
                                    search_url,
                                    wait_until="domcontentloaded",
                                    timeout=max(config.BROWSER_TIMEOUT_MS, 45_000),
                                )
                                break
                            except (PlaywrightTimeoutError, PlaywrightError) as exc:
                                last_navigation_error = exc
                                logger.warning(
                                    "[RANKLIST] Navigation failed for %s (attempt %d/3): %s | %s",
                                    username, attempt, exc, search_url,
                                )
                                if attempt < 3:
                                    time.sleep(5 * attempt)
                        if response is None:
                            raise BrowserFetchError(
                                f"Could not open filtered ranklist after 3 attempts: {search_url}"
                            ) from last_navigation_error
                        status = response.status
                        if status >= 400:
                            raise BrowserFetchError(
                                f"CodeChef rankings page returned HTTP {status} for {division_code}."
                            )

                        try:
                            page.wait_for_function(
                                """username => document.body && document.body.innerText.toLowerCase().includes(username)""",
                                arg=wanted,
                                timeout=min(config.BROWSER_TIMEOUT_MS, 2_500),
                            )
                        except PlaywrightTimeoutError:
                            pass

                        # The ranklist's network row is authoritative for rank and
                        # score.  Do this before text scraping: rendered search
                        # containers can include pagination/count numbers that look
                        # like a score (the cause of incorrect zero solved counts).
                        for payload in captured_payloads:
                            try:
                                rows = _extract_ranking_rows_from_browser_response(payload)
                            except CodeChefStructureChangedError:
                                # A recognised empty list has no rows but is
                                # still a verified ranklist response.
                                continue
                            for raw in rows:
                                entry = _parse_ranking_row(raw)
                                if entry.username == wanted:
                                    entry.source_contest = division_code.upper()
                                    return entry

                        # Keep DOM extraction only as a last resort when the UI did
                        # not expose its JSON response to the browser listener.
                        entry = _dom_entry(page, wanted, division_code)
                        if entry is not None:
                            return entry

                        # CodeChef's empty filtered ranklists often render an
                        # otherwise normal table without a "No results" label
                        # or an empty JSON response.  A fully rendered ranklist
                        # header is therefore sufficient evidence of absence;
                        # blank/throttled/incomplete pages still fail above.
                        body_text = page.locator("body").inner_text()
                        rendered_ranklist = _is_rendered_ranklist_page(body_text)
                        if status == 200 and response_status not in {403, 404, 429} and (
                            bool(captured_payloads) or rendered_ranklist
                        ):
                            return None

                        raise BrowserFetchError(
                            f"Could not confirm an exact result or a verified empty result for {username} in {division_code}."
                        )
                    except PlaywrightTimeoutError as exc:
                        raise BrowserFetchError(
                            f"Timed out while opening CodeChef rankings {search_url}"
                        ) from exc
                    finally:
                        page.remove_listener("response", on_response)

                found_entries.extend(
                    _search_usernames_first_match(
                        normalized_usernames,
                        search_codes,
                        browser_fetch,
                    )
                )
            finally:
                context.close()
                browser.close()
    except BrowserFetchError:
        raise
    except Exception as exc:
        raise BrowserFetchError(f"Browser ranklist fetching failed: {exc}") from exc

    if not found_entries:
        # A successfully loaded ranklist with no roster matches is a valid
        # attendance result, not a fatal data-source error.  main.py will
        # verify missing usernames and mark valid accounts "Did Not
        # Participate" (or "Username Not Found" for confirmed invalid ones).
        logger.info(
            "None of the supplied usernames appeared in the searched ranklists: %s. "
            "Continuing with an empty participant list.",
            ", ".join(search_codes),
        )
        return []

    logger.info(
        "Found %d of %d supplied username(s) using browser first-match division searching.",
        len(found_entries),
        len(normalized_usernames),
    )
    # Ratings are enriched by the report workflow after all ranklist matches
    # are collected.  Keeping ranklist discovery separate guarantees that the
    # profile pass sees every participant, not only early browser matches.
    return found_entries


def enrich_profile_ratings_browser(
    entries: List[RankingEntry], rating_type: str = "codechef",
) -> List[RankingEntry]:
    """Replace ranklist ratings with current ratings from rendered profiles.

    One browser, context, and page are reused for the whole roster.  A profile
    failure is isolated to that student: its report value stays ``Pending``.
    """
    rating_type = (rating_type or "codechef").strip().lower()
    if rating_type not in {"codechef", "dsa"}:
        raise ValueError("rating_type must be 'codechef' or 'dsa'")

    for entry in entries:
        # Ranklist ratings are intentionally discarded, even if present.
        entry.rating_after = entry.rating_change = entry.rating_before = None

    if not entries:
        return entries
    logger.info(
        "[PROFILE] Checking %d profile(s) for ranklist participant(s).",
        len(entries),
    )
    try:
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        from playwright.sync_api import sync_playwright
    except ImportError:
        logger.warning("[PROFILE] Playwright is unavailable; profile ratings will remain Pending.")
        return entries

    suffix = "?rating=dsa-monday" if rating_type == "dsa" else ""
    label = "DSA" if rating_type == "dsa" else "CodeChef"

    def set_from_text(entry: RankingEntry, text: str) -> bool:
        rating, change = _parse_profile_rating(text, "", rating_type=rating_type)
        if rating is None:
            return False
        entry.rating_after = rating
        entry.rating_change = change
        entry.rating_before = rating - change if change is not None else None
        return True

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel="chrome", headless=config.BROWSER_HEADLESS)
            context = browser.new_context(viewport={"width": 1440, "height": 1000})
            page = context.new_page()
            page.set_default_timeout(config.BROWSER_TIMEOUT_MS)
            try:
                for entry in entries:
                    profile_url = f"{config.CODECHEF_BASE_URL}/users/{entry.username}{suffix}"
                    logger.info("[PROFILE] Checking %s rating: %s", label, profile_url)
                    for attempt in range(1, 3):
                        try:
                            response = page.goto(
                                profile_url,
                                wait_until="domcontentloaded",
                                timeout=max(config.BROWSER_TIMEOUT_MS, 45_000),
                            )
                            if response is not None and response.status >= 400:
                                raise RuntimeError(f"profile returned HTTP {response.status}")
                            # The responsive page header lists both labels. Read
                            # the active rendered card, not the whole page.
                            card_selector = "#rating-block-dsa-monday" if rating_type == "dsa" else "#rating-block-all"
                            card = page.locator(card_selector)
                            card.wait_for(state="visible", timeout=10_000)
                            if set_from_text(entry, card.inner_text()):
                                logger.info("[PROFILE] %s rating found: %s", label, entry.rating_after)
                                break
                        except Exception as exc:
                            logger.warning(
                                "[PROFILE] Browser check failed for %s (attempt %d/2): %s",
                                entry.username, attempt, exc,
                            )
                            # In particular, honor CodeChef's HTTP 429 rate
                            # limit before retrying this same profile.
                            if attempt < 2:
                                time.sleep(max(config.PROFILE_REQUEST_DELAY_SECONDS, 15.0))
                    if entry.rating_after is not None:
                        time.sleep(config.PROFILE_REQUEST_DELAY_SECONDS)
                        continue

                    # Server-rendered content is a fallback only; normal operation
                    # reads the JavaScript-rendered page above.
                    try:
                        fallback = _session().get(profile_url, timeout=min(config.REQUEST_TIMEOUT_SECONDS, 8))
                        if fallback.status_code == 200 and set_from_text(entry, fallback.text):
                            logger.info("[PROFILE] %s rating found via fallback: %s", label, entry.rating_after)
                            continue
                    except requests.RequestException as exc:
                        logger.warning("[PROFILE] Fallback failed for %s: %s", entry.username, exc)
                    logger.warning("[PROFILE] Rating not found for %s", entry.username)
                    logger.warning("[PROFILE] URL: %s", profile_url)
                    time.sleep(config.PROFILE_REQUEST_DELAY_SECONDS)
            finally:
                context.close()
                browser.close()
    except Exception as exc:
        logger.warning("[PROFILE] Could not start profile browser: %s", exc)
    return entries


def find_invalid_usernames_browser(usernames: List[str]) -> set[str]:
    """Confirm which missing roster usernames are not CodeChef accounts.

    A username is considered valid when its public profile responds with HTTP
    200. Only clear 404/nonexistent responses are classified as invalid; other
    network failures are left unclassified so they can remain "Did Not
    Participate" rather than being incorrectly labeled.
    """
    invalid = set()
    session = _session()
    for username in usernames:
        normalized = normalize_username(username)
        if not normalized:
            continue
        url = f"{config.CODECHEF_BASE_URL}/users/{normalized}"
        try:
            response = session.get(url, timeout=config.REQUEST_TIMEOUT_SECONDS)
        except requests.RequestException as exc:
            logger.warning("Could not verify username %s: %s", normalized, exc)
            continue
        if response.status_code == 404:
            invalid.add(normalized)
        elif response.status_code == 200:
            continue
        else:
            logger.warning(
                "Could not conclusively verify username %s (HTTP %s); leaving it valid/unknown.",
                normalized,
                response.status_code,
            )
        time.sleep(config.REQUEST_DELAY_SECONDS)
    return invalid


def load_rankings_csv(csv_path: Path) -> List[RankingEntry]:
    """Load rankings exported to CSV instead of calling CodeChef's web endpoint.

    The file must have a username column (``Username``, ``CodeChef Username``,
    ``Handle``, or ``Code``). Rank, name, score, problems solved, rating, and
    rating change are optional. Column names are case-insensitive.
    """
    csv_path = Path(csv_path)
    if not csv_path.exists():
        raise RankingsFileError(f"Rankings CSV not found at '{csv_path}'.")

    aliases = {
        "username": ("username", "codechefusername", "handle", "code", "userhandle"),
        "rank": ("rank",),
        "name": ("name", "studentname", "displayname"),
        "score": ("score", "totalscore"),
        "problems_solved": ("problemssolved", "solved", "problems"),
        "rating": ("rating", "ratingafter"),
        "diff": ("diff", "ratingdiff", "ratingchange"),
    }

    def normalized_header(value: str) -> str:
        return re.sub(r"[^a-z0-9]", "", value.lower())

    try:
        with csv_path.open(newline="", encoding="utf-8-sig") as file:
            reader = csv.DictReader(file)
            headers = {
                normalized_header(header): header
                for header in (reader.fieldnames or [])
            }
            columns = {
                field: next((headers[name] for name in names if name in headers), None)
                for field, names in aliases.items()
            }
            if columns["username"] is None:
                raise RankingsFileError(
                    "Rankings CSV needs a username column named Username, CodeChef "
                    "Username, Handle, or Code."
                )

            entries = []
            for row_number, row in enumerate(reader, start=2):
                username = (row.get(columns["username"]) or "").strip()
                if not username:
                    continue
                raw = {
                    "code": username,
                    "rank": row.get(columns["rank"]) if columns["rank"] else None,
                    "name": row.get(columns["name"]) if columns["name"] else username,
                    "score": row.get(columns["score"]) if columns["score"] else None,
                    "problemsSolved": row.get(columns["problems_solved"]) if columns["problems_solved"] else None,
                    "rating": row.get(columns["rating"]) if columns["rating"] else None,
                    "diff": row.get(columns["diff"]) if columns["diff"] else None,
                }
                try:
                    entries.append(_parse_ranking_row(raw))
                except CodeChefStructureChangedError as exc:
                    raise RankingsFileError(
                        f"Could not parse rankings CSV row {row_number}: {exc}"
                    ) from exc
    except UnicodeDecodeError as exc:
        raise RankingsFileError("Rankings CSV must be UTF-8 encoded.") from exc
    except csv.Error as exc:
        raise RankingsFileError(f"Could not read rankings CSV: {exc}") from exc

    if not entries:
        raise RankingsFileError(
            f"Rankings CSV at '{csv_path}' contains no rows with a username."
        )
    logger.info("Loaded %d ranking row(s) from %s", len(entries), csv_path)
    return entries


def _parse_profile_rating(
    text: str,
    contest_code: str,
    rating_type: str = "codechef",
) -> tuple[Optional[int], Optional[int]]:
    """Extract the *current*, labelled rating tuple from rendered profile text.

    ``contest_code`` remains accepted for backward compatibility but is
    deliberately not used: a profile's current rating is the source of truth,
    not a rating associated with a ranklist contest.
    """
    rating_type = (rating_type or "codechef").strip().lower()
    if rating_type not in {"codechef", "dsa"}:
        raise ValueError("rating_type must be 'codechef' or 'dsa'")

    label = "DSA Rating" if rating_type == "dsa" else "CodeChef Rating"
    # A small bounded window makes the association with the visible label
    # explicit and prevents a normal lookup from falling into the DSA graph.
    labelled = re.search(
        rf"{re.escape(label)}\s*(?:\n|\s)+(?P<rating>\d{{3,5}})"
        rf"(?:\s*\(\s*(?P<change>[+-]?\d+)\s*\)\s*Rating)?",
        text,
        re.I,
    )
    if labelled:
        return int(labelled.group("rating")), _parse_rating_diff(labelled.group("change"))

    # Some profile layouts label the chart rather than the summary card.
    graph_label = "DSA Rating Graph" if rating_type == "dsa" else "Rating Graph"
    if rating_type == "codechef":
        # Do not let the unqualified phrase inside "DSA Rating Graph" match.
        marker = re.search(r"(?<!DSA\s)\bRating Graph\b", text, re.I)
    else:
        marker = re.search(re.escape(graph_label), text, re.I)
    if marker:
        next_marker = re.search(r"\b(?:DSA Rating Graph|CodeChef Rating|DSA Rating)\b", text[marker.end():], re.I)
        window = text[marker.end(): marker.end() + (next_marker.start() if next_marker else 3000)]
        match = re.search(r"\b(\d{3,5})\s*\(\s*([+-]?\d+)\s*\)\s*Rating", window, re.I)
        if match:
            return int(match.group(1)), int(match.group(2))

    # The production profile card puts its numeric value before its label in
    # DOM order (``1435 ... CodeChef Rating``).  This is intentionally after
    # chart parsing: a full-page DSA graph can otherwise see a normal-rating
    # value that appears before the DSA label.
    labelled_after = re.search(
        rf"\b(?P<rating>\d{{3,5}})(?:\s*\(\s*(?P<change>[+-]?\d+)\s*\)\s*Rating)?"
        rf"[\s\S]{{0,250}}?{re.escape(label)}\b",
        text,
        re.I,
    )
    if labelled_after:
        return int(labelled_after.group("rating")), _parse_rating_diff(labelled_after.group("change"))
    return (None, None)


def _parse_ranking_row(raw: dict) -> Optional[RankingEntry]:
    """
    Parse a single row of the 'list' array from the rankings endpoint.

    Field names are based on the JSON structure CodeChef's own ranklist page
    has used ('rank', 'code' or 'username', 'name', 'score', 'rating',
    'diff'/'ratingdiff'). This function is defensive: any field it can't
    find is left as None rather than guessed, and unexpected shapes raise
    CodeChefStructureChangedError so the failure is loud, not silent.
    """
    try:
        username_raw = raw.get("code") or raw.get("username") or raw.get("user_handle")
        if not username_raw:
            raise CodeChefStructureChangedError(
                "A rankings row had no recognizable username field "
                f"(expected 'code' or 'username'). Row keys were: {list(raw.keys())}"
            )

        rank = _to_int(raw.get("rank") or raw.get("global_rank") or raw.get("contestRank"))
        display_name = str(raw.get("name") or raw.get("user_name") or username_raw)
        total_score = _to_float(raw.get("score") or raw.get("total_score") or raw.get("points"))
        ranklist_solved = _to_int(
            raw.get("problemsSolved") or raw.get("problems_solved") or
            raw.get("solved") or raw.get("solved_count") or raw.get("solvedProblems")
        )
        # Score is the report's agreed source of truth: 400 = 4, 300 = 3,
        # etc.  Some ranklist responses expose an unreliable/placeholder
        # solved-count field, so only use it when score is unavailable.
        problems_solved = (
            derive_problems_solved_from_score(total_score)
            if total_score is not None else ranklist_solved
        )

        rating_after = _to_int(
            raw.get("rating") or raw.get("ratingAfter") or raw.get("rating_after") or
            raw.get("newRating") or raw.get("new_rating")
        )
        rating_change = _parse_rating_diff(
            raw.get("diff") or raw.get("ratingdiff") or raw.get("ratingDiff") or
            raw.get("rating_change") or raw.get("ratingChange")
        )
        rating_before = None
        if rating_after is not None and rating_change is not None:
            rating_before = rating_after - rating_change

        return RankingEntry(
            rank=rank,
            username=normalize_username(username_raw),
            display_name=display_name,
            problems_solved=problems_solved,
            total_score=total_score,
            rating_after=rating_after,
            rating_change=rating_change,
            rating_before=rating_before,
            raw=raw,
        )
    except CodeChefStructureChangedError:
        raise
    except Exception as exc:  # noqa: BLE001 - deliberately broad, converted below
        raise CodeChefStructureChangedError(
            f"Failed to parse a CodeChef rankings row ({exc}). Row was: {raw}"
        ) from exc


def _to_int(value) -> Optional[int]:
    if value is None or value == "":
        return None
    try:
        return int(float(value))
    except (ValueError, TypeError):
        return None


def _to_float(value) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def _parse_rating_diff(value) -> Optional[int]:
    """CodeChef often represents rating change as a signed string, e.g. '+15' or '-8'."""
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value).strip()
    text = text.replace("+", "")
    try:
        return int(text)
    except ValueError:
        return None


KNOWN_CONTEST_METADATA = {
    # CodeChef Starters 253: official CodeChef announcement says
    # Wednesday, 26 August 2026, 8:00 PM--10:00 PM IST.
    "START253C": {
        "contest_name": "Starters 253",
        "start_date": "2026-08-26 20:00 IST",
        "end_date": "2026-08-26 22:00 IST",
    },
    "START254D": {
        "contest_name": "Starters 254",
        "start_date": "2026-06-24",
        "end_date": "2026-06-24",
    },
}


def get_contest_metadata(contest_code: str, entries: Optional[List[RankingEntry]] = None) -> ContestMetadata:
    """Return contest metadata without inventing values.

    CodeChef's rankings endpoint does not reliably include contest dates.
    For contests whose official schedule is known to this application we use
    an explicit verified metadata entry; otherwise the workbook says
    ``Unknown`` rather than silently making up a date.
    """
    code = contest_code.upper()
    known = KNOWN_CONTEST_METADATA.get(code, {})
    return ContestMetadata(
        contest_code=code,
        contest_name=known.get("contest_name", code),
        contest_url=f"{config.CODECHEF_BASE_URL}/{code}",
        start_date=known.get("start_date", "Unknown"),
        end_date=known.get("end_date", "Unknown"),
    )


def fetch_problem_wise_status(
    contest_code: str, entries: List[RankingEntry]
) -> Dict[str, Dict[str, str]]:
    """
    OPT-IN, best-effort per-problem solve grid: {username: {problem_code: "Solved"/"Not Solved"}}.

    NOT called by default (see module docstring). CodeChef's public
    rankings endpoint does not expose a per-problem grid, so the only way
    to build one is one extra request per student per problem via each
    student's status page -- slow and fragile at class/school scale, and
    disabled by default for that reason. This function currently returns
    an empty dict as a safe placeholder; excel_report.py already handles
    an empty problem-wise dict gracefully by marking the per-problem
    columns "Not available" and showing only the total problems-solved
    count (which IS available from the rankings endpoint).

    If you need real per-problem detail, implement the per-student status
    page fetch here, being mindful of request volume and CodeChef's terms.
    """
    logger.info(
        "fetch_problem_wise_status() was called, but per-problem detail is not "
        "exposed by CodeChef's public rankings endpoint -- returning no data. "
        "See the docstring of this function in codechef.py."
    )
    return {}
