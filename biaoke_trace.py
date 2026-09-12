# -*- coding: utf-8 -*-
"""飆大公開文時間線：哪天說什麼、後來官方日 K 對不對。

不是買訊、不進海選。社團沒寫進公開 1709 的目標價不編。
手機問到檔名／連線／龍頭時走這裡。
"""
from __future__ import annotations

import os
import re
import sqlite3
from typing import Any, Dict, List, Optional, Sequence, Tuple

from tg_layout import html_escape

HOW = (
    "他不是掃全市場爆量，也不是等新聞。公開文能還原的順序是："
    "先定大盤位階（夜盤／台指期 15 分＋60 分數 5 或 9、費半有沒有 1-4 重疊），"
    "再看當下主流的次族群第一名有沒有整理完、誰先過前高，不比絕對漲跌。"
    "龍頭用量價結構（整理時間誰短、誰先測高）。"
    "個股買點才用量先價行：爆大量日高低當壓／撐，價穩量縮才進，否則放棄。"
    "半山腰只隔日沖；新聞變多、平台狂貼法說，他當中短高點。"
    "他 2026-07-16 寫過用「不公開的量價結構」看台積電來選波浪標籤——那塊這裡不發明公式。"
    "錯的他會改口（3 月 22000、7/16 不破 40000），時間線要把對跟錯一起留。"
)

RAILS = (
    "看大盤他常先畫台積電，不是先畫加權。"
    "上升軌＝同一次級兩個低點連起來（浪 2 低連浪 4 低）。"
    "下降壓＝同一次級兩個更低的高連起來，當參考壓。"
    "三角＝兩條一起，看收在不在上下區間。"
    "2025-10-15 附圖黃軌是 3-2 連 3-4，口令不跌破才走 3-5。"
    "2025-12-03 才講死日期：台積電 9/3 低連 11/24 低，或加權 9/3 低連 11/21 低；不破才談第五波。"
    "2025-12-16 他說台積電已跌破。資料庫日 K：2330 9/3 低 1145、11/24 低 1375；"
    "12/16 收 1435，交易日延長那條軌約 1443，收盤跌破。加權同日還沒破 9/3–11/21 那條——"
    "他用台積電當先行。不是買訊。"
)

HOLD = (
    "他現在講大盤用台指期細微波（四萬點），不是教科書加權一萬七。"
    "2026-09-10 09:51：9/8 起 abc，當天看到 c 末端，下波至少測 48218。"
    "2026-09-11 08:43：未來 2～3 交易日觀盤重點是 9/3 加權低點 45839 有沒有守住。"
    "有守住＝右肩還是高有過前高、低不破前低，高檔震盪趨勢向上。"
    "這段不要追高殺低，只汰弱留強（他說很難）；建議抱長線主流龍頭。"
    "同日：加權細微波已走 5 段，會不會走 9 段他說目前無法判斷；四大龍頭裡南亞科最弱。"
    "2026-09-11 17:49：夜盤 15 分走出 5 段、下降軌破壞、初步止訊號；今晚至少穿越 46506。"
    "庫沒有 15 分 K 就不數他的段數對不對。資料庫：20260903 TWII 低 45839.36、收 45857.66；"
    "9/4～9/10 的低都高於 45839。9/11 起那 2～3 日守不守還在走。不是買訊。"
)

