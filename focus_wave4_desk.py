# -*- coding: utf-8 -*-
"""次級四浪話筒頁：五波可畫母體 → 股性／EPS／AI 鏈分級。

使用者鎖（2026-11-26）：
- 五波畫得出＝全部納入再分級
- 可畫＝五波下跌走完、正在反彈／往上
- 要搶的＝次級四浪高；連四浪低（③低）都過不了／當天下來＝偏沒力
- 再挑：最值得介入 vs 短衝搶一波（實質 EPS vs 技術反彈）
- 股性：外資／投信／自營（官方淨買賣；不准假成本）
- 觀察非買訊；不准改 leave_zero／ma60_lower
"""
from __future__ import annotations

import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor, wait
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo

from scripts.focus_targets_screen import (
    AI_TAUGHT_GROUPS,
    DB_DEFAULT,
    _taught_ai_sids,
    scan,
)

TAIPEI = ZoneInfo("Asia/Taipei")
CHIP_LOOKBACK = 10
PAGE_SIZE = 10  # 話筒實質十檔翻頁
# 盤中距離用現價（2026-11-27 使用者鎖 B）；結構仍用已收日K回推。
LIVE_ROOM_POLICY = "B_intraday_last"
# 十檔附圖：並行上限（matplotlib 別開太兇）
CHART_PAINT_WORKERS = 3

# 使用者鎖：實質收入好的教過臉，未過四浪低也絕不准排除（觀察非買訊）。
# horizon＝他口述遠距位，不是進場價、不是買訊。
QUALITY_HORIZON_ZH: Dict[str, str] = {
    "2383": "台光電實質收入好：未過四浪低也不排除；12個月內看8000（口述遠距，非買訊）",
    "6442": "光聖實質臉：未過四浪低也不排除；一定過2500（口述遠距，非買訊）",
}
# 被動元件這類＝比較是搶反彈／短衝臉，不是台光電那種實質長線臉。
REBOUND_TAUGHT_TAGS = frozenset({"被動元件"})

_DESK_CACHE: Dict[str, Any] = {"key": "", "ts": 0.0, "payload": None}
_DESK_TTL_SEC = 180.0
_DESK_CACHE_LOCK = threading.Lock()
# 實質十檔盤中現價：有界並行（失敗／逾時→收盤臉）
_LIVE_OVERLAY_WORKERS = 6
_LIVE_QUOTE_TIMEOUT_SEC = 5.0


def _is_rebound_face(row: "Wave4Row") -> bool:
    tags = set(row.taught_tags or [])
    if tags & REBOUND_TAUGHT_TAGS:
        return True
    chain = str(row.industry_chain or "")
    return "被動元件" in chain


@dataclass
class Wave4Row:
    stock_id: str
    stock_name: str
    market: str
    close: float
    wave4: float = 0.0  # 次級四浪高＝要搶的位
    wave3_low: float = 0.0  # ③低＝四浪低；至少要過才有力
    room_to_w4_pct: float = 0.0
    above_w4_low: bool = True
    bottom_near_year_ago_bars: int = 0
    score: float = 0.0
    eps_last: Optional[float] = None
    eps_profit: bool = False
    taught_tags: List[str] = field(default_factory=list)
    industry_chain: str = ""
    chip_label: str = ""
    foreign_net_sum: float = 0.0
    trust_net_sum: float = 0.0
    dealer_net_sum: float = 0.0
    bucket: str = ""  # intervene | sprint | watch
    why_zh: str = ""


def _num(x: Any) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


def _eps_last(con: sqlite3.Connection, sid: str) -> Tuple[Optional[float], bool]:
    row = con.execute(
        "SELECT eps FROM quarterly_income WHERE stock_id=? "
        "ORDER BY year DESC, season DESC LIMIT 1",
        (sid,),
    ).fetchone()
    if not row or row[0] is None:
        return None, False
    v = _num(row[0])
    return v, v > 0


def _industry(con: sqlite3.Connection, sid: str) -> str:
    row = con.execute(
        "SELECT chain FROM stock_fine_industry WHERE stock_id=?", (sid,)
    ).fetchone()
    return str(row[0] or "") if row else ""


