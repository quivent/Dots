import tempfile
from pathlib import Path
import unittest
from crew_work_report import read_report, write_report, report_path


class WorkReportTests(unittest.TestCase):
    def test_one_atomic_report_preserves_source_time_and_clears_old_blocker(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            first=write_report(root,'iris','blocked',{'focus':'Test a seam','blocker':'Missing input'})
            self.assertEqual(read_report(root,'iris')['reportedAt'],first['reportedAt'])
            second=write_report(root,'iris','checkpoint',{'focus':'Seam tested','artifact':'production/iris/receipt.json'})
            self.assertEqual(read_report(root,'iris')['blocker'],'')
            self.assertEqual(read_report(root,'iris')['reportedAt'],second['reportedAt'])
            self.assertEqual(len(list(root.glob('*.json'))),1)

    def test_paths_symlinks_and_oversized_input_are_not_published(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            with self.assertRaises(ValueError): report_path(root,'../auth')
            secret=root/'private';secret.write_text('not a report')
            (root/'iris.json').symlink_to(secret)
            self.assertIsNone(read_report(root,'iris'))
            (root/'iris.json').unlink();(root/'iris.json').write_text('x'*9000)
            self.assertIsNone(read_report(root,'iris'))


if __name__=='__main__':unittest.main()
