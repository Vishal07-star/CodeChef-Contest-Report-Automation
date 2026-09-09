"""
excel_report.py
---------------
Builds the final, teacher-facing Excel workbook using openpyxl.

Sheets:
  1. Contest Report   - one row per student, rank/score/rating/participation
  2. Problem Details   - per-problem solved grid (best-effort, see codechef.py)
  3. Not Participated  - students who did not appear in the ranklist
  4. Contest Info      - contest metadata + summary counts
  5. Students          - the original roster, as loaded from students.csv
"""

from __future__ import annotations

from pathlib import Path
import re
from typing import List

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

import config
from codechef import ContestMetadata, derive_problems_solved_from_score, division_label
from exceptions import ReportGenerationError
from matching import MatchResult
from utils import StudentRoster, logger, now_iso, safe_filename

# ---------------------------------------------------------------------------
# Shared styling constants
# ---------------------------------------------------------------------------
HEADER_FILL = PatternFill(start_color="1F4E78", end_color="1F4E78", fill_type="solid")
HEADER_FONT = Font(color="FFFFFF", bold=True)
TITLE_FONT = Font(bold=True, size=14, color="1F4E78")
SUBTITLE_FONT = Font(italic=True, size=10, color="595959")
SUMMARY_LABEL_FONT = Font(bold=True)
CENTER = Alignment(horizontal="center", vertical="center")
LEFT = Alignment(horizontal="left", vertical="center")
THIN_BORDER = Border(
    left=Side(style="thin", color="D9D9D9"),
    right=Side(style="thin", color="D9D9D9"),
    top=Side(style="thin", color="D9D9D9"),
    bottom=Side(style="thin", color="D9D9D9"),
)
NOT_PARTICIPATED_FILL = PatternFill(start_color="FFF2CC", end_color="FFF2CC", fill_type="solid")
USERNAME_NOT_FOUND_FILL = PatternFill(start_color="FFF2CC", end_color="FFF2CC", fill_type="solid")
SOLVED_FILL = PatternFill(start_color="E2EFDA", end_color="E2EFDA", fill_type="solid")
NOT_SOLVED_FILL = PatternFill(start_color="FCE4E4", end_color="FCE4E4", fill_type="solid")


def _style_header_row(ws: Worksheet, row: int, num_cols: int) -> None:
    for col in range(1, num_cols + 1):
        cell = ws.cell(row=row, column=col)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = CENTER
        cell.border = THIN_BORDER


def _autosize_columns(ws: Worksheet, min_width: int = 10, max_width: int = 45) -> None:
    widths = {}
    for row in ws.iter_rows():
        for cell in row:
            if cell.value is None:
                continue
            col = cell.column_letter
            length = len(str(cell.value))
            widths[col] = max(widths.get(col, 0), length)
    for col, width in widths.items():
        ws.column_dimensions[col].width = max(min_width, min(max_width, width + 2))


def _write_table(ws: Worksheet, start_row: int, headers: List[str]) -> int:
    """Write a header row starting at start_row, styled, and return that row number."""
    for col, header in enumerate(headers, start=1):
        ws.cell(row=start_row, column=col, value=header)
    _style_header_row(ws, start_row, len(headers))
    return start_row


# ---------------------------------------------------------------------------
# Sheet 1: Contest Report
# ---------------------------------------------------------------------------

def _format_contest_date(start_date: str) -> str:
    """Format a known contest start date as DD.MM.YYYY for the teacher sheet."""
    if not start_date or str(start_date).strip().lower() == "unknown":
        return ""
    text = str(start_date).strip()
    match = re.match(r"^(\d{4})-(\d{2})-(\d{2})", text)
    if match:
        return f"{match.group(3)}.{match.group(2)}.{match.group(1)}"
    return text