def _chip_sums(
    con: sqlite3.Connection, sid: str, *, n: int = CHIP_LOOKBACK
) -> Tuple[float, float, float, str]:
    """取「最近有三大淨買賣」的連續窗（官方欄；缺資料不硬猜散戶）。

    本機／Render 盤後若 T86 尚未寫進近幾日，會往回找仍有非零淨買賣的交易日窗。
    """
    rows = con.execute(
        "SELECT date, foreign_net, trust_net, dealer_net FROM daily_quotes "
        "WHERE stock_id=? ORDER BY date DESC LIMIT 60",
        (sid,),
    ).fetchall()
    # 找到最近一筆三者不全為 0／NULL 的日子當錨
    anchor = -1
    for i, (_d, f, t, d) in enumerate(rows):
        if abs(_num(f)) + abs(_num(t)) + abs(_num(d)) > 1e-9:
            anchor = i
            break
    if anchor < 0:
        return 0.0, 0.0, 0.0, ""
    win = rows[anchor : anchor + int(n)]
    f = sum(_num(r[1]) for r in win)
    t = sum(_num(r[2]) for r in win)
    d = sum(_num(r[3]) for r in win)
    asof_chip = str(win[0][0] or "")
    return f, t, d, asof_chip


def _chip_label(
    foreign: float, trust: float, dealer: float, *, chip_asof: str = ""
) -> str:
    """近窗三大淨買賣誰主導；無資料＝籌碼未齊（不准冒充散戶）。"""
    if abs(foreign) + abs(trust) + abs(dealer) <= 1e-9:
        return "籌碼未齊"
    parts = [
        ("外資", float(foreign)),
        ("投信", float(trust)),
        ("自營", float(dealer)),
    ]
    parts.sort(key=lambda x: x[1], reverse=True)
    top_name, top_v = parts[0]
    second_v = parts[1][1]
    tag = f"（迄{chip_asof[4:6]}/{chip_asof[6:8]}）" if len(chip_asof) == 8 else ""
    if top_v > 0 and top_v >= max(abs(second_v) * 1.25, 50.0):
        return f"{top_name}偏愛{tag}"
    if top_v > 0 and second_v > 0 and top_v + second_v > abs(parts[2][1]):
        return f"{parts[0][0]}＋{parts[1][0]}{tag}"
    if max(foreign, trust, dealer) <= 0 and min(foreign, trust, dealer) < 0:
        return f"法人偏賣／技術反彈{tag}"
    return f"偏散戶／雜訊{tag}"

def _assign_bucket(row: Wave4Row) -> Tuple[str, str]:
    """intervene＝值得介入；sprint＝短衝／搶反彈；watch＝可畫仍觀察。

    路徑：搶次級四浪高；連四浪低都過不了＝偏沒力。
    實質收入好（台光電／光聖）不准排除；被動元件這類＝比較搶反彈。
    """
    rebound = _is_rebound_face(row)
    ai = bool(row.taught_tags) and not rebound  # 被動元件不當成長線 AI 實質臉
    room = float(row.room_to_w4_pct)
    near = int(row.bottom_near_year_ago_bars)
    chip = row.chip_label or ""
    inst = chip.startswith(("外資", "投信", "自營")) and "偏賣" not in chip
    chip_ready = chip not in ("", "籌碼未齊")
    eps_ok = bool(row.eps_profit)
    past = room <= 0
    weak = not bool(row.above_w4_low)  # 尚未過③低＝四浪低

    why_bits = [
        f"距四浪高{room:.1f}%",
        f"EPS{'獲利' if eps_ok else '無／虧'}{'' if row.eps_last is None else f'({row.eps_last:.2f})'}",
        chip or "籌碼未齊",
    ]
    if row.taught_tags:
        why_bits.append("鏈:" + "/".join(row.taught_tags[:2]))
    if near >= 2:
        why_bits.append(f"底爆量{near}根")
    elif near == 1:
        why_bits.append("底單爆量")
    if past:
        why_bits.append("已過四浪高")
    if rebound:
        why_bits.append("被動元件型＝搶反彈")

    quality = bool(
        eps_ok
        and not rebound
        and (ai or row.stock_id in QUALITY_HORIZON_ZH)
    )
    # 已過四浪高就不要再疊「未過四浪低」文案
    if not past and weak and quality:
        why_bits.append("未過四浪低仍留（實質不准排除）")
    elif not past and weak:
        why_bits.append("未過四浪低＝偏沒力")
    hz = QUALITY_HORIZON_ZH.get(row.stock_id)
    if hz:
        why_bits.append(hz.split("；")[-1] if "；" in hz else hz)

    # 被動元件：永遠搶反彈短衝，不准進值得介入（含已過四浪高）
    if rebound:
        return "sprint", "；".join(why_bits) + (
            "→已過四浪仍搶反彈臉" if past else "→搶反彈短衝"
        )

    # 連四浪低都過不了：雜訊／無實質 → 弱；有實質＋鏈＝不准排除，繼續走介入閘
    if weak and not past and not quality:
        return "sprint", "；".join(why_bits) + "→連四浪低都過不了＝弱"

    # 短衝：缺 EPS 保護＝技術反彈臉；或深空無鏈無量
    if (not eps_ok) or (room > 55 and not ai and near == 0):
        return "sprint", "；".join(why_bits) + "→短衝技術臉"

    # 法人偏賣但有 EPS／鏈：不當短衝，先觀察（股性偏賣≠沒價值）
    if "偏賣" in chip and eps_ok:
        if ai and 5 <= room <= 50 and not past:
            return "watch", "；".join(why_bits) + "→有實質但近窗法人偏賣"
        return "watch", "；".join(why_bits) + "→法人偏賣改觀察"

    # 值得介入：EPS＋（實質鏈或機構偏愛）＋合理距四浪高（約5–50%）
    if eps_ok and (ai or inst) and (15 <= room <= 45 or (near >= 1 and 8 <= room <= 55)) and not past:
        return "intervene", "；".join(why_bits) + "→實質＋鏈／籌碼"
    if eps_ok and ai and 5 <= room <= 55 and not past:
        return "intervene", "；".join(why_bits) + "→實質＋AI鏈"
    if eps_ok and inst and chip_ready and 8 <= room <= 50 and not past:
        return "intervene", "；".join(why_bits) + "→實質＋機構偏愛"

    if past and eps_ok and ai:
        return "watch", "；".join(why_bits) + "→已過四浪仍觀察"
    return "watch", "；".join(why_bits) + "→可畫觀察"


