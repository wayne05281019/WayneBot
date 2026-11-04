# -*- coding: utf-8 -*-
"""Path OOS 封印閘——立刻可跑（修測法錯優先於堆指標）。

讀既有 path_forecast_summary／scored gz，不算新因子。
seal_ok 未過 → 禁止把方向 100% 當成果。不是買訊。不上話筒。
§13 下一鍵：path_oos_seal_vnext（未贏不准換現況）。
"""
from __future__ import annotations

import gzip
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.decade_lab_path_forecast import OUT_DIR, _oos_seal_gate  # noqa: E402

SUMMARY = OUT_DIR / "path_forecast_summary.json"
SCORED_GZ = OUT_DIR / "path_forecast_scored_latest.jsonl.gz"
VNEXT = OUT_DIR / "path_oos_seal_vnext.json"
LATEST_JSON = OUT_DIR / "path_oos_seal_latest.json"
LATEST_MD = OUT_DIR / "path_oos_seal_latest.md"


def _load_scored() -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    if SCORED_GZ.is_file():
        with gzip.open(SCORED_GZ, "rt", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return rows


def _synthetic_from_summary(summary: Dict[str, Any]) -> List[Dict[str, Any]]:
    """無 scored gz 時用摘要 holdout_as_of＋占位列，只為算 seal 門檻（不虛構勝負）。"""
    n = int(summary.get("directional_n") or summary.get("scored_n") or 0)
    oos = summary.get("oos_holdout") or {}
    as_ofs = [str(x) for x in (oos.get("holdout_as_of") or []) if x]
    rows: List[Dict[str, Any]] = []
    # 用占位 as_of 填滿 n；verdict 中性，不進 hit 宣稱
    for i in range(max(0, n - len(as_ofs))):
        rows.append(
            {
                "as_of": f"synthetic_{i:04d}",
                "bias": "up" if i % 2 == 0 else "down",
                "verdict": "觀望占位不計真勝",
                "amp_verdict": "幅度占位",
            }
        )
    for j, d in enumerate(as_ofs):
        rows.append(
            {
                "as_of": d,
                "bias": "up" if j % 2 == 0 else "down",
                "verdict": "觀望占位不計真勝",
                "amp_verdict": "幅度占位",
            }
        )
    return rows


def run() -> Dict[str, Any]:
    summary: Dict[str, Any] = {}
    if SUMMARY.is_file():
        summary = json.loads(SUMMARY.read_text(encoding="utf-8"))
    scored = _load_scored()
    source = "scored_gz"
    if not scored:
        scored = _synthetic_from_summary(summary)
        source = "summary_synthetic_for_gate_only"
    seal = _oos_seal_gate(scored, min_holdout=20, frac=0.20)
    dir_hr = summary.get("hit_rate_directional")
    wrote = int(summary.get("wrote") or 0)
    dir_n = int(summary.get("directional_n") or seal.get("scored_n") or 0)
    call_rate = (dir_n / wrote) if wrote else None
    boast_blocked = bool(
        dir_hr == 1.0 or (isinstance(dir_hr, float) and abs(float(dir_hr) - 1.0) < 1e-9)
    )
    out = {
        "written_at": __import__("datetime").datetime.now(
            __import__("zoneinfo").ZoneInfo("Asia/Taipei")
        ).isoformat(timespec="seconds"),
        "tz": "Asia/Taipei",
        "track": "path_oos_seal",
        "source_rows": source,
        "parent_summary": str(SUMMARY.relative_to(ROOT)) if SUMMARY.is_file() else None,
        "summary_directional_n": dir_n,
        "summary_wrote": wrote,
        "summary_call_rate": round(call_rate, 6) if call_rate is not None else None,
        "summary_hit_rate_directional": dir_hr,
        "boast_dir_100_blocked": boast_blocked,
        "seal": seal,
        "gate_zh": (
            "過閘＝seal_ok 且 holdout_n≥20；規則封印後 holdout 只驗不調；"
            "禁止報方向100%；不是買訊；phone_sync=blocked"
        ),
        "replace_live": False,
        "not_buy_signal": True,
        "phone_sync": "blocked",
        "WAVE_NEURONS_MATCH": False,
        "next_key": "path_oos_seal_vnext",
        "aligned_mine_zh": "對 USER_ASKS_MINE B 測法／C OOS；修錯優先於堆指標",
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    LATEST_JSON.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    seal_ok = bool(seal.get("seal_ok"))
    md = "\n".join(
        [
            "# Path OOS 封印閘",
            "",
            f"寫入：`{out['written_at']}`（Asia/Taipei）。來源：{source}。",
            f"- seal_ok：**{seal_ok}**；holdout_n={seal.get('holdout_n')}；"
            f"scored_n={seal.get('scored_n')}；need≥{seal.get('need_scored_n')}",
            f"- 摘要 dir_n={dir_n}／wrote={wrote}／call_rate={out.get('summary_call_rate')}",
            f"- 方向命中（摘要）={dir_hr} → **不准當過關**（boast_blocked={boast_blocked}）",
            f"- 原因：{seal.get('reason_zh')}",
            "",
            "不是買訊。不上話筒。§13 下一鍵 `path_oos_seal_vnext`。",
            "",
        ]
    )
    LATEST_MD.write_text(md, encoding="utf-8")

    vnext = {
        "written_at": out["written_at"],
        "tz": "Asia/Taipei",
        "track": "path_oos_seal_vnext",
        "status": "collecting" if not seal_ok else "ready_to_compare",
        "parent": "path_forecast_summary.json",
        "problem_zh": "現況 OOS 最末5計分日＝假 holdout；n=24 不足以封印≥20",
        "hypothesis_zh": "厚庫重跑後 scored_n≥40，封印 holdout=max(20,ceil(n*0.2)) 且≤n/2；規則指紋後只驗",
        "gate_zh": (
            "seal_ok 且 holdout_n≥20；空名單不算；"
            "不准用 hit_rate_directional=1.0 宣稱贏；未過不准換現況編碼"
        ),
        "latest_seal_ok": seal_ok,
        "latest_scored_n": seal.get("scored_n"),
        "phone_sync": "blocked",
        "not_buy_signal": True,
        "WAVE_NEURONS_MATCH": False,
        "next_after_replace_zh": "過閘換封印邏輯為現況後立刻再生 path_oos_seal_vnext2（walk-forward 票權）",
    }
    VNEXT.write_text(json.dumps(vnext, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return out


def main() -> int:
    out = run()
    print(json.dumps(out, ensure_ascii=False, indent=2))
    # 腳本成功跑完＝0；seal 未過仍算測法閘有跑（exit 0），方便 CI
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
