# -*- coding: utf-8 -*-
"""正向雙人長時壓力：偉權＋哥哥同時按十二顆、寫庫、疊排程雷達。

與既有 dual_user_concurrent／persona_grid／cross_feature 不同：
- 真 sqlite（不是只 Mock pending）
- 觀察鈕的 user_watchlist 必須出現在 06:30 自選雷達
- 執行緒寫庫 ＋ asyncio 十二顆 ＋ MainRunner 家人廣播同時跑
- 其中一人行情列壞掉，不能擋住另一人的早報附帶雷達
"""
from __future__ import annotations

import asyncio
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ai_trader import ai_user_id
from bot_servers import (
    HELP_TOPICS,
    MENU_BTN_AI,
    MENU_BTN_CARD,
    MENU_BTN_MARKET,
    MENU_BTN_REPORT,
    MENU_BTN_STREAK,
    MENU_COMPACT_ROWS,
    MENU_FULL_ALIASES,
    MENU_ROW1,
    MENU_ROW2,
    WayneTelegramBot,
)
from main_runner import MainRunner
from trade_journal import record_buy, record_sell
from wayne_db import (
    add_to_watchlist,
    get_user_portfolio,
    get_user_watchlist,
    init_database,
    list_tg_user_ids,
    remove_from_watchlist,
    touch_tg_user,
)

WAYNE = "9001"
BRO = "9002"
WAYNE_I = 9001
BRO_I = 9002

ALL_BUTTONS = [t for t in list(MENU_ROW1) + list(MENU_ROW2) if str(t).strip()]
ALIASES = ("刷新上一檔", "決策卡", "完整選單", "精簡選單", "選單", "幫助")
HAMMER_SEC = 5.0
BUTTON_ROUNDS = 48


def _msg(uid: int, text: str = ""):
    user = SimpleNamespace(id=uid, first_name="u")
    chat = SimpleNamespace(id=uid)
    message = MagicMock()
    message.chat_id = uid
    message.chat = chat
    message.from_user = user
    message.text = text
    message.reply_text = AsyncMock(return_value=MagicMock(delete=AsyncMock()))
    message.reply_html = AsyncMock(return_value=MagicMock(delete=AsyncMock()))
    message.reply_photo = AsyncMock()
    return message


def _update(message):
    return SimpleNamespace(message=message, effective_user=message.from_user)


def _bind_hit(hits: dict[str, list[str]], name: str):
    async def _cmd(update, context):
        uid = str(update.effective_user.id)
        hits.setdefault(uid, []).append(name)

    return _cmd


def _seed_quotes(db: str, rows: list[tuple]) -> None:
    from wayne_db import ensure_core_schema

    ensure_core_schema(db)
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT OR REPLACE INTO daily_quotes("
        "date,stock_id,stock_name,market,open,high,low,close,volume,turnover_k,pct_change,avg_price) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        ("20260908", "2330", "台積電", "TW", 500, 510, 490, 500, 1000, 1000, 1.0, 500),
    )
    for sid, name, close, pct in rows:
        conn.execute(
            "INSERT OR REPLACE INTO daily_quotes("
            "date,stock_id,stock_name,market,open,high,low,close,volume,turnover_k,pct_change,avg_price) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            ("20260908", sid, name, "TW", close, close, close, close, 100, 100, pct, close),
        )
    conn.commit()
    conn.close()


