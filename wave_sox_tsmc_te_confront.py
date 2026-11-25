# -*- coding: utf-8 -*-
"""費半／台積／加權日盤／電子夜盤 價位對應＋波浪關係（靜默）。

對齊規則（Asia/Taipei）：
- 費半 SOX／台積 ADR(TSM)＝美股已收柱；對「下一根」台股開市日。
- 2330／TWII＝台股日盤官方已收。
- TE night＝電子期夜盤（futures_daily symbol=TE session=night）。
- TX night 僅對照，不當電子鏈主軌。

硬邊界：未收不當收；phone_sync=blocked；不是買訊；
不准發明未口述價／個股浪號；WAVE_NEURONS_MATCH=false；
勝率不准混海選／黃金買點；§13 未過閘不換現況。
"""
from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
LAB = ROOT / "docs" / "expert_notes" / "飆客" / "decade_lab"
OUT_JSON = LAB / "wave_sox_tsmc_te_confront_latest.json"
OUT_MD = LAB / "wave_sox_tsmc_te_confront_latest.md"
TAIPEI = ZoneInfo("Asia/Taipei")

TRACK = "wave_sox_tsmc_te"
VARIANT = "cross_v2_2023_mine"
PHONE_SYNC = "blocked"
PHONE_WARNING = "試標・推論／非他原文・非買訊・對質未過閘"
MIN_N = 20
SINCE_DEFAULT = "20230101"

UP = 0.6
DOWN = -0.6
HOLD = -0.25


def _now() -> str:
    return datetime.now(TAIPEI).strftime("%Y-%m-%dT%H:%M:%S%z")


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


def _load_index(
    conn: sqlite3.Connection, symbol: str
) -> Dict[str, Dict[str, float]]:
    rows = conn.execute(
        """
        SELECT REPLACE(CAST(date AS TEXT),'-',''), open, high, low, close
        FROM index_daily WHERE symbol=? ORDER BY 1
        """,
        (symbol,),
    ).fetchall()
    out: Dict[str, Dict[str, float]] = {}
    prev: Optional[float] = None
    for d, o, h, lo, c in rows:
        day = _ymd(d)
        cc = _f(c)
        if not day or not cc or cc <= 0:
            continue
        ret = None if prev is None else (cc / prev - 1.0) * 100.0
        out[day] = {
            "o": _f(o) or cc,
            "h": _f(h) or cc,
            "l": _f(lo) or cc,
            "c": cc,
            "ret": float(ret) if ret is not None else 0.0,
            "ret_ok": ret is not None,
        }
        prev = cc
    return out


def _load_stock(
    conn: sqlite3.Connection, sid: str
) -> Dict[str, Dict[str, float]]:
    rows = conn.execute(
        """
        SELECT REPLACE(CAST(date AS TEXT),'-',''), open, high, low, close
        FROM daily_quotes WHERE stock_id=? ORDER BY 1
        """,
        (sid,),
    ).fetchall()
    out: Dict[str, Dict[str, float]] = {}
    prev: Optional[float] = None
    for d, o, h, lo, c in rows:
        day = _ymd(d)
        cc = _f(c)
        if not day or not cc or cc <= 0:
            continue
        ret = None if prev is None else (cc / prev - 1.0) * 100.0
        out[day] = {
            "o": _f(o) or cc,
            "h": _f(h) or cc,
            "l": _f(lo) or cc,
            "c": cc,
            "ret": float(ret) if ret is not None else 0.0,
            "ret_ok": ret is not None,
        }
        prev = cc
    return out


def _load_fut(
    conn: sqlite3.Connection, symbol: str, session: str
) -> Dict[str, Dict[str, float]]:
    rows = conn.execute(
        """
        SELECT REPLACE(CAST(date AS TEXT),'-',''), open, high, low, close
        FROM futures_daily
        WHERE symbol=? AND session=?
        ORDER BY 1
        """,
        (symbol, session),
    ).fetchall()
    out: Dict[str, Dict[str, float]] = {}
    prev: Optional[float] = None
    for d, o, h, lo, c in rows:
        day = _ymd(d)
        cc = _f(c)
        if not day or not cc or cc <= 0:
            continue
        ret = None if prev is None else (cc / prev - 1.0) * 100.0
        out[day] = {
            "o": _f(o) or cc,
            "h": _f(h) or cc,
            "l": _f(lo) or cc,
            "c": cc,
            "ret": float(ret) if ret is not None else 0.0,
            "ret_ok": ret is not None,
        }
        prev = cc
    return out


