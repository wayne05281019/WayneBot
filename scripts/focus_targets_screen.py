#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""最近重點標的觀察掃（非買訊）。

優先序（2026-11-26 使用者鎖；同夜補排）：
1. 近幾日可「由尾回推」定義五波下跌＋新開始起漲（台光電／光聖型）＝主閘
2. 下降五波畫得出 → 目前都有機會回測次級四浪最高，至少也測得到低；
   還要看距四浪高多遠、有無實際 EPS 獲利、在 AI 產業鏈的地位
3. 量價輔證：底點爆大量後再爆一次更好；只爆一次也可；沒爆仍可觀察（不擋主閘）
4. 量價語意對齊飆大 11/26——不是自創「一年級」口號：
   - 「去年 12 月將近一年的巨量」＝級距對照約一年前巨量
   - 台積＝籌碼沉澱排除最差破底（輔證）

硬邊界：Asia/Taipei；官方日 K；觀察非買訊；不准發明個股 5／9 浪號認證。
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo

from scripts.biaoke_tail_back_five_wave import analyze_bars

TAIPEI = ZoneInfo("Asia/Taipei")
ROOT = Path(__file__).resolve().parents[1]
LAB = ROOT / "docs" / "expert_notes" / "飆客" / "decade_lab"
DB_DEFAULT = ROOT / "data" / "wayne_market.db"

# 輔證：約一年前巨量對照窗（對齊「去年12月將近一年」）
YEAR_AGO_BACK_DAYS = 400
YEAR_AGO_NEAR_DAYS = 200
BOTTOM_VOL_LOOKBACK = 8
NEAR_YEAR_AGO_FRAC = 0.80  # ≥ 一年前巨量×0.8 算「將近」

# 教過且與 AI 鏈相關的組＝掃檔必納（成交額前段漏掉也要試畫）
AI_TAUGHT_GROUPS = (
    "光通訊",
    "低軌衛星",
    "記憶體製造",
    "記憶體控制",
    "記憶體模組",
    "記憶體通路",
    "記憶體封測",
    "高階測試",
    "ASIC",
    "散熱",
    "PCB",
    "ABF",
    "電源管理",
    "無塵室",
    "被動元件",
)


def _taught_ai_sids() -> Dict[str, List[str]]:
    """sid → taught group names。讀不到 industry_fine 就不強制。"""
    try:
        from industry_fine import TAUGHT_GROUPS  # type: ignore
    except Exception:
        return {}
    out: Dict[str, List[str]] = {}
    for g in AI_TAUGHT_GROUPS:
        for sid in TAUGHT_GROUPS.get(g) or ():
            s = str(sid).strip()
            if not s:
                continue
            out.setdefault(s, []).append(str(g))
    return out


@dataclass
class FocusHit:
    stock_id: str
    stock_name: str
    market: str
    asof: str
    close: float
    vol: float
    wave_start: float
    wave_end: float
    wave4: float
    room_to_w4_pct: float
    new_start_date: str
    wave_start_date: str
    wave_end_date: str
    # 量價輔證（非主閘）
    year_ago_peak_vol: float
    year_ago_peak_date: str
    bottom_near_year_ago_bars: int
    vol_note_zh: str
    score: float


def _ymd(raw: Any) -> str:
    t = str(raw or "").replace("-", "")[:8]
    return t if len(t) == 8 and t.isdigit() else ""


def _num(x: Any) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


def latest_full_asof(con: sqlite3.Connection, *, min_rows: int = 1500) -> str:
    row = con.execute(
        """
        SELECT date, COUNT(*) AS c FROM daily_quotes
        GROUP BY date HAVING c >= ?
        ORDER BY date DESC LIMIT 1
        """,
        (int(min_rows),),
    ).fetchone()
    return _ymd(row[0]) if row else ""


