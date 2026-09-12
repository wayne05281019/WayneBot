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
from http.server import HTTPServer, ThreadingHTTPServer

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

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), main.HealthHandler)
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
    assert "git_sha" in body
    assert "stt_ok" in body
    assert body["stt_ok"] in (True, False)
    assert "biaoke_live_ok" in body
    assert body["biaoke_live_ok"] in (True, False)
    assert body["cmoney_ok"] in (True, False)
    assert "cmoney_comment_http" in body
    assert "biaoke_n" in body
    assert "biaoke_replies" in body
    assert "biaoke_latest_id" in body
    assert "biaoke_latest_at" in body
    assert "tx_15_n" in body
    assert "tx_zip_n" in body
    assert "tx_night_high" in body
    assert body["tx_15_n"] == 0


def test_health_cmoney_ok_follows_env_without_leaking_token(serve, monkeypatch):
    get, db, main = serve
    monkeypatch.delenv("CMONEY_AUTH_TOKEN", raising=False)
    code, body = get("/health")
    assert code == 200
    assert body["cmoney_ok"] is False
    monkeypatch.setenv("CMONEY_AUTH_TOKEN", "not-a-real-token-xyz")
    code, body = get("/health")
    assert body["cmoney_ok"] is True
    dumped = json.dumps(body, ensure_ascii=False)
    assert "not-a-real-token-xyz" not in dumped
    assert "Bearer" not in dumped


def test_health_reports_latest_biaoke_post(serve):
    get, db, main = serve
    from biaoke_desk import upsert_biaoke_posts

    upsert_biaoke_posts(
        db,
        [
            {
                "id": "184545002",
                "n": 1,
                "date": "2026-09-11",
                "time": "17:49",
                "kind": "post",
                "tags": [],
                "text": "1. 台指期夜盤15分鐘線",
            }
        ],
    )
    main._HEALTH_DATA_CACHE["at"] = 0.0
    main._HEALTH_DATA_CACHE["payload"] = None
    code, body = get("/health")
    assert code == 200
    assert body["biaoke_latest_id"] == "184545002"
    assert "2026-09-11" in body["biaoke_latest_at"]
    assert "17:49" in body["biaoke_latest_at"]
    dumped = json.dumps(body, ensure_ascii=False)
    assert "Bearer" not in dumped


def test_health_reports_tx_night_cover(serve):
    get, db, main = serve
    from kline_hop import save_minute_bars
    from taifex_ticks import _mark_zip

    bars = []
    t = 15 * 60
    while t <= 16 * 60 + 45:
        hh, mm = divmod(t, 60)
        bars.append(
            {
                "t": f"20260911{hh:02d}{mm:02d}",
                "o": 46300,
                "h": 46400,
                "l": 46200,
                "c": 46350,
                "v": 1,
            }
        )
        t += 15
    bars.append(
        {
            "t": "202609120000",
            "o": 46600,
            "h": 46663,
            "l": 46580,
            "c": 46650,
            "v": 1,
        }
    )
    bars.append(
        {
            "t": "202609120445",
            "o": 46050,
            "h": 46100,
            "l": 46041,
            "c": 46080,
            "v": 1,
        }
    )
    save_minute_bars("TX", "15", bars, db, source="taifex")
    _mark_zip(db, "20260914", len(bars))
    main._HEALTH_DATA_CACHE["at"] = 0.0
    main._HEALTH_DATA_CACHE["payload"] = None
    code, body = get("/health")
    assert code == 200
    assert body["tx_15_n"] >= 8
    assert body["tx_zip_n"] >= 1
    assert body["tx_night_high"] == "46663"
    assert body["tx_night_low"] == "46041"
    assert body["tx_night_date"] == "2026-09-11"
    dumped = json.dumps(body, ensure_ascii=False)
    assert "Bearer" not in dumped


def test_code_revision_reads_render_commit(monkeypatch):
    import main as main_mod

    monkeypatch.setenv("RENDER_GIT_COMMIT", "ff80cc3ce79e35a3dcbfd6dd8b92f82c51ed5991")
    monkeypatch.delenv("GITHUB_SHA", raising=False)
    assert main_mod._code_revision() == "ff80cc3ce79e35a3dcbfd6dd8b92f82c51ed5991"
    monkeypatch.delenv("RENDER_GIT_COMMIT", raising=False)
    monkeypatch.setenv("GITHUB_SHA", "deadbeef")
    assert main_mod._code_revision() == "deadbeef"
    monkeypatch.delenv("GITHUB_SHA", raising=False)
    assert main_mod._code_revision() == ""


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
    assert body.get("data_ok") is None
    assert body.get("latest_complete") == ""
    assert body.get("boot_grace_s") == 3600


def test_boot_grace_fills_data_fields_when_db_ready(serve, monkeypatch):
    """庫已可讀時，boot grace 仍要回 data_ok／latest_complete，不能整段空白。"""
    get, db, main = serve
    monkeypatch.setenv("WAYNE_BOOT_GRACE_SECONDS", "3600")
    import time as _time

    main._PROCESS_STARTED_AT = _time.time()
    code, body = get("/health")
    assert code == 200
    assert body["booting"] is True
    assert body["db_ok"] is True
    assert body.get("data_ok") is not None
    assert "latest_complete" in body
    assert body.get("boot_grace_s") == 3600


def test_ready_does_not_run_full_audit(serve, monkeypatch):
    """/ready 必須跟 /health 一樣便宜；掃全庫會讓正式站超過 45s。"""
    get, db, main = serve
    import automation_health

    def _boom(*a, **k):
        raise AssertionError("/ready 不該跑 health_payload／run_automation_audit")

    monkeypatch.setattr(automation_health, "health_payload", _boom)
    monkeypatch.setattr(automation_health, "run_automation_audit", _boom)
    code, body = get("/ready")
    assert "watchdog" in body
    assert "jobs" in body
    assert "morning_screen" in body["jobs"]
    assert "delivered" in body["jobs"]["morning_screen"]
    assert "error" not in body or "health_payload" not in str(body.get("error") or "")


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

    def _boom(*a, **k):
        raise RuntimeError("audit exploded")

    monkeypatch.setattr(main, "_cheap_health_data", _boom)
    code, body = get("/health")
    assert code == 200
    assert body["data_ok"] is False
    assert "audit exploded" in body.get("data_error", "")


def test_live_always_200_even_if_db_missing(serve, monkeypatch):
    """Render 健檢走 /live：行程活著就 200，不碰資料庫。"""
    get, db, main = serve
    monkeypatch.setenv("WAYNE_DB_PATH", str(db) + ".gone")
    code, body = get("/live")
    assert code == 200
    assert body.get("live") is True