def enrich_hits(
    hits: Sequence[Dict[str, Any]],
    *,
    db_path: Path = DB_DEFAULT,
) -> List[Wave4Row]:
    taught_map = _taught_ai_sids()
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    out: List[Wave4Row] = []
    try:
        for h in hits:
            sid = str(h.get("stock_id") or "")
            if not sid:
                continue
            eps_v, eps_ok = _eps_last(con, sid)
            f, t, d, chip_asof = _chip_sums(con, sid)
            tags = list(taught_map.get(sid) or [])
            chain = _industry(con, sid)
            above = h.get("above_w4_low")
            if above is None and h.get("wave3_low") is not None:
                above = float(h.get("close") or 0) + 1e-9 >= float(h.get("wave3_low") or 0)
            row = Wave4Row(
                stock_id=sid,
                stock_name=str(h.get("stock_name") or sid),
                market=str(h.get("market") or ""),
                close=float(h.get("close") or 0),
                wave4=float(h.get("wave4") or 0),
                wave3_low=float(h.get("wave3_low") or 0),
                room_to_w4_pct=float(h.get("room_to_w4_pct") or 0),
                above_w4_low=bool(True if above is None else above),
                bottom_near_year_ago_bars=int(h.get("bottom_near_year_ago_bars") or 0),
                score=float(h.get("score") or 0),
                eps_last=eps_v,
                eps_profit=eps_ok,
                taught_tags=tags,
                industry_chain=chain,
                chip_label=_chip_label(f, t, d, chip_asof=chip_asof),
                foreign_net_sum=f,
                trust_net_sum=t,
                dealer_net_sum=d,
            )
            bucket, why = _assign_bucket(row)
            row.bucket = bucket
            row.why_zh = why
            out.append(row)
    finally:
        con.close()
    return out