def top_n_by_turnover(
    con: sqlite3.Connection, *, market: str, as_of: str, n: int = 100
) -> List[Tuple[str, str]]:
    rows = con.execute(
        """
        SELECT q.stock_id, q.stock_name, q.turnover_k
        FROM daily_quotes q
        LEFT JOIN stock_universe u ON u.stock_id = q.stock_id
        WHERE q.date = ? AND q.market = ?
          AND length(q.stock_id)=4 AND q.stock_id GLOB '[0-9][0-9][0-9][0-9]'
          AND COALESCE(u.asset_type, 'STOCK') = 'STOCK'
        ORDER BY q.turnover_k DESC
        LIMIT ?
        """,
        (as_of, market, int(n)),
    ).fetchall()
    return [(str(a), str(b or a)) for a, b, _ in rows]


def load_bars(con: sqlite3.Connection, sid: str, n: int = 280) -> List[dict]:
    rows = con.execute(
        "SELECT date,open,high,low,close,volume FROM daily_quotes "
        "WHERE stock_id=? ORDER BY date DESC LIMIT ?",
        (sid, n),
    ).fetchall()
    out = []
    for d, o, h, l, c, v in reversed(rows):
        out.append(
            {
                "date": _ymd(d),
                "open": _num(o),
                "high": _num(h),
                "low": _num(l),
                "close": _num(c),
                "volume": _num(v),
            }
        )
    return out


def year_ago_peak_vol(
    bars: Sequence[dict], asof: str
) -> Tuple[float, str]:
    """約一年前窗內最大量（對齊『去年12月將近一年的巨量』對照級距）。"""
    if len(asof) != 8:
        return 0.0, ""
    dt = datetime(int(asof[:4]), int(asof[4:6]), int(asof[6:8]))
    lo = (dt - timedelta(days=YEAR_AGO_BACK_DAYS)).strftime("%Y%m%d")
    hi = (dt - timedelta(days=YEAR_AGO_NEAR_DAYS)).strftime("%Y%m%d")
    best_v, best_d = 0.0, ""
    for b in bars:
        d = _ymd(b.get("date"))
        if not d or d < lo or d > hi:
            continue
        v = _num(b.get("volume"))
        if v > best_v:
            best_v, best_d = v, d
    return best_v, best_d


def count_bottom_near_year_ago(
    bars: Sequence[dict], *, ref_vol: float, new_start_i: int
) -> int:
    """新開始低附近窗內，量 ≥ 一年前巨量×frac 的根數（連續問題量輔證）。"""
    if ref_vol <= 0 or new_start_i < 0:
        return 0
    thr = ref_vol * NEAR_YEAR_AGO_FRAC
    i0 = max(0, new_start_i - 1)
    i1 = min(len(bars), new_start_i + BOTTOM_VOL_LOOKBACK)
    return sum(1 for b in bars[i0:i1] if _num(b.get("volume")) >= thr - 1e-9)


def score_hit(
    *,
    room: float,
    bottom_near: int,
    ok_five: bool,
    wave_bars: int = 0,
) -> float:
    """貼近台光電／光聖臉：五波清楚、距四浪高約 25% 最佳，不是越深越好。"""
    if not ok_five or room <= 0:
        return -1e9
    # 空間以 ~25% 為峰（光聖≈24、台光電≈25）
    ideal = 25.0
    s = 100.0 - abs(float(room) - ideal) * 1.35
    if room > 60.0:
        s -= min(room - 60.0, 40.0) * 0.5
    # 輔證：底部將近一年前巨量（2383 問題量型）——加分但不蓋過鐵律主閘
    s += min(int(bottom_near), 3) * 6.0
    # 結構太短（<12 根）略扣；適中加分
    if 12 <= int(wave_bars) <= 90:
        s += 6.0
    elif int(wave_bars) < 12:
        s -= 8.0
    return s


