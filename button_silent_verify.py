# -*- coding: utf-8 -*-
"""全鈕靜默落檔／對質清冊與缺鈕骨架。

選股對質 vs 個人本對照分開記、分開覆盤，勝率不准混（AGENTS §7）。
壓撐三軌（current／first／biaoke_silent）由 ``pressure_rank_verify`` 管，這裡只登記並存，不重發明。
失敗吞掉，不准打斷出卡／海選／查股／AI倉。過程／％不准進對話。
空名單不算有記；要真代號＋當日官方開高低收＋量。未收不當收。Asia/Taipei。
"""
from __future__ import annotations

import os
import sqlite3
from typing import Any, Dict, List, Optional, Sequence, Tuple

# 對質窗：與 judge_tape.score_live_judges 一致（隔日／五日官方已收）
VERIFY_HORIZONS = (1, 5)
# 改碼門檻（各軌各自算；個人本不進改碼）
OPTIMIZE_MIN_N = 20

CLASS_SCREEN = "screen_verify"  # 規則選股對質
CLASS_PERSONAL = "personal_book"  # 個人本對照（不是選股）
CLASS_CONTEXT = "context_freeze"  # 大盤／外圍佐證凍
CLASS_PRESSURE = "pressure_rank"  # 壓撐排序三軌（另模組）
CLASS_BIAOKE = "biaoke_tape"  # 飆大點名／近窗
CLASS_AI = "ai_desk"  # AI倉假錢對照
CLASS_LOOKUP = "lookup_query"  # 查股路徑：按了才記，不是選股

# kind 前綴／固定 kind：個人本對照（勝率不准混進選股）
BOOK_KINDS = frozenset({"book_hold", "book_watch", "book_buy"})
# 選股／規則對質（可各自算勝率，彼此仍不准混）
SCREEN_KINDS = frozenset(
    {
        "leave_zero",
        "ma60_lower",
        "golden_buy",
        "revenue_cross",
        "select_01",
        "select_02",
        "select_03",
        "day_trade",
        "overnight",
        "em_leave_zero",
        "em_ma60_lower",
        "em_golden_buy",
        "dongzhu",
        "streak_foreign",
        "streak_trust",
        "streak_both",
        "money_flow",
        "ai_desk",
        "ai_desk_winrate",
        "ai_desk_dip",
        "ai_buy_reason",
        "biaoke_named",
        "intraday_leave_zero",
        "winrate_buypoint",
        "winrate_filter",
    }
)


def _ymd(raw: Any) -> str:
    t = str(raw or "").replace("-", "")[:8]
    return t if len(t) == 8 and t.isdigit() else ""


def _as_of(market_db: str, hint: str = "") -> str:
    day = _ymd(hint)
    if day:
        return day
    try:
        from import_health import latest_complete_quote_date

        return _ymd(latest_complete_quote_date(market_db))
    except Exception:
        return ""


def _watch_as_of(market_db: str, hint: str = "") -> str:
    """加入觀察個人本對照日：收盤後可到今日，不卡 fuse 16:30（對齊話筒 as_of）。"""
    day = _ymd(hint)
    if day:
        return day
    try:
        from wayne_db import resolve_watch_view_as_of

        as_of, _lag = resolve_watch_view_as_of(market_db)
        return _ymd(as_of)
    except Exception:
        return _as_of(market_db, hint)