def _build_contest_report_sheet(
    wb: Workbook, match_result: MatchResult, roster: StudentRoster, contest: ContestMetadata,
    rating_type: str = "codechef"
) -> None:
    """Build the teacher-facing sheet in the college attendance-sheet format.

    The first sheet intentionally mirrors the reference format:
    S.No | Register Number | Name of the student | Department | Section | DATE |
    Total Problems solved | Global Rank | Contest Rating |
    Div 1, Div 2, Div 3, Div 4 | ATTENDED Yes/No | IF NO Reason

    Register number, department and section are optional in students.csv. The
    original two-column Name,Username file continues to work; those cells are
    simply blank until the optional columns are supplied.
    """
    ws = wb.active
    ws.title = "Contest Report"

    headers = [
        "S.No",
        "Register Number",
        "Name of the student",
        "Department",
        "Section",
        "DATE",
        "Total Problems solved",
        "Global Rank",
        "Contest Rating",
        "Div 1, Div 2, Div 3, Div 4",
        "ATTENDED Yes/No",
        "IF NO Reason",
    ]

    # Reference-sheet style: simple black borders, wrapped bold header, and a
    # light green identity block for student details.
    reference_header_font = Font(name="Times New Roman", bold=True, size=12)
    reference_body_font = Font(name="Times New Roman", size=11)
    reference_header_alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    reference_body_alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    identity_fill = PatternFill(start_color="A9D18E", end_color="A9D18E", fill_type="solid")
    attended_fill = PatternFill(start_color="E2F0D9", end_color="E2F0D9", fill_type="solid")

    # Keep a small title row while making the actual data table start at row 3.
    ws["A1"] = f"CodeChef Contest Report - {contest.contest_name}"
    ws["A1"].font = TITLE_FONT
    ws["A2"] = f"Report generated: {now_iso()}"
    ws["A2"].font = SUBTITLE_FONT

    header_row = 4
    for col, header in enumerate(headers, start=1):
        cell = ws.cell(row=header_row, column=col, value=header)
        cell.font = reference_header_font
        cell.alignment = reference_header_alignment
        cell.border = Border(
            left=Side(style="thin", color="000000"),
            right=Side(style="thin", color="000000"),
            top=Side(style="thin", color="000000"),
            bottom=Side(style="thin", color="000000"),
        )

    # MatchResult.matched is deliberately in the same order as roster.students.
    by_username = {m.username: m for m in match_result.matched}
    contest_date = _format_contest_date(contest.start_date)
    is_dsa = rating_type.lower() == "dsa"

    for index, student in enumerate(roster.students, start=1):
        m = by_username.get(student.username)
        entry = m.entry if m else None
        participated = bool(m and m.participated)

        # The ranklist score is the reliable report input: 400 points means
        # 4 solved problems, 300 means 3, and so on.
        problems_solved = (
            derive_problems_solved_from_score(entry.total_score)
            if entry and entry.total_score is not None
            else entry.problems_solved if entry else None
        )
        rank = entry.rank if entry else None
        rating = entry.rating_after if (entry and entry.rating_after is not None) else ("Pending" if participated else "")
        division = division_label(entry.source_contest) if entry else ""
        if division.startswith("Division "):
            division = division.replace("Division ", "Div ", 1)

        if participated:
            attended = "Yes"
            reason = ""
        elif m and m.duplicate:
            attended = "No"
            reason = "Duplicate username"
        elif m and not m.username_valid:
            attended = "No"
            reason = "Username Not Found"
        else:
            attended = "No"
            reason = "Did Not Participate"

        values = [
            index,
            student.register_number,
            student.name,
            student.department,
            student.section,
            contest_date,
            problems_solved if problems_solved is not None else "",
            rank if rank is not None else "",
            rating,
            division,
            attended,
            reason,
        ]

        for col, value in enumerate(values, start=1):
            cell = ws.cell(row=header_row + index, column=col, value=value)
            cell.font = reference_body_font
            cell.alignment = reference_body_alignment
            cell.border = Border(
                left=Side(style="thin", color="000000"),
                right=Side(style="thin", color="000000"),
                top=Side(style="thin", color="000000"),
                bottom=Side(style="thin", color="000000"),
            )
            if 2 <= col <= 5 and participated:
                cell.fill = identity_fill
            elif not participated:
                cell.fill = NOT_PARTICIPATED_FILL
            elif col == 11:
                cell.fill = attended_fill

    last_row = header_row + len(roster.students)
    ws.freeze_panes = "A5"
    ws.auto_filter.ref = f"A{header_row}:L{max(last_row, header_row)}"
    ws.row_dimensions[header_row].height = 48

    widths = {
        "A": 8, "B": 18, "C": 28, "D": 14, "E": 10, "F": 14,
        "G": 20, "H": 14, "I": 16, "J": 22, "K": 16, "L": 24,
    }
    for col, width in widths.items():
        ws.column_dimensions[col].width = width
    ws.sheet_view.showGridLines = True
    ws.page_setup.orientation = "landscape"
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True


