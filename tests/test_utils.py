"""
Tests for utils.py: username normalization and students.csv loading/validation.
"""

import tempfile
import unittest
from pathlib import Path

from exceptions import (
    StudentsFileEmptyError,
    StudentsFileInvalidColumnsError,
    StudentsFileMissingError,
)
from utils import load_students, normalize_username


class TestNormalizeUsername(unittest.TestCase):
    def test_lowercases(self):
        self.assertEqual(normalize_username("Rahul123"), "rahul123")

    def test_strips_whitespace(self):
        self.assertEqual(normalize_username("  rahul123  "), "rahul123")

    def test_strips_leading_at(self):
        self.assertEqual(normalize_username("@rahul123"), "rahul123")

    def test_none_returns_empty(self):
        self.assertEqual(normalize_username(None), "")


class TestLoadStudents(unittest.TestCase):
    def _write_csv(self, tmp_path: Path, content: str) -> Path:
        path = tmp_path / "students.csv"
        path.write_text(content, encoding="utf-8")
        return path

    def test_missing_file_raises(self):
        with self.assertRaises(StudentsFileMissingError):
            load_students(Path("/nonexistent/path/students.csv"))

    def test_empty_file_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write_csv(Path(tmp), "Name,Username\n")
            with self.assertRaises(StudentsFileEmptyError):
                load_students(path)

    def test_invalid_columns_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write_csv(Path(tmp), "FullName,Handle\nRahul,rahul123\n")
            with self.assertRaises(StudentsFileInvalidColumnsError):
                load_students(path)

    def test_valid_file_loads(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write_csv(
                Path(tmp),
                "Name,Username\nRahul,rahul123\nPriya,priya07\n",
            )
            roster = load_students(path)
            self.assertEqual(len(roster.students), 2)
            self.assertEqual(roster.students[0].username, "rahul123")

    def test_reference_format_name_column_loads(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write_csv(
                Path(tmp),
                "Sl. No.,Register Number,Name of the student,Department,Section,Username\n"
                "1,22CS001,Rahul Kumar,CSE,A,rahul123\n",
            )
            roster = load_students(path)
            self.assertEqual(len(roster.students), 1)
            self.assertEqual(roster.students[0].name, "Rahul Kumar")
            self.assertEqual(roster.students[0].register_number, "22CS001")

    def test_duplicate_usernames_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write_csv(
                Path(tmp),
                "Name,Username\nRahul,same_user\nPriya,same_user\n",
            )
            roster = load_students(path)
            self.assertIn("same_user", roster.duplicate_usernames)
            self.assertTrue(all(s.duplicate for s in roster.students))

    def test_row_with_missing_username_is_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write_csv(
                Path(tmp),
                "Name,Username\nRahul,rahul123\nNoUsername,\n",
            )
            roster = load_students(path)
            self.assertEqual(len(roster.students), 1)


if __name__ == "__main__":
    unittest.main()