# 話筒完整鍵盤清點（上七下七）＋記買入子路徑
# status: present=已有管線；gap_filled=本檔補骨架；external=他模組（壓撐三軌／飆大 tape／AI fills）
BUTTON_CATALOG: Tuple[Dict[str, Any], ...] = (
    {
        "btn": "勝率買點",
        "kinds": ("winrate_buypoint", "winrate_filter"),
        "class": CLASS_SCREEN,
        "status": "present",
        "pipe": "winrate_buypoint 21:00 roster＋隔日篩 → live_judge；button_silent_verify.snapshot_winrate_buypoint",
        "window": "盤後 leave_zero 官方柱 1／5；隔日篩結果另 kind",
        "note": "選股對質；只認藍▲紅框 leave_zero；未過關不准改黃金買點／買訊",
    },
    {
        "btn": "海選",
        "kinds": (
            "leave_zero",
            "ma60_lower",
            "golden_buy",
            "revenue_cross",
            "select_01",
            "select_02",
            "select_03",
            "em_leave_zero",
            "em_ma60_lower",
            "em_golden_buy",
        ),
        "class": CLASS_SCREEN,
        "status": "present",
        "pipe": "judge_tape.snapshot_button_lists + dongzhu_tape screen + screen_review",
        "window": "1／5 日官方收（live_judge）；洞燭／海選另有 1／5／10",
        "note": "選股對質；leave_zero／ma60_lower 分開記分開對；勝率不准混",
    },
    {
        "btn": "紅箭確認",
        "kinds": ("ma60_lower",),
        "class": CLASS_SCREEN,
        "status": "present",
        "pipe": "judge_tape bucket=ma60_lower → live_judge；red_arrow_quant TAG_FILTER／NEXT_CANDIDATE",
        "window": "1／5 日官方收（live_judge）；evolve 碟 h1／h5／h10＋假突破另軌",
        "note": "買訊＝ma60_lower（與 leave_zero 並列）；未確認紅箭不當買；下一版 ma60_lower_tight 靜默收",
    },
    {
        "btn": "持股",
        "kinds": ("book_hold",),
        "class": CLASS_PERSONAL,
        "status": "gap_filled",
        "pipe": "button_silent_verify.snapshot_book_hold",
        "window": "1／5 日官方收（個人本對照，不進選股勝率）",
        "note": "個人本對照；不是選股",
    },
    {
        "btn": "加入觀察",
        "kinds": ("book_watch",),
        "class": CLASS_PERSONAL,
        "status": "gap_filled",
        "pipe": "button_silent_verify.snapshot_book_watch（as_of＝watch_display_cap／resolve_watch_view_as_of）",
        "window": "1／5 日官方收（個人本對照，不進選股勝率；收盤後不卡 16:30）",
        "note": "個人本對照；不是選股；勝率不准混",
    },
    {
        "btn": "飆大",
        "kinds": ("biaoke_named", "biaoke_levels", "biaoke_diverge"),
        "class": CLASS_BIAOKE,
        "status": "gap_filled",
        "pipe": (
            "biaoke_tape（近窗柱）＋本檔每日點名凍結 live_judge；"
            "biaoke_claims 點位（lo/hi／role）→ biaoke_levels 輔助凍；"
            "點位／大盤走法必寫他說＋可重算我說→biaoke_diverge；"
            "§13 n≥20 且下一版贏現況才換該軌並再生；"
            "對質前 ensure_confront_aux 補台指／電子夜盤／美股已收"
        ),
        "window": "近窗官方 OHLC＋量；點位持續對質；live_judge 再對 1／5",
        "note": "不是買訊；不准話筒抬槓；不准寫回黃金買點／海選；未過閘不改買訊",
    },
    {
        "btn": "台股大盤",
        "kinds": ("market", "fut", "us", "outer"),
        "class": CLASS_CONTEXT,
        "status": "present",
        "pipe": "judge_tape + silent_progress + biaoke_forecast",
        "window": "加權完整柱＋日夜盤／美指已收；試畫另軌",
        "note": "佐證凍；現在不准發明 5／9",
    },
    {
        "btn": "資金輪動",
        "kinds": ("money_flow",),
        "class": CLASS_SCREEN,
        "status": "gap_filled",
        "pipe": "button_silent_verify.snapshot_money_flow",
        "window": "1／5 日官方收；與海選勝率分開",
        "note": "外資／投信買超＋短線熱代表股；不是買訊",
    },
    {
        "btn": "當沖",
        "kinds": ("day_trade",),
        "class": CLASS_SCREEN,
        "status": "present",
        "pipe": "judge_tape screen bucket",
        "window": "1／5 日官方收",
        "note": "選股對質；非黃金買點",
    },
    {
        "btn": "隔日沖",
        "kinds": ("overnight",),
        "class": CLASS_SCREEN,
        "status": "present",
        "pipe": "judge_tape screen bucket",
        "window": "1／5 日官方收",
        "note": "選股對質；非黃金買點",
    },
    {
        "btn": "壓撐觀察",
        "kinds": ("pressure_sideways", "pressure_test_press", "pressure_stand_support"),
        "class": CLASS_PRESSURE,
        "status": "external",
        "pipe": "judge_tape 三標籤落檔＋pressure_rank_verify 四軌",
        "window": "前瞻 5 交易日；current／first／second／biaoke_silent 分開",
        "note": "first／second 過閘才改話筒排序；飆大軌永不自動上",
    },
    {
        "btn": "大量區×季線",
        "kinds": ("volzone_ma60",),
        "class": CLASS_PRESSURE,
        "status": "external",
        "pipe": "volzone_ma60_verify current／ma60_rising／ma60_rising_thin",
        "window": "前瞻 5 交易日；與壓撐／海選勝率分開",
        "note": "靜默對質；過閘也不自動改黃金買點／海選／買訊",
    },
    {
        "btn": "盤中剛離零→收盤",
        "kinds": ("intraday_leave_zero",),
        "class": CLASS_SCREEN,
        "status": "external",
        "pipe": "intraday_leave_zero_verify lookup／MIS hit → close_hold／next_1",
        "window": "當日官方收是否仍 leave_zero；選填隔日報酬",
        "note": "靜默對質；不是新鈕；過閘也不自動改黃金買點／買訊",
    },
    {
        "btn": "買點排除層",
        "kinds": ("buy_exclude",),
        "class": CLASS_SCREEN,
        "status": "external",
        "pipe": "buy_exclude_verify lz_raw／lz_v2／…／lz_ctrl_near_h20 → night_tick；paint＝v5（結構＋當天額；live 不含 near_h20）；勝率名單另砍非 AI",
        "window": "前瞻 1／5／10 日官方收；母體收<20000＋興櫃；分價層落檔",
        "note": "靜默對質；near_h20／非 AI 只當對照臂；不准改黃金買點公式",
    },
    {
        "btn": "勝率大量區再篩",
        "kinds": ("winrate_volzone_filter",),
        "class": CLASS_SCREEN,
        "status": "external",
        "pipe": (
            "winrate_volzone_filter_verify current／vz_mid_thin／ma60_rising／"
            "space_h20／untangle_up／combo_vz_ma60 → night_tick"
        ),
        "window": "前瞻 1／3／5／10 日；母體＝勝率買點現況（leave_zero＋exclude＋AI）",
        "note": "靜默對質；不過閘不改話筒排序／推播；不准改黃金買點公式",
    },
    {
        "btn": "AI倉",
        "kinds": ("ai_desk", "ai_desk_winrate", "ai_desk_dip", "ai_buy_reason"),
        "class": CLASS_AI,
        "status": "gap_filled",
        "pipe": (
            "screen_review.ai_fills＋ai_buy_reasons＋MainRunner._run_ai_desk "
            "成交後 snapshot_ai_desk（分桶 winrate_active／dip_add）"
        ),
        "window": (
            "ai_fills 隔日收；live_judge 1／5；理由表當日落檔對照；"
            "各桶各自對質，不准混海選／勝率買點推播軌"
        ),
        "note": (
            "假錢；總50萬＝30操作＋20抄底；硬閘只認盤後勝率買點 roster；"
            "有買進理由必落檔；不准真下單；不准改黃金買點；n≥20且贏該軌才換並再生"
        ),
    },
    {
        "btn": "連買區",
        "kinds": ("streak_foreign", "streak_trust", "streak_both"),
        "class": CLASS_SCREEN,
        "status": "present",
        "pipe": "judge_tape + buy_streak snapshot",
        "window": "1／5 日官方收",
        "note": "選股對質",
    },
    {
        "btn": "剛脫離零",
        "kinds": ("leave_zero",),
        "class": CLASS_SCREEN,
        "status": "present",
        "pipe": "judge_tape leave_zero pick + screen_review 星級",
        "window": "1／5 日官方收；星級隔日另檔",
        "note": "買點切入認 leave_zero；與 ma60_lower 分開對；不准改黃金買點公式",
    },
    {
        "btn": "洞燭先機",
        "kinds": ("dongzhu",),
        "class": CLASS_SCREEN,
        "status": "present",
        "pipe": "judge_tape + dongzhu_tape",
        "window": "1／5／10 日官方收（dongzhu_tape）；live_judge 1／5",
        "note": "與海選分開記、分開覆盤",
    },
    {
        "btn": "記買入",
        "kinds": ("book_buy",),
        "class": CLASS_PERSONAL,
        "status": "gap_filled",
        "pipe": "button_silent_verify.snapshot_book_buy",
        "window": "當日手記成交代號＋官方柱 1／5 對照",
        "note": "個人本對照（子路徑）；不是選股",
    },
    {
        "btn": "查股",
        "kinds": ("lookup", "lookup_chart"),
        "class": CLASS_LOOKUP,
        "status": "present",
        "pipe": "wayne_navigator remember_rows kind=lookup → score_live_judges 1／5；lookup_chart_verify structure_levels／stance_rel → night_tick；盤中離零另軌 intraday_leave_zero_verify",
        "window": "按了才記（沒打代號＝沒名單）；官方柱 1／5 報酬對照＋結構壓撐／stance 精確度",
        "note": "不是選股、不進選股勝率；結構／導航精確度專軌只對柱、不產 PNG、不准改買訊",
    },
    {
        "btn": "情境預估",
        "kinds": ("scenario_forecast",),
        "class": CLASS_LOOKUP,
        "status": "gap_filled",
        "pipe": (
            "button_silent_verify.snapshot_scenario_forecast（查股圖下按了才記）；"
            "dc_scenario_silent_verify.night_tick（台北 02:20／dc_sf_silent；"
            "與飆大 01:00 錯開、專鎖隔離）"
        ),
        "window": (
            "查股圖下按了才記＋D.C 日對質沒按也跑（台北 02:20／連續 30 日曆日）；"
            "圖＋說法／文意差異落 dc_sf_*；有差當天改 dc_sf_rules 上話筒"
        ),
        "note": (
            "獨立附加；D.C 日對質＝沒按也留；不是選股、浪號只在此鈕；"
            "不改黃金買點；與飆大軌互不影響；失敗不准擋查股／飆大"
        ),
    },
)


