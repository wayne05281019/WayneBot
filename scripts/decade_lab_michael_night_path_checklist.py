#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""麥可夜盤三路徑 → 隔日勾選（固定覆盤欄）。

S9：夜盤先寫 A／B／C → 隔日對官方柱／他自己「成立」句勾選。
phone_sync=blocked；buy_signal=false；不准混海選／黃金買點。
15 分均線細判缺 minute 時標 pending_tx15；日盤粗判用 futures_daily。
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "docs" / "expert_notes" / "飆客" / "decade_lab"
TAIPEI = ZoneInfo("Asia/Taipei")
SCHEMA = "michael_night_path_day_check_v1"
OPS_ID = "S9_night_path_then_day_check"
TRACK = "michael_tx15_teach"

STATUS_OK = ("pending", "hit", "miss", "partial", "pending_tx15", "observe_only")


def _now() -> str:
    return datetime.now(TAIPEI).strftime("%Y-%m-%dT%H:%M:%S%z")


def _ymd(raw: Any) -> str:
    t = str(raw or "").replace("-", "")[:8]
    return t if len(t) == 8 and t.isdigit() else ""


def blank_checklist(
    *,
    night_asof: str,
    day_asof: str,
    source_post_id: Optional[str] = None,
) -> Dict[str, Any]:
    """固定欄位模板：三路徑各一組夜盤盒＋隔日盒。"""
    na = _ymd(night_asof)
    da = _ymd(day_asof)
    if not na or not da:
        raise ValueError("night_asof／day_asof 必須 YYYYMMDD")
    return {
        "schema": SCHEMA,
        "as_of_taipei": _now(),
        "tz": "Asia/Taipei",
        "track": TRACK,
        "ops_id": OPS_ID,
        "phone_sync": "blocked",
        "buy_signal": False,
        "mix_into_biaoke_screen": False,
        "not_buy_signal": True,
        "night_asof": na,
        "day_asof": da,
        "source_post_id": source_post_id,
        "paths": [
            {
                "id": "A_range_120_60",
                "p_said": 0.65,
                "night_box": {
                    "label_zh": "夜盤多半落在15K120～60帶（時間換空間）",
                    "status": "pending",
                    "evidence_zh": "",
                },
                "day_box": {
                    "label_zh": "隔日僅消化夜盤震盪（非早弱／非一路高歌）",
                    "status": "pending",
                    "evidence_zh": "",
                },
            },
            {
                "id": "B_weak_below_ma10",
                "p_said": 0.20,
                "night_box": {
                    "label_zh": "夜盤收在15K10下且反彈無力",
                    "status": "pending",
                    "evidence_zh": "",
                },
                "day_box": {
                    "label_zh": "隔日早盤偏弱；若撿≥10:00",
                    "status": "pending",
                    "evidence_zh": "",
                },
            },
            {
                "id": "C_reclaim_ma120",
                "p_said": 0.15,
                "night_box": {
                    "label_zh": "夜盤收前15K120翻上（末兩根在上）",
                    "status": "pending",
                    "evidence_zh": "",
                },
                "day_box": {
                    "label_zh": "隔日偏一路高歌／早盤站上延續",
                    "status": "pending",
                    "evidence_zh": "",
                },
            },
        ],
        "edge_rules": [
            {
                "id": "near_120_no_long",
                "label_zh": "近15K120不做多",
                "status": "observe_only",
            },
            {
                "id": "near_60_no_short",
                "label_zh": "近15K60不做空",
                "status": "observe_only",
            },
        ],
        "official": {"tx_night": None, "tx_regular": None},
        "verdict_zh": "",
        "preferred_path": None,
        "note_zh": "固定覆盤欄；非買訊；不上話筒；不准寫進海選／黃金買點",
    }


def _load_tx_session(
    conn: sqlite3.Connection, day: str, session: str
) -> Optional[Dict[str, float]]:
    row = conn.execute(
        """
        SELECT open, high, low, close, volume
        FROM futures_daily
        WHERE symbol='TX' AND date=? AND session=?
        LIMIT 1
        """,
        (day, session),
    ).fetchone()
    if not row:
        return None
    return {
        "o": float(row[0]),
        "h": float(row[1]),
        "l": float(row[2]),
        "c": float(row[3]),
        "v": float(row[4] or 0),
    }


