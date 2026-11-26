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
            "五波畫得出＝五波走完、正在反彈／往上次級四浪高，全部納入再分級；"
            "未按結構就破＝偏弱；分級看距四浪高／EPS／AI鏈／股性；"
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


# --- 次級四浪：股性＋EPS 深分級（觀察非買訊）---
CHIP_WINDOW_N = 10
CHIP_LEAD_RATIO = 1.35
CHIP_FLAT_FRAC_OF_VOL = 0.02  # |淨額|合計 / 近窗日均量 < 2% → 近乎平
RETAIL_VOL_VS_MEDIAN = 1.6
MUST_CHECK_SIDS = (
    "2383",
    "3653",
    "3017",
    "2327",
    "8046",
    "3037",
    "6442",
    "2408",
    "2344",
    "3324",
    "3105",
)

CHIP_LABEL_HEURISTIC_ZH = (
    "近 N=10 個「已有三大法人欄」交易日，加總 daily_quotes.foreign_net／"
    "trust_net／dealer_net（單位＝張，官方 T86／櫃買寫進日 K；"
    "缺 T86 的全日全 0 日跳過，不准當真 0 張）。"
    "三者買超淨額最大且相對第二名達 clear lead（≥1.35×）→ "
    "外資／投信／自營；三者近乎平＋近窗量明顯高於中位量且法人弱 → 偏散戶。"
    "不准發明主力成本；broker_branch_trades 全市場分點不抓。"
)


def last_chip_asof(con: sqlite3.Connection) -> str:
    """市場上最後一日三大法人有非零寫入的 asof。"""
    row = con.execute(
        "SELECT MAX(date) FROM daily_quotes WHERE "
        "ABS(COALESCE(foreign_net,0))+ABS(COALESCE(trust_net,0))"
        "+ABS(COALESCE(dealer_net,0))>0"
    ).fetchone()
    return _ymd(row[0]) if row and row[0] else ""


def chip_window_rows(
    con: sqlite3.Connection, sid: str, *, n: int = CHIP_WINDOW_N
) -> Tuple[str, List[Tuple[str, float, float, float, float]]]:
    """回傳 (chip_asof, [(date, foreign, trust, dealer, volume), ...]) 近→遠。

    只取 ≤ 市場最後有法人欄之日，再往前湊滿 N 個交易日（該股有量）。
    """
    asof = last_chip_asof(con)
    if not asof:
        return "", []
    rows = con.execute(
        "SELECT date, COALESCE(foreign_net,0), COALESCE(trust_net,0), "
        "COALESCE(dealer_net,0), COALESCE(volume,0) "
        "FROM daily_quotes WHERE stock_id=? AND date<=? AND volume>0 "
        "ORDER BY date DESC LIMIT ?",
        (sid, asof, int(n)),
    ).fetchall()
    out: List[Tuple[str, float, float, float, float]] = []
    for r in rows:
        d = _ymd(r[0])
        if not d:
            continue
        out.append((d, float(r[1]), float(r[2]), float(r[3]), float(r[4])))
    return asof, out


