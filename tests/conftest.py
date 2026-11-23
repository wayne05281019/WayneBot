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


def require_production_db() -> str:
    """給仍用 os.path.isfile 判斷的舊測試：沒有生產庫就 skip，有就回傳路徑。"""
    if not has_production_db():
        pytest.skip(
            f"需要生產規模的庫（{_PROD_DB} 目前 {production_db_size()} bytes）"
        )
    return _PROD_DB


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "production_db: 需要生產規模的 wayne_market.db（沒有就 skip）",
    )
    config.addinivalue_line(
        "markers",
        "network: 允許打外網（預設單元測 stub ISIN／MOPS／月表；不准掛死 smoke）",
    )
    config.addinivalue_line(
        "markers",
        "real_fresh_gate: 測 daily_quotes 完整日新鮮閘（不把 fresh 對齊列數）",
    )


@pytest.fixture(autouse=True)
def _stub_isin_universe_offline(request, monkeypatch):
    """單元測不准打 isin.twse.com.tw：空庫 ensure_stock_directory 會連抓 3 頁，
    每頁 timeout=25 → 幾百個測累積就把 smoke 卡死 70 分＋（見 #501）。
    需要真抓的測掛 @pytest.mark.network。
    """
    if request.node.get_closest_marker("production_db"):
        yield
        return
    if request.node.get_closest_marker("network"):
        yield
        return

    def _no_isin():
        return []

    monkeypatch.setattr("universe.fetch_isin_universe", _no_isin)
    # 有些路徑先 from universe import fetch_isin_universe 再叫
    try:
        import universe as _uni

        monkeypatch.setattr(_uni, "fetch_isin_universe", _no_isin)
    except Exception:
        pass
    try:
        import wayne_db as _wdb

        monkeypatch.setattr(
            _wdb,
            "fetch_isin_universe",
            _no_isin,
            raising=False,
        )
    except Exception:
        pass
    yield


@pytest.fixture(autouse=True)
def _stub_official_http_offline(request, monkeypatch):
    """單元測不准真打 MOPS／證交所月表。

    查股／介紹圖會 asyncio.to_thread(ensure_stock_fundamentals) 或同步 ensure；
    SSL 握手卡住時 requests timeout 不生效，asyncio 關 loop 再等 default
    executor join 300s（CI smoke --durations 多支卡在 ~300／500／900s，
    總長 142→180 分被 cancel；本機 faulthandler 對質過）。
    需要真抓掛 @pytest.mark.network（含 production_db 路徑）。
    """
    if request.node.get_closest_marker("network"):
        yield
        return

    def _no_json(*_a, **_k):
        return []

    def _no_bytes(*_a, **_k):
        return b""

    def _no_month(*_a, **_k):
        return []

    # _post_form＝MOPS ajax POST（timeout=60×3）；漏 stub 時空庫 ensure
    # 會連打數十次，CI smoke 卡在介紹圖／查股測（本機 durations 對質）。
    monkeypatch.setattr("fundamentals._get", _no_json, raising=False)
    monkeypatch.setattr("fundamentals._get_bytes", _no_bytes, raising=False)
    monkeypatch.setattr("fundamentals._post_form", _no_bytes, raising=False)
    try:
        import fundamentals as _fund

        monkeypatch.setattr(_fund, "_get", _no_json)
        monkeypatch.setattr(_fund, "_get_bytes", _no_bytes)
        monkeypatch.setattr(_fund, "_post_form", _no_bytes)
    except Exception:
        pass
    try:
        import biaoke_walk as _bw

        monkeypatch.setattr(_bw, "fetch_stock_month", _no_month, raising=False)
    except Exception:
        pass
    yield


@pytest.fixture(autouse=True)
def _db_path_guard(request, tmp_path, monkeypatch):
    """未標記的測試一律導向臨時庫；標記的才拿到真的庫。"""
    for key in (
        "TELEGRAM_CHAT_ID",
        "TG_CHAT_ID",
        "WAYNE_FAMILY_CHAT_IDS",
        "WAYNE_BROTHER_CHAT_ID",
        "TELEGRAM_BOT_TOKEN",
        "TG_BOT_TOKEN",
        "WAYNE_ALLOWLIST_EMPTY_CLOSED",
    ):
        monkeypatch.delenv(key, raising=False)
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
    monkeypatch.setenv("WAYNE_SKIP_ETF_NAV_REFRESH", "1")
    yield


@pytest.fixture()
def production_db(request):
    """給 pytest 風格測試直接取路徑用；unittest.TestCase 請用模組層 pytestmark。"""
    if not request.node.get_closest_marker("production_db"):
        pytest.skip("此測試未標記 production_db")
    return _PROD_DB
