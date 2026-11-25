# -*- coding: utf-8 -*-
"""preferred 路徑三態對質（靜默）｜觸位／守位／失效改口。

準度定義＝下一窗 preferred 路徑是否在三態對上官方已收柱：
- touch：高／低碰到他說過的目標位（或帶）
- hold：全日低／收仍在守位之上（或壓力之下，依角色）
- fail_retract：破了 → 應觸發改口／升權下一版鍵（對 miss 回寫）

硬邊界：Asia/Taipei；未收不當收；phone_sync=blocked；不是買訊；
不准發明未口述價；勝率不准混海選／黃金買點；§13 n≥20 且贏現況才換。
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
LAB = ROOT / "docs" / "expert_notes" / "飆客" / "decade_lab"
MANUAL = ROOT / "docs" / "expert_notes" / "飆客" / "observe_manual"
OUT_JSON = LAB / "wave_pref_path_confront_latest.json"
OUT_MD = LAB / "wave_pref_path_confront_latest.md"
TAIPEI = ZoneInfo("Asia/Taipei")

TRACK = "wave_pref_path_3state"
VARIANT_CURRENT = "pref_3state_v1_verdict_map"
VARIANT_NEXT = "pref_3state_v2_intraday_break_hold"
PHONE_SYNC = "blocked"
MIN_N = 20
PHONE_WARNING = "試標・推論／非他原文・非買訊・對質未過閘"

_VERDICT_OK = re.compile(r"成立|通過|完成|觸及|站上|收回|守住")
_VERDICT_FAIL = re.compile(r"否決|失敗|未觸|未收復|未再探|未在|未發生|遠低|遠高於目標下")
_VERDICT_PARTIAL = re.compile(r"部分|pending|靠近|升權觀察")


def _now() -> str:
    return datetime.now(TAIPEI).strftime("%Y-%m-%dT%H:%M:%S%z")


def _ymd(raw: Any) -> str:
    t = str(raw or "").replace("-", "")[:8]
    return t if len(t) == 8 and t.isdigit() else ""


def list_eod_paths(lab: Optional[Path] = None) -> List[Path]:
    base = lab or LAB
    return [
        p
        for p in sorted(base.glob("wave_eod_verify_20*.json"))
        if "latest" not in p.name and "preflight" not in p.name
    ]


def _path_by_id(paths: List[Dict[str, Any]], pid: str) -> Optional[Dict[str, Any]]:
    for row in paths or []:
        if str(row.get("id") or "") == pid:
            return row
    return None


def _classify_verdict(text: str) -> str:
    t = str(text or "").strip()
    if not t:
        return "unknown"
    # 否決／成立以句首為準（EOD 慣例：「成立：…」「否決：…」）
    if t.startswith("否決"):
        return "fail"
    if t.startswith("成立") or t.startswith("通過"):
        return "hit"
    if t.startswith("部分") or "pending" in t.lower():
        return "partial"
    if _VERDICT_OK.search(t) and "否決" not in t[:8]:
        return "hit"
    if _VERDICT_FAIL.search(t):
        return "fail"
    if _VERDICT_PARTIAL.search(t):
        return "partial"
    return "unknown"


def score_eod(data: Dict[str, Any], *, source: str = "") -> Dict[str, Any]:
    """對單一 EOD：preferred 三態分數。"""
    as_of = _ymd(data.get("as_of"))
    preferred = str(data.get("preferred_was") or "").strip()
    paths = list(data.get("paths") or [])
    pref_row = _path_by_id(paths, preferred) if preferred else None
    if pref_row is None and paths:
        # 無 preferred_was 時取第一條標優先者
        for row in paths:
            if "優先" in str(row.get("next_zh") or "") or row.get("priority") == 1:
                pref_row = row
                preferred = str(row.get("id") or "")
                break
        if pref_row is None:
            pref_row = paths[0]
            preferred = str(pref_row.get("id") or "")

    verdict = str((pref_row or {}).get("verdict") or data.get("preferred_outcome_zh") or "")
    state = _classify_verdict(verdict)

    # 三態欄位（觀測用）
    touch = state == "hit"
    # hold：FB／守位類成立也算 hold；fail 不算
    hold = state == "hit" and (
        "守" in verdict or "收回" in verdict or "站" in verdict or "成立" in verdict
    )
    fail_retract = state == "fail"
    # miss 有 rule_patch → 應有改口／下一版鍵
    miss = data.get("miss_analysis") if isinstance(data.get("miss_analysis"), dict) else {}
    has_retract_hook = bool(str(miss.get("rule_patch") or "").strip())

    # 計分：hit＝preferred 成立；fail＝否決；partial／unknown 不進 decided
    decided = state in ("hit", "fail")
    hit = state == "hit"

    return {
        "as_of": as_of,
        "preferred_id": preferred,
        "verdict_zh": verdict[:180],
        "state": state,
        "touch": bool(touch),
        "hold": bool(hold),
        "fail_retract": bool(fail_retract),
        "has_retract_hook": has_retract_hook,
        "decided": decided,
        "hit": hit if decided else None,
        "source_file": source,
        "buy_signal": False,
        "phone_sync": PHONE_SYNC,
        "not_buy_signal": True,
    }


def run_suite(lab: Optional[Path] = None) -> Dict[str, Any]:
    rows: List[Dict[str, Any]] = []
    for path in list_eod_paths(lab):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(data, dict):
            continue
        # 未收不當收
        bar = data.get("bar_status")
        if isinstance(bar, dict) and "未收" in str(bar.get("note_zh") or ""):
            continue
        if isinstance(bar, str) and "未收" in bar:
            continue
        if not data.get("official") and not data.get("paths"):
            continue
        try:
            rel = str(path.relative_to(ROOT))
        except ValueError:
            rel = str(path)
        rows.append(score_eod(data, source=rel))

    decided = [r for r in rows if r.get("decided")]
    hits = [r for r in decided if r.get("hit")]
    n = len(decided)
    hit_rate = (len(hits) / n) if n else None
    gate_n20 = n >= MIN_N
    # 現況＝v1；下一版尚未收集獨立勝率 → replace=False
    replace = False

    by_state: Dict[str, int] = {}
    for r in rows:
        k = str(r.get("state") or "unknown")
        by_state[k] = by_state.get(k, 0) + 1

    payload = {
        "written_at": _now(),
        "tz": "Asia/Taipei",
        "track": TRACK,
        "purpose_zh": "preferred 路徑三態對質：觸位／守位／失效改口（非買訊）",
        "phone_sync": PHONE_SYNC,
        "buy_signal": False,
        "not_buy_signal": True,
        "phone_warning_fixed": PHONE_WARNING,
        "mix_forbidden_zh": "勝率不准混進海選／黃金買點／洞燭",
        "current_variant": VARIANT_CURRENT,
        "next_variant": {
            "variant": VARIANT_NEXT,
            "note_zh": "1125 intraday_break→FB_hold 規則併入三態計分；收集中",
            "gate_zh": f"獨立交易日 n≥{MIN_N} 且贏現況才替換（§13）",
        },
        "gate": {
            "min_n": MIN_N,
            "n_decided": n,
            "n_rows": len(rows),
            "hit_rate": hit_rate,
            "gate_n20": gate_n20,
            "replace": replace,
            "WAVE_NEURONS_MATCH": False,
        },
        "state_counts": by_state,
        "rows": rows,
        "forbid_zh": [
            "不准當買訊",
            "不准發明未口述價／新①",
            "不准未收當收",
            "phone_sync=blocked 時不准定案浪號上話筒",
        ],
    }
    return payload


def write_outputs(payload: Dict[str, Any], *, root: Optional[Path] = None) -> Tuple[Path, Path]:
    lab = (root or ROOT) / "docs" / "expert_notes" / "飆客" / "decade_lab"
    lab.mkdir(parents=True, exist_ok=True)
    jp = lab / "wave_pref_path_confront_latest.json"
    mp = lab / "wave_pref_path_confront_latest.md"
    jp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    g = payload.get("gate") or {}
    lines = [
        "# preferred 路徑三態對質（靜默）",
        "",
        f"寫入：`{payload.get('written_at')}`（Asia/Taipei）。",
        f"軌：`{TRACK}`｜現況 `{VARIANT_CURRENT}`｜下一版 `{VARIANT_NEXT}`",
        "",
        f"- n_decided={g.get('n_decided')} hit_rate={g.get('hit_rate')} gate_n20={g.get('gate_n20')} replace={g.get('replace')}",
        f"- state_counts={payload.get('state_counts')}",
        f"- 警語：`{PHONE_WARNING}`",
        "",
        "不是買訊。不上話筒定案。WAVE_NEURONS_MATCH=false。",
        "",
        "## 列",
        "",
        "| as_of | preferred | state | hit |",
        "|---|---|---|---|",
    ]
    for r in payload.get("rows") or []:
        lines.append(
            f"| `{r.get('as_of')}` | `{r.get('preferred_id')}` | {r.get('state')} | {r.get('hit')} |"
        )
    mp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return jp, mp


def main() -> int:
    payload = run_suite()
    jp, mp = write_outputs(payload)
    g = payload["gate"]
    print(
        "GATE",
        f"pref_3state n={g['n_decided']} hit_rate={g['hit_rate']} "
        f"gate_n20={g['gate_n20']} replace={g['replace']} "
        f"next={VARIANT_NEXT} phone_sync=blocked buy_signal=0",
    )
    print("WROTE", jp.name, mp.name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