def _bot(db: str) -> WayneTelegramBot:
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
    bot._dismiss_menu_transients = AsyncMock()
    bot._enter_main_menu = AsyncMock()
    bot._force_reply_menu = AsyncMock()
    bot._dismiss_help_msgs = AsyncMock()
    bot._transient_status = AsyncMock(return_value=MagicMock())
    bot._delete_message = AsyncMock()
    bot._send_card_to = AsyncMock()
    bot._send_chips_to = AsyncMock()
    bot._send_industry = AsyncMock()
    bot._send_fund_to = AsyncMock()
    bot._send_picture_guide = AsyncMock()
    bot._commit_issue_report = AsyncMock()
    bot.screener = MagicMock()
    bot.portfolio_engine = MagicMock()
    hits: dict[str, list[str]] = {WAYNE: [], BRO: []}
    bot._stress_hits = hits
    bot.help_cmd = _bind_hit(hits, "說明")
    bot.screen_cmd = _bind_hit(hits, "海選")
    bot.portfolio_cmd = _bind_hit(hits, "持股")
    bot.watch_cmd = _bind_hit(hits, "觀察")
    bot.decision_card_btn = _bind_hit(hits, "刷新")
    bot.report_cmd = _bind_hit(hits, "回報")
    bot.market_cmd = _bind_hit(hits, "大盤")
    bot.flow_cmd = _bind_hit(hits, "資金")
    bot.daytrade_cmd = _bind_hit(hits, "當沖")
    bot.overnight_cmd = _bind_hit(hits, "隔日沖")
    bot.streak_cmd = _bind_hit(hits, "連買區")
    bot.menu_cmd = _bind_hit(hits, "選單")

    async def _ai(message, uid):
        hits.setdefault(str(uid), []).append("AI倉")

    async def _bk(message, *, ask=""):
        uid = str(getattr(getattr(message, "from_user", None), "id", "") or "")
        hits.setdefault(uid, []).append("飆客")

    bot._send_ai_desk_view = AsyncMock(side_effect=_ai)
    bot._send_biaoke_page = AsyncMock(side_effect=_bk)
    return bot


def _runner(db: str, monkeypatch) -> MainRunner:
    monkeypatch.delenv("WAYNE_FAMILY_CHAT_IDS", raising=False)
    monkeypatch.setenv("TELEGRAM_CHAT_ID", WAYNE)
    monkeypatch.setenv("WAYNE_FAMILY_CHAT_IDS", BRO)
    monkeypatch.delenv("TG_CHAT_ID", raising=False)
    runner = MainRunner.__new__(MainRunner)
    runner.db_path = db
    runner.chat_id = WAYNE
    runner.today_str = "20260908"
    runner.portfolio_engine = None
    runner.bot = None
    return runner


def test_telegram_watch_feeds_morning_radar_not_old_table(tmp_path, monkeypatch):
    """觀察鈕寫 user_watchlist；雷達以前只讀 user_watchlists，兩人加自選早報會空。"""
    db = str(tmp_path / "watch.db")
    init_database(db)
    touch_tg_user(db, WAYNE, "偉權")
    touch_tg_user(db, BRO, "哥哥")
    add_to_watchlist(db, WAYNE, "2330", "台積電")
    add_to_watchlist(db, WAYNE, "00706L", "期元大S&P日圓正2")
    add_to_watchlist(db, BRO, "2317", "鴻海")
    _seed_quotes(db, [("2317", "鴻海", 200.0, -0.5), ("00706L", "期元大S&P日圓正2", 10.0, 0.2)])
    runner = _runner(db, monkeypatch)
    runner._load_latest_quotes_map = lambda: {
        "2330": {"close": 500.0, "pct_change": 1.0},
        "00706L": {"close": 10.0, "pct_change": 0.2},
        "2317": {"close": 200.0, "pct_change": -0.5},
    }
    wayne = runner._format_watch_radar_section(WAYNE)
    bro = runner._format_watch_radar_section(BRO)
    assert "2330" in wayne and "2317" not in wayne
    assert "2317" in bro and "2330" not in bro
    assert "S&P" not in wayne
    assert "S&amp;P" in wayne
    assert "收 500.00" in wayne
    assert runner.portfolio_engine is None


def test_radar_unions_legacy_watchlists_table(tmp_path, monkeypatch):
    db = str(tmp_path / "union.db")
    init_database(db)
    add_to_watchlist(db, WAYNE, "2330", "台積電")
    from portfolio_engine import PortfolioEngine

    eng = PortfolioEngine(db)
    eng.add_watchlist(WAYNE, "0050", "元大台灣50")
    runner = _runner(db, monkeypatch)
    runner.portfolio_engine = eng
    html = runner._format_watch_radar_section(WAYNE)
    assert "2330" in html and "0050" in html