def classify_chip_label(
    foreign_sum: float,
    trust_sum: float,
    dealer_sum: float,
    *,
    vol_mean: float,
    vol_median_prior: float,
    lead_ratio: float = CHIP_LEAD_RATIO,
) -> Tuple[str, bool, str]:
    """回 (chip_label, constructive, detail_zh)。

    chip_label ∈ {外資, 投信, 自營, 偏散戶, 籌碼平淡, 缺資料}
    constructive＝機構買超主導且淨額為正。
    """
    trips = [
        ("外資", float(foreign_sum)),
        ("投信", float(trust_sum)),
        ("自營", float(dealer_sum)),
    ]
    abs_sum = sum(abs(v) for _k, v in trips)
    if abs_sum <= 1e-9 and float(vol_mean or 0) <= 0:
        return "缺資料", False, "近窗無法人淨額"
    flat_cut = max(50.0, float(vol_mean or 0) * CHIP_FLAT_FRAC_OF_VOL * CHIP_WINDOW_N)
    retail_hot = bool(
        vol_median_prior > 0
        and vol_mean >= float(vol_median_prior) * RETAIL_VOL_VS_MEDIAN
        and abs_sum < flat_cut * 2
    )
    if abs_sum < flat_cut:
        if retail_hot:
            return "偏散戶", False, (
                f"法人近乎平(|F|+|T|+|D|={abs_sum:.0f}張<{flat_cut:.0f})，"
                f"近窗量{vol_mean:.0f}>中位×{RETAIL_VOL_VS_MEDIAN}"
            )
        return "籌碼平淡", False, (
            f"法人近乎平(|F|+|T|+|D|={abs_sum:.0f}張)，量未顯熱"
        )
    # 只在「買超>0」的機構之間比 clear lead；全賣不准標成外資／投信／自營愛
    buyers = sorted([(k, v) for k, v in trips if v > 0], key=lambda x: x[1], reverse=True)
    if not buyers:
        return "偏散戶", False, (
            f"無機構買超 F={foreign_sum:.0f}/T={trust_sum:.0f}/D={dealer_sum:.0f}張"
            + ("，量熱" if retail_hot else "，法人偏賣")
        )
    top_k, top_v = buyers[0]
    second_v = buyers[1][1] if len(buyers) > 1 else 0.0
    clear = top_v >= float(second_v) * float(lead_ratio) and top_v >= flat_cut * 0.25
    if clear:
        return top_k, True, (
            f"{top_k}買超主導 F={foreign_sum:.0f}/T={trust_sum:.0f}/D={dealer_sum:.0f}張 "
            f"(lead≥{lead_ratio}×)"
        )
    return top_k, False, (
        f"{top_k}相對買超 F={foreign_sum:.0f}/T={trust_sum:.0f}/D={dealer_sum:.0f}張"
        "（未達 clear lead）"
    )


def _vol_median(vals: Sequence[float]) -> float:
    xs = sorted(float(v) for v in vals)
    if not xs:
        return 0.0
    mid = len(xs) // 2
    if len(xs) % 2:
        return xs[mid]
    return 0.5 * (xs[mid - 1] + xs[mid])


def enrich_chip_character(con: sqlite3.Connection, hit: Dict[str, Any]) -> Dict[str, Any]:
    """在 enrich_hit 之上補股性標籤與近窗法人加總。"""
    sid = str(hit.get("stock_id") or "")
    chip_asof, rows = chip_window_rows(con, sid, n=CHIP_WINDOW_N)
    foreign_sum = sum(r[1] for r in rows)
    trust_sum = sum(r[2] for r in rows)
    dealer_sum = sum(r[3] for r in rows)
    vols = [r[4] for r in rows]
    vol_mean = (sum(vols) / len(vols)) if vols else 0.0
    # 前段中位量：再往前抓 20 日
    prior = con.execute(
        "SELECT COALESCE(volume,0) FROM daily_quotes WHERE stock_id=? AND date<? "
        "AND volume>0 ORDER BY date DESC LIMIT 20",
        (sid, chip_asof or "99999999"),
    ).fetchall()
    vol_med = _vol_median([float(r[0]) for r in prior]) if prior else vol_mean
    label, constructive, detail = classify_chip_label(
        foreign_sum,
        trust_sum,
        dealer_sum,
        vol_mean=vol_mean,
        vol_median_prior=vol_med,
    )
    out = dict(hit)
    out.update(
        {
            "chip_asof": chip_asof,
            "chip_n": len(rows),
            "chip_foreign_sum": round(foreign_sum, 1),
            "chip_trust_sum": round(trust_sum, 1),
            "chip_dealer_sum": round(dealer_sum, 1),
            "chip_unit": "張",
            "chip_label": label,
            "chip_constructive": bool(constructive),
            "chip_detail_zh": detail,
            "nearVol": int(hit.get("bottom_near_year_ago_bars") or 0),
        }
    )
    return out


def assign_character_bucket(hit: Dict[str, Any]) -> str:
    """最值得介入 vs 短衝搶一波。觀察非買訊。

    規則：EPS≤0／缺 → 短衝；有實質獲利＋（AI鏈或建設性機構買超）→ 值得介入；
    其餘（僅技術空間／散戶熱／法人弱）→ 短衝。
    """
    eps = hit.get("eps_last")
    eps_ok = bool(hit.get("eps_profit"))
    if eps is None or (isinstance(eps, (int, float)) and float(eps) <= 0) or not eps_ok:
        return "短衝搶一波"
    taught = bool(hit.get("taught_ai"))
    constructive = bool(hit.get("chip_constructive"))
    label = str(hit.get("chip_label") or "")
    if taught or constructive:
        return "最值得介入"
    if label == "偏散戶":
        return "短衝搶一波"
    # 有 EPS 但無 AI、無建設性籌碼 → 技術反彈側
    return "短衝搶一波"