def catalog() -> List[Dict[str, Any]]:
    return [dict(row) for row in BUTTON_CATALOG]


def coverage_counts() -> Dict[str, int]:
    rows = catalog()
    out = {"present": 0, "gap_filled": 0, "external": 0, "missing": 0, "total": len(rows)}
    for row in rows:
        key = str(row.get("status") or "missing")
        if key not in out:
            key = "missing"
        out[key] = int(out.get(key) or 0) + 1
    return out


def is_personal_book_kind(kind: str) -> bool:
    return str(kind or "").strip() in BOOK_KINDS


def is_screen_kind(kind: str) -> bool:
    k = str(kind or "").strip()
    if k in BOOK_KINDS:
        return False
    if k.startswith("pressure_"):
        return False
    if k in ("market", "fut", "us", "outer"):
        return False
    return k in SCREEN_KINDS or k.startswith("streak_")


def _remember(market_db: str, kind: str, rows: Sequence[Dict[str, Any]], *, as_of: str, pick: str, src: str) -> int:
    try:
        from judge_tape import remember_rows

        return int(remember_rows(market_db, kind, rows, as_of=as_of, pick=pick, src=src) or 0)
    except Exception:
        return 0


def _row_from_quote(sid: str, name: str = "", **extra: Any) -> Dict[str, Any]:
    out: Dict[str, Any] = {"stock_id": str(sid).strip(), "stock_name": str(name or "")}
    out.update(extra)
    return out