_CASES: List[Tuple[re.Pattern[str], str]] = [
    (
        re.compile(r"(汎銓|泛銓|6830)"),
        "汎銓 6830。公開能對上的是：2026-02-24 他寫市場很少人提的高階半導體檢測，領頭羊穎崴，"
        "泛銓也可以介入做波段（當天收 236，之後 20 日約 +83%，3/9 高 411）。"
        "高階測試最早兩檔黑馬是雍智 6683、汎銓 6830；穎崴仍是領頭羊，黑馬不是去替代龍頭。"
        "2026-04-18 樓中樓：新聞變多、平台一直貼法說，不是好現象，中短期高點到了。"
        "之後 20 日約 −17%、60 日約 −55%。線圖先於新聞；新聞擁擠是賣點邏輯。"
        "2025-09-03 那次型態目標 210～220，第一段沒碰到。不是買訊。",
    ),
    (
        re.compile(r"(雍智|6683)"),
        "雍智 6683。高階測試最早兩檔黑馬是雍智 6683、汎銓 6830。"
        "公開 2026-02-24 主文寫死的是汎銓可波段、領頭羊穎崴；雍智是同一條高階測試／探針卡鏈的另一檔最早黑馬。"
        "跟漲先看穎崴、旺矽，不是拿黑馬去替代龍頭。不是買訊。",
    ),
    (
        re.compile(r"(聯發科|2454|發哥)"),
        "聯發科 2454。2025-09-12 公開還在講回測 1430、目標 1575～1600。"
        "2026-04-22 才公開 IC 設計主線（創意／力旺已噴，看低位階），當天接近漲停，20 日約 +85.8%。"
        "聯發科不在 4/16 那份可抱到明年名單（那份是台積電、台達電、台光電、旺矽、穎崴、奇鋐）。"
        "2026-07-23：F10／ABF 長線主流暫不調整，發哥尚未納入 F 系列。"
        "2026-05-28 說進第一個平台，整理完朝第一階段目標；6/1 當天收 4555，因 MSCI 尾盤爆量改口可能延後。"
        "你記得的「五千塊」在公開 1709 主文＋樓中樓對不到這三個字，不編。"
        "不是買訊。",
    ),
    (
        re.compile(r"(川湖|2059)"),
        "川湖 2059。他常拿川湖跟台光電當 AI 伺服器零組件觀察指標。"
        "2025-10-21：觀察直接過 3985 還是要 abc 才過；過不了這波很難超過 4200。"
        "2025-12-07：台光電、貿聯、川湖都沒什麼大行情了，可分批調節。"
        "2026-01-08：頭肩頂成立，昨天最後回測，要停損出清。"
        "「上萬元」這句公開 1709 對不到。不是買訊。",
    ),
    (
        re.compile(r"(南亞科|2408)"),
        "南亞科 2408。公開買點不是 130：2025-05-22 他自己寫「我是 44 買入」後來停損出清；"
        "11/7 再進、11/12 說記憶體是當時唯一不受大盤影響的主流、南亞科是指標；"
        "11/13 洗盤先出場；12/17 起專心做記憶體（群聯／華邦電／南亞科／模組），PCB 做頭就撤；"
        "2026-01-23 出清。11/18 那句支撐 1300 是台光電，不是南亞科。"
        "你記得的「一百三十左右買進」公開 1709 對不到。不是買訊。",
    ),
    (
        re.compile(r"(南亞)(?!科)"),
        "南亞 1303 跟南亞科 2408 不是同一檔。飆大公開文裡記憶體主線講的是南亞科。"
        "若你要的是南亞科，直接打南亞科或 2408。不是買訊。",
    ),
]

_RAIL_ASK = re.compile(
    r"(連線|連哪兩天|上升軌|下降壓|黃軌|三角|怎麼看大盤|看大盤|"
    r"3-2|3-4|11/24|11/21|軌道|1145|1375)"
)
_HOLD_ASK = re.compile(
    r"(45839|46506|48218|右肩|低不破前低|高有過前高|高檔震[盪檔]|追高殺低|汰弱留強|"
    r"觀盤重點|波浪|位階|細微波|第[1-9一二三四五]浪|第[1-9一二三四五]波|段數|"
    r"9/3.{0,12}(低點|低|有守)|守住.{0,12}(45839|低點))"
)
_HOW_ASK = re.compile(
    r"(族群發動|怎麼抓龍頭|次族群|誰先過前高|龍頭怎麼抓|"
    r"怎麼知道哪個族群|勝率|怎麼斷言|怎麼預估)"
)


def _ymd(raw: Any) -> str:
    t = str(raw or "").replace("-", "")[:8]
    return t if len(t) == 8 and t.isdigit() else ""


def _bar_on(conn: sqlite3.Connection, sid: str, ymd: str) -> Optional[Dict[str, float]]:
    if sid == "TWII":
        row = conn.execute(
            "SELECT date, high, low, close FROM index_daily WHERE symbol='TWII' AND date=?",
            (ymd,),
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT date, high, low, close FROM daily_quotes WHERE stock_id=? AND date=?",
            (sid, ymd),
        ).fetchone()
    if not row:
        return None
    return {"date": str(row[0]), "high": float(row[1]), "low": float(row[2]), "close": float(row[3])}


def _index_of(dates: Sequence[str], ymd: str) -> int:
    key = _ymd(ymd)
    for i, d in enumerate(dates):
        if _ymd(d) == key:
            return i
    return -1