def build_wave4_desk(
    db_path: Path | str = DB_DEFAULT,
    *,
    top_n: int = 200,
) -> Dict[str, Any]:
    path = Path(db_path)
    scanned = scan(path, top_n=int(top_n), limit=0, market=None)
    hits = list(scanned.get("hits") or [])
    rows = enrich_hits(hits, db_path=path)
    intervene = [r for r in rows if r.bucket == "intervene"]
    sprint = [r for r in rows if r.bucket == "sprint"]
    watch = [r for r in rows if r.bucket == "watch"]

    def _sort(rs: List[Wave4Row]) -> List[Wave4Row]:
        return sorted(
            rs,
            key=lambda r: (
                -int(r.bottom_near_year_ago_bars),
                -float(r.score),
                abs(float(r.room_to_w4_pct) - 25.0),
                r.stock_id,
            ),
        )

    intervene, sprint, watch = _sort(intervene), _sort(sprint), _sort(watch)
    return {
        "ok": bool(scanned.get("ok")),
        "asof": scanned.get("asof"),
        "as_of_taipei": datetime.now(TAIPEI).isoformat(timespec="seconds"),
        "title_zh": "次級四浪",
        "not_buy_signal": True,
        "rule_zh": (
            "可畫＝五波下跌走完、正在反彈；要搶的是次級四浪高；"
            "連四浪低（③低）都過不了／當天下來＝偏沒力；"
            "實質收入好（台光電／光聖型）絕不准因未過四浪低排除；"
            "被動元件這類比較是搶反彈短衝臉。"
            "母體全收後再依EPS／鏈／股性分級。雙爆更好、單爆也可。觀察非買訊。"
        ),
        "chip_rule_zh": (
            f"股性＝近{CHIP_LOOKBACK}日官方 foreign_net／trust_net／dealer_net 加總誰主導；"
            "不准畫假主力成本。"
        ),
        "quality_horizon_zh": dict(QUALITY_HORIZON_ZH),
        "n_universe": scanned.get("n_universe"),
        "n_hits": len(rows),
        "n_intervene": len(intervene),
        "n_sprint": len(sprint),
        "n_watch": len(watch),
        "intervene": [asdict(r) for r in intervene],
        "sprint": [asdict(r) for r in sprint],
        "watch": [asdict(r) for r in watch],
        "ai_taught_groups": list(AI_TAUGHT_GROUPS),
    }


def format_wave4_desk_html(payload: Dict[str, Any], *, max_each: int = 12) -> str:
    if not payload or not payload.get("ok"):
        return "次級四浪目前組不出名單（基準日或庫異常）。觀察非買訊。"
    asof = str(payload.get("asof") or "")
    lines = [
        f"<b>次級四浪</b>（{asof[:4]}/{asof[4:6]}/{asof[6:8]} 盤後母體）",
        "觀察非買訊。要搶＝次級四浪高；連四浪低都過不了／當天下來＝偏沒力。",
        "實質好（台光電／光聖）不排除；被動元件這類＝搶反彈。",
        (
            f"可畫 {payload.get('n_hits')}｜"
            f"值得介入 {payload.get('n_intervene')}｜"
            f"短衝 {payload.get('n_sprint')}｜"
            f"觀察 {payload.get('n_watch')}"
        ),
        "",
        "<b>值得介入</b>（實質EPS＋鏈／籌碼）",
    ]
    intervene = list(payload.get("intervene") or [])[: int(max_each)]
    if not intervene:
        lines.append("（尚無）")
    for r in intervene:
        tags = "/".join(r.get("taught_tags") or []) or "—"
        lines.append(
            f"<code>{r['stock_id']}</code> {r['stock_name']} "
            f"距{r['room_to_w4_pct']:.0f}% {r.get('chip_label') or ''} "
            f"EPS{r.get('eps_last') if r.get('eps_last') is not None else '—'} "
            f"{tags}"
        )
    lines.extend(["", "<b>短衝搶一波</b>（技術反彈／弱EPS）"])
    sprint = list(payload.get("sprint") or [])[: int(max_each)]
    if not sprint:
        lines.append("（尚無）")
    for r in sprint:
        lines.append(
            f"<code>{r['stock_id']}</code> {r['stock_name']} "
            f"距{r['room_to_w4_pct']:.0f}% {r.get('chip_label') or ''} "
            f"EPS{r.get('eps_last') if r.get('eps_last') is not None else '—'}"
        )
    lines.extend(
        [
            "",
            "股性看近10日外資／投信／自營淨買賣；買訊仍只認獲利剛離零／已過閘紅箭頭。",
        ]
    )
    return "\n".join(lines)


