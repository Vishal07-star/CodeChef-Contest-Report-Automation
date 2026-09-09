"""
exceptions.py
--------------
Custom exception hierarchy used across the project.

Keeping these in one place means every module raises/catches the same
well-defined error types, and main.py can convert them into clear,
human-readable messages for the teacher running the tool.
"""


class ContestReportError(Exception):
    """Base class for every error raised by this project."""


# ---------------------------------------------------------------------------
# CodeChef data-layer errors
# ---------------------------------------------------------------------------
class CodeChefError(ContestReportError):
    """Base class for all errors originating from codechef.py."""


class InvalidContestInputError(CodeChefError):
    """Raised when the --contest value is neither a valid code nor a valid URL."""


class ContestNotFoundError(CodeChefError):
    """Raised when CodeChef has no record of the given contest code."""


class ContestNotEndedError(CodeChefError):
    """Raised when the contest is still running / hasn't started, so
    final rankings are not meaningful yet."""


class RankingsUnavailableError(CodeChefError):
    """Raised when CodeChef returns no rankings for a contest that should
    have them (e.g. private contest, region-locked, or removed)."""


class RankingsFileError(CodeChefError):
    """Raised when an imported rankings CSV is missing or cannot be parsed."""


class BrowserFetchError(CodeChefError):
    """Raised when the local-browser ranklist fetcher cannot collect results."""


class CodeChefStructureChangedError(CodeChefError):
    """Raised when the JSON returned by CodeChef no longer matches the
    fields this project expects. This is the 'canary' error: if CodeChef
    changes its website, this is the exception you should see, and the
    fix should only ever need to touch codechef.py."""


class CodeChefNetworkError(CodeChefError):
    """Raised for connection errors, timeouts, or repeated failed retries."""


# ---------------------------------------------------------------------------
# Student data errors
# ---------------------------------------------------------------------------
class StudentDataError(ContestReportError):
    """Base class for errors related to students.csv."""


class StudentsFileMissingError(StudentDataError):
    pass


class StudentsFileEmptyError(StudentDataError):
    pass


class StudentsFileInvalidColumnsError(StudentDataError):
    pass


# ---------------------------------------------------------------------------
# Report generation errors
# ---------------------------------------------------------------------------
class ReportGenerationError(ContestReportError):
    """Raised when the Excel report cannot be built."""


class EmailSendError(ContestReportError):
    """Raised when the email fails to send. This is intentionally never
    fatal to the overall run -- the report is still generated locally."""
