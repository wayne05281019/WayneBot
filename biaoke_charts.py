# -*- coding: utf-8 -*-
"""1709／社團附圖索引。圖檔不進 git，只留 URL＋短註＋代號。

頭像不算圖。第 4／5 顆讀這份索引：問一檔帶公開附圖對官方日K。
社團附圖只對價，不進話筒原文、不送圖。
"""
from __future__ import annotations

import gzip
import json
import os
import re
from functools import lru_cache
from typing import Any, Dict, List, Optional, Sequence

_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs", "expert_notes", "飆客")
CHART_INDEX_GZ = os.path.join(_DIR, "chart_index.json.gz")
AVATAR_NEEDLE = "image.cmoney.tw/profile/"
_CODE = re.compile(r"(?<!\d)(\d{4})(?!\d)")
_YEARS = {str(y) for y in range(1990, 2036)}

# 已目視過的關鍵圖。不准靠 OCR 亂猜，也不准發明建築兩檔代號。
_NOTE_BY_SNIP = {
    "516b26b0-786e-494d-bf8f-1897b6f7dd7f": "平台依賴度排名（當時 F10）",
    "f04ffb08-735d-42f8-a1c4-c473afa72034": "紅框：台光電量縮站上1265、金像電量縮小紅",
    "57effce7-7abf-4894-9354-e5d3812260d1": "紅框：漢唐量沒再放大",
    "0fdcb54f-cbc3-45cf-bf40-51a99eb15aee": "台光電 AI 高速 CCL 護城河 S+++",
    "57e9c59f-ebcc-46b2-8c51-6f9d452e2575": "穎崴 2027 EPS 190～200",
    "59129621-6b40-42b2-90fa-74a1945b3b48": "金像電 CCL 漲價侵蝕毛利＝舊利空發酵",
    "9de6eef2-0bfa-4eb1-bf1f-47216dde15e0": "AI 族群重要性表：記憶體不宜當主線",
    "4ffd8f7b-ffe7-4ee0-b6ce-945c153c1c3e": "勤誠破支撐就不適合操作",
    "nu9_05aT_7A": "YouTube 縮圖：PCB開始震",
    "3e7ba93c-b7d1-4ef5-bbd7-d5f39fd6783b": "智原日K：abc 修正、不確定過396",
    "41887249-c7df-4936-afae-6e89c2b69c1e": "萬海：突破頸線確認K線",
    "b330272a-5450-4d1e-aaeb-cae23a0c3aba": "新興日K：一年半底部",
    "57073c49-89a5-4b82-b978-a05e89d38ddd": "新興：一年半W底＋下飄旗",
    "b735aca2-0e7c-4c72-b59b-92be5df9beb1": "新興15分：短線破底翻",
    "e25c0db0-efb4-427f-8220-ad9978ddb1bc": "萬海15分：破底翻確認",
    "2bfc7988-2140-4df1-8bf9-de09903e774a": "新興：主力成本區／破線（文說裕民一樣）",
    "47069aed-1411-489b-be09-56331d956c35": "新興教學圖：下飄旗＋破底翻確認",
    "046492e4-cc55-460f-a081-5f1aa9a04bf7": "台指期：假突破／做頭（主文點華碩，圖不是華碩日K）",
    "73437676-c106-4922-a48e-42e91e0a48b0": "台指期：做頭，頭肩頂左肩或M頭左側",
    "01804ab6-2fdd-47b7-8390-adf0caf8f170": "廣達1/26日K：回測頸線收盤不能跌破",
    "76b9bce8-f8e9-45ea-b565-17153a894777": "廣達2/2日K：頸線越墊越高",
    "b7132fee-a48f-4a69-956b-ebedacf4f75c": "台指近月60分：上升軌道破壞（主文點台通／頎邦，圖不是個股日K）",
    "54a8021a-7174-4b99-a26f-5ed31a27ca92": "櫃買指數日K：B然後C（不是台通／頎邦日K）",
    "47b69e0f-de57-44d9-a9ec-4e809202ca13": "光聖盤中走勢：反彈至125附近（不是日K）",
    "925ae6d3-392a-4e43-8cf7-6ef7c03a7406": "頎邦盤中走勢：回測支撐確認（不是日K）",
    "9a56b8cc-9e24-4397-a5cb-68d6df19c5a5": "廣達盤中走勢：2/15-16缺口壓力（不是日K）",
    "f413de27-c9fa-4a44-8bcb-4832929d6930": "台指期近月日K：上升軌道有點跌破（庫沒柱）",
    "3e6b15a5-a550-4e9e-a9ea-9d4e20405a82": "樺漢盤中走勢：站上頸線、回測327（主文寫鴻海機器人概念股，圖不是鴻海日K）",
    "3d8bf14c-9c2f-4feb-ac93-8c56755b79af": "樺漢盤中走勢：10:20測326-327先觀望（不是日K）",
    "d841fc6b-6dbd-47cc-9b2e-d6c1bf900da8": "樺漢盤中走勢：12:31拉回後改口可買完（不是日K，不是1231）",
    "df0553e6-4348-4cd8-ab64-09a179b9d6e1": "樺漢盤中走勢：12:15看327有沒有守（不是日K）",
    "ead7aa97-2233-4df3-a6d2-4016a6b6fb01": "樺漢盤中走勢：09:32最後上車、比鴻海多（圖不是鴻海日K）",
    "b0b38f9c-6ac5-4260-8f9d-0206f1167367": "光聖盤中走勢：10:10多空支撐仍寫125（不是日K）",
    "a23ff8ba-c9f6-4086-89a8-b4b7e2d68168": "光聖盤中走勢：09:15看144-145反壓不是漲停（不是日K）",
    "c3095408-726b-4dde-b71f-7cebd42ae8b5": "廣達盤中走勢：10:17洗到282再連續漲（不是日K）",
    "5e0d0c26-161f-4a5b-946f-94c6ca086382": "樺漢盤中走勢：13:30必過400看明天周K（不是日K／不是周K）",
    "d9ca1bdc-42f3-444b-87fc-6852e905a126": "廣達盤中走勢：13:30不像鴻海過282一路飆（不是日K，不是鴻海日K）",
    "26d9c950-b806-47d5-959b-7cd66855e460": "廣達盤中走勢：10:30改口非常強、用282算還有20%（不是日K，不是鴻海日K）",
    "0f2edc9a-0fb0-460c-b4e2-0deb3042b5f9": "樺漢盤中走勢：12:00早盤洗盤、長下引線紅K才噴（不是日K）",
    "821625f8-5d5f-426d-8a50-6f5c953706bc": "廣達盤中走勢：13:30下星期上半週站穩300、不要賺幾%就下車（不是日K）",
    "d6a36765-2022-4e9e-a780-29c96479a294": "光聖盤中走勢：13:30下週一攻克144-145、測前高161.5否則整理半年（不是日K）",
}
_TICKERS_BY_SNIP = {
    "516b26b0-786e-494d-bf8f-1897b6f7dd7f": [
        "2330",
        "2383",
        "2059",
        "3017",
        "2308",
        "6223",
        "6515",
        "2368",
        "8210",
        "3081",
        "2454",
        "7769",
    ],
    "f04ffb08-735d-42f8-a1c4-c473afa72034": ["2383", "2368"],
    "57effce7-7abf-4894-9354-e5d3812260d1": ["2404"],
    "0fdcb54f-cbc3-45cf-bf40-51a99eb15aee": ["2383"],
    "57e9c59f-ebcc-46b2-8c51-6f9d452e2575": ["6515"],
    "59129621-6b40-42b2-90fa-74a1945b3b48": ["2368"],
    "4ffd8f7b-ffe7-4ee0-b6ce-945c153c1c3e": ["8210"],
    "3e7ba93c-b7d1-4ef5-bbd7-d5f39fd6783b": ["3035"],
    "41887249-c7df-4936-afae-6e89c2b69c1e": ["2615"],
    "b330272a-5450-4d1e-aaeb-cae23a0c3aba": ["2605"],
    "57073c49-89a5-4b82-b978-a05e89d38ddd": ["2605"],
    "b735aca2-0e7c-4c72-b59b-92be5df9beb1": ["2605"],
    "e25c0db0-efb4-427f-8220-ad9978ddb1bc": ["2615"],
    "2bfc7988-2140-4df1-8bf9-de09903e774a": ["2605"],
    "47069aed-1411-489b-be09-56331d956c35": ["2605"],
    "046492e4-cc55-460f-a081-5f1aa9a04bf7": ["2357"],
    "01804ab6-2fdd-47b7-8390-adf0caf8f170": ["2382"],
    "76b9bce8-f8e9-45ea-b565-17153a894777": ["2382"],
    "b7132fee-a48f-4a69-956b-ebedacf4f75c": ["8011", "6147"],
    "54a8021a-7174-4b99-a26f-5ed31a27ca92": ["8011", "6147"],
    "47b69e0f-de57-44d9-a9ec-4e809202ca13": ["6442"],
    "925ae6d3-392a-4e43-8cf7-6ef7c03a7406": ["6147"],
    "9a56b8cc-9e24-4397-a5cb-68d6df19c5a5": ["2382"],
    "3e6b15a5-a550-4e9e-a9ea-9d4e20405a82": ["6414"],
    "3d8bf14c-9c2f-4feb-ac93-8c56755b79af": ["6414"],
    "d841fc6b-6dbd-47cc-9b2e-d6c1bf900da8": ["6414"],
    "df0553e6-4348-4cd8-ab64-09a179b9d6e1": ["6414"],
    "ead7aa97-2233-4df3-a6d2-4016a6b6fb01": ["6414"],
    "b0b38f9c-6ac5-4260-8f9d-0206f1167367": ["6442"],
    "a23ff8ba-c9f6-4086-89a8-b4b7e2d68168": ["6442"],
    "c3095408-726b-4dde-b71f-7cebd42ae8b5": ["2382"],
    "5e0d0c26-161f-4a5b-946f-94c6ca086382": ["6414"],
    "d9ca1bdc-42f3-444b-87fc-6852e905a126": ["2382"],
    "26d9c950-b806-47d5-959b-7cd66855e460": ["2382"],
    "0f2edc9a-0fb0-460c-b4e2-0deb3042b5f9": ["6414"],
    "821625f8-5d5f-426d-8a50-6f5c953706bc": ["2382"],
    "d6a36765-2022-4e9e-a780-29c96479a294": ["6442"],
}
_ALIAS = {
    "穎葳": "6515",
    "川湖": "2059",
    "聖暉": "5536",
    "旺矽": "6223",
    "鴻勁": "7769",
    "志聖": "2467",
    "漢唐": "2404",
    "樺漢": "6414",
}


