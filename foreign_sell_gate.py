# -*- coding: utf-8 -*-
"""外資／恐懼預警｜分軌閘門與明確優化狀態（不是買訊）。

正反向分軌；勝率不准混。n≥20 且贏該軌現況 → 該軌可收正式觀察文案；
未過閘維持「還在測試」。不准改 leave_zero／黃金買點／藍▲紅框。
時區 Asia/Taipei。
"""
from __future__ import annotations

import os
import sqlite3
from typing import Any, Dict, List, Optional

from dongzhu_tape import OPTIMIZE_MIN_N, tape_store_path

MIN_N = OPTIMIZE_MIN_N

# 離線全量回測備註（2026-10-25 密窗 20260324→20261022 n=145；不是靜默 live n，不准當假 live）
OFFLINE_NOTE: Dict[str, str] = {
    "fear": (
        "離線：ForeignSell lead 亮 hit≈23.4% vs 基線≈7.7% 有 lift；"
        "StockHit top500 亮≈11.7% 輸暗≈13.4%；Dump 解讀分歧"
    ),
    "escalate": (
        "離線密窗：n5_k3_th90 top500 hit≈16.8% vs 基線≈12.3% 有 lift；"
        "現況 n3 近平基線；下一版靜默仍 n5；靜默 n 未滿不換碼"
    ),
    "extreme": (
        "離線密窗：續極端 lots_th5000 命中≈69.5% vs≈8.8%；"
        "價回撤 −5% 近平／輸基線，不當主閘"
    ),
    "calm": (
        "離線密窗：小買→大買 top500 n5 弱 lift（≈54.4% vs≈52.5%）、"
        "流動對照近平；未過閘；買升級橘六角仍不亮"
    ),
}

TRACKS = ("fear", "escalate", "extreme", "calm")


def _ymd(raw: Any) -> str:
    t = str(raw or "").replace("-", "")[:8]
    return t if len(t) == 8 and t.isdigit() else ""


def _conn(store: str) -> Optional[sqlite3.Connection]:
    if not store or not os.path.isfile(store):
        return None
    try:
        return sqlite3.connect(store, timeout=5.0)
    except sqlite3.Error:
        return None


def _distinct_tape_days(store: str, table: str, kind: str) -> int:
    conn = _conn(store)
    if conn is None:
        return 0
    try:
        row = conn.execute(
            f"SELECT COUNT(DISTINCT as_of) FROM {table} WHERE kind=?",
            (kind,),
        ).fetchone()
        return int(row[0] or 0) if row else 0
    except sqlite3.Error:
        return 0
    finally:
        conn.close()


def _fear_gate(db_path: str) -> Dict[str, Any]:
    try:
        from fear_preopen_verify import gate_status

        g = gate_status(db_path)
    except Exception:
        g = {"n_days": 0, "ready_to_observe": False}
    n = int(g.get("n_days") or 0)
    # 離線 StockHit 輸、Dump 分歧；僅 ForeignSell 有 lift → 整體未過「贏現況」
    # 靜默 rates 未證贏話筒現況前，不准收正式觀察文案
    return {
        "track": "fear",
        "label": "開盤前恐懼",
        "n_days": n,
        "min_n": MIN_N,
        "n_ok": n >= MIN_N,
        "wins_current": False,
        "promote_observe_copy": False,
        "display_mode": "test",
        "buy_signal": False,
        "offline_note": OFFLINE_NOTE["fear"],
        "next_silent": "v2_n-1.2_twd0.3_dx0.4_br3",
    }


def _escalate_gate(db_path: str) -> Dict[str, Any]:
    store = tape_store_path(db_path) if db_path else ""
    n_tape = _distinct_tape_days(store, "foreign_sell_escalate_tape", "foreign_sell_escalate")
    n_rates = 0
    hit = miss = 0
    try:
        from foreign_sell_escalate_verify import gate_status

        g = gate_status(db_path)
        n_rates = int(g.get("n_days") or 0)
    except Exception:
        g = {}
    conn = _conn(store)
    if conn is not None:
        try:
            row = conn.execute(
                """
                SELECT hit, miss FROM foreign_sell_escalate_rates
                WHERE kind=? AND lead_sync='lead'
                ORDER BY updated_at DESC LIMIT 1
                """,
                ("foreign_sell_escalate",),
            ).fetchone()
            if row:
                hit, miss = int(row[0] or 0), int(row[1] or 0)
        except sqlite3.Error:
            pass
        finally:
            conn.close()
    n = max(n_tape, n_rates)
    # 離線有 lift，但靜默對質尚未收滿／未證明贏話筒現況編碼 → 不准正式
    win = False
    return {
        "track": "escalate",
        "label": "小賣→大賣",
        "n_days": n,
        "n_tape_days": n_tape,
        "n_scored_days": n_rates,
        "hit": hit,
        "miss": miss,
        "min_n": MIN_N,
        "n_ok": n >= MIN_N,
        "wins_current": win,
        "promote_observe_copy": False,
        "display_mode": "test",
        "buy_signal": False,
        "offline_note": OFFLINE_NOTE["escalate"],
        "next_silent": "n5_k3_th90_u2",
    }


