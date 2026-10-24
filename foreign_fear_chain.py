# -*- coding: utf-8 -*-
"""外資恐懼鏈｜全量回測收斂常數與離線裁決（不是買訊）。

主軸：小賣→大賣（escalate）與反向小買→大買（calm）分軌；
勝率不准混。獨立交易日 n≥20 且贏該軌現況才談換編碼（§13）。
未過閘不准改話筒買訊／海選／leave_zero。單位：張（1張＝1000股）。
時區 Asia/Taipei。
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

from foreign_sell_gate import MIN_N, all_track_gates, optimize_status_one_liner

# 本庫外資 T86 連續密窗起點（≥800 檔有 foreign_net；2026-10-25 盤點）
DENSE_FOREIGN_START = "20260324"
DEFAULT_ARTIFACT_ROOT = "/opt/cursor/artifacts/foreign-fear-chain-20261025"

# 離線全量（密窗）裁決摘要——不是 live 靜默 n；不准當假 live 過閘
OFFLINE_CONVERGE_20261025: Dict[str, Dict[str, Any]] = {
    "escalate": {
        "window": {"start": DENSE_FOREIGN_START, "end": "20261022", "n_dense_days": 145},
        "current_key": "n3_k3_th90_u2",
        "next_silent_key": "n5_k3_th90_u2",
        "top500_current": {"hit": 0.127, "base": 0.127, "lit": 1322, "lift": False},
        "top500_next": {"hit": 0.168, "base": 0.123, "lit": 2728, "lift": True},
        "units_ok": True,
        "promote_encoding": False,
        "reason": "現況 n3 近平基線；n5 離線有 lift 但靜默獨立日未≥20，只續靜默落檔",
    },
    "calm": {
        "window": {"start": DENSE_FOREIGN_START, "end": "20261022", "n_dense_days": 145},
        "current_key": "buy_n3_k3_th90_u2",
        "next_silent_key": "buy_n5_k3_th90_u2",
        "top500_current": {"hit": 0.474, "base": 0.529, "lit": 1277, "lift": False},
        "top500_next": {"hit": 0.544, "base": 0.525, "lit": 2567, "lift": "weak"},
        "liquid_next": {"hit": 0.517, "base": 0.519, "lift": False},
        "units_ok": True,
        "promote_encoding": False,
        "reason": "反向小買→大買多數近平／弱於基線；買升級橘六角仍不亮",
    },
    "extreme": {
        "window": {"start": DENSE_FOREIGN_START, "end": "20261022", "n_dense_days": 145},
        "next_silent_key": "share_th0.25",
        "cont_extreme_example": {
            "key": "lots_th5000@top500",
            "hit": 0.695,
            "base": 0.088,
            "lift": True,
        },
        "price_dd": {"lift": False, "note": "價回撤 −5% 近平／輸基線，不當主閘"},
        "promote_encoding": False,
        "reason": "續極端離線大贏但靜默 n 未滿；價回撤不當主訊號；未改買訊",
    },
}


def load_json(path: str) -> Optional[Dict[str, Any]]:
    if not path or not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def converge_verdict(
    db_path: str = "",
    *,
    artifact_root: str = "",
) -> Dict[str, Any]:
    """合併 live 靜默閘＋離線全量備註；永遠 buy_signal=False。"""
    root = str(artifact_root or DEFAULT_ARTIFACT_ROOT).rstrip("/")
    gates = all_track_gates(str(db_path or "").strip())
    by_track = {str(g.get("track") or ""): g for g in gates}
    offline = dict(OFFLINE_CONVERGE_20261025)
    # 若本機剛跑完 artifact，覆寫數字
    esc = load_json(f"{root}/escalate/foreign_sell_escalate_report.json")
    calm = load_json(f"{root}/calm/foreign_sell_calm_report.json")
    if esc:
        offline["escalate"] = {
            **offline["escalate"],
            "window": esc.get("window") or offline["escalate"]["window"],
            "units_ok": bool(((esc.get("units") or {}).get("consistency") or {}).get("units_ok")),
            "artifact": f"{root}/escalate/foreign_sell_escalate_report.json",
        }
    if calm:
        offline["calm"] = {
            **offline["calm"],
            "window": calm.get("window") or offline["calm"]["window"],
            "units_ok": bool(calm.get("units_ok")),
            "artifact": f"{root}/calm/foreign_sell_calm_report.json",
        }
    any_n_ok = any(bool(g.get("n_ok")) for g in gates)
    any_promote = any(bool(g.get("promote_observe_copy")) for g in gates)
    return {
        "generated_note": "foreign_fear_chain.converge_verdict",
        "tz": "Asia/Taipei",
        "dense_foreign_start": DENSE_FOREIGN_START,
        "min_n": MIN_N,
        "buy_signal": False,
        "promote_leave_zero": False,
        "promote_golden_buy": False,
        "any_silent_n_ok": bool(any_n_ok),
        "any_promote_observe": bool(any_promote),
        "gate_one_liner": optimize_status_one_liner(str(db_path or "").strip()),
        "live_gates": by_track,
        "offline": offline,
        "tracks_focus": ("escalate", "calm"),
        "hard_rules": [
            "外資恐懼鏈／反向＝環境／觀察，不是買訊",
            "進場只認藍▲紅框",
            "勝率分軌不准混；空名單不算 n",
            "n≥20 且贏該軌現況才換編碼；未過閘只靜默",
            "張≠股（1張＝1000股）；T86／量欄單位張",
        ],
    }


def converge_md(verdict: Dict[str, Any]) -> str:
    """使用者可看短表。"""
    lines: List[str] = [
        "# 外資恐懼鏈｜全量回測收斂裁決",
        "",
        f"- 時區：`{verdict.get('tz')}`；密窗起 `{verdict.get('dense_foreign_start')}`",
        f"- **不是買訊**；`buy_signal={verdict.get('buy_signal')}`",
        f"- {verdict.get('gate_one_liner')}",
        "",
        "| 軌 | 靜默 n | n≥20 | 離線 lift（主看） | 換編碼 |",
        "|---|---:|:---:|:---:|:---:|",
    ]
    off = verdict.get("offline") or {}
    live = verdict.get("live_gates") or {}
    labels = {
        "fear": "開盤前恐懼",
        "escalate": "小賣→大賣",
        "extreme": "極端大賣D+",
        "calm": "反向／小買",
    }
    for key, label in labels.items():
        g = live.get(key) or {}
        o = off.get(key) or {}
        n = int(g.get("n_days") or 0)
        n_ok = "是" if g.get("n_ok") else "否"
        if key == "escalate":
            lift = "n5 有／n3 無"
        elif key == "calm":
            lift = "弱／近平"
        elif key == "extreme":
            lift = "續極端有／價無"
        else:
            lift = "見備註"
        promo = "否" if not o.get("promote_encoding") else "是"
        if g.get("promote_observe_copy"):
            promo = "觀察文案可收"
        lines.append(f"| {label} | {n} | {n_ok} | {lift} | {promo} |")
    lines += [
        "",
        "## 硬邊界",
        "",
    ]
    for r in verdict.get("hard_rules") or []:
        lines.append(f"- {r}")
    lines.append("")
    return "\n".join(lines)


__all__ = [
    "DENSE_FOREIGN_START",
    "DEFAULT_ARTIFACT_ROOT",
    "OFFLINE_CONVERGE_20261025",
    "converge_verdict",
    "converge_md",
    "load_json",
]
