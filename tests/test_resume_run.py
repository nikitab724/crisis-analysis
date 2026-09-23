"""Performance updates can restore saved reports without erasing the archive."""

import importlib.util
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))


@unittest.skipUnless(importlib.util.find_spec('dotenv'), 'requires live launcher dependencies')
class ResumeRunTests(unittest.TestCase):
    def test_restores_only_data_and_counters_and_preserves_source(self):
        from run_pipeline import restore_run
        with TemporaryDirectory() as source, TemporaryDirectory() as destination:
            root = Path(source)
            (root/'filtered_posts.csv').write_text('text,country,state,city,disasters\nFlood,US,Texas,Austin,Flood\n')
            (root/'crisis_counts.csv').write_text('country,state,disasters,count\nUS,Texas,Flood,1\n')
            (root/'pipeline_status.json').write_text('{"posts_received":100}')
            (root/'unrelated.txt').write_text('Do not copy')
            original = {p.name: p.read_bytes() for p in root.iterdir()}
            restore_run(root, destination)
            self.assertEqual({p.name for p in Path(destination).iterdir()},
                             {'filtered_posts.csv', 'crisis_counts.csv', 'pipeline_status.json'})
            self.assertEqual(original, {p.name: p.read_bytes() for p in root.iterdir()})

    def test_invalid_archive_is_rejected_before_any_data_is_copied(self):
        from run_pipeline import restore_run
        with TemporaryDirectory() as source, TemporaryDirectory() as destination:
            (Path(source)/'filtered_posts.csv').write_text('wrong,columns\n1,2\n')
            with self.assertRaises(ValueError):
                restore_run(source, destination)
            self.assertEqual(list(Path(destination).iterdir()), [])


if __name__ == '__main__':
    unittest.main()