def test_bad_quote_on_one_user_does_not_drop_brother_extra(tmp_path, monkeypatch):
    db = str(tmp_path / "badq.db")
    init_database(db)
    touch_tg_user(db, WAYNE, "偉權")
    touch_tg_user(db, BRO, "哥哥")
    add_to_watchlist(db, WAYNE, "2330", "台積電")
    add_to_watchlist(db, BRO, "2317", "鴻海")
    runner = _runner(db, monkeypatch)
    sent: list[tuple] = []

    def _boom(uid=""):
        if str(uid) == WAYNE:
            raise RuntimeError("broken quote row")
        return f"RADAR-{uid}"

    runner._format_watch_radar_section = _boom
    runner.send_telegram_message = lambda text, chat_id=None: sent.append((str(chat_id), text))
    runner._run_ai_desk = lambda *a, **k: {}
    runner.bot = MagicMock()
    runner.bot.send_screening_report = lambda screening, chat_id=None: sent.append(
        ("screen", str(chat_id))
    )
    with patch(
        "taiwan_market.format_taiwan_market_brief_html", return_value="大盤摘要"
    ):
        runner._push_screening(
            {
                "status": "success",
                "payload": [{"html": "海選"}],
                "results": {},
                "message": "海選本文",
            },
            as_of="20260908",
        )
    extra = [(c, t) for c, t in sent if c in (WAYNE, BRO)]
    assert any(c == BRO and "RADAR-9002" in str(t) for c, t in extra)
    assert any(c == WAYNE and "大盤摘要" in str(t) and "RADAR-9001" not in str(t) for c, t in extra)
    assert ("screen", WAYNE) in sent and ("screen", BRO) in sent


def test_holdings_journal_watch_isolated_under_thread_hammer(tmp_path):
    db = str(tmp_path / "hammer.db")
    init_database(db)
    errors: list[str] = []

    def wayne_loop():
        try:
            for i in range(40):
                record_buy(db, WAYNE, "2330", "台積電", 1, 500 + i)
                add_to_watchlist(db, WAYNE, "2330", "台積電")
                add_to_watchlist(db, WAYNE, "2383", "台光電")
                get_user_watchlist(db, WAYNE)
                get_user_portfolio(db, WAYNE)
            record_sell(db, WAYNE, "2330", 10, 510)
        except Exception as e:
            errors.append(f"wayne:{e}")

    def bro_loop():
        try:
            for i in range(40):
                record_buy(db, BRO, "2317", "鴻海", 2, 100 + i)
                add_to_watchlist(db, BRO, "2317", "鴻海")
                add_to_watchlist(db, BRO, "2454", "聯發科")
                get_user_watchlist(db, BRO)
                get_user_portfolio(db, BRO)
            record_sell(db, BRO, "2317", 20, 120)
        except Exception as e:
            errors.append(f"bro:{e}")

    t0 = time.monotonic()
    with ThreadPoolExecutor(max_workers=2) as pool:
        f1 = pool.submit(wayne_loop)
        f2 = pool.submit(bro_loop)
        f1.result()
        f2.result()
    elapsed = time.monotonic() - t0
    assert errors == [], errors
    w_watch = {r["stock_code"] for r in get_user_watchlist(db, WAYNE)}
    b_watch = {r["stock_code"] for r in get_user_watchlist(db, BRO)}
    assert w_watch == {"2330", "2383"}
    assert b_watch == {"2317", "2454"}
    w_hold = {r["stock_code"]: r["shares"] for r in get_user_portfolio(db, WAYNE)}
    b_hold = {r["stock_code"]: r["shares"] for r in get_user_portfolio(db, BRO)}
    assert "2317" not in w_hold
    assert "2330" not in b_hold
    assert w_hold.get("2330", 0) == pytest.approx(30.0)
    assert b_hold.get("2317", 0) == pytest.approx(60.0)
    assert elapsed < 20.0