def format_wave4_hub_html() -> str:
    """按「次級四浪」後第一頁：兩路分流說明（話筒約18全形寬）。"""
    return "\n".join(
        [
            "<b>次級四浪</b>（觀察非買訊）",
            "① 打代號／股名：辨識後請你確認，",
            "一次兩張：次級四浪圖＋結構圖（同路上大量區日）。",
            "② 實質十檔：有實質獲利，",
            "最優先出10檔＋次級四浪圖，可翻頁。",
            "盤中距離用現價；圖用已收日K。",
            "買訊仍只認獲利剛離零／已過閘紅箭頭。",
        ]
    )



def get_wave4_desk_cached(
    db_path: Path | str = DB_DEFAULT, *, top_n: int = 200, force: bool = False
) -> Dict[str, Any]:
    path = str(Path(db_path))
    now = time.time()
    hit = _DESK_CACHE.get("payload")
    if (
        not force
        and hit
        and _DESK_CACHE.get("key") == path
        and now - float(_DESK_CACHE.get("ts") or 0) < _DESK_TTL_SEC
    ):
        return hit
    # 雙重檢查：冷 miss 只准一人建桌，避免多線 stampede 重複 scan
    with _DESK_CACHE_LOCK:
        now = time.time()
        hit = _DESK_CACHE.get("payload")
        if (
            not force
            and hit
            and _DESK_CACHE.get("key") == path
            and now - float(_DESK_CACHE.get("ts") or 0) < _DESK_TTL_SEC
        ):
            return hit
        payload = build_wave4_desk(path, top_n=int(top_n))
        _DESK_CACHE["key"] = path
        _DESK_CACHE["ts"] = time.time()
        _DESK_CACHE["payload"] = payload
        return payload


def refresh_row_bucket(row: Dict[str, Any]) -> Dict[str, Any]:
    """現價改了 room／above_w4_low 後，分級桶與 why 必須重算，不准留收盤舊文案。"""
    out = dict(row)
    if "eps_profit" in out:
        eps_ok = bool(out.get("eps_profit"))
    else:
        try:
            eps_ok = float(out.get("eps_last") or 0) > 0
        except (TypeError, ValueError):
            eps_ok = False
    wr = Wave4Row(
        stock_id=str(out.get("stock_id") or ""),
        stock_name=str(out.get("stock_name") or ""),
        market=str(out.get("market") or ""),
        close=float(out.get("close") or 0),
        wave4=float(out.get("wave4") or 0),
        wave3_low=float(out.get("wave3_low") or 0),
        room_to_w4_pct=float(out.get("room_to_w4_pct") or 0),
        above_w4_low=bool(out.get("above_w4_low", True)),
        bottom_near_year_ago_bars=int(out.get("bottom_near_year_ago_bars") or 0),
        score=float(out.get("score") or 0),
        eps_last=out.get("eps_last"),
        eps_profit=eps_ok,
        taught_tags=list(out.get("taught_tags") or []),
        industry_chain=str(out.get("industry_chain") or ""),
        chip_label=str(out.get("chip_label") or ""),
        foreign_net_sum=float(out.get("foreign_net_sum") or 0),
        trust_net_sum=float(out.get("trust_net_sum") or 0),
        dealer_net_sum=float(out.get("dealer_net_sum") or 0),
    )
    bucket, why = _assign_bucket(wr)
    out["bucket"] = bucket
    out["why_zh"] = why
    return out


def apply_live_close(row: Dict[str, Any], live_close: float) -> Dict[str, Any]:
    """盤中 B：用現價重算距四浪高／是否過四浪低；不重畫五波；分級同步重算。"""
    px = float(live_close or 0)
    w4 = float(row.get("wave4") or 0)
    l3 = float(row.get("wave3_low") or 0)
    if px <= 0 or w4 <= 0:
        return dict(row)
    out = dict(row)
    out["close"] = px
    out["room_to_w4_pct"] = round((w4 - px) / px * 100.0, 2)
    if l3 > 0:
        out["above_w4_low"] = px + 1e-9 >= l3
    out["live_px"] = True
    return refresh_row_bucket(out)


