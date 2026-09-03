# -*- coding: utf-8 -*-
"""/health 誠實回報：行程能否服務決定狀態碼，資料新鮮度只出現在欄位裡。

刻意不讓資料過期把 /health 變紅——Render 健檢失敗會重啟，
而重啟修不了資料管線，只會把互動 bot 一起弄掉。
"""
import importlib
import json
import os
import sqlite3
import sys
import threading
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from http.server import HTTPServer

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _seed_db(path):
    """用真的 schema，才會走到真的資料狀態查詢路徑。"""
    from wayne_db import ensure_core_schema

    ensure_core_schema(path)
    conn = sqlite3.connect(path)
    conn.execute(
        "INSERT INTO daily_quotes (date, stock_id, stock_name, market, open, high, low,"
        " close, volume, turnover_k, pct_change, avg_price)"
        " VALUES ('20260902', '2330', '台積電', 'TWSE', 1000, 1010, 990, 1000, 5000, 5000, 0.5, 1000)"
    )
    conn.commit()
    conn.close()


@pytest.fixture()
def serve(tmp_path, monkeypatch):
    """起一個真的 HTTP server，用真的 HTTP 請求驗狀態碼。"""
    db = str(tmp_path / "wayne.db")
    _seed_db(db)
    monkeypatch.setenv("WAYNE_DB_PATH", db)
    monkeypatch.setenv("WAYNE_BOOT_GRACE_SECONDS", "0")

    import main

    importlib.reload(main)
    main._PROCESS_STARTED_AT = 0.0  # 直接跳過啟動寬限

    httpd = HTTPServer(("127.0.0.1", 0), main.HealthHandler)
    port = httpd.server_address[1]
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()

    def _get(route):
        url = f"http://127.0.0.1:{port}{route}"
        try:
            with urllib.request.urlopen(url, timeout=10) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode("utf-8"))

    try:
        yield _get, db, main
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_health_200_when_process_can_serve(serve):
    get, db, main = serve
    code, body = get("/health")
    assert code == 200
    assert body["serving"] is True
    assert body["ok"] is True
    assert body["status"] == "healthy"
    assert body["db_ok"] is True


def test_health_reports_data_staleness_without_failing(serve):
    """資料沒對齊時 data_ok=False，但狀態碼仍是 200。"""
    get, db, main = serve
    code, body = get("/health")
    assert code == 200
    assert "data_ok" in body
    assert body["data_ok"] is False  # 種的假庫不可能對齊融合日
    assert body["serving"] is True


def test_health_503_when_db_unreadable(serve, monkeypatch):
    get, db, main = serve
    monkeypatch.setenv("WAYNE_DB_PATH", str(db) + ".gone")
    code, body = get("/health")
    assert code == 503
    assert body["serving"] is False
    assert body["ok"] is False
    assert body["status"] == "unhealthy"
    assert any("資料庫" in r for r in body["serving_reasons"])


def test_health_503_when_polling_heartbeat_stale(serve):
    get, db, main = serve
    from ops_watchdog import HEARTBEAT_POLLING, ensure_ops_tables

    ensure_ops_tables(db)
    stale = (datetime.now() - timedelta(hours=3)).isoformat(timespec="seconds")
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT OR REPLACE INTO ops_heartbeat(kind, beat_at, note) VALUES (?, ?, '')",
        (HEARTBEAT_POLLING, stale),
    )
    conn.commit()
    conn.close()

    code, body = get("/health")
    assert code == 503
    assert body["polling_alive"] is False
    assert any("輪詢" in r for r in body["serving_reasons"])


def test_health_200_when_polling_heartbeat_fresh(serve):
    get, db, main = serve
    from ops_watchdog import HEARTBEAT_POLLING, record_heartbeat

    record_heartbeat(db, HEARTBEAT_POLLING)
    code, body = get("/health")
    assert code == 200
    assert body["polling_alive"] is True


def test_boot_grace_keeps_health_green(serve, monkeypatch):
    """冷啟動抓 Release DB 期間不能回 503，否則 Render 會重啟成死循環。"""
    get, db, main = serve
    monkeypatch.setenv("WAYNE_DB_PATH", str(db) + ".gone")
    monkeypatch.setenv("WAYNE_BOOT_GRACE_SECONDS", "3600")
    import time as _time

    main._PROCESS_STARTED_AT = _time.time()
    code, body = get("/health")
    assert code == 200
    assert body["serving"] is True
    assert body["booting"] is True


def test_ready_503_when_data_not_ready(serve):
    get, db, main = serve
    code, body = get("/ready")
    assert code == 503
    assert body["ready"] is False
    assert "watchdog" in body


def test_root_route_matches_health(serve):
    get, db, main = serve
    code_a, body_a = get("/")
    code_b, body_b = get("/health")
    assert code_a == code_b
    assert body_a["serving"] == body_b["serving"]


def test_health_never_claims_healthy_while_not_serving(serve, monkeypatch):
    get, db, main = serve
    monkeypatch.setenv("WAYNE_DB_PATH", str(db) + ".gone")
    code, body = get("/health")
    assert not (body["status"] == "healthy" and body["serving"] is False)
    assert body["ok"] == body["serving"]


def test_health_survives_data_layer_exception(serve, monkeypatch):
    """資料狀態算不出來時不能 500，也不能假裝資料是好的。"""
    get, db, main = serve
    import automation_health

    def _boom(*a, **k):
        raise RuntimeError("audit exploded")

    monkeypatch.setattr(automation_health, "health_payload", _boom)
    code, body = get("/health")
    assert code == 200
    assert body["data_ok"] is False
    assert "audit exploded" in body.get("data_error", "")