def test_two_users_all_buttons_and_help_topics_interleaved(tmp_path):
    db = str(tmp_path / "btns.db")
    bot = _bot(db)
    assert ALL_BUTTONS == [
        "說明",
        "海選",
        "持股",
        "觀察",
        MENU_BTN_CARD,
        MENU_BTN_REPORT,
        "飆客",
        MENU_BTN_MARKET,
        "資金",
        "當沖",
        "隔日沖",
        MENU_BTN_AI,
        MENU_BTN_STREAK,
    ]

    async def run():
        for i in range(BUTTON_ROUNDS):
            w = ALL_BUTTONS[i % len(ALL_BUTTONS)]
            b = ALL_BUTTONS[(i + 6) % len(ALL_BUTTONS)]
            await asyncio.gather(
                bot.on_text(_update(_msg(WAYNE_I, w)), MagicMock()),
                bot.on_text(_update(_msg(BRO_I, b)), MagicMock()),
            )
        for alias in ALIASES:
            await asyncio.gather(
                bot.on_text(_update(_msg(WAYNE_I, alias)), MagicMock()),
                bot.on_text(_update(_msg(BRO_I, alias)), MagicMock()),
            )
        bot._last_card[WAYNE] = "2330"
        bot._last_card[BRO] = "2317"
        await asyncio.gather(
            bot.on_text(_update(_msg(WAYNE_I, "籌碼")), MagicMock()),
            bot.on_text(_update(_msg(BRO_I, "籌碼")), MagicMock()),
        )

    asyncio.run(run())
    for uid in (WAYNE, BRO):
        names = set(bot._stress_hits[uid])
        for need in ("說明", "海選", "持股", "觀察", "刷新", "回報", "飆客", "大盤", "資金", "當沖", "隔日沖", "AI倉", "連買區"):
            assert need in names, (uid, need, names)
    assert bot._last_card[WAYNE] == "2330"
    assert bot._last_card[BRO] == "2317"
    bot._send_chips_to.assert_awaited()
    chip_codes = [c.args[1] for c in bot._send_chips_to.await_args_list]
    assert "2330" in chip_codes and "2317" in chip_codes


def test_help_topics_and_compact_isolated(tmp_path):
    db = str(tmp_path / "help.db")
    bot = _bot(db)

    async def run():
        topics = sorted(HELP_TOPICS)
        for i, topic in enumerate(topics):
            w_msg = _msg(WAYNE_I, "說明")
            b_msg = _msg(BRO_I, "說明")
            await asyncio.gather(
                bot._reply_help_topic(w_msg, topics[i % len(topics)]),
                bot._reply_help_topic(b_msg, topics[(i + 3) % len(topics)]),
            )
        bot._set_menu_compact(WAYNE, True)
        bot._set_menu_compact(BRO, False)

    asyncio.run(run())
    wayne_kb = [b.text for row in bot._reply_menu(WAYNE).keyboard for b in row]
    bro_kb = [[b.text for b in row] for row in bot._reply_menu(BRO).keyboard]
    assert wayne_kb == [t for row in MENU_COMPACT_ROWS for t in row]
    assert bro_kb == [list(MENU_ROW1), list(MENU_ROW2)]
    for alias in MENU_FULL_ALIASES:
        assert alias


