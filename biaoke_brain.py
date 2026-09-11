# -*- coding: utf-8 -*-
"""飆大對話腦：公開文思考套官方日 K／大盤。不是買訊、不進海選。

公開文有寫過就引原文。沒寫過的檔（例如藝舍-KY）仍用同一套框架看官方 K，
不說「不猜」。止跌只講結構條件，不給保證日期。食衣住行不答。
"""
from __future__ import annotations

import os
import re
import sqlite3
from typing import Any, Dict, List, Optional, Sequence, Tuple

from tg_layout import html_escape

PENDING = "biaoke:chat"
DISCLAIMER = (
    "這不是買訊。問句由這顆對話腦即時彙整後回你。"
    "資料庫沒點名的檔也用同一套框架，可能看錯。"
)
OFFTOPIC = "這區只談台股／美股／大盤／個股結構。食衣住行不問這邊。"
WINDOW_OPEN = "在。打字或語音都行。"
CHAT_HINT = WINDOW_OPEN

_TICKER = re.compile(r"\b(\d{3,6}[A-Za-z]?)\b", re.I)
_OFF = re.compile(
    r"(吃飯|晚餐|午餐|早餐|宵夜|菜單|食譜|衣服|穿搭|外套|住哪|房租|"
    r"天氣|電影|追劇|約會|戀愛|減肥|旅遊|機票|怎麼煮|幾點睡|幾點吃|"
    r"吃什麼|吃啥|今晚吃|穿什麼)"
)
_ON = re.compile(
    r"(股|盤|市|價|量|漲|跌|K線|加權|台指|費半|夜盤|細微|買點|賣點|止跌|"
    r"反彈|那斯達克|那指|標普|道瓊|輝達|台積|記憶體|散熱|光通|KY|ETF|"
    r"連買|海選|美股|台股|大盤|族群|支撐|壓力|波浪|量價|空頭|多頭)"
)
_MKT = re.compile(
    r"(大盤|台股|美股|止跌|反彈|連跌|費半|那指|那斯達克|標普|道瓊|"
    r"夜盤|加權|空頭|多頭|何時.*止|哪時候.*止|大概.*止|什麼時候.*[漲跌止])"
)
_HI = re.compile(
    r"^(你好|哈囉|嗨|在嗎|在不在|早安|午安|晚安|嘿|嘿啊|嗨嗨|hi|hello|hey)[\s！!。.~～]*$",
    re.I,
)
_FILL = re.compile(
    r"^(飆大|飆客|AI飆客)\s*|"
    r"(能不能買|可以買嗎|該買嗎|會不會跌|幫我看|分析一下|怎麼看|"
    r"的走勢|這檔|看看)"
)

def is_desk_query(ask: str) -> bool:
    """只有空字串才出開場 stub。怎麼觀察／去年年底當問句走對話腦。"""
    return not (ask or "").strip()


def is_offtopic(ask: str) -> bool:
    q = (ask or "").strip()
    if not q:
        return False
    if _ON.search(q) or _TICKER.search(q):
        return False
    return bool(_OFF.search(q))


def is_market_question(ask: str) -> bool:
    return bool(_MKT.search(ask or ""))


def _ymd(raw: Any) -> str:
    t = str(raw or "").replace("-", "")[:8]
    if len(t) == 8 and t.isdigit():
        return f"{t[:4]}-{t[4:6]}-{t[6:8]}"
    return str(raw or "").strip()


def _px(val: Any) -> str:
    try:
        n = float(val)
    except (TypeError, ValueError):
        return "—"
    if abs(n - round(n)) < 1e-9:
        return str(int(round(n)))
    return f"{n:.2f}".rstrip("0").rstrip(".")


def _pct(val: Any) -> str:
    try:
        n = float(val)
    except (TypeError, ValueError):
        return "—"
    sign = "＋" if n > 0 else ""
    return f"{sign}{n:.2f}%".replace("＋-", "−").replace("-", "−")


