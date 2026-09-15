# -*- coding: utf-8 -*-
"""大盤波浪位階：只跟飆大自己點過的標籤走。

從他講過的時間往後對質：後來再點名，就拿先前那筆跟官方柱比。
不准發明 5／9 段、不准把波浪套個股、不准拿教科書升浪。
不是買訊。
"""
from __future__ import annotations

import os
import re
import sqlite3
from typing import Any, Dict, List, Optional, Sequence, Tuple

_WAVE_ASK = re.compile(
    r"(現在波浪位階|哪個位階|波浪位階|以波浪|"
    r"細微波|右肩型態|大盤現在|現在大盤|"
    r"上昇|上升還是下降|升浪還是|哪一浪|哪一波|"
    r"C-1|C-2|C-3|位階二|修正末端|測底)"
)
_EYES_ASK = re.compile(
    r"(技術線圖|他看到什麼|看大盤轉折|轉折最準|沒人比|"
    r"怎麼判.{0,8}(大盤|轉折|位階)|用了?(什麼|啥)工具|"
    r"大盤對比類股|類股對比個股)"
)
_SKIP_FIFTH = re.compile(r"抱到.?2027|第五波漲勢結束")
_TAGGERS: Tuple[Tuple[str, str, re.Pattern[str]], ...] = (
    ("C-3", "down", re.compile(r"C-2\s*轉\s*C-3|轉C-3")),
    ("C-1", "down", re.compile(r"C波下殺\s*C-1|走C波下殺|C-1")),
    ("第五波測底", "retest", re.compile(r"第五波.{0,8}測底|再一次測底|短線築底")),
    ("修正末端", "retest", re.compile(r"修正的?末端")),
    ("位階二", "side", re.compile(r"波浪位階二|位階二|波浪位階的\s*2")),
    ("右肩", "side", re.compile(r"做右肩|右肩型態|持續做右肩|就是做右肩")),
    ("A波低", "down_done", re.compile(r"A波低點|就是A波低")),
    ("大B波", "up", re.compile(r"大B波|走大B波")),
    ("波浪四", "down", re.compile(r"來到波浪四|波浪四點位")),
    ("頭肩底", "retest", re.compile(r"頭肩底")),
    ("第五波失敗", "down", re.compile(r"第五波.{0,10}(沒了|失敗|開始做頭)")),
)

