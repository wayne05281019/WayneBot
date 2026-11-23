# -*- coding: utf-8 -*-
"""飆大觀測・BK-VERIFY 自測核心（§13 再生／不准混海選／黃金買點）。

三軌考題（歷史開市日官方柱）：
1. chain_trio：夜盤美指／SOX → 早盤 TX → 現貨加權（三層觀測鏈）
2. level_touch：他點過的位是否被後窗官方柱碰到
3. segment_bias：試標段／forward 路徑是否對／偏／未完

硬邊界：
- Asia/Taipei；已收官方柱；空名單不算；phone_sync=blocked；不是買訊
- 勝率不准混進海選／黃金買點；WAVE 段號仍屬警語層
- 錯案必填 miss_analysis，並預留下一版候選鍵
"""
from __future__ import annotations

import json
import os
import sqlite3
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
MARKET_DB = Path(os.environ.get("WAYNE_DB_PATH") or (ROOT / "data" / "wayne_market.db"))
OUT_DIR = ROOT / "docs" / "expert_notes" / "飆客" / "observe_manual"
CASES_DIR = OUT_DIR / "cases"
TAIPEI = ZoneInfo("Asia/Taipei")

TRACK = "bk_verify"
VARIANT_CURRENT = "bk_verify_v1_trio_level_seg"
VARIANT_NEXT = "bk_verify_v2_chain_sox_strict"
MIN_N = 20
TOL_PCT = 0.005
FWD_N = 5
PHONE_SYNC = "blocked"

VERDICT_HIT = "對"
VERDICT_MISS = "偏"
VERDICT_OPEN = "未完"
VERDICT_EMPTY = "空名單"


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


def score_level_vs_fwd(
    level: float,
    role: str,
    bars: Sequence[Dict[str, float]],
    i0: int,
    *,
    fwd: int = FWD_N,
    tol_pct: float = TOL_PCT,
    include_day0: bool = False,
) -> Tuple[str, Optional[bool]]:
    """他點過的位 → 後窗官方柱：對／偏／未完（預設不含發文當日）。"""
    if i0 < 0 or i0 >= len(bars) or level <= 0:
        return "缺柱", None
    start = i0 if include_day0 else i0 + 1
    end = i0 + int(fwd)
    if end >= len(bars) or start > end:
        return VERDICT_OPEN, None
    win = list(bars[start : end + 1])
    if not win:
        return VERDICT_OPEN, None
    # 缺完整 OHLC 的柱不准當收（ohlc_complete=False 或缺高低）
    usable = []
    for b in win:
        if b.get("ohlc_complete") is False:
            return VERDICT_OPEN, None
        if _f(b.get("high")) is None or _f(b.get("low")) is None or _f(b.get("close")) is None:
            return VERDICT_OPEN, None
        usable.append(b)
    if not usable:
        return VERDICT_OPEN, None
    mx = max(float(b["high"]) for b in usable)
    mn = min(float(b["low"]) for b in usable)
    last = float(usable[-1]["close"])
    tol = float(level) * float(tol_pct)
    touched = any(
        float(b["low"]) - tol <= float(level) <= float(b["high"]) + tol for b in usable
    )
    role_l = str(role or "touch")
    if role_l == "support":
        if mn >= float(level) - tol:
            return VERDICT_HIT, True
        if mn < float(level) - 3 * tol and last < float(level) - tol:
            return VERDICT_MISS, False
        if touched and last >= float(level) - tol:
            return VERDICT_HIT, True
        return VERDICT_MISS, False
    if role_l == "break":
        if mn <= float(level) + tol:
            return VERDICT_HIT, True
        return VERDICT_MISS, False
    if role_l == "pressure":
        if mx >= float(level) - tol:
            return VERDICT_HIT, True
        if last < float(level) - 2 * tol and mx < float(level) - tol:
            return VERDICT_MISS, False
        return VERDICT_OPEN, None
    if touched:
        return VERDICT_HIT, True
    return VERDICT_MISS, False


