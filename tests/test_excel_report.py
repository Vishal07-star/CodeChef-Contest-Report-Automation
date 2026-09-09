"""
Tests for excel_report.py: verifies the workbook is generated with the
expected sheets and handles missing/pending data gracefully.
Uses mock data only -- no live CodeChef data or network access.
"""

import tempfile
import unittest
from pathlib import Path

from openpyxl import load_workbook
from openpyxl.styles import PatternFill

from codechef import ContestMetadata, RankingEntry
from excel_report import generate_report
from matching import match_students
from utils import Student, StudentRoster

EXPECTED_SHEETS = [
    "Contest Report",
    "Problem Details",
    "Not Participated",
    "Contest Info",
    "Students",
]


def build_sample_data():
    roster = StudentRoster()
    roster.students = [
        Student(name="Rahul", username="rahul123", original_username="rahul123"),
        Student(name="Priya", username="priya07", original_username="priya07"),
        Student(name="Arun", username="arun22", original_username="arun22"),
    ]
    rankings = [
        RankingEntry(
            rank=1, username="rahul123", display_name="Rahul", problems_solved=4,
            total_score=400.0, rating_after=1800, rating_change=20, rating_before=1780,
        ),
        RankingEntry(
            rank=2, username="priya07", display_name="Priya", problems_solved=3,
            total_score=300.0, rating_after=None, rating_change=None, rating_before=None,
        ),
    ]
    match_result = match_students(roster, rankings)
    contest = ContestMetadata(contest_code="TESTCONTEST", contest_name="Test Contest")
    return contest, roster, match_result