def scan(
    db_path: Path = DB_DEFAULT,
    *,
    top_n: int = 200,
    limit: int = 0,
    market: Optional[str] = None,
) -> Dict[str, Any]:
    """掃可畫五波標的。

    limit<=0＝可畫全收（使用者鎖：畫得出＝納入範圍再分級，不准先砍）。
    """
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    asof = latest_full_asof(con)
    if not asof:
        con.close()
        return {"ok": False, "error": "no asof"}
    universe: List[Tuple[str, str, str]] = []
    seen: set[str] = set()
    markets = (str(market),) if market in ("TW", "TWO") else ("TW", "TWO")
    for mkt in markets:
        for sid, name in top_n_by_turnover(con, market=mkt, as_of=asof, n=top_n):
            if sid in seen:
                continue
            seen.add(sid)
            universe.append((sid, name, mkt))
    # 教過 AI 鏈強制納入母體（健策／南電／國巨等不因成交額窗漏掉）
    taught = _taught_ai_sids()
    for sid, _groups in taught.items():
        if sid in seen:
            continue
        row = con.execute(
            "SELECT stock_name, market FROM daily_quotes WHERE stock_id=? AND date=?",
            (sid, asof),
        ).fetchone()
        if not row:
            row = con.execute(
                "SELECT stock_name, market FROM daily_quotes WHERE stock_id=? "
                "ORDER BY date DESC LIMIT 1",
                (sid,),
            ).fetchone()
        if not row:
            continue
        name, mkt = str(row[0] or sid), str(row[1] or "")
        if market in ("TW", "TWO") and mkt != market:
            continue
        seen.add(sid)
        universe.append((sid, name, mkt or "TW"))
    hits: List[FocusHit] = []
    for sid, name, mkt in universe:
        bars = load_bars(con, sid, 280)
        if len(bars) < 80:
            continue
        tb = analyze_bars(bars)
        if not tb.ok_five or not tb.five_points or len(tb.five_points) < 6:
            continue
        if not tb.ok_new_start or tb.new_start is None:
            continue
        pts = tb.five_points
        w0, w4, w5 = pts[0], pts[4], pts[5]
        close = float(bars[-1]["close"])
        # 可畫就納入：已過四浪高也留（分級標「已過」），不准因空間砍掉
        room = (w4.price - close) / close * 100.0
        ref_v, ref_d = year_ago_peak_vol(bars, asof)
        near_n = count_bottom_near_year_ago(
            bars, ref_vol=ref_v, new_start_i=int(tb.new_start.i)
        )
        if near_n >= 2:
            vol_note = (
                f"底部近窗有{near_n}根量≥約一年前巨量×{NEAR_YEAR_AGO_FRAC:.0%}"
                f"（對照{ref_d or '—'} {ref_v:.0f}張；2383問題量型輔證）"
            )
        elif near_n == 1:
            vol_note = (
                f"底部近窗1根量接近約一年前巨量（對照{ref_d or '—'} {ref_v:.0f}張）"
            )
        else:
            vol_note = (
                "五波可畫＝納入範圍；底部未達將近一年前巨量仍可觀察"
                "（雙爆更好、單爆也可；分級另看距四浪高／EPS／AI鏈地位）"
            )
        if room <= 0:
            vol_note = "已過／觸及次級四浪高；五波可畫仍納入分級。" + vol_note
        wave_bars = int(w5.i) - int(w0.i)
        # 已過四浪高：主分用較低分，但仍進名單
        if room > 0:
            sc = score_hit(
                room=room, bottom_near=near_n, ok_five=True, wave_bars=wave_bars
            )
        else:
            sc = 40.0 + min(int(near_n), 3) * 4.0

        hits.append(
            FocusHit(
                stock_id=sid,
                stock_name=name,
                market=mkt,
                asof=asof,
                close=close,
                vol=float(bars[-1]["volume"]),
                wave_start=float(w0.price),
                wave_end=float(w5.price),
                wave4=float(w4.price),
                room_to_w4_pct=round(room, 2),
                new_start_date=str(tb.new_start.date or bars[tb.new_start.i]["date"]),
                wave_start_date=str(w0.date or bars[w0.i]["date"]),
                wave_end_date=str(w5.date or bars[w5.i]["date"]),
                year_ago_peak_vol=float(ref_v),
                year_ago_peak_date=ref_d,
                bottom_near_year_ago_bars=int(near_n),
                vol_note_zh=vol_note,
                score=round(sc, 2),
            )
        )
    hits.sort(key=lambda h: (-h.score, -h.room_to_w4_pct, h.stock_id))
    # limit<=0：可畫全收；>0 才截（僅除錯用）
    if int(limit) > 0:
        hits = hits[: int(limit)]
    out = {
        "ok": True,
        "asof": asof,
        "as_of_taipei": datetime.now(TAIPEI).isoformat(timespec="seconds"),
        "priority_zh": (
            "五波畫得出＝全部納入再分級；"
            "分級看距四浪高／EPS獲利／AI鏈地位；"
            "量價雙爆更好、單爆也可、沒爆仍可觀察"
        ),
        "iron_laws_zh": (
            "WR-IRON：③非①③⑤最短；①④價區不重疊（淺疊≤8%可畫）；"
            "下跌序 H2<H0、L3<L1、L5<L3。急殺短段可用逐日擺動備援轉折。"
        ),
        "oral_vol_zh": (
            "台光電原文＝底部連續爆2根『去年12月將近一年的巨量』"
            "（級距對照約一年前巨量，不是自創『一年級』百分位名）；"
            "台積＝籌碼沉澱排除最差破底。觀察非買訊。"
        ),
        "n_universe": len(universe),
        "n_taught_forced": len(taught),
        "n_hits": len(hits),
        "hits": [asdict(h) for h in hits],
    }
    con.close()
    return out


