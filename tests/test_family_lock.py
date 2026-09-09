# -*- coding: utf-8 -*-
"""私人 Bot 白名單、公開 zip 不准混持股、token 不准進 git、私人備份。"""
from __future__ import annotations

import asyncio
import json
import os
import re
import sqlite3
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from config import (
    allowed_telegram_uids,
    extra_family_chat_ids,
    telegram_uid_allowed,
)
from wayne_db import (
    add_to_portfolio,
    add_to_watchlist,
    ensure_core_schema,
    export_private_user_payload,
    list_tg_user_ids,
    strip_private_user_data,
    touch_tg_user,
)

ROOT = Path(__file__).resolve().parents[1]


def _msg(uid: int, text: str = ""):
    user = SimpleNamespace(id=uid, first_name="路人")
    chat = SimpleNamespace(id=uid)
    message = MagicMock()
    message.chat_id = uid
    message.chat = chat
    message.from_user = user
    message.text = text
    message.reply_text = AsyncMock()
    message.reply_html = AsyncMock()
    message.reply_document = AsyncMock()
    return message


def _update(message):
    return SimpleNamespace(
        message=message,
        effective_user=message.from_user,
        effective_message=message,
        callback_query=None,
    )


def _bot(db: str):
    from bot_servers import WayneTelegramBot
    from wayne_db import init_database

    init_database(db)
    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    bot.db_path = db
    bot.charts_dir = "data/charts"
    bot._pending = {}
    bot._last_card = {}
    bot._lookup_ctx = {}
    bot._menu_fade_msgs = {}
    bot._lookup_fade_msgs = {}
    bot._screening_msgs = {}
    bot._line_pack_status_msgs = {}
    bot._help_msgs = {}
    bot._lookup_locks = {}
    bot._pending_locks = {}
    bot._lookup_op_state = {}
    bot._screening_running = set()
    bot._trade_running = set()
    bot._screening_gate = asyncio.Lock()
    bot._screening_global_owner = ""
    bot._menu_fade_gen = {}
    bot._menu_pin_msgs = {}
    bot._force_reply_menu = AsyncMock()
    bot._enter_main_menu = AsyncMock()
    return bot


def test_allowed_uids_owner_plus_family(monkeypatch):
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "9001,9004")
    monkeypatch.setenv("WAYNE_FAMILY_CHAT_IDS", "9003")
    monkeypatch.delenv("TG_CHAT_ID", raising=False)
    monkeypatch.delenv("WAYNE_BROTHER_CHAT_ID", raising=False)
    assert extra_family_chat_ids() == ["9003", "9004"]
    assert allowed_telegram_uids() == ["9001", "9003", "9004"]
    assert telegram_uid_allowed("9001") is True
    assert telegram_uid_allowed("9003") is True
    assert telegram_uid_allowed("7777") is False


def test_empty_allowlist_fail_closed(monkeypatch):
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    monkeypatch.delenv("TG_CHAT_ID", raising=False)
    monkeypatch.delenv("WAYNE_FAMILY_CHAT_IDS", raising=False)
    monkeypatch.delenv("WAYNE_BROTHER_CHAT_ID", raising=False)
    monkeypatch.setenv("WAYNE_ALLOWLIST_EMPTY_CLOSED", "1")
    assert allowed_telegram_uids() == []
    assert telegram_uid_allowed("9001") is False


def test_stranger_start_replies_private_and_not_in_tg_users(tmp_path, monkeypatch):
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "9001")
    monkeypatch.setenv("WAYNE_FAMILY_CHAT_IDS", "9002")
    monkeypatch.delenv("TG_CHAT_ID", raising=False)
    db = str(tmp_path / "lock.db")
    bot = _bot(db)
    msg = _msg(7777, "/start")
    update = _update(msg)

    async def run():
        await bot.on_text(update, MagicMock())

    asyncio.run(run())
    msg.reply_text.assert_awaited()
    assert msg.reply_text.await_args.args[0] == "這是私人 Bot"
    assert list_tg_user_ids(db) == []