def _snip_note(url: str) -> str:
    u = url or ""
    for snip, note in _NOTE_BY_SNIP.items():
        if snip in u:
            return note
    return ""


def _snip_tickers(url: str) -> List[str]:
    u = url or ""
    for snip, ids in _TICKERS_BY_SNIP.items():
        if snip in u:
            return list(ids)
    return []


def _add_sid(found: List[str], sid: str, valid: Optional[set]) -> None:
    sid = str(sid or "").strip()
    if not sid or sid in found:
        return
    if valid is not None and sid not in valid:
        return
    found.append(sid)


def extract_tickers(
    ocr: str = "",
    blob: str = "",
    *,
    url: str = "",
    name_to_sid: Optional[Dict[str, str]] = None,
    valid_ids: Optional[Sequence[str]] = None,
    limit: int = 12,
) -> List[str]:
    found: List[str] = []
    valid = set(valid_ids) if valid_ids is not None else None
    for sid in _snip_tickers(url):
        _add_sid(found, sid, valid)
    names = dict(_ALIAS)
    if name_to_sid:
        names.update(name_to_sid)
    text = (ocr or "") + "\n" + (blob or "")
    for name in sorted(names, key=len, reverse=True):
        if name and name in text:
            _add_sid(found, names[name], valid)
        if len(found) >= limit:
            return found[:limit]
    for code in _CODE.findall(ocr or ""):
        if code in _YEARS:
            continue
        _add_sid(found, code, valid)
        if len(found) >= limit:
            break
    return found[:limit]


