# -*- coding: utf-8 -*-
"""當下判斷默默落檔；官方收齊再對隔日／五日。

不推話筒、不改畫面、不改黃金買點。盤中未收不當官方收。
"""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Sequence
from zoneinfo import ZoneInfo

TAIPEI = ZoneInfo("Asia/Taipei")
HORIZONS = (1, 5)

_DDL = """
CREATE TABLE IF NOT EXISTS live_judge (
    as_of TEXT NOT NULL,
    kind TEXT NOT NULL,
    pick TEXT NOT NULL DEFAULT '',
    sid TEXT NOT NULL,
    name TEXT DEFAULT '',
    px REAL,
    profit REAL,
    extra TEXT DEFAULT '',
    ran_at TEXT DEFAULT '',
    PRIMARY KEY (as_of, kind, pick, sid)
);
CREATE TABLE IF NOT EXISTS live_judge_score (
    as_of TEXT NOT NULL,
    kind TEXT NOT NULL,
    pick TEXT NOT NULL DEFAULT '',
    sid TEXT NOT NULL,
    horizon INTEGER NOT NULL,
    check_as_of TEXT NOT NULL,
    now_px REAL,
    fwd_pct REAL,
    verdict TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (as_of, kind, pick, sid, horizon)
);
"""


def _ymd(raw: Any) -> str:
    t = str(raw or "").replace("-", "")[:8]
    return t if len(t) == 8 and t.isdigit() else ""


def _now() -> str:
    return datetime.now(TAIPEI).strftime("%Y-%m-%dT%H:%M:%S")


def store_path(market_db: str) -> str:
    path = os.path.abspath(str(market_db or "data/wayne_market.db"))
    root = os.path.dirname(path) or "."
    name = os.path.basename(path)
    if name == "wayne_evolve.db":
        return path
    return os.path.join(root, "wayne_evolve.db")


def _ensure(store: str) -> None:
    parent = os.path.dirname(os.path.abspath(store))
    if parent:
        os.makedirs(parent, exist_ok=True)
    conn = sqlite3.connect(store, timeout=30.0)
    try:
        conn.executescript(_DDL)
        conn.commit()
    finally:
        conn.close()


def _num(val: Any) -> Optional[float]:
    if val is None or val == "":
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _as_of(market_db: str, hint: str = "") -> str:
    day = _ymd(hint)
    if day:
        return day
    try:
        from import_health import latest_complete_quote_date

        return _ymd(latest_complete_quote_date(market_db))
    except Exception:
        return ""


_SCREEN_BUCKETS = (
    "leave_zero",
    "ma60_lower",  # 紅箭確認買訊；與 leave_zero 分開記、分開對
    "golden_buy",
    "revenue_cross",
    "select_01",
    "select_02",
    "select_03",
    "day_trade",
    "overnight",
)
# 大盤／外圍佐證可只有部分欄；個股選股要開高低收＋量才算有記
# biaoke_levels／biaoke_diverge＝點位／他說vs我說輔助凍（可含假碼）；不是選股勝率
_CONTEXT_KINDS = frozenset(
    {"market", "fut", "us", "outer", "biaoke_levels", "biaoke_diverge"}
)
_BAR_KEYS = ("o", "h", "l", "c", "v")
_CHIP_KEYS = ("fn", "tn", "dn", "pct")
_EXTRA_KEEP = (
    "live",
    "chase_warning",
    "entry_stars",
    "buy_star",
    "bucket_key",
    "buy_gate",
    "buy_gate_note",
    "hold_prior_state",
    "trend_up_now",
    "trend_now_label",
    "leave_days",
    "src_as_of",
    "q60r",
    "stance",
    "rel_kind",
    "src",
    "why",
    "five",
    "field",
    "fine",
    "role",
    "q",
    "pct_change",
    "vol_rank_120",
    "leave_l20",
    "vs20",
    "vs60",
    "d20",
    "foreign_net",
    "trust_net",
    "dealer_net",
    # 大盤大量區（與個股同一套 find_volume_zone；不混海選勝率）
    "zone_date",
    "zone_high",
    "zone_low",
    "zone_volume",
    "zone_active",
    # 飆大點名點位（對質輔助；不准當買訊）
    "lo",
    "hi",
    "verb",
    "snippet",
    "claim_key",
    "post_date",
    "hit",
    # 他說／我說分軌（靜默；不准當買訊／抬槓）
    "our_lo",
    "our_hi",
    "our_basis",
    "our_path",
    "diverged",
    "winner",
    "his_verdict",
    "our_verdict",
    "variant",
)
# 話筒按鍵改名不准改 kind。pick 才分同一顆鈕底下的子名單。
_OUTER_MARKS = (
    ("_BRENT", "布蘭特", "brent_px", "brent_pct"),
    ("_DXY", "美元指數", "dx_f_px", "dx_f_pct"),
    ("_USDTWD", "美元兌台幣", "usdtwd_px", "usdtwd_pct"),
)
# 大盤／飆大對質用：台指電子日夜盤＋那指／費半／台積已收。沒官方數就不寫。
_FUT_MARKS = (
    ("_TX_D", "TX", "regular", "台指日盤"),
    ("_TX_N", "TX", "night", "台指夜盤"),
    ("_TE_D", "TE", "regular", "電子日盤"),
    ("_TE_N", "TE", "night", "電子夜盤"),
)
_US_LEAD_MARKS = (
    ("_IXIC", "那指", "ixic_px", "ixic_pct"),
    ("_SOX", "費半", "sox_px", "sox_pct"),
    ("_TSMUS", "台積美股", "tsm_px", "tsm_pct"),
)
_LEAVE_ZERO_PICKS = ("0",)