def attach_official_bars(
    doc: Dict[str, Any], conn: Optional[sqlite3.Connection] = None
) -> Dict[str, Any]:
    """附官方期指日／夜盤柱（有才寫；未收不補假數）。"""
    out = deepcopy(doc)
    close_conn = False
    if conn is None:
        db = Path(os.environ.get("WAYNE_DB_PATH") or (ROOT / "data" / "wayne_market.db"))
        if not db.exists():
            return out
        conn = sqlite3.connect(str(db))
        close_conn = True
    try:
        night = _load_tx_session(conn, out["night_asof"], "night")
        day = _load_tx_session(conn, out["day_asof"], "regular")
        out["official"] = {"tx_night": night, "tx_regular": day}
    finally:
        if close_conn and conn is not None:
            conn.close()
    return out


def set_box(
    doc: Dict[str, Any],
    path_id: str,
    which: str,
    status: str,
    evidence_zh: str = "",
) -> Dict[str, Any]:
    if status not in STATUS_OK:
        raise ValueError(f"bad status: {status}")
    if which not in ("night_box", "day_box"):
        raise ValueError(f"bad which: {which}")
    out = deepcopy(doc)
    for p in out["paths"]:
        if p["id"] == path_id:
            p[which]["status"] = status
            if evidence_zh:
                p[which]["evidence_zh"] = evidence_zh
            return out
    raise KeyError(path_id)


def coarse_day_hint(doc: Dict[str, Any]) -> Dict[str, Any]:
    """用日盤／夜盤收相對粗判 C／B（細 15K 仍 pending_tx15）。

    - 日盤收 ≫ 夜盤收且日高明顯高於夜收 → C day 傾向 hit
    - 日盤開／低明顯弱於夜收 → B day 傾向 hit
    - 其餘不自動改 A／B／C 夜盤細盒
    """
    out = deepcopy(doc)
    night = (out.get("official") or {}).get("tx_night") or {}
    day = (out.get("official") or {}).get("tx_regular") or {}
    if not night or not day:
        return out
    nc = float(night["c"])
    do, dh, dl, dc = float(day["o"]), float(day["h"]), float(day["l"]), float(day["c"])
    # 強：開高或收在夜收之上且衝高
    strong = (dc >= nc * 1.002 and dh >= nc * 1.008) or (do >= nc * 1.005 and dh > nc)
    # 弱：開低且低點明顯低於夜收
    weak = (do <= nc * 0.997 and dl <= nc * 0.99) or (dc <= nc * 0.995 and dl < nc)
    for p in out["paths"]:
        if p["id"] == "C_reclaim_ma120" and p["day_box"]["status"] in (
            "pending",
            "pending_tx15",
        ):
            if strong:
                p["day_box"]["status"] = "hit"
                p["day_box"]["evidence_zh"] = (
                    f"粗判：日盤 O{do:.0f}/H{dh:.0f}/C{dc:.0f} vs 夜收{nc:.0f}＝偏強"
                    "（15K120 細判仍待 minute）"
                )
            else:
                p["day_box"]["status"] = "pending_tx15"
        if p["id"] == "B_weak_below_ma10" and p["day_box"]["status"] in (
            "pending",
            "pending_tx15",
        ):
            if weak and not strong:
                p["day_box"]["status"] = "hit"
                p["day_box"]["evidence_zh"] = (
                    f"粗判：日盤 O{do:.0f}/L{dl:.0f}/C{dc:.0f} vs 夜收{nc:.0f}＝偏弱"
                )
            elif strong:
                p["day_box"]["status"] = "miss"
                p["day_box"]["evidence_zh"] = "粗判：日盤偏強→早弱路徑未成立"
            else:
                p["day_box"]["status"] = "pending_tx15"
        if p["id"] == "A_range_120_60" and p["day_box"]["status"] == "pending":
            if strong or weak:
                p["day_box"]["status"] = "miss"
                p["day_box"]["evidence_zh"] = "粗判：隔日有明確強／弱方向→非純消化震盪"
            else:
                p["day_box"]["status"] = "pending_tx15"
        # 夜盤細盒缺 15K → pending_tx15（除非已人工／口頭勾）
        if p["night_box"]["status"] == "pending":
            p["night_box"]["status"] = "pending_tx15"
            if not p["night_box"].get("evidence_zh"):
                p["night_box"]["evidence_zh"] = "待 15 分官方柱對 120／60／10"
    return out


