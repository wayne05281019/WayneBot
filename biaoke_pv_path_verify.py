# -*- coding: utf-8 -*-
"""D10／D11a／D11g 價量路徑靜默對質落檔骨架（非買訊；預設不上話筒臉）。

分軌 kind：
  - biaoke_pv_d10_path
  - biaoke_pv_d11a_triple
  - biaoke_pv_d11g_wash_dist

硬規則：官方已收 OHLC＋量；盤中未收不當收；無假數；勝率分軌；
不准改 leave_zero／golden_buy／海選；n≥20 且贏該軌基線才談上臉。
Asia/Taipei。失敗不擋出卡。過程／％不准進對話。
"""
from __future__ import annotations

import json
import os
import sqlite3
from typing import Any, Dict, List, Optional, Sequence

KIND_D10 = "biaoke_pv_d10_path"
KIND_D11A = "biaoke_pv_d11a_triple"
KIND_D11G = "biaoke_pv_d11g_wash_dist"
KINDS = (KIND_D10, KIND_D11A, KIND_D11G)


def ensure_tables(db_path: str) -> None:
    path = str(db_path or "").strip()
    if not path:
        return
    con = sqlite3.connect(path, timeout=12.0)
    try:
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS biaoke_pv_path_events (
                as_of TEXT NOT NULL,
                stock_id TEXT NOT NULL,
                kind TEXT NOT NULL,
                variant TEXT NOT NULL,
                spike_date TEXT,
                event_date TEXT NOT NULL,
                path TEXT,
                close REAL,
                volume REAL,
                h1 REAL,
                h3 REAL,
                h5 REAL,
                cont_down_h5 INTEGER,
                v_reversal_10 INTEGER,
                meta_json TEXT,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (as_of, stock_id, kind, variant, event_date)
            );
            CREATE INDEX IF NOT EXISTS idx_biaoke_pv_path_kind
                ON biaoke_pv_path_events(kind, variant, as_of);
            """
        )
        con.commit()
    finally:
        con.close()


def rates_summary(db_path: str, *, kind: str) -> Dict[str, Any]:
    """分軌彙總；對話只准在明確優化狀態用一句。"""
    ensure_tables(db_path)
    con = sqlite3.connect(db_path, timeout=12.0)
    try:
        rows = con.execute(
            """
            SELECT variant,
                   COUNT(*) AS n_events,
                   COUNT(DISTINCT as_of) AS n_days,
                   AVG(h5) AS mean_h5,
                   AVG(CASE WHEN cont_down_h5 IS NOT NULL THEN cont_down_h5 END) AS cont_down_rate,
                   AVG(CASE WHEN v_reversal_10 IS NOT NULL THEN v_reversal_10 END) AS v_rate
            FROM biaoke_pv_path_events
            WHERE kind=?
            GROUP BY variant
            """,
            (kind,),
        ).fetchall()
    finally:
        con.close()
    out = {"kind": kind, "variants": {}}
    for variant, n_events, n_days, mean_h5, cont_down_rate, v_rate in rows:
        out["variants"][str(variant)] = {
            "n_events": int(n_events or 0),
            "n_unique_days": int(n_days or 0),
            "mean_h5": mean_h5,
            "cont_down_h5_rate": cont_down_rate,
            "v_reversal_rate": v_rate,
            "gate_n20": int(n_days or 0) >= 20,
            "face": False,
        }
    return out


def run_skeleton(
    db_path: str,
    *,
    stock_ids: Optional[Sequence[str]] = None,
    limit_stocks: int = 80,
    json_snapshot: str = "",
) -> Dict[str, Any]:
    """可從 deepdive JSON 匯入，或僅建表回傳空骨架狀態。"""
    ensure_tables(db_path)
    imported = 0
    if json_snapshot and os.path.isfile(json_snapshot):
        raw = json.loads(open(json_snapshot, encoding="utf-8").read())
        # 深拆結果不自動當閘；只示意落檔形狀。正式日更應由排程逐日寫入。
        deepdives = raw.get("deepdives") or []
        con = sqlite3.connect(db_path, timeout=12.0)
        try:
            from datetime import datetime
            from zoneinfo import ZoneInfo

            now = datetime.now(ZoneInfo("Asia/Taipei")).isoformat(timespec="seconds")
            for dd in deepdives:
                if not dd.get("ok"):
                    continue
                sid = str(dd.get("stock_id") or "")
                if stock_ids and sid not in set(stock_ids):
                    continue
                for p in dd.get("recent_spike_paths") or []:
                    path = str(p.get("path") or "")
                    ed = str(p.get("event_date") or p.get("spike_date") or "")
                    if not ed:
                        continue
                    fwd = p.get("fwd") or {}
                    con.execute(
                        """
                        INSERT OR REPLACE INTO biaoke_pv_path_events(
                          as_of, stock_id, kind, variant, spike_date, event_date,
                          path, close, volume, h1, h3, h5, cont_down_h5,
                          v_reversal_10, meta_json, updated_at
                        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                        """,
                        (
                            ed,
                            sid,
                            KIND_D10,
                            path or "undecided",
                            str(p.get("spike_date") or ""),
                            ed,
                            path,
                            (p.get("spike_ohlcv") or {}).get("c"),
                            (p.get("spike_ohlcv") or {}).get("v"),
                            fwd.get("h1"),
                            fwd.get("h3"),
                            fwd.get("h5"),
                            1 if p.get("cont_down_h5") else (0 if p.get("cont_down_h5") is False else None),
                            None,
                            json.dumps({"source": "deepdive_snapshot"}, ensure_ascii=False),
                            now,
                        ),
                    )
                    imported += 1
                    if path in ("wash", "distribution"):
                        con.execute(
                            """
                            INSERT OR REPLACE INTO biaoke_pv_path_events(
                              as_of, stock_id, kind, variant, spike_date, event_date,
                              path, close, volume, h1, h3, h5, cont_down_h5,
                              v_reversal_10, meta_json, updated_at
                            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                            """,
                            (
                                ed,
                                sid,
                                KIND_D11G,
                                path,
                                str(p.get("spike_date") or ""),
                                ed,
                                path,
                                (p.get("spike_ohlcv") or {}).get("c"),
                                (p.get("spike_ohlcv") or {}).get("v"),
                                fwd.get("h1"),
                                fwd.get("h3"),
                                fwd.get("h5"),
                                1 if p.get("cont_down_h5") else (0 if p.get("cont_down_h5") is False else None),
                                None,
                                json.dumps({"source": "deepdive_snapshot"}, ensure_ascii=False),
                                now,
                            ),
                        )
                        imported += 1
                for t in dd.get("triple_traps") or []:
                    ed = str(t.get("v3") or "")
                    if not ed:
                        continue
                    fwd = t.get("fwd") or {}
                    con.execute(
                        """
                        INSERT OR REPLACE INTO biaoke_pv_path_events(
                          as_of, stock_id, kind, variant, spike_date, event_date,
                          path, close, volume, h1, h3, h5, cont_down_h5,
                          v_reversal_10, meta_json, updated_at
                        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                        """,
                        (
                            ed,
                            sid,
                            KIND_D11A,
                            "triple_v3",
                            str(t.get("v1") or ""),
                            ed,
                            "triple_trap",
                            ((t.get("bars") or {}).get("v3") or {}).get("c"),
                            ((t.get("bars") or {}).get("v3") or {}).get("v"),
                            fwd.get("h1"),
                            fwd.get("h3"),
                            fwd.get("h5"),
                            1 if t.get("cont_down_h5") else (0 if t.get("cont_down_h5") is False else None),
                            1 if t.get("v_hit_10") else (0 if t.get("v_hit_10") is False else None),
                            json.dumps({"v1": t.get("v1"), "v2": t.get("v2")}, ensure_ascii=False),
                            now,
                        ),
                    )
                    imported += 1
            con.commit()
        finally:
            con.close()

    summary = {k: rates_summary(db_path, kind=k) for k in KINDS}
    return {
        "ok": True,
        "imported_rows": imported,
        "limit_stocks": limit_stocks,
        "face_default": False,
        "tracks": summary,
        "note": "skeleton only; not buy signal; no face until n≥20 and beats baseline",
    }
