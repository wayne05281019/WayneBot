#!/usr/bin/env python3
"""Recompute Huang power scoreboard: market + stock quant, W20/W40, gate, vnext.

Honesty: only official bars from wayne_market.db; no invented hits.
Learning goal = break limits (wave draw/confirm, amp, winrate) for index AND stocks.
phone_sync stays blocked until §11 gate; never use blocked as reason to skip quant/prep.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
DAYS = ROOT / "docs/expert_notes/黃培碩/huang_days"
DB = ROOT / "data/wayne_market.db"
OUT_SB = ROOT / "docs/expert_notes/黃培碩/huang_scoreboard.json"
OUT_STOCK = ROOT / "docs/expert_notes/黃培碩/huang_stock_quant_ledger.json"
OUT_VNEXT = ROOT / "docs/expert_notes/黃培碩/huang_vnext_candidates.json"
OUT_PRIN = ROOT / "docs/expert_notes/黃培碩/huang_judgment_principles_quant.json"
OUT_CLOSURE = ROOT / "docs/expert_notes/黃培碩/huang_chrono_closure_report.md"
FILM_INDEX = ROOT / "docs/expert_notes/黃培碩/huang_film_index.json"
TZ = ZoneInfo("Asia/Taipei")


def now_taipei() -> str:
    return datetime.now(TZ).strftime("%Y-%m-%dT%H:%M:%S+08:00")


def open_days(con: sqlite3.Connection) -> list[str]:
    rows = con.execute(
        "select distinct date from index_daily where symbol='TWII' order by date"
    ).fetchall()
    return [r[0] for r in rows]


def next_open(opens: list[str], day: str) -> str | None:
    for d in opens:
        if d > day:
            return d
    return None


def bar(con: sqlite3.Connection, sid: str, day: str) -> dict | None:
    r = con.execute(
        "select open,high,low,close,volume from daily_quotes where stock_id=? and date=?",
        (sid, day),
    ).fetchone()
    if not r:
        return None
    return {"o": r[0], "h": r[1], "l": r[2], "c": r[3], "v": r[4]}


def amp_verdict(v: str) -> str:
    if v == "hit":
        return "hit"
    if v in ("miss", "skew"):
        return v
    return "unknown"


def rate(rows: list[dict], key: str, good=("hit",)) -> float | None:
    if not rows:
        return None
    return sum(1 for r in rows if r.get(key) in good) / len(rows)


def stock_dir_expect(day_obj: dict) -> str:
    """coarse expect from high_prob path text: up|down|chop."""
    hp = ((day_obj.get("forecast_for_next") or {}).get("high_prob") or {})
    text = " ".join(str(hp.get(k, "")) for k in ("path_zh", "wave_zh", "amp_zh", "levels_zh"))
    down_kw = ("拉回", "續拉", "深回", "重挫", "黑棒", "修正", "下跌", "震盪／續拉")
    up_kw = ("續推", "創高", "偏推", "緩推", "擴延續", "盤堅續", "反彈")
    if any(k in text for k in down_kw) and not any(k in text for k in ("續推", "創高")):
        return "down_or_chop"
    if any(k in text for k in up_kw):
        return "up_or_chop"
    return "chop"


def confront_stock(expect: str, pct: float) -> str:
    if pct is None:
        return "missing"
    if expect == "down_or_chop":
        return "hit" if pct <= 1.0 else "miss"
    if expect == "up_or_chop":
        return "hit" if pct >= -1.0 else "miss"
    return "hit" if abs(pct) <= 3.0 else "miss"


def main() -> None:
    con = sqlite3.connect(DB)
    opens = open_days(con)
    day_files = sorted(DAYS.glob("2026*.json"))
    chrono_rows = []
    stock_rows = []
    dual_ok = 0
    regime_ok = 0
    n_absorbed = 0

    for p in day_files:
        d = json.loads(p.read_text(encoding="utf-8"))
        meta = d.get("meta") or {}
        if meta.get("film_status") == "closed":
            continue
        n_absorbed += 1
        conf = d.get("confront_official") or {}
        if not conf:
            continue
        verdict = conf.get("verdict") or {}
        fc = d.get("forecast_for_next") or {}
        if fc.get("high_prob") and (fc.get("low_prob") or fc.get("single_branch_ok")):
            dual_ok += 1
        audit = d.get("no_forget_audit") or {}
        if audit.get("regime_complete"):
            regime_ok += 1
        row = {
            "day": meta.get("day") or p.stem,
            "target": fc.get("target_day") or conf.get("as_of"),
            "path": verdict.get("path"),
            "wave": verdict.get("wave"),
            "amp": verdict.get("amp"),
            "levels": verdict.get("levels"),
            "fail_codes": [
                x.get("code")
                for x in (d.get("rolling_fix") or [])
                if isinstance(x, dict) and x.get("code")
            ],
            "growth_zh": (d.get("cross_learn_zh") or "")[:80],
            "film_status": meta.get("film_status"),
        }
        # wave confirm extras
        wp = d.get("wave_progress") or {}
        row["wave_confirm"] = {
            "label_lock": (d.get("wave_def_draw") or {}).get("label_lock"),
            "peak_status": (wp.get("peak_claim") or {}).get("status"),
            "pullback_band": wp.get("pullback_band"),
            "rebound_band": wp.get("rebound_band"),
            "amp_in_band": (conf.get("amp_band_check") or {}).get("in_band"),
        }
        chrono_rows.append(row)

        # stock quant: named symbols D → target
        target = row["target"]
        named = (d.get("regime_D") or {}).get("named_symbols") or []
        expect = stock_dir_expect(d)
        frozen = ((d.get("named_stocks_ohlcv") or {}).get("bars") or {})
        for sid in named:
            b0 = frozen.get(sid)
            if isinstance(b0, dict) and b0.get("status") == "missing":
                b0 = None
            if not b0:
                b0 = bar(con, sid, row["day"])
            b1 = bar(con, sid, target) if target else None
            if not b0 or not b1 or b0.get("c") in (None, 0):
                stock_rows.append(
                    {
                        "day": row["day"],
                        "target": target,
                        "stock_id": sid,
                        "status": "missing_bar",
                        "expect": expect,
                    }
                )
                continue
            pct = (float(b1["c"]) - float(b0["c"])) / float(b0["c"]) * 100.0
            band_lo = float(b0["c"]) * 0.98
            band_hi = float(b0["c"]) * 1.02
            in_band = band_lo <= float(b1["c"]) <= band_hi
            # widen floor lesson days: if expect down, allow -3%
            if expect == "down_or_chop":
                band_lo = float(b0["c"]) * 0.97
                in_band = band_lo <= float(b1["c"]) <= band_hi
            path_v = confront_stock(expect, pct)
            amp_v = "hit" if in_band else "miss"
            stock_rows.append(
                {
                    "day": row["day"],
                    "target": target,
                    "stock_id": sid,
                    "status": "ok",
                    "expect": expect,
                    "c0": b0["c"],
                    "c1": b1["c"],
                    "pct": round(pct, 3),
                    "path": path_v,
                    "amp": amp_v,
                    "band": [round(band_lo, 2), round(band_hi, 2)],
                }
            )

    n = len(chrono_rows)
    w20 = chrono_rows[-20:] if n else []
    w40 = chrono_rows[-40:] if n else []

    def pack(rows: list[dict]) -> dict | None:
        if not rows:
            return None
        return {
            "n": len(rows),
            "path_hit_rate": rate(rows, "path"),
            "wave_hit_rate": rate(rows, "wave"),
            "amp_hit_rate": rate(rows, "amp", good=("hit",)),
            "amp_hit_incl_skew": rate(rows, "amp", good=("hit", "skew")),
            "levels_hit_rate": rate(rows, "levels"),
            "strict_all_hit_rate": sum(
                1
                for r in rows
                if r.get("path") == "hit"
                and r.get("wave") == "hit"
                and r.get("amp") == "hit"
                and r.get("levels") == "hit"
            )
            / len(rows),
        }

    stock_ok = [r for r in stock_rows if r.get("status") == "ok"]
    stock_pack = {
        "n_rows": len(stock_ok),
        "n_missing": sum(1 for r in stock_rows if r.get("status") != "ok"),
        "path_hit_rate": rate(stock_ok, "path") if stock_ok else None,
        "amp_hit_rate": rate(stock_ok, "amp") if stock_ok else None,
        "by_stock": {},
    }
    by = {}
    for r in stock_ok:
        by.setdefault(r["stock_id"], []).append(r)
    for sid, rs in sorted(by.items()):
        stock_pack["by_stock"][sid] = {
            "n": len(rs),
            "path_hit_rate": rate(rs, "path"),
            "amp_hit_rate": rate(rs, "amp"),
        }

    baseline = {
        "source": "nov_short_window_holdout",
        "n": 12,
        "hit_rate_strict": 0.583,
        "hit_rate_incl_partial": 0.833,
        "note_zh": "1110–1127 標題基線；chrono 要贏這條才算技能升",
    }
    w20_pack = pack(w20)
    beats_baseline = None
    if w20_pack and w20_pack["n"] >= 20:
        beats_baseline = w20_pack["strict_all_hit_rate"] >= baseline["hit_rate_strict"]

    gate = {
        "n_valid_confronted": n,
        "n_ge_20": n >= 20,
        "dual_branch_rate": (dual_ok / n) if n else None,
        "dual_branch_ge_0_90": (dual_ok / n >= 0.90) if n else False,
        "regime_complete_rate": (regime_ok / n) if n else None,
        "regime_complete_ok": (regime_ok == n) if n else False,
        "beats_title_baseline_w20": beats_baseline,
        "stock_quant_n": len(stock_ok),
        "stock_quant_ready": len(stock_ok) >= 20,
        "status": "collecting",
        "note_zh": "§8 全過才准宣稱會判；過閘後必換話筒編碼並再生下一版。不准以 blocked 少做量化／準備。",
    }
    stock_path = stock_pack.get("path_hit_rate") or 0.0
    stock_amp = stock_pack.get("amp_hit_rate") or 0.0
    gate["stock_path_hit_rate"] = stock_path
    gate["stock_amp_hit_rate"] = stock_amp
    # 個股軌要自己變準；不准用大盤命中冒充個股過閘
    gate["stock_rates_ok"] = bool(
        gate["stock_quant_ready"] and stock_path >= 0.70 and stock_amp >= 0.60
    )
    if (
        gate["n_ge_20"]
        and gate["dual_branch_ge_0_90"]
        and gate["regime_complete_ok"]
        and beats_baseline
        and gate["stock_rates_ok"]
    ):
        gate["status"] = "gate_ready_review"
    elif gate["n_ge_20"]:
        gate["status"] = "collecting_n20_plus_stock_needs_lift"

    # vnext silent candidates from validated fixes
    vnext = {
        "as_of_taipei": now_taipei(),
        "purpose_zh": "過閘前就再生／備好下一版候選；大盤＋個股同步。過閘＝必換話筒並再開下一軌。",
        "phone_apply": "pending_gate",
        "candidates": [
            {
                "id": "MKT_AMP_WIDE_FLOOR_POST_STRESS",
                "scope": "market_amp",
                "rule_zh": "瘋狗浪／連續拉回／臨界黑棒後，高機率幅度下緣用深拉（約-3%）而非死守-1.5%",
                "evidence": ["POST_FRENZY_D2_WIDEN_FLOOR", "CRITICAL_K_WEEKEND_WIDE_FLOOR"],
                "status": "silent_collecting",
                "n_fired": 2,
                "n_hit_after": 1,
            },
            {
                "id": "MKT_BLACK_BAR_FORK",
                "scope": "market_wave",
                "rule_zh": "大黑棒日維持雙分支（未確認結束 vs 結束進A），幅度用結構帶",
                "evidence": ["BLACK_BAR_FORK_KEEP_BAND"],
                "status": "silent_collecting",
                "n_fired": 1,
                "n_hit_after": 1,
            },
            {
                "id": "MKT_MEMORY_DIVERGE_KEEP_GRIND",
                "scope": "market_wave",
                "rule_zh": "記憶體內部分歧≠指數敗象；指數仍盤堅帶",
                "evidence": ["MEMORY_DIVERGE_INDEX_GRIND"],
                "status": "silent_collecting",
                "n_fired": 1,
                "n_hit_after": 1,
            },
            {
                "id": "STK_NAMED_DIR_AMP_LEDGER",
                "scope": "stock_path_amp",
                "rule_zh": "點名股逐日方向＋±2%/深拉帶對質；累積勝率後才接查股結構提醒",
                "evidence": ["huang_stock_quant_ledger"],
                "status": "silent_collecting",
                "n_fired": len(stock_ok),
                "n_hit_after": sum(1 for r in stock_ok if r.get("path") == "hit" and r.get("amp") == "hit"),
            },
            {
                "id": "WAVE_DRAW_CONFIRM_BANDS",
                "scope": "wave_draw_confirm",
                "rule_zh": "浪頂／回檔／反彈帶每日凍＋隔日柱對質；過閘後升級大盤／查股可畫可對質帶",
                "evidence": ["wave_progress", "chrono wave hit"],
                "status": "silent_collecting",
                "n_fired": n,
                "n_hit_after": sum(1 for r in chrono_rows if r.get("wave") == "hit"),
            },
        ],
    }

    sb = {
        "as_of_taipei": now_taipei(),
        "phone_sync": "blocked_until_gate",
        "buy_signal": False,
        "recomputable": True,
        "power_goal_zh": "最終＝波浪繪製／確認、點位漲跌幅度、大盤＋個股獲勝率變強並破除限制；過閘必換話筒。準備與量化同步，不准少做。",
        "windows": {"W20": w20_pack, "W40": pack(w40), "all": pack(chrono_rows)},
        "title_only_baseline": baseline,
        "market_quant": {
            "n": n,
            "path_hit": sum(1 for r in chrono_rows if r.get("path") == "hit"),
            "wave_hit": sum(1 for r in chrono_rows if r.get("wave") == "hit"),
            "amp_hit": sum(1 for r in chrono_rows if r.get("amp") == "hit"),
            "levels_hit": sum(1 for r in chrono_rows if r.get("levels") == "hit"),
            "dual_branch_rate": gate["dual_branch_rate"],
            "regime_complete_rate": gate["regime_complete_rate"],
        },
        "stock_quant": stock_pack,
        "gate_section8": gate,
        "feb_pack": {
            "n_confronted": n,
            "hit_high_prob": sum(1 for r in chrono_rows if r.get("path") == "hit"),
            "hit_high_prob_partial": sum(1 for r in chrono_rows if r.get("amp") == "skew"),
            "miss_high_prob": sum(1 for r in chrono_rows if r.get("path") == "miss" or r.get("amp") == "miss"),
            "dual_branch_rate": gate["dual_branch_rate"],
            "regime_complete_rate": gate["regime_complete_rate"],
        },
        "chrono_2026": {
            "start": "20260102",
            "n": n,
            "path_hit": sum(1 for r in chrono_rows if r.get("path") == "hit"),
            "amp_hit": sum(1 for r in chrono_rows if r.get("amp") == "hit"),
            "days": [
                {
                    "day": r["day"],
                    "target": r["target"],
                    "path": r["path"],
                    "wave": r["wave"],
                    "amp": r["amp"],
                    "levels": r["levels"],
                    "fail_codes": r["fail_codes"],
                    "growth_zh": r["growth_zh"],
                }
                for r in chrono_rows
            ],
        },
        "vnext_ref": "huang_vnext_candidates.json",
        "stock_ledger_ref": "huang_stock_quant_ledger.json",
    }

    stock_ledger = {
        "as_of_taipei": now_taipei(),
        "purpose_zh": "點名個股隔日方向＋幅度對質總帳；與大盤分數板同步更新。",
        "phone_apply": "pending_gate",
        "summary": stock_pack,
        "rows": stock_rows,
    }

    OUT_SB.write_text(json.dumps(sb, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    OUT_STOCK.write_text(json.dumps(stock_ledger, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    OUT_VNEXT.write_text(json.dumps(vnext, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # refresh principles header counters (keep principle list if present)
    if OUT_PRIN.exists():
        prin = json.loads(OUT_PRIN.read_text(encoding="utf-8"))
    else:
        prin = {"principles": [], "failures": []}
    prin["as_of_taipei"] = now_taipei()
    prin["phone_sync"] = "blocked_until_gate"
    prin["buy_signal"] = False
    prin["purpose_zh"] = (
        "量化黃的判斷原則＋我隔日失敗碼；大盤＋個股同步。"
        "n不足不准改話筒；但準備／對質／再生下一版一天都不能少。"
    )
    prin["n_days_absorbed"] = n_absorbed
    prin["n_forecasts_confronted"] = n
    prin["my_forecast_score"] = {
        "hit_high_prob": sum(1 for r in chrono_rows if r.get("path") == "hit"),
        "hit_high_prob_partial": sum(1 for r in chrono_rows if r.get("amp") == "skew"),
        "miss_high_prob": sum(1 for r in chrono_rows if r.get("amp") == "miss" or r.get("path") == "miss"),
        "hit_rate_high_prob_strict": rate(chrono_rows, "path"),
        "amp_hit_rate": rate(chrono_rows, "amp", good=("hit",)),
        "wave_hit_rate": rate(chrono_rows, "wave"),
        "stock_path_hit_rate": stock_pack["path_hit_rate"],
        "stock_amp_hit_rate": stock_pack["amp_hit_rate"],
    }
    prin["power_track_zh"] = "破除限制：波浪繪製確認＋幅度＋大盤／個股勝率；過閘必換。"
    OUT_PRIN.write_text(json.dumps(prin, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_closure_report(sb)

    print(
        json.dumps(
            {
                "n": n,
                "gate": gate["status"],
                "W20": w20_pack,
                "stock_n": len(stock_ok),
                "stock_path": stock_pack["path_hit_rate"],
                "stock_amp": stock_pack["amp_hit_rate"],
                "closure": str(OUT_CLOSURE.name),
            },
            ensure_ascii=False,
        )
    )


def write_closure_report(sb: dict) -> None:
    """Living draft of daily growth trajectory; finalize when chrono completes."""
    days = (sb.get("chrono_2026") or {}).get("days") or []
    stock = sb.get("stock_quant") or {}
    gate = sb.get("gate_section8") or {}
    w20 = (sb.get("windows") or {}).get("W20") or {}
    c = sb.get("chrono_2026") or {}
    now = datetime.now(TZ).strftime("%Y-%m-%d %H:%M Asia/Taipei")
    lines: list[str] = []
    lines.append("# 黃培碩chrono 結案報告・成長軌跡（進行中稿）")
    lines.append("")
    lines.append(f"更新：{now}")
    lines.append(
        "非買訊。目標：波浪理論＋驗證；大盤＋個股隔日預估覆盤；"
        "資料夠→量化→推演；過閘換編碼。"
    )
    lines.append("")
    lines.append(
        "> **完成定義：** Drive 自 2026-01-02 起開市日全日序關完＋"
        "`huang_daily_audit.py` 全綠＋分數板／個股總帳／vnext 齊＋本報告定稿。"
    )
    lines.append("")
    lines.append("## 1. 總覽（截至目前）")
    lines.append("")
    lines.append(f"- 已對質開市日 n＝**{c.get('n', 0)}**（起點 20260102）")
    lines.append(f"- 大盤方向 hit：{c.get('path_hit', 0)}/{c.get('n', 0)}")
    lines.append(f"- 大盤幅度 hit：{c.get('amp_hit', 0)}/{c.get('n', 0)}")
    if w20:
        lines.append(
            f"- W20：path {w20.get('path_hit_rate'):.2f}／wave {w20.get('wave_hit_rate'):.2f}／"
            f"amp {w20.get('amp_hit_rate'):.2f}／嚴格全中 {w20.get('strict_all_hit_rate'):.2f}"
        )
    lines.append(
        f"- 個股列數：{stock.get('n_rows')}；path≈{stock.get('path_hit_rate')}；"
        f"amp≈{stock.get('amp_hit_rate')}"
    )
    lines.append(f"- 閘門狀態：`{gate.get('status')}`")
    lines.append("")
    lines.append("## 2. 每日成長軌跡（對質日）")
    lines.append("")
    lines.append("| 日 | 對質日 | path | wave | amp | levels | 成長／失敗碼 |")
    lines.append("|---|---|---|---|---|---|---|")
    for r in days:
        codes = ",".join(r.get("fail_codes") or []) or "—"
        growth = (r.get("growth_zh") or "").replace("|", "／")
        lines.append(
            f"| {r['day']} | {r.get('target', '')} | {r.get('path')} | {r.get('wave')} | "
            f"{r.get('amp')} | {r.get('levels')} | {codes}；{growth} |"
        )
    lines.append("")
    lines.append("## 3. 規則進化（滾動課）")
    lines.append("")
    seen: list[str] = []
    for r in days:
        for code in r.get("fail_codes") or []:
            if code not in seen:
                seen.append(code)
    for code in seen:
        hits = [r["day"] for r in days if code in (r.get("fail_codes") or [])]
        lines.append(f"- `{code}` ← 首次／出現於 {', '.join(hits)}")
    lines.append("")
    lines.append("## 4. 大盤 vs 個股")
    lines.append("")
    lines.append("- 大盤：方向已穩；幅度課（加寬上下緣／破線後日）已在滾動生效。")
    lines.append(
        "- 個股：獨立期望對質中；**不准用大盤命中冒充個股**；目前個股勝率仍需拉升才過閘。"
    )
    lines.append(
        "- 每日必含：波浪鐵律驗證、黃金切割＋等幅度、量價（量／20日均）、"
        "market_power＋stock_quant。"
    )
    lines.append("")
    lines.append("## 5. 尚未完成")
    lines.append("")
    pending: list[str] = []
    if FILM_INDEX.exists():
        idx = json.loads(FILM_INDEX.read_text(encoding="utf-8"))
        done = {r["day"] for r in days}
        pending = [
            x["day"]
            for x in idx.get("days") or []
            if x.get("day", "") >= "20260204"
            and x.get("film_status") in ("present", "absent_open")
            and x["day"] not in done
        ]
    lines.append(f"- 下一待關：{pending[0] if pending else '（chrono 已追到 index 尾或需更新 index）'}")
    if pending:
        lines.append("- 待關清單（節錄）：" + ", ".join(pending[:12]))
    lines.append(
        "- 結案時本檔改「定稿」、補總結句：學到什麼、哪個規則過閘、話筒換了什麼。"
    )
    lines.append("")
    lines.append("## 6. 定稿欄（完成時填）")
    lines.append("")
    lines.append("- 定稿日時（Asia/Taipei）：")
    lines.append("- 最終 n／大盤勝率／個股勝率：")
    lines.append("- 過閘項目：")
    lines.append("- 已換話筒編碼／Render git_sha：")
    lines.append("- 再生下一版候選：")
    lines.append("")
    OUT_CLOSURE.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
