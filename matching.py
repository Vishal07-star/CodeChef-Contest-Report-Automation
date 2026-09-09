"""
matching.py
-----------
Matches the student roster (students.csv) against the fetched CodeChef
ranking entries, and classifies every student as participated /
did-not-participate.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

from codechef import RankingEntry
from utils import Student, StudentRoster, logger, normalize_username


@dataclass
class MatchedStudent:
    name: str
    username: str                  # normalized
    original_username: str
    participated: bool
    duplicate: bool
    username_valid: bool = True
    entry: Optional[RankingEntry] = None


@dataclass
class MatchResult:
    matched: List[MatchedStudent]          # every student, participated or not
    unmatched_usernames: List[str]         # usernames in rankings with no matching student
    participants_count: int
    non_participants_count: int
    ambiguous_count: int
    username_not_found_count: int

    def participants(self) -> List[MatchedStudent]:
        return [m for m in self.matched if m.participated]

    def non_participants(self) -> List[MatchedStudent]:
        """Students with a valid CodeChef username who are absent from the ranklist."""
        return [
            m for m in self.matched
            if not m.participated and not m.duplicate and m.username_valid
        ]

    def username_not_found(self) -> List[MatchedStudent]:
        """Students whose roster username could not be verified as a CodeChef account."""
        return [
            m for m in self.matched
            if not m.participated and not m.duplicate and not m.username_valid
        ]

    def ambiguous(self) -> List[MatchedStudent]:
        """Students whose shared handle makes their participation unverifiable."""
        return [m for m in self.matched if m.duplicate]

    def duplicate_usernames_note(self) -> str:
        duplicates = sorted({m.username for m in self.matched if m.duplicate})
        if not duplicates:
            return ""
        return (
            f"{len(duplicates)} CodeChef username(s) are claimed by more than one "
            f"student in students.csv: {', '.join(duplicates)}. Please fix students.csv."
        )


def match_students(
    roster: StudentRoster,
    rankings: List[RankingEntry],
    invalid_usernames: Optional[set[str]] = None,
) -> MatchResult:
    """
    For every student in the roster, look up whether they appear in the
    contest rankings (by normalized username). `invalid_usernames` contains
    usernames that were explicitly checked against CodeChef and confirmed not
    to exist. A valid username absent from the contest ranklist is therefore
    classified as "Did Not Participate", while an invalid username is kept
    separate as "Username Not Found".
    """
    rankings_by_username: Dict[str, RankingEntry] = {r.username: r for r in rankings}
    invalid_usernames = {normalize_username(u) for u in (invalid_usernames or set())}

    matched: List[MatchedStudent] = []
    matched_ranking_usernames = set()

    for student in roster.students:
        entry = rankings_by_username.get(student.username)
        # A shared handle cannot prove which listed student participated. Do not
        # award participation credit until the roster is corrected.
        participated = entry is not None and not student.duplicate
        username_valid = student.username not in invalid_usernames
        if participated:
            matched_ranking_usernames.add(student.username)

        matched.append(
            MatchedStudent(
                name=student.name,
                username=student.username,
                original_username=student.original_username,
                participated=participated,
                duplicate=student.duplicate,
                username_valid=username_valid,
                entry=entry,
            )
        )

    unmatched_usernames = sorted(
        set(rankings_by_username.keys()) - matched_ranking_usernames
    )
    if unmatched_usernames:
        logger.info(
            "%d username(s) appear in the contest rankings but not in students.csv "
            "(could be other participants, or a student who mistyped their username "
            "in students.csv): %s",
            len(unmatched_usernames),
            ", ".join(unmatched_usernames[:20]) + ("..." if len(unmatched_usernames) > 20 else ""),
        )

    participants_count = sum(1 for m in matched if m.participated)
    non_participants_count = sum(
        1 for m in matched if not m.participated and not m.duplicate and m.username_valid
    )
    username_not_found_count = sum(
        1 for m in matched if not m.participated and not m.duplicate and not m.username_valid
    )
    ambiguous_count = sum(1 for m in matched if m.duplicate)

    logger.info(
        "Matching complete: %d participated, %d did not participate, %d username not found, %d ambiguous (out of %d students)",
        participants_count, non_participants_count, username_not_found_count, ambiguous_count, len(matched),
    )

    return MatchResult(
        matched=matched,
        unmatched_usernames=unmatched_usernames,
        participants_count=participants_count,
        non_participants_count=non_participants_count,
        ambiguous_count=ambiguous_count,
        username_not_found_count=username_not_found_count,
    )
