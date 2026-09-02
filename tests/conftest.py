# -*- coding: utf-8 -*-
"""測試隔離：預設沒有任何測試碰得到真正的生產庫。

WAYNE_DB_PATH 預設是 data/wayne_market.db，也就是 Render 上那顆真的庫。
在加上這層之前，任何測試呼叫 config.get_db_path() 都會直接寫上去；
而且先跑的測試建出一顆空 schema 之後，後面靠 os.path.isfile 判斷
「有沒有庫可用」的測試就會誤判成有，改成拿空庫去比對真實數字而失敗。

需要真實資料的測試請掛 @pytest.mark.production_db（或模組層 pytestmark），
沒有生產規模的庫時會明確 skip 而不是假裝通過。
"""
from __future__ import annotations

import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# 在任何 fixture 動手腳之前先記下真正的庫在哪。
_PROD_DB = (
    os.environ.get("WAYNE_DB_PATH")
    or os.environ.get("DB_PATH")
    or os.path.join(ROOT, "data", "wayne_market.db")
)

# 空 schema 大概幾百 KB；生產庫是好幾百 MB。門檻要遠高於空 schema。
MIN_PRODUCTION_BYTES = 50 * 1024 * 1024


def production_db_path() -> str:
    return _PROD_DB


def production_db_size() -> int:
    try:
        return os.path.getsize(_PROD_DB)
    except OSError:
        return 0


def has_production_db() -> bool:
    return production_db_size() >= MIN_PRODUCTION_BYTES


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "production_db: 需要生產規模的 wayne_market.db（沒有就 skip）",
    )


@pytest.fixture(autouse=True)
def _db_path_guard(request, tmp_path, monkeypatch):
    """未標記的測試一律導向臨時庫；標記的才拿到真的庫。"""
    if request.node.get_closest_marker("production_db"):
        if not has_production_db():
            pytest.skip(
                f"需要生產規模的庫（{_PROD_DB} 目前 {production_db_size()} bytes）"
            )
        monkeypatch.setenv("WAYNE_DB_PATH", _PROD_DB)
        monkeypatch.delenv("DB_PATH", raising=False)
        yield
        return

    monkeypatch.setenv("WAYNE_DB_PATH", str(tmp_path / "isolated.db"))
    monkeypatch.delenv("DB_PATH", raising=False)
    yield


@pytest.fixture()
def production_db(request):
    """給 pytest 風格測試直接取路徑用；unittest.TestCase 請用模組層 pytestmark。"""
    if not request.node.get_closest_marker("production_db"):
        pytest.skip("此測試未標記 production_db")
    return _PROD_DB