# 他自己點名過、能對上公開文的位階帶。更早沒寫死浪名的不加。
_CURATED: Tuple[Dict[str, str], ...] = (
    {
        "date": "2025-05-19",
        "time": "10:55",
        "aid": "171472406",
        "tag": "右肩",
        "direc": "side",
        "quote": "細微波脈動結束會開始高檔震盪，以做型態右肩可能性最大。",
    },
    {
        "date": "2025-12-03",
        "time": "",
        "aid": "",
        "tag": "第五波條件",
        "direc": "up",
        "quote": "台積電 9/3 低連 11/24 低，或加權 9/3 低連 11/21 低；不破才談第五波。",
    },
    {
        "date": "2025-12-15",
        "time": "",
        "aid": "",
        "tag": "第五波失敗",
        "direc": "down",
        "quote": "1-4 重疊、軌道幾乎破壞，那組末升第五波判定失敗、開始做頭。",
    },
    {
        "date": "2026-07-07",
        "time": "",
        "aid": "",
        "tag": "第五波失敗",
        "direc": "down",
        "quote": "樂觀第五波擴延沒了，改 A-c。",
    },
    {
        "date": "2026-07-29",
        "time": "11:13",
        "aid": "181095970",
        "tag": "波浪四",
        "direc": "down",
        "quote": "大盤及台積電已經來到波浪四點位，今天第一次抄底，即會開始進行 B 波反彈。",
    },
    {
        "date": "2026-07-30",
        "time": "09:55",
        "aid": "181149602",
        "tag": "大B波",
        "direc": "up",
        "quote": "A波從 6/23～7/29。就算走大B波也是漲漲跌跌、至少 6 周，不要急著買。",
    },
    {
        "date": "2026-07-31",
        "time": "08:54",
        "aid": "181180579",
        "tag": "A波低",
        "direc": "down_done",
        "quote": "要這麼精準抓到 7/29 是 A 波低點，憑藉細微波波型。波浪沒辦法 100%，台積電＋某金融商品量價已 100% 確認。",
    },
    {
        "date": "2026-09-10",
        "time": "09:51",
        "aid": "184499206",
        "tag": "修正末端",
        "direc": "retest",
        "quote": "9/8 起 abc、當天看到 c 末端；下波起漲至少測 48218。",
    },
    {
        "date": "2026-09-11",
        "time": "08:43",
        "aid": "184526608",
        "tag": "右肩",
        "direc": "side",
        "quote": "9/3 低 45839 有守住＝右肩高有過前高、低不破前低，高檔震盪趨勢向上。細微波已走 5 段，5 或 9 無法判斷。",
    },
    {
        "date": "2026-09-11",
        "time": "17:56",
        "aid": "184545002",
        "tag": "位階二",
        "direc": "side",
        "quote": "我一直主張大盤就是做右肩，也就是走橫台震盪整理的波浪位階的 2，不是位階 3。",
    },
    {
        "date": "2026-09-12",
        "time": "10:34",
        "aid": "184545002",
        "tag": "位階二",
        "direc": "side",
        "quote": "下周要過前波高點 47578，才能維持高有過前高做右肩（還是在波浪位階二）。",
    },
    {
        "date": "2026-09-13",
        "time": "22:19",
        "aid": "184545002",
        "tag": "C-3",
        "direc": "down",
        "quote": "明天最好漲至少 500 點，否則要小心 C-2 轉 C-3。出現會發文。",
    },
    {
        "date": "2026-09-14",
        "time": "09:51",
        "aid": "184578674",
        "tag": "修正末端",
        "direc": "retest",
        "quote": "60 分最後走 1-2-3-4-5 不是 abc。最差 C-1，等 C-2 轉 C-3 再出清、目前言之過早。已到本波指數修正末端。頭肩底頸線沒破。",
    },
    {
        "date": "2026-09-14",
        "time": "21:50",
        "aid": "184578674",
        "tag": "第五波測底",
        "direc": "retest",
        "quote": "目前是對第五波再一次測底；今天就是再一次測底（或稱短線築底，等反彈）。",
    },
)

# 加權圖只畫他自己點過、能對官方柱的水平。46506 是台指日盤低，不畫在加權。
_TWII_LEVELS: Tuple[Tuple[float, str, str], ...] = (
    (39384.85, "7/29 A波低", "20260729"),
    (43500.0, "他原文C波最差", ""),
    (45839.36, "9/3低右肩", "20260903"),
    (47578.24, "9/8前波高", "20260908"),
    (48218.87, "6/23大一級前高", "20260623"),
)

EYES = (
    "他看線圖不是 KD／MACD／布林／均線——那些他當不算技術分析。"
    "順序是：先定大盤（台指期夜盤→15 分細微波 5 或 9、60 分、下降壓連他自己點過的高例如 48218；"
    "加權日K對質 45839／47578／48218；常先畫台積電兩個低連線當先行）。"
    "確認低點他明講波浪沒辦法 100%，要疊台積電量價、費半／那指、夜盤有沒有先過下降壓。"
    "類股看資金輪動、誰先過前高、這族龍頭攻還是休；個股看量先價行（爆大量日高當壓、低當撐），"
    "相對龍頭的位階，不把波浪套在那一檔。"
    "2026-07-31 他寫要這麼精準抓到 7/29 是 A 波低，憑細微波波型；官方加權當日低 39385 對得上。"
)


def is_wave_question(ask: str) -> bool:
    q = (ask or "").strip()
    if not q:
        return False
    return bool(_WAVE_ASK.search(q) or _EYES_ASK.search(q))


def _clip(text: str, n: int) -> str:
    s = " ".join(str(text or "").split())
    return s if len(s) <= n else s[: n - 1] + "…"


def _px(val: Any) -> str:
    try:
        n = float(val)
    except (TypeError, ValueError):
        return ""
    if abs(n - round(n)) < 1e-6:
        return str(int(round(n)))
    return f"{n:.2f}".rstrip("0").rstrip(".")


def _ymd(raw: Any) -> str:
    t = str(raw or "").replace("-", "")[:8]
    return t if len(t) == 8 and t.isdigit() else ""


def _spoken(raw: str) -> str:
    try:
        from biaoke_ingest import spoken_text

        return spoken_text(raw or "")
    except Exception:
        return str(raw or "")


