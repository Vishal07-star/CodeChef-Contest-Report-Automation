"""
utils.py
--------
General-purpose helpers shared across the project:

  * logging setup
  * students.csv loading & validation
  * username normalization
  * small formatting helpers

CodeChef-specific parsing lives in codechef.py, not here, so that any future
CodeChef website change only ever touches one file.
"""

from __future__ import annotations

import csv
import logging
import logging.handlers
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List

import config
from exceptions import (
    StudentsFileEmptyError,
    StudentsFileInvalidColumnsError,
    StudentsFileMissingError,
)

NAME_COLUMN_ALIASES = ("Name", "Name of the student")
USERNAME_COLUMN_ALIASES = ("Username",)


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
def setup_logging(log_file: Path = config.LOG_FILE, level: str = config.LOG_LEVEL) -> logging.Logger:
    """
    Configure root logging once. Safe to call multiple times (idempotent).

    Logs go both to the console (so the teacher sees progress) and to a
    rotating log file under logs/. Never logs secrets: callers must not
    pass SMTP passwords, tokens, or credentials into log messages.
    """
    logger = logging.getLogger("codechef_report")
    if logger.handlers:
        return logger  # already configured

    logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    log_file = Path(log_file)
    log_file.parent.mkdir(parents=True, exist_ok=True)
    file_handler = logging.handlers.RotatingFileHandler(
        log_file, maxBytes=2_000_000, backupCount=5, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    return logger


logger = logging.getLogger("codechef_report")


# ---------------------------------------------------------------------------
# Username normalization
# ---------------------------------------------------------------------------
def normalize_username(raw: str) -> str:
    """
    CodeChef usernames are case-insensitive and users often paste them with
    stray whitespace or a leading '@'. Normalize so matching is reliable.
    """
    if raw is None:
        return ""
    cleaned = raw.strip()
    if cleaned.startswith("@"):
        cleaned = cleaned[1:]
    return cleaned.lower()


# ---------------------------------------------------------------------------
# Student records
# ---------------------------------------------------------------------------
@dataclass
class Student:
    name: str
    username: str                # normalized
    original_username: str        # exactly as typed in the CSV
    register_number: str = ""
    department: str = ""
    section: str = ""
    duplicate: bool = False


@dataclass
class StudentRoster:
    students: List[Student] = field(default_factory=list)
    duplicate_usernames: Dict[str, List[str]] = field(default_factory=dict)  # normalized -> [names]

    def usernames(self) -> List[str]:
        return [s.username for s in self.students]


def load_students(csv_path: Path = config.STUDENTS_CSV_PATH) -> StudentRoster:
    """
    Load and validate students.csv.

    Raises:
        StudentsFileMissingError: file does not exist
        StudentsFileEmptyError: file has no data rows
        StudentsFileInvalidColumnsError: required columns are missing
    """
    csv_path = Path(csv_path)
    if not csv_path.exists():
        raise StudentsFileMissingError(
            f"students.csv not found at '{csv_path}'. "
            f"Create it with columns: Name,Username"
        )

    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        fieldnames = set(reader.fieldnames or [])
        name_column = next((column for column in NAME_COLUMN_ALIASES if column in fieldnames), None)
        username_column = next((column for column in USERNAME_COLUMN_ALIASES if column in fieldnames), None)
        missing = []
        if name_column is None:
            missing.append("Name (or Name of the student)")
        if username_column is None:
            missing.append("Username")
        if missing:
            raise StudentsFileInvalidColumnsError(
                f"students.csv is missing required column(s): {missing}. "
                f"Found columns: {sorted(fieldnames) if fieldnames else '(none)'}. "
                f"Expected at least: Name (or Name of the student),Username"
            )

        rows = list(reader)

    if not rows:
        raise StudentsFileEmptyError(
            f"students.csv at '{csv_path}' has a header row but no student data."
        )

    roster = StudentRoster()
    seen: Dict[str, List[str]] = {}

    for i, row in enumerate(rows, start=2):  # row 1 is the header
        name = (row.get(name_column) or "").strip()
        original_username = (row.get(username_column) or "").strip()

        if not name or not original_username:
            logger.warning(
                "students.csv line %d: skipping row with missing Name or Username: %s",
                i, row,
            )
            continue

        normalized = normalize_username(original_username)
        seen.setdefault(normalized, []).append(name)
        roster.students.append(
            Student(
                name=name,
                username=normalized,
                original_username=original_username,
                register_number=(row.get("Register Number") or row.get("RegisterNumber") or row.get("Register No") or "").strip(),
                department=(row.get("Department") or "").strip(),
                section=(row.get("Section") or "").strip(),
            )
        )

    # Mark duplicates (same username claimed by more than one row)
    for normalized, names in seen.items():
        if len(names) > 1:
            roster.duplicate_usernames[normalized] = names
            for s in roster.students:
                if s.username == normalized:
                    s.duplicate = True
            logger.warning(
                "Duplicate CodeChef username '%s' claimed by multiple students: %s",
                normalized, names,
            )

    if not roster.students:
        raise StudentsFileEmptyError(
            f"students.csv at '{csv_path}' contains no valid student rows "
            f"(every row was missing a Name or Username)."
        )

    logger.info("Loaded %d student record(s) from %s", len(roster.students), csv_path)
    return roster


# ---------------------------------------------------------------------------
# Misc formatting helpers
# ---------------------------------------------------------------------------
def now_iso() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def safe_filename(text: str) -> str:
    keep = "-_"
    return "".join(c for c in text if c.isalnum() or c in keep)