def _short_note(kind: str, tickers: Sequence[str], url: str) -> str:
    known = _snip_note(url)
    if known:
        return known[:80]
    ids = ",".join(list(tickers)[:4])
    if kind == "kline":
        return ("日K截圖 " + ids).strip()[:80]
    if kind == "screenshot":
        return ("討論截圖 " + ids).strip()[:80]
    return ("其他附圖 " + ids).strip()[:80]


def _texts_for_aid(posts: Sequence[Dict[str, Any]], aid: str) -> str:
    aid = str(aid or "")
    if not aid:
        return ""
    chunks: List[str] = []
    for row in posts or []:
        pid = str(row.get("id") or "")
        parent = str(row.get("parent") or "")
        if pid == aid or parent == aid or pid.startswith(aid + ":"):
            tags = " ".join(str(t) for t in (row.get("tags") or []) if t)
            chunks.append(tags)
            chunks.append(str(row.get("text") or ""))
    return "\n".join(chunks)


def build_chart_index(
    catalog: Sequence[Dict[str, Any]],
    *,
    posts: Optional[Sequence[Dict[str, Any]]] = None,
    name_to_sid: Optional[Dict[str, str]] = None,
    valid_ids: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    """用已下載分類結果建精簡索引。不准塞整段 OCR，不准把頭像算進去。"""
    rows: List[Dict[str, Any]] = []
    seen = set()
    src_count: Dict[str, int] = {}
    post_rows = list(posts or [])
    valid = list(valid_ids) if valid_ids is not None else None
    for raw in catalog or []:
        url = str(raw.get("url") or "").strip()
        if not url or AVATAR_NEEDLE in url:
            continue
        if url in seen:
            continue
        seen.add(url)
        src = str(raw.get("src") or "")
        aid = str(raw.get("aid") or "")
        kind = str(raw.get("kind") or "other")
        blob = _texts_for_aid(post_rows, aid)
        tickers = extract_tickers(
            str(raw.get("ocr") or ""),
            blob,
            url=url,
            name_to_sid=name_to_sid,
            valid_ids=valid,
        )
        rows.append(
            {
                "src": src,
                "date": str(raw.get("date") or ""),
                "aid": aid,
                "url": url,
                "kind": kind,
                "tickers": tickers,
                "note": _short_note(kind, tickers, url),
            }
        )
        src_count[src] = src_count.get(src, 0) + 1
    return {
        "n": len(rows),
        "sources": src_count,
        "note": "圖檔不進 git；頭像已剔除。神經元下一件才讀圖。",
        "charts": rows,
    }


def write_chart_index(blob: Dict[str, Any], path: str = "") -> str:
    dest = path or CHART_INDEX_GZ
    parent = os.path.dirname(dest)
    if parent:
        os.makedirs(parent, exist_ok=True)
    tmp = dest + ".tmp"
    with gzip.open(tmp, "wt", encoding="utf-8") as fh:
        json.dump(blob, fh, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, dest)
    return dest


@lru_cache(maxsize=1)
def load_chart_index() -> Dict[str, Any]:
    if not os.path.isfile(CHART_INDEX_GZ):
        return {}
    with gzip.open(CHART_INDEX_GZ, "rt", encoding="utf-8") as fh:
        blob = json.load(fh) or {}
    if not isinstance(blob, dict):
        return {}
    return blob


def charts_for(sid: str) -> List[Dict[str, Any]]:
    """這檔出現在附圖索引裡的列。沒有就空。已目視短註蓋過索引裡的「日K截圖」。"""
    want = str(sid or "").strip()
    if not want:
        return []
    out: List[Dict[str, Any]] = []
    for row in load_chart_index().get("charts") or []:
        url = str(row.get("url") or "")
        ticks = [str(t) for t in (row.get("tickers") or [])]
        extra = _snip_tickers(url)
        if extra:
            ticks = list(extra)
        if want not in ticks:
            continue
        item = dict(row)
        item["tickers"] = ticks
        known = _snip_note(url)
        if known:
            item["note"] = known
        out.append(item)
    return out


def load_name_map(db_path: str = "") -> Dict[str, str]:
    """官方股名→代號。前華科對不到就不編。"""
    out = dict(_ALIAS)
    path = db_path or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "data", "wayne_market.db"
    )
    if not path or not os.path.isfile(path):
        return out
    try:
        import sqlite3

        conn = sqlite3.connect(path, timeout=10.0)
        try:
            rows = conn.execute(
                "SELECT stock_id, stock_name FROM stock_universe"
            ).fetchall()
        finally:
            conn.close()
    except Exception:
        return out
    for sid, name in rows:
        sid_s = str(sid or "").strip()
        name_s = str(name or "").replace("*", "").strip()
        if sid_s and name_s and name_s not in out:
            out[name_s] = sid_s
    return out