def _tags_in(text: str) -> List[Tuple[str, str]]:
    blob = _spoken(text)
    if _SKIP_FIFTH.search(blob) and "測底" not in blob:
        blob = _SKIP_FIFTH.sub(" ", blob)
    out: List[Tuple[str, str]] = []
    seen = set()
    for tag, direc, pat in _TAGGERS:
        if tag in seen:
            continue
        if pat.search(blob):
            seen.add(tag)
            out.append((tag, direc))
    return out


def _merge(rows: List[Dict[str, str]], hit: Dict[str, str]) -> None:
    key = (hit.get("date") or "", hit.get("time") or "", hit.get("tag") or "")
    for old in rows:
        if (old.get("date") or "", old.get("time") or "", old.get("tag") or "") == key:
            if len(str(hit.get("quote") or "")) > len(str(old.get("quote") or "")):
                old.update(hit)
            return
    rows.append(hit)


def _from_rows(posts: Sequence[Dict[str, Any]]) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    for p in posts or []:
        raw = str(p.get("text") or "")
        tags = _tags_in(raw)
        if not tags:
            continue
        day = str(p.get("date") or "")
        when = str(p.get("time") or "")
        aid = str(p.get("id") or p.get("parent") or "")
        for tag, direc in tags:
            _merge(
                out,
                {
                    "date": day,
                    "time": when,
                    "aid": aid,
                    "tag": tag,
                    "direc": direc,
                    "quote": _clip(_spoken(raw), 160),
                },
            )
    return out


def _live_hits(db_path: str = "") -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    try:
        from biaoke_desk import catchup_seed_rows

        rows.extend(_from_rows(catchup_seed_rows() or []))
    except Exception:
        pass
    if db_path:
        try:
            from biaoke_desk import load_corpus

            posts = list((load_corpus(db_path) or {}).get("posts") or [])
            rows.extend(_from_rows(posts[-80:]))
        except Exception:
            pass
    return rows


def degree_hits(db_path: str = "") -> List[Dict[str, str]]:
    """時間序：他自己點過的位階。live 只補 catchup／overlay，不發明浪。"""
    rows = [dict(x) for x in _CURATED]
    for hit in _live_hits(db_path):
        _merge(rows, hit)
    rows.sort(key=lambda h: (h.get("date") or "", h.get("time") or "", h.get("aid") or ""))
    return rows


def last_two(db_path: str = "") -> Tuple[Optional[Dict[str, str]], Optional[Dict[str, str]]]:
    hits = degree_hits(db_path)
    if not hits:
        return None, None
    last = hits[-1]
    prev = None
    for h in reversed(hits[:-1]):
        if h.get("tag") != last.get("tag") or h.get("date") != last.get("date"):
            prev = h
            break
    return last, prev


def _compare(prev: Optional[Dict[str, str]], last: Optional[Dict[str, str]]) -> str:
    if not last:
        return "帶裡還沒接到他自己點名的位階，不准發明浪。"
    if not prev:
        return "這是帶裡最早一筆他自己點名的位階，前面沒得對。"
    a, b = prev.get("tag") or "", last.get("tag") or ""
    pair = (a, b)
    if pair == ("修正末端", "第五波測底") or pair == ("頭肩底", "第五波測底"):
        return (
            f"先前 {prev.get('date')} 叫{a}，後來 {last.get('date')} 收到{b}："
            "同一組細微波收斂，不是改口成大 3，也還沒發文升成 C-3。"
        )
    if a == "位階二" and b in {"修正末端", "第五波測底", "頭肩底", "C-1", "右肩"}:
        return (
            f"大一級他 {prev.get('date')} 仍叫位階二／右肩；"
            f"這一組細微波 {last.get('date')} 叫{b}。"
            "兩層並存，他慣用同一晚多標籤再用點數驗。沒把計數升成大 3。"
        )
    if a in {"波浪四", "大B波"} and b == "A波低":
        return (
            f"{prev.get('date')} 還在抄底／B 波框架，{last.get('date')} 收成 7/29 就是 A 波低——"
            "同向收斂。他自稱憑細微波抓轉折。"
        )
    if a == "A波低" and b in {"位階二", "右肩", "修正末端"}:
        return (
            f"7/29 A 波低之後，{last.get('date')} 他改叫{b}："
            "大一級還在 2，不是再數一次教科書第五波。"
        )
    if b == "C-3" and a != "C-3":
        return (
            f"{last.get('date')} 只是預告要小心 C-2 轉 C-3，不是已確認。"
            "他自己說出現會發文；後來 9/14 仍言之過早。"
        )
    if a == b:
        return f"跟 {prev.get('date')} 同一標籤「{a}」，同向，沒改口。"
    return (
        f"先前 {prev.get('date')} 點「{a}」，後來 {last.get('date')} 點「{b}」。"
        "只記他自己的標籤，不准發明中間數了幾段。"
    )