def _prior_us_day(us_days: List[str], tw_day: str) -> Optional[str]:
    """美股已收 → 對下一開市台股日：取 < tw_day 的最近美股日。"""
    tw = _ymd(tw_day)
    cands = [d for d in us_days if d < tw]
    return cands[-1] if cands else None


def _side(ret: Optional[float]) -> str:
    if ret is None:
        return "na"
    if ret >= UP:
        return "up"
    if ret <= DOWN:
        return "down"
    if ret >= HOLD:
        return "hold"
    return "soft"


def scan_oral_cross(db_path: str, *, limit: int = 30) -> Dict[str, Any]:
    """他自己文：費半／台積／電子夜盤並提（材料庫）。"""
    path = str(db_path or "").strip()
    if not path or not Path(path).is_file():
        return {"ok": False, "rows": []}
    conn = sqlite3.connect(path, timeout=15.0)
    try:
        rows = conn.execute(
            """
            SELECT id, date, time, kind, text FROM biaoke_posts
            WHERE IFNULL(kind,'post') != 'bystander'
              AND IFNULL(text,'') != ''
              AND (
                text LIKE '%費半%' OR text LIKE '%SOX%' OR text LIKE '%台積%'
                OR text LIKE '%電子夜%' OR text LIKE '%電子期%' OR text LIKE '%2330%'
              )
            ORDER BY date DESC, time DESC
            LIMIT ?
            """,
            (int(limit),),
        ).fetchall()
    except sqlite3.Error:
        return {"ok": False, "rows": []}
    finally:
        conn.close()
    out = []
    for pid, day, hm, kind, text in rows:
        blob = str(text or "")
        flags = {
            "sox": bool(re.search(r"費半|SOX|費城半導體", blob)),
            "tsmc": bool(re.search(r"台積|2330", blob)),
            "te_night": bool(re.search(r"電子夜|電子期夜|電子期", blob)),
            "wave": bool(re.search(r"波浪|細微|3-3|第五|三段|五段", blob)),
        }
        if not (flags["sox"] or flags["tsmc"] or flags["te_night"]):
            continue
        out.append(
            {
                "post_id": str(pid or ""),
                "date": str(day or ""),
                "time": str(hm or ""),
                "kind": str(kind or "post"),
                "flags": flags,
                "snip_zh": re.sub(r"\s+", " ", blob).strip()[:160],
            }
        )
    return {
        "ok": True,
        "n": len(out),
        "note_zh": (
            "口述對照：費半先行／台積三段 vs 大盤五段／電子夜盤確認鏈；"
            "只收他自己講的。不准發明個股浪號上話筒。"
        ),
        "rows": out[:20],
        "buy_signal": False,
        "phone_sync": PHONE_SYNC,
    }


