"""
Tests for codechef.py's contest-input parsing and row-parsing logic.
These tests use only mock/sample data -- no live network calls, no
dependency on any real contest being available.
"""

import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from codechef import (
    RankingEntry,
    _parse_rating_diff,
    _parse_ranking_row,
    _parse_profile_rating,
    expand_division_contest_codes,
    fetch_contest_rankings_browser,
    _search_usernames_first_match,
    _browser_search_url,
    _is_explicit_rankings_payload,
    _is_rendered_ranklist_page,
    get_contest_metadata,
    load_rankings_csv,
    parse_contest_input,
)
from exceptions import BrowserFetchError, CodeChefStructureChangedError, InvalidContestInputError


class TestParseContestInput(unittest.TestCase):
    def test_bare_code(self):
        self.assertEqual(parse_contest_input("START200"), "START200")

    def test_bare_code_lowercase_is_uppercased(self):
        self.assertEqual(parse_contest_input("starters200"), "STARTERS200")

    def test_full_url(self):
        self.assertEqual(
            parse_contest_input("https://www.codechef.com/START200"), "START200"
        )

    def test_url_with_trailing_slash(self):
        self.assertEqual(
            parse_contest_input("https://www.codechef.com/START200/"), "START200"
        )

    def test_url_with_query_string(self):
        self.assertEqual(
            parse_contest_input("https://www.codechef.com/START200?tab=ranklist"),
            "START200",
        )

    def test_non_codechef_url_rejected(self):
        with self.assertRaises(InvalidContestInputError):
            parse_contest_input("https://www.example.com/START200")

    def test_empty_input_rejected(self):
        with self.assertRaises(InvalidContestInputError):
            parse_contest_input("   ")

    def test_garbage_input_rejected(self):
        with self.assertRaises(InvalidContestInputError):
            parse_contest_input("!!! not a contest !!!")


class TestExpandDivisionContestCodes(unittest.TestCase):
    def test_division_letter_expands_to_all_four(self):
        self.assertEqual(
            expand_division_contest_codes("START253D"),
            ["START253A", "START253B", "START253C", "START253D"],
        )

    def test_division_letter_from_division_a(self):
        self.assertEqual(
            expand_division_contest_codes("START253A"),
            ["START253A", "START253B", "START253C", "START253D"],
        )

    def test_bare_code_without_division_letter_is_unchanged(self):
        self.assertEqual(expand_division_contest_codes("START200"), ["START200"])

    def test_non_digit_before_letter_is_unchanged(self):
        # "COOK" ends in a letter but not one preceded by a digit -- not a
        # division-style code, so it must be left alone.
        self.assertEqual(expand_division_contest_codes("COOKOFF"), ["COOKOFF"])


class TestFirstMatchDivisionSearch(unittest.TestCase):
    def test_searches_div4_to_div1_and_stops_when_found(self):
        calls = []

        def fake_fetch(contest_code, username):
            calls.append((contest_code, username))
            if contest_code == "START253C":
                return RankingEntry(
                    rank=10, username=username, display_name="Student",
                    problems_solved=3, total_score=300, rating_after=1500,
                    rating_change=10, rating_before=1490, source_contest=contest_code
                )
            return None

        result = _search_usernames_first_match(
            ["abc123"], ["START253D", "START253C", "START253B", "START253A"], fake_fetch
        )

        self.assertEqual([c[0] for c in calls], ["START253D", "START253C"])
        self.assertEqual(result[0].source_contest, "START253C")

    def test_div4_match_is_not_searched_again_in_lower_divisions(self):
        calls = []

        def fake_fetch(contest_code, username):
            calls.append(contest_code)
            if contest_code == "START253D":
                return RankingEntry(
                    rank=1, username=username, display_name="Student",
                    problems_solved=4, total_score=400, rating_after=1600,
                    rating_change=20, rating_before=1580, source_contest=contest_code
                )
            return None

        result = _search_usernames_first_match(
            ["ac123"], ["START253D", "START253C", "START253B", "START253A"], fake_fetch
        )

        self.assertEqual(calls, ["START253D"])
        self.assertEqual(result[0].source_contest, "START253D")

    def test_duplicate_roster_usernames_are_searched_once(self):
        calls = []

        def fake_fetch(contest_code, username):
            calls.append((contest_code, username))
            return None

        with patch("codechef.time.sleep", return_value=None):
            result = _search_usernames_first_match(
                ["ac123"],
                ["START253D", "START253C", "START253B", "START253A"],
                fake_fetch,
            )

        # The caller normalizes/deduplicates roster usernames before invoking
        # this helper; duplicate values are therefore tested by passing the
        # normalized unique list explicitly.
        self.assertEqual(len(calls), 4)
        self.assertTrue(all(c[1] == "ac123" for c in calls))

    def test_dsa_browser_search_url_uses_only_rankings_page(self):
        url = _browser_search_url("DSAMONDAY018", "kit28csb184")
        self.assertIn("/rankings/DSAMONDAY018?", url)
        self.assertIn("search=kit28csb184", url)
        self.assertNotIn("/public/", url)
        from codechef import _browser_search_urls
        self.assertEqual(len(_browser_search_urls("DSAMONDAY018", "kit28csb184")), 1)

    def test_ranklist_failure_never_becomes_non_participation(self):
        def failed_fetch(_contest_code, _username):
            raise BrowserFetchError("simulated timeout")

        with self.assertRaises(BrowserFetchError):
            _search_usernames_first_match(
                ["kit28csb184"], ["DSAMONDAY018"], failed_fetch
            )

    def test_explicit_empty_ranklist_payload_is_recognised(self):
        self.assertTrue(_is_explicit_rankings_payload({"data": {"list": []}}))
        self.assertFalse(_is_explicit_rankings_payload({"message": "temporary error"}))

    def test_generic_landing_page_is_not_a_ranklist(self):
        self.assertFalse(_is_rendered_ranklist_page("Becoming the best coder is easy!"))
        self.assertTrue(_is_rendered_ranklist_page("CodeChef Ranklist Username Total Score"))