def test_allowlisted_start_touches_user(tmp_path, monkeypatch):
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "9001")
    monkeypatch.setenv("WAYNE_FAMILY_CHAT_IDS", "9002")
    monkeypatch.delenv("TG_CHAT_ID", raising=False)
    db = str(tmp_path / "ok.db")
    bot = _bot(db)
    msg = _msg(9002, "開始")
    msg.from_user = SimpleNamespace(id=9002, first_name="哥")
    update = _update(msg)

    async def run():
        await bot.start_cmd(update, MagicMock())

    asyncio.run(run())
    assert "9002" in list_tg_user_ids(db)
    msg.reply_html.assert_awaited()


def test_callback_without_effective_user_uses_from_user(tmp_path, monkeypatch):
    """pytest 空白名單時，callback 只有 from_user 也要放行（deep-audit 測法）。"""
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    monkeypatch.delenv("WAYNE_FAMILY_CHAT_IDS", raising=False)
    monkeypatch.delenv("TG_CHAT_ID", raising=False)
    db = str(tmp_path / "cb-open.db")
    bot = _bot(db)
    q = SimpleNamespace(
        data="?:stock",
        from_user=SimpleNamespace(id=1, first_name="u"),
        message=MagicMock(),
        answer=AsyncMock(),
    )
    update = SimpleNamespace(callback_query=q)

    async def run():
        return await bot._reject_stranger(update)

    assert asyncio.run(run()) is False
    q.answer.assert_not_awaited()


def test_callback_stranger_without_effective_user_rejected(tmp_path, monkeypatch):
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "9001")
    monkeypatch.delenv("WAYNE_FAMILY_CHAT_IDS", raising=False)
    monkeypatch.delenv("TG_CHAT_ID", raising=False)
    db = str(tmp_path / "cb-closed.db")
    bot = _bot(db)
    q = SimpleNamespace(
        data="?:stock",
        from_user=SimpleNamespace(id=7777, first_name="路人"),
        message=MagicMock(),
        answer=AsyncMock(),
    )
    update = SimpleNamespace(callback_query=q)

    async def run():
        return await bot._reject_stranger(update)

    assert asyncio.run(run()) is True
    q.answer.assert_awaited()
    assert q.answer.await_args.args[0] == "這是私人 Bot"


def test_callback_owner_without_effective_user_allowed(tmp_path, monkeypatch):
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "9001")
    monkeypatch.delenv("WAYNE_FAMILY_CHAT_IDS", raising=False)
    monkeypatch.delenv("TG_CHAT_ID", raising=False)
    db = str(tmp_path / "cb-owner.db")
    bot = _bot(db)
    q = SimpleNamespace(
        data="?:stock",
        from_user=SimpleNamespace(id=9001, first_name="權"),
        message=MagicMock(),
        answer=AsyncMock(),
    )
    update = SimpleNamespace(callback_query=q)

    async def run():
        return await bot._reject_stranger(update)

    assert asyncio.run(run()) is False
    q.answer.assert_not_awaited()


def test_wrap_cmd_rejects_stranger(tmp_path, monkeypatch):
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "9001")
    monkeypatch.delenv("WAYNE_FAMILY_CHAT_IDS", raising=False)
    monkeypatch.delenv("TG_CHAT_ID", raising=False)
    db = str(tmp_path / "wrap.db")
    bot = _bot(db)
    bot.portfolio_cmd = AsyncMock()
    user = SimpleNamespace(id=4242, first_name="路人")
    msg = MagicMock()
    msg.reply_text = AsyncMock()
    update = SimpleNamespace(effective_user=user, message=msg, callback_query=None, effective_message=msg)

    async def run():
        wrapped = bot._wrap_cmd(bot.portfolio_cmd)
        await wrapped(update, MagicMock())

    asyncio.run(run())
    bot.portfolio_cmd.assert_not_awaited()
    msg.reply_text.assert_awaited()
    assert "4242" not in list_tg_user_ids(db)