def overlay_live_on_rows(
    rows: Sequence[Dict[str, Any]],
    db_path: Path | str = DB_DEFAULT,
    *,
    max_workers: int = _LIVE_OVERLAY_WORKERS,
    quote_timeout_sec: float = _LIVE_QUOTE_TIMEOUT_SEC,
) -> Tuple[List[Dict[str, Any]], bool]:
    """開市合併窗才抓現價；失敗／逾時就保留收盤臉（不准假現價）。

    十檔有界並行抓價（workers 上限 8），避免逐檔串行拖慢話筒。
    """
    try:
        from live_quote import fetch_lookup_quote, is_live_merge_window
    except Exception:
        return [dict(r) for r in rows], False
    if not is_live_merge_window():
        return [dict(r) for r in rows], False
    path = str(db_path)
    base = [dict(r) for r in rows]
    if not base:
        return base, False

    def _px(r: Dict[str, Any]) -> float:
        sid = str(r.get("stock_id") or "")
        mkt = str(r.get("market") or "")
        if not sid:
            return 0.0
        try:
            rt = fetch_lookup_quote(sid, mkt, path) or {}
            return float(rt.get("close") or 0)
        except Exception:
            return 0.0

    prices = [0.0] * len(base)
    workers = max(1, min(8, int(max_workers or _LIVE_OVERLAY_WORKERS), len(base)))
    to = float(quote_timeout_sec or _LIVE_QUOTE_TIMEOUT_SEC)
    pool = ThreadPoolExecutor(max_workers=workers)
    try:
        futs = {pool.submit(_px, r): i for i, r in enumerate(base)}
        done, not_done = wait(futs, timeout=to)
        for fut in done:
            i = futs[fut]
            try:
                prices[i] = float(fut.result() or 0)
            except Exception:
                prices[i] = 0.0
        for fut in not_done:
            prices[futs[fut]] = 0.0  # 逾時 → 收盤臉
    finally:
        # 不快等慢線；HTTP 仍受 MIS connect/read timeout 綁住
        pool.shutdown(wait=False, cancel_futures=True)
    out: List[Dict[str, Any]] = []
    any_live = False
    for r, px in zip(base, prices):
        if px > 0:
            out.append(apply_live_close(r, px))
            any_live = True
        else:
            out.append(r)  # 保留原收盤 close，不寫假價
    return out, any_live


