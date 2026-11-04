#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""path 測法 integrity 離線重算（§13 下一鍵：修測法優先於堆指標）。

讀已落檔的 path_forecast_summary + scored jsonl，不重跑厚庫也能：
1. 用封印 OOS（holdout≥20）重算——不夠就明確 sealed_ok=false
2. 標 call_rate／range 稀釋／small amp／神經元
3. 產出機器可讀 next_gates；禁止把 dir 100% 當過關

不是買訊；phone_sync=blocked；不准改黃金買點／海選／洞燭。
"""
from __future__ import annotations

import gzip
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.decade_lab_path_forecast import (  # noqa: E402
    _next_gates,
    _oos_holdout,
    _sample_audit,
)

OUT_DIR = ROOT / "docs" / "expert_notes" / "飆客" / "decade_lab"
TAIPEI = ZoneInfo("Asia/Taipei")
VARIANT = "path_score_integrity_v1"
NEXT_VARIANT = "path_score_integrity_vnext_walkforward"


def _now() -> str:
    return datetime.now(TAIPEI).strftime("%Y-%m-%dT%H:%M:%S%z")


def _load_scored(path: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    with gzip.open(path, "rt", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def _by_amp_class(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for cls in ("micro", "small", "mid", "large"):
        sub = [r for r in rows if r.get("amp_class") == cls]
        h = sum(1 for r in sub if "幅度對得上" in str(r.get("amp_verdict") or ""))
        m = sum(1 for r in sub if "幅度偏了" in str(r.get("amp_verdict") or ""))
        n = h + m
        out[cls] = {
            "n": n,
            "hit": h,
            "miss": m,
            "hit_rate": (h / n) if n else None,
        }
    return out


def run_integrity(
    *,
    summary_path: Optional[Path] = None,
    scored_path: Optional[Path] = None,
) -> Dict[str, Any]:
    summary_path = summary_path or (OUT_DIR / "path_forecast_summary.json")
    scored_path = scored_path or (OUT_DIR / "path_forecast_scored_latest.jsonl.gz")
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    scored = _load_scored(scored_path)

    wrote = int(summary.get("wrote") or 0)
    range_n = int((summary.get("sample_audit") or {}).get("range_n") or 0)
    insuff_n = int((summary.get("sample_audit") or {}).get("insuff_n") or 0)
    soft_range_n = int((summary.get("sample_audit") or {}).get("soft_range_n") or 0)
    # 舊摘要沒計數時，用 wrote − scored 粗估 range（下限）
    if range_n <= 0 and wrote > 0:
        range_n = max(0, wrote - len(scored))

    dir_rows = [r for r in scored if r.get("bias") in {"up", "down"}]
    hit = sum(1 for r in dir_rows if "對得上" in str(r.get("verdict") or ""))
    miss = sum(1 for r in dir_rows if "偏了" in str(r.get("verdict") or ""))
    dir_n = hit + miss
    dir_hr = (hit / dir_n) if dir_n else None
    by_amp = _by_amp_class(scored)

    oos_sealed = _oos_holdout(scored, holdout_n=20, sealed=True)
    oos_legacy = _oos_holdout(scored, holdout_n=5, sealed=False)
    audit = _sample_audit(
        wrote=wrote or max(dir_n, 1),
        range_n=range_n,
        insuff_n=insuff_n,
        soft_range_n=soft_range_n,
        dir_n=dir_n,
        hit_rate=dir_hr,
        by_amp_class=by_amp,
        oos=oos_sealed,
    )
    next_gates = _next_gates(audit, oos_sealed)

    # 誠實對照：舊摘要 dir100 不能當現況勝率宣稱
    published_dir = summary.get("hit_rate_directional")
    honest = {
        "published_hit_rate_directional": published_dir,
        "published_scored_n": int(summary.get("scored_n") or dir_n),
        "forbid_claim_zh": "禁止宣稱方向 100%／已可上話筒；測法 integrity 未過",
        "call_rate": audit.get("call_rate"),
        "range_dilution": bool(audit.get("call_rate", 1) < 0.02 and dir_n < 50),
        "small_amp": by_amp.get("small"),
        "legacy_oos_holdout_n": int(oos_legacy.get("holdout_n") or 0),
        "sealed_oos_ok": bool(oos_sealed.get("sealed_ok")),
    }

    out: Dict[str, Any] = {
        "written_at": _now(),
        "tz": "Asia/Taipei",
        "track": VARIANT,
        "status": "collecting" if not audit.get("method_integrity_ok") else "integrity_pass_pending_neurons",
        "parent_summary": "path_forecast_summary.json",
        "scored_source": str(scored_path.relative_to(ROOT)),
        "problem_zh": (
            "現況測法：range 稀釋＋OOS 薄＋small amp 弱 → dir 滿是假漂亮；"
            "本鍵只修測法閘，不堆新指標、不改 bias"
        ),
        "hypothesis_zh": (
            "封印 OOS≥20＋call_rate／small amp 硬閘擋住灌水後，"
            "厚庫重跑才准談幅度／波浪下一槓桿"
        ),
        "directional_n": dir_n,
        "hit": hit,
        "miss": miss,
        "hit_rate_directional": dir_hr,
        "by_amp_class": by_amp,
        "oos_holdout": oos_sealed,
        "oos_holdout_legacy_unsealed": oos_legacy,
        "sample_audit": audit,
        "next_gates": next_gates,
        "honest_vs_published": honest,
        "gate_n20": dir_n >= 20,
        "gate_integrity": bool(audit.get("method_integrity_ok")),
        "replace": False,
        "replace_zh": "測法閘未過不准換 path 現況編碼；過閘後再生 walk-forward 票權鍵",
        "next_variant": {
            "variant": NEXT_VARIANT,
            "rule_zh": "edge 票權改 walk-forward（只用 as_of 以前過閘旗）；OOS 封印後只驗",
            "gate_zh": "n≥20 且 method_integrity_ok；small amp 不輸現況；不准改買訊",
            "status": "queued",
        },
        "aligned_user_goals": [
            "一／可回放判斷工場：as-of＋封印 OOS＝測法先對",
            "一／兩套驗證比準度：sealed vs legacy 雙列",
            "二／雙套驗證？／規則錯要重抓：本鍵答測法錯優先",
            "三／as-of 防前瞻·OOS·分軌：前瞻已修於 path；本鍵鎖 OOS",
        ],
        "not_buy_signal": True,
        "phone_sync": "blocked",
        "WAVE_NEURONS_MATCH": False,
        "note_zh": "厚庫重跑 scripts/decade_lab_path_forecast.py 後再跑本腳本覆寫本摘要",
    }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUT_DIR / "path_score_integrity_latest.json"
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # 同步把 summary 的 next_gates／封印 OOS 對照補上（不改 scored 列）
    summary = dict(summary)
    summary["oos_holdout"] = oos_sealed
    summary["oos_holdout_legacy_unsealed"] = oos_legacy
    summary["sample_audit"] = audit
    summary["next_gates"] = next_gates
    summary["gate_integrity"] = bool(audit.get("method_integrity_ok"))
    summary["path_score_integrity"] = {
        "track": VARIANT,
        "path": "path_score_integrity_latest.json",
        "gate_integrity": out["gate_integrity"],
        "written_at": out["written_at"],
    }
    summary["phone_sync"] = "blocked"
    summary["WAVE_NEURONS_MATCH"] = False
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return out


def main() -> int:
    out = run_integrity()
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if out.get("directional_n", 0) > 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