def valid_stock_ids(db_path: str = "") -> List[str]:
    names = load_name_map(db_path)
    return sorted(set(names.values()))


_PUBLIC_SRC = "public1709"
_NOTE_WEIGHT = {
    "平台依賴": 200,
    "F10": 180,
    "紅框": 170,
    "護城河": 160,
    "舊利空": 90,
    "破支撐": 90,
    "不宜當主線": 80,
    "長抱": 80,
    "EPS": 60,
}
_HOLD_NOTE = ("平台依賴", "護城河", "F10", "長抱", "紅框")
# 註記已經寫死是哪一檔的，別檔問句不要搶第一。
_NOTE_OWN = (
    ("漢唐量沒再放大", "2404"),
    ("台光電量縮站上1265", "2383"),
    ("台光電 AI 高速 CCL", "2383"),
    ("穎崴 2027", "6515"),
    ("金像電 CCL", "2368"),
    ("勤誠破支撐", "8210"),
    ("智原日K", "3035"),
    ("萬海：突破頸線", "2615"),
    ("萬海15分", "2615"),
    ("新興日K", "2605"),
    ("新興：一年半W底", "2605"),
    ("新興15分", "2605"),
    ("新興：主力成本區", "2605"),
    ("新興教學圖", "2605"),
    ("台指期：假突破", "2357"),
    ("台指期：做頭", "2357"),
    ("廣達1/26日K", "2382"),
    ("廣達2/2日K", "2382"),
    ("台指近月60分", "8011"),
    ("櫃買指數日K", "6147"),
    ("光聖盤中走勢", "6442"),
    ("頎邦盤中走勢", "6147"),
    ("廣達盤中走勢", "2382"),
    ("樺漢盤中走勢", "6414"),
)