def test_backup_cmd_sends_json_for_allowlisted(tmp_path, monkeypatch):
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "9001")
    monkeypatch.delenv("WAYNE_FAMILY_CHAT_IDS", raising=False)
    monkeypatch.delenv("TG_CHAT_ID", raising=False)
    db = str(tmp_path / "bak.db")
    ensure_core_schema(db)
    add_to_watchlist(db, "9001", "2330", "台積電")
    add_to_portfolio(db, "9001", "2330", "台積電", 1000, 500)
    bot = _bot(db)
    msg = _msg(9001, "備份")
    msg.from_user = SimpleNamespace(id=9001, first_name="權")
    update = _update(msg)

    async def run():
        await bot.backup_cmd(update, MagicMock())

    asyncio.run(run())
    msg.reply_document.assert_awaited()
    kwargs = msg.reply_document.await_args.kwargs
    assert "waynebot_private_9001_" in kwargs["filename"]
    assert "不要上傳 GitHub" in kwargs["caption"]
    raw = kwargs["document"].getvalue()
    payload = json.loads(raw.decode("utf-8"))
    assert payload["user_id"] == "9001"
    assert payload["watchlist"][0]["stock_code"] == "2330"
    assert payload["holdings"][0]["stock_code"] == "2330"


def test_strip_private_user_data_keeps_quotes(tmp_path):
    db = str(tmp_path / "mkt.db")
    ensure_core_schema(db)
    touch_tg_user(db, "secret-uid-999", "路人")
    add_to_watchlist(db, "secret-uid-999", "2330", "台積電")
    add_to_portfolio(db, "secret-uid-999", "2330", "台積電", 1000, 500)
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO daily_quotes(date,stock_id,stock_name,market,open,high,low,close,volume,turnover_k,pct_change,avg_price) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        ("20260908", "2330", "台積電", "TW", 500, 510, 490, 500, 1000, 1000, 1.0, 500),
    )
    conn.commit()
    conn.close()
    deleted = strip_private_user_data(db)
    assert deleted.get("user_holdings", 0) >= 1
    assert deleted.get("user_watchlist", 0) >= 1
    assert deleted.get("tg_users", 0) >= 1
    assert list_tg_user_ids(db) == []
    conn = sqlite3.connect(db)
    n = conn.execute("SELECT COUNT(*) FROM daily_quotes").fetchone()[0]
    h = conn.execute("SELECT COUNT(*) FROM user_holdings").fetchone()[0]
    conn.close()
    assert n == 1
    assert h == 0
    blob = Path(db).read_bytes()
    assert b"secret-uid-999" not in blob


def test_export_private_user_payload_scoped(tmp_path):
    db = str(tmp_path / "exp.db")
    ensure_core_schema(db)
    add_to_watchlist(db, "9001", "2330", "台積電")
    add_to_watchlist(db, "9002", "2317", "鴻海")
    payload = export_private_user_payload(db, "9001")
    codes = [r["stock_code"] for r in payload["watchlist"]]
    assert codes == ["2330"]
    assert "2317" not in codes


def test_tracked_files_have_no_telegram_bot_token():
    listed = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT)
    paths = [p.decode("utf-8") for p in listed.split(b"\0") if p]
    token_re = re.compile(rb"(?<![A-Za-z0-9])\d{8,10}:[A-Za-z0-9_-]{35,}")
    hits = []
    for rel in paths:
        path = ROOT / rel
        if not path.is_file():
            continue
        if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".zip", ".db"}:
            continue
        try:
            data = path.read_bytes()
        except OSError:
            continue
        if b"\0" in data[:4096]:
            continue
        if token_re.search(data):
            hits.append(rel)
    assert hits == []


def test_env_example_warns_token_not_in_git():
    text = (ROOT / ".env.example").read_text(encoding="utf-8")
    assert "YOUR_TELEGRAM_BOT_TOKEN_HERE" in text
    assert "不要貼聊天" in text
    assert "WAYNE_FAMILY_CHAT_IDS" in text


def test_gha_does_not_inject_telegram_secrets():
    text = (ROOT / ".github/workflows/daily_run.yml").read_text(encoding="utf-8")
    assert "secrets.TELEGRAM_BOT_TOKEN" not in text
    assert "strip_private_user_data" in text


def test_backup_script_exists_and_mentions_no_github():
    src = (ROOT / "scripts/backup_private_user_data.py").read_text(encoding="utf-8")
    assert "不要上傳" in src
    assert "export_private_user_payload" in src