def summarize(doc: Dict[str, Any]) -> Dict[str, Any]:
    out = deepcopy(doc)
    hits: List[str] = []
    for p in out["paths"]:
        n, d = p["night_box"]["status"], p["day_box"]["status"]
        if n == "hit" or d == "hit":
            hits.append(p["id"])
    # preferred：夜盤主機率 A 若 hit；否則日盤 C／B
    pref = None
    for pid in ("A_range_120_60", "C_reclaim_ma120", "B_weak_below_ma10"):
        p = next(x for x in out["paths"] if x["id"] == pid)
        if p["night_box"]["status"] == "hit" or p["day_box"]["status"] == "hit":
            pref = pid
            break
    out["preferred_path"] = pref
    out["verdict_zh"] = (
        f"勾選命中：{', '.join(hits) if hits else '尚無'}；"
        f"preferred={pref or 'none'}；非買訊"
    )
    return out


def seed_20261113_oral(doc: Dict[str, Any]) -> Dict[str, Any]:
    """11/13 夜盤表＋他自己隔日「成立」句（語料已鎖）。"""
    out = deepcopy(doc)
    out["source_post_id"] = "188400106:c188400106-440"
    out["user_lock_zh"] = "2026-11-13 使用者：有參考價值；2026-11-14 固定覆盤欄"
    out = set_box(
        out,
        "A_range_120_60",
        "night_box",
        "hit",
        "口頭自對：夜盤主機率震盪成立（c188594037-246）",
    )
    out = set_box(
        out,
        "C_reclaim_ma120",
        "night_box",
        "partial",
        "路徑4＝強翻120延伸；夜盤主仍A，收前／早盤銜接待細對",
    )
    out = set_box(
        out,
        "C_reclaim_ma120",
        "day_box",
        "hit",
        "口頭自對：早盤第一根站上15K120→開噴；達標下车（c188594037-379）",
    )
    out = set_box(
        out,
        "B_weak_below_ma10",
        "night_box",
        "miss",
        "主路徑非弱收10下",
    )
    out = set_box(
        out,
        "B_weak_below_ma10",
        "day_box",
        "miss",
        "隔日偏強／高歌，非早弱",
    )
    out = set_box(
        out,
        "A_range_120_60",
        "day_box",
        "miss",
        "隔日路徑4延伸＝一路高歌，非純消化震盪",
    )
    return out


def write_checklist(doc: Dict[str, Any], *, also_latest: bool = True) -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    day = doc["day_asof"]
    path = OUT_DIR / f"michael_night_path_checklist_{day}.json"
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if also_latest:
        latest = OUT_DIR / "michael_night_path_checklist_latest.json"
        latest.write_text(
            json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    return path


def build_and_write(
    *,
    night_asof: str,
    day_asof: str,
    seed_oral_1113: bool = False,
    coarse: bool = True,
) -> Dict[str, Any]:
    doc = blank_checklist(night_asof=night_asof, day_asof=day_asof)
    if seed_oral_1113:
        doc = seed_20261113_oral(doc)
    doc = attach_official_bars(doc)
    if coarse and not seed_oral_1113:
        doc = coarse_day_hint(doc)
    doc = summarize(doc)
    write_checklist(doc)
    return doc


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="麥可夜盤三路徑隔日勾選覆盤欄")
    ap.add_argument("--night", required=True, help="夜盤 asof YYYYMMDD")
    ap.add_argument("--day", required=True, help="隔日／日盤 asof YYYYMMDD")
    ap.add_argument(
        "--seed-oral-1113",
        action="store_true",
        help="灌入 11/13 口頭自對範例（語料鎖）",
    )
    ap.add_argument("--no-coarse", action="store_true", help="不做日盤粗判")
    args = ap.parse_args(argv)
    doc = build_and_write(
        night_asof=args.night,
        day_asof=args.day,
        seed_oral_1113=args.seed_oral_1113,
        coarse=not args.no_coarse,
    )
    print(json.dumps({"ok": True, "day_asof": doc["day_asof"], "verdict_zh": doc["verdict_zh"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
