# -*- coding: utf-8 -*-
import os
import subprocess
import sys
import tempfile
import unittest

import pytest

pytestmark = pytest.mark.production_db


class ExportCompareCardTests(unittest.TestCase):
    def test_export_jianzhun(self):
        with tempfile.TemporaryDirectory() as tmp:
            proc = subprocess.run(
                [sys.executable, "scripts/export_compare_card.py", "建準", "--out", tmp],
                capture_output=True,
                text=True,
                cwd=os.path.dirname(os.path.dirname(__file__)),
            )
            self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)
            self.assertTrue(os.path.isfile(os.path.join(tmp, "2421_card.png")))
            self.assertTrue(os.path.getsize(os.path.join(tmp, "2421_card.png")) > 50_000)
            self.assertTrue(os.path.isfile(os.path.join(tmp, "2421_rows.tsv")))


if __name__ == "__main__":
    unittest.main()