def _bars_on(market_db: str, sids: Sequence[str], day: str) -> Dict[str, Dict[str, float]]:
    """只讀已進庫的官方柱數字。沒有就不寫。不准產圖。"""
    day = _ymd(day)
    want = [str(s).strip() for s in sids if str(s or "").strip()]
    if not market_db or not os.path.isfile(market_db) or not day or not want:
        return {}
    conn = sqlite3.connect(market_db, timeout=8.0)
    out: Dict[str, Dict[str, float]] = {}
    try:
        cols = {str(r[1]) for r in conn.execute("PRAGMA table_info(daily_quotes)")}
        chip = all(
            c in cols for c in ("foreign_net", "trust_net", "dealer_net", "pct_change")
        )
        sql = (
            "SELECT stock_id, open, high, low, close, volume, "
            "foreign_net, trust_net, dealer_net, pct_change"
            if chip
            else "SELECT stock_id, open, high, low, close, volume"
        )
        chunk = 400
        for i in range(0, len(want), chunk):
            part = want[i : i + chunk]
            marks = ",".join("?" * len(part))
            rows = conn.execute(
                f"""
                {sql}
                FROM daily_quotes
                WHERE REPLACE(CAST(date AS TEXT),'-','')=? AND stock_id IN ({marks})
                """,
                [day, *part],
            ).fetchall()
            for row in rows:
                sid = str(row[0])
                bar = {}
                for key, raw in (
                    ("o", row[1]),
                    ("h", row[2]),
                    ("l", row[3]),
                    ("c", row[4]),
                    ("v", row[5]),
                ):
                    n = _num(raw)
                    if n is None:
                        continue
                    bar[key] = n
                if chip and len(row) >= 10:
                    for key, raw in (
                        ("fn", row[6]),
                        ("tn", row[7]),
                        ("dn", row[8]),
                        ("pct", row[9]),
                    ):
                        n = _num(raw)
                        if n is None:
                            continue
                        bar[key] = n
                if bar.get("c"):
                    out[sid] = bar
    except sqlite3.Error:
        return out
    finally:
        conn.close()
    return out


def _row_bar(raw: Dict[str, Any]) -> Dict[str, float]:
    bar: Dict[str, float] = {}
    mapping = (
        ("o", ("open", "o")),
        ("h", ("high", "h")),
        ("l", ("low", "l")),
        ("c", ("close", "c", "price", "px", "pick_close")),
        ("v", ("volume", "v")),
        ("pct", ("pct_change", "pct", "pct_chg")),
    )
    for key, aliases in mapping:
        for a in aliases:
            n = _num(raw.get(a))
            if n is not None:
                bar[key] = n
                break
    return bar


def _ohlcv_complete(bar: Dict[str, Any]) -> bool:
    """真代號要有官方開高低收＋量才算有記。"""
    for key in _BAR_KEYS:
        if _num(bar.get(key)) is None:
            return False
    return True