def snapshot_money_flow(market_db: str, as_of: str = "") -> int:
    """資金輪動沒按也落檔：外資買超／投信買超／短線熱代表股。空名單＝0。"""
    day = _as_of(market_db, as_of)
    if not market_db or not day or not os.path.isfile(market_db):
        return 0
    rows: List[Dict[str, Any]] = []
    seen = set()
    try:
        conn = sqlite3.connect(market_db, timeout=8.0)
        conn.row_factory = sqlite3.Row
        try:
            packs = []
            for col, desc in (("foreign_net", True), ("trust_net", True)):
                order = "DESC" if desc else "ASC"
                packs.append(
                    conn.execute(
                        f"""
                        SELECT stock_id, stock_name, close, pct_change, volume,
                               foreign_net, trust_net, dealer_net
                        FROM daily_quotes
                        WHERE REPLACE(CAST(date AS TEXT),'-','')=? AND length(stock_id)=4
                        ORDER BY {col} {order}
                        LIMIT 6
                        """,
                        (day,),
                    ).fetchall()
                )
            packs.append(
                conn.execute(
                    """
                    SELECT stock_id, stock_name, close, pct_change, volume,
                           foreign_net, trust_net, dealer_net
                    FROM daily_quotes
                    WHERE REPLACE(CAST(date AS TEXT),'-','')=? AND length(stock_id)=4
                      AND volume>=3000 AND ABS(pct_change)>=1.5
                    ORDER BY ABS(foreign_net) DESC
                    LIMIT 6
                    """,
                    (day,),
                ).fetchall()
            )
        finally:
            conn.close()
        for pack in packs:
            for r in pack:
                sid = str(r["stock_id"] or "").strip()
                if not sid or sid in seen:
                    continue
                seen.add(sid)
                rows.append(
                    _row_from_quote(
                        sid,
                        str(r["stock_name"] or ""),
                        close=r["close"],
                        pct_change=r["pct_change"],
                        volume=r["volume"],
                        foreign_net=r["foreign_net"],
                        trust_net=r["trust_net"],
                        dealer_net=r["dealer_net"],
                    )
                )
    except Exception:
        return 0
    return _remember(market_db, "money_flow", rows, as_of=day, pick="rule", src="flow")