def vol_tier_of(near: int) -> str:
    n = int(near or 0)
    if n >= 2:
        return "ge2"
    if n == 1:
        return "eq1"
    return "none"


def room_band_of(room: float) -> str:
    r = float(room)
    if r <= 0:
        return "past"  # 已過／觸及次級四浪高；仍可畫、仍納入分級
    if r < 15.0:
        return "tight"
    if r <= 35.0:
        return "near25"
    if r <= 55.0:
        return "wide"
    return "deep"


def eps_fields(con: sqlite3.Connection, sid: str) -> Tuple[Optional[float], bool]:
    """latest season eps；獲利＝最新季>0 或同年度累計>0。"""
    rows = con.execute(
        "SELECT year, season, eps FROM quarterly_income WHERE stock_id=? "
        "ORDER BY year DESC, season DESC LIMIT 12",
        (sid,),
    ).fetchall()
    if not rows:
        return None, False
    eps_last: Optional[float] = None
    for _y, _s, e in rows:
        if e is None:
            continue
        eps_last = float(e)
        break
    if eps_last is not None and eps_last > 0:
        return eps_last, True
    # 同年度累計（最新年各季加總；累計形取最大季）
    years = sorted({int(y) for y, _s, e in rows if e is not None}, reverse=True)
    if not years:
        return eps_last, False
    y0 = years[0]
    season_eps = {
        int(s): float(e)
        for y, s, e in rows
        if int(y) == y0 and e is not None
    }
    if not season_eps:
        return eps_last, False
    # 累計形：季節遞增 → 取最大季當 cum
    vals = [season_eps[s] for s in sorted(season_eps)]
    cumish = vals[-1]
    if len(vals) >= 2 and all(vals[i] <= vals[i + 1] + 1e-9 for i in range(len(vals) - 1)):
        profit = cumish > 0
    else:
        profit = sum(vals) > 0
    return eps_last, bool(profit)


def taught_ai_tags_for(sid: str) -> List[str]:
    try:
        from industry_fine import extra_tags_for  # type: ignore
    except Exception:
        return list((_taught_ai_sids().get(str(sid)) or []))
    tags = [str(t) for t in (extra_tags_for(sid) or [])]
    ai = set(AI_TAUGHT_GROUPS)
    out = [t for t in tags if t in ai]
    if out:
        return out
    return list((_taught_ai_sids().get(str(sid)) or []))