def remember_rows(
    market_db: str,
    kind: str,
    rows: Iterable[Dict[str, Any]] | None,
    *,
    as_of: str = "",
    pick: str = "",
    src: str = "",
) -> int:
    """記下此刻秀出的判斷。失敗當沒發生，不准影響原功能。"""
    kind = str(kind or "").strip()
    if not market_db or not kind:
        return 0
    day = _as_of(market_db, as_of)
    if not day:
        return 0
    store = store_path(market_db)
    try:
        _ensure(store)
    except Exception:
        return 0
    items = list(rows or [])
    ran = _now()
    tag = str(pick or "")
    sids = []
    for raw in items:
        if not isinstance(raw, dict):
            continue
        sid = str(raw.get("stock_id") or raw.get("code") or raw.get("sid") or "").strip()
        if sid:
            sids.append(sid)
    if not sids:
        return 0
    bars = _bars_on(market_db, sids, day)
    conn = sqlite3.connect(store, timeout=30.0)
    n = 0
    try:
        for raw in items:
            if not isinstance(raw, dict):
                continue
            sid = str(raw.get("stock_id") or raw.get("code") or raw.get("sid") or "").strip()
            if not sid:
                continue
            extra: Dict[str, Any] = {}
            for key in _EXTRA_KEEP:
                if key == "src":
                    continue
                if raw.get(key) not in (None, "", {}, []):
                    extra[key] = raw.get(key) if key != "live" else True
            if src:
                extra["src"] = str(src)
            bar = dict(bars.get(sid) or {})
            bar.update(_row_bar(raw))
            # 個股選股／個人本：缺官方開高低收＋量不算有記。外圍假碼／大盤佐證除外。
            if kind not in _CONTEXT_KINDS and not sid.startswith("_"):
                if not _ohlcv_complete(bar):
                    continue
            for key in _BAR_KEYS + _CHIP_KEYS:
                if key in bar:
                    extra[key] = bar[key]
            if extra.get("fn") is not None and extra.get("foreign_net") is None:
                extra["foreign_net"] = extra["fn"]
            if extra.get("tn") is not None and extra.get("trust_net") is None:
                extra["trust_net"] = extra["tn"]
            if extra.get("dn") is not None and extra.get("dealer_net") is None:
                extra["dealer_net"] = extra["dn"]
            px = _num(raw.get("close") or raw.get("price") or raw.get("px") or extra.get("c"))
            conn.execute(
                """
                INSERT OR REPLACE INTO live_judge(
                    as_of, kind, pick, sid, name, px, profit, extra, ran_at
                ) VALUES (?,?,?,?,?,?,?,?,?)
                """,
                (
                    day,
                    kind,
                    tag,
                    sid,
                    str(raw.get("stock_name") or raw.get("name") or "")[:40],
                    px,
                    _num(raw.get("profit_pct") if raw.get("profit_pct") is not None else raw.get("profit")),
                    json.dumps(extra, ensure_ascii=False) if extra else "",
                    ran,
                ),
            )
            n += 1
        conn.commit()
    except sqlite3.Error:
        return 0
    finally:
        conn.close()
    return n


