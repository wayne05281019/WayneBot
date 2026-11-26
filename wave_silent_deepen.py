# -*- coding: utf-8 -*-
"""波浪靜默加深：連鎖日 preferred、次路徑校準、口述巢狀浪對照。

硬邊界：Asia/Taipei；未收不當收；phone_sync=blocked；不是買訊；
不准發明未口述價／新①；WAVE_NEURONS_MATCH=false；§13 未過閘不換現況／不上話筒定案。
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

import wave_cross_relation_mine as crm
import wave_pref_path_confront as pc
import wave_sox_tsmc_te_confront as stx

ROOT = Path(__file__).resolve().parent
LAB = ROOT / "docs" / "expert_notes" / "飆客" / "decade_lab"
OUT_JSON = LAB / "wave_silent_deepen_latest.json"
OUT_MD = LAB / "wave_silent_deepen_latest.md"
TAIPEI = ZoneInfo("Asia/Taipei")

TRACK = "wave_silent_deepen"
# §13：v3 仍收樣；同件再生下一版 v4（守位連鎖＋練畫對質）
VARIANT = "deepen_v3_cross_mine_2023"
NEXT_VARIANT = "deepen_v4_hold_chain_paint_2026"
PHONE_SYNC = "blocked"
PHONE_WARNING = "試標・推論／非他原文・非買訊・對質未過閘"
MIN_N = 20

# 他口述巢狀浪用語（材料庫；不准發明新①／不准當買訊）
_NESTED_ORAL = re.compile(
    r"(3-3\s*轉\s*3-4|3轉4|③\s*轉\s*④|3-3-3|3-3-4|3-3-5|"
    r"C3-3|C-3-3|C3-4|小級數|細微波|巢狀|嵌套)"
)
_COARSE_ORAL = re.compile(r"(大的?\s*[ABC]|一二三四五|第五波|第五段|大⑤|大④)")


def _now() -> str:
    return datetime.now(TAIPEI).strftime("%Y-%m-%dT%H:%M:%S%z")


def _ymd(raw: Any) -> str:
    t = str(raw or "").replace("-", "")[:8]
    return t if len(t) == 8 and t.isdigit() else ""


def load_eods(lab: Optional[Path] = None) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for path in pc.list_eod_paths(lab):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(data, dict):
            continue
        data["_source"] = path.name
        rows.append(data)
    rows.sort(key=lambda d: _ymd(d.get("as_of")))
    return rows


def score_secondary_paths(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """每個 path 的三態（不只 preferred）— 校準權重用。"""
    out: List[Dict[str, Any]] = []
    preferred = str(data.get("preferred_was") or "")
    for row in data.get("paths") or []:
        pid = str(row.get("id") or "")
        verdict = str(row.get("verdict") or "")
        state = pc._classify_verdict(verdict)
        out.append(
            {
                "id": pid,
                "state": state,
                "is_preferred": pid == preferred,
                "verdict_zh": verdict[:160],
            }
        )
    return out


def chain_consecutive(eods: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """相鄰交易日 preferred 結果連鎖（學「昨天成立 → 今天該升／降權」）。"""
    scored = [pc.score_eod(d, source=str(d.get("_source") or "")) for d in eods]
    chains: List[Dict[str, Any]] = []
    for i in range(1, len(scored)):
        prev, cur = scored[i - 1], scored[i]
        if not prev.get("decided") or not cur.get("as_of"):
            continue
        miss = {}
        for d in eods:
            if _ymd(d.get("as_of")) == cur.get("as_of"):
                miss = d.get("miss_analysis") if isinstance(d.get("miss_analysis"), dict) else {}
                break
        chains.append(
            {
                "from_as_of": prev.get("as_of"),
                "to_as_of": cur.get("as_of"),
                "from_preferred": prev.get("preferred_id"),
                "from_state": prev.get("state"),
                "from_hit": prev.get("hit"),
                "to_preferred": cur.get("preferred_id"),
                "to_state": cur.get("state"),
                "to_hit": cur.get("hit"),
                "miss_kind_hint_zh": str(miss.get("rule_patch") or "")[:180],
                "buy_signal": False,
                "phone_sync": PHONE_SYNC,
            }
        )
    return chains


def scan_nested_oral(db_path: str, *, limit: int = 40) -> Dict[str, Any]:
    """從他自己文掃巢狀／粗浪用語（材料；不上話筒定案）。"""
    path = str(db_path or "").strip()
    if not path or not Path(path).is_file():
        return {"ok": False, "reason": "no_db", "rows": []}
    conn = sqlite3.connect(path, timeout=15.0)
    rows_out: List[Dict[str, Any]] = []
    try:
        rows = conn.execute(
            """
            SELECT id, date, time, kind, text FROM biaoke_posts
            WHERE IFNULL(kind,'post') != 'bystander'
              AND IFNULL(text,'') != ''
              AND (
                text LIKE '%3-3%' OR text LIKE '%3轉4%' OR text LIKE '%細微波%'
                OR text LIKE '%小級數%' OR text LIKE '%第五波%' OR text LIKE '%C3-3%'
                OR text LIKE '%C-3-3%' OR text LIKE '%巢%'
              )
            ORDER BY date DESC, time DESC
            LIMIT ?
            """,
            (int(limit),),
        ).fetchall()
    except sqlite3.Error:
        return {"ok": False, "reason": "sql", "rows": []}
    finally:
        conn.close()
    nested_n = coarse_n = 0
    for pid, day, hm, kind, text in rows:
        blob = str(text or "")
        nested = bool(_NESTED_ORAL.search(blob))
        coarse = bool(_COARSE_ORAL.search(blob))
        if nested:
            nested_n += 1
        if coarse:
            coarse_n += 1
        if not (nested or coarse):
            continue
        snip = re.sub(r"\s+", " ", blob).strip()[:160]
        rows_out.append(
            {
                "post_id": str(pid or ""),
                "date": str(day or ""),
                "time": str(hm or ""),
                "kind": str(kind or "post"),
                "nested_oral": nested,
                "coarse_oral": coarse,
                "snip_zh": snip,
            }
        )
    return {
        "ok": True,
        "n_rows": len(rows_out),
        "n_nested_flag": nested_n,
        "n_coarse_flag": coarse_n,
        "note_zh": (
            "巢狀（3-3轉3-4／細微波）與粗浪（大段／第五波）並存於他文；"
            "對質時兩層都記，不准只留粗③→④就把巢狀抹掉；"
            "現在仍 WAVE_NEURONS_MATCH=false，不准發明①～⑤上話筒。"
        ),
        "rows": rows_out[:25],
        "buy_signal": False,
        "phone_sync": PHONE_SYNC,
    }


def _latest_forward() -> Dict[str, Any]:
    """讀最新 forward infer（優先 latest，再掃日期檔）。"""
    for path in (
        LAB / "wave_forward_infer_latest.json",
        LAB / "wave_forward_infer_20261127.json",
        LAB / "wave_forward_infer_20261126.json",
    ):
        if path.is_file():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if isinstance(data, dict) and data:
                return data
    return {}


def build_next_preflight(forward: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """下一開市日預檢：只列已口述位與 preferred；未收不當收。"""
    fwd = forward if isinstance(forward, dict) else _latest_forward()
    pref = str((fwd or {}).get("preferred_infer") or "FB_hold_above_37837")
    as_of = str((fwd or {}).get("infer_for") or "").strip() or "20261127"
    return {
        "as_of": as_of,
        "written_at": _now(),
        "tz": "Asia/Taipei",
        "phone_sync": PHONE_SYNC,
        "buy_signal": False,
        "not_buy_signal": True,
        "bar_status": "pre_open_pending_official",
        "note_zh": "未收不當收；開市後對官方柱再蓋 EOD。不准發明新①。",
        "preferred_infer": pref,
        "from_as_of_day": str((fwd or {}).get("as_of_day") or ""),
        "watch_levels": {
            "hold_37837": 37837.05,
            "ref_37164": 37164.0,
            "target_350_355": [35000.0, 35500.0],
            "wave4_band": [41800.0, 42700.0],
            "wave4_mid": 42250.0,
            "cross_zh": "費半已收／台積2330／電子夜盤 TE 只對照，不准發明浪號",
        },
        "checks_zh": [
            "preferred＝FB_hold：收是否仍＞37837（盤中失守要記 partial）",
            "再失 37837 → 升權 M3／35000～35500",
            "W4 41800～42700 僅強勢再觸才升權",
            "交叉：費半已收→台股日；2330／TWII 日盤；TE night 電子夜盤確認鏈",
            "練畫：遠窗／結構只對他點過的位，WAVE_NEURONS_MATCH=false",
        ],
        "phone_warning_fixed": PHONE_WARNING,
        "WAVE_NEURONS_MATCH": False,
        "next_variant": NEXT_VARIANT,
    }


def build_1126_preflight(forward: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """相容舊測：固定讀 1126 forward；新碼請用 build_next_preflight。"""
    path = LAB / "wave_forward_infer_20261126.json"
    fwd = forward
    if fwd is None and path.is_file():
        try:
            fwd = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            fwd = None
    pre = build_next_preflight(fwd if isinstance(fwd, dict) else None)
    # 舊契約：as_of 仍標 1126（該日開市前預檢檔）
    pre["as_of"] = "20261126"
    if not pre.get("preferred_infer"):
        pre["preferred_infer"] = "FB_hold_above_37837"
    return pre


def run_paint_practice(*, db_path: str = "", panels: str = "far") -> Dict[str, Any]:
    """靜默練畫：本機渲遠窗／試畫結構，對官方柱；不上話筒、非買訊。"""
    out: Dict[str, Any] = {
        "ok": False,
        "panels": str(panels or "far"),
        "paths": [],
        "note_zh": "",
        "buy_signal": False,
        "phone_sync": PHONE_SYNC,
        "WAVE_NEURONS_MATCH": False,
    }
    # pytest 預設略過真渲（太慢）；設 WAYNE_WAVE_PAINT_PRACTICE=1 才在測中真畫
    if os.getenv("PYTEST_CURRENT_TEST") and os.getenv("WAYNE_WAVE_PAINT_PRACTICE") != "1":
        out["note_zh"] = "pytest 略過真渲（設 WAYNE_WAVE_PAINT_PRACTICE=1 才練畫）"
        out["skipped"] = "pytest"
        return out
    if os.getenv("WAYNE_WAVE_PAINT_PRACTICE", "1").strip() in {"0", "false", "no"}:
        out["note_zh"] = "WAYNE_WAVE_PAINT_PRACTICE 關閉，略過練畫"
        out["skipped"] = "env"
        return out
    db = str(db_path or "").strip()
    if not db:
        try:
            from config import get_db_path

            db = str(get_db_path() or "")
        except Exception:
            db = str(ROOT / "data" / "wayne_market.db")
    if not db or not Path(db).is_file():
        out["note_zh"] = "無行情庫，略過練畫"
        return out
    try:
        from biaoke_level_learn import paint_open_day_hypothesis

        painted = paint_open_day_hypothesis(
            db, force=True, panels=str(panels or "far")
        )
    except Exception as exc:
        out["note_zh"] = f"練畫失敗：{type(exc).__name__}"
        return out
    paths: List[str] = []
    if isinstance(painted, dict):
        for key in (
            "far_path",
            "near_path",
            "micro_path",
            "path",
            "tx60_path",
            "oral_path",
            "out_path",
        ):
            val = painted.get(key)
            if isinstance(val, str) and val.strip():
                paths.append(val.strip())
        for key in ("far", "near", "micro", "paths", "kit"):
            val = painted.get(key)
            if isinstance(val, dict):
                for vv in val.values():
                    if isinstance(vv, str) and vv.strip():
                        paths.append(vv.strip())
            elif isinstance(val, list):
                for vv in val:
                    if isinstance(vv, str) and vv.strip():
                        paths.append(vv.strip())
        # 去重保序
        paths = list(dict.fromkeys(paths))
    out["ok"] = bool(paths) or bool(
        isinstance(painted, dict) and painted.get("ok")
    )
    out["paths"] = paths[:8]
    out["as_of"] = str((painted or {}).get("as_of") or "") if isinstance(painted, dict) else ""
    out["slot_id"] = str((painted or {}).get("slot_id") or "") if isinstance(painted, dict) else ""
    out["paint_keys"] = sorted(list(painted.keys()))[:24] if isinstance(painted, dict) else []
    out["note_zh"] = (
        "靜默練畫完成（只對他點過的位；WAVE_NEURONS_MATCH=false；非買訊）"
        if out["ok"]
        else "練畫未產出圖檔（可能缺柱／逾時）；繼續收樣"
    )
    return out


def run_deepen(*, db_path: str = "") -> Dict[str, Any]:
    eods = load_eods()
    pref_suite = pc.run_suite()
    secondary: List[Dict[str, Any]] = []
    for d in eods:
        secondary.append(
            {
                "as_of": _ymd(d.get("as_of")),
                "paths": score_secondary_paths(d),
            }
        )
    chains = chain_consecutive(eods)
    # 連鎖標籤（材料；繼續收樣，未過閘不換現況）
    chain_tags = []
    for ch in chains:
        if ch.get("from_as_of") == "20261124" and ch.get("to_as_of") == "20261125":
            chain_tags.append(
                {
                    "id": "gap_reclaim_then_intraday_break",
                    "zh": (
                        "1124 FB 跳空收回成立 → 1125 preferred W4 否決且盤中失 37837 收站回；"
                        "下一窗改 FB_hold（已回寫 v4）。繼續收樣，未過閘不換現況。"
                    ),
                }
            )
        if ch.get("from_as_of") == "20261125" and ch.get("to_as_of") == "20261126":
            chain_tags.append(
                {
                    "id": "intraday_break_then_hold_pass",
                    "zh": (
                        "1125 W4 否決／盤中失 37837 收站回 → 1126 preferred FB_hold 通過"
                        "（全日 L／C 皆＞37837）。準度樣本＋1；下一窗續 FB_hold。"
                        "v4 候選＝守位連鎖＋練畫對質；n≥20 且贏現況才換。"
                    ),
                }
            )
    db = db_path
    if not db:
        try:
            from config import get_db_path

            db = str(get_db_path() or "")
        except Exception:
            db = str(ROOT / "data" / "wayne_market.db")
    nested = scan_nested_oral(db)
    # 2023起聯動×位階挖礦 → 波浪強化候選（仍 blocked）
    mine = crm.run_suite(db, since_ymd="20230101", write_daily=True)
    crm.write_outputs(mine)
    cross = stx.run_suite(db, since_ymd="20230101", run_mine=False)
    stx.write_outputs(cross)
    dig = ((mine.get("mine") or {}).get("dig_worth") or [])
    hints = list(mine.get("wave_strengthen_hints") or [])
    paint = run_paint_practice(db_path=db, panels="far")
    g = pref_suite.get("gate") or {}
    payload = {
        "written_at": _now(),
        "tz": "Asia/Taipei",
        "track": TRACK,
        "variant": VARIANT,
        "next_variant": NEXT_VARIANT,
        "purpose_zh": (
            "靜默加深：連鎖日＋次路徑＋巢狀口述＋2023聯動位階挖礦＋練畫（非買訊）"
        ),
        "phone_sync": PHONE_SYNC,
        "buy_signal": False,
        "not_buy_signal": True,
        "phone_warning_fixed": PHONE_WARNING,
        "WAVE_NEURONS_MATCH": False,
        "gate": {
            "min_n": MIN_N,
            "pref_n_decided": g.get("n_decided"),
            "pref_hit_rate": g.get("hit_rate"),
            "gate_n20": g.get("gate_n20"),
            "replace": False,
            "n_chains": len(chains),
            "n_dig_worth": len(dig),
            "paint_ok": bool(paint.get("ok")),
        },
        "pref_suite_ref": {
            "current_variant": pref_suite.get("current_variant"),
            "next_variant": (pref_suite.get("next_variant") or {}).get("variant"),
            "state_counts": pref_suite.get("state_counts"),
        },
        "chains": chains,
        "chain_tags": chain_tags,
        "secondary_paths": secondary,
        "nested_oral": nested,
        "paint_practice": paint,
        "cross_mine": {
            "variant": mine.get("variant"),
            "n_dig_worth": len(dig),
            "dig_ids": [d.get("id") for d in dig[:12]],
            "dig_worth": dig[:8],
            "wave_strengthen_hints": hints,
            "coverage": mine.get("coverage"),
        },
        "sox_tsmc_te_ref": {
            "variant": cross.get("variant"),
            "gate": cross.get("gate"),
            "flag_counts": cross.get("flag_counts"),
        },
        "forbid_zh": [
            "不准當買訊",
            "不准發明未口述價／新①",
            "不准未收當收",
            "phone_sync=blocked 時不准定案浪號上話筒",
            "勝率不准混海選／黃金買點",
            "dig_worth 未過閘不准直接改 preferred",
            "練畫不上話筒；WAVE_NEURONS_MATCH=false",
        ],
    }
    return payload


def write_outputs(payload: Dict[str, Any]) -> Tuple[Path, Path, Path]:
    LAB.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    g = payload.get("gate") or {}
    lines = [
        "# 波浪靜默加深",
        "",
        f"寫入：`{payload.get('written_at')}`（Asia/Taipei）。",
        f"軌：`{TRACK}`／`{VARIANT}`｜下一版 `{payload.get('next_variant') or NEXT_VARIANT}`"
        f"｜phone_sync=blocked｜非買訊",
        "",
        f"- pref n={g.get('pref_n_decided')} hit_rate={g.get('pref_hit_rate')} "
        f"gate_n20={g.get('gate_n20')} replace={g.get('replace')} chains={g.get('n_chains')} "
        f"paint_ok={g.get('paint_ok')}",
        f"- 警語：`{PHONE_WARNING}`",
        "",
        "## 連鎖",
        "",
    ]
    for ch in payload.get("chains") or []:
        lines.append(
            f"- `{ch.get('from_as_of')}` {ch.get('from_preferred')}={ch.get('from_state')} "
            f"→ `{ch.get('to_as_of')}` {ch.get('to_preferred')}={ch.get('to_state')}"
        )
    for tag in payload.get("chain_tags") or []:
        lines.append(f"- tag `{tag.get('id')}`：{tag.get('zh')}")
    nest = payload.get("nested_oral") or {}
    cm = payload.get("cross_mine") or {}
    paint = payload.get("paint_practice") or {}
    lines += [
        "",
        "## 巢狀口述",
        "",
        f"- nested_flag={nest.get('n_nested_flag')} coarse_flag={nest.get('n_coarse_flag')} "
        f"n_rows={nest.get('n_rows')}",
        f"- {nest.get('note_zh')}",
        "",
        "## 靜默練畫",
        "",
        f"- ok={paint.get('ok')} panels={paint.get('panels')} "
        f"paths_n={len(paint.get('paths') or [])}",
        f"- {paint.get('note_zh')}",
        "",
        "## 2023聯動×位階挖礦",
        "",
        f"- dig_worth={cm.get('n_dig_worth')} ids={cm.get('dig_ids')}",
    ]
    for h in cm.get("wave_strengthen_hints") or []:
        lines.append(f"- hint `{h.get('next_track')}` ← `{h.get('from_hyp')}`")
    lines += [
        "",
        "WAVE_NEURONS_MATCH=false。不上話筒定案。",
        "",
    ]
    OUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    pre = build_next_preflight()
    preflight_path = LAB / f"wave_intraday_preflight_{pre.get('as_of')}.json"
    preflight_path.write_text(
        json.dumps(pre, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    # refresh pref confront artifacts too
    pref = pc.run_suite()
    pc.write_outputs(pref)
    return OUT_JSON, OUT_MD, preflight_path


def main() -> int:
    payload = run_deepen()
    jp, mp, pf = write_outputs(payload)
    g = payload["gate"]
    print(
        "GATE",
        f"deepen pref_n={g.get('pref_n_decided')} hit={g.get('pref_hit_rate')} "
        f"gate_n20={g.get('gate_n20')} chains={g.get('n_chains')} "
        f"replace=0 phone_sync=blocked buy_signal=0",
    )
    print("WROTE", jp.name, mp.name, pf.name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