def industry_chain_for(con: sqlite3.Connection, sid: str) -> str:
    row = con.execute(
        "SELECT chain FROM stock_fine_industry WHERE stock_id=? LIMIT 1",
        (sid,),
    ).fetchone()
    return str(row[0] or "") if row else ""


def assign_tier(
    *,
    vol_tier: str,
    eps_profit: bool,
    taught_ai: bool,
    room_band: str,
) -> str:
    """A 最佳 → D。觀察非買訊。"""
    if (
        vol_tier == "ge2"
        and eps_profit
        and taught_ai
        and room_band in ("near25", "tight")
    ):
        return "A"
    if (
        (vol_tier in ("ge2", "eq1") or taught_ai)
        and eps_profit
        and room_band not in ("deep", "past")
    ):
        return "B"
    if eps_profit or taught_ai:
        return "C"
    return "D"


def enrich_hit(con: sqlite3.Connection, hit: Dict[str, Any]) -> Dict[str, Any]:
    sid = str(hit.get("stock_id") or "")
    near = int(hit.get("bottom_near_year_ago_bars") or 0)
    room = float(hit.get("room_to_w4_pct") or 0.0)
    vt = vol_tier_of(near)
    rb = room_band_of(room)
    eps_last, eps_ok = eps_fields(con, sid)
    tags = taught_ai_tags_for(sid)
    chain = industry_chain_for(con, sid)
    taught_ai = bool(tags)
    tier = assign_tier(
        vol_tier=vt, eps_profit=eps_ok, taught_ai=taught_ai, room_band=rb
    )
    out = dict(hit)
    out.update(
        {
            "vol_tier": vt,
            "room_band": rb,
            "eps_last": eps_last,
            "eps_profit": bool(eps_ok),
            "taught_tags": tags,
            "taught_ai": taught_ai,
            "industry_chain": chain,
            "tier": tier,
            "observe_only_zh": "觀察非買訊",
        }
    )
    return out


def merge_and_tier(
    *screen_paths: Path,
    db_path: Path = DB_DEFAULT,
) -> Dict[str, Any]:
    """合併各市場可畫五波命中 → 補 EPS／AI 鏈／量價分級。不准先剔除可畫檔。"""
    by_sid: Dict[str, Dict[str, Any]] = {}
    asof = ""
    sources: List[str] = []
    for p in screen_paths:
        path = Path(p)
        if not path.is_file():
            continue
        raw = json.loads(path.read_text(encoding="utf-8"))
        sources.append(str(path))
        asof = str(raw.get("asof") or asof)
        for h in raw.get("hits") or []:
            sid = str(h.get("stock_id") or "").strip()
            if not sid:
                continue
            # 可畫全收：已過四浪高也納入（room_band=past），不准先剔除
            prev = by_sid.get(sid)
            if prev is None or float(h.get("score") or -1e9) > float(
                prev.get("score") or -1e9
            ):
                by_sid[sid] = dict(h)
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    enriched = [enrich_hit(con, h) for h in by_sid.values()]
    con.close()

    def _sort_key(h: Dict[str, Any]) -> Tuple:
        room = float(h.get("room_to_w4_pct") or 0.0)
        return (-float(h.get("score") or 0.0), abs(room - 25.0), str(h.get("stock_id")))

    tiers: Dict[str, List[Dict[str, Any]]] = {k: [] for k in ("A", "B", "C", "D")}
    for h in enriched:
        tiers.setdefault(str(h.get("tier") or "D"), []).append(h)
    for k in tiers:
        tiers[k].sort(key=_sort_key)
    counts = {k: len(tiers[k]) for k in ("A", "B", "C", "D")}
    return {
        "ok": True,
        "asof": asof,
        "as_of_taipei": datetime.now(TAIPEI).isoformat(timespec="seconds"),
        "note_zh": (
            "五波畫得出＝全部納入再分級；"
            "爆兩次巨量更好、一次也可、沒爆仍可觀察；"
            "分級看距四浪高／EPS獲利／AI鏈地位；觀察非買訊"
        ),
        "sources": sources,
        "n_hits": sum(counts.values()),
        "n_per_tier": counts,
        "tiers": tiers,
        "hits": [h for k in ("A", "B", "C", "D") for h in tiers[k]],
    }


