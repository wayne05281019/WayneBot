#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""位階對質（靜默）｜他點過的位 → 官方柱碰到沒 → 對／偏／未完。

分軌（勝率不准混）：
- track_degree_level：degree_hits 大盤標籤文抽出指數點位，對加權後窗官方柱
- track_levelish_explicit：現況位階口語＋文內明確支撐／壓力／必破語（加樣本）
- track_biaoke_hybrid：degree_turns 有明確點位則走位階柱對質，否則退回方向窗（wave8 飆大軌 vnext）

硬邊界：
- Asia/Taipei；只用已收官方柱；盤中未收不當收
- 不准發明 5／9；不准套個股；不是買訊；phone_sync=blocked
- 錯窗修正：對質窗＝發文日**之後** FWD 根，不准把當日柱當「已驗證」灌水
- §13：現況鍵寫死；下一鍵同件再生；未過閘不准改話筒／WAVE_NEURONS_MATCH
"""
from __future__ import annotations

import gzip
import json
import os
import re
import sqlite3
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

MARKET_DB = Path(os.environ.get("WAYNE_DB_PATH") or (ROOT / "data" / "wayne_market.db"))
OUT_DIR = ROOT / "docs" / "expert_notes" / "飆客" / "decade_lab"
TAIPEI = ZoneInfo("Asia/Taipei")

MIN_N = 20
MIN_INDEX_LV = 15000.0
FWD_N = 5
TOL_PCT = 0.005

# 現況鍵／下一鍵（§13 同件再生）
VARIANT_CURRENT = "level_bar_fwd5_role_infer"
VARIANT_NEXT = "level_bar_vnext_explicit_hybrid"

_SUP = re.compile(r"支撐|不破|守住|回測|測底|有守|築底|低不破")
_BRK = re.compile(r"必破|會破|跌破|破了|下殺|南下|跌破")
_PRS = re.compile(r"壓力|高點|過前|要過|突破|前波高|頸線")
_STOCK_LEAK = re.compile(r"台通|頎邦|聯發科|鴻海|個股|兆赫|健鼎")


def _now() -> str:
    return datetime.now(TAIPEI).strftime("%Y-%m-%dT%H:%M:%S")


def _ymd(raw: Any) -> str:
    t = str(raw or "").replace("-", "")[:8]
    return t if len(t) == 8 and t.isdigit() else ""


def _load_twii(conn: sqlite3.Connection) -> List[Dict[str, float]]:
    rows = conn.execute(
        """
        SELECT REPLACE(CAST(date AS TEXT),'-',''), open, high, low, close
        FROM index_daily WHERE symbol='TWII' ORDER BY 1
        """
    ).fetchall()
    out: List[Dict[str, float]] = []
    for d, o, h, l, c in rows:
        day = _ymd(d)
        try:
            cc = float(c)
        except (TypeError, ValueError):
            continue
        if not day or cc <= 0:
            continue
        try:
            hh = float(h) if h not in (None, "") else cc
            ll = float(l) if l not in (None, "") else cc
            oo = float(o) if o not in (None, "") else cc
        except (TypeError, ValueError):
            hh = ll = oo = cc
        out.append({"date": day, "open": oo, "high": hh, "low": ll, "close": cc})
    return out


def _explicit_role(ctx: str) -> Optional[str]:
    blob = str(ctx or "")
    if _BRK.search(blob):
        return "break"
    if _PRS.search(blob):
        return "pressure"
    if _SUP.search(blob):
        return "support"
    return None


def _infer_role(ctx: str, direc: str) -> str:
    exp = _explicit_role(ctx)
    if exp:
        return exp
    d = str(direc or "").lower()
    if d in {"retest", "down_done"}:
        return "support"
    if d == "down":
        return "break"
    if d == "up":
        return "pressure"
    return "touch"


def _stock_leak(ctx: str) -> bool:
    blob = str(ctx or "")
    if not _STOCK_LEAK.search(blob):
        return False
    # 同句有大盤／加權／台指則仍留
    return not re.search(r"大盤|加權|台指|指數", blob)


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
    """錯窗鎖死：預設只用發文日之後的官方柱（include_day0=False）。"""
    if i0 < 0 or i0 >= len(bars) or level <= 0:
        return "缺柱", None
    start = i0 if include_day0 else i0 + 1
    end = i0 + int(fwd)
    if end >= len(bars) or start > end:
        return "未完", None
    win = list(bars[start : end + 1])
    if not win:
        return "未完", None
    mx = max(float(b["high"]) for b in win)
    mn = min(float(b["low"]) for b in win)
    last = float(win[-1]["close"])
    tol = float(level) * float(tol_pct)
    touched = any(
        float(b["low"]) - tol <= float(level) <= float(b["high"]) + tol for b in win
    )
    role_l = str(role or "touch")
    if role_l == "support":
        if mn >= float(level) - tol:
            return "對", True
        if mn < float(level) - 3 * tol and last < float(level) - tol:
            return "偏", False
        if touched and last >= float(level) - tol:
            return "對", True
        return "偏", False
    if role_l == "break":
        if mn <= float(level) + tol:
            return "對", True
        return "偏", False
    if role_l == "pressure":
        if mx >= float(level) - tol:
            return "對", True
        if last < float(level) - 2 * tol and mx < float(level) - tol:
            return "偏", False
        return "未完", None
    # touch：只問有沒有碰到
    if touched:
        return "對", True
    return "偏", False


def _extract_levels(text: str) -> List[Dict[str, Any]]:
    from biaoke_walk import extract_index_levels

    out: List[Dict[str, Any]] = []
    for x in extract_index_levels(text or ""):
        try:
            lv = float(x.get("level"))
        except (TypeError, ValueError):
            continue
        if lv < MIN_INDEX_LV:
            continue
        ctx = str(x.get("ctx") or "")
        if _stock_leak(ctx):
            continue
        out.append({"level": lv, "role_hint": x.get("role") or "", "ctx": ctx})
    return out


def _corpus_by_id(db_path: Path) -> Dict[str, Dict[str, Any]]:
    try:
        from biaoke_desk import load_corpus

        posts = list((load_corpus(str(db_path)) or {}).get("posts") or [])
    except Exception:
        posts = []
    out: Dict[str, Dict[str, Any]] = {}
    for p in posts:
        pid = str(p.get("id") or "").strip()
        if pid:
            out[pid] = p
    return out


def _spoken(raw: str) -> str:
    try:
        from biaoke_ingest import spoken_text

        return spoken_text(raw or "")
    except Exception:
        return re.sub(r"\s+", " ", str(raw or "")).strip()


def collect_degree_level_rows(
    db_path: Path,
    bars: Sequence[Dict[str, float]],
    *,
    explicit_only: bool = False,
    fwd: int = FWD_N,
    tol_pct: float = TOL_PCT,
    include_day0: bool = False,
) -> List[Dict[str, Any]]:
    from biaoke_wave import degree_hits

    day_i = {b["date"]: i for i, b in enumerate(bars)}
    by_id = _corpus_by_id(db_path)
    rows: List[Dict[str, Any]] = []
    seen = set()
    for h in degree_hits(str(db_path)):
        aid = str(h.get("aid") or "").strip()
        full = ""
        if aid and aid in by_id:
            full = _spoken(str((by_id[aid] or {}).get("text") or ""))
        if not full:
            full = str(h.get("quote") or "")
        day = _ymd(h.get("date"))
        if not day or day not in day_i:
            continue
        direc = str(h.get("direc") or "")
        for x in _extract_levels(full):
            role = (
                _explicit_role(x["ctx"])
                if explicit_only
                else _infer_role(x["ctx"], direc)
            )
            if explicit_only and not role:
                continue
            if not role:
                role = "touch"
            key = (day, round(float(x["level"]), 1), str(h.get("tag") or ""), role)
            if key in seen:
                continue
            seen.add(key)
            verd, ok = score_level_vs_fwd(
                float(x["level"]),
                role,
                bars,
                day_i[day],
                fwd=fwd,
                tol_pct=tol_pct,
                include_day0=include_day0,
            )
            rows.append(
                {
                    "track": "degree_level",
                    "as_of": day,
                    "tag": h.get("tag"),
                    "direc": direc,
                    "level": float(x["level"]),
                    "role": role,
                    "verdict": verd,
                    "ok": ok,
                    "aid": aid,
                    "ctx": (x.get("ctx") or "")[:90],
                    "fwd": fwd,
                    "tol_pct": tol_pct,
                    "include_day0": bool(include_day0),
                    "variant": VARIANT_CURRENT
                    if not explicit_only
                    else "level_bar_explicit_only",
                }
            )
    return rows


def collect_levelish_explicit_rows(
    db_path: Path,
    bars: Sequence[Dict[str, float]],
    *,
    fwd: int = FWD_N,
    tol_pct: float = TOL_PCT,
) -> List[Dict[str, Any]]:
    """加樣本：現況位階口語＋明確支撐／壓力／必破（不准 touch 灌水）。"""
    from biaoke_level_learn import looks_like_level_now

    day_i = {b["date"]: i for i, b in enumerate(bars)}
    by_id = _corpus_by_id(db_path)
    rows: List[Dict[str, Any]] = []
    seen = set()
    for pid, p in by_id.items():
        text = _spoken(str(p.get("text") or ""))
        if not looks_like_level_now(text):
            continue
        day = _ymd(p.get("date"))
        if not day or day not in day_i:
            continue
        for x in _extract_levels(text):
            role = _explicit_role(x["ctx"])
            if not role:
                continue
            key = (day, round(float(x["level"]), 1), pid, role)
            if key in seen:
                continue
            seen.add(key)
            verd, ok = score_level_vs_fwd(
                float(x["level"]),
                role,
                bars,
                day_i[day],
                fwd=fwd,
                tol_pct=tol_pct,
                include_day0=False,
            )
            rows.append(
                {
                    "track": "levelish_explicit",
                    "as_of": day,
                    "post_id": pid,
                    "level": float(x["level"]),
                    "role": role,
                    "verdict": verd,
                    "ok": ok,
                    "ctx": (x.get("ctx") or "")[:90],
                    "fwd": fwd,
                    "tol_pct": tol_pct,
                    "include_day0": False,
                    "variant": "levelish_explicit_fwd5",
                }
            )
    return rows


def collect_biaoke_hybrid_rows(
    db_path: Path,
    bars: Sequence[Dict[str, float]],
    *,
    fwd: int = FWD_N,
    tol_pct: float = TOL_PCT,
) -> List[Dict[str, Any]]:
    """飆大軌 vnext：有明確點位→柱對質；否則方向窗（不准混進 textbook 勝率）。"""
    from biaoke_wave import degree_turns
    from scripts.decade_lab_wave8_dual import _biaoke_bias, _fwd_bias, _judge_dir

    day_i = {b["date"]: i for i, b in enumerate(bars)}
    by_id = _corpus_by_id(db_path)
    rows: List[Dict[str, Any]] = []
    for t in degree_turns(str(db_path)):
        day = _ymd(t.get("date"))
        aid = str(t.get("aid") or "").strip()
        tag = str(t.get("tag") or "")
        direc = str(t.get("direc") or "")
        if not day or day not in day_i:
            rows.append(
                {
                    "track": "biaoke_hybrid",
                    "as_of": day,
                    "tag": tag,
                    "direc": direc,
                    "verdict": "缺柱",
                    "ok": None,
                    "path": "missing_bar",
                    "variant": VARIANT_NEXT,
                }
            )
            continue
        i = day_i[day]
        full = ""
        if aid and aid in by_id:
            full = _spoken(str((by_id[aid] or {}).get("text") or ""))
        if not full:
            full = str(t.get("quote") or "")
        level_oks: List[bool] = []
        used_levels: List[float] = []
        for x in _extract_levels(full):
            role = _explicit_role(x["ctx"])
            if not role:
                continue
            verd, ok = score_level_vs_fwd(
                float(x["level"]),
                role,
                bars,
                i,
                fwd=fwd,
                tol_pct=tol_pct,
                include_day0=False,
            )
            if ok is None:
                continue
            level_oks.append(bool(ok))
            used_levels.append(float(x["level"]))
        if level_oks:
            hit_n = sum(1 for o in level_oks if o)
            miss_n = len(level_oks) - hit_n
            verd = "對" if hit_n >= miss_n else "偏"
            rows.append(
                {
                    "track": "biaoke_hybrid",
                    "as_of": day,
                    "tag": tag,
                    "direc": direc,
                    "verdict": verd,
                    "ok": verd == "對",
                    "path": "level_bar",
                    "levels": used_levels[:6],
                    "variant": VARIANT_NEXT,
                }
            )
            continue
        bias = _biaoke_bias(direc, tag)
        actual = _fwd_bias(bars, i, fwd)
        verd = _judge_dir(bias, actual)
        ok = True if verd == "對" else (False if verd == "偏" else None)
        rows.append(
            {
                "track": "biaoke_hybrid",
                "as_of": day,
                "tag": tag,
                "direc": direc,
                "bias": bias,
                "actual": actual,
                "verdict": verd,
                "ok": ok,
                "path": "direction_fallback",
                "variant": VARIANT_NEXT,
            }
        )
    return rows


def _score_rows(rows: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    decided = [r for r in rows if r.get("ok") is True or r.get("ok") is False]
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
        "gate_n20": n >= MIN_N,
        "n_days": len(days),
        "outcome_counts": dict(Counter(str(r.get("verdict") or "") for r in rows)),
        "role_counts": dict(
            Counter(str(r.get("role") or "") for r in rows if r.get("role"))
        ),
    }


def run(db_path: Path = MARKET_DB) -> Dict[str, Any]:
    conn = sqlite3.connect(str(db_path), timeout=60.0)
    try:
        bars = _load_twii(conn)
    finally:
        conn.close()
    if len(bars) < 40:
        return {"error": "twii_too_short", "n": len(bars)}

    # 現況：degree 點位＋角色推斷；錯窗＝forward-only
    cur_rows = collect_degree_level_rows(
        db_path, bars, explicit_only=False, fwd=FWD_N, tol_pct=TOL_PCT, include_day0=False
    )
    # 錯窗對照（不准採用）：含當日
    wrong_rows = collect_degree_level_rows(
        db_path, bars, explicit_only=False, fwd=FWD_N, tol_pct=TOL_PCT, include_day0=True
    )
    # 加樣本：levelish 明確語
    sample_rows = collect_levelish_explicit_rows(
        db_path, bars, fwd=FWD_N, tol_pct=TOL_PCT
    )
    # 下一鍵：hybrid（明確點位優先，否則方向）
    next_rows = collect_biaoke_hybrid_rows(
        db_path, bars, fwd=FWD_N, tol_pct=TOL_PCT
    )
    # 下一鍵旁枝：只留明確角色＋略緊 tol（另軌收集）
    next_explicit = collect_degree_level_rows(
        db_path,
        bars,
        explicit_only=True,
        fwd=FWD_N,
        tol_pct=0.003,
        include_day0=False,
    )

    s_cur = _score_rows(cur_rows)
    s_wrong = _score_rows(wrong_rows)
    s_sample = _score_rows(sample_rows)
    s_next = _score_rows(next_rows)
    s_next_exp = _score_rows(next_explicit)

    # 替換閘：下一鍵須 n≥20 且贏現況；本軌 phone 永遠 blocked
    replace = bool(
        s_next.get("gate_n20")
        and s_cur.get("gate_n20")
        and (s_next.get("hit_rate") or 0) > (s_cur.get("hit_rate") or 0) + 1e-12
    )

    inventory = {
        "encodings_zh": [
            "biaoke_level_snaps＋_score_against_next＝口語對口語（不是官方柱）",
            "biaoke_open_day_paints＋_score_levels_vs_bar＝隔日 TX 柱對活畫關鍵位",
            "wave8 textbook_8cycle＝實驗室八循環幾何（已採用）",
            "wave8 biaoke_degree＝標籤→方向窗（~47%，不採用）",
            "biaoke_micro_fractal＝細微波關鍵詞→後5日（弱）",
            "teach kit＝遠／近／超近加權教具渲圖，對質另軌",
            f"本檔現況 {VARIANT_CURRENT}＝他點過的指數位→加權後窗碰到沒",
        ],
        "wrong_window_fix_zh": (
            "對質窗改為發文日之後 FWD 根；include_day0 僅作對照不准採用"
        ),
    }

    summary: Dict[str, Any] = {
        "written_at": _now(),
        "tz": "Asia/Taipei",
        "purpose_zh": "收緊位階對質：他點過的位→官方柱碰到沒→對／偏／未完",
        "twii_n": len(bars),
        "twii_from": bars[0]["date"],
        "twii_to": bars[-1]["date"],
        "fwd_n": FWD_N,
        "tol_pct": TOL_PCT,
        "min_index_level": MIN_INDEX_LV,
        "inventory": inventory,
        "tracks": {
            VARIANT_CURRENT: {**s_cur, "pot": "他說／飆預測", "window": "fwd_only"},
            "wrong_window_incl_day0": {
                **s_wrong,
                "pot": "對照／不准採用",
                "window": "incl_day0",
            },
            "levelish_explicit_fwd5": {
                **s_sample,
                "pot": "加樣本",
                "window": "fwd_only",
            },
            VARIANT_NEXT: {
                **s_next,
                "pot": "他說／飆預測・下一鍵",
                "window": "level_or_direction",
            },
            "level_bar_explicit_tol3": {
                **s_next_exp,
                "pot": "下一鍵旁枝",
                "window": "fwd_only",
            },
        },
        "current_variant": VARIANT_CURRENT,
        "next_variant": {
            "variant": VARIANT_NEXT,
            "rule_zh": "degree_turns：明確點位多數決柱對質，否則方向窗 fallback",
            "n_decided": s_next.get("n_decided"),
            "hit_rate": s_next.get("hit_rate"),
            "vs_current": {
                "current_hit_rate": s_cur.get("hit_rate"),
                "edge": (
                    None
                    if s_next.get("hit_rate") is None or s_cur.get("hit_rate") is None
                    else float(s_next["hit_rate"]) - float(s_cur["hit_rate"])
                ),
            },
            "gate_n20": s_next.get("gate_n20"),
            "replace": replace,
            "phone_sync": "blocked",
            "also_collecting": "level_bar_explicit_tol3／levelish_explicit_fwd5",
        },
        "adopt": {
            "pick": VARIANT_NEXT if replace else VARIANT_CURRENT,
            "reason": (
                f"下一鍵 hit {s_next.get('hit_rate')} > 現況 {s_cur.get('hit_rate')}"
                if replace
                else "下一鍵未贏現況或 n 不足；繼續靜默收集"
            ),
        },
        "WAVE_NEURONS_MATCH": False,
        "wave_neurons_gap_zh": [
            "飆大位階方向軌仍弱於教科書八循環（wave8 adopt=textbook）",
            "細微波／形態命中仍弱",
            "位→柱軌雖能量化，仍未到「神經元真的跟他一樣」的人工鎖",
            "phone 未過閘；不准發明 5／9、不准上話筒",
        ],
        "not_buy_signal": True,
        "phone_sync": "blocked",
        "note_zh": (
            "只認他點過的大盤位＋官方柱。空名單不算。"
            "WAVE_NEURONS_MATCH 仍 False。"
        ),
    }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(TAIPEI).strftime("%Y%m%d")
    latest = OUT_DIR / "biaoke_level_bar_hit_latest.json"
    stamped = OUT_DIR / f"biaoke_level_bar_hit_{stamp}.json"
    blob = json.dumps(summary, ensure_ascii=False, indent=2) + "\n"
    latest.write_text(blob, encoding="utf-8")
    stamped.write_text(blob, encoding="utf-8")

    with gzip.open(OUT_DIR / "biaoke_level_bar_hit_rows.jsonl.gz", "wt", encoding="utf-8") as f:
        for r in cur_rows + sample_rows + next_rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    md = [
        "# 位階對質｜他點過的位 → 官方柱",
        "",
        f"寫入：`{summary['written_at']}`（Asia/Taipei）。",
        f"TWII {summary['twii_from']}→{summary['twii_to']} n={summary['twii_n']}；FWD={FWD_N}；tol={TOL_PCT}。",
        "",
        f"- 現況 `{VARIANT_CURRENT}`：n_decided={s_cur.get('n_decided')} hit_rate={s_cur.get('hit_rate')}",
        f"- 下一鍵 `{VARIANT_NEXT}`：n_decided={s_next.get('n_decided')} hit_rate={s_next.get('hit_rate')} replace={replace}",
        f"- 加樣本 levelish_explicit：n_decided={s_sample.get('n_decided')} hit_rate={s_sample.get('hit_rate')}",
        f"- 錯窗對照 incl_day0：hit_rate={s_wrong.get('hit_rate')}（不准採用）",
        "",
        "不是買訊。不上話筒。WAVE_NEURONS_MATCH=false。",
        "",
    ]
    (OUT_DIR / "biaoke_level_bar_hit_latest.md").write_text(
        "\n".join(md) + "\n", encoding="utf-8"
    )
    return summary


def main() -> int:
    out = run()
    print(json.dumps(out, ensure_ascii=False, indent=2)[:8000])
    return 0 if not out.get("error") else 2


if __name__ == "__main__":
    raise SystemExit(main())