def _twii_bar(db_path: str, ymd: str) -> Dict[str, Any]:
    day = _ymd(ymd)
    if not db_path or not os.path.isfile(db_path) or not day:
        return {}
    try:
        conn = sqlite3.connect(db_path, timeout=8.0)
        try:
            row = conn.execute(
                "SELECT date, open, high, low, close FROM index_daily "
                "WHERE (symbol='TWII' OR symbol='^TWII' OR symbol='' OR symbol IS NULL) "
                "AND REPLACE(CAST(date AS TEXT),'-','')=? LIMIT 1",
                (day,),
            ).fetchone()
        except sqlite3.Error:
            row = None
        finally:
            conn.close()
    except Exception:
        return {}
    if not row:
        return {}
    return {"date": row[0], "open": row[1], "high": row[2], "low": row[3], "close": row[4]}


def _twii_latest(db_path: str) -> Dict[str, Any]:
    if not db_path or not os.path.isfile(db_path):
        return {}
    try:
        from biaoke_brain import load_index_bars

        bars = load_index_bars(db_path, n=1) or []
        return dict(bars[-1]) if bars else {}
    except Exception:
        return {}


def _broke_low_since(db_path: str, ymd: str, level: float) -> Dict[str, Any]:
    day = _ymd(ymd)
    if not db_path or not os.path.isfile(db_path) or not day:
        return {}
    try:
        conn = sqlite3.connect(db_path, timeout=8.0)
        try:
            row = conn.execute(
                "SELECT date, low, close FROM index_daily "
                "WHERE (symbol='TWII' OR symbol='^TWII') "
                "AND REPLACE(CAST(date AS TEXT),'-','')>? AND low<? "
                "ORDER BY date DESC LIMIT 1",
                (day, float(level)),
            ).fetchone()
        except sqlite3.Error:
            row = None
        finally:
            conn.close()
    except Exception:
        return {}
    if not row:
        return {}
    return {"date": row[0], "low": row[1], "close": row[2]}


def _official_bits(db_path: str) -> List[str]:
    bits: List[str] = []
    last = _twii_latest(db_path)
    if last:
        bits.append(
            f"官方加權 {last.get('date') or ''} 收 {_px(last.get('close')) or '—'} "
            f"高 {_px(last.get('high')) or '—'} 低 {_px(last.get('low')) or '—'}"
        )
        try:
            close = float(last.get("close") or 0)
            hi = float(last.get("high") or 0)
            lo = float(last.get("low") or 0)
        except (TypeError, ValueError):
            close = hi = lo = 0.0
        if close >= 45839:
            bits.append(f"收 {_px(close)} 還在他自己點的 9/3 低 45839 之上")
        elif close > 0:
            bits.append(f"收 {_px(close)} 已低於 45839，覆巢先當有事")
        broke = _broke_low_since(db_path, "20260903", 45839.36)
        if broke:
            bits.append(
                f"{broke.get('date')} 官方低 {_px(broke.get('low'))} 已低於 45839；"
                f"當日收 {_px(broke.get('close'))}。"
                "右肩「低不破前低」這根低點先當有事，他 9/14 改用頭肩底頸線沒破，兩套一起留"
            )
        if hi >= 47578:
            bits.append(f"官方高 {_px(hi)} 已過 47578，才比較像維持右肩")
        elif hi > 0:
            bits.append(f"官方高 {_px(hi)} 還沒過 47578，右肩還沒做完")
    else:
        bits.append("官方加權這顆庫還沒這列，不准自己寫點位")
    a_low = _twii_bar(db_path, "20260729")
    if a_low:
        bits.append(
            f"7/29 官方低 {_px(a_low.get('low'))}，對得上他說的 A 波低 39385"
        )
    return bits