def test_overlap_buttons_sqlite_and_scheduled_radar(tmp_path, monkeypatch):
    """長時壓縮：5 秒內兩執行緒寫庫、asyncio 按鈕、排程雷達同時讀。"""
    db = str(tmp_path / "overlap.db")
    init_database(db)
    bot = _bot(db)
    runner = _runner(db, monkeypatch)
    _seed_quotes(db, [("2317", "鴻海", 200.0, 0.5), ("2383", "台光電", 400.0, 2.0)])
    stop = threading.Event()
    errors: list[str] = []
    radar_ok = {"n": 0}

    def sqlite_writer():
        n = 0
        try:
            while not stop.is_set():
                record_buy(db, WAYNE, "2330", "台積電", 1, 500)
                record_buy(db, BRO, "2317", "鴻海", 1, 100)
                add_to_watchlist(db, WAYNE, "2330", "台積電")
                add_to_watchlist(db, WAYNE, "2383", "台光電")
                add_to_watchlist(db, BRO, "2317", "鴻海")
                touch_tg_user(db, WAYNE, "偉權")
                touch_tg_user(db, BRO, "哥哥")
                n += 1
        except Exception as e:
            errors.append(f"sql:{e}")
        radar_ok["writes"] = n

    def schedule_reader():
        try:
            while not stop.is_set():
                ids = set(runner._family_chat_ids())
                if WAYNE in ids and BRO in ids:
                    w = runner._format_watch_radar_section(WAYNE)
                    b = runner._format_watch_radar_section(BRO)
                    if "2330" in w and "2317" in b and "2317" not in w and "2330" not in b:
                        radar_ok["n"] += 1
                time.sleep(0.01)
        except Exception as e:
            errors.append(f"sched:{e}")

    async def buttons():
        deadline = time.monotonic() + HAMMER_SEC
        i = 0
        while time.monotonic() < deadline:
            w = ALL_BUTTONS[i % len(ALL_BUTTONS)]
            b = ALL_BUTTONS[(i + 5) % len(ALL_BUTTONS)]
            await asyncio.gather(
                bot.on_text(_update(_msg(WAYNE_I, w)), MagicMock()),
                bot.on_text(_update(_msg(BRO_I, b)), MagicMock()),
            )
            i += 1
        return i

    t_sql = threading.Thread(target=sqlite_writer)
    t_sch = threading.Thread(target=schedule_reader)
    t_sql.start()
    t_sch.start()
    rounds = asyncio.run(buttons())
    stop.set()
    t_sql.join(timeout=5)
    t_sch.join(timeout=5)
    assert errors == [], errors
    assert rounds >= 12
    assert radar_ok["n"] >= 1
    ids = list_tg_user_ids(db)
    assert WAYNE in ids and BRO in ids
    assert ai_user_id(WAYNE) != ai_user_id(BRO)
    assert ai_user_id(WAYNE) == "ai_9001"
    assert set(runner._family_chat_ids()) >= {WAYNE, BRO}
    w_html, _ = bot._render_watch(get_user_watchlist(db, WAYNE))
    b_html, _ = bot._render_watch(get_user_watchlist(db, BRO))
    assert "2330" in w_html and "2317" not in w_html
    assert "2317" in b_html and "2330" not in b_html
    remove_from_watchlist(db, WAYNE, "2330")
    after = runner._format_watch_radar_section(WAYNE)
    assert "2330" not in after
    assert "2383" in after
    assert "2317" in runner._format_watch_radar_section(BRO)


def test_pending_report_and_why_survive_other_user(tmp_path):
    db = str(tmp_path / "pend.db")
    bot = _bot(db)
    wayne = f"{WAYNE}:{WAYNE}"
    bro = f"{BRO}:{BRO}"
    bot._pending[wayne] = "report"
    bot._pending[bro] = "buy:2317"
    bot._last_card[BRO] = "3105"

    async def run():
        await bot.on_text(_update(_msg(WAYNE_I, "大盤")), MagicMock())

    asyncio.run(run())
    assert bot._pending.get(bro) == "buy:2317"
    assert bot._pending.get(wayne) != "report"
    assert "大盤" in bot._stress_hits[WAYNE]
    assert bot._stress_hits[BRO] == []


def test_screening_gate_then_both_finish(tmp_path):
    db = str(tmp_path / "gate.db")
    bot = _bot(db)
    bot._reply_screening_payload = AsyncMock()
    bot._pin_reply_menu = AsyncMock()
    bot._screening_progress_text = lambda *a, **k: "p"
    bot.screener.run_full_screening = MagicMock(return_value={"status": "success", "payload": []})
    bot._screening_global_owner = f"{WAYNE}:{WAYNE}"
    msg_b = _msg(BRO_I, "海選")

    async def run():
        await bot._run_manual_screening(msg_b)
        bot._screening_global_owner = ""
        bot._screening_running.clear()
        await bot._run_manual_screening(_msg(WAYNE_I, "海選"))
        await bot._run_manual_screening(_msg(BRO_I, "海選"))

    asyncio.run(run())
    blob = " ".join(
        str(c.args[0]) for c in (msg_b.reply_html.await_args_list + msg_b.reply_text.await_args_list) if c.args
    )
    assert "海選正在掃描" in blob or "海選進行中" in blob
    assert bot.screener.run_full_screening.call_count == 2
