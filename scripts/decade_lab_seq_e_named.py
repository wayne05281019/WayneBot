#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""十年回測旁路｜序E：點名檔近窗對質第一批（個股不數浪）。

硬邊界：只寫 decade_lab；讀 wayne_market；三鍋分標；不是買訊；
不准寫回黃金買點／海選／洞燭；不准發明個股 5／9。
融資／大戶／某金融商品／期現無官方 → 標缺跳過。
"""
from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

MARKET_DB = Path(ROOT / "data" / "wayne_market.db")
OUT_DIR = ROOT / "docs" / "expert_notes" / "飆客" / "decade_lab"
TP = ZoneInfo("Asia/Taipei")

# 第一小波：knowhow 已有對照結果的點名檔（台北日）
SEED_NAMED: List[Dict[str, Any]] = [
    {
        "event_date": "2025-04-25",
        "stock_id": "2382",
        "name": "廣達",
        "said": "老 AI 伺服器供應鏈最整齊",
        "group": "老AI伺服器",
        "horizon_days": 40,
        "teacher_verdict_hint": "40日+23%級；方向對",
        "source_ref": "knowhow.md §族群／對照",
    },
    {
        "event_date": "2025-04-25",
        "stock_id": "2383",
        "name": "台光電",
        "said": "老 AI 伺服器供應鏈最整齊",
        "group": "老AI伺服器",
        "horizon_days": 40,
        "teacher_verdict_hint": "40日+52%級；方向對",
        "source_ref": "knowhow.md §旋轉／對照",
    },
    {
        "event_date": "2025-08-06",
        "stock_id": "4916",
        "name": "事欣科",
        "said": "無人機四檔半山腰隔日沖（不是3679）",
        "group": "無人機",
        "horizon_days": 20,
        "half_mountain": True,
        "teacher_verdict_hint": "半山腰＝操作方式；20日+8.2%走平≠四檔都平",
        "source_ref": "knowhow.md §旋轉",
    },
    {
        "event_date": "2025-08-06",
        "stock_id": "5371",
        "name": "中光電",
        "said": "無人機四檔半山腰隔日沖",
        "group": "無人機",
        "horizon_days": 20,
        "half_mountain": True,
        "teacher_verdict_hint": "20日+41.5%",
        "source_ref": "knowhow.md §旋轉",
    },
    {
        "event_date": "2025-08-06",
        "stock_id": "8033",
        "name": "雷虎",
        "said": "無人機四檔半山腰隔日沖",
        "group": "無人機",
        "horizon_days": 20,
        "half_mountain": True,
        "teacher_verdict_hint": "20日+56.8%",
        "source_ref": "knowhow.md §旋轉",
    },
    {
        "event_date": "2025-10-30",
        "stock_id": "8021",
        "name": "尖點",
        "said": "尖點漲停＝零組件整理完成",
        "group": "零組件／散熱對齊",
        "horizon_days": 20,
        "teacher_verdict_hint": "20日+17.6%",
        "source_ref": "knowhow.md §對照",
    },
    {
        "event_date": "2025-12-17",
        "stock_id": "8299",
        "name": "群聯",
        "said": "記憶體布局；PCB做出貨",
        "group": "記憶體",
        "horizon_days": 20,
        "teacher_verdict_hint": "記憶體20日+73%級",
        "source_ref": "knowhow.md §對照",
    },
    {
        "event_date": "2025-12-17",
        "stock_id": "2408",
        "name": "南亞科",
        "said": "記憶體布局；PCB做出貨",
        "group": "記憶體",
        "horizon_days": 20,
        "teacher_verdict_hint": "記憶體20日+52%級",
        "source_ref": "knowhow.md §對照",
    },
    {
        "event_date": "2026-02-24",
        "stock_id": "6515",
        "name": "穎崴",
        "said": "高階檢測很少人提，可波段",
        "group": "高階測試",
        "horizon_days": 20,
        "teacher_verdict_hint": "20日+83%級",
        "source_ref": "knowhow.md §對照",
    },
    {
        "event_date": "2026-07-23",
        "stock_id": "3017",
        "name": "奇鋐",
        "said": "散熱先確認低點、先彈",
        "group": "散熱",
        "horizon_days": 20,
        "teacher_verdict_hint": "20日+22%",
        "source_ref": "knowhow.md §對照",
    },
]


def _now_tp() -> datetime:
    return datetime.now(TP)


def _ymd(s: str) -> str:
    return str(s or "").replace("-", "")[:8]


def _load_stock_window(
    stock_id: str, as_of: str, *, before: int = 8, after: int = 40
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[str]]:
    gaps: List[str] = []
    ymd = _ymd(as_of)
    if not MARKET_DB.exists():
        return [], [], ["缺 wayne_market.db"]
    con = sqlite3.connect(f"file:{MARKET_DB}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        pre = con.execute(
            """
            SELECT date, open, high, low, close, volume FROM daily_quotes
            WHERE stock_id=? AND date<=?
            ORDER BY date DESC LIMIT ?
            """,
            (stock_id, ymd, before),
        ).fetchall()
        pre_rows = [dict(r) for r in pre]
        pre_rows.reverse()
        post = con.execute(
            """
            SELECT date, open, high, low, close, volume FROM daily_quotes
            WHERE stock_id=? AND date>?
            ORDER BY date ASC LIMIT ?
            """,
            (stock_id, ymd, after),
        ).fetchall()
        post_rows = [dict(r) for r in post]
        if not pre_rows:
            gaps.append(f"缺柱：{stock_id} ≤{ymd}")
        elif pre_rows[-1]["date"] != ymd:
            gaps.append(
                f"缺柱或休市：{stock_id} 請求日 {ymd}；近窗末日 {pre_rows[-1]['date']}"
            )
    finally:
        con.close()
    return pre_rows, post_rows, gaps


def _fwd_return(pre: List[Dict[str, Any]], post: List[Dict[str, Any]], horizon: int) -> Optional[float]:
    if not pre:
        return None
    entry = pre[-1].get("close")
    try:
        entry_f = float(entry)
    except (TypeError, ValueError):
        return None
    if entry_f <= 0:
        return None
    if len(post) < horizon:
        # 用既有末日；標樣本不足另欄
        if not post:
            return None
        exit_px = float(post[-1]["close"])
        return (exit_px - entry_f) / entry_f * 100.0
    exit_px = float(post[horizon - 1]["close"])
    return (exit_px - entry_f) / entry_f * 100.0


def _map_outcome(hint: str, ret: Optional[float]) -> str:
    h = hint or ""
    if ret is None:
        return "未完"
    if "認錯" in h or "改口" in h:
        return "他改口"
    if "偏" in h or "早了" in h or "沒" in h and "對" not in h:
        # soft — still use return sign as lab
        pass
    if "對" in h or "+" in h:
        return "對" if ret is not None and ret > 0 else "偏"
    if ret > 5:
        return "對"
    if ret < -5:
        return "偏"
    return "未完"


def _form_record(seed: Dict[str, Any]) -> Dict[str, Any]:
    as_of = seed["event_date"]
    sid = seed["stock_id"]
    horizon = int(seed.get("horizon_days") or 20)
    pre, post, gaps = _load_stock_window(sid, as_of, before=8, after=max(horizon, 40))
    ret = _fwd_return(pre, post, horizon)
    near = [
        {
            "date": b["date"],
            "o": b.get("open"),
            "h": b.get("high"),
            "l": b.get("low"),
            "c": b.get("close"),
            "v": b.get("volume"),
        }
        for b in pre
    ]
    outcome = _map_outcome(seed.get("teacher_verdict_hint") or "", ret)
    missing_curriculum = [
        "族群倖存者偏差全表：本批只點名檔，未掃未點名對照組",
        "融資使用率／千張大戶：無官方則標缺",
        "期現／基差：語料有才測 → 本批跳過",
        "某金融商品：待辨明",
        "紅箭頭 ma60_lower 分軌：另軌",
        "如何賣 20高vs最高溫：另軌",
    ]
    record = {
        "A": {
            "event_date": as_of,
            "symbol": sid,
            "name": seed.get("name"),
            "group": seed.get("group"),
            "said": seed.get("said"),
            "source_ref": seed.get("source_ref"),
            "seq": "E",
            "level_hypothesis": "點名檔近窗對質（個股不數浪）",
        },
        "B": {
            "alive_labels": [
                {
                    "label": seed.get("group") or "點名",
                    "kill": "族群領頭做頭／整族撤換／他改口不要碰",
                }
            ],
            "half_mountain": bool(seed.get("half_mountain")),
        },
        "C": {
            "near_window_ohlcv": near,
            "window_n": len(near),
            "post_n": len(post),
            "horizon_days": horizon,
        },
        "D": {
            "pot": "實驗室",
            "note": "序E不重算 Fib／DC；見序C",
            "no_stock_wave_count": True,
        },
        "E": {
            "volume_price_story": "點名近窗柱已附；裸K旗標見序D模組可另叠",
            "outer": {
                "fwd_return_pct": ret,
                "horizon_days": horizon,
                "post_complete": len(post) >= horizon,
            },
        },
        "F": {
            "teacher_claim_pot": "他說／飆預測",
            "lab_pot": "實驗室（近窗＋前瞻報酬對照）",
            "dc_estimate_pot": "DC→我估（本列未用）",
        },
        "G": {
            "outcome": outcome,
            "teacher_verdict_hint": seed.get("teacher_verdict_hint"),
            "lab_fwd_return_pct": ret,
        },
        "H": {
            "actionable_fix": (
                "半山腰只隔日沖≠走平預期；點名對質要留未點名對照才降倖存者偏差；"
                "個股不准數浪上話筒；負結果也留"
            ),
            "negative_logged": outcome in ("偏", "他改口") or (ret is not None and ret < 0),
        },
        "flags": {
            "missing_bars": gaps,
            "missing_curriculum": missing_curriculum,
            "as_of_cutoff": f"{_ymd(as_of)} 收盤後可知；盤中未收不當收",
            "survivor_bias_note": "本批皆已點名；未掃盲測對照",
            "limit_up_down": None,
            "settlement_week": None,
            "gap_open": None,
        },
        "meta": {
            "written_at": _now_tp().isoformat(),
            "tz": "Asia/Taipei",
            "not_buy_signal": True,
            "batch": "E0_named_wave1",
        },
    }
    record["counted"] = bool(sid) and len(near) > 0
    return record


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    records = [_form_record(s) for s in SEED_NAMED]
    counted = [r for r in records if r.get("counted")]
    stamp = _now_tp().strftime("%Y%m%d")
    out_jsonl = OUT_DIR / f"seq_e_named_{stamp}.jsonl"
    with out_jsonl.open("w", encoding="utf-8") as f:
        for r in counted:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    alias = OUT_DIR / "seq_e_named_latest.jsonl"
    alias.write_text(out_jsonl.read_text(encoding="utf-8"), encoding="utf-8")

    n_pos = sum(
        1
        for r in counted
        if isinstance((r.get("E") or {}).get("outer", {}).get("fwd_return_pct"), (int, float))
        and (r["E"]["outer"]["fwd_return_pct"] or 0) > 0
    )

    md = [
        "# 序E｜點名檔近窗對質第一批",
        "",
        f"寫入：`{_now_tp().isoformat()}`（Asia/Taipei）。",
        f"種子 n={len(SEED_NAMED)}；有記 n={len(counted)}；前瞻報酬>0 n={n_pos}。",
        "鍋：他說＝點名主張；實驗室＝近窗柱＋N日報酬。個股不數浪。不是買訊。",
        "倖存者偏差：本批皆已點名，盲測對照未跑。融資／大戶／期現／金融商品標缺。",
        "",
        f"JSONL：`{alias.relative_to(ROOT)}`",
        "",
    ]
    for r in counted:
        a = r["A"]
        e = (r.get("E") or {}).get("outer") or {}
        g = r.get("G") or {}
        md.append(f"## {a['event_date']} {a['symbol']} {a.get('name') or ''}".rstrip())
        md.append("")
        md.append(f"- **A** {a.get('said')}（{a.get('group')}）")
        md.append(
            f"- **E** {e.get('horizon_days')}日報酬={None if e.get('fwd_return_pct') is None else round(e['fwd_return_pct'], 1)}%"
            f"；樣本齊={e.get('post_complete')}"
        )
        md.append(f"- **G** {g.get('outcome')}｜{g.get('teacher_verdict_hint')}")
        if (r.get("B") or {}).get("half_mountain"):
            md.append("- **半山腰**：只當操作方式標籤")
        gaps = (r.get("flags") or {}).get("missing_bars") or []
        if gaps:
            md.append("- **缺柱**：" + "；".join(gaps[:3]))
        md.append("")

    md_path = OUT_DIR / "seq_e_named_latest.md"
    md_path.write_text("\n".join(md) + "\n", encoding="utf-8")
    summary = {
        "written_at": _now_tp().isoformat(),
        "tz": "Asia/Taipei",
        "n_seed": len(SEED_NAMED),
        "n_counted": len(counted),
        "n_fwd_positive": n_pos,
        "jsonl": str(alias.relative_to(ROOT)),
        "md": str(md_path.relative_to(ROOT)),
        "not_buy_signal": True,
        "pot": "實驗室＋他說附原文",
        "skipped": [
            "survivor_blind_controls",
            "margin_large_holder",
            "basis_futures",
            "mystery_instrument",
            "ma60_lower_track",
            "how_to_sell_track",
        ],
    }
    (OUT_DIR / "seq_e_named_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False))
    return 0 if counted else 1


if __name__ == "__main__":
    raise SystemExit(main())