def _direc_line(last: Dict[str, str]) -> str:
    tag = last.get("tag") or ""
    direc = last.get("direc") or ""
    if direc == "retest" or tag in {"第五波測底", "修正末端", "頭肩底"}:
        return (
            "方向：這一組細微波他點的是修正末端／測底等反彈，不是已確認大 3 推動，"
            "也不是已確認 C-3 下殺。不追高；C-2 轉 C-3 他說會發文，沒發文就不要替他升浪。"
        )
    if direc == "side" or tag in {"位階二", "右肩"}:
        return (
            "方向：大一級他點高檔震盪／右肩／位階二，趨勢他仍說向上整理。"
            "還沒過 47578 不要當成突破；破他點的右肩低才先當覆巢。"
        )
    if direc == "up" or tag == "大B波":
        return "方向：他點的是反彈／B 波向上，時間可以很長，他自己說不要急著買。"
    if direc in {"down", "down_done"}:
        return "方向：他點的是下跌段或下跌剛走完。準備下降的時間先看他有沒有發文升成 C-3。"
    return "方向：只跟他最新標籤走，不准發明升或降裡面第幾浪。"


def format_wave_head(db_path: str = "") -> str:
    """巢穴／推論用短句，不吃掉官方四路。"""
    last, prev = last_two(db_path)
    if not last:
        return "還沒接到他自己點名的大盤位階，不准發明浪。位階不講死。"
    stamp = " ".join(x for x in (last.get("date") or "", last.get("time") or "") if x)
    prev_t = f"；再前 {prev.get('date')} {prev.get('tag')}" if prev else ""
    return (
        f"現在位階 {stamp} {last.get('tag')}{prev_t}。"
        "大一級還在位階二／右肩，C-3 沒發文。位階不講死。不數 5／9 段。"
    )


def format_wave_now(db_path: str = "", *, n: int = 680) -> str:
    """口語：現在位階＝他自己最近一次怎麼點＋再前一次＋官方對質。"""
    last, prev = last_two(db_path)
    bits: List[str] = [format_wave_head(db_path)]
    if last:
        bits.append(_clip(last.get("quote") or "", 140))
    bits.append(_compare(prev, last))
    if last:
        bits.append(_direc_line(last))
    bits.append(
        "轉折錨：2026-07-31 他寫要這麼精準抓到 7/29 是 A 波低，憑細微波波型；"
        "官方加權當日低 39385 對得上。那次靠細微波＋台積電量價，不是發明公式。"
    )
    bits.extend(_official_bits(db_path))
    bits.append("同一晚可並存多標籤，用點數一驗再驗。不是買訊。")
    return _clip("。".join(b.rstrip("。") for b in bits if b), n)


def format_wave_eyes() -> str:
    return EYES


def _load_twii_bars(db_path: str, n: int = 80) -> List[Dict[str, Any]]:
    if not db_path or not os.path.isfile(db_path):
        return []
    try:
        conn = sqlite3.connect(db_path, timeout=8.0)
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                "SELECT date, open, high, low, close FROM index_daily "
                "WHERE symbol='TWII' OR symbol='^TWII' "
                "ORDER BY date DESC LIMIT ?",
                (int(n),),
            ).fetchall()
        except sqlite3.Error:
            rows = []
        finally:
            conn.close()
    except Exception:
        return []
    out = [dict(r) for r in rows]
    out.reverse()
    return out