def format_tiered_txt(pack: Dict[str, Any]) -> str:
    lines: List[str] = []
    counts = pack.get("n_per_tier") or {}
    lines.append(
        f"asof={pack.get('asof')} n={pack.get('n_hits')} "
        f"A={counts.get('A',0)} B={counts.get('B',0)} "
        f"C={counts.get('C',0)} D={counts.get('D',0)}｜觀察非買訊"
    )
    lines.append(str(pack.get("note_zh") or ""))
    for tier in ("A", "B", "C", "D"):
        rows = (pack.get("tiers") or {}).get(tier) or []
        lines.append(f"\n=== Tier {tier}（{len(rows)}）===")
        for h in rows:
            tags = ",".join(h.get("taught_tags") or []) or "—"
            eps = h.get("eps_last")
            eps_s = f"{eps:.2f}" if isinstance(eps, (int, float)) else "—"
            lines.append(
                f"{h.get('stock_id')} {h.get('stock_name')} "
                f"room={h.get('room_to_w4_pct')}% "
                f"nearVol={h.get('bottom_near_year_ago_bars')} "
                f"vol={h.get('vol_tier')} band={h.get('room_band')} "
                f"eps={eps_s} profit={1 if h.get('eps_profit') else 0} "
                f"taught={tags} score={h.get('score')}"
            )
    return "\n".join(lines) + "\n"


def main() -> None:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--market", choices=("TW", "TWO"), default=None)
    ap.add_argument("--top-n", type=int, default=200)
    ap.add_argument(
        "--limit",
        type=int,
        default=0,
        help="<=0 可畫全收（預設）；>0 才截斷",
    )
    ap.add_argument("--out", default="")
    ap.add_argument(
        "--merge-tier",
        nargs="+",
        default=None,
        help="合併既有 screen JSON 並分級輸出",
    )
    ap.add_argument("--tier-json", default="")
    ap.add_argument("--tier-txt", default="")
    args = ap.parse_args()
    if args.merge_tier:
        pack = merge_and_tier(*[Path(p) for p in args.merge_tier])
        jpath = Path(args.tier_json) if args.tier_json else (
            Path("/opt/cursor/artifacts") / f"focus_tiered_{pack.get('asof') or 'na'}.json"
        )
        tpath = Path(args.tier_txt) if args.tier_txt else jpath.with_suffix(".txt")
        jpath.parent.mkdir(parents=True, exist_ok=True)
        jpath.write_text(json.dumps(pack, ensure_ascii=False, indent=2), encoding="utf-8")
        tpath.write_text(format_tiered_txt(pack), encoding="utf-8")
        print("TIER_JSON", jpath)
        print("TIER_TXT", tpath)
        print("n_per_tier", pack.get("n_per_tier"), "n", pack.get("n_hits"))
        return

    out = scan(top_n=int(args.top_n), limit=int(args.limit), market=args.market)
    LAB.mkdir(parents=True, exist_ok=True)
    tag = args.market or "all"
    path = Path(args.out) if args.out else (
        LAB / f"focus_targets_screen_{out.get('asof') or 'na'}_{tag}.json"
    )
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.market is None:
        latest = LAB / "focus_targets_screen_latest.json"
        latest.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print("OUT", path)
    print("asof", out.get("asof"), "hits", out.get("n_hits"), "/", out.get("n_universe"))
    for h in out.get("hits") or []:
        print(
            f"{h['stock_id']} {h['stock_name']} room={h['room_to_w4_pct']}% "
            f"w0={h['wave_start']:.0f}→w5={h['wave_end']:.0f} w4={h['wave4']:.0f} "
            f"nearVol={h['bottom_near_year_ago_bars']} score={h['score']}"
        )


if __name__ == "__main__":
    main()