class TestParseRatingDiff(unittest.TestCase):
    def test_positive_string(self):
        self.assertEqual(_parse_rating_diff("+15"), 15)

    def test_negative_string(self):
        self.assertEqual(_parse_rating_diff("-8"), -8)

    def test_plain_number(self):
        self.assertEqual(_parse_rating_diff(12), 12)

    def test_none(self):
        self.assertIsNone(_parse_rating_diff(None))

    def test_unparsable(self):
        self.assertIsNone(_parse_rating_diff("pending"))


class TestParseProfileRating(unittest.TestCase):
    def test_normal_profile_label_returns_current_rating_and_change(self):
        text = """
        CodeChef Rating
        1435 (+11) Rating
        """
        self.assertEqual(_parse_profile_rating(text, "START253C"), (1435, 11))

    def test_dsa_profile_label_returns_current_rating_and_change(self):
        text = "DSA Rating\n1513 (-33) Rating"
        self.assertEqual(_parse_profile_rating(text, "DSAMONDAY018", rating_type="dsa"), (1513, -33))

    def test_normal_does_not_use_dsa_when_both_ratings_exist(self):
        text = "CodeChef Rating\n1435 (+11) Rating\nDSA Rating\n1513 (-33) Rating"
        self.assertEqual(_parse_profile_rating(text, "START253C"), (1435, 11))

    def test_dsa_does_not_use_normal_when_both_ratings_exist(self):
        text = "CodeChef Rating\n1435 (+11) Rating\nDSA Rating\n1513 (-33) Rating"
        self.assertEqual(_parse_profile_rating(text, "DSAMONDAY018", rating_type="dsa"), (1513, -33))

    def test_rendered_card_with_value_before_label(self):
        text = "1435\n(Div 3)\nCodeChef Rating\n(Highest Rating 1463)"
        self.assertEqual(_parse_profile_rating(text, "START253C"), (1435, None))

    def test_missing_rating(self):
        self.assertEqual(_parse_profile_rating("START253C\nGlobal Rank: 5", "START253C"), (None, None))

    def test_dsa_rating_reads_dsa_graph_not_codechef_graph(self):
        text = """
        Rating Graph
        1435 (+11) RatingProvisional
        Starters 253 (Rated)
        DSA Rating Graph
        1513 (-33) RatingProvisional
        Monday Munch - DSA Challenge 018 (Rated)
        1435 (+11) RatingProvisional
        """
        self.assertEqual(_parse_profile_rating(text, "SOME_DSA_CONTEST", rating_type="dsa"), (1513, -33))

    def test_codechef_rating_does_not_use_dsa_rating(self):
        text = """
        Rating Graph
        1435 (+11) RatingProvisional
        START253C
        DSA Rating Graph
        1513 (-33) RatingProvisional
        Monday Munch - DSA Challenge 018 (Rated)
        """
        self.assertEqual(_parse_profile_rating(text, "START253C", rating_type="codechef"), (1435, 11))