def verify_low_rail(
    db_path: str,
    *,
    sid: str,
    d1: str,
    d2: str,
    at: str,
) -> Dict[str, Any]:
    """用交易日把兩低連成線，對 at 那天的收／低。庫沒這天就空。"""
    out: Dict[str, Any] = {"sid": sid, "ok": False}
    if not db_path or not os.path.isfile(db_path):
        return out
    conn = sqlite3.connect(db_path, timeout=15.0)
    try:
        a = _bar_on(conn, sid, d1)
        b = _bar_on(conn, sid, d2)
        c = _bar_on(conn, sid, at)
        if not a or not b or not c:
            return out
        if sid == "TWII":
            rows = conn.execute(
                "SELECT date FROM index_daily WHERE symbol='TWII' ORDER BY date"
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT date FROM daily_quotes WHERE stock_id=? ORDER BY date",
                (sid,),
            ).fetchall()
        dates = [str(r[0]) for r in rows]
        i1, i2, ia = _index_of(dates, d1), _index_of(dates, d2), _index_of(dates, at)
        if i1 < 0 or i2 < 0 or ia < 0 or i1 == i2:
            return out
        rail = a["low"] + (b["low"] - a["low"]) * ((ia - i1) / (i2 - i1))
        out.update(
            {
                "ok": True,
                "p1_low": a["low"],
                "p2_low": b["low"],
                "at": c["date"],
                "rail": round(rail, 2),
                "close": c["close"],
                "low": c["low"],
                "broke_close": c["close"] < rail,
                "broke_low": c["low"] < rail,
            }
        )
        return out
    except sqlite3.OperationalError:
        return out
    finally:
        conn.close()


def verify_level_holds(
    db_path: str,
    *,
    sid: str,
    ymd: str,
    through: str = "",
) -> Dict[str, Any]:
    """那日低點之後，後續日 K 低有沒有再破。庫沒這天就空。"""
    out: Dict[str, Any] = {"sid": sid, "ok": False, "held": None}
    if not db_path or not os.path.isfile(db_path):
        return out
    conn = sqlite3.connect(db_path, timeout=15.0)
    try:
        bar = _bar_on(conn, sid, ymd)
        if not bar:
            return out
        level = float(bar["low"])
        params: List[Any] = [ymd]
        if sid == "TWII":
            sql = "SELECT date, low FROM index_daily WHERE symbol='TWII' AND date>? "
            if through:
                sql += "AND date<=? "
                params.append(through)
            sql += "ORDER BY date"
            rows = conn.execute(sql, params).fetchall()
        else:
            sql = "SELECT date, low FROM daily_quotes WHERE stock_id=? AND date>? "
            params = [sid, ymd]
            if through:
                sql += "AND date<=? "
                params.append(through)
            sql += "ORDER BY date"
            rows = conn.execute(sql, params).fetchall()
        later = [{"date": str(r[0]), "low": float(r[1])} for r in rows if r and r[1] is not None]
        broke = [r for r in later if r["low"] <= level]
        nearest = min(later, key=lambda r: r["low"]) if later else None
        out.update(
            {
                "ok": True,
                "level": round(level, 2),
                "at": bar["date"],
                "n_later": len(later),
                "held": not broke,
                "broke_on": broke[0]["date"] if broke else "",
                "nearest_later_low": round(nearest["low"], 2) if nearest else None,
                "nearest_later_date": nearest["date"] if nearest else "",
                "last_date": later[-1]["date"] if later else "",
            }
        )
        return out
    except sqlite3.OperationalError:
        return out
    finally:
        conn.close()


def format_trace(ask: str, db_path: str = "") -> str:
    """問句 → 已對過官方日 K 的時間線。沒對上就空字串。"""
    q = (ask or "").strip()
    if not q:
        return ""
    parts: List[str] = []
    for pat, body in _CASES:
        if pat.search(q):
            parts.append(body)
    if _HOLD_ASK.search(q):
        live = ""
        try:
            from biaoke_verify import format_watch

            live = format_watch(db_path)
        except Exception:
            live = ""
        extra = ""
        if not live:
            chk = verify_level_holds(db_path, sid="TWII", ymd="20260903")
            if chk.get("ok") and chk.get("n_later"):
                extra = f" 重算：9/3 低 {chk['level']:.2f}；"
                if chk.get("held"):
                    extra += (
                        f"{chk.get('nearest_later_date')} 低 {chk['nearest_later_low']:.2f} 最近，"
                        f"到 {chk.get('last_date')} 還沒破。"
                    )
                else:
                    extra += f"{chk.get('broke_on')} 已破。"
        parts.append(HOLD + (("\n" + live) if live else extra))
    if _RAIL_ASK.search(q):
        extra = ""
        chk = verify_low_rail(
            db_path, sid="2330", d1="20250903", d2="20251124", at="20251216"
        )
        if chk.get("ok"):
            extra = (
                f" 重算：12/16 收 {chk['close']:.0f}、軌 {chk['rail']:.0f}，"
                + ("收盤跌破。" if chk.get("broke_close") else "收盤還沒破。")
            )
        parts.append(RAILS + extra)
    if _HOW_ASK.search(q):
        parts.append(HOW)
    return "\n".join(parts)


def format_trace_html(ask: str, db_path: str = "") -> str:
    raw = format_trace(ask, db_path)
    if not raw:
        return ""
    return "\n".join(html_escape(line) for line in raw.split("\n"))