def run_suite(
    db_path: str = "",
    *,
    lookback_days: int = 0,
    since_ymd: str = SINCE_DEFAULT,
    run_mine: bool = True,
) -> Dict[str, Any]:
    path = str(db_path or "").strip()
    if not path:
        try:
            from config import get_db_path

            path = str(get_db_path() or "")
        except Exception:
            path = str(ROOT / "data" / "wayne_market.db")
    if not path or not Path(path).is_file():
        return {
            "ok": False,
            "reason": "no_db",
            "phone_sync": PHONE_SYNC,
            "buy_signal": False,
        }
    # 系統化挖礦（2023起逐日）— 主成果在 mine 模組
    mine_payload: Optional[Dict[str, Any]] = None
    if run_mine:
        try:
            import wave_cross_relation_mine as crm

            mine_payload = crm.run_suite(path, since_ymd=since_ymd or SINCE_DEFAULT)
            crm.write_outputs(mine_payload)
        except Exception as exc:  # noqa: BLE001 — 挖礦失敗不擋對照摘要
            mine_payload = {"ok": False, "error": str(exc)[:200]}

    conn = sqlite3.connect(path, timeout=30.0)
    try:
        twii = _load_index(conn, "TWII")
        sox = _load_index(conn, "SOX")
        tsm_adr = _load_index(conn, "TSM")
        tsmc = _load_stock(conn, "2330")
        te_n = _load_fut(conn, "TE", "night")
        te_r = _load_fut(conn, "TE", "regular")
        tx_n = _load_fut(conn, "TX", "night")
    finally:
        conn.close()

    since = (since_ymd or SINCE_DEFAULT).replace("-", "")[:8]
    tw_days = [d for d in sorted(twii.keys()) if d >= since]
    if lookback_days and len(tw_days) > lookback_days:
        tw_days = tw_days[-int(lookback_days) :]
    us_days = sorted(set(sox.keys()) | set(tsm_adr.keys()))

    rows: List[Dict[str, Any]] = []
    flag_counts: Dict[str, int] = {}
    for day in tw_days:
        tw = twii.get(day)
        if not tw or not tw.get("ret_ok"):
            continue
        u = _prior_us_day(us_days, day)
        sx = sox.get(u) if u else None
        adr = tsm_adr.get(u) if u else None
        t2330 = tsmc.get(day)
        ten = te_n.get(day) or (te_n.get(u) if u else None)
        ter = te_r.get(day)
        txn = tx_n.get(day) or (tx_n.get(u) if u else None)

        sx_ret = float(sx["ret"]) if sx and sx.get("ret_ok") else None
        adr_ret = float(adr["ret"]) if adr and adr.get("ret_ok") else None
        t_ret = float(t2330["ret"]) if t2330 and t2330.get("ret_ok") else None
        tw_ret = float(tw["ret"])
        te_n_ret = float(ten["ret"]) if ten and ten.get("ret_ok") else None
        te_r_ret = float(ter["ret"]) if ter and ter.get("ret_ok") else None

        flags = {
            "sox_down_te_night_hold": bool(
                sx_ret is not None
                and sx_ret <= DOWN
                and te_n_ret is not None
                and te_n_ret >= HOLD
            ),
            "sox_down_tsmc_hold": bool(
                sx_ret is not None
                and sx_ret <= DOWN
                and t_ret is not None
                and t_ret >= HOLD
            ),
            "sox_up_tsmc_up_tw_up": bool(
                sx_ret is not None
                and sx_ret >= UP
                and t_ret is not None
                and t_ret >= UP
                and tw_ret >= UP
            ),
            "adr_down_2330_hold": bool(
                adr_ret is not None
                and adr_ret <= DOWN
                and t_ret is not None
                and t_ret >= HOLD
            ),
            "te_night_down_day_te_hold": bool(
                te_n_ret is not None
                and te_n_ret <= DOWN
                and te_r_ret is not None
                and te_r_ret >= HOLD
            ),
            "te_night_leads_tw": bool(
                te_n_ret is not None
                and t_ret is not None
                and abs(te_n_ret - tw_ret) >= 0.4
                and ((te_n_ret > 0 and tw_ret > 0) or (te_n_ret < 0 and tw_ret < 0))
            ),
            "tsmc_leads_tw": bool(
                t_ret is not None and abs(t_ret - tw_ret) >= 0.6
            ),
        }
        for k, on in flags.items():
            if on:
                flag_counts[k] = flag_counts.get(k, 0) + 1

        rows.append(
            {
                "tw_day": day,
                "us_day": u,
                "sides": {
                    "sox": _side(sx_ret),
                    "tsm_adr": _side(adr_ret),
                    "2330": _side(t_ret),
                    "twii": _side(tw_ret),
                    "te_night": _side(te_n_ret),
                    "te_day": _side(te_r_ret),
                    "tx_night": _side(
                        float(txn["ret"]) if txn and txn.get("ret_ok") else None
                    ),
                },
                "rets": {
                    "sox": sx_ret,
                    "tsm_adr": adr_ret,
                    "2330": t_ret,
                    "twii": tw_ret,
                    "te_night": te_n_ret,
                    "te_day": te_r_ret,
                },
                "flags": {k: bool(v) for k, v in flags.items() if v},
                "prices": {
                    "sox_c": (sx or {}).get("c"),
                    "2330_c": (t2330 or {}).get("c"),
                    "twii_c": tw.get("c"),
                    "te_night_c": (ten or {}).get("c"),
                },
            }
        )

    # 近窗摘要（最近有齊 SOX＋2330＋TE night 的日子）
    recent = [
        r
        for r in rows
        if r["rets"].get("sox") is not None
        and r["rets"].get("2330") is not None
        and r["rets"].get("te_night") is not None
    ][-12:]

    oral = scan_oral_cross(path)
    n_aligned = len(
        [
            r
            for r in rows
            if r["rets"].get("sox") is not None and r["rets"].get("2330") is not None
        ]
    )
    dig = ((mine_payload or {}).get("mine") or {}).get("dig_worth") or []
    hints = (mine_payload or {}).get("wave_strengthen_hints") or []
    payload = {
        "written_at": _now(),
        "tz": "Asia/Taipei",
        "track": TRACK,
        "variant": VARIANT,
        "purpose_zh": (
            "費半↔台積↔加權日盤↔電子夜盤 2023起對應＋系統化挖礦（靜默；非買訊）"
        ),
        "phone_sync": PHONE_SYNC,
        "buy_signal": False,
        "not_buy_signal": True,
        "phone_warning_fixed": PHONE_WARNING,
        "WAVE_NEURONS_MATCH": False,
        "since": since,
        "align_rule_zh": (
            "美股 SOX／TSM 已收 → 對下一開市台股日；"
            "2330／TWII＝當日日盤；TE night＝電子期夜盤（可跨日曆標註）。"
        ),
        "wave_relation_zh": [
            "口述常見：費半先行／確認；台積多當三段對照、大盤多當五段／細微波（黃／飆大材料）。",
            "電子夜盤＝半導體鏈台股端夜間確認，不是另發明浪號。",
            "現在 WAVE_NEURONS_MATCH=false：不准把對照寫成個股①～⑤上話筒。",
            "dig_worth 候選進加深下一軌；未過閘不准改 preferred／話筒。",
        ],
        "gate": {
            "min_n": MIN_N,
            "n_tw_days": len(rows),
            "n_sox_2330_aligned": n_aligned,
            "n_te_night_days": sum(
                1 for r in rows if r["rets"].get("te_night") is not None
            ),
            "n_dig_worth": len(dig),
            "gate_n20": n_aligned >= MIN_N,
            "replace": False,
        },
        "flag_counts": flag_counts,
        "recent_aligned": recent,
        "oral_cross": oral,
        "mine_ref": {
            "ok": (mine_payload or {}).get("ok", True) if mine_payload else False,
            "variant": (mine_payload or {}).get("variant"),
            "n_dig_worth": len(dig),
            "dig_ids": [d.get("id") for d in dig[:12]],
            "hints": hints[:6],
        },
        "coverage": {
            "sox_n": len(sox),
            "tsm_adr_n": len(tsm_adr),
            "2330_n": len(tsmc),
            "twii_n": len(twii),
            "te_night_n": len(te_n),
            "te_day_n": len(te_r),
            "tx_night_n": len(tx_n),
            "since": since,
        },
        "forbid_zh": [
            "不准當買訊",
            "不准發明未口述價／個股浪號",
            "不准未收當收",
            "phone_sync=blocked",
            "勝率不准混海選／黃金買點",
        ],
    }
    return payload