class TestGenerateReport(unittest.TestCase):
    def test_all_sheets_present(self):
        contest, roster, match_result = build_sample_data()
        with tempfile.TemporaryDirectory() as tmp:
            path = generate_report(contest, roster, match_result, output_dir=Path(tmp))
            self.assertTrue(path.exists())
            wb = load_workbook(path)
            self.assertEqual(wb.sheetnames, EXPECTED_SHEETS)

    def test_filename_uses_contest_code(self):
        contest, roster, match_result = build_sample_data()
        with tempfile.TemporaryDirectory() as tmp:
            path = generate_report(contest, roster, match_result, output_dir=Path(tmp))
            self.assertEqual(path.name, "CodeChef_TESTCONTEST_Report.xlsx")

    def test_dsa_uses_separate_excel_filename(self):
        contest, roster, match_result = build_sample_data()
        with tempfile.TemporaryDirectory() as tmp:
            path = generate_report(
                contest, roster, match_result, output_dir=Path(tmp), rating_type="dsa"
            )
            self.assertEqual(path.name, "DSA_TESTCONTEST_Report.xlsx")

    def test_pending_rating_handled_gracefully(self):
        # Priya has no rating_after in the mock data -> should show "Pending", not crash / invent a value.
        contest, roster, match_result = build_sample_data()
        with tempfile.TemporaryDirectory() as tmp:
            path = generate_report(contest, roster, match_result, output_dir=Path(tmp))
            wb = load_workbook(path)
            ws = wb["Contest Report"]
            values = [cell.value for row in ws.iter_rows() for cell in row]
            self.assertIn("Pending", values)


    def test_invalid_username_is_yellow_and_labeled(self):
        roster = StudentRoster()
        roster.students = [
            Student(name="Rahul", username="rahul123", original_username="rahul123"),
            Student(name="Typo", username="wrong_name", original_username="wrong_name"),
        ]
        rankings = [
            RankingEntry(
                rank=1, username="rahul123", display_name="Rahul", problems_solved=4,
                total_score=400.0, rating_after=1800, rating_change=20, rating_before=1780,
            )
        ]
        match_result = match_students(roster, rankings, invalid_usernames={"wrong_name"})
        contest = ContestMetadata(contest_code="TESTCONTEST", contest_name="Test Contest")
        with tempfile.TemporaryDirectory() as tmp:
            path = generate_report(contest, roster, match_result, output_dir=Path(tmp))
            wb = load_workbook(path)
            ws = wb["Contest Report"]
            row = next(r for r in range(5, ws.max_row + 1) if ws.cell(row=r, column=3).value == "Typo")
            self.assertEqual(ws.cell(row=row, column=11).value, "No")
            self.assertEqual(ws.cell(row=row, column=12).value, "Username Not Found")
            self.assertEqual(ws.cell(row=row, column=11).fill.fgColor.rgb, "00FFF2CC")

    def test_valid_absent_username_is_yellow_and_did_not_participate(self):
        roster = StudentRoster()
        roster.students = [
            Student(name="Rahul", username="rahul123", original_username="rahul123"),
            Student(name="Priya", username="priya07", original_username="priya07"),
        ]
        rankings = [
            RankingEntry(
                rank=1, username="rahul123", display_name="Rahul", problems_solved=4,
                total_score=400.0, rating_after=1800, rating_change=20, rating_before=1780,
            )
        ]
        match_result = match_students(roster, rankings)
        contest = ContestMetadata(contest_code="TESTCONTEST", contest_name="Test Contest")
        with tempfile.TemporaryDirectory() as tmp:
            path = generate_report(contest, roster, match_result, output_dir=Path(tmp))
            wb = load_workbook(path)
            ws = wb["Contest Report"]
            row = next(r for r in range(5, ws.max_row + 1) if ws.cell(row=r, column=3).value == "Priya")
            self.assertEqual(ws.cell(row=row, column=11).value, "No")
            self.assertEqual(ws.cell(row=row, column=12).value, "Did Not Participate")
            self.assertEqual(ws.cell(row=row, column=11).fill.fgColor.rgb, "00FFF2CC")

    def test_non_participant_present_in_not_participated_sheet(self):
        contest, roster, match_result = build_sample_data()
        with tempfile.TemporaryDirectory() as tmp:
            path = generate_report(contest, roster, match_result, output_dir=Path(tmp))
            wb = load_workbook(path)
            ws = wb["Not Participated"]
            values = [cell.value for row in ws.iter_rows() for cell in row]
            self.assertIn("Arun", values)



    def test_dsa_report_uses_dsa_columns_without_division(self):
        contest, roster, match_result = build_sample_data()
        with tempfile.TemporaryDirectory() as tmp:
            path = generate_report(
                contest, roster, match_result, output_dir=Path(tmp), rating_type="dsa"
            )
            wb = load_workbook(path)
            ws = wb["Contest Report"]
            header_row = 4
            headers = [ws.cell(row=header_row, column=c).value for c in range(1, 13)]
            self.assertEqual(
                headers,
                [
                    "S.No", "Register Number", "Name of the student", "Department",
                    "Section", "DATE", "Total Problems solved", "Global Rank",
                    "Contest Rating", "Div 1, Div 2, Div 3, Div 4",
                    "ATTENDED Yes/No", "IF NO Reason",
                ],
            )

    def test_empty_problem_wise_shows_not_available_note(self):
        contest, roster, match_result = build_sample_data()
        with tempfile.TemporaryDirectory() as tmp:
            path = generate_report(contest, roster, match_result, problem_wise={}, output_dir=Path(tmp))
            wb = load_workbook(path)
            ws = wb["Problem Details"]
            values = [cell.value for row in ws.iter_rows() for cell in row if cell.value]
            self.assertTrue(any("not available" in str(v).lower() for v in values))

    def test_reference_sheet_format_and_optional_student_fields(self):
        roster = StudentRoster()
        roster.students = [
            Student(
                name="Rahul", username="rahul123", original_username="rahul123",
                register_number="711524BCS001", department="CSE", section="B",
            ),
        ]
        rankings = [
            RankingEntry(
                rank=86485, username="rahul123", display_name="Rahul", problems_solved=1,
                total_score=100.0, rating_after=1022, rating_change=10, rating_before=1012,
                source_contest="START254D",
            )
        ]
        match_result = match_students(roster, rankings)
        contest = ContestMetadata(
            contest_code="START254D", contest_name="Starters 254",
            start_date="2026-06-24 20:00 IST", end_date="2026-06-24 22:00 IST",
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = generate_report(contest, roster, match_result, output_dir=Path(tmp))
            wb = load_workbook(path)
            ws = wb["Contest Report"]
            self.assertEqual(ws.cell(row=4, column=1).value, "S.No")
            self.assertEqual(ws.cell(row=5, column=1).value, 1)
            self.assertEqual(ws.cell(row=5, column=2).value, "711524BCS001")
            self.assertEqual(ws.cell(row=5, column=4).value, "CSE")
            self.assertEqual(ws.cell(row=5, column=5).value, "B")
            self.assertEqual(ws.cell(row=5, column=6).value, "24.06.2026")
            self.assertEqual(ws.cell(row=5, column=8).value, 86485)
            self.assertEqual(ws.cell(row=5, column=9).value, 1022)
            self.assertEqual(ws.cell(row=5, column=10).value, "Div 4")
            self.assertEqual(ws.cell(row=5, column=11).value, "Yes")
            self.assertEqual(ws.cell(row=5, column=12).value, None)


if __name__ == "__main__":
    unittest.main()

class TestDerivedReportFields(unittest.TestCase):
    def test_score_derives_problems_and_division(self):
        roster = StudentRoster()
        roster.students = [Student(name="Test", username="user1", original_username="user1")]
        rankings = [RankingEntry(rank=1, username="user1", display_name="Test", problems_solved=None, total_score=400.0, rating_after=1500, rating_change=10, rating_before=1490, source_contest="START253A")]
        match_result = match_students(roster, rankings)
        contest = ContestMetadata(contest_code="START253A", contest_name="Starters 253")
        with tempfile.TemporaryDirectory() as tmp:
            path = generate_report(contest, roster, match_result, output_dir=Path(tmp))
            wb = load_workbook(path)
            ws = wb["Contest Report"]
            row = 5
            self.assertEqual(ws.cell(row=row, column=7).value, 4)
            self.assertEqual(ws.cell(row=row, column=10).value, "Div 1")
