#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""麥可條件自研模組（靜默）｜討論串長文 → 可量化旗標 → 路徑勝率加測。

設計原則（使用者鎖）：
- 模組必須自研，跟別人不同才有獲勝機會；不准抄現成密技名就當訊號。
- 從飆大楼下「麥可／麥克／大葛格」長文抽取可重述規則，用官方日 K／台指期驗證。
- 有用指標不准輕易放棄：裸 gap_south 側向未過硬閘時，改切市況／下影／季線變體深挖。
- 加測抬大盤方向勝率；不取代飆大主文；不是買訊；不上話筒。

深挖結論（已落碼）：
- 當日 open→close：gap_south ≈65% 收綠 → 當沖空視角成立（michael_gap_south_intraday_down）
- 三日窗硬閘回歸（偏多票）：
  - gap_south + 季線下 + 下影≥0.30
  - gap_south + 季線下 + 昨漲≥1.5%
  - gap_south + 外資 z≥0 +（季線下或下影≥0.25）（裸外資易孤票踩空）
  - gap_south + 空頭市況 + 下影≥0.30
- 檢測窗分軌：當日空不准套三日 fwd；三日回歸票才進 path
"""
from __future__ import annotations

import gzip
import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in __import__("sys").path:
    __import__("sys").path.insert(0, str(ROOT))

MARKET_DB = Path(os.environ.get("WAYNE_DB_PATH") or (ROOT / "data" / "wayne_market.db"))
OUT_DIR = ROOT / "docs" / "expert_notes" / "飆客" / "decade_lab"
TAIPEI = ZoneInfo("Asia/Taipei")
MIN_N = 20
MIN_EDGE = 0.25
MIN_SIDE_HIT = 0.55
SOFT_SIDE_HIT = 0.48
SOFT_EDGE = 0.35
MAX_SOFT_VOTE = 0.45


def _now() -> str:
    return datetime.now(TAIPEI).strftime("%Y-%m-%dT%H:%M:%S")


def _ymd(raw: Any) -> str:
    t = str(raw or "").replace("-", "")[:8]
    return t if len(t) == 8 and t.isdigit() else ""


def _f(v: Any) -> Optional[float]:
    try:
        if v is None or v == "":
            return None
        n = float(v)
    except (TypeError, ValueError):
        return None
    if n != n:
        return None
    return n


def _wick_lower(bar: Dict[str, float]) -> float:
    span = float(bar["high"]) - float(bar["low"])
    if span <= 0:
        return 0.0
    return (min(float(bar["open"]), float(bar["close"])) - float(bar["low"])) / span


def snapshot_michael_factors(
    *,
    twii: Dict[str, Dict[str, float]],
    tx_reg: Dict[str, Dict[str, float]],
    tx_night: Dict[str, float],
    sox: Dict[str, Dict[str, float]],
    tw_days: Sequence[str],
    as_of: str,
    foreign_z: Optional[float] = None,
) -> Tuple[Dict[str, Any], List[str]]:
    """日線代理的麥可自研條件快照（as-of 收盤後，不含未來）。"""
    day = _ymd(as_of)
    factors: Dict[str, Any] = {}
    missing: List[str] = []
    if day not in twii or day not in list(tw_days):
        return factors, ["michael_twii"]
    i = list(tw_days).index(day)
    bar = twii[day]
    if i < 1:
        missing.append("michael_prior")
        return factors, missing

    prev = twii[tw_days[i - 1]]
    prev_c = float(prev["close"])
    o = float(bar["open"])
    c = float(bar["close"])
    h = float(bar["high"])
    lo = float(bar["low"])
    ret = float(bar.get("ret") or 0.0)
    prior_ret = float(prev.get("ret") or 0.0)
    gap = (o / prev_c - 1.0) * 100.0 if prev_c > 0 else 0.0
    wick_today = _wick_lower(bar)

    factors["michael_gap_pct"] = round(gap, 4)
    factors["michael_lower_wick"] = round(wick_today, 4)
    factors["michael_prior_ret"] = round(prior_ret, 4)

    night = _f(tx_night.get(day))
    prior_strong = prior_ret >= 1.2 or (night is not None and night >= 1.0)
    open_high_fade = gap >= 0.6 and c < o and ret <= -0.3
    gap_down_after_strong = prior_strong and gap <= -0.5
    gap_south = bool(open_high_fade or gap_down_after_strong)
    factors["michael_gap_south"] = gap_south
    # 當日空偏＝他當沖視角（驗證用）；路徑 3 日主判看下方硬閘回歸變體
    factors["michael_gap_south_intraday_down"] = bool(gap_south and c < o)
    # 語料高頻：夜盤異常後開高／向南（檢測＝夜盤涨跌＋日盤 gap_south）
    factors["michael_night_hot"] = bool(night is not None and abs(night) >= 0.8)
    factors["michael_gap_south_after_night"] = bool(
        gap_south and night is not None and night >= 0.8
    )

    factors["michael_prior_lower_wick"] = round(_wick_lower(prev), 4)
    factors["michael_wick_flip_risk"] = bool(
        _wick_lower(prev) >= 0.45 and prior_ret > -0.2
    )

    look = tw_days[max(0, i - 10) : i]
    if len(look) >= 5:
        hi10 = max(float(twii[d]["high"]) for d in look)
        lo10 = min(float(twii[d]["low"]) for d in look)
        mid = (hi10 + lo10) / 2.0
        span = hi10 - lo10
        factors["michael_bound_hi"] = round(hi10, 2)
        factors["michael_bound_lo"] = round(lo10, 2)
        factors["michael_bound_span_pct"] = (
            round((span / mid) * 100.0, 4) if mid > 0 else None
        )
        factors["michael_fail_upper"] = bool(
            h >= hi10 * 0.995 and c < hi10 * 0.997 and ret <= 0.2
        )
        factors["michael_break_lower"] = bool(c < lo10 and ret <= -0.5)
        factors["michael_wide_chop"] = bool(
            factors.get("michael_bound_span_pct") is not None
            and float(factors["michael_bound_span_pct"]) >= 3.0
        )
    else:
        missing.append("michael_bounds")

    regime = ""
    below_ma60 = False
    if i >= 60:
        ma60 = sum(float(twii[tw_days[j]]["close"]) for j in range(i - 60, i)) / 60.0
        factors["michael_ma60"] = round(ma60, 2)
        below_ma60 = bool(c < ma60)
        factors["michael_below_ma60"] = below_ma60
        recent_above = any(
            float(twii[tw_days[j]]["close"]) >= ma60 for j in range(max(0, i - 5), i)
        )
        factors["michael_ma60_lost"] = bool(recent_above and c < ma60 * 0.998)
        if c >= ma60 * 1.03:
            regime = "bull"
        elif c <= ma60 * 0.97:
            regime = "bear"
        else:
            regime = "chop"
        factors["michael_regime"] = regime
    else:
        missing.append("michael_ma60")

    sox_days = sorted(sox.keys())
    prior_sox = None
    for d in sox_days:
        if d < day:
            prior_sox = d
        else:
            break
    if prior_sox and prior_sox in sox:
        sr = float(sox[prior_sox].get("ret") or 0.0)
        factors["michael_sox_prior_ret"] = round(sr, 4)
        factors["michael_sox_weak"] = bool(sr <= -1.5)
    else:
        missing.append("michael_sox")

    near_high = (h - c) / h <= 0.002 if h > 0 else False
    factors["michael_bull_a"] = bool(gap >= 2.5 and ret >= 1.5 and near_high)
    factors["michael_bull_b"] = bool(gap <= -2.8 and ret >= 1.2)
    factors["michael_bull_strict"] = bool(
        factors["michael_bull_a"] or factors["michael_bull_b"]
    )

    fz = _f(foreign_z)
    if fz is not None:
        factors["michael_foreign_z"] = round(fz, 4)

    # —— 自研硬閘變體（深挖後保留；路徑三日偏多回歸）——
    if gap_south:
        factors["michael_gap_south_bounce"] = bool(
            below_ma60 and wick_today >= 0.30
        )  # n≈32 edge≈+1.63 side≈0.66
        factors["michael_gap_south_after_strong"] = bool(
            below_ma60 and prior_ret >= 1.5
        )  # n≈52 edge≈+0.84 side≈0.58
        # 外資不空仍過閘有用；孤票踩空改在 path 端 soft_range（不准因孤票廢掉模組）
        factors["michael_gap_south_fx_ok"] = bool(fz is not None and fz >= 0.0)
        # 更嚴變體：外資不空＋季線下或下影（另軌收集；n 未滿閘暫不強投）
        factors["michael_gap_south_fx_ma"] = bool(
            fz is not None
            and fz >= 0.0
            and (below_ma60 or wick_today >= 0.25)
        )
        factors["michael_gap_south_bear_wick"] = bool(
            regime == "bear" and wick_today >= 0.30
        )  # n≈24 edge≈+1.93 side≈0.75
    else:
        factors["michael_gap_south_bounce"] = False
        factors["michael_gap_south_after_strong"] = False
        factors["michael_gap_south_fx_ok"] = False
        factors["michael_gap_south_fx_ma"] = False
        factors["michael_gap_south_bear_wick"] = False
        factors["michael_gap_south_after_night"] = False

    if day in tx_reg:
        factors["michael_tx_ret"] = round(float(tx_reg[day].get("ret") or 0.0), 4)
    else:
        missing.append("michael_tx")

    return factors, missing


def load_tx_regular(conn: sqlite3.Connection) -> Dict[str, Dict[str, float]]:
    out: Dict[str, Dict[str, float]] = {}
    prev = None
    try:
        rows = conn.execute(
            """
            SELECT REPLACE(CAST(date AS TEXT),'-',''), open, high, low, close, pct_change
            FROM futures_daily WHERE symbol='TX' AND session='regular' ORDER BY 1
            """
        ).fetchall()
    except sqlite3.Error:
        return out
    for d, o, h, lo, c, pct in rows:
        day = _ymd(d)
        cc = _f(c)
        if not day or not cc:
            continue
        ret = _f(pct)
        if ret is None and prev and prev > 0:
            ret = (cc / prev - 1.0) * 100.0
        out[day] = {
            "open": _f(o) or cc,
            "high": _f(h) or cc,
            "low": _f(lo) or cc,
            "close": cc,
            "ret": ret if ret is not None else 0.0,
            "ret_ok": ret is not None,
        }
        prev = cc
    return out


def quantify_michael(conn: sqlite3.Connection) -> Dict[str, Any]:
    from scripts.decade_lab_path_forecast import _load_sym, _load_tx_night

    twii = _load_sym(conn, "TWII")
    sox = _load_sym(conn, "SOX")
    tx_reg = load_tx_regular(conn)
    tx_night = _load_tx_night(conn)
    tw_days = sorted(twii.keys())
    idx = {d: i for i, d in enumerate(tw_days)}

    # 外資 z 快取（硬閘 fx_ok 需要）
    foreign_z_by_day: Dict[str, float] = {}
    try:
        from scripts.decade_lab_inst_module import ensure as ensure_inst
        from scripts.decade_lab_inst_module import snapshot_inst_factors

        ensure_inst(conn)
        for d in tw_days:
            inst_f, _ = snapshot_inst_factors(conn, d)
            fz = _f(inst_f.get("inst_foreign_z"))
            if fz is not None:
                foreign_z_by_day[d] = fz
    except Exception:
        pass

    def fwd3(d: str) -> Optional[float]:
        i = idx.get(d)
        if i is None or i + 3 >= len(tw_days):
            return None
        return (twii[tw_days[i + 3]]["close"] / twii[d]["close"] - 1.0) * 100.0

    day_f: Dict[str, Dict[str, Any]] = {}
    for d in tw_days[:-3]:
        f, _m = snapshot_michael_factors(
            twii=twii,
            tx_reg=tx_reg,
            tx_night=tx_night,
            sox=sox,
            tw_days=tw_days,
            as_of=d,
            foreign_z=foreign_z_by_day.get(d),
        )
        if f:
            day_f[d] = f
    days = [d for d in sorted(day_f) if fwd3(d) is not None]
    base = [x for x in (fwd3(d) for d in days) if x is not None]
    base_m = (sum(base) / len(base)) if base else 0.0
    flags: List[Dict[str, Any]] = []
    codes = [
        # 硬閘優先變體（自研深挖；三日窗檢測）
        "michael_gap_south_bounce",
        "michael_gap_south_after_strong",
        "michael_gap_south_fx_ok",
        "michael_gap_south_fx_ma",
        "michael_gap_south_bear_wick",
        "michael_gap_south_after_night",  # 語料：夜盤熱→日向南
        # 基底軟閘（三日回歸）
        "michael_gap_south",
        # 注意：intraday_down 是當日 open→close 概念，不准用三日窗當檢測（方法錯會誤判）
        "michael_wick_flip_risk",
        "michael_fail_upper",
        "michael_break_lower",
        "michael_wide_chop",
        "michael_ma60_lost",
        "michael_sox_weak",
        "michael_bull_strict",
        "michael_below_ma60",
    ]
    def add(code: str) -> None:
        xs = [fwd3(d) for d in days if day_f[d].get(code)]
        xs = [x for x in xs if x is not None]
        if len(xs) < MIN_N:
            return
        m = sum(xs) / len(xs)
        edge = m - base_m
        if edge > 0:
            hit = sum(1 for x in xs if x > 0.6) / len(xs)
        else:
            hit = sum(1 for x in xs if x < -0.6) / len(xs)
        hard = abs(edge) >= MIN_EDGE and hit >= MIN_SIDE_HIT
        soft = (not hard) and abs(edge) >= SOFT_EDGE and hit >= SOFT_SIDE_HIT
        if not hard and not soft:
            return
        vote = float(edge)
        if soft:
            mag = min(MAX_SOFT_VOTE, abs(vote) * 0.55)
            vote = mag if vote > 0 else -mag
        flags.append(
            {
                "flag": code,
                "n": len(xs),
                "fwd3_avg": round(m, 4),
                "edge3": round(edge, 4),
                "vote": round(vote, 4),
                "hit_rate_side": round(hit, 4),
                "gate": "hard" if hard else "soft",
                "source": "michael_self_module",
            }
        )

    for code in codes:
        add(code)

    # 當日空偏：檢測窗＝open→close（不准誤用三日 fwd；方法錯會把當日空當三日多）
    intradaily: List[float] = []
    for d in days:
        if not day_f[d].get("michael_gap_south_intraday_down"):
            continue
        bar = twii.get(d) or {}
        o = _f(bar.get("open"))
        c = _f(bar.get("close"))
        if o and c and o > 0:
            intradaily.append((c / o - 1.0) * 100.0)
    if len(intradaily) >= MIN_N:
        m = sum(intradaily) / len(intradaily)
        edge = m  # vs 0
        hit = sum(1 for x in intradaily if x < -0.15) / len(intradaily)
        hard = edge <= -0.25 and hit >= MIN_SIDE_HIT
        soft = (not hard) and edge <= -0.15 and hit >= SOFT_SIDE_HIT
        if hard or soft:
            vote = float(edge)
            if soft:
                mag = min(MAX_SOFT_VOTE, abs(vote) * 0.55)
                vote = -mag
            flags.append(
                {
                    "flag": "michael_gap_south_intraday_down",
                    "n": len(intradaily),
                    "fwd3_avg": None,
                    "same_day_oc_avg": round(m, 4),
                    "edge3": round(edge, 4),
                    "vote": round(vote, 4),
                    "hit_rate_side": round(hit, 4),
                    "gate": "hard" if hard else "soft",
                    "horizon": "same_day_open_close",
                    "path_vote": False,
                    "source": "michael_self_module",
                    "note_zh": "檢測＝當日開收；不准套三日窗；不進 path 三日票",
                }
            )

    flags.sort(key=lambda r: (r.get("gate") != "hard", -abs(r.get("edge3") or 0)))
    out = {
        "written_at": _now(),
        "tz": "Asia/Taipei",
        "source": "michael_self_module",
        "note_zh": (
            "自研模組：麥可長文→日K變體；有用指標深挖不棄；"
            "當日空／三日回歸分軌（檢測窗對齊）；不取代飆大；不是買訊"
        ),
        "n_days": len(days),
        "base3": round(base_m, 4),
        "flags": flags,
        "hard_flags": [f["flag"] for f in flags if f.get("gate") == "hard"],
        "gate": "hard: n>=20 & |edge|>=0.25 & side>=0.55；soft 降權；當日空另軌",
        "not_buy_signal": True,
        "phone_sync": "blocked",
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "michael_quant_latest.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    with gzip.open(OUT_DIR / "michael_quant_flags.jsonl.gz", "wt", encoding="utf-8") as f:
        for r in flags:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return out


def load_michael_votes() -> Dict[str, float]:
    path = OUT_DIR / "michael_quant_latest.json"
    votes: Dict[str, float] = {}
    if not path.is_file():
        return votes
    try:
        blob = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return votes
    for r in blob.get("flags") or []:
        # 當日窗旗標不准混進三日 path 票（檢測方法分軌）
        if r.get("path_vote") is False:
            continue
        if str(r.get("horizon") or "") == "same_day_open_close":
            continue
        flag = str(r.get("flag") or "")
        vote = _f(r.get("vote"))
        edge = _f(r.get("edge3"))
        n = int(r.get("n") or 0)
        if flag and n >= MIN_N:
            if vote is not None:
                votes[flag] = float(vote)
            elif edge is not None:
                votes[flag] = float(edge)
    return votes


def extract_michael_corpus(conn: sqlite3.Connection, *, limit_articles: int = 12) -> Dict[str, Any]:
    """近窗討論串：被點名感謝的麥可長文落檔（學習材料，不當飆大判斷）。"""
    thanks = conn.execute(
        """
        SELECT reply_to, COUNT(*) n
        FROM biaoke_thread
        WHERE (
            text LIKE '%麥可%' OR text LIKE '%麥克%' OR text LIKE '%大葛格%'
            OR text LIKE '%麥可大%' OR text LIKE '%麥可哥%'
          )
          AND IFNULL(reply_to,'') != ''
        GROUP BY 1
        HAVING n >= 2
        ORDER BY n DESC
        """
    ).fetchall()
    rows_out = []
    for reply_to, n in thanks:
        art = str(reply_to).split("-")[0]
        cid = f"{art}:c{reply_to}"
        row = conn.execute(
            "SELECT id, article_id, date, time, text FROM biaoke_thread WHERE id=?",
            (cid,),
        ).fetchone()
        if not row or len(str(row[4] or "")) < 200:
            # 備援：id 尾碼對得上的長文
            row = conn.execute(
                """
                SELECT id, article_id, date, time, text FROM biaoke_thread
                WHERE id LIKE ? AND length(text) >= 200
                ORDER BY length(text) DESC LIMIT 1
                """,
                (f"%c{reply_to}",),
            ).fetchone()
        if not row or len(str(row[4] or "")) < 200:
            continue
        rows_out.append(
            {
                "id": row[0],
                "article_id": row[1],
                "date": row[2],
                "time": row[3],
                "thanks_n": int(n),
                "text": row[4],
                "voice": "michael",
            }
        )
    out = {
        "written_at": _now(),
        "tz": "Asia/Taipei",
        "n": len(rows_out),
        "note_zh": "自研材料：麥可長文；加測用；不當飆大判斷；不上話筒",
        "posts": [
            {
                "id": r["id"],
                "article_id": r["article_id"],
                "date": r["date"],
                "time": r["time"],
                "thanks_n": r["thanks_n"],
                "snip": (r["text"] or "")[:400],
            }
            for r in rows_out
        ],
        "not_buy_signal": True,
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "michael_corpus_latest.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return out


if __name__ == "__main__":
    conn = sqlite3.connect(str(MARKET_DB), timeout=60.0)
    try:
        corp = extract_michael_corpus(conn)
        print("corpus", corp.get("n"), flush=True)
        q = quantify_michael(conn)
        print(
            "flags",
            len(q.get("flags") or []),
            "hard",
            q.get("hard_flags"),
            flush=True,
        )
    finally:
        conn.close()
