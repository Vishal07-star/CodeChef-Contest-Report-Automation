"""
Tests for matching.py: student <-> ranking matching, and non-participant detection.
Uses mock RankingEntry / StudentRoster objects -- no live CodeChef data needed.
"""

import unittest

from codechef import RankingEntry
from matching import match_students
from utils import Student, StudentRoster


def make_roster(pairs):
    roster = StudentRoster()
    for name, username in pairs:
        roster.students.append(
            Student(name=name, username=username.lower(), original_username=username)
        )
    return roster


def make_entry(username, rank=1, problems_solved=3, score=300.0, rating_after=1500, rating_change=10):
    return RankingEntry(
        rank=rank,
        username=username.lower(),
        display_name=username,
        problems_solved=problems_solved,
        total_score=score,
        rating_after=rating_after,
        rating_change=rating_change,
        rating_before=rating_after - rating_change,
    )


class TestMatchStudents(unittest.TestCase):
    def test_all_participated(self):
        roster = make_roster([("Rahul", "rahul123"), ("Priya", "priya07")])
        rankings = [make_entry("rahul123", rank=1), make_entry("priya07", rank=2)]
        result = match_students(roster, rankings)
        self.assertEqual(result.participants_count, 2)
        self.assertEqual(result.non_participants_count, 0)

    def test_some_did_not_participate(self):
        roster = make_roster([("Rahul", "rahul123"), ("Priya", "priya07"), ("Arun", "arun22")])
        rankings = [make_entry("rahul123", rank=1)]
        result = match_students(roster, rankings)
        self.assertEqual(result.participants_count, 1)
        self.assertEqual(result.non_participants_count, 2)
        non_names = {m.name for m in result.non_participants()}
        self.assertEqual(non_names, {"Priya", "Arun"})

    def test_case_insensitive_matching(self):
        roster = make_roster([("Rahul", "Rahul123")])
        rankings = [make_entry("rahul123", rank=1)]
        result = match_students(roster, rankings)
        self.assertEqual(result.participants_count, 1)


    def test_valid_username_absent_from_rankings_is_did_not_participate(self):
        roster = make_roster([("Rahul", "rahul123"), ("Priya", "priya07")])
        rankings = [make_entry("rahul123", rank=1)]
        result = match_students(roster, rankings)
        priya = next(m for m in result.matched if m.name == "Priya")
        self.assertTrue(priya.username_valid)
        self.assertEqual(priya.entry, None)
        self.assertEqual(result.non_participants_count, 1)
        self.assertEqual(result.username_not_found_count, 0)
        self.assertEqual(priya.participated, False)

    def test_confirmed_invalid_username_is_not_did_not_participate(self):
        roster = make_roster([("Rahul", "rahul123"), ("Typo", "wrong_name")])
        rankings = [make_entry("rahul123", rank=1)]
        result = match_students(roster, rankings, invalid_usernames={"wrong_name"})
        typo = next(m for m in result.matched if m.name == "Typo")
        self.assertFalse(typo.username_valid)
        self.assertEqual(result.non_participants_count, 0)
        self.assertEqual(result.username_not_found_count, 1)
        self.assertIn(typo, result.username_not_found())

    def test_unmatched_ranking_usernames_reported(self):
        roster = make_roster([("Rahul", "rahul123")])
        rankings = [make_entry("rahul123", rank=1), make_entry("someone_else", rank=2)]
        result = match_students(roster, rankings)
        self.assertIn("someone_else", result.unmatched_usernames)

    def test_duplicate_usernames_flagged(self):
        roster = make_roster([("Rahul", "same_user"), ("Ravi", "same_user")])
        roster.duplicate_usernames["same_user"] = ["Rahul", "Ravi"]
        for s in roster.students:
            s.duplicate = True
        rankings = [make_entry("same_user", rank=1)]
        result = match_students(roster, rankings)
        self.assertTrue(all(m.duplicate for m in result.matched))
        self.assertIn("same_user", result.duplicate_usernames_note())
        self.assertEqual(result.participants_count, 0)
        self.assertEqual(result.non_participants_count, 0)
        self.assertEqual(result.ambiguous_count, 2)


if __name__ == "__main__":
    unittest.main()