def write_outputs(payload: Dict[str, Any]) -> Tuple[Path, Path]:
    LAB.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    g = payload.get("gate") or {}
    lines = [
        "# 費半／台積／日盤／電子夜盤 靜默對質",
        "",
        f"寫入：`{payload.get('written_at')}`（Asia/Taipei）。",
        f"軌：`{TRACK}`／`{VARIANT}`｜phone_sync=blocked｜非買訊",
        "",
        f"- n_aligned={g.get('n_sox_2330_aligned')} te_night_days={g.get('n_te_night_days')} "
        f"gate_n20={g.get('gate_n20')} replace={g.get('replace')}",
        f"- flag_counts={payload.get('flag_counts')}",
        f"- {payload.get('align_rule_zh')}",
        "",
        "## 波浪關係（材料）",
        "",
    ]
    for z in payload.get("wave_relation_zh") or []:
        lines.append(f"- {z}")
    lines += ["", "## 近窗對齊", ""]
    for r in payload.get("recent_aligned") or []:
        sides = r.get("sides") or {}
        lines.append(
            f"- `{r.get('tw_day')}` us=`{r.get('us_day')}` "
            f"SOX={sides.get('sox')} ADR={sides.get('tsm_adr')} "
            f"2330={sides.get('2330')} TWII={sides.get('twii')} "
            f"TEnight={sides.get('te_night')} flags={list((r.get('flags') or {}).keys())}"
        )
    oral = payload.get("oral_cross") or {}
    lines += [
        "",
        f"## 口述交叉 n={oral.get('n')}",
        "",
        f"- {oral.get('note_zh')}",
        "",
        "WAVE_NEURONS_MATCH=false。不上話筒定案。",
        "",
    ]
    OUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return OUT_JSON, OUT_MD


def main() -> int:
    payload = run_suite()
    jp, mp = write_outputs(payload)
    g = payload.get("gate") or {}
    print(
        "GATE",
        f"sox_tsmc_te n_aligned={g.get('n_sox_2330_aligned')} "
        f"te_night={g.get('n_te_night_days')} gate_n20={g.get('gate_n20')} "
        f"replace=0 phone_sync=blocked buy_signal=0",
    )
    print("WROTE", jp.name, mp.name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
