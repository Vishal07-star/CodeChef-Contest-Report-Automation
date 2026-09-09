"""
email_report.py
----------------
Optional: emails the generated Excel report to the teacher.

Credentials come ONLY from environment variables / GitHub Secrets:
    SMTP_EMAIL      - the sending Gmail address
    SMTP_PASSWORD   - a Gmail App Password (NOT your normal Gmail password)
    TEACHER_EMAIL   - recipient address(es), comma-separated

If any of these are missing, send_report_email() simply skips sending and
returns False -- it never raises, so a missing email configuration never
blocks the Excel report from being generated. See README "Gmail App
Password setup" for how to create SMTP_PASSWORD.
"""

from __future__ import annotations

import smtplib
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import List, Optional

import config
from codechef import ContestMetadata
from matching import MatchResult
from utils import logger


def _build_summary_body(contest: ContestMetadata, match_result: MatchResult) -> str:
    participants = match_result.participants()
    top_student = "N/A"
    if participants:
        best = min(
            (m for m in participants if m.entry and m.entry.rank is not None),
            key=lambda m: m.entry.rank,
            default=None,
        )
        if best:
            top_student = f"{best.name} (Rank {best.entry.rank})"

    solved_values = [
        m.entry.problems_solved for m in participants
        if m.entry and m.entry.problems_solved is not None
    ]
    avg_solved = round(sum(solved_values) / len(solved_values), 2) if solved_values else "N/A"

    return (
        f"Contest: {contest.contest_name} ({contest.contest_code})\n"
        f"Participants: {match_result.participants_count}\n"
        f"Did Not Participate: {match_result.non_participants_count}\n"
        f"Average solved: {avg_solved}\n"
        f"Top student: {top_student}\n\n"
        f"The full report is attached as an Excel file.\n"
    )


def send_report_email(
    contest: ContestMetadata,
    match_result: MatchResult,
    attachment_path: Path,
    recipients: Optional[List[str]] = None,
) -> bool:
    """
    Send the report by email. Returns True if sent, False if skipped
    (e.g. not configured) or failed. Never raises -- a failed/skipped email
    must never be treated as a fatal error for the overall run.
    """
    if not config.email_is_configured():
        logger.info(
            "Email not configured (SMTP_EMAIL / SMTP_PASSWORD / TEACHER_EMAIL "
            "not all set) -- skipping email step."
        )
        return False

    recipients = recipients or [
        addr.strip() for addr in config.TEACHER_EMAIL.split(",") if addr.strip()
    ]
    if not recipients:
        logger.warning("TEACHER_EMAIL was set but contained no valid address(es). Skipping email.")
        return False

    attachment_path = Path(attachment_path)
    if not attachment_path.exists():
        logger.error("Cannot email report: file not found at %s", attachment_path)
        return False

    msg = MIMEMultipart()
    msg["Subject"] = f"CodeChef Contest Report - {contest.contest_name}"
    msg["From"] = config.SMTP_EMAIL
    msg["To"] = ", ".join(recipients)
    msg.attach(MIMEText(_build_summary_body(contest, match_result), "plain"))

    with open(attachment_path, "rb") as f:
        part = MIMEApplication(f.read(), Name=attachment_path.name)
    part["Content-Disposition"] = f'attachment; filename="{attachment_path.name}"'
    msg.attach(part)

    try:
        with smtplib.SMTP(config.SMTP_SERVER, config.SMTP_PORT, timeout=30) as server:
            server.starttls()
            server.login(config.SMTP_EMAIL, config.SMTP_PASSWORD)
            server.sendmail(config.SMTP_EMAIL, recipients, msg.as_string())
    except smtplib.SMTPAuthenticationError:
        logger.error(
            "Email authentication failed. If using Gmail, make sure SMTP_PASSWORD is "
            "a Gmail App Password, not your normal account password (see README)."
        )
        return False
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to send email: %s", exc)
        return False

    logger.info("Report emailed to: %s", ", ".join(recipients))
    return True
