#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""因素不足／測試無果 → 記錄＋發想＋排程補抓重測（靜默）。

使用者鎖：
- 回測若發現已加入的判斷因素明顯不足、可能測了也無果 → 必須記錄。
- 發想任何可能有用的資訊（即使目前不在庫）。
- 準備適合時間加入／重抓，再重測用以獲取可沿用資料。

只落數字 json／gz；不准存圖；不是買訊；不上話筒。
"""
from __future__ import annotations

import gzip
import json
import os
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in __import__("sys").path:
    __import__("sys").path.insert(0, str(ROOT))

MARKET_DB = Path(os.environ.get("WAYNE_DB_PATH") or (ROOT / "data" / "wayne_market.db"))
LAB_DB = Path(os.environ.get("DECADE_LAB_DB") or (ROOT / "data" / "decade_lab.db"))
OUT_DIR = ROOT / "docs" / "expert_notes" / "飆客" / "decade_lab"
TAIPEI = ZoneInfo("Asia/Taipei")

# 方向準度低於此＝「明顯不足／可能無果」（仍可覆盤，但要發想補因）
FRUITLESS_HIT_RATE = 0.55
# 觀望／因素不足佔比高於此＝資訊不夠開刀
HIGH_NEUTRAL_FRAC = 0.55
MIN_SCORED = 20

DDL = """
CREATE TABLE IF NOT EXISTS factor_gap_queue (
    id TEXT NOT NULL PRIMARY KEY,
    written_at TEXT NOT NULL,
    source TEXT NOT NULL,
    fruitless INTEGER NOT NULL DEFAULT 0,
    reason_zh TEXT NOT NULL DEFAULT '',
    evidence_json TEXT NOT NULL DEFAULT '{}',
    ideas_json TEXT NOT NULL DEFAULT '[]',
    schedule_json TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'queued',
    last_fetch_at TEXT NOT NULL DEFAULT '',
    last_retest_at TEXT NOT NULL DEFAULT '',
    note_zh TEXT NOT NULL DEFAULT ''
);
"""


def _now() -> str:
    return datetime.now(TAIPEI).strftime("%Y-%m-%dT%H:%M:%S")


def _today() -> str:
    return datetime.now(TAIPEI).strftime("%Y%m%d")


def ensure_lab(conn: sqlite3.Connection) -> None:
    conn.executescript(DDL)


# —— 發想庫：投資人走勢／波浪覆盤可能用到、目前多半不在 FACTOR_PACK ——
IDEA_CATALOG: List[Dict[str, Any]] = [
    {
        "id": "margin_balance_long",
        "kind": "chips",
        "why_zh": "融資餘額長窗：過熱／殺融資常領先加權轉折",
        "store": "market_margin_daily（數字表）",
        "fetch": "MI_MARGN 官方續補",
        "best_window_taipei": "盤後 16:00–18:00；長史週末補",
    },
    {
        "id": "tape_adv_dec_long",
        "kind": "breadth",
        "why_zh": "漲跌家數／成交值分位：廣度背離＝單一權值騙線可歸因",
        "store": "market_tape_daily",
        "fetch": "FMTQIK 月檔 2006–2016 續補",
        "best_window_taipei": "盤後 15:30–17:00；長史週末",
    },
    {
        "id": "inst_buy_sell_daily",
        "kind": "flow",
        "why_zh": "外資／投信合計買賣超：資金面確認方向，錯了能歸因",
        "store": "三法／投信日表（張數，不准假成本）",
        "fetch": "TWSE T86／投信彙整（數字）",
        "best_window_taipei": "盤後 16:30–20:00",
    },
    {
        "id": "tx_oi_inst_long",
        "kind": "futures",
        "why_zh": "台指期法人 OI／未平倉：夜盤方向與隔日開盤落差可覆盤",
        "store": "futures_daily／OI 長史",
        "fetch": "TAIFEX 報表長史",
        "best_window_taipei": "盤後 15:30–17:30；夜盤後 05:00–06:30",
    },
    {
        "id": "te_futures_long",
        "kind": "futures",
        "why_zh": "電子期 TE：半導體鏈與 SOX／台積連動的台股端確認",
        "store": "futures TE 日 K",
        "fetch": "TAIFEX／Yahoo 補長史標來源",
        "best_window_taipei": "盤後；長史週末",
    },
    {
        "id": "fear_greed_daily",
        "kind": "sentiment",
        "why_zh": "恐懼貪婪極端：極端恐懼後反彈／貪婪後回吐可量化",
        "store": "fear_greed_daily（單欄數字）",
        "fetch": "CNN Fear&Greed 歷史（文字數字）",
        "best_window_taipei": "每日美盤後約 05:00–07:00",
    },
    {
        "id": "active_etf_flow",
        "kind": "flow",
        "why_zh": "主動 ETF／投信賣壓流：被動買盤外的主動殺盤",
        "store": "etf_flow_daily",
        "fetch": "公開 ETF 申贖／投信報告彙整",
        "best_window_taipei": "盤後或週五彙整",
    },
    {
        "id": "us10y_dxy_yen",
        "kind": "macro",
        "why_zh": "美債10年／日圓：流動性與套息，解釋「美股好台股不跟」",
        "store": "index_daily: US10Y, USDJPY",
        "fetch": "Yahoo ^TNX, USDJPY=X",
        "best_window_taipei": "美盤後 05:00–07:00；長史隨時",
    },
    {
        "id": "gold_copper",
        "kind": "macro",
        "why_zh": "金／銅：風險偏好與景氣代理，油匯之外的避險維度",
        "store": "index_daily: GOLD, COPPER",
        "fetch": "Yahoo GC=F, HG=F",
        "best_window_taipei": "美盤後；長史週末",
    },
    {
        "id": "otc_index",
        "kind": "breadth",
        "why_zh": "櫃買指數：中小型廣度，加權被權值綁架時可對質",
        "store": "index_daily: OTC",
        "fetch": "官方／Yahoo 櫃買",
        "best_window_taipei": "盤後 15:00–16:30",
    },
    {
        "id": "tsm_adr_premium",
        "kind": "lead",
        "why_zh": "2330 vs TSM ADR 溢價：隔日開盤預期與權值導向",
        "store": "日表兩欄價差％",
        "fetch": "既有 2330 官方柱＋TSM Yahoo",
        "best_window_taipei": "美收後～開盤前 06:00–08:50",
    },
    {
        "id": "tx_night_full",
        "kind": "futures",
        "why_zh": "台指夜盤完整長史：開盤跳空歸因；缺則夜盤票常空轉",
        "store": "futures night bars",
        "fetch": "既有 TX 夜盤管線續補缺年",
        "best_window_taipei": "日盤前 08:00–08:50；夜盤後 05:00",
    },
    {
        "id": "vix_term_vvix",
        "kind": "sentiment",
        "why_zh": "VIX 期限／VVIX：恐慌結構，不只現貨 VIX 一日漲跌",
        "store": "index_daily 附加欄或獨立表",
        "fetch": "CBOE／Yahoo 可取得者",
        "best_window_taipei": "美盤後",
    },
    {
        "id": "wave_fractal_mtf",
        "kind": "structure",
        "why_zh": "波浪子浪／多週期對齊：日線八循環不夠時的下一刀",
        "store": "decade_lab 對質列（數字），不准 PNG",
        "fetch": "用已存 TWII 柱重切規則（不必新抓）",
        "best_window_taipei": "任何離峰；優先週末批次",
    },
]


def _next_slots(now: Optional[datetime] = None) -> List[Dict[str, str]]:
    """依台北牆鐘排出最近可執行窗（抓數／重測）。"""
    now = now or datetime.now(TAIPEI)
    slots: List[Dict[str, str]] = []

    def add(day: datetime, hh: int, mm: int, kind: str, note: str) -> None:
        t = day.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if t <= now:
            return
        slots.append(
            {
                "at": t.strftime("%Y-%m-%dT%H:%M:%S"),
                "kind": kind,
                "note_zh": note,
            }
        )

    for d in range(0, 8):
        day = (now + timedelta(days=d)).replace(tzinfo=TAIPEI)
        wd = day.weekday()  # 0=Mon
        # 開市日假設 Mon–Fri；真正休市鍵另由排程判斷
        if wd < 5:
            add(day, 15, 40, "fetch_tw_official", "盤後：漲跌家數／融資／法人流")
            add(day, 16, 40, "fetch_futures_oi", "盤後：TX／TE／OI")
            add(day, 5, 30, "fetch_us_macro", "美盤後：美債／日圓／金銅／恐懼")
            add(day, 6, 30, "fetch_adr_premium", "早報前：TSM ADR 溢價")
            add(day, 22, 40, "retest_path", "夜窗：path_forecast 重測（有新柱才有意義）")
        if wd == 5:  # Sat
            add(day, 10, 0, "backfill_long", "週末長史補洞（margin／tape／TE）")
            add(day, 14, 0, "retest_wave_path", "週末：波浪＋走勢預測重測落檔")
    # 去重並只留最近 12 檔
    seen = set()
    out = []
    for s in sorted(slots, key=lambda x: x["at"]):
        key = (s["at"], s["kind"])
        if key in seen:
            continue
        seen.add(key)
        out.append(s)
        if len(out) >= 12:
            break
    return out


def _load_path_summary() -> Dict[str, Any]:
    p = OUT_DIR / "path_forecast_summary.json"
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _load_wave_summary() -> Dict[str, Any]:
    p = OUT_DIR / "wave8_dual_summary.json"
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _db_coverage() -> Dict[str, Any]:
    if not MARKET_DB.exists():
        return {"ok": False, "error": "missing_market_db"}
    conn = sqlite3.connect(str(MARKET_DB), timeout=30.0)
    try:
        out: Dict[str, Any] = {"ok": True, "symbols": {}}
        for sym in (
            "TWII",
            "IXIC",
            "SOX",
            "VIX",
            "DXY",
            "USDTWD",
            "BRENT",
            "TSM",
            "NVDA",
            "US10Y",
            "USDJPY",
            "GOLD",
            "COPPER",
            "OTC",
        ):
            row = conn.execute(
                "SELECT COUNT(*), MIN(date), MAX(date) FROM index_daily WHERE symbol=?",
                (sym,),
            ).fetchone()
            out["symbols"][sym] = {
                "n": int(row[0] or 0),
                "from": str(row[1] or ""),
                "to": str(row[2] or ""),
            }
        for table in ("market_margin_daily", "market_tape_daily", "futures_daily"):
            try:
                n = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                out[table] = int(n or 0)
            except sqlite3.Error:
                out[table] = None
        return out
    finally:
        conn.close()


def _path_lab_stats() -> Dict[str, Any]:
    if not LAB_DB.exists():
        return {}
    conn = sqlite3.connect(str(LAB_DB), timeout=30.0)
    try:
        ensure_lab(conn)
        try:
            n = conn.execute("SELECT COUNT(*) FROM path_forecast").fetchone()[0]
            insuf = conn.execute(
                "SELECT COUNT(*) FROM path_forecast WHERE verdict LIKE ?",
                ("%因素不足%",),
            ).fetchone()[0]
            watch = conn.execute(
                "SELECT COUNT(*) FROM path_forecast WHERE verdict LIKE ?",
                ("%觀望%",),
            ).fetchone()[0]
            empty_why = conn.execute(
                "SELECT COUNT(*) FROM path_forecast WHERE why_json IN ('[]','null','')"
            ).fetchone()[0]
        except sqlite3.Error:
            return {}
        return {
            "n": int(n or 0),
            "insufficient_n": int(insuf or 0),
            "watch_n": int(watch or 0),
            "empty_why_n": int(empty_why or 0),
        }
    finally:
        conn.close()


def diagnose_fruitless(
    path_summary: Optional[Dict[str, Any]] = None,
    wave_summary: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """判斷目前回測是否「因素明顯不足／可能無果」。"""
    path_summary = path_summary if path_summary is not None else _load_path_summary()
    wave_summary = wave_summary if wave_summary is not None else _load_wave_summary()
    lab = _path_lab_stats()
    cov = _db_coverage()

    reasons: List[str] = []
    evidence: Dict[str, Any] = {"path": {}, "wave": {}, "lab": lab, "coverage": cov}

    hr = path_summary.get("hit_rate_directional")
    dn = int(path_summary.get("directional_n") or 0)
    evidence["path"] = {
        "hit_rate_directional": hr,
        "directional_n": dn,
        "factor_pack": path_summary.get("factor_pack") or [],
    }
    if dn >= MIN_SCORED and hr is not None and float(hr) < FRUITLESS_HIT_RATE:
        reasons.append(
            f"走勢預測方向準度 {float(hr):.3f} < {FRUITLESS_HIT_RATE}（n={dn}）→ 現有因素包可能不夠／切法無果"
        )
    elif dn >= MIN_SCORED and hr is not None and float(hr) < 0.62:
        reasons.append(
            f"走勢預測方向準度 {float(hr):.3f} 仍偏弱（n={dn}）→ 記錄補因並排程重測"
        )

    if lab.get("n"):
        frac_insuf = lab["insufficient_n"] / max(1, lab["n"])
        frac_empty = lab["empty_why_n"] / max(1, lab["n"])
        evidence["lab_frac"] = {"insufficient": frac_insuf, "empty_why": frac_empty}
        if frac_insuf >= 0.05:
            reasons.append(f"因素不足不計分占比 {frac_insuf:.1%}")
        if frac_empty >= HIGH_NEUTRAL_FRAC:
            reasons.append(f"why 空包占比 {frac_empty:.1%} → 投票因素點不亮，覆盤無從歸因")

    # 覆蓋缺口：目錄有想要、庫裡幾乎沒有
    missing_syms = []
    if cov.get("ok"):
        for sym, meta in (cov.get("symbols") or {}).items():
            if int(meta.get("n") or 0) < 100 and sym not in {"TWII", "IXIC", "SOX", "VIX", "DXY", "USDTWD", "BRENT", "TSM", "NVDA"}:
                missing_syms.append(sym)
            if sym in {"US10Y", "USDJPY", "GOLD", "COPPER", "OTC"} and int(meta.get("n") or 0) < 100:
                missing_syms.append(sym)
        missing_syms = sorted(set(missing_syms))
        if missing_syms:
            reasons.append("庫內缺長史：" + ",".join(missing_syms))
        for t in ("market_margin_daily", "market_tape_daily"):
            n = cov.get(t)
            if n is not None and int(n) < 2000:
                reasons.append(f"{t} 列數偏少 n={n}（二十年窗應更厚）")

    w_tracks = (wave_summary or {}).get("tracks") or {}
    text = w_tracks.get("textbook_8cycle") or {}
    if text.get("n_decided", 0) >= MIN_SCORED and (text.get("hit_rate") or 0) < 0.60:
        reasons.append(
            f"波浪教科書準度 {(text.get('hit_rate') or 0):.3f} 仍低 → 結構因素／切法要再發想"
        )
    evidence["wave"] = {
        "adopt": (wave_summary or {}).get("adopt"),
        "textbook_hit": text.get("hit_rate"),
        "textbook_n": text.get("n_decided"),
    }

    fruitless = bool(reasons) and (
        (dn >= MIN_SCORED and hr is not None and float(hr) < 0.62)
        or bool(missing_syms)
        or (lab.get("n") and lab.get("empty_why_n", 0) / max(1, lab["n"]) >= HIGH_NEUTRAL_FRAC)
    )
    return {
        "fruitless": fruitless,
        "reasons": reasons,
        "evidence": evidence,
    }


def pick_ideas(diag: Dict[str, Any], *, limit: int = 12) -> List[Dict[str, Any]]:
    """依缺口證據挑發想項（有覆蓋的降權，缺的優先）。"""
    cov = (diag.get("evidence") or {}).get("coverage") or {}
    syms = cov.get("symbols") or {}
    picked: List[Dict[str, Any]] = []

    def have_sym(sym: str, min_n: int = 100) -> bool:
        return int((syms.get(sym) or {}).get("n") or 0) >= min_n

    for idea in IDEA_CATALOG:
        iid = idea["id"]
        skip = False
        if iid == "us10y_dxy_yen" and have_sym("US10Y") and have_sym("USDJPY"):
            skip = True
        if iid == "gold_copper" and have_sym("GOLD") and have_sym("COPPER"):
            skip = True
        if iid == "otc_index" and have_sym("OTC"):
            skip = True
        if iid == "margin_balance_long" and int(cov.get("market_margin_daily") or 0) >= 3000:
            skip = True
        if iid == "tape_adv_dec_long" and int(cov.get("market_tape_daily") or 0) >= 3000:
            skip = True
        if skip:
            continue
        picked.append(dict(idea))
        if len(picked) >= limit:
            break
    return picked


def record_gap(
    *,
    source: str = "path_forecast+wave8",
    path_summary: Optional[Dict[str, Any]] = None,
    wave_summary: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """診斷→記錄→發想→排程。無果才標 fruitless=1，但缺口一律落檔。"""
    diag = diagnose_fruitless(path_summary, wave_summary)
    ideas = pick_ideas(diag)
    schedule = _next_slots()
    rid = f"gap-{_today()}-{source.replace('+','_')}"
    rec = {
        "id": rid,
        "written_at": _now(),
        "tz": "Asia/Taipei",
        "source": source,
        "fruitless": bool(diag["fruitless"]),
        "reason_zh": "；".join(diag["reasons"]) or "尚無明顯無果訊號，仍記錄覆蓋與候補",
        "evidence": diag["evidence"],
        "ideas": ideas,
        "schedule": schedule,
        "status": "queued" if ideas else "idle",
        "actions_zh": [
            "缺序列→適合窗抓數字／gz（不准 PNG）",
            "抓完→重跑 path_forecast／wave8_dual／reusable_quant",
            "n≥20 且贏現況才換編碼；勝率分軌不混；不上話筒",
        ],
        "not_buy_signal": True,
        "phone_sync": "blocked",
    }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "factor_gap_queue_latest.json").write_text(
        json.dumps(rec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    # 追加歷史（gz）
    hist = OUT_DIR / "factor_gap_queue_history.jsonl.gz"
    with gzip.open(hist, "ab") as f:
        f.write((json.dumps(rec, ensure_ascii=False) + "\n").encode("utf-8"))

    lab = sqlite3.connect(str(LAB_DB), timeout=60.0)
    try:
        ensure_lab(lab)
        lab.execute(
            """
            INSERT INTO factor_gap_queue(
                id, written_at, source, fruitless, reason_zh,
                evidence_json, ideas_json, schedule_json, status, note_zh
            ) VALUES (?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(id) DO UPDATE SET
                written_at=excluded.written_at,
                fruitless=excluded.fruitless,
                reason_zh=excluded.reason_zh,
                evidence_json=excluded.evidence_json,
                ideas_json=excluded.ideas_json,
                schedule_json=excluded.schedule_json,
                status=excluded.status
            """,
            (
                rid,
                rec["written_at"],
                source,
                1 if rec["fruitless"] else 0,
                rec["reason_zh"],
                json.dumps(rec["evidence"], ensure_ascii=False),
                json.dumps(ideas, ensure_ascii=False),
                json.dumps(schedule, ensure_ascii=False),
                rec["status"],
                "因素不足→發想→排程重測",
            ),
        )
        lab.commit()
    finally:
        lab.close()

    md = [
        "# 因素缺口佇列（靜默）",
        "",
        f"寫入：`{rec['written_at']}`（Asia/Taipei）",
        f"- fruitless：`{rec['fruitless']}`",
        f"- 原因：{rec['reason_zh']}",
        f"- 發想 {len(ideas)} 條；最近排程 {len(schedule)} 檔",
        "",
        "## 發想（節錄）",
        "",
    ]
    for it in ideas[:8]:
        md.append(
            f"- `{it['id']}`｜{it['why_zh']}｜窗：{it.get('best_window_taipei','')}"
        )
    md.extend(["", "不是買訊。不上話筒。", ""])
    (OUT_DIR / "factor_gap_queue_latest.md").write_text("\n".join(md), encoding="utf-8")
    return rec


def due_now(schedule: Optional[Sequence[Dict[str, str]]] = None, *, within_min: int = 90) -> List[Dict[str, str]]:
    """回傳此刻±窗內該做的排程（給 cron／agent 接）。"""
    now = datetime.now(TAIPEI)
    sched = list(schedule) if schedule is not None else (_load_latest_schedule())
    out = []
    for s in sched:
        try:
            t = datetime.strptime(s["at"], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=TAIPEI)
        except (KeyError, ValueError):
            continue
        delta = (t - now).total_seconds() / 60.0
        if -15 <= delta <= within_min:
            out.append(dict(s))
    return out


def _load_latest_schedule() -> List[Dict[str, str]]:
    p = OUT_DIR / "factor_gap_queue_latest.json"
    if not p.exists():
        return _next_slots()
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        return list(d.get("schedule") or [])
    except (OSError, json.JSONDecodeError):
        return _next_slots()


def main() -> int:
    rec = record_gap()
    print(json.dumps({
        "id": rec["id"],
        "fruitless": rec["fruitless"],
        "ideas_n": len(rec["ideas"]),
        "schedule_n": len(rec["schedule"]),
        "reason_zh": rec["reason_zh"][:240],
        "due": due_now(rec["schedule"]),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
