#!/usr/bin/env python3
"""
main.py
-------
CLI entry point for the CodeChef Contest Performance Reporting System.

Usage:
    python main.py --contest STARTERS200
    python main.py --contest https://www.codechef.com/STARTERS200
    python main.py --contest STARTERS200 --send-email
    python main.py --contest STARTERS200 --no-email
    python main.py --contest STARTERS200 --students-csv path/to/students.csv
    python main.py --help
"""

from __future__ import annotations

import argparse
import sys

import codechef
import config
import email_report
import excel_report
import matching
import utils
from exceptions import ContestReportError


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="main.py",
        description=(
            "Generate an Excel report of student performance in a CodeChef contest. "
            "Reads students from students.csv, fetches the public contest ranklist "
            "from CodeChef, and writes a formatted .xlsx report to reports/."
        ),
    )
    parser.add_argument(
        "--contest",
        required=True,
        help="Contest code (e.g. STARTERS200) or full CodeChef contest URL "
             "(e.g. https://www.codechef.com/STARTERS200).",
    )
    parser.add_argument(
        "--students-csv",
        default=str(config.STUDENTS_CSV_PATH),
        help=f"Path to the students CSV file (default: {config.STUDENTS_CSV_PATH}).",
    )
    parser.add_argument(
        "--output-dir",
        default=str(config.REPORTS_DIR),
        help=f"Directory to write the Excel report into (default: {config.REPORTS_DIR}).",
    )
    parser.add_argument(
        "--rankings-csv",
        help=("Use an exported rankings CSV instead of fetching CodeChef. The CSV must "
              "include Username, CodeChef Username, Handle, or Code; other report "
              "columns are optional."),
    )
    parser.add_argument(
        "--rating-type",
        choices=("codechef", "dsa"),
        default="codechef",
        help=("Which CodeChef rating graph to report. 'codechef' is the normal "
              "CodeChef rating (default); 'dsa' uses the separate DSA Rating "
              "graph and does not modify or replace the CodeChef rating."),
    )

    email_group = parser.add_mutually_exclusive_group()
    email_group.add_argument(
        "--send-email",
        action="store_true",
        help="Force-attempt to email the report (requires SMTP_EMAIL, SMTP_PASSWORD, "
             "TEACHER_EMAIL environment variables). Errors from email sending do not "
             "fail the overall run.",
    )
    email_group.add_argument(
        "--no-email",
        action="store_true",
        help="Never attempt to send an email, even if email environment variables are set.",
    )

    return parser


def run(argv=None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    logger = utils.setup_logging()

    try:
        contest_code = codechef.parse_contest_input(args.contest)
        logger.info("Processing contest: %s | Rating type: %s", contest_code, args.rating_type)

        roster = utils.load_students(args.students_csv)
        logger.info("Number of students loaded: %d", len(roster.students))

        rankings = (
            codechef.load_rankings_csv(args.rankings_csv)
            if args.rankings_csv
            else codechef.fetch_contest_rankings_browser(contest_code, roster.usernames(), rating_type=args.rating_type)
        )
        # Every username actually found in the ranklist gets one profile pass.
        # This runs after matching has completed for both browser and CSV
        # ranklists, and never uses a ranklist rating as a reason to skip.
        rankings = codechef.enrich_profile_ratings_browser(
            rankings, rating_type=args.rating_type
        )

        contest_meta = codechef.get_contest_metadata(contest_code, rankings)

        invalid_usernames = set()
        if not args.rankings_csv:
            requested_missing = [
                username for username in roster.usernames()
                if username not in {r.username for r in rankings}
            ]
            if requested_missing:
                invalid_usernames = codechef.find_invalid_usernames_browser(requested_missing)
                if invalid_usernames:
                    logger.info(
                        "Confirmed %d invalid/nonexistent CodeChef username(s): %s",
                        len(invalid_usernames), ", ".join(sorted(invalid_usernames)),
                    )

        match_result = matching.match_students(
            roster, rankings, invalid_usernames=invalid_usernames
        )
        logger.info(
            "Participants found: %d | Students not matched (did not participate): %d",
            match_result.participants_count,
            match_result.non_participants_count,
        )

        # Problems Solved is derived directly from Total Score (100 points per
        # solved problem for this report), so no extra per-student requests are
        # made for problem details.
        problem_wise = {}

        report_path = excel_report.generate_report(
            contest=contest_meta,
            roster=roster,
            match_result=match_result,
            problem_wise=problem_wise,
            output_dir=args.output_dir,
            rating_type=args.rating_type,
        )
        print(f"\nReport generated: {report_path}")

        should_email = args.send_email or (config.email_is_configured() and not args.no_email)
        if should_email:
            sent = email_report.send_report_email(contest_meta, match_result, report_path)
            if sent:
                print(f"Report emailed to: {config.TEACHER_EMAIL}")
                logger.info("Email sent successfully.")
            else:
                print("Email was not sent (skipped or failed). See logs/contest_report.log for details.")
                logger.info("Email not sent.")
        else:
            logger.info("Email step skipped (--no-email or email not configured).")

        return 0

    except ContestReportError as exc:
        logger.error(str(exc))
        print(f"\nError: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001 - final safety net, never crash silently
        logger.exception("Unexpected error")
        print(f"\nUnexpected error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(run())