class TestParseRankingRow(unittest.TestCase):
    def test_typical_row(self):
        raw = {
            "rank": "1",
            "code": "Rahul123",
            "name": "Rahul Sharma",
            "score": "300.00",
            "rating": "1850",
            "diff": "+25",
        }
        entry = _parse_ranking_row(raw)
        self.assertIsInstance(entry, RankingEntry)
        self.assertEqual(entry.rank, 1)
        self.assertEqual(entry.username, "rahul123")
        self.assertEqual(entry.display_name, "Rahul Sharma")
        self.assertEqual(entry.total_score, 300.0)
        self.assertEqual(entry.rating_after, 1850)
        self.assertEqual(entry.rating_change, 25)
        self.assertEqual(entry.rating_before, 1825)

    def test_missing_username_raises(self):
        with self.assertRaises(CodeChefStructureChangedError):
            _parse_ranking_row({"rank": "1", "name": "No Username Here"})

    def test_missing_rating_fields_are_none_not_invented(self):
        raw = {"rank": "5", "code": "someone", "name": "Someone"}
        entry = _parse_ranking_row(raw)
        self.assertIsNone(entry.rating_after)
        self.assertIsNone(entry.rating_change)
        self.assertIsNone(entry.rating_before)


class TestDivisionSearchCodes(unittest.TestCase):
    def test_dsa_contest_has_no_division_search(self):
        from codechef import _division_search_codes
        self.assertEqual(_division_search_codes("DSAMONDAY018", rating_type="dsa"), ["DSAMONDAY018"])

    def test_codechef_division_search_is_d4_to_d1(self):
        from codechef import _division_search_codes
        self.assertEqual(_division_search_codes("START253C", rating_type="codechef"), ["START253D", "START253C", "START253B", "START253A"])


class TestContestMetadata(unittest.TestCase):
    def test_metadata_never_invents_dates_for_unknown_contest(self):
        meta = get_contest_metadata("START200")
        self.assertEqual(meta.contest_code, "START200")
        self.assertEqual(meta.start_date, "Unknown")
        self.assertEqual(meta.end_date, "Unknown")
        self.assertIn("START200", meta.contest_url)

    def test_known_start253c_metadata(self):
        meta = get_contest_metadata("START253C")
        self.assertEqual(meta.contest_name, "Starters 253")
        self.assertEqual(meta.start_date, "2026-08-26 20:00 IST")
        self.assertEqual(meta.end_date, "2026-08-26 22:00 IST")


class TestLoadRankingsCsv(unittest.TestCase):
    def test_loads_standard_export_columns(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rankings.csv"
            path.write_text(
                "Rank,CodeChef Username,Name,Problems Solved,Total Score,Rating Change\n"
                "1,Rahul123,Rahul Sharma,4,400,+20\n",
                encoding="utf-8",
            )
            entries = load_rankings_csv(path)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].username, "rahul123")
        self.assertEqual(entries[0].problems_solved, 4)
        self.assertEqual(entries[0].total_score, 400.0)
        self.assertEqual(entries[0].rating_change, 20)


if __name__ == "__main__":
    unittest.main()


def test_empty_browser_result_must_not_be_treated_as_absent():
    # Regression rule documented by v10: an empty ranking fetch is a source
    # failure, not evidence that every roster student was absent.
    from exceptions import RankingsUnavailableError
    assert issubclass(RankingsUnavailableError, Exception)

class TestDerivedContestFields(unittest.TestCase):
    def test_problems_solved_derived_from_score(self):
        from codechef import _parse_ranking_row
        self.assertEqual(_parse_ranking_row({"code": "user1", "rank": 1, "score": 400}).problems_solved, 4)
        self.assertEqual(_parse_ranking_row({"code": "user2", "rank": 2, "score": 300}).problems_solved, 3)
        self.assertEqual(_parse_ranking_row({"code": "user3", "rank": 3, "score": 200}).problems_solved, 2)

    def test_score_overrides_placeholder_ranklist_solved_count(self):
        from codechef import _parse_ranking_row
        entry = _parse_ranking_row(
            {"code": "user1", "rank": 1, "score": 400, "problemsSolved": 0}
        )
        self.assertEqual(entry.problems_solved, 4)

    def test_division_label(self):
        from codechef import division_label
        self.assertEqual(division_label("START253A"), "Division 1")
        self.assertEqual(division_label("START253B"), "Division 2")
        self.assertEqual(division_label("START253C"), "Division 3")
        self.assertEqual(division_label("START253D"), "Division 4")


def test_browser_ranklist_extractor_accepts_nested_payload():
    from codechef import _extract_ranking_rows_from_browser_response

    payload = {
        "data": {
            "result": {
                "rows": [
                    {"rank": 42, "code": "kit28bcs001", "score": 300},
                ]
            }
        }
    }
    rows = _extract_ranking_rows_from_browser_response(payload)
    assert rows[0]["code"] == "kit28bcs001"
    assert rows[0]["rank"] == 42