def render_twii_degree_png(db_path: str, save_path: str) -> str:
    """加權日K＋他自己點過的水平。不數段、不畫假未來 K。"""
    bars = _load_twii_bars(db_path, n=90)
    if len(bars) < 8 or not save_path:
        return ""
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from wayne_navigator import NAV_CHART_DPI, _fp
    except Exception:
        return ""

    def _draw() -> str:
        n = len(bars)
        opens = [float(r.get("open") or r.get("close") or 0) for r in bars]
        highs = [float(r.get("high") or r.get("close") or 0) for r in bars]
        lows = [float(r.get("low") or r.get("close") or 0) for r in bars]
        closes = [float(r.get("close") or 0) for r in bars]
        ys = highs + lows
        for lv, _lab, _d in _TWII_LEVELS:
            ys.append(lv)
        ymin = min(ys) - 400
        ymax = max(ys) + 900
        os.makedirs(os.path.dirname(save_path) or ".", exist_ok=True)
        fig, ax = plt.subplots(figsize=(12.4, 7.2), dpi=NAV_CHART_DPI)
        fig.patch.set_facecolor("#ffffff")
        ax.set_facecolor("#ffffff")
        for i in range(n):
            up = closes[i] >= opens[i]
            color = "#e53935" if up else "#00897b"
            ax.vlines(i, lows[i], highs[i], color=color, linewidth=1.1, zorder=3)
            y0, y1 = sorted((opens[i], closes[i]))
            ax.add_patch(
                plt.Rectangle(
                    (i - 0.32, y0),
                    0.64,
                    max(y1 - y0, 8),
                    facecolor=color,
                    edgecolor=color,
                    linewidth=0.4,
                    zorder=4,
                )
            )
        colors = {
            "7/29 A波低": "#2e7d32",
            "他原文C波最差": "#90a4ae",
            "9/3低右肩": "#0277bd",
            "9/8前波高": "#c62828",
            "6/23大一級前高": "#6a1b9a",
        }
        styles = {
            "他原文C波最差": (0, (4, 3)),
        }
        for lv, lab, _d in _TWII_LEVELS:
            ax.axhline(
                lv,
                color=colors.get(lab, "#37474f"),
                linewidth=1.15,
                linestyle=styles.get(lab, "-"),
                zorder=2,
            )
            ax.text(
                n - 0.4,
                lv,
                f" {lab} {_px(lv)}",
                color=colors.get(lab, "#37474f"),
                fontsize=9,
                fontproperties=_fp(9, "bold"),
                va="center",
                ha="left",
                zorder=6,
            )
        last = bars[-1]
        ax.set_title(
            f"加權官方日K　他自己點過的水平　{_ymd(last.get('date'))} 收 {_px(last.get('close'))}",
            fontproperties=_fp(13, "bold"),
            color="#1f2933",
            loc="left",
            pad=18,
        )
        ax.text(
            0.0,
            1.04,
            "不是 15 分、不數 5／9 段、不是買訊。43500 是他原文最差情境，不是官方收。",
            transform=ax.transAxes,
            fontproperties=_fp(9),
            color="#546e7a",
        )
        ax.set_xlim(-0.6, n + 8)
        ax.set_ylim(ymin, ymax)
        ax.grid(True, linestyle=(0, (1.2, 1.6)), linewidth=0.5, color="#bdbdbd")
        step = max(n // 7, 4)
        ticks = list(range(0, n, step))
        if n - 1 not in ticks:
            ticks.append(n - 1)
        labels = []
        for i in ticks:
            d = str(bars[i].get("date") or "")
            d = _ymd(d)
            labels.append(f"{d[4:6]}/{d[6:8]}" if len(d) == 8 else d)
        ax.set_xticks(ticks)
        ax.set_xticklabels(labels, fontproperties=_fp(10, "bold"))
        ax.tick_params(labelsize=10)
        for lab in ax.get_yticklabels():
            lab.set_fontproperties(_fp(10, "bold"))
        fig.subplots_adjust(left=0.07, right=0.82, top=0.84, bottom=0.08)
        fig.savefig(save_path, dpi=NAV_CHART_DPI, facecolor=fig.get_facecolor())
        plt.close(fig)
        return save_path if os.path.isfile(save_path) else ""

    try:
        return _draw()
    except Exception:
        return ""


def build_twii_degree_chart(db_path: str, save_path: str) -> Dict[str, Any]:
    path = render_twii_degree_png(db_path, save_path)
    last, prev = last_two(db_path)
    cap_bits = [
        "加權官方日K＋他自己點過的水平（不是15分、不是介紹圖／決策卡）",
        format_wave_now(db_path, n=420),
    ]
    if last:
        cap_bits.append(f"最新標籤 {last.get('date')} {last.get('tag')}")
    if prev:
        cap_bits.append(f"再前 {prev.get('date')} {prev.get('tag')}")
    cap_bits.append("不數 5／9 段。這不是買訊。")
    return {
        "ok": bool(path),
        "path": path or "",
        "caption": _clip("\n".join(cap_bits), 900),
    }