def stock_query(ask: str) -> str:
    q = (ask or "").strip()
    q = re.sub(r"^(飆大|飆客|AI飆客)\s*", "", q)
    q = _FILL.sub("", q)
    q = re.sub(r"(大概|何時|哪時候|什麼時候|止跌|會不會|嗎|呢)+", " ", q)
    return re.sub(r"\s+", " ", q).strip(" 　,，、?")


def load_bars(db_path: str, stock_id: str, *, n: int = 80) -> List[Dict[str, Any]]:
    if not db_path or not os.path.isfile(db_path) or not stock_id:
        return []
    conn = sqlite3.connect(db_path, timeout=15.0)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT date, stock_id, stock_name, open, high, low, close, volume, pct_change
            FROM daily_quotes
            WHERE stock_id=?
            ORDER BY date DESC
            LIMIT ?
            """,
            (str(stock_id), int(n)),
        ).fetchall()
    except sqlite3.OperationalError:
        rows = []
    finally:
        conn.close()
    out = [dict(r) for r in rows]
    out.reverse()
    return out


def load_index_bars(db_path: str, *, n: int = 40) -> List[Dict[str, Any]]:
    if not db_path or not os.path.isfile(db_path):
        return []
    conn = sqlite3.connect(db_path, timeout=15.0)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT date, close, pct_change, high, low
            FROM index_daily
            WHERE symbol='TWII' OR symbol='' OR symbol IS NULL
            ORDER BY date DESC
            LIMIT ?
            """,
            (int(n),),
        ).fetchall()
    except sqlite3.OperationalError:
        rows = []
    finally:
        conn.close()
    out = [dict(r) for r in rows]
    out.reverse()
    return out