def _extreme_gate(db_path: str) -> Dict[str, Any]:
    store = tape_store_path(db_path) if db_path else ""
    n = _distinct_tape_days(store, "foreign_sell_extreme_tape", "foreign_sell_extreme_dplus")
    win = False  # 靜默尚未對完續極端 vs 現況；離線 lift 不算 live 過閘
    return {
        "track": "extreme",
        "label": "極端大賣D+",
        "n_days": n,
        "min_n": MIN_N,
        "n_ok": n >= MIN_N,
        "wins_current": win,
        "promote_observe_copy": False,
        "display_mode": "test",
        "buy_signal": False,
        "offline_note": OFFLINE_NOTE["extreme"],
        "next_silent": "share_th0.25",
    }


def _calm_gate(db_path: str) -> Dict[str, Any]:
    store = tape_store_path(db_path) if db_path else ""
    n = _distinct_tape_days(store, "foreign_sell_calm_tape", "foreign_sell_calm_env")
    # 離線近平基線 → 明確未贏
    return {
        "track": "calm",
        "label": "Calm／小買環境",
        "n_days": n,
        "min_n": MIN_N,
        "n_ok": n >= MIN_N,
        "wins_current": False,
        "promote_observe_copy": False,
        "display_mode": "test",
        "buy_signal": False,
        "offline_note": OFFLINE_NOTE["calm"],
        "next_silent": "buy_n5_k3_th90_u2",
    }


def all_track_gates(db_path: str = "") -> List[Dict[str, Any]]:
    path = str(db_path or "").strip()
    return [
        _fear_gate(path),
        _escalate_gate(path),
        _extreme_gate(path),
        _calm_gate(path),
    ]


def any_promote(db_path: str = "") -> bool:
    return any(bool(g.get("promote_observe_copy")) for g in all_track_gates(db_path))


def optimize_status_one_liner(db_path: str = "") -> str:
    """對話唯一准講的明確優化狀態一句。"""
    gates = all_track_gates(db_path)
    bits = []
    for g in gates:
        n = int(g.get("n_days") or 0)
        need = int(g.get("min_n") or MIN_N)
        if g.get("promote_observe_copy"):
            bits.append(f"{g['label']}可收正式觀察")
        elif n >= need:
            bits.append(f"{g['label']}n={n}未贏現況")
        else:
            bits.append(f"{g['label']}n={n}/{need}")
    return (
        "明確優化狀態：外資／恐懼預警四軌皆未過閘（"
        + "；".join(bits)
        + "）→ 話筒維持還在測試；非買訊、不改黃金買點"
    )


def gate_table_md(db_path: str = "") -> str:
    """PR／回報用分軌表（可含離線備註；不准當假 live）。"""
    lines = [
        "| 軌 | 靜默獨立日 n | n≥20 | 贏該軌現況 | 話筒 | 備註 |",
        "|---|---:|:---:|:---:|:---:|---|",
    ]
    for g in all_track_gates(db_path):
        n = int(g.get("n_days") or 0)
        lines.append(
            "| {label} | {n} | {nok} | {win} | {mode} | {note} |".format(
                label=g["label"],
                n=n,
                nok="是" if g.get("n_ok") else "否",
                win="是" if g.get("wins_current") else "否",
                mode="正式觀察" if g.get("promote_observe_copy") else "還在測試",
                note=str(g.get("offline_note") or "")[:80],
            )
        )
    return "\n".join(lines)


__all__ = [
    "MIN_N",
    "OFFLINE_NOTE",
    "TRACKS",
    "all_track_gates",
    "any_promote",
    "optimize_status_one_liner",
    "gate_table_md",
]
