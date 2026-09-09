"""
config.py
---------
Central place for every configurable value in the project.

Design goals (see README section "Configuration"):
  * Secrets (passwords, tokens) come ONLY from environment variables /
    GitHub Secrets. They are never hard-coded and never logged.
  * Non-secret settings have sensible defaults here, but can be overridden
    with environment variables so a teacher never has to edit Python code.
  * CLI arguments (handled in main.py) take priority over everything here.
"""

import os
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

if load_dotenv:
    load_dotenv(Path(__file__).resolve().parent / ".env")

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent

STUDENTS_CSV_PATH = Path(os.environ.get("STUDENTS_CSV_PATH", BASE_DIR / "students.csv"))
REPORTS_DIR = Path(os.environ.get("REPORTS_DIR", BASE_DIR / "reports"))
LOGS_DIR = Path(os.environ.get("LOGS_DIR", BASE_DIR / "logs"))

REPORTS_DIR.mkdir(parents=True, exist_ok=True)
LOGS_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# CodeChef data-fetching behaviour
# ---------------------------------------------------------------------------
# CodeChef does not publish a stable, documented public API. The browser
# fetcher uses the current contest rankings UI, which is served at
# /rankings/<contest_code>. The older alternate route is deliberately not
# used because it can return 404 for current contests.
CODECHEF_BASE_URL = "https://www.codechef.com"
CODECHEF_RANKINGS_ENDPOINT = CODECHEF_BASE_URL + "/api/rankings/{contest_code}"
CODECHEF_RANKINGS_PAGE_URL = CODECHEF_BASE_URL + "/rankings/{contest_code}"

# A normal browser-like User-Agent. This is NOT an attempt to bypass any
# access control -- it simply avoids being blocked as an obviously
# mis-identified bot on a plain, unauthenticated GET request.
HTTP_USER_AGENT = os.environ.get(
    "HTTP_USER_AGENT",
    "Mozilla/5.0 (compatible; CodeChefContestReportBot/1.0; "
    "+https://github.com/) requests-python",
)

REQUEST_TIMEOUT_SECONDS = float(os.environ.get("REQUEST_TIMEOUT_SECONDS", 15))
ITEMS_PER_PAGE = int(os.environ.get("ITEMS_PER_PAGE", 100))
MAX_PAGES = int(os.environ.get("MAX_PAGES", 200))  # safety cap: 200 * 100 = 20,000 rows
REQUEST_DELAY_SECONDS = float(os.environ.get("REQUEST_DELAY_SECONDS", 0.1))  # politeness delay between pages
MAX_RETRIES = int(os.environ.get("MAX_RETRIES", 3))
RETRY_BACKOFF_SECONDS = float(os.environ.get("RETRY_BACKOFF_SECONDS", 2.0))

# Local-browser fetching. CodeChef may block direct scripted API calls, so the
# default report path uses a real browser on the teacher's Windows PC.
BROWSER_HEADLESS = os.environ.get("BROWSER_HEADLESS", "false").lower() == "true"
BROWSER_TIMEOUT_MS = int(os.environ.get("BROWSER_TIMEOUT_MS", 20_000))
# Public profile pages rate-limit rapid repeated navigation.  Pace a class
# report so every ranklist participant gets a fair profile lookup.
PROFILE_REQUEST_DELAY_SECONDS = float(os.environ.get("PROFILE_REQUEST_DELAY_SECONDS", 5.0))

# ---------------------------------------------------------------------------
# Email (all optional; email sending is skipped gracefully if unset)
# ---------------------------------------------------------------------------
SMTP_SERVER = os.environ.get("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", 587))
SMTP_EMAIL = os.environ.get("SMTP_EMAIL")          # sender's Gmail address
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD")    # Gmail App Password (NOT the normal password)
TEACHER_EMAIL = os.environ.get("TEACHER_EMAIL")    # recipient(s); comma-separated allowed

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")
LOG_FILE = LOGS_DIR / "contest_report.log"


def email_is_configured() -> bool:
    """True only if every value needed to send mail is present."""
    return bool(SMTP_EMAIL and SMTP_PASSWORD and TEACHER_EMAIL)