def character_score(hit: Dict[str, Any], bucket: str) -> float:
    """桶內排序分（非買訊）。"""
    base = float(hit.get("score") or 0.0)
    room = float(hit.get("room_to_w4_pct") or 0.0)
    near = int(hit.get("nearVol") or hit.get("bottom_near_year_ago_bars") or 0)
    eps = hit.get("eps_last")
    eps_v = float(eps) if isinstance(eps, (int, float)) else 0.0
    taught = 1.0 if hit.get("taught_ai") else 0.0
    constructive = 1.0 if hit.get("chip_constructive") else 0.0
    retail = 1.0 if hit.get("chip_label") == "偏散戶" else 0.0
    room_face = max(0.0, 35.0 - abs(room - 25.0))  # 貼 25% 臉
    if bucket == "最值得介入":
        return (
            base
            + 40.0 * taught
            + min(50.0, max(0.0, eps_v))
            + 25.0 * constructive
            + room_face
            + 8.0 * min(near, 4)
        )
    # 短衝：薄 EPS／散戶熱／量爆加分；深虧 EPS 也算技術側
    thin = 0.0
    if eps is None or eps_v <= 0:
        thin = 30.0
    elif eps_v < 2.0:
        thin = 15.0
    return (
        base
        + thin
        + 22.0 * retail
        + 6.0 * min(near, 4)
        + room_face * 0.6
        - 15.0 * taught  # AI 鏈不該排在短衝頂
    )


def build_why_zh(hit: Dict[str, Any], bucket: str) -> str:
    eps = hit.get("eps_last")
    eps_s = f"{eps:.2f}" if isinstance(eps, (int, float)) else "缺"
    tags = ",".join(hit.get("taught_tags") or []) or "—"
    ftd = (
        f"F{hit.get('chip_foreign_sum', 0):.0f}/"
        f"T{hit.get('chip_trust_sum', 0):.0f}/"
        f"D{hit.get('chip_dealer_sum', 0):.0f}張"
        f"（近{hit.get('chip_n', 0)}日≤{hit.get('chip_asof') or '?'}）"
    )
    bits = [
        f"股性={hit.get('chip_label')}",
        f"法人加總{ftd}",
        f"EPS季={eps_s}{'獲利' if hit.get('eps_profit') else '無保護'}",
        f"AI鏈={tags}",
        f"room={hit.get('room_to_w4_pct')}%",
        f"nearVol={hit.get('nearVol', hit.get('bottom_near_year_ago_bars'))}",
    ]
    if bucket == "最值得介入":
        bits.append("實質收益保護＋AI／建設性籌碼側")
    else:
        bits.append("技術反彈／散戶熱／薄EPS側")
    bits.append("觀察非買訊")
    return "；".join(str(b) for b in bits)