def build_miss_analysis(
    *,
    case_id: str,
    track: str,
    expected: str,
    actual: str,
    unexpected: str = "",
    which_broke: str = "",
    rule_patch: str = "",
    next_variant: str = VARIANT_NEXT,
) -> Dict[str, Any]:
    """錯案除錯鉤子：每次 miss／偏必留；§13 同件預留下一版鍵。"""
    return {
        "case_id": case_id,
        "track": track,
        "expected": expected,
        "actual_path": actual,
        "unexpected_level": unexpected,
        "which_segment_broke": which_broke,
        "rule_patch": rule_patch
        or f"下一版候選鍵 {next_variant}：收緊 SOX／夜盤方向一致才給 chain 對",
        "next_variant": next_variant,
        "not_buy_signal": True,
        "mix_forbidden_zh": "勝率不准混進海選／黃金買點",
    }


def score_rows(rows: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    decided = [r for r in rows if r.get("ok") is True or r.get("ok") is False]
    # 空名單不算
    decided = [r for r in decided if str(r.get("verdict") or "") != VERDICT_EMPTY]
    hit = sum(1 for r in decided if r.get("ok") is True)
    miss = sum(1 for r in decided if r.get("ok") is False)
    n = hit + miss
    days = sorted({str(r.get("as_of") or "") for r in decided if r.get("as_of")})
    return {
        "n_rows": len(rows),
        "n_decided": n,
        "hit": hit,
        "miss": miss,
        "hit_rate": (hit / n) if n else None,
        "gate_n20": n >= MIN_N and len(days) >= MIN_N,
        "n_days": len(days),
        "outcome_counts": dict(Counter(str(r.get("verdict") or "") for r in rows)),
        "empty_skipped": sum(1 for r in rows if r.get("verdict") == VERDICT_EMPTY),
    }


def load_twii_bars(
    con: sqlite3.Connection, *, since: str = "20240101"
) -> List[Dict[str, float]]:
    rows = con.execute(
        """
        SELECT REPLACE(CAST(date AS TEXT),'-',''), open, high, low, close
        FROM index_daily WHERE symbol='TWII' AND REPLACE(CAST(date AS TEXT),'-','')>=?
        ORDER BY 1
        """,
        (since,),
    ).fetchall()
    out: List[Dict[str, float]] = []
    for d, o, h, l, c in rows:
        day = _ymd(d)
        cc = _f(c)
        if not day or not cc:
            continue
        oo, hh, ll = _f(o), _f(h), _f(l)
        # 缺 OHLC 仍留下 close，但標記 incomplete（對質時當未完）
        out.append(
            {
                "date": day,
                "open": oo if oo is not None else cc,
                "high": hh if hh is not None else cc,
                "low": ll if ll is not None else cc,
                "close": cc,
                "ohlc_complete": oo is not None and hh is not None and ll is not None,
            }
        )
    return out


def load_tx_bars(
    con: sqlite3.Connection, *, since: str = "20240101", session: str = "regular"
) -> List[Dict[str, float]]:
    rows = con.execute(
        """
        SELECT REPLACE(CAST(date AS TEXT),'-',''), session, open, high, low, close
        FROM futures_daily
        WHERE symbol='TX' AND REPLACE(CAST(date AS TEXT),'-','')>=? AND session=?
        ORDER BY 1
        """,
        (since, session),
    ).fetchall()
    out: List[Dict[str, float]] = []
    for d, sess, o, h, l, c in rows:
        day = _ymd(d)
        cc = _f(c)
        if not day or not cc:
            continue
        oo, hh, ll = _f(o), _f(h), _f(l)
        if oo is None or hh is None or ll is None:
            continue
        out.append(
            {
                "date": day,
                "session": str(sess or session),
                "open": oo,
                "high": hh,
                "low": ll,
                "close": cc,
                "ohlc_complete": True,
            }
        )
    return out


def load_us_overnight(con: sqlite3.Connection) -> Dict[str, Dict[str, Any]]:
    try:
        rows = con.execute(
            """
            SELECT as_of, us_session, regime, sox_pct, nq_f_pct, ixic_pct, spx_pct
            FROM us_overnight ORDER BY as_of
            """
        ).fetchall()
    except sqlite3.Error:
        return {}
    out: Dict[str, Dict[str, Any]] = {}
    for as_of, us_sess, regime, sox, nq, ixic, spx in rows:
        day = _ymd(as_of)
        if not day:
            continue
        out[day] = {
            "as_of": day,
            "us_session": _ymd(us_sess) or day,
            "regime": str(regime or ""),
            "sox_pct": _f(sox),
            "nq_f_pct": _f(nq),
            "ixic_pct": _f(ixic),
            "spx_pct": _f(spx),
        }
    return out


def grade_level_touch_case(
    case: Dict[str, Any], bars: Sequence[Dict[str, float]]
) -> Dict[str, Any]:
    """考「他點過的位是否碰到」。"""
    case_id = str(case.get("case_id") or "level_touch")
    as_of = _ymd(case.get("as_of"))
    levels = list(case.get("levels") or [])
    if not levels:
        return {
            "case_id": case_id,
            "track": "level_touch",
            "as_of": as_of,
            "verdict": VERDICT_EMPTY,
            "ok": None,
            "note_zh": "空名單不算",
            "variant": VARIANT_CURRENT,
        }
    day_i = {str(b["date"]): i for i, b in enumerate(bars)}
    if not as_of or as_of not in day_i:
        return {
            "case_id": case_id,
            "track": "level_touch",
            "as_of": as_of,
            "verdict": VERDICT_OPEN,
            "ok": None,
            "note_zh": "缺 as_of 官方柱",
            "deps_missing": ["official_twii_as_of"],
            "variant": VARIANT_CURRENT,
        }
    i0 = day_i[as_of]
    fwd = int(case.get("fwd") or FWD_N)
    tol = float(case.get("tol_pct") or TOL_PCT)
    sub: List[Dict[str, Any]] = []
    for lv in levels:
        level = _f(lv.get("level"))
        role = str(lv.get("role") or "touch")
        if not level:
            continue
        verd, ok = score_level_vs_fwd(
            float(level), role, bars, i0, fwd=fwd, tol_pct=tol, include_day0=False
        )
        # 發文當日柱本身缺完整 OHLC → 未完
        if bars[i0].get("ohlc_complete") is False:
            verd, ok = VERDICT_OPEN, None
        sub.append(
            {
                "level": float(level),
                "role": role,
                "verdict": verd,
                "ok": ok,
                "source": lv.get("source") or "oral",
            }
        )
    if not sub:
        return {
            "case_id": case_id,
            "track": "level_touch",
            "as_of": as_of,
            "verdict": VERDICT_EMPTY,
            "ok": None,
            "note_zh": "空名單不算",
            "variant": VARIANT_CURRENT,
        }
    decided = [s for s in sub if s.get("ok") is True or s.get("ok") is False]
    if not decided:
        verd = VERDICT_OPEN
        ok: Optional[bool] = None
    else:
        hit_n = sum(1 for s in decided if s["ok"] is True)
        verd = VERDICT_HIT if hit_n >= (len(decided) - hit_n) else VERDICT_MISS
        ok = verd == VERDICT_HIT
    row: Dict[str, Any] = {
        "case_id": case_id,
        "track": "level_touch",
        "as_of": as_of,
        "verdict": verd,
        "ok": ok,
        "levels": sub,
        "fwd": fwd,
        "tol_pct": tol,
        "variant": VARIANT_CURRENT,
        "deps": list(case.get("deps") or ["official_twii"]),
    }
    if ok is False:
        bad = [s for s in sub if s.get("ok") is False]
        row["miss_analysis"] = build_miss_analysis(
            case_id=case_id,
            track="level_touch",
            expected="後窗官方柱碰到他點過的位（角色相符）",
            actual=f"偏：{json.dumps(bad, ensure_ascii=False)[:240]}",
            unexpected="; ".join(f"{s['level']}@{s['role']}" for s in bad),
            which_broke="level_touch",
            rule_patch=(
                f"下一版 {VARIANT_NEXT}：level 角色改為僅認文內明確支撐／壓力／必破；"
                "touch 灌水列剔除"
            ),
        )
    return row


def _path_outcome_from_bar(
    path: Dict[str, Any], bar: Dict[str, float], *, tol_pct: float = TOL_PCT
) -> Tuple[str, Optional[bool], str]:
    """用當日官方柱對一條試標路徑給對／偏／未完。"""
    pid = str(path.get("id") or "")
    levels = path.get("levels") or {}
    hh, ll, cc = _f(bar.get("high")), _f(bar.get("low")), _f(bar.get("close"))
    if hh is None or ll is None or cc is None:
        return VERDICT_OPEN, None, "缺完整官方柱"
    # 常見語意：retest/broke/target/reclaim/fail
    if "retest" in levels or "broke" in levels:
        lv = _f(levels.get("retest") or levels.get("broke"))
        if lv is None:
            return VERDICT_OPEN, None, "缺 retest/broke 位"
        tol = float(lv) * tol_pct
        if ll <= float(lv) + tol:
            return VERDICT_HIT, True, f"L{ll:.2f} 測到／破 {lv}"
        return VERDICT_MISS, False, f"L{ll:.2f} 未測到 {lv}"
    if "reclaim" in levels:
        lv = _f(levels["reclaim"])
        if lv is None:
            return VERDICT_OPEN, None, "缺 reclaim 位"
        tol = float(lv) * tol_pct
        if cc >= float(lv) - tol and hh >= float(lv) - tol:
            return VERDICT_HIT, True, f"C{cc:.2f} 收復 {lv}"
        return VERDICT_MISS, False, f"C{cc:.2f} 未收復 {lv}"
    if "lo" in levels and "hi" in levels:
        lo, hi = _f(levels["lo"]), _f(levels["hi"])
        if lo is None or hi is None:
            return VERDICT_OPEN, None, "缺 band"
        # 收回帶：高點進帶或收進帶
        if hh >= float(lo) or (float(lo) <= cc <= float(hi)):
            return VERDICT_HIT, True, f"H{hh:.2f}/C{cc:.2f} 碰到帶 {lo}-{hi}"
        return VERDICT_MISS, False, f"H{hh:.2f} 未進帶 {lo}-{hi}"
    # 試標段列表 fallback
    segs = list(path.get("segments_provisional") or [])
    if not segs:
        return VERDICT_EMPTY, None, "空段號不算"
    hits = misses = 0
    notes = []
    for s in segs:
        lv = _f(s.get("level"))
        lo, hi = _f(s.get("lo")), _f(s.get("hi"))
        if lv is not None:
            tol = float(lv) * tol_pct
            if float(ll) - tol <= float(lv) <= float(hh) + tol:
                hits += 1
                notes.append(f"{s.get('label')}:觸{lv}")
            else:
                misses += 1
                notes.append(f"{s.get('label')}:未觸{lv}")
        elif lo is not None and hi is not None:
            if hh >= float(lo):
                hits += 1
                notes.append(f"{s.get('label')}:進帶")
            else:
                misses += 1
                notes.append(f"{s.get('label')}:未進帶")
    if hits + misses == 0:
        return VERDICT_EMPTY, None, "空段號不算"
    if hits >= misses:
        return VERDICT_HIT, True, f"{pid}: " + "; ".join(notes)
    return VERDICT_MISS, False, f"{pid}: " + "; ".join(notes)


def grade_segment_bias_case(case: Dict[str, Any]) -> Dict[str, Any]:
    """考試標段／forward 路徑：用 as_of 官方柱對質。"""
    case_id = str(case.get("case_id") or "segment_bias")
    as_of = _ymd(case.get("as_of"))
    bar = case.get("official_bar") or {}
    paths = list(case.get("paths") or [])
    preferred = str(case.get("preferred") or (paths[0].get("id") if paths else ""))
    if not paths:
        return {
            "case_id": case_id,
            "track": "segment_bias",
            "as_of": as_of,
            "verdict": VERDICT_EMPTY,
            "ok": None,
            "note_zh": "空名單不算",
            "variant": VARIANT_CURRENT,
        }
    if not bar or _f(bar.get("close")) is None:
        return {
            "case_id": case_id,
            "track": "segment_bias",
            "as_of": as_of,
            "verdict": VERDICT_OPEN,
            "ok": None,
            "deps_missing": ["official_bar_in_case_or_db"],
            "variant": VARIANT_CURRENT,
        }
    path_rows = []
    for p in paths:
        verd, ok, note = _path_outcome_from_bar(p, bar)
        path_rows.append(
            {
                "id": p.get("id"),
                "verdict": verd,
                "ok": ok,
                "note": note,
                "segments_provisional": p.get("segments_provisional") or [],
            }
        )
    pref_row = next((r for r in path_rows if r["id"] == preferred), path_rows[0])
    verd = pref_row["verdict"]
    ok = pref_row["ok"]
    row: Dict[str, Any] = {
        "case_id": case_id,
        "track": "segment_bias",
        "as_of": as_of,
        "preferred": preferred,
        "verdict": verd,
        "ok": ok,
        "paths": path_rows,
        "official_bar": {
            "o": _f(bar.get("open")),
            "h": _f(bar.get("high")),
            "l": _f(bar.get("low")),
            "c": _f(bar.get("close")),
            "v": _f(bar.get("volume")),
        },
        "variant": VARIANT_CURRENT,
        "deps": list(case.get("deps") or ["wave_forward_infer", "official_twii"]),
        "pot": "試標・推論／非他原文・非買訊",
    }
    if ok is False:
        row["miss_analysis"] = build_miss_analysis(
            case_id=case_id,
            track="segment_bias",
            expected=f"preferred {preferred} 應對官方柱成立",
            actual=pref_row.get("note") or "偏",
            unexpected=json.dumps(
                [r for r in path_rows if r.get("ok") is True], ensure_ascii=False
            )[:240],
            which_broke=str(preferred),
            rule_patch=(
                f"下一版 {VARIANT_NEXT}：preferred 失效時改看同日成立路徑並回寫 "
                "miss→handbooks；不准發明新價"
            ),
        )
    return row


def _regime_bias(overnight: Dict[str, Any]) -> Optional[str]:
    """夜盤偏向：risk_off／risk_on／mixed；缺 SOX／NQ 回 None。"""
    sox = _f(overnight.get("sox_pct"))
    nq = _f(overnight.get("nq_f_pct"))
    regime = str(overnight.get("regime") or "")
    if sox is None and nq is None and not regime:
        return None
    if regime == "risk_off" or (sox is not None and sox <= -1.5):
        return "down"
    if regime == "risk_on" or (sox is not None and sox >= 1.5):
        return "up"
    if nq is not None and nq <= -0.8:
        return "down"
    if nq is not None and nq >= 0.8:
        return "up"
    return "mixed"


def grade_chain_trio_case(
    case: Dict[str, Any],
    *,
    overnight_map: Dict[str, Dict[str, Any]],
    tx_regular: Sequence[Dict[str, float]],
    twii: Sequence[Dict[str, float]],
) -> Dict[str, Any]:
    """考三層觀測鏈：夜盤 → TX 日盤 → 加權現貨。"""
    case_id = str(case.get("case_id") or "chain_trio")
    as_of = _ymd(case.get("as_of"))
    deps_missing: List[str] = []
    ov = dict(case.get("overnight") or {})
    if not ov:
        ov = dict(overnight_map.get(as_of) or {})
    if not ov:
        # 常用：美股 session 日＝台股前一曆日；允許 case 指定 overnight_as_of
        oa = _ymd(case.get("overnight_as_of"))
        if oa and oa in overnight_map:
            ov = dict(overnight_map[oa])
        else:
            deps_missing.append("us_overnight_sox_or_nq")

    tx_i = {b["date"]: b for b in tx_regular}
    tw_i = {b["date"]: b for b in twii}
    tx = dict(case.get("tx_bar") or {}) or dict(tx_i.get(as_of) or {})
    tw = dict(case.get("twii_bar") or {}) or dict(tw_i.get(as_of) or {})
    if not tx:
        deps_missing.append("tx_regular_bar")
    if not tw or tw.get("ohlc_complete") is False:
        # 從 dict 嵌入的 bar 沒有 ohlc_complete 欄時，用 OHLC 有無判斷
        if _f(tw.get("high")) is None or _f(tw.get("low")) is None:
            deps_missing.append("twii_complete_ohlc")

    night_bias = _regime_bias(ov) if ov else None
    if night_bias is None and "us_overnight_sox_or_nq" not in deps_missing:
        deps_missing.append("us_overnight_sox_or_nq")

    if deps_missing and (not ov or not tx or not tw):
        return {
            "case_id": case_id,
            "track": "chain_trio",
            "as_of": as_of,
            "verdict": VERDICT_OPEN,
            "ok": None,
            "deps_missing": deps_missing,
            "note_zh": "BK-CHAIN／官方柱未齊；框架可跑、本題標未完",
            "variant": VARIANT_CURRENT,
            "layers": {
                "night": ov or None,
                "tx": tx or None,
                "twii": tw or None,
            },
        }

    tx_c, tx_o = _f(tx.get("close")), _f(tx.get("open"))
    tw_c, tw_o = _f(tw.get("close")), _f(tw.get("open"))
    tx_bias = None
    if tx_c is not None and tx_o is not None:
        if tx_c < tx_o * (1 - 0.003):
            tx_bias = "down"
        elif tx_c > tx_o * (1 + 0.003):
            tx_bias = "up"
        else:
            tx_bias = "flat"
    tw_bias = None
    if tw_c is not None and tw_o is not None:
        if tw_c < tw_o * (1 - 0.003):
            tw_bias = "down"
        elif tw_c > tw_o * (1 + 0.003):
            tw_bias = "up"
        else:
            tw_bias = "flat"

    # 鏈對：夜盤 down → TX 非 up → TWII 非 up（弱鏈）；up 對稱；mixed 只看 TX／TWII 同向
    expected = str(case.get("expect_chain") or night_bias or "mixed")
    layers_ok = []
    if expected == "down":
        layers_ok.append(night_bias in ("down", "mixed"))
        layers_ok.append(tx_bias in ("down", "flat"))
        layers_ok.append(tw_bias in ("down", "flat"))
    elif expected == "up":
        layers_ok.append(night_bias in ("up", "mixed"))
        layers_ok.append(tx_bias in ("up", "flat"))
        layers_ok.append(tw_bias in ("up", "flat"))
    else:
        layers_ok.append(tx_bias == tw_bias and tx_bias is not None)

    if all(layers_ok):
        verd, ok = VERDICT_HIT, True
    elif any(x is None for x in (night_bias, tx_bias, tw_bias)):
        verd, ok = VERDICT_OPEN, None
    else:
        verd, ok = VERDICT_MISS, False

    row: Dict[str, Any] = {
        "case_id": case_id,
        "track": "chain_trio",
        "as_of": as_of,
        "verdict": verd,
        "ok": ok,
        "expect_chain": expected,
        "layers": {
            "night_bias": night_bias,
            "tx_bias": tx_bias,
            "twii_bias": tw_bias,
            "overnight": {
                "regime": ov.get("regime"),
                "sox_pct": ov.get("sox_pct"),
                "nq_f_pct": ov.get("nq_f_pct"),
            },
            "tx": {"o": tx_o, "h": _f(tx.get("high")), "l": _f(tx.get("low")), "c": tx_c},
            "twii": {"o": tw_o, "h": _f(tw.get("high")), "l": _f(tw.get("low")), "c": tw_c},
        },
        "deps": list(case.get("deps") or ["us_overnight", "tx_regular", "twii"]),
        "deps_missing": deps_missing,
        "variant": VARIANT_CURRENT,
        "note_zh": "三層鏈只對方向一致性；不是買訊；SOX 缺則未完",
    }
    if ok is False:
        row["miss_analysis"] = build_miss_analysis(
            case_id=case_id,
            track="chain_trio",
            expected=f"鏈方向 {expected}",
            actual=(
                f"night={night_bias} tx={tx_bias} twii={tw_bias}"
            ),
            unexpected="層間背離",
            which_broke="chain_trio",
            rule_patch=(
                f"下一版 {VARIANT_NEXT}：SOX≤-1.5 才准標弱鏈對；"
                "NQ 缺時不得用 regime 字串單獨過關"
            ),
        )
    return row


def load_case_files(cases_dir: Path = CASES_DIR) -> List[Dict[str, Any]]:
    if not cases_dir.is_dir():
        return []
    out: List[Dict[str, Any]] = []
    for p in sorted(cases_dir.glob("*.json")):
        try:
            blob = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(blob, list):
            out.extend([x for x in blob if isinstance(x, dict)])
        elif isinstance(blob, dict):
            if isinstance(blob.get("cases"), list):
                out.extend([x for x in blob["cases"] if isinstance(x, dict)])
            else:
                out.append(blob)
    return out


def run_suite(
    *,
    db_path: Path = MARKET_DB,
    cases_dir: Path = CASES_DIR,
    out_dir: Path = OUT_DIR,
    write: bool = True,
) -> Dict[str, Any]:
    cases = load_case_files(cases_dir)
    twii: List[Dict[str, float]] = []
    tx_reg: List[Dict[str, float]] = []
    overnight: Dict[str, Dict[str, Any]] = {}
    db_ok = db_path.is_file()
    if db_ok:
        con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            twii = load_twii_bars(con)
            tx_reg = load_tx_bars(con, session="regular")
            overnight = load_us_overnight(con)
        finally:
            con.close()

    rows: List[Dict[str, Any]] = []
    miss_hooks: List[Dict[str, Any]] = []
    for case in cases:
        track = str(case.get("track") or "").strip()
        if track == "level_touch":
            row = grade_level_touch_case(case, twii)
        elif track == "segment_bias":
            row = grade_segment_bias_case(case)
        elif track == "chain_trio":
            row = grade_chain_trio_case(
                case, overnight_map=overnight, tx_regular=tx_reg, twii=twii
            )
        else:
            row = {
                "case_id": case.get("case_id"),
                "track": track or "unknown",
                "verdict": VERDICT_OPEN,
                "ok": None,
                "note_zh": "未知 track；框架保留",
                "variant": VARIANT_CURRENT,
            }
        rows.append(row)
        if isinstance(row.get("miss_analysis"), dict):
            miss_hooks.append(row["miss_analysis"])

    by_track: Dict[str, List[Dict[str, Any]]] = {}
    for r in rows:
        by_track.setdefault(str(r.get("track") or "unknown"), []).append(r)

    track_scores = {t: score_rows(rs) for t, rs in by_track.items()}
    overall = score_rows(rows)
    # 分軌勝率不准混：整體只作目錄，替換閘看各軌自己
    replace_any = False
    next_collecting = {
        "variant": VARIANT_NEXT,
        "rule_zh": (
            "chain：SOX≤-1.5 才准弱鏈對；level：剔除 touch 灌水；"
            "segment：preferred 失效改看同日成立路徑"
        ),
        "status": "collecting",
        "gate_n20": False,
        "replace": False,
        "note_zh": "現況樣本仍少；繼續靜默收集。勝率不准混海選／黃金買點。",
    }

    summary: Dict[str, Any] = {
        "written_at": _now(),
        "tz": "Asia/Taipei",
        "track": TRACK,
        "purpose_zh": "BK-VERIFY：三層鏈／他點過的位／試標段 → 對／偏／未完；可重跑自測",
        "phone_sync": PHONE_SYNC,
        "buy_signal": False,
        "not_buy_signal": True,
        "mix_forbidden_zh": "勝率不准混進海選／黃金買點；本軌不上話筒買訊",
        "current_variant": VARIANT_CURRENT,
        "next_variant": next_collecting,
        "db": {
            "path": str(db_path),
            "ok": db_ok,
            "twii_n": len(twii),
            "twii_from": twii[0]["date"] if twii else None,
            "twii_to": twii[-1]["date"] if twii else None,
            "tx_regular_n": len(tx_reg),
            "us_overnight_n": len(overnight),
        },
        "cases_n": len(cases),
        "rows": rows,
        "tracks": track_scores,
        "overall_catalog_only": overall,
        "miss_analysis": miss_hooks,
        "deps_zh": [
            "BK-CHAIN《三層觀測操作手》齊了可加更多 chain 考題",
            "BK-WAVE 段號證據桶齊了可擴 segment 母體",
            "本機／Render 官方柱需完整 OHLC；缺柱＝未完",
            "wave_forward_infer／wave_eod_verify 可當 segment 樣例來源",
        ],
        "daily_review_zh": (
            "開市日盤後：python scripts/observe_verify_suite.py --write；"
            "核對 verify_latest.json；有 miss 填 rule_patch 並續收下一版鍵"
        ),
        "gate": {
            "min_n": MIN_N,
            "replace": replace_any,
            "phone_sync": PHONE_SYNC,
            "note_zh": "n≥20 獨立交易日且贏現況才換；現況框架階段 replace=false",
        },
    }

    if write:
        out_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(TAIPEI).strftime("%Y%m%d")
        blob = json.dumps(summary, ensure_ascii=False, indent=2) + "\n"
        (out_dir / "verify_latest.json").write_text(blob, encoding="utf-8")
        (out_dir / f"verify_{stamp}.json").write_text(blob, encoding="utf-8")
        md = [
            "# BK-VERIFY 自測覆核",
            "",
            f"寫入：`{summary['written_at']}`（Asia/Taipei）。",
            f"現況鍵 `{VARIANT_CURRENT}` → 下一版候選 `{VARIANT_NEXT}`（§13 再生）。",
            "",
            f"- 考題數：{len(cases)}；分軌：{', '.join(sorted(by_track)) or '（空）'}",
            f"- 總覽 n_decided={overall.get('n_decided')} hit_rate={overall.get('hit_rate')}（僅目錄，不准混軌）",
            f"- miss 鉤子：{len(miss_hooks)}",
            f"- phone_sync={PHONE_SYNC}；不是買訊；不准混海選／黃金買點",
            "",
            "## 怎麼跑",
            "",
            "```bash",
            "python scripts/observe_verify_suite.py --write",
            "pytest -q tests/test_observe_verify.py",
            "```",
            "",
            "## 每日覆核",
            "",
            "- 開市日盤後跑 suite 落 `verify_latest.json`／`verify_YYYYMMDD.json`",
            "- 有偏 → 讀 `miss_analysis` → 改下一版候選規則繼續收",
            "- 空名單不算；缺官方完整柱＝未完",
            "",
        ]
        (out_dir / "verify_latest.md").write_text("\n".join(md) + "\n", encoding="utf-8")
        # 錯案單獨落檔方便除錯
        if miss_hooks:
            (out_dir / "verify_miss_hooks_latest.json").write_text(
                json.dumps(miss_hooks, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
    return summary


__all__ = [
    "VARIANT_CURRENT",
    "VARIANT_NEXT",
    "build_miss_analysis",
    "grade_chain_trio_case",
    "grade_level_touch_case",
    "grade_segment_bias_case",
    "run_suite",
    "score_level_vs_fwd",
    "score_rows",
]