# ---------------------------------------------------------------------------
# Sheet 2: Problem Details
# ---------------------------------------------------------------------------
def _build_problem_details_sheet(wb: Workbook, match_result: MatchResult, problem_wise: dict) -> None:
    ws = wb.create_sheet("Problem Details")

    problem_codes = sorted({p for pdata in problem_wise.values() for p in pdata.keys()})

    ws["A1"] = "Problem Details"
    ws["A1"].font = TITLE_FONT
    if not problem_wise:
        ws["A2"] = (
            "Per-problem solve data is not available from CodeChef's public "
            "rankings API. Only the total 'Problems Solved' count (shown on the "
            "Contest Report sheet) is available. See codechef.py for details."
        )
        ws["A2"].font = SUBTITLE_FONT
        header_row = 4
    else:
        header_row = 2

    headers = ["Student Name", "CodeChef Username"] + problem_codes + ["Total Solved"]
    _write_table(ws, header_row, headers)

    r = header_row + 1
    for m in sorted(match_result.matched, key=lambda m: m.name.lower()):
        row_values = [m.name, m.original_username]
        per_problem = problem_wise.get(m.username, {})
        total_solved = 0
        for code in problem_codes:
            status = per_problem.get(code)
            if status is None:
                row_values.append("Not available")
            else:
                row_values.append(status)
                if status == "Solved":
                    total_solved += 1
        if problem_codes:
            row_values.append(total_solved)
        elif m.entry and m.entry.problems_solved is not None:
            row_values.append(m.entry.problems_solved)
        elif m.entry and m.entry.total_score is not None:
            row_values.append(derive_problems_solved_from_score(m.entry.total_score))
        else:
            row_values.append("N/A" if not m.participated else 0)

        for col, value in enumerate(row_values, start=1):
            cell = ws.cell(row=r, column=col, value=value)
            cell.border = THIN_BORDER
            cell.alignment = CENTER if col > 2 else LEFT
            if value == "Solved":
                cell.fill = SOLVED_FILL
            elif value == "Not Solved":
                cell.fill = NOT_SOLVED_FILL
        r += 1

    last_row = r - 1
    if last_row >= header_row + 1:
        ws.freeze_panes = ws.cell(row=header_row + 1, column=1).coordinate
        ws.auto_filter.ref = f"A{header_row}:{get_column_letter(len(headers))}{last_row}"

    _autosize_columns(ws)


# ---------------------------------------------------------------------------
# Sheet 3: Not Participated
# ---------------------------------------------------------------------------
def _build_not_participated_sheet(wb: Workbook, match_result: MatchResult) -> None:
    ws = wb.create_sheet("Not Participated")
    ws["A1"] = "Students Who Did Not Participate"
    ws["A1"].font = TITLE_FONT

    header_row = 3
    headers = ["Name", "Username", "Status"]
    _write_table(ws, header_row, headers)

    r = header_row + 1
    for m in match_result.non_participants():
        status = "Did Not Participate"
        if m.duplicate:
            status += " (Duplicate username in students.csv)"
        for col, value in enumerate([m.name, m.original_username, status], start=1):
            cell = ws.cell(row=r, column=col, value=value)
            cell.border = THIN_BORDER
        r += 1

    if r == header_row + 1:
        ws.cell(row=r, column=1, value="(Every student participated!)").font = SUBTITLE_FONT
        r += 1

    last_row = r - 1
    ws.freeze_panes = ws.cell(row=header_row + 1, column=1).coordinate
    if last_row >= header_row:
        ws.auto_filter.ref = f"A{header_row}:{get_column_letter(len(headers))}{max(last_row, header_row)}"

    _autosize_columns(ws)


