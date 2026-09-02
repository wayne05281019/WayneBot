# -*- coding: utf-8 -*-
import os
import unittest

from config import get_db_path
from wayne_db import lookup_stocks


class LookupNameTests(unittest.TestCase):
    def test_jianzhun_resolves_to_2421(self):
        db = get_db_path()
        if not os.path.isfile(db):
            self.skipTest("no db")
        hits = lookup_stocks(db, "建準")
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["stock_id"], "2421")
        self.assertIn("建準", hits[0]["stock_name"])


if __name__ == "__main__":
    unittest.main()
