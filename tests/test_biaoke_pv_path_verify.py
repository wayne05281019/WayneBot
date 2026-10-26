# -*- coding: utf-8 -*-
"""價量路徑靜默骨架：建表／空跑不炸；非買訊。"""
from __future__ import annotations

import os
import sqlite3
import tempfile

from biaoke_pv_path_verify import KINDS, ensure_tables, rates_summary, run_skeleton


def test_ensure_tables_and_empty_rates():
    with tempfile.TemporaryDirectory() as td:
        db = os.path.join(td, "t.db")
        ensure_tables(db)
        con = sqlite3.connect(db)
        try:
            n = con.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE name='biaoke_pv_path_events'"
            ).fetchone()[0]
        finally:
            con.close()
        assert n == 1
        for kind in KINDS:
            s = rates_summary(db, kind=kind)
            assert s["kind"] == kind
            assert s["variants"] == {}


def test_run_skeleton_no_json():
    with tempfile.TemporaryDirectory() as td:
        db = os.path.join(td, "t.db")
        out = run_skeleton(db)
        assert out.get("ok") is True
        assert out.get("face_default") is False
        assert out.get("imported_rows") == 0