# ---------------------------------------------------------------------------
# Sheet 4: Contest Info
# ---------------------------------------------------------------------------
def _build_contest_info_sheet(
    wb: Workbook, contest: ContestMetadata, roster: StudentRoster, match_result: MatchResult
) -> None:
    ws = wb.create_sheet("Contest Info")
    ws["A1"] = "Contest Info"
    ws["A1"].font = TITLE_FONT

    rows = [
        ("Contest Name", contest.contest_name),
        ("Contest Code", contest.contest_code),
        ("Contest URL", contest.contest_url),
        ("Contest Date", f"{contest.start_date} - {contest.end_date}"),
        ("Report Generation Time", now_iso()),
        ("Total Students", len(roster.students)),
        ("Participants", match_result.participants_count),
        ("Non-participants", match_result.non_participants_count),
        ("Username Not Found", match_result.username_not_found_count),
        ("Ambiguous duplicate usernames", match_result.ambiguous_count),
    ]
    r = 3
    for label, value in rows:
        ws.cell(row=r, column=1, value=label).font = SUMMARY_LABEL_FONT
        ws.cell(row=r, column=2, value=value)
        r += 1

    if match_result.duplicate_usernames_note():
        ws.cell(row=r + 1, column=1, value="Note:").font = SUMMARY_LABEL_FONT
        ws.cell(row=r + 1, column=2, value=match_result.duplicate_usernames_note())

    _autosize_columns(ws)


# ---------------------------------------------------------------------------
# Sheet 5: Students
# ---------------------------------------------------------------------------
def _build_students_sheet(wb: Workbook, roster: StudentRoster) -> None:
    ws = wb.create_sheet("Students")
    ws["A1"] = "Original Student List (students.csv)"
    ws["A1"].font = TITLE_FONT

    header_row = 3
    headers = ["Name", "Username"]
    _write_table(ws, header_row, headers)

    r = header_row + 1
    for s in roster.students:
        ws.cell(row=r, column=1, value=s.name).border = THIN_BORDER
        ws.cell(row=r, column=2, value=s.original_username).border = THIN_BORDER
        r += 1

    last_row = r - 1
    ws.freeze_panes = ws.cell(row=header_row + 1, column=1).coordinate
    if last_row >= header_row:
        ws.auto_filter.ref = f"A{header_row}:B{max(last_row, header_row)}"

    _autosize_columns(ws)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def generate_report(
    contest: ContestMetadata,
    roster: StudentRoster,
    match_result: MatchResult,
    problem_wise: dict | None = None,
    output_dir: Path = config.REPORTS_DIR,
    rating_type: str = "codechef",
) -> Path:
    """
    Build the full workbook and save it to
    reports/CodeChef_<CONTEST_CODE>_Report.xlsx for normal contests,
    or reports/DSA_<CONTEST_CODE>_Report.xlsx for DSA contests.

    Raises ReportGenerationError on any failure while building/saving.
    """
    problem_wise = problem_wise or {}
    try:
        wb = Workbook()
        _build_contest_report_sheet(wb, match_result, roster, contest, rating_type=rating_type)
        _build_problem_details_sheet(wb, match_result, problem_wise)
        _build_not_participated_sheet(wb, match_result)
        _build_contest_info_sheet(wb, contest, roster, match_result)
        _build_students_sheet(wb, roster)

        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        prefix = "DSA" if rating_type.lower() == "dsa" else "CodeChef"
        filename = f"{prefix}_{safe_filename(contest.contest_code)}_Report.xlsx"
        output_path = output_dir / filename
        wb.save(output_path)
    except Exception as exc:  # noqa: BLE001
        raise ReportGenerationError(f"Failed to generate Excel report: {exc}") from exc

    logger.info("Excel report generated: %s", output_path)
    return output_path
