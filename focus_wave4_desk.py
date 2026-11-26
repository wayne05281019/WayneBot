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

# 使用者鎖：實質收入好的教過臉，未過四浪低也絕不准排除（觀察非買訊）。
# horizon＝他口述遠距位，不是進場價、不是買訊。
QUALITY_HORIZON_ZH: Dict[str, str] = {
    "2383": "台光電實質收入好：未過四浪低也不排除；12個月內看8000（口述遠距，非買訊）",
    "1815": "光聖實質臉：未過四浪低也不排除；一定過2500（口述遠距，非買訊）",
}
# 被動元件這類＝比較是搶反彈／短衝臉，不是台光電那種實質長線臉。
REBOUND_TAUGHT_TAGS = frozenset({"被動元件"})


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
    if weak and quality:
        why_bits.append("未過四浪低仍留（實質收入好不准排除）")
    elif weak:
        why_bits.append("未過四浪低＝偏沒力")
    hz = QUALITY_HORIZON_ZH.get(row.stock_id)
    if hz:
        why_bits.append(hz.split("；")[-1] if "；" in hz else hz)

    # 被動元件這類：比較是搶反彈，不進值得介入長線桶
    if rebound and not past:
        return "sprint", "；".join(why_bits) + "→搶反彈短衝"

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