def character_tier_pack(
    *screen_paths: Path,
    db_path: Path = DB_DEFAULT,
) -> Dict[str, Any]:
    """合併可畫五波母體 → 股性＋EPS 深分兩桶。past-w4 全留。"""
    base = merge_and_tier(*screen_paths, db_path=db_path)
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    enriched: List[Dict[str, Any]] = []
    for h in base.get("hits") or []:
        row = enrich_chip_character(con, h)
        bucket = assign_character_bucket(row)
        score = round(character_score(row, bucket), 2)
        row["character_bucket"] = bucket
        row["character_score"] = score
        row["why_zh"] = build_why_zh(row, bucket)
        row["observe_only_zh"] = "觀察非買訊"
        enriched.append(row)
    con.close()

    buckets: Dict[str, List[Dict[str, Any]]] = {
        "最值得介入": [],
        "短衝搶一波": [],
    }
    for h in enriched:
        buckets.setdefault(str(h.get("character_bucket")), []).append(h)
    for k in buckets:
        buckets[k].sort(
            key=lambda x: (-float(x.get("character_score") or 0), str(x.get("stock_id")))
        )
    counts = {k: len(buckets[k]) for k in ("最值得介入", "短衝搶一波")}
    by_sid = {str(h.get("stock_id")): h for h in enriched}
    must_rows = []
    for sid in MUST_CHECK_SIDS:
        h = by_sid.get(sid)
        if not h:
            must_rows.append(
                {
                    "stock_id": sid,
                    "in_mother": False,
                    "character_bucket": None,
                    "why_zh": "不在可畫五波母體",
                }
            )
            continue
        must_rows.append(
            {
                "stock_id": sid,
                "stock_name": h.get("stock_name"),
                "in_mother": True,
                "character_bucket": h.get("character_bucket"),
                "chip_label": h.get("chip_label"),
                "eps_last": h.get("eps_last"),
                "character_score": h.get("character_score"),
                "why_zh": h.get("why_zh"),
            }
        )
    return {
        "ok": True,
        "asof": base.get("asof"),
        "as_of_taipei": datetime.now(TAIPEI).isoformat(timespec="seconds"),
        "button_zh": "次級四浪",
        "note_zh": (
            "母體＝可畫五波（含已過四浪高）；再依股性＋EPS 深分："
            "最值得介入＝收益保護／AI鏈＋建設性籌碼；"
            "短衝搶一波＝技術反彈／散戶熱／薄EPS。觀察非買訊。"
        ),
        "chip_label_heuristic_zh": CHIP_LABEL_HEURISTIC_ZH,
        "chip_window_n": CHIP_WINDOW_N,
        "sources": base.get("sources"),
        "n_mother": int(base.get("n_hits") or 0),
        "n_per_bucket": counts,
        "buckets": buckets,
        "must_check": must_rows,
        "observe_only_zh": "觀察非買訊",
    }


def format_character_tier_txt(pack: Dict[str, Any], *, top_n: int = 25) -> str:
    lines: List[str] = []
    counts = pack.get("n_per_bucket") or {}
    lines.append(
        f"asof={pack.get('asof')} 次級四浪｜母體n={pack.get('n_mother')} "
        f"值得介入={counts.get('最值得介入', 0)} "
        f"短衝搶一波={counts.get('短衝搶一波', 0)}｜觀察非買訊"
    )
    lines.append(str(pack.get("note_zh") or ""))
    lines.append(str(pack.get("chip_label_heuristic_zh") or ""))
    for bucket in ("最值得介入", "短衝搶一波"):
        rows = (pack.get("buckets") or {}).get(bucket) or []
        lines.append(f"\n=== {bucket}（共{len(rows)}；列 top {top_n}）===")
        for h in rows[: int(top_n)]:
            eps = h.get("eps_last")
            eps_s = f"{eps:.2f}" if isinstance(eps, (int, float)) else "—"
            tags = ",".join(h.get("taught_tags") or []) or "—"
            lines.append(
                f"{h.get('stock_id')} {h.get('stock_name')} "
                f"room={h.get('room_to_w4_pct')}% "
                f"nearVol={h.get('nearVol', h.get('bottom_near_year_ago_bars'))} "
                f"eps={eps_s} taught={tags} "
                f"chip={h.get('chip_label')} "
                f"score={h.get('character_score')} "
                f"| {h.get('why_zh')}"
            )
    lines.append("\n=== must-check ===")
    for m in pack.get("must_check") or []:
        lines.append(
            f"{m.get('stock_id')} {m.get('stock_name') or ''} "
            f"bucket={m.get('character_bucket')} | {m.get('why_zh')}"
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
    ap.add_argument(
        "--character-tier",
        nargs="+",
        default=None,
        help="合併 screen JSON → 股性＋EPS 深分兩桶（次級四浪）",
    )
    ap.add_argument("--character-json", default="")
    ap.add_argument("--character-txt", default="")
    args = ap.parse_args()
    if args.character_tier:
        pack = character_tier_pack(*[Path(p) for p in args.character_tier])
        jpath = Path(args.character_json) if args.character_json else (
            Path("/opt/cursor/artifacts")
            / f"focus_w4_character_tier_{pack.get('asof') or 'na'}.json"
        )
        tpath = Path(args.character_txt) if args.character_txt else jpath.with_suffix(".txt")
        jpath.parent.mkdir(parents=True, exist_ok=True)
        jpath.write_text(json.dumps(pack, ensure_ascii=False, indent=2), encoding="utf-8")
        tpath.write_text(format_character_tier_txt(pack), encoding="utf-8")
        print("CHARACTER_JSON", jpath)
        print("CHARACTER_TXT", tpath)
        print("n_per_bucket", pack.get("n_per_bucket"), "mother", pack.get("n_mother"))
        return
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
