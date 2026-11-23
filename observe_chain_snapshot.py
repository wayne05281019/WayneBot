# -*- coding: utf-8 -*-
"""三層觀測鏈・唯讀快照（BK-CHAIN）。

美股夜盤 e-mini → 台指早盤確認 → 加權現貨驗證＋費半連動。
只讀 us_overnight／futures_daily／index_daily；不寫海選、不改黃金買點。
試標・推論／非他原文・非買訊・對質未過閘。
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional

PLAYBOOK_PATH = (
    Path(__file__).resolve().parent
    / "docs"
    / "expert_notes"
    / "飆客"
    / "observe_manual"
    / "chain_playbook.json"
)

WARNING_ZH = "試標・推論／非他原文・非買訊・對質未過閘"
SCHEMA_DAY = "biaoke_observe_chain_day_v1"

# 手冊欄 ↔ 程式欄（對齊 chain_playbook.json field_map）
FIELD_MAP = {
    "sox_pct": "us_overnight.sox_pct",
    "nq_f_pct": "us_overnight.nq_f_pct",
    "es_f_pct": "us_overnight.payload.es_f_pct",
    "ixic_pct": "us_overnight.ixic_pct",
    "spx_pct": "us_overnight.spx_pct",
    "dji_pct": "us_overnight.dji_pct",
    "tx_night": "futures_daily(symbol=TX,session=night)",
    "te_night": "futures_daily(symbol=TE,session=night)",
    "tx_regular": "futures_daily(symbol=TX,session=regular)",
    "twii": "index_daily(symbol=TWII)",
}

GAPS = (
    "es_f_pct 無獨立欄（payload）",
    "早盤 15 分 minute_bars 常缺",
    "他點名位未自動灌勾選",
    "費半 1-4 無自動偵測",
    "尚無 pipeline_runs 鍵",
)


def _norm_ymd(raw: Any) -> str:
    s = str(raw or "").strip().replace("-", "")[:8]
    return s if len(s) == 8 and s.isdigit() else ""


def _f(val: Any) -> Optional[float]:
    if val is None or val == "":
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _bar(row: Optional[Dict[str, Any]], *, prefix: str = "") -> Optional[Dict[str, Any]]:
    if not row:
        return None
    out: Dict[str, Any] = {}
    for k in ("date", "open", "high", "low", "close", "volume", "pct_change", "session", "symbol"):
        if k not in row:
            continue
        v = row.get(k)
        if k in ("open", "high", "low", "close", "pct_change"):
            v = _f(v)
        elif k == "volume":
            try:
                v = int(v or 0)
            except (TypeError, ValueError):
                v = 0
        out[k if not prefix else f"{prefix}{k}"] = v
    return out or None


def load_playbook(path: Optional[Path] = None) -> Dict[str, Any]:
    p = Path(path) if path else PLAYBOOK_PATH
    if not p.is_file():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))


def playbook_checklist_ids(playbook: Optional[Dict[str, Any]] = None) -> List[str]:
    doc = playbook if playbook is not None else load_playbook()
    return [str(x.get("id") or "") for x in (doc.get("daily_checklist") or []) if x.get("id")]


def blank_day_sheet(*, as_of: str = "") -> Dict[str, Any]:
    """當日可勾選空殼（話筒／自測）。"""
    ymd = _norm_ymd(as_of)
    checks = {cid: {"status": "pending", "result": None, "note_zh": ""} for cid in playbook_checklist_ids()}
    return {
        "schema": SCHEMA_DAY,
        "tz": "Asia/Taipei",
        "track": "BK-CHAIN",
        "warning_zh": WARNING_ZH,
        "not_buy_signal": True,
        "buy_signal": False,
        "mix_into_biaoke_screen": False,
        "golden_buy_untouched": True,
        "as_of": ymd or None,
        "night_hypothesis": "pending",
        "layer2_verdict": "pending",
        "layer3_verdict": "pending",
        "sox_link_note": "",
        "checks": checks,
        "official": {
            "us_overnight": None,
            "tx_night": None,
            "te_night": None,
            "tx_regular": None,
            "twii": None,
        },
        "field_map": dict(FIELD_MAP),
        "gaps": list(GAPS),
        "rephrase_log": [],
        "note_zh": "空殼給話筒／自測填；不准假數；非買訊",
    }


def _load_us(db_path: str, as_of: str) -> Dict[str, Any]:
    if not db_path:
        return {}
    try:
        from us_overnight import load_us_overnight
    except Exception:
        return {}
    ymd = _norm_ymd(as_of)
    if ymd:
        snap = load_us_overnight(db_path, ymd) or {}
        if snap:
            return snap
    # 無指定日或該日空：最後一筆
    try:
        conn = sqlite3.connect(db_path, timeout=8.0)
        try:
            row = conn.execute(
                "SELECT as_of FROM us_overnight ORDER BY as_of DESC LIMIT 1"
            ).fetchone()
        finally:
            conn.close()
        if not row:
            return {}
        return load_us_overnight(db_path, str(row[0])) or {}
    except Exception:
        return {}


def _twii_bar(db_path: str, as_of: str) -> Optional[Dict[str, Any]]:
    if not db_path:
        return None
    ymd = _norm_ymd(as_of)
    try:
        conn = sqlite3.connect(db_path, timeout=8.0)
        try:
            if ymd:
                row = conn.execute(
                    """
                    SELECT date, open, high, low, close, volume, pct_change
                    FROM index_daily
                    WHERE symbol='TWII' AND replace(date,'-','')=?
                    """,
                    (ymd,),
                ).fetchone()
            else:
                row = conn.execute(
                    """
                    SELECT date, open, high, low, close, volume, pct_change
                    FROM index_daily
                    WHERE symbol='TWII'
                    ORDER BY date DESC LIMIT 1
                    """
                ).fetchone()
        finally:
            conn.close()
    except Exception:
        return None
    if not row:
        return None
    return {
        "date": str(row[0] or "").replace("-", "")[:8],
        "open": _f(row[1]),
        "high": _f(row[2]),
        "low": _f(row[3]),
        "close": _f(row[4]),
        "volume": int(row[5] or 0) if row[5] is not None else None,
        "pct_change": _f(row[6]),
        "symbol": "TWII",
    }


def _us_slice(snap: Dict[str, Any]) -> Dict[str, Any]:
    if not snap:
        return {}
    keys = (
        "as_of",
        "us_session",
        "regime",
        "sox_pct",
        "sox_chg",
        "soxx_post_pct",
        "nq_f_pct",
        "nq_f_chg",
        "nq_f_px",
        "es_f_pct",
        "es_f_chg",
        "es_f_px",
        "ym_f_pct",
        "ixic_pct",
        "spx_pct",
        "dji_pct",
        "tsm_pct",
        "tsm_post_pct",
        "nvda_pct",
        "nvda_post_pct",
        "vix",
    )
    out: Dict[str, Any] = {}
    for k in keys:
        if snap.get(k) is not None:
            out[k] = snap.get(k)
    out["es_f_source"] = "payload" if "es_f_pct" in out or "es_f_px" in out else "missing"
    return out


def load_chain_snapshot(
    db_path: str,
    as_of: Optional[str] = None,
    *,
    include_te: bool = True,
) -> Dict[str, Any]:
    """讀三層鏈當日官方欄。缺就標 gap，不准編假數。"""
    ymd = _norm_ymd(as_of)
    sheet = blank_day_sheet(as_of=ymd)

    us = _us_slice(_load_us(db_path, ymd))
    sheet["official"]["us_overnight"] = us or None

    tx_night = te_night = tx_reg = None
    try:
        from taiwan_market import load_futures_daily, load_futures_night

        tx_night = _bar(load_futures_night(db_path, ymd or None, symbol="TX"))
        if include_te:
            te_night = _bar(load_futures_night(db_path, ymd or None, symbol="TE"))
        tx_reg = _bar(load_futures_daily(db_path, ymd or None, symbol="TX"))
    except Exception:
        pass

    sheet["official"]["tx_night"] = tx_night
    sheet["official"]["te_night"] = te_night
    sheet["official"]["tx_regular"] = tx_reg
    sheet["official"]["twii"] = _twii_bar(db_path, ymd)

    # 勾選格：有數＝pending（等人／自測填結果）；無數＝gap
    def _mark(cid: str, present: bool) -> None:
        cell = sheet["checks"].setdefault(cid, {"status": "pending", "result": None, "note_zh": ""})
        if not present:
            cell["status"] = "gap"

    _mark("A1", us.get("sox_pct") is not None or us.get("soxx_post_pct") is not None)
    _mark("A2", us.get("es_f_pct") is not None)
    _mark("A3", us.get("nq_f_pct") is not None)
    _mark("A4", bool(tx_night and tx_night.get("close") is not None))
    _mark("A5", bool(te_night and te_night.get("close") is not None) if include_te else False)
    if not include_te:
        sheet["checks"]["A5"] = {"status": "skip", "result": "skip", "note_zh": "未讀 TE"}
    _mark("B1", bool(tx_reg and tx_reg.get("open") is not None))
    # B2 15 分常缺 → 有日盤高低則 gap_proxy_day
    if tx_reg and (tx_reg.get("high") is not None or tx_reg.get("low") is not None):
        sheet["checks"]["B2"] = {
            "status": "gap_proxy_day",
            "result": None,
            "note_zh": "minute_bars 未接；暫以日盤高低代理",
        }
    else:
        _mark("B2", False)
    sheet["checks"]["B3"]["status"] = "pending"
    tw = sheet["official"]["twii"] or {}
    _mark("C1", tw.get("close") is not None or tw.get("open") is not None)
    sheet["checks"]["C2"]["status"] = "gap"
    sheet["checks"]["C2"]["note_zh"] = "大量壓撐交 vol_zone／BK-WAVE"
    sheet["checks"]["C3"]["status"] = "no_active_band"
    sheet["checks"]["C3"]["note_zh"] = "點名帶需人工／WAVE 注入"
    if tw.get("close") is not None:
        sheet["checks"]["C4"] = {
            "status": "pending",
            "result": None,
            "note_zh": "有收才可戳；盤中未收不當收",
        }
    else:
        _mark("C4", False)
    for d in ("D1", "D2", "D3"):
        sheet["checks"][d]["status"] = "pending"

    sheet["snapshot_meta"] = {
        "warning_zh": WARNING_ZH,
        "helper": "observe_chain_snapshot.load_chain_snapshot",
        "gaps_static": list(GAPS),
        "es_f_source": us.get("es_f_source"),
    }
    return sheet


def sox_link_flags(us: Dict[str, Any], *, tx_night_bias: str = "") -> Dict[str, Any]:
    """費半連動粗標（試標）。bias: up/down/range/''。"""
    sox = _f(us.get("sox_pct"))
    if sox is None:
        sox = _f(us.get("soxx_post_pct"))
    es = _f(us.get("es_f_pct"))
    nq = _f(us.get("nq_f_pct"))
    out = {
        "warning_zh": WARNING_ZH,
        "not_buy_signal": True,
        "D1_fake_strength": False,
        "D2_internal_tape": False,
        "note_zh": "",
    }
    outer_weak = sox is not None and sox <= -1.0
    outer_ok = sox is not None and sox >= -0.3
    local_strong = tx_night_bias == "up" or (
        es is not None and es >= 0.3 and (nq is None or nq >= 0.2)
    )
    local_weak = tx_night_bias == "down" or (
        es is not None and es <= -0.3 and (nq is None or nq <= -0.2)
    )
    if outer_weak and local_strong:
        out["D1_fake_strength"] = True
        out["note_zh"] = "費半弱而外圍／夜偏強 → 假強警示（試標）"
    elif outer_ok and local_weak:
        out["D2_internal_tape"] = True
        out["note_zh"] = "費半尚穩而本地弱 → 偏內盤量價（試標）"
    return out