def intervene_page(
    payload: Dict[str, Any], page: int = 0, *, page_size: int = PAGE_SIZE
) -> Tuple[List[Dict[str, Any]], int, bool]:
    """回 (本頁列, 總頁數, 還有下一頁)。"""
    all_rows = list(payload.get("intervene") or [])
    n = len(all_rows)
    ps = max(1, int(page_size))
    pages = max(1, (n + ps - 1) // ps) if n else 1
    p = max(0, min(int(page), pages - 1))
    sl = all_rows[p * ps : (p + 1) * ps]
    has_next = (p + 1) * ps < n
    return sl, pages, has_next


def format_wave4_page_html(
    payload: Dict[str, Any],
    rows: Sequence[Dict[str, Any]],
    *,
    page: int = 0,
    pages: int = 1,
    live: bool = False,
) -> str:
    asof = str(payload.get("asof") or "")
    head = f"{asof[:4]}/{asof[4:6]}/{asof[6:8]}" if len(asof) == 8 else asof
    lines = [
        f"<b>次級四浪・實質十檔</b>",
        f"{head}｜第{int(page)+1}/{int(pages)}頁",
        "觀察非買訊。有實質獲利且最優。",
        "結構圖接著送。",
        "被動元件搶反彈不進這頁。",
        "盤中距離＝現價。" if live else "距離＝母體收盤臉。",
        f"實質可翻共{payload.get('n_intervene') or 0}檔。",
        "",
    ]
    if not rows:
        lines.append("（本頁尚無）")

    def _pad_name(name: str, width: int = 4) -> str:
        """股名補全形空白到固定寬，讓「距％」上下對齊。"""
        s = str(name or "")
        pad = max(0, int(width) - len(s))
        return s + ("　" * pad)

    for r in rows:
        tags = "/".join(r.get("taught_tags") or []) or "—"
        live_tag = "・現" if r.get("live_px") else ""
        low_tag = "" if r.get("above_w4_low", True) else "・未過低"
        eps = r.get("eps_last")
        eps_s = f"{eps:.2f}" if isinstance(eps, (int, float)) else "—"
        room_i = int(round(float(r.get("room_to_w4_pct") or 0)))
        # 兩行：代號名距％｜EPS／鏈；％右對齊兩位數格
        lines.append(
            f"<code>{r.get('stock_id')}</code> {_pad_name(str(r.get('stock_name') or ''))}"
            f"　距{room_i:2d}%{live_tag}{low_tag}"
        )
        lines.append(f"EPS{eps_s} {tags}")
    lines.append("")
    lines.append("點代號看出結構。")
    lines.append("買訊仍只認獲利剛離零／已過閘紅箭頭。")
    return "\n".join(lines)



def find_wave4_row(payload: Dict[str, Any], stock_id: str) -> Optional[Dict[str, Any]]:
    sid = str(stock_id or "").strip()
    if not sid:
        return None
    for bucket in ("intervene", "sprint", "watch"):
        for r in payload.get(bucket) or []:
            if str(r.get("stock_id") or "") == sid:
                return dict(r)
    return None


def format_wave4_one_html(row: Dict[str, Any], *, live: bool = False) -> str:
    sid = str(row.get("stock_id") or "")
    name = str(row.get("stock_name") or sid)
    w4 = float(row.get("wave4") or 0)
    l3 = float(row.get("wave3_low") or 0)
    close = float(row.get("close") or 0)
    room = float(row.get("room_to_w4_pct") or 0)
    hz = QUALITY_HORIZON_ZH.get(sid, "")
    past = room <= 0
    low_line = (
        "現價已過／觸及次級四浪高"
        if past
        else (
            "已過四浪低"
            if row.get("above_w4_low", True)
            else "尚未過四浪低"
        )
    )
    bucket_zh = {
        "intervene": "值得介入",
        "sprint": "短衝／搶反彈",
        "watch": "觀察",
    }.get(str(row.get("bucket") or ""), str(row.get("bucket") or "—"))
    lines = [
        f"<b>次級四浪・{sid} {name}</b>",
        "觀察非買訊。要搶＝次級四浪高；",
        "連四浪低都過不了／當天下來＝偏沒力。",
        f"現價 {close:g}" if live or row.get("live_px") else f"收 {close:g}",
        f"四浪高 {w4:g}｜四浪低 {l3:g}",
        f"距高 {room:.1f}%",
        low_line,
        f"分級：{bucket_zh}",
    ]

    def _disp(s: str) -> int:
        return sum(2 if ord(c) > 127 else 1 for c in s)

    def _wrap_bits(text: str) -> None:
        """以 ；→： 切段後併到 ≤36 disp；括註不拆孤行。"""
        raw = (
            str(text or "")
            .replace("；", "；\0")
            .replace("→", "\0→")
            .replace("：", "：\0")
        )
        parts = [x.strip() for x in raw.split("\0") if x.strip()]
        chunk = ""
        for part in parts:
            trial = f"{chunk}{part}" if chunk else part
            if chunk and _disp(trial) > 36:
                lines.append(chunk)
                chunk = part
            else:
                chunk = trial
            while _disp(chunk) > 36:
                cut = False
                acc = ""
                for i, ch in enumerate(chunk):
                    acc2 = acc + ch
                    if _disp(acc2) > 36 and acc:
                        brk = max((acc.rfind(c) for c in "、／。，"), default=-1)
                        if brk >= 4:
                            lines.append(acc[: brk + 1])
                            chunk = acc[brk + 1 :] + chunk[i:]
                        else:
                            lines.append(acc)
                            chunk = chunk[i:]
                        cut = True
                        break
                    acc = acc2
                if not cut:
                    break
        if chunk:
            lines.append(chunk)

    why = str(row.get("why_zh") or "").strip()
    if why:
        _wrap_bits(why)
    if hz:
        _wrap_bits(hz)
    lines.append("買訊仍只認獲利剛離零／已過閘紅箭頭。")
    return "\n".join(lines)


def paint_wave4_chart(
    stock_id: str,
    *,
    db_path: Path | str = DB_DEFAULT,
    out_dir: Path | str,
    tag: str = "",
    header_style: str = "A",
) -> Optional[Path]:
    """渲一張次級四浪結構樣張；失敗回 None（不准假圖）。

    必須走 wayne_navigator.run_mpl_paint（全站單一 paint worker），
    不准自開 ThreadPool 並行踩 matplotlib／FreeType。
    """
    sid = str(stock_id or "").strip()
    if not sid:
        return None
    out = Path(out_dir) / f"wave4_{sid}_{tag or 'x'}.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    style = str(header_style or "A").upper()

    def _do() -> Optional[Path]:
        from scripts.paint_focus_target_sample import paint

        paint(sid, out, db_path=Path(db_path), header_style=style)
        if out.is_file() and out.stat().st_size > 12_000:
            return out
        return None

    try:
        from wayne_navigator import run_mpl_paint

        return run_mpl_paint(_do)
    except Exception:
        try:
            # 備援：已在 paint worker 內或匯入失敗時仍試一次同步
            return _do()
        except Exception:
            return None


def paint_wave4_one_pair(
    stock_id: str,
    *,
    db_path: Path | str = DB_DEFAULT,
    out_dir: Path | str,
    stock_name: str = "",
    tag: str = "one",
    header_style: str = "B",
) -> List[Dict[str, str]]:
    """單檔一次兩張：①次級四浪圖 ②查股同款結構圖（同路上大量區日／高低）。

    同一 mpl worker 內依序渲，不准並行踩 FreeType。
    結構圖 force_vol_zone＝四浪圖 pick_path_vol_zone 結果（反彈壓／下降撐壓）。
    """
    sid = str(stock_id or "").strip()
    if not sid:
        return []
    name = str(stock_name or "").strip() or sid
    out_dir_p = Path(out_dir)
    out_dir_p.mkdir(parents=True, exist_ok=True)
    style = str(header_style or "B").upper()
    wave_out = out_dir_p / f"wave4_{sid}_{tag or 'one'}.png"
    struct_out = out_dir_p / f"struct_{sid}_{tag or 'one'}.png"

    def _do() -> List[Dict[str, str]]:
        charts: List[Dict[str, str]] = []
        force_zone: Dict[str, Any] | None = None
        face_asof = ""
        try:
            from scripts.paint_focus_target_sample import paint

            meta = paint(sid, wave_out, db_path=Path(db_path), header_style=style)
            z = (meta or {}).get("zone") if isinstance(meta, dict) else None
            if isinstance(z, dict) and z.get("date") and z.get("high") and z.get("low"):
                force_zone = dict(z)
            if isinstance(meta, dict):
                face_asof = str(meta.get("asof") or "").replace("-", "")[:8]
            if wave_out.is_file() and wave_out.stat().st_size > 12_000:
                charts.append(
                    {
                        "stock_id": sid,
                        "stock_name": name,
                        "path": str(wave_out),
                        "kind": "wave4",
                        "caption": f"{sid} {name} 次級四浪（觀察非買訊）",
                    }
                )
        except Exception:
            pass
        try:
            from three_in_one_chart import render_lookup_structure_result

            path, cap = render_lookup_structure_result(
                sid,
                name,
                str(db_path),
                str(struct_out),
                force_vol_zone=force_zone,
                face_asof=face_asof,
            )
            if path and Path(path).is_file() and Path(path).stat().st_size > 8_000:
                charts.append(
                    {
                        "stock_id": sid,
                        "stock_name": name,
                        "path": str(path),
                        "kind": "struct",
                        "caption": str(cap or f"{sid} {name} 結構圖")[:200],
                    }
                )
        except Exception:
            pass
        return charts

    try:
        from wayne_navigator import run_mpl_paint

        return list(run_mpl_paint(_do) or [])
    except Exception:
        try:
            return _do()
        except Exception:
            return []


def paint_wave4_page_charts(
    rows: Sequence[Dict[str, Any]],
    *,
    db_path: Path | str = DB_DEFAULT,
    out_dir: Path | str,
    page: int = 0,
    max_workers: int = CHART_PAINT_WORKERS,
) -> List[Dict[str, str]]:
    """實質十檔附圖：逐檔走單一 mpl worker；缺圖略過。回 [{sid,name,path,caption}, ...]。"""
    _ = max_workers  # 保留參數相容；不准再平行踩圖
    out_dir_p = Path(out_dir)
    out_dir_p.mkdir(parents=True, exist_ok=True)
    tag = f"p{int(page)}"
    out: List[Dict[str, str]] = []
    for r in rows or []:
        sid = str(r.get("stock_id") or "").strip()
        if not sid:
            continue
        name = str(r.get("stock_name") or sid)
        room = float(r.get("room_to_w4_pct") or 0)
        live = "・現" if r.get("live_px") else ""
        cap = f"{sid} {name} 距{room:.0f}%{live}（觀察非買訊）"
        p = paint_wave4_chart(sid, db_path=db_path, out_dir=out_dir_p, tag=tag)
        if not p:
            continue
        out.append(
            {
                "stock_id": sid,
                "stock_name": name,
                "path": str(p),
                "caption": cap[:200],
            }
        )
    return out
