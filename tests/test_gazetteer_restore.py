"""Regression tests for extracting data without replaying a cluster's SQL."""

from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from prepare_gazetteer_restore import COPY_HEADER, prepare_restore  # noqa: E402

CITY = "4671654\tAustin\t['Austin']\tUS\tTX\t30.26715\t-97.74306\tPPLA\t931830\n"
STATE = "4736286\tTexas\t['Texas']\tUS\tTX\t31.25044\t-99.25061\tADM1\t22875689\n"
MOUNTAIN = "1\tMountain\t\\N\tUS\tTX\t30\t-97\tMT\t0\n"


class GazetteerRestoreTests(unittest.TestCase):
    def test_extracts_only_lookup_data_and_preserves_copy_escaping(self):
        with TemporaryDirectory() as directory:
            backup, output = Path(directory) / "source.backup", Path(directory) / "restore.sql"
            backup_text = "CREATE ROLE do_not_copy;\nCOPY auth.users (secret) FROM stdin;\nprivate-value\n\\.\n"
            backup_text += COPY_HEADER + "\n" + CITY + STATE + MOUNTAIN + "\\.\nDROP TABLE unrelated;\n"
            backup.write_text(backup_text)
            report = prepare_restore(backup, output)
            restored = output.read_text()
            self.assertEqual(report["source_rows"], 3)
            self.assertEqual(report["restore_rows"], 2)
            self.assertIn(CITY + STATE, restored)
            self.assertNotIn(MOUNTAIN, restored)
            for excluded in ("private-value", "do_not_copy", "DROP TABLE", "auth.users"):
                self.assertNotIn(excluded, restored)
            self.assertEqual(backup.read_text(), backup_text)

    def test_full_mode_preserves_other_feature_types(self):
        with TemporaryDirectory() as directory:
            backup, output = Path(directory) / "source.backup", Path(directory) / "restore.sql"
            backup.write_text(COPY_HEADER + "\n" + CITY + MOUNTAIN + "\\.\n")
            self.assertEqual(prepare_restore(backup, output, all_features=True)["restore_rows"], 2)
            self.assertIn(MOUNTAIN, output.read_text())

    def test_never_overwrites_an_existing_output(self):
        with TemporaryDirectory() as directory:
            backup, output = Path(directory) / "source.backup", Path(directory) / "restore.sql"
            backup.write_text(COPY_HEADER + "\n" + CITY + "\\.\n")
            output.write_text("preserve existing restore\n")
            with self.assertRaises(FileExistsError):
                prepare_restore(backup, output)
            self.assertEqual(output.read_text(), "preserve existing restore\n")

    def test_invalid_or_incomplete_data_leaves_no_output(self):
        cases = (COPY_HEADER + "\n" + CITY,
                 COPY_HEADER + "\ninvalid\n\\.\n",
                 COPY_HEADER.replace("population", "unexpected_column") + "\n" + CITY + "\\.\n",
                 "SELECT 1;\n")
        for contents in cases:
            with self.subTest(contents=contents), TemporaryDirectory() as directory:
                backup, output = Path(directory) / "source.backup", Path(directory) / "restore.sql"
                backup.write_text(contents)
                with self.assertRaises(ValueError):
                    prepare_restore(backup, output)
                self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