def _px_short(val: Any) -> str:
    try:
        n = float(val)
    except (TypeError, ValueError):
        return ""
    if abs(n - round(n)) < 1e-9:
        return str(int(round(n)))
    return f"{n:.2f}".rstrip("0").rstrip(".")


def official_on(db_path: str, sid: str, date: str) -> Dict[str, Any]:
    """這檔這天的官方日K。沒這列就空，不准編。"""
    if not db_path or not os.path.isfile(db_path) or not sid:
        return {}
    ymd = str(date or "").replace("-", "")[:8]
    if len(ymd) != 8 or not ymd.isdigit():
        return {}
    try:
        import sqlite3

        conn = sqlite3.connect(db_path, timeout=8.0)
        try:
            row = conn.execute(
                "SELECT date, open, high, low, close, volume FROM daily_quotes "
                "WHERE stock_id=? AND REPLACE(CAST(date AS TEXT),'-','')=? LIMIT 1",
                (str(sid), ymd),
            ).fetchone()
        except sqlite3.Error:
            row = None
        finally:
            conn.close()
    except Exception:
        return {}
    if not row:
        return {}
    return {
        "date": row[0],
        "open": row[1],
        "high": row[2],
        "low": row[3],
        "close": row[4],
        "volume": row[5],
    }


def pick_charts(
    sid: str,
    *,
    limit: int = 3,
    public_only: bool = True,
    hold: bool = False,
) -> List[Dict[str, Any]]:
    """問一檔只帶最有用的幾張。公開文才進話筒；社團不送。"""
    rows = charts_for(sid)
    if public_only:
        rows = [r for r in rows if str(r.get("src") or "") == _PUBLIC_SRC]
    if hold:
        rows = [
            r
            for r in rows
            if any(k in str(r.get("note") or "") for k in _HOLD_NOTE)
        ]

    def score(row: Dict[str, Any]) -> tuple:
        note = str(row.get("note") or "")
        n = 0
        for key, weight in _NOTE_WEIGHT.items():
            if key in note:
                n = max(n, weight)
        if _snip_note(str(row.get("url") or "")):
            n = max(n, 95)
        if str(row.get("kind") or "") == "screenshot":
            n += 10
        for hint, own in _NOTE_OWN:
            if hint in note and own and own != str(sid):
                n -= 120
                break
        return (n, str(row.get("date") or ""))

    rows = sorted(rows, key=score, reverse=True)
    return rows[: max(0, int(limit))]


def format_charts_vs_official(
    sid: str,
    db_path: str = "",
    *,
    hold: bool = False,
    limit: int = 3,
) -> str:
    """第 4 顆眼睛：他的公開附圖對這檔官方日K。沒日K就標缺。"""
    rows = pick_charts(sid, limit=limit, public_only=True, hold=hold)
    if not rows:
        return ""
    parts: List[str] = []
    saw_bar = False
    missing = False
    for row in rows:
        note = str(row.get("note") or "附圖").strip()
        day = str(row.get("date") or "")
        bar = official_on(db_path, sid, day)
        if bar:
            saw_bar = True
            close = _px_short(bar.get("close"))
            hi = _px_short(bar.get("high"))
            lo = _px_short(bar.get("low"))
            op = _px_short(bar.get("open"))
            extra = f"官方收{close or '—'} 開{op or '—'} 高{hi or '—'} 低{lo or '—'}"
            parts.append(f"{day} {note}（{extra}）")
        else:
            missing = True
            parts.append(f"{day} {note}".strip())
    head = "他的附圖（長抱／F10）：" if hold else "他的附圖對官方日K："
    text = head + "；".join(parts)
    if missing and not saw_bar:
        text += "。官方這顆庫當日沒這列，不准編"
    elif missing:
        text += "。缺日K的不准編"
    text += "。截圖是他當下讀數，會改口。不是買訊"
    return text[:420]