def _direct_lookup(db_path: str, query: str, *, limit: int = 8) -> List[Dict[str, Any]]:
    q = (query or "").strip()
    if not q or not db_path or not os.path.isfile(db_path):
        return []
    ticker = ""
    m = _TICKER.search(q)
    if m and m.group(1) == q.replace(" ", ""):
        ticker = m.group(1).upper()
    name = q.replace("-", "")
    conn = sqlite3.connect(db_path, timeout=15.0)
    conn.row_factory = sqlite3.Row
    try:
        if ticker:
            rows = conn.execute(
                """
                SELECT stock_id, stock_name, date, close, pct_change, volume
                FROM daily_quotes
                WHERE UPPER(stock_id)=?
                ORDER BY date DESC LIMIT 1
                """,
                (ticker,),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT a.stock_id, a.stock_name, a.date, a.close, a.pct_change, a.volume
                FROM daily_quotes a
                JOIN (
                    SELECT stock_id, MAX(date) AS d
                    FROM daily_quotes
                    WHERE stock_name LIKE ?
                    GROUP BY stock_id
                ) b ON a.stock_id=b.stock_id AND a.date=b.d
                ORDER BY a.volume DESC
                LIMIT ?
                """,
                (f"%{q}%", int(limit)),
            ).fetchall()
            if not rows:
                rows = conn.execute(
                    """
                    SELECT a.stock_id, a.stock_name, a.date, a.close, a.pct_change, a.volume
                    FROM daily_quotes a
                    JOIN (
                        SELECT stock_id, MAX(date) AS d
                        FROM daily_quotes
                        WHERE REPLACE(stock_name, '-', '') LIKE ?
                        GROUP BY stock_id
                    ) b ON a.stock_id=b.stock_id AND a.date=b.d
                    ORDER BY a.volume DESC
                    LIMIT ?
                    """,
                    (f"%{name}%", int(limit)),
                ).fetchall()
    except sqlite3.OperationalError:
        rows = []
    finally:
        conn.close()
    return [dict(r) for r in rows]


def resolve_stock(db_path: str, query: str) -> List[Dict[str, Any]]:
    q = stock_query(query)
    if not q:
        return []
    m = _TICKER.search(q)
    code = m.group(1).upper() if m else ""
    name = q
    hits: List[Dict[str, Any]] = []
    try:
        from wayne_db import lookup_stocks

        hits = list(lookup_stocks(db_path, code or name) or [])
    except Exception:
        hits = []
    direct = _direct_lookup(db_path, code or name)
    seen = set()
    with_bars: List[Dict[str, Any]] = []
    for h in direct + hits:
        sid = str(h.get("stock_id") or "")
        if not sid or sid in seen:
            continue
        seen.add(sid)
        if load_bars(db_path, sid, n=8):
            with_bars.append(h)
    if with_bars:
        return with_bars
    return direct or hits


def volume_first_price(bars: Sequence[Dict[str, Any]], *, lookback: int = 40) -> Dict[str, Any]:
    """量先價行：窗口最大量日高當壓、低當撐。沒公式、不編 KD。"""
    window = list(bars)[-int(lookback) :] if bars else []
    if not window:
        return {}
    spike = max(window, key=lambda r: float(r.get("volume") or 0))
    last = window[-1]
    vol_now = float(last.get("volume") or 0)
    vol_spike = float(spike.get("volume") or 0)
    close = float(last.get("close") or 0)
    hi = float(spike.get("high") or 0)
    lo = float(spike.get("low") or 0)
    down = 0
    for i in range(len(window) - 1, 0, -1):
        if float(window[i].get("close") or 0) < float(window[i - 1].get("close") or 0):
            down += 1
        else:
            break
    shrinking = vol_spike > 0 and vol_now <= vol_spike * 0.5
    above_lo = close >= lo if lo else False
    above_hi = close >= hi if hi else False
    if not above_lo:
        stance = "收在爆大量日低點之下 → 這腳還不算站上撐，放棄這次量價買點。"
        buy = ""
    elif above_hi:
        stance = "已過爆大量日高點。半山腰只隔日沖；回測那根高點當撐才像突破回測。"
        buy = "突破回測" if shrinking else "過高但量還沒縮"
    elif shrinking:
        stance = "量縮且收在爆大量日低點之上 → 比較像他說的『價穩量縮才進』。"
        buy = "整理末端候選（難）"
    else:
        stance = "站上撐了但量還沒縮到窒息 → 還不到他說的進場。"
        buy = ""
    name = str(last.get("stock_name") or last.get("stock_id") or "")
    return {
        "name": name,
        "sid": str(last.get("stock_id") or ""),
        "date": _ymd(last.get("date")),
        "close": close,
        "pct": last.get("pct_change"),
        "vol_now": vol_now,
        "spike_date": _ymd(spike.get("date")),
        "spike_high": hi,
        "spike_low": lo,
        "spike_vol": vol_spike,
        "shrinking": shrinking,
        "above_support": above_lo,
        "broke_resistance": above_hi,
        "down_streak": down,
        "stance": stance,
        "buy": buy,
    }


def down_streak(bars: Sequence[Dict[str, Any]]) -> int:
    n = 0
    for i in range(len(bars) - 1, 0, -1):
        c0 = float(bars[i].get("close") or 0)
        c1 = float(bars[i - 1].get("close") or 0)
        if c0 < c1:
            n += 1
        else:
            break
    return n


def match_posts(ask: str, *, limit: int = 4, db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """問句對公開文：完整庫當底圖，只取相鄰幾則，不掃成講義。"""
    try:
        from biaoke_desk import load_corpus
        from biaoke_net import related_posts
    except Exception:
        return []
    q = (ask or "").strip()
    if not q:
        return []
    posts = list((load_corpus(db_path) or {}).get("posts") or [])
    return related_posts(q, posts, limit=limit)


def _cite_posts(posts: Sequence[Dict[str, Any]]) -> str:
    if not posts:
        return ""
    p = posts[0]
    snip = html_escape(re.sub(r"\s+", " ", str(p.get("text") or ""))[:90])
    if not snip:
        return ""
    return f"他 {html_escape(p.get('date'))} 寫過：{snip}"


def _us_facts(db_path: str, as_of: str = "") -> Dict[str, Any]:
    if not db_path or not os.path.isfile(db_path):
        return {}
    try:
        from us_overnight import load_us_overnight

        if as_of:
            snap = load_us_overnight(db_path, as_of)
            if snap:
                return snap
    except Exception:
        pass
    conn = sqlite3.connect(db_path, timeout=15.0)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT * FROM us_overnight ORDER BY as_of DESC LIMIT 1"
        ).fetchone()
    except sqlite3.OperationalError:
        row = None
    finally:
        conn.close()
    return dict(row) if row else {}


def _us_down_days(db_path: str) -> int:
    if not db_path or not os.path.isfile(db_path):
        return 0
    conn = sqlite3.connect(db_path, timeout=15.0)
    try:
        rows = conn.execute(
            """
            SELECT as_of, ixic_pct, sox_pct, spx_pct
            FROM us_overnight
            ORDER BY as_of DESC
            LIMIT 8
            """
        ).fetchall()
    except sqlite3.OperationalError:
        rows = []
    finally:
        conn.close()
    n = 0
    for r in rows:
        ix = r[1] if r[1] is not None else r[2]
        if ix is None:
            ix = r[3]
        try:
            v = float(ix)
        except (TypeError, ValueError):
            break
        if v < 0:
            n += 1
        else:
            break
    return n


def _fmt_us(us: Dict[str, Any]) -> str:
    if not us:
        return "美股隔夜這包庫裡還沒接到。"
    bits = []
    for key, label in (
        ("ixic_pct", "那指"),
        ("spx_pct", "標普"),
        ("dji_pct", "道瓊"),
        ("sox_pct", "費半"),
        ("nq_f_pct", "那指期"),
        ("tsm_pct", "台積美股"),
        ("nvda_pct", "輝達"),
        ("vix", "VIX"),
    ):
        if us.get(key) is None:
            continue
        if key == "vix":
            bits.append(f"{label} {_px(us.get(key))}")
        else:
            bits.append(f"{label} {_pct(us.get(key))}")
    regime = str(us.get("regime") or "")
    lab = {"risk_off": "逆風", "caution": "偏空", "ok": "中性"}.get(regime, "")
    head = f"美股 {html_escape(lab)}".strip() if lab else "美股"
    as_of = html_escape(_ymd(us.get("as_of") or ""))
    return head + (f"（{as_of}）" if as_of else "") + "：" + "、".join(bits) if bits else head


def overlay_stock(
    hit: Dict[str, Any],
    struct: Dict[str, Any],
    *,
    in_corpus: bool,
) -> str:
    sid = html_escape(str(hit.get("stock_id") or struct.get("sid") or ""))
    name = html_escape(str(hit.get("stock_name") or struct.get("name") or sid))
    if not struct:
        return f"{sid} {name} 官方日 K 還不夠，我先不硬套。"
    head = f"{sid} {name}。"
    if not in_corpus:
        head = f"{sid} {name} 資料庫從頭到尾沒點名這檔，我就拿官方日 K 用他那套量價看，可能看錯。"
    body = (
        f"{html_escape(struct.get('date'))} 收 {_px(struct.get('close'))}"
        f"（{_pct(struct.get('pct'))}）。"
        f"近窗爆大量日 {html_escape(struct.get('spike_date'))}，"
        f"高 {_px(struct.get('spike_high'))}、低 {_px(struct.get('spike_low'))}。"
        f"{html_escape(struct.get('stance') or '')}"
    )
    buy = str(struct.get("buy") or "")
    extra = ""
    if buy:
        extra = f"對他說的買點來看，比較像{html_escape(buy)}；半山腰他只做隔日沖。"
    return "\n".join(x for x in (head, body, extra) if x)


def overlay_market(
    *,
    twii: Sequence[Dict[str, Any]],
    tsmc: Dict[str, Any],
    us: Dict[str, Any],
    us_down: int,
    mkt: Optional[Dict[str, Any]] = None,
    night: Optional[Dict[str, Any]] = None,
) -> str:
    mkt = mkt or {}
    last = twii[-1] if twii else {}
    tw_down = down_streak(twii)
    close = last.get("close")
    pct = last.get("pct_change")
    as_of = _ymd(last.get("date") or mkt.get("as_of") or "")
    lines = ["止跌他不猜日曆，要結構先出來才算。"]
    now_bits = []
    if close:
        now_bits.append(f"加權 {as_of} 收 {_px(close)}（{_pct(pct)}）連跌 {tw_down} 日")
    if mkt.get("regime_label"):
        now_bits.append(html_escape(str(mkt.get("regime_label"))))
    if night and night.get("close") is not None:
        now_bits.append(
            f"台指夜盤 {_ymd(night.get('date'))} 收 {_px(night.get('close'))}"
            f"（{_pct(night.get('pct_change'))}）"
        )
    if now_bits:
        lines.append("現況：" + "；".join(now_bits))
    lines.append(_fmt_us(us) + (f"；那指／費半連跌約 {us_down} 日" if us_down else ""))
    if tsmc:
        lines.append(
            f"台積電 {html_escape(tsmc.get('date'))} 收 {_px(tsmc.get('close'))}。"
            f"爆大量日 {html_escape(tsmc.get('spike_date'))}，"
            f"高 {_px(tsmc.get('spike_high'))}、低 {_px(tsmc.get('spike_low'))}。"
            f"{html_escape(tsmc.get('stance') or '')}"
        )
    lines.append("他要費半不再破低、夜盤先過下降壓、台積電量價站上撐，這幾件疊在一起才比較像下跌趨勢化解。")
    sox = us.get("sox_pct")
    risk = str(us.get("regime") or "")
    tsmc_low = bool(
        tsmc.get("above_support")
        and tsmc.get("shrinking")
        and not tsmc.get("broke_resistance")
    )
    if risk == "risk_off" or (sox is not None and float(sox) < -1.5):
        lines.append("現在費半／美股還在逆風，夜盤若再破，日盤先當擴延，不談止跌完成。")
    elif tsmc_low and tw_down <= 1:
        lines.append("台積電這腳比較像低檔量縮站上，大盤仍要夜盤確認。還不是買訊。")
    else:
        lines.append("條件還沒齊。若夜盤先止穩、費半不再破低，日盤才有機會談反彈——這不是日期保證。")
    return "\n".join(lines)


def _load_night(db_path: str) -> Dict[str, Any]:
    try:
        from taiwan_market import load_futures_night

        row = load_futures_night(db_path)
        return dict(row) if row else {}
    except Exception:
        return {}


def _load_mkt(db_path: str) -> Dict[str, Any]:
    try:
        from taiwan_market import analyze_taiwan_market

        row = analyze_taiwan_market(db_path, db_only=True, page_light=True)
        return dict(row) if row else {}
    except Exception:
        return {}


def answer_biaoke(db_path: str, ask: str, history: Optional[Sequence[Any]] = None) -> str:
    """一句問句 → Telegram HTML。用飆大公開文思考彙整，不是選單考卷。

    history：同一人上一句（偉權／哥哥分開），讓『那呢』接得上。
    """
    from biaoke_mind import follow_up_ask, format_methods_html
    from biaoke_trace import format_trace_html

    q = follow_up_ask((ask or "").strip(), history)
    if not q:
        from biaoke_desk import format_biaoke_html

        return format_biaoke_html("")
    try:
        from biaoke_live import live_reply

        live = live_reply(db_path, q, history)
    except Exception:
        live = ""
    if live:
        return live
    if _HI.match(q):
        return "在，你說。"
    if is_offtopic(q):
        return OFFTOPIC
    if is_desk_query(q):
        from biaoke_desk import format_biaoke_html

        return format_biaoke_html(q)

    methods = format_methods_html(q)
    trace = format_trace_html(q, db_path)
    hits = resolve_stock(db_path, q)
    posts = match_posts(q, limit=5, db_path=db_path)
    want_mkt = is_market_question(q)
    stock_like = bool(stock_query(q)) and not want_mkt
    if hits and (stock_like or (not want_mkt) or len(stock_query(q)) >= 2):
        if len(hits) > 1 and not _TICKER.search(q):
            from lookup_fuzzy import hits_need_picker

            if hits_need_picker(hits):
                lines = [DISCLAIMER, "對到多檔，點名一檔再問。"]
                for h in hits[:8]:
                    lines.append(
                        f"{html_escape(h.get('stock_id'))} {html_escape(h.get('stock_name'))}"
                    )
                return "\n".join(lines)
        hit = hits[0]
        sid = str(hit.get("stock_id") or "")
        bars = load_bars(db_path, sid)
        struct = volume_first_price(bars)
        in_corpus = bool(posts)
        body = overlay_stock(hit, struct, in_corpus=in_corpus)
        cite = _cite_posts(posts)
        extra = ""
        if want_mkt:
            twii = load_index_bars(db_path)
            tsmc = volume_first_price(load_bars(db_path, "2330"))
            us = _us_facts(db_path, str((twii[-1].get("date") if twii else "") or ""))
            extra = overlay_market(
                twii=twii,
                tsmc=tsmc,
                us=us,
                us_down=_us_down_days(db_path),
                mkt=_load_mkt(db_path),
                night=_load_night(db_path),
            )
        chunks = []
        if trace:
            chunks.append(trace)
        chunks.append(body)
        if extra:
            chunks.append(extra)
        if cite:
            chunks.append(cite)
        chunks.append(DISCLAIMER)
        return "\n\n".join(chunks)

    if trace:
        cite = _cite_posts(posts)
        extra = ""
        if want_mkt:
            twii = load_index_bars(db_path)
            tsmc = volume_first_price(load_bars(db_path, "2330"))
            us = _us_facts(db_path, str((twii[-1].get("date") if twii else "") or ""))
            extra = overlay_market(
                twii=twii,
                tsmc=tsmc,
                us=us,
                us_down=_us_down_days(db_path),
                mkt=_load_mkt(db_path),
                night=_load_night(db_path),
            )
        return "\n\n".join(x for x in (trace, extra, methods, cite, DISCLAIMER) if x)

    if methods and not hits and not want_mkt:
        cite = _cite_posts(posts)
        return "\n\n".join(x for x in (methods, cite, DISCLAIMER) if x)

    if want_mkt or not hits:
        if want_mkt or re.search(r"(止跌|連跌|美股|台股|大盤|費半)", q):
            twii = load_index_bars(db_path)
            tsmc = volume_first_price(load_bars(db_path, "2330"))
            us = _us_facts(db_path, str((twii[-1].get("date") if twii else "") or ""))
            body = overlay_market(
                twii=twii,
                tsmc=tsmc,
                us=us,
                us_down=_us_down_days(db_path),
                mkt=_load_mkt(db_path),
                night=_load_night(db_path),
            )
            cite = _cite_posts(posts)
            return "\n\n".join(x for x in (body, cite, DISCLAIMER) if x)
        if posts:
            return "\n\n".join(x for x in (methods, _cite_posts(posts), DISCLAIMER) if x)
        return "這句我沒對到檔。你直接說股名或大盤就好，也可以接著上一句問。\n" + DISCLAIMER
    return DISCLAIMER