def ensure_confront_aux(market_db: str, as_of: str = "") -> Dict[str, Any]:
    """對質前輔助資料缺則同步補：台指／電子日夜盤、美股／美指已收。

    只補官方來源；盤中未收不當收。失敗吞掉，不准擋海選／查股／飆大。
    pytest 略過外網。
    """
    out: Dict[str, Any] = {"fut": 0, "us": 0, "day": ""}
    day = _as_of(market_db, as_of)
    out["day"] = day
    if not market_db or not day or not os.path.isfile(market_db):
        return out
    if os.getenv("PYTEST_CURRENT_TEST"):
        return out
    # 期貨：當日台指／電子日夜盤缺柱才補
    need_fut = False
    try:
        conn = sqlite3.connect(market_db, timeout=8.0)
        try:
            names = {
                str(r[0]) for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            if "futures_daily" not in names:
                need_fut = True
            else:
                for _sid, sym, sess, _name in _FUT_MARKS:
                    hit = conn.execute(
                        """
                        SELECT close FROM futures_daily
                        WHERE symbol=? AND session=?
                          AND REPLACE(CAST(date AS TEXT),'-','')=?
                        LIMIT 1
                        """,
                        (sym, sess, day),
                    ).fetchone()
                    close = _num(hit[0]) if hit else None
                    if close is None or close <= 0:
                        need_fut = True
                        break
        finally:
            conn.close()
    except Exception:
        need_fut = True
    if need_fut:
        try:
            from taiwan_market import sync_futures_daily

            got = sync_futures_daily(market_db, dates=[day]) or {}
            out["fut"] = int(got.get("wrote") or got.get("n") or 1)
        except Exception:
            out["fut"] = 0
    # 美股／美指：當日 us_overnight 缺才補（已收才凍；盤中未收不當收）
    need_us = False
    try:
        conn = sqlite3.connect(market_db, timeout=8.0)
        try:
            names = {
                str(r[0]) for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            if "us_overnight" not in names:
                need_us = True
            else:
                row = conn.execute(
                    "SELECT ixic_pct, sox_pct, tsm_pct FROM us_overnight WHERE as_of=?",
                    (day,),
                ).fetchone()
                if not row or all(v is None for v in row):
                    need_us = True
        finally:
            conn.close()
    except Exception:
        need_us = True
    if need_us:
        try:
            from us_overnight import refresh_us_overnight

            snap = refresh_us_overnight(market_db, day) or {}
            out["us"] = 1 if snap else 0
        except Exception:
            out["us"] = 0
    return out


def _freeze_screen_buckets(market_db: str, day: str) -> Dict[str, int]:
    """海選各舊桶靜默凍。例外往外拋，由 run_tracked 蓋失敗戳。"""
    stats: Dict[str, int] = {}
    results: Dict[str, Any] = {}
    src = "none"
    try:
        from screen_sessions import load_session_results, screen_session_has_data

        results = load_session_results(market_db, day, "morning") or {}
        if not any(results.values()):
            results = load_session_results(market_db, day, "evening") or {}
        if any(results.values()) or screen_session_has_data(market_db, day):
            src = "session"
    except Exception:
        results = {}
    if not any(isinstance(results.get(b), list) and results.get(b) for b in _SCREEN_BUCKETS):
        picked = _rows_from_screen_picks(market_db, day)
        if picked:
            results = picked
            src = "picks"
    for bucket in _SCREEN_BUCKETS:
        rows = results.get(bucket) if isinstance(results.get(bucket), list) else []
        stats[bucket] = remember_rows(
            market_db, bucket, rows, as_of=day, pick="rule", src=src
        )
    return stats


def _freeze_streak(market_db: str, day: str) -> Dict[str, int]:
    """連買三類靜默凍。"""
    from buy_streak import KIND_BOTH, KIND_FOREIGN, KIND_TRUST, MARKET_ALL, MIN_STREAK, load_snapshot

    stats: Dict[str, int] = {}
    for kind in (KIND_FOREIGN, KIND_TRUST, KIND_BOTH):
        snap = load_snapshot(market_db, kind, MARKET_ALL, as_of=day, use_cache=True)
        key = f"streak_{kind}"
        days_map = getattr(snap, "by_days", None) or {}
        if not days_map:
            stats[key] = remember_rows(
                market_db, key, [], as_of=day, pick="rule", src="streak"
            )
            continue
        n = 0
        for days, rows in days_map.items():
            if int(days) < int(MIN_STREAK) or not rows:
                continue
            payload = [
                {"stock_id": r.stock_id, "stock_name": getattr(r, "name", "")}
                for r in rows
            ]
            n += remember_rows(
                market_db,
                key,
                payload,
                as_of=day,
                pick=str(int(days)),
                src="streak",
            )
        stats[key] = n
    return stats


def _freeze_emerging(market_db: str, day: str) -> Dict[str, int]:
    """興櫃海選桶靜默凍。"""
    from screening_engine import ScreeningEngine

    stats: Dict[str, int] = {}
    em = ScreeningEngine(market_db).run_emerging_screening(day, sync=False) or {}
    em_day = str(em.get("as_of") or day)
    for bucket, kind in (
        ("leave_zero", "em_leave_zero"),
        ("ma60_lower", "em_ma60_lower"),
        ("golden_buy", "em_golden_buy"),
    ):
        rows = em.get(bucket) if isinstance(em.get(bucket), list) else []
        stats[kind] = remember_rows(
            market_db, kind, rows, as_of=em_day, pick="rule", src="emerging"
        )
    return stats


def _freeze_market_aux(market_db: str, day: str) -> Dict[str, int]:
    """大盤／外圍／期貨／美股佐證凍。"""
    return {
        "market": _snapshot_market(market_db, day),
        "outer": _snapshot_outer(market_db, day),
        "fut": _snapshot_futures(market_db, day),
        "us": _snapshot_us_lead(market_db, day),
    }


def snapshot_button_lists(market_db: str, as_of: str = "") -> Dict[str, int]:
    """當天規則名單沒按也落檔。代號＋為什麼選＋官方柱／量／法人。不准渲圖、不推話筒。

    各功能軌分開落檔、分開蓋 pipeline 成功／失敗戳（sv-*）；
    融合成功不准當每一軌都寫進庫的證明。一軌失敗不擋其他軌。
    """
    stats: Dict[str, int] = {}
    if not market_db:
        return stats
    day = _as_of(market_db, as_of)
    if not day:
        return stats
    from silent_track_runs import run_tracked

    # 對質輔助：缺期貨／美股已收可同步補；未收不當收。失敗不擋。
    try:
        aux = ensure_confront_aux(market_db, day)
        if aux.get("fut") or aux.get("us"):
            stats["aux_sync_fut"] = int(aux.get("fut") or 0)
            stats["aux_sync_us"] = int(aux.get("us") or 0)
    except Exception:
        pass

    def _merge_ok(track: str, fn, *, into: Optional[Dict[str, int]] = None) -> None:
        hit = run_tracked(market_db, track, day, fn)
        payload = hit.get("result")
        target = into if into is not None else stats
        if hit.get("ok") and isinstance(payload, dict):
            for k, v in payload.items():
                try:
                    target[str(k)] = int(v or 0)
                except (TypeError, ValueError):
                    target[str(k)] = 0
        elif hit.get("ok") and isinstance(payload, (int, float)):
            target[track.replace("-", "_")] = int(payload)
        elif not hit.get("ok"):
            # 失敗戳已寫；stats 記 -1 方便本機對質，不當成功筆數
            target[f"_{track}_error"] = 1

    _merge_ok("screen-buckets", lambda: _freeze_screen_buckets(market_db, day))
    _merge_ok("streak", lambda: _freeze_streak(market_db, day))
    if not os.getenv("PYTEST_CURRENT_TEST"):
        _merge_ok("emerging", lambda: _freeze_emerging(market_db, day))
    def _freeze_dongzhu() -> Dict[str, int]:
        # 不准吞例外：失敗要蓋 error 戳（空名單仍算本輪跑完＝success）
        from biaoke_field_scan import dongzhu_picks

        data = dongzhu_picks(market_db, record_flow=False) or {}
        why = str(data.get("why") or "").strip()
        five = str(data.get("five") or "").strip()
        field = str(data.get("field") or "").strip()
        rows = []
        for raw in list(data.get("recs") or []):
            if not isinstance(raw, dict):
                continue
            sid = str(raw.get("sid") or raw.get("stock_id") or "").strip()
            if not sid:
                continue
            rows.append(
                {
                    "stock_id": sid,
                    "stock_name": str(raw.get("name") or raw.get("stock_name") or ""),
                    "close": raw.get("close") or raw.get("px"),
                    "why": str(raw.get("why") or why),
                    "five": five,
                    "field": field or str(raw.get("fine") or ""),
                    "fine": raw.get("fine"),
                    "role": raw.get("role"),
                    "vs20": raw.get("vs20"),
                    "vs60": raw.get("vs60"),
                    "q": raw.get("volr") or raw.get("q"),
                }
            )
        return {
            "dongzhu": remember_rows(
                market_db, "dongzhu", rows, as_of=day, pick="rule", src="dongzhu"
            )
        }

    _merge_ok("dongzhu", _freeze_dongzhu)
    _merge_ok("market-aux", lambda: _freeze_market_aux(market_db, day))
    if not os.getenv("PYTEST_CURRENT_TEST"):
        _merge_ok(
            "leave-zero-picks",
            lambda: _snapshot_leave_zero_picks(market_db, day),
        )
        stats.update(_snapshot_pressure_support(market_db, day))
    # 全鈕缺縫骨架：資金輪動／個人本／AI倉／飆大點名。各軌自己蓋戳。
    try:
        from button_silent_verify import snapshot_all_button_gaps

        stats.update(snapshot_all_button_gaps(market_db, day) or {})
    except Exception as exc:
        from silent_track_runs import mark_track

        mark_track(
            market_db,
            "money-flow",
            day,
            "error",
            f"snapshot_all_button_gaps: {type(exc).__name__}: {exc}",
        )
    return stats


def _snapshot_pressure_support(market_db: str, day: str) -> Dict[str, int]:
    """壓撐觀察沒按也落檔：三標籤各自一列。不是買訊、不改黃金買點。

    壓撐＋其後各 night_tick 軌各自蓋 sv-* 成功／失敗戳；失敗不擋其他軌。
    """
    from silent_track_runs import run_tracked

    stats: Dict[str, int] = {}

    def _pressure_track() -> Dict[str, int]:
        from pressure_rank_verify import night_tick as pressure_night
        from pressure_support_watch import TAG_ORDER, screen_pressure_support

        out: Dict[str, int] = {}
        for tag in TAG_ORDER:
            key = f"pressure_{tag}"
            rows = screen_pressure_support(market_db, tag, as_of=day)
            out[key] = remember_rows(
                market_db, key, rows or [], as_of=day, pick=tag, src="radar"
            )
        # 名單凍＋四軌對質同件；任一步丟例外＝整軌 error 戳
        pressure_night(market_db, day)
        return out

    hit = run_tracked(
        market_db, "pressure", day, _pressure_track, note_ok="pressure freeze+night"
    )
    if hit.get("ok") and isinstance(hit.get("result"), dict):
        stats.update({k: int(v or 0) for k, v in hit["result"].items()})
    else:
        stats["_pressure_error"] = 1

    night_jobs = (
        ("volzone-ma60", "volzone_ma60_verify"),
        ("intraday-lz", "intraday_leave_zero_verify"),
        ("buy-exclude", "buy_exclude_verify"),
        ("winrate-vz-filter", "winrate_volzone_filter_verify"),
        ("lookup-chart", "lookup_chart_verify"),
        ("stabilize", "stabilize_verify"),
        ("biaoke-diverge", "biaoke_diverge"),
        ("fear", "fear_preopen_verify"),
        ("foreign-sell-escalate", "foreign_sell_escalate_verify"),
        ("foreign-sell-extreme", "foreign_sell_extreme_verify"),
        ("foreign-sell-calm", "foreign_sell_calm_verify"),
    )
    for track, mod_name in night_jobs:

        def _make(mod: str = mod_name):
            def _fn():
                m = __import__(mod, fromlist=["night_tick"])
                return m.night_tick(market_db, day)

            return _fn

        run_tracked(market_db, track, day, _make())
    return stats


def _rows_from_screen_picks(market_db: str, day: str) -> Dict[str, List[Dict[str, Any]]]:
    """海選當日有寄出／展示的名單。session 空時仍要確實記代號。"""
    day = _ymd(day)
    out: Dict[str, List[Dict[str, Any]]] = {}
    if not market_db or not os.path.isfile(market_db) or not day:
        return out
    conn = sqlite3.connect(market_db, timeout=8.0)
    try:
        rows = conn.execute(
            """
            SELECT bucket, stock_id, stock_name, pick_close
            FROM screen_picks WHERE REPLACE(CAST(as_of AS TEXT),'-','')=?
            """,
            (day,),
        ).fetchall()
    except sqlite3.Error:
        rows = []
    finally:
        conn.close()
    for bucket, sid, name, close in rows:
        key = str(bucket or "")
        sid_s = str(sid or "").strip()
        if key not in _SCREEN_BUCKETS or not sid_s:
            continue
        out.setdefault(key, []).append(
            {
                "stock_id": sid_s,
                "stock_name": str(name or ""),
                "close": close,
            }
        )
    return out


def _snapshot_dongzhu(market_db: str, day: str) -> int:
    """洞燭先機沒按也落檔。只記推薦檔＋為什麼選＋官方柱／法人。不推話筒。"""
    try:
        from biaoke_field_scan import dongzhu_picks

        data = dongzhu_picks(market_db, record_flow=False) or {}
    except Exception:
        return remember_rows(market_db, "dongzhu", [], as_of=day, pick="rule", src="dongzhu")
    why = str(data.get("why") or "").strip()
    five = str(data.get("five") or "").strip()
    field = str(data.get("field") or "").strip()
    rows = []
    for raw in list(data.get("recs") or []):
        if not isinstance(raw, dict):
            continue
        sid = str(raw.get("sid") or raw.get("stock_id") or "").strip()
        if not sid:
            continue
        rows.append(
            {
                "stock_id": sid,
                "stock_name": str(raw.get("name") or raw.get("stock_name") or ""),
                "close": raw.get("close") or raw.get("px"),
                "why": str(raw.get("why") or why),
                "five": five,
                "field": field or str(raw.get("fine") or ""),
                "fine": raw.get("fine"),
                "role": raw.get("role"),
                "vs20": raw.get("vs20"),
                "vs60": raw.get("vs60"),
                "q": raw.get("volr") or raw.get("q"),
            }
        )
    return remember_rows(
        market_db, "dongzhu", rows, as_of=day, pick="rule", src="dongzhu"
    )


def _market_vol_zone_fields(market_db: str, day: str) -> Dict[str, Any]:
    """大盤大量區欄：接個股 find_volume_zone。失敗當沒有，不准擋落檔。"""
    day = _ymd(day)
    if not market_db or not os.path.isfile(market_db) or not day:
        return {}
    try:
        from vol_zone_chart import (
            VOL_ZONE_BARS,
            VOL_ZONE_LOOKBACK,
            VOL_ZONE_MA60_WARM,
            find_volume_zone,
            load_official_ohlc,
            official_work,
        )

        need = max(int(VOL_ZONE_BARS) + int(VOL_ZONE_LOOKBACK) + int(VOL_ZONE_MA60_WARM), 180)
        raw = load_official_ohlc("TWII", market_db, need)
        work = official_work(raw)
        if work is None or getattr(work, "empty", True):
            return {}
        # 落檔只認 as_of 當日及以前柱；盤中未收不當收
        dnorm = work["date"].astype(str).str.replace("-", "", regex=False).str[:8]
        work = work.loc[dnorm <= day].reset_index(drop=True)
        if work.empty or len(work) < 2:
            return {}
        zone = find_volume_zone(work)
        if not zone:
            return {}
        out: Dict[str, Any] = {}
        zd = _ymd(zone.get("date"))
        if zd:
            out["zone_date"] = zd
        for key, src in (
            ("zone_high", "high"),
            ("zone_low", "low"),
            ("zone_volume", "volume"),
        ):
            n = _num(zone.get(src))
            if n is not None:
                out[key] = n
        out["zone_active"] = bool(zone.get("active"))
        return out
    except Exception:
        return {}


def _snapshot_market(market_db: str, day: str) -> int:
    """台股大盤沒按也落檔。凍官方加權柱＋大量區欄，不產圖。"""
    day = _ymd(day)
    bar: Dict[str, Any] = {}
    if market_db and os.path.isfile(market_db) and day:
        conn = sqlite3.connect(market_db, timeout=8.0)
        try:
            row = conn.execute(
                """
                SELECT open, high, low, close, volume
                FROM index_daily
                WHERE (symbol='TWII' OR symbol='^TWII')
                  AND REPLACE(CAST(date AS TEXT),'-','')=?
                LIMIT 1
                """,
                (day,),
            ).fetchone()
        except sqlite3.Error:
            row = None
        finally:
            conn.close()
        if row:
            for key, raw in (
                ("open", row[0]),
                ("high", row[1]),
                ("low", row[2]),
                ("close", row[3]),
                ("volume", row[4]),
            ):
                n = _num(raw)
                if n is not None:
                    bar[key] = n
    if not bar.get("close"):
        return remember_rows(market_db, "market", [], as_of=day, pick="rule", src="market")
    row: Dict[str, Any] = {
        "stock_id": "TWII",
        "stock_name": "加權",
        "open": bar.get("open"),
        "high": bar.get("high"),
        "low": bar.get("low"),
        "close": bar.get("close"),
        "volume": bar.get("volume"),
    }
    row.update(_market_vol_zone_fields(market_db, day))
    return remember_rows(
        market_db,
        "market",
        [row],
        as_of=day,
        pick="rule",
        src="market",
    )


def _snapshot_outer(market_db: str, day: str) -> int:
    """外圍沒按也落檔。只讀已進庫 payload，不准現場打 Yahoo。"""
    snap: Dict[str, Any] = {}
    if market_db and os.path.isfile(market_db) and day:
        conn = sqlite3.connect(market_db, timeout=8.0)
        try:
            row = conn.execute(
                "SELECT payload FROM us_overnight WHERE as_of=?",
                (day,),
            ).fetchone()
        except sqlite3.Error:
            row = None
        finally:
            conn.close()
        if row and row[0]:
            try:
                blob = json.loads(row[0])
            except (TypeError, json.JSONDecodeError):
                blob = {}
            if isinstance(blob, dict):
                snap = blob
    rows: List[Dict[str, Any]] = []
    for sid, name, px_key, pct_key in _OUTER_MARKS:
        px = _num(snap.get(px_key))
        if px is None or px <= 0:
            continue
        item: Dict[str, Any] = {
            "stock_id": sid,
            "stock_name": name,
            "close": px,
            "px": px,
        }
        pct = _num(snap.get(pct_key))
        if pct is not None:
            item["pct_change"] = pct
        rows.append(item)
    if not rows:
        return remember_rows(market_db, "outer", [], as_of=day, pick="rule", src="outer")
    return remember_rows(
        market_db, "outer", rows, as_of=day, pick="rule", src="outer"
    )


def _snapshot_futures(market_db: str, day: str) -> int:
    """台指／電子日盤＋夜盤。只讀已進庫官方柱，不准現場抓。缺就不寫。"""
    day = _ymd(day)
    rows: List[Dict[str, Any]] = []
    if market_db and os.path.isfile(market_db) and day:
        conn = sqlite3.connect(market_db, timeout=8.0)
        try:
            for sid, sym, sess, name in _FUT_MARKS:
                try:
                    hit = conn.execute(
                        """
                        SELECT open, high, low, close, volume, pct_change
                        FROM futures_daily
                        WHERE symbol=? AND session=?
                          AND REPLACE(CAST(date AS TEXT),'-','')=?
                        LIMIT 1
                        """,
                        (sym, sess, day),
                    ).fetchone()
                except sqlite3.Error:
                    hit = None
                if not hit:
                    continue
                close = _num(hit[3])
                if close is None or close <= 0:
                    continue
                item: Dict[str, Any] = {
                    "stock_id": sid,
                    "stock_name": name,
                    "open": hit[0],
                    "high": hit[1],
                    "low": hit[2],
                    "close": close,
                    "volume": hit[4],
                }
                pct = _num(hit[5])
                if pct is not None:
                    item["pct_change"] = pct
                rows.append(item)
        finally:
            conn.close()
    if not rows:
        return remember_rows(market_db, "fut", [], as_of=day, pick="rule", src="fut")
    return remember_rows(market_db, "fut", rows, as_of=day, pick="rule", src="fut")


def _us_overnight_blob(market_db: str, day: str) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    if not market_db or not os.path.isfile(market_db) or not day:
        return out
    conn = sqlite3.connect(market_db, timeout=8.0)
    try:
        row = conn.execute(
            "SELECT payload FROM us_overnight WHERE as_of=?",
            (day,),
        ).fetchone()
        if row and row[0]:
            try:
                blob = json.loads(row[0])
            except (TypeError, json.JSONDecodeError):
                blob = {}
            if isinstance(blob, dict):
                out.update(blob)
        try:
            cols = conn.execute(
                "SELECT ixic_pct, sox_pct, tsm_pct FROM us_overnight WHERE as_of=?",
                (day,),
            ).fetchone()
        except sqlite3.Error:
            cols = None
        if cols:
            if out.get("ixic_pct") is None and cols[0] is not None:
                out["ixic_pct"] = cols[0]
            if out.get("sox_pct") is None and cols[1] is not None:
                out["sox_pct"] = cols[1]
            if out.get("tsm_pct") is None and cols[2] is not None:
                out["tsm_pct"] = cols[2]
    except sqlite3.Error:
        pass
    finally:
        conn.close()
    return out


def _snapshot_us_lead(market_db: str, day: str) -> int:
    """那指／費半／台積已收。對大盤與飆大隔夜說法。沒官方數就不寫。"""
    day = _ymd(day)
    snap = _us_overnight_blob(market_db, day)
    rows: List[Dict[str, Any]] = []
    for sid, name, px_key, pct_key in _US_LEAD_MARKS:
        px = _num(snap.get(px_key))
        pct = _num(snap.get(pct_key))
        if (px is None or px <= 0) and pct is None:
            continue
        item: Dict[str, Any] = {
            "stock_id": sid,
            "stock_name": name,
        }
        if px is not None and px > 0:
            item["close"] = px
            item["px"] = px
        if pct is not None:
            item["pct_change"] = pct
        rows.append(item)
    if not rows:
        return remember_rows(market_db, "us", [], as_of=day, pick="rule", src="us")
    return remember_rows(market_db, "us", rows, as_of=day, pick="rule", src="us")


def _snapshot_leave_zero_picks(market_db: str, day: str) -> Dict[str, int]:
    """剛脫離零沒按也落檔：昨獲利貼零、今離開 0。不改海選黃金買點。"""
    stats: Dict[str, int] = {}
    try:
        from screening_engine import ScreeningEngine

        engine = ScreeningEngine(market_db)
        frames, em_ids = engine._load_profit_scan_frames(day)
    except Exception:
        for token in _LEAVE_ZERO_PICKS:
            stats[f"leave_zero_{token}"] = remember_rows(
                market_db, "leave_zero", [], as_of=day, pick=token, src="radar"
            )
        return stats
    for token in _LEAVE_ZERO_PICKS:
        try:
            rows = engine._screen_leave_zero_from_profit(
                day,
                days_ago=0,
                mode="ago",
                star_key="leave_zero",
                frames=frames,
                em_ids=em_ids,
            )
            stats[f"leave_zero_{token}"] = remember_rows(
                market_db, "leave_zero", rows or [], as_of=day, pick=token, src="radar"
            )
        except Exception:
            stats[f"leave_zero_{token}"] = remember_rows(
                market_db, "leave_zero", [], as_of=day, pick=token, src="radar"
            )
    return stats


def _quote_dates(market_db: str, cap: str) -> List[str]:
    cap = _ymd(cap)
    if not market_db or not cap or not os.path.isfile(market_db):
        return []
    conn = sqlite3.connect(market_db, timeout=8.0)
    try:
        rows = conn.execute(
            """
            SELECT DISTINCT REPLACE(CAST(date AS TEXT),'-','') AS d
            FROM daily_quotes
            WHERE REPLACE(CAST(date AS TEXT),'-','') <= ?
            ORDER BY d
            """,
            (cap,),
        ).fetchall()
    except sqlite3.Error:
        return []
    finally:
        conn.close()
    return [_ymd(r[0]) for r in rows if _ymd(r[0])]


def _close_on(market_db: str, sid: str, day: str) -> Optional[float]:
    conn = sqlite3.connect(market_db, timeout=8.0)
    try:
        row = conn.execute(
            """
            SELECT close FROM daily_quotes
            WHERE stock_id=? AND REPLACE(CAST(date AS TEXT),'-','')=?
            """,
            (sid, day),
        ).fetchone()
    except sqlite3.Error:
        return None
    finally:
        conn.close()
    return _num(row[0] if row else None)


def _verdict(fwd: Optional[float]) -> str:
    if fwd is None:
        return ""
    if fwd > 0.15:
        return "up"
    if fwd < -0.15:
        return "down"
    return "flat"


def score_live_judges(market_db: str, cap: str = "") -> int:
    """官方柱走完才填隔日／五日。未收盤不寫。"""
    day = _as_of(market_db, cap)
    if not market_db or not day:
        return 0
    store = store_path(market_db)
    if not os.path.isfile(store):
        return 0
    dates = _quote_dates(market_db, day)
    if not dates:
        return 0
    by_i = {d: i for i, d in enumerate(dates)}
    conn = sqlite3.connect(store, timeout=30.0)
    conn.row_factory = sqlite3.Row
    filled = 0
    try:
        conn.executescript(_DDL)
        rows = conn.execute(
            "SELECT as_of, kind, pick, sid, px FROM live_judge WHERE sid!=''"
        ).fetchall()
        scored = {
            (str(r[0]), str(r[1]), str(r[2]), str(r[3]), int(r[4]))
            for r in conn.execute(
                "SELECT as_of, kind, pick, sid, horizon FROM live_judge_score"
            )
        }
        for row in rows:
            as_of = str(row["as_of"] or "")
            sid = str(row["sid"] or "")
            if as_of not in by_i or not sid or sid.startswith("_"):
                continue
            start = by_i[as_of]
            pick_px = _num(row["px"])
            if pick_px is None or pick_px <= 0:
                pick_px = _close_on(market_db, sid, as_of)
            if pick_px is None or pick_px <= 0:
                continue
            for hz in HORIZONS:
                key = (as_of, str(row["kind"]), str(row["pick"] or ""), sid, int(hz))
                if key in scored:
                    continue
                want_i = start + int(hz)
                if want_i >= len(dates):
                    continue
                check = dates[want_i]
                if check > day:
                    continue
                now_px = _close_on(market_db, sid, check)
                if now_px is None or now_px <= 0:
                    continue
                fwd = round((now_px / pick_px - 1.0) * 100.0, 2)
                conn.execute(
                    """
                    INSERT OR REPLACE INTO live_judge_score(
                        as_of, kind, pick, sid, horizon, check_as_of, now_px, fwd_pct, verdict
                    ) VALUES (?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        as_of,
                        str(row["kind"]),
                        str(row["pick"] or ""),
                        sid,
                        int(hz),
                        check,
                        now_px,
                        fwd,
                        _verdict(fwd),
                    ),
                )
                filled += 1
        conn.commit()
    except sqlite3.Error:
        return 0
    finally:
        conn.close()
    return filled