def _distinct_uids(market_db: str, table: str, col: str = "user_id") -> List[str]:
    if not market_db or not os.path.isfile(market_db):
        return []
    try:
        conn = sqlite3.connect(market_db, timeout=8.0)
        try:
            names = {str(r[0]) for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if table not in names:
                return []
            rows = conn.execute(f"SELECT DISTINCT {col} FROM {table} WHERE {col}!=''").fetchall()
        finally:
            conn.close()
        return [str(r[0]).strip() for r in rows if str(r[0] or "").strip()]
    except Exception:
        return []


def snapshot_book_hold(market_db: str, as_of: str = "") -> int:
    """持股＝個人本對照。有真代號才記；空本不算有記。"""
    day = _as_of(market_db, as_of)
    if not day:
        return 0
    n = 0
    for uid in _distinct_uids(market_db, "user_holdings"):
        try:
            from wayne_db import get_user_portfolio

            items = get_user_portfolio(market_db, uid) or []
        except Exception:
            items = []
        rows = []
        for raw in items:
            sid = str(raw.get("stock_code") or raw.get("stock_id") or "").strip()
            if not sid:
                continue
            rows.append(_row_from_quote(sid, str(raw.get("stock_name") or "")))
        n += _remember(market_db, "book_hold", rows, as_of=day, pick=uid, src="book")
    return n


def snapshot_book_watch(market_db: str, as_of: str = "") -> int:
    """加入觀察＝個人本對照。有真代號才記。as_of 對齊話筒收盤後 cap。"""
    day = _watch_as_of(market_db, as_of)
    if not day:
        return 0
    n = 0
    for uid in _distinct_uids(market_db, "user_watchlist"):
        try:
            from wayne_db import get_user_watchlist

            items = get_user_watchlist(market_db, uid) or []
        except Exception:
            items = []
        rows = []
        for raw in items:
            sid = str(raw.get("stock_code") or raw.get("stock_id") or "").strip()
            if not sid:
                continue
            rows.append(_row_from_quote(sid, str(raw.get("stock_name") or "")))
        n += _remember(market_db, "book_watch", rows, as_of=day, pick=uid, src="book")
    return n


def snapshot_book_buy(market_db: str, as_of: str = "") -> int:
    """記買入＝當日手記成交個人本對照。"""
    day = _as_of(market_db, as_of)
    if not market_db or not day or not os.path.isfile(market_db):
        return 0
    n = 0
    try:
        conn = sqlite3.connect(market_db, timeout=8.0)
        try:
            names = {str(r[0]) for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if "user_trade_logs" not in names:
                return 0
            rows = conn.execute(
                """
                SELECT user_id, stock_code, stock_name, action, price
                FROM user_trade_logs
                WHERE REPLACE(CAST(trade_date AS TEXT),'-','')=?
                """,
                (day,),
            ).fetchall()
        finally:
            conn.close()
    except Exception:
        return 0
    by_uid: Dict[str, List[Dict[str, Any]]] = {}
    for uid, code, name, action, price in rows:
        sid = str(code or "").strip()
        if not sid:
            continue
        key = str(uid or "").strip() or "_"
        by_uid.setdefault(key, []).append(
            _row_from_quote(sid, str(name or ""), close=price, action=str(action or ""))
        )
    for uid, items in by_uid.items():
        n += _remember(market_db, "book_buy", items, as_of=day, pick=uid, src="book")
    return n


def snapshot_ai_desk(market_db: str, as_of: str = "") -> int:
    """AI倉當日 BUY／理由凍結（與海選／勝率推播分開；分桶各自對質）。

    kinds：
    - ai_desk：當日全部 BUY（相容舊軌）
    - ai_desk_winrate：bucket=winrate_active（30 萬操作桶）
    - ai_desk_dip：bucket=dip_add（20 萬抄底桶）
    - ai_buy_reason：當日有落檔理由的代號（空理由不算）
    失敗吞掉，不准擋話筒／海選／查股。
    """
    day = _as_of(market_db, as_of)
    if not market_db or not day or not os.path.isfile(market_db):
        return 0
    try:
        from screen_review import ensure_ai_fills_table

        ensure_ai_fills_table(market_db)
    except Exception:
        pass
    try:
        from ai_research import ensure_ai_research_tables

        ensure_ai_research_tables(market_db)
    except Exception:
        pass
    try:
        conn = sqlite3.connect(market_db, timeout=8.0)
        try:
            names = {str(r[0]) for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            hits = []
            if "ai_fills" in names:
                hits = conn.execute(
                    """
                    SELECT user_id, stock_id, stock_name, price, bucket
                    FROM ai_fills
                    WHERE action='BUY' AND REPLACE(CAST(as_of AS TEXT),'-','')=?
                    """,
                    (day,),
                ).fetchall()
            reason_hits = []
            if "ai_buy_reasons" in names:
                reason_hits = conn.execute(
                    """
                    SELECT user_id, stock_id, stock_name, bucket, reason
                    FROM ai_buy_reasons
                    WHERE REPLACE(CAST(as_of AS TEXT),'-','')=?
                      AND TRIM(COALESCE(reason,''))!=''
                    """,
                    (day,),
                ).fetchall()
        finally:
            conn.close()
    except Exception:
        return 0
    by_uid: Dict[str, List[Dict[str, Any]]] = {}
    by_uid_wr: Dict[str, List[Dict[str, Any]]] = {}
    by_uid_dip: Dict[str, List[Dict[str, Any]]] = {}
    for uid, sid, name, price, bucket in hits:
        code = str(sid or "").strip()
        if not code:
            continue
        key = str(uid or "").strip() or "wayne_ai"
        row = _row_from_quote(
            code,
            str(name or ""),
            close=price,
            bucket_key=str(bucket or ""),
        )
        by_uid.setdefault(key, []).append(row)
        b = str(bucket or "").strip()
        if b == "dip_add":
            by_uid_dip.setdefault(key, []).append(row)
        else:
            # winrate_active 或舊 leave_zero 桶都歸操作軌（舊殘列相容，不混海選）
            by_uid_wr.setdefault(key, []).append(row)
    n = 0
    for uid, items in by_uid.items():
        n += _remember(market_db, "ai_desk", items, as_of=day, pick=uid, src="ai")
    for uid, items in by_uid_wr.items():
        n += _remember(market_db, "ai_desk_winrate", items, as_of=day, pick=uid, src="ai_wr")
    for uid, items in by_uid_dip.items():
        n += _remember(market_db, "ai_desk_dip", items, as_of=day, pick=uid, src="ai_dip")
    # 理由落檔：有真代號＋非空理由才算；補當日官方收才凍（缺柱不算有記）
    quote_close: Dict[str, float] = {}
    try:
        conn = sqlite3.connect(market_db, timeout=8.0)
        try:
            for sid, close in conn.execute(
                """
                SELECT stock_id, close FROM daily_quotes
                WHERE REPLACE(CAST(date AS TEXT),'-','')=?
                """,
                (day,),
            ):
                try:
                    px = float(close or 0)
                except (TypeError, ValueError):
                    px = 0.0
                if str(sid or "").strip() and px > 0:
                    quote_close[str(sid).strip()] = px
        finally:
            conn.close()
    except Exception:
        quote_close = {}
    by_uid_reason: Dict[str, List[Dict[str, Any]]] = {}
    for uid, sid, name, bucket, reason in reason_hits:
        code = str(sid or "").strip()
        if not code or not str(reason or "").strip():
            continue
        px = quote_close.get(code)
        if px is None or px <= 0:
            # 成交價後備（同日 BUY）
            for u2, s2, _n2, price, _b2 in hits:
                if str(s2 or "").strip() == code:
                    try:
                        px = float(price or 0)
                    except (TypeError, ValueError):
                        px = 0.0
                    break
        if not px or px <= 0:
            continue
        key = str(uid or "").strip() or "wayne_ai"
        by_uid_reason.setdefault(key, []).append(
            _row_from_quote(
                code,
                str(name or ""),
                close=px,
                bucket_key=str(bucket or ""),
            )
        )
    for uid, items in by_uid_reason.items():
        n += _remember(market_db, "ai_buy_reason", items, as_of=day, pick=uid, src="ai_why")
    return n


def snapshot_biaoke_named(market_db: str, as_of: str = "") -> int:
    """飆大當日點名檔凍結（讀 biaoke_tape；沒有真代號不算）。"""
    day = _as_of(market_db, as_of)
    if not market_db or not day or not os.path.isfile(market_db):
        return 0
    rows: List[Dict[str, Any]] = []
    seen = set()
    try:
        conn = sqlite3.connect(market_db, timeout=8.0)
        try:
            names = {str(r[0]) for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if "biaoke_tape" not in names:
                return 0
            hits = conn.execute(
                """
                SELECT stock_id, stock_name, open, high, low, close, volume, bar_date
                FROM biaoke_tape
                WHERE REPLACE(CAST(post_date AS TEXT),'-','')=?
                   OR REPLACE(CAST(bar_date AS TEXT),'-','')=?
                """,
                (day, day),
            ).fetchall()
        finally:
            conn.close()
        for sid, name, o, h, l, c, v, _bar in hits:
            code = str(sid or "").strip()
            if not code or code in seen:
                continue
            seen.add(code)
            rows.append(
                _row_from_quote(
                    code,
                    str(name or ""),
                    open=o,
                    high=h,
                    low=l,
                    close=c,
                    volume=v,
                )
            )
    except Exception:
        return 0
    return _remember(market_db, "biaoke_named", rows, as_of=day, pick="rule", src="biaoke")


def snapshot_biaoke_levels(market_db: str, as_of: str = "") -> int:
    """飆大點名點位凍結（讀 biaoke_claims lo/hi／role；對質輔助，不是買訊）。

    當日發文點位＋當日對到 hit 的列都凍。個股要真代號＋官方柱；
    大盤／期點用 ``_BKLV_*`` 假碼（context）。空點位不算有記。
    """
    day = _as_of(market_db, as_of)
    if not market_db or not day or not os.path.isfile(market_db):
        return 0
    try:
        from biaoke_claims import ensure_biaoke_claims_table

        ensure_biaoke_claims_table(market_db)
    except Exception:
        pass
    rows: List[Dict[str, Any]] = []
    seen = set()
    try:
        conn = sqlite3.connect(market_db, timeout=8.0)
        try:
            names = {str(r[0]) for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if "biaoke_claims" not in names:
                return 0
            hits = conn.execute(
                """
                SELECT claim_key, post_date, stock_id, stock_name, role, verb,
                       lo, hi, snippet, hit, club
                FROM biaoke_claims
                WHERE (
                    REPLACE(CAST(post_date AS TEXT),'-','')=?
                    OR REPLACE(CAST(hit_date AS TEXT),'-','')=?
                )
                  AND (lo IS NOT NULL OR hi IS NOT NULL)
                  AND COALESCE(club, 0)=0
                """,
                (day, day),
            ).fetchall()
        finally:
            conn.close()
    except Exception:
        return 0
    for ck, post_date, sid, name, role, verb, lo, hi, snippet, hit, _club in hits:
        key = str(ck or "").strip()
        if not key or key in seen:
            continue
        try:
            lo_n = float(lo) if lo is not None else None
        except (TypeError, ValueError):
            lo_n = None
        try:
            hi_n = float(hi) if hi is not None else None
        except (TypeError, ValueError):
            hi_n = None
        if (lo_n is None or lo_n <= 0) and (hi_n is None or hi_n <= 0):
            continue
        seen.add(key)
        code = str(sid or "").strip()
        px = hi_n if hi_n and hi_n > 0 else lo_n
        if not code:
            # 指數／期點：假碼進 context，不需個股柱
            code = f"_BKLV_{key[:24]}"
        rows.append(
            _row_from_quote(
                code,
                str(name or "") or str(role or "點位"),
                close=px,
                lo=lo_n,
                hi=hi_n,
                role=str(role or ""),
                verb=str(verb or ""),
                snippet=str(snippet or "")[:160],
                claim_key=key,
                post_date=str(post_date or ""),
                hit=str(hit or ""),
            )
        )
    if not rows:
        return 0
    return _remember(market_db, "biaoke_levels", rows, as_of=day, pick="rule", src="biaoke_lv")


def snapshot_biaoke_diverge(market_db: str, as_of: str = "") -> int:
    """飆大他說／我說分軌凍（必有可重算下一步；§13 另軌；不是買訊）。"""
    try:
        from biaoke_diverge import snapshot_biaoke_diverge as _snap

        return int(_snap(market_db, as_of=as_of) or 0)
    except Exception:
        return 0


def snapshot_winrate_buypoint(market_db: str, as_of: str = "") -> int:
    """勝率買點盤後名單靜默凍（讀 winrate_buypoint_roster；空名單不算）。"""
    day = _as_of(market_db, as_of)
    if not market_db or not day:
        return 0
    try:
        from winrate_buypoint import silent_remember_roster

        return int(silent_remember_roster(market_db, day) or 0)
    except Exception:
        return 0


def snapshot_all_button_gaps(market_db: str, as_of: str = "") -> Dict[str, int]:
    """補缺鈕骨架一輪。一條失敗不擋其他。"""
    day = _as_of(market_db, as_of)
    stats: Dict[str, int] = {}
    if not day:
        return stats
    runners = (
        ("money_flow", snapshot_money_flow),
        ("book_hold", snapshot_book_hold),
        ("book_watch", snapshot_book_watch),
        ("book_buy", snapshot_book_buy),
        ("ai_desk", snapshot_ai_desk),
        ("biaoke_named", snapshot_biaoke_named),
        ("biaoke_levels", snapshot_biaoke_levels),
        ("biaoke_diverge", snapshot_biaoke_diverge),
        ("winrate_buypoint", snapshot_winrate_buypoint),
    )
    for key, fn in runners:
        try:
            stats[key] = int(fn(market_db, day) or 0)
        except Exception:
            stats[key] = 0
    return stats


def pressure_coexists() -> bool:
    """壓撐三軌模組是否可匯入（與本骨架並存）。"""
    try:
        from pressure_rank_verify import (
            VARIANT_BIAOKE_SILENT,
            VARIANT_CURRENT,
            VARIANT_FIRST,
            night_tick,
        )

        return bool(VARIANT_CURRENT and VARIANT_FIRST and VARIANT_BIAOKE_SILENT and night_tick)
    except Exception:
        return False


def snapshot_scenario_forecast(
    market_db: str, stock_id: str, meta: Optional[Dict[str, Any]] = None, as_of: str = ""
) -> int:
    """查股圖下按「情境預估」才記：真代號＋官方柱＋錨點摘要。空代號＝0。失敗吞掉。"""
    sid = str(stock_id or "").strip()
    day = _as_of(market_db, as_of)
    if not market_db or not sid or not day or not os.path.isfile(market_db):
        return 0
    meta = dict(meta or {})
    name = ""
    close = None
    volume = None
    try:
        conn = sqlite3.connect(market_db, timeout=8.0)
        try:
            r = conn.execute(
                """
                SELECT stock_name, open, high, low, close, volume
                FROM daily_quotes
                WHERE stock_id=? AND REPLACE(CAST(date AS TEXT),'-','')=?
                LIMIT 1
                """,
                (sid, day),
            ).fetchone()
            if not r:
                r = conn.execute(
                    """
                    SELECT stock_name, open, high, low, close, volume
                    FROM daily_quotes
                    WHERE stock_id=?
                    ORDER BY REPLACE(CAST(date AS TEXT),'-','') DESC
                    LIMIT 1
                    """,
                    (sid,),
                ).fetchone()
            if r:
                name = str(r[0] or "")
                close = r[4]
                volume = r[5]
                row = _row_from_quote(
                    sid,
                    name,
                    open=r[1],
                    high=r[2],
                    low=r[3],
                    close=close,
                    volume=volume,
                    vegas_stance=(meta.get("vegas") or {}).get("stance"),
                    desc_press_pos=(meta.get("desc_press") or {}).get("pos"),
                    ladder_n=len(meta.get("ladders") or []),
                )
            else:
                row = _row_from_quote(sid, "", ladder_n=len(meta.get("ladders") or []))
        finally:
            conn.close()
    except Exception:
        return 0
    if close is None and not (meta.get("vegas") or meta.get("desc_press") or meta.get("ladders")):
        # 無官方柱且無錨＝不算有記
        return 0
    return _remember(
        market_db,
        "scenario_forecast",
        [row],
        as_of=day,
        pick="button",
        src="scenario_forecast",
    )


def optimize_status_one_liner(market_db: str = "") -> str:
    """報告唯一准講的明確優化狀態一句（不含過程／％細節堆砌）。"""
    cov = coverage_counts()
    pressure_ok = pressure_coexists()
    pressure_line = ""
    if pressure_ok and market_db:
        try:
            from pressure_rank_verify import optimize_status_one_liner as pressure_line_fn

            pressure_line = str(pressure_line_fn(market_db) or "").strip()
        except Exception:
            pressure_line = ""
    if not pressure_line:
        pressure_line = (
            "壓撐三軌並存可跑"
            if pressure_ok
            else "壓撐三軌模組未載入"
        )
    # 各選股軌改碼：骨架階段一律繼續收集；個人本永不改買訊
    return (
        f"明確優化狀態：全鈕靜默骨架已齊"
        f"（有{cov['present']}／補{cov['gap_filled']}／壓撐外軌{cov['external']}／缺{cov['missing']}）；"
        f"各選股軌 n 仍收集、未過 n≥{OPTIMIZE_MIN_N} 且贏現況→不改碼；"
        f"個人本只對照不改買訊；{pressure_line}"
    )
