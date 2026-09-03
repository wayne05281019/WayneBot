# -*- coding: utf-8 -*-
"""測試不能碰到真正的生產庫。

WAYNE_DB_PATH 預設就是 Render 上那顆真的 wayne_market.db，
在 conftest 的隔離層之前，八個測試檔會直接往上面寫 schema；
先跑的測試建出空庫之後，靠 os.path.isfile 判斷有無庫的測試還會
誤判成「有庫」，拿空庫去比對真實數字而失敗。
"""
import os
import sqlite3
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from conftest import (  # noqa: E402
    MIN_PRODUCTION_BYTES,
    has_production_db,
    production_db_path,
)


def test_unmarked_test_gets_isolated_db_path():
    from config import get_db_path

    path = os.path.abspath(get_db_path())
    assert path != os.path.abspath(production_db_path())
    assert "isolated.db" in os.path.basename(path)


def test_writing_the_db_does_not_touch_production():
    """真的寫下去，確認落點是臨時檔。"""
    from config import get_db_path

    path = get_db_path()
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE canary (x INTEGER)")
    conn.execute("INSERT INTO canary VALUES (1)")
    conn.commit()
    conn.close()

    assert os.path.isfile(path)
    assert os.path.abspath(path) != os.path.abspath(production_db_path())


def test_each_test_gets_a_fresh_db():
    """上一個測試寫的 canary 不該留到這裡。"""
    from config import get_db_path

    path = get_db_path()
    if not os.path.isfile(path):
        return
    conn = sqlite3.connect(path)
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    conn.close()
    assert "canary" not in names


def test_legacy_db_path_env_is_cleared():
    """DB_PATH 是 get_db_path 的第二順位，也得一起隔離掉。"""
    assert os.environ.get("DB_PATH") in (None, "")


@pytest.mark.production_db
def test_marked_test_receives_production_db():
    from config import get_db_path

    assert os.path.abspath(get_db_path()) == os.path.abspath(production_db_path())
    assert os.path.getsize(get_db_path()) >= MIN_PRODUCTION_BYTES


def test_production_threshold_rejects_empty_schema(tmp_path):
    """空 schema 幾百 KB 就會騙過 os.path.isfile，門檻必須遠高於它。"""
    from wayne_db import ensure_core_schema

    empty = str(tmp_path / "empty.db")
    ensure_core_schema(empty)
    assert os.path.getsize(empty) < MIN_PRODUCTION_BYTES


def test_has_production_db_matches_size_rule():
    expected = os.path.getsize(production_db_path()) >= MIN_PRODUCTION_BYTES if os.path.isfile(
        production_db_path()
    ) else False
    assert has_production_db() is expected
