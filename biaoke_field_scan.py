# -*- coding: utf-8 -*-
"""他教過怎麼找還沒點名的族群：洞燭先機＋次族群第一名誰先過前高＋從底部找落後。

資金流騙不了人：單位＝CMoney 產業鏈佔當日法人買超％、％怎麼變。流入＝佔比升，流出＝佔比降。
佔比如實主判，飆大找法只參考、不是唯一。張數會被當下熱門族蓋過，不拿來排名。對五件只落在族群：底部這層（不數浪）、形態還沒過前高、
量價落後檔量起來、關鍵K＝官方收、碎形＝第一名還沒先過。個股不數 5／9。盤中未收不當官方收。
不是買訊、不進海選。這顆推出這型最落後次級兩到三檔；真正下單進場仍只認高低卡黃金買點。
"""
from __future__ import annotations

import json
import re
import sqlite3
from collections import defaultdict
from typing import Any, Dict, List, Optional, Sequence, Tuple

from industry_fine import TAUGHT_GROUPS

WANT_ASK = re.compile(
    r"(新族群|蠢蠢欲動|怎麼找|根據我的指引|找族群|還沒點名|底部蠢蠢|指引去找)"
)
SHARE_ASK = re.compile(
    r"(哪族|哪個族群|現在哪族|什麼族|先機|資金輪動|佔比|洞燭|"
    r"還沒當第一|升還沒第一)"
)

def _gmem(tag: str) -> Tuple[Tuple[str, str], ...]:
    return tuple((str(sid), "") for sid in (TAUGHT_GROUPS.get(tag) or ()))


# 教過的次族群：名稱／龍頭／落後檔對得上才沿用。排名掃全部 CMoney 三層鏈，不准發明一族、不准發明 5／9。
# needles＝籌碼K細項鏈裡他教過的次族群字，用來把族內成員從庫裡補齊。沒有準字就空，不准拿代工／通訊設備去灌。
_GROUPS: Tuple[Dict[str, Any], ...] = (
    {
        "key": "asic",
        "field": "ASIC",
        "names": ("ASIC", "創意", "世芯", "智原"),
        "needles": ("IP/ASIC", "ASIC"),
        "layers": ("電子上游", "IP/ASIC"),
        "leaders": (("3443", "創意"), ("3661", "世芯-KY"), ("3035", "智原")),
    },
    {
        "key": "cool",
        "field": "散熱",
        "names": ("散熱", "健策", "奇鋐"),
        "needles": ("散熱",),
        "layers": ("電子中游", "散熱零組件"),
        "leaders": (("3653", "健策"), ("3017", "奇鋐")),
        "members": _gmem("散熱"),
    },
    {
        "key": "inp",
        "field": "光通訊",
        "names": ("光通訊", "矽光子", "InP", "聯亞", "光聖", "波若威", "穩懋"),
        "needles": (),
        "layers": (),
        "leaders": (("3081", "聯亞"), ("2455", "全新"), ("6442", "光聖")),
        "members": _gmem("光通訊"),
    },
    {
        "key": "sat",
        "field": "低軌衛星",
        "names": ("低軌衛星", "低軌", "昇達科", "耀登", "華通", "穩懋"),
        "needles": (),
        "layers": (),
        "leaders": (("3491", "昇達科"), ("3105", "穩懋")),
        "members": _gmem("低軌衛星"),
    },
    {
        "key": "mature",
        "field": "成熟製程",
        "names": ("成熟製程", "聯電", "力積電", "世界"),
        "needles": (),
        "layers": (),
        "leaders": (("2303", "聯電"),),
        "members": _gmem("成熟製程"),
    },
    {
        "key": "robot",
        "field": "機器人",
        "names": ("機器人", "上銀", "研華", "精銳", "工業電腦"),
        "needles": (),
        "layers": (),
        "leaders": (("2049", "上銀"), ("2395", "研華")),
        "members": _gmem("機器人"),
    },
    {
        "key": "mem",
        "field": "記憶體製造",
        "names": ("記憶體製造", "記憶體原料", "南亞科", "華邦電", "旺宏"),
        "needles": ("記憶體製造",),
        "layers": ("電子上游", "記憶體製造"),
        "leaders": (("2408", "南亞科"),),
        "members": _gmem("記憶體製造"),
    },
    {
        "key": "memctl",
        "field": "記憶體控制",
        "names": ("記憶體控制", "控制晶片", "群聯", "點序"),
        "needles": (),
        "layers": (),
        "leaders": (("8299", "群聯"),),
        "members": _gmem("記憶體控制"),
    },
    {
        "key": "memmod",
        "field": "記憶體模組",
        "names": ("記憶體模組", "宜鼎", "威剛", "創見"),
        "needles": ("記憶體銷售",),
        "layers": ("電子上游", "記憶體銷售"),
        "leaders": (("5289", "宜鼎"),),
        "members": _gmem("記憶體模組"),
    },
    {
        "key": "memdist",
        "field": "記憶體通路",
        "names": ("記憶體通路", "至上", "增你強"),
        "needles": (),
        "layers": ("電子上游", "IC", "通路"),
        "leaders": (("8112", "至上"),),
        "members": _gmem("記憶體通路"),
    },
    {
        "key": "pcb",
        "field": "PCB",
        "names": ("PCB", "台光電", "CCL"),
        "needles": ("PCB",),
        "layers": ("電子上游", "PCB", "材料設備"),
        "leaders": (("2383", "台光電"),),
        "members": _gmem("PCB"),
    },
    {
        "key": "abf",
        "field": "ABF",
        "names": ("ABF", "欣興", "南電", "景碩"),
        "needles": ("ABF",),
        "layers": ("電子上游", "ABF"),
        "leaders": (("3037", "欣興"),),
        "members": _gmem("ABF"),
    },
    {
        "key": "pass",
        "field": "被動元件",
        "names": ("被動元件", "被動", "國巨"),
        "needles": ("被動元件",),
        "layers": ("電子上游", "被動元件"),
        "leaders": (("2327", "國巨"),),
    },
    {
        "key": "test",
        "field": "高階測試／封測",
        "names": ("高階測試", "封測", "穎崴", "旺矽", "汎銓"),
        "needles": ("封測",),
        "layers": ("電子上游", "IC", "封測"),
        "leaders": (("6515", "穎崴"), ("6223", "旺矽")),
        "laggards": (
            ("6257", "矽格"),
            ("3264", "欣銓"),
            ("2449", "京元電子"),
            ("2441", "超豐"),
        ),
    },
    {
        "key": "hitest",
        "field": "高階測試",
        "names": ("高階測試", "F4", "穎崴", "旺矽", "精測"),
        "needles": (),
        "layers": (),
        "leaders": (("6515", "穎崴"), ("6223", "旺矽")),
        "members": _gmem("高階測試"),
    },
    {
        "key": "mempack",
        "field": "記憶體封測",
        "names": ("記憶體封測", "力成", "南茂"),
        "needles": (),
        "layers": (),
        "leaders": (("6239", "力成"),),
        "members": _gmem("記憶體封測"),
    },
    {
        "key": "lab",
        "field": "檢測驗證",
        "names": ("檢測驗證", "汎銓", "閎康", "宜特"),
        "needles": (),
        "layers": (),
        "leaders": (("6830", "汎銓"),),
        "members": _gmem("檢測驗證"),
    },
    {
        "key": "solar",
        "field": "太陽能",
        "names": ("太陽能", "元晶", "茂迪"),
        "needles": ("太陽能",),
        "layers": ("電子下游", "太陽能"),
        "leaders": (("6443", "元晶"),),
        "members": _gmem("太陽能"),
    },
    {
        "key": "chem",
        "field": "特用化學",
        "names": ("特用化學", "台特化", "新應材"),
        "needles": (),
        "layers": (),
        "leaders": (("4772", "台特化"),),
        "members": _gmem("特用化學"),
    },
    {
        "key": "fab",
        "field": "無塵室",
        "names": ("無塵室", "聖暉", "漢唐", "亞翔"),
        "needles": (),
        "layers": (),
        "leaders": (("5536", "聖暉*"), ("2404", "漢唐")),
        "members": _gmem("無塵室"),
    },
    {
        "key": "air",
        "field": "航空",
        "names": ("航空", "華航", "長榮航", "星宇"),
        "needles": (),
        "layers": (),
        "leaders": (("2610", "華航"),),
        "members": _gmem("航空"),
    },
    {
        "key": "power",
        "field": "重電",
        "names": ("重電", "華城", "中興電", "士電"),
        "needles": (),
        "layers": (),
        "leaders": (("1519", "華城"),),
        "members": _gmem("重電"),
    },
)


def _is_flow_group(g: Dict[str, Any]) -> bool:
    """流入只認對得上 CMoney 三層的。機器人／低軌等聯想族不當另一套掃描。"""
    return bool(
        tuple(x for x in (g.get("layers") or ()) if str(x).strip())
        or tuple(x for x in (g.get("needles") or ()) if str(x).strip())
    )


def _flow_groups() -> Tuple[Dict[str, Any], ...]:
    return tuple(g for g in _GROUPS if _is_flow_group(g))


_HOW = (
    "他教過怎麼找：①次族群還沒熱、很少人提；②次族群第一名誰先過前高，不比絕對漲跌；"
    "③高點整理的從底部找落後。不是猜新聞。"
)
_HOW_LINES = (
    "他教過怎麼找：",
    "① 次族群還沒熱",
    "② 誰先過前高",
    "不比絕對漲跌",
    "③ 從底部找落後",
    "不是猜新聞。",
)
_PAGE_RULES = (
    "佔比如實主判。不是買訊、不進海選。",
    "每天資金進哪條主／次／細項。",
    "微弱可察也算進駐。",
    "每檔先寫買或不買。",
    "已持有寫留或不加碼。",
    "龍頭來不及買。比價下次級落後檔。",
    "股民追漲不追跌。先機不追當天第一名。",
    "點火後抓同鏈比價落後。",
    "捕捉只收近季有賺的。",
    "60低當嚴重低估觀察，不是買訊。",
    "連動名單只認對得上籌碼K的龍頭／落後。",
    "自選歸類只參考，不准整份覆蓋。",
    "聯想名單不當流入主判。",
    "推薦＝最落後次級兩到三檔，不是單檔買訊。",
    "剛好剛離零才標黃金買點。",
    "盤中未收不當官方收。",
)
_PAGE_NOTES = (
    "不是整層電子。",
    "先機＝佔比升還沒第一",
    "次級距20高≤−8%",
    "這型次級2～3檔約八成有人漲",
    "追第一名約五成六",
    "追當天第一名容易人去樓空。",
    "抓資金脈絡，不是猜新聞。",
    "金控／銀行當停車格。",
    "電子細項先機較穩。",
    "貼20高＝偏晚。",
)
_RULE_LINES = (
    "佔比如實主判。飆大找法只參考、不是唯一。",
    "資金輪動要比到主產業／次產業／產業鏈，再分龍頭與次級。",
    "龍頭來不及買，比價下次級落後檔。",
    "捕捉名單＝最落後次級兩到三檔，不是單檔買訊。",
    "盤中未收不當官方收。不是買訊、不進海選。",
    "這顆推出這型最落後次級兩到三檔給你選。",
    "剛好剛離零才標黃金買點。下單進場仍認剛離零。",
    "打股名沒打準會列出相近的請你點。",
)
# 五天太薄。兩個月仍薄。官方資金窗＝近 100 個有法人日，每天只記流入／流出第一名。
# 100 日簇內首漲停前一收：次級距20高中位 −8.6% → 簡化門檻 −8%。不鎖起點％、不發明 5／9。
# 進場前徵兆（scripts/dongzhu_precursor.py，窗 20260428–20260917，次級 vs20≤−8% 且仍低於60高，後10個交易日官方收）：
# 佔比升還沒當第一：漲停 54.3%／漲停或≥8% 71.4% n=70 套 4.3%
# 同上且略過金控／銀行停車格：62.7%／80.0% n=75 套 1.3% ← 編碼
# 電子細項：83.0% n=47 套 0；教過電子次族群：82.6% n=69 ← 編碼
# 航運 50% n=20、塑化 74.3% n=35、建築 54.5% n=11、電信 n=2、ASIC／散熱近100 n=0 → 不編碼
# 軍工沒有 CMoney 細項，不發明一族。
# 追當天流入第一名：29.7%／54.7% n=64
# 昨天第一名今天佔比在退：29.1%／54.5% n=55＝人去樓空，不推買
# 升還沒第一 ∩ 黃金買點：漲停或≥8% 70.8% ← 話筒買點旁標的勝率（型別鎖死，不是個股自己回測）
# 未編碼（n≥20 但沒贏基線）：佔比升最多 67.1%；升≥1pt 67.1%；連升兩日 63.2%；volr≥1.2 51.1%；vs20≤−12 70.5%；龍頭未過20高 71.4%
FLOW_LOOKBACK = 100
SHARE_DAYS = 5
MIN_CHAIN_N = 3
PRE_VS20 = -8.0
# 確定細項後捕捉名單＝距20高最深次級 n 檔。回測 1 檔約四成四、2 檔約七成、3 檔約八成有人漲；1 檔不准當買訊。
LAG_CAPTURE_N = 3
PREFER_NOT_LEAD = True
SKIP_LEAVING_HOT = True
SKIP_PARKING = True
PREFER_ELEC = True
PREFER_TAUGHT = True
PARKING_NEEDLES = ("金控", "銀行")
PRE_BUY_WIN_PCT = 70.8  # 後10日漲停或≥8%；只標在先機∩黃金買點
PRE_BUY_WIN_LABEL = f"勝率 {PRE_BUY_WIN_PCT:g}%"
PRE_BUY_WIN_BTN = f"勝{PRE_BUY_WIN_PCT:.0f}%"
# 話筒／海選共用：資金輪動要注意（100法人日走查鎖死）。
ROTATION_NOTES = (
    "看主產業／次產業／產業鏈，不是整層電子。",
    "近100日多數流入第一名只當1天；追當天第一名容易買在人去樓空。",
    "先機＝佔比升還沒當第一、次級距20高≤−8%，金控／銀行當停車格不拿來當先機（回測略過停車格後細項次級有人後10日漲停或≥8%約八成；電子細項這型約八成三；含停車格約七成；追第一名約五成五）。這是細項、不是單檔保證。航運／塑化／建築當先機沒贏過電子細項。軍工沒有 CMoney 細項、不發明一族。",
    "昨天第一名今天佔比在退，或單日掉超過1pt＝不留不買。貼20高＝偏晚。",
    "確定細項後看最落後次級兩到三檔（2檔約七成、3檔約八成有人漲）；1檔不到五成，不准當買訊。虧損／沒季報不能比價／EPS，不上捕捉。",
    "洞燭推薦＝這型次級落後檔，不是單檔保證。剛好剛離零才標黃金買點。紅箭頭不是買訊。盤中未收不當官方收。",
)


def rotation_notice_lines(db_path: str = "") -> List[str]:
    notes = list(ROTATION_NOTES)
    d = load_dongzhu_precursor(db_path) if db_path else {}
    rates = (d or {}).get("rates") or {}
    np_ = rates.get("no_park") or {}
    pre = rates.get("pre") or {}
    ch = rates.get("chase") or {}
    el = rates.get("elec") or {}
    if int(np_.get("n") or 0) < 20:
        return notes
    g = float(np_.get("gain") or 0)
    gpre = float(pre.get("gain") or 0)
    gch = float(ch.get("gain") or 0)
    notes[2] = (
        "先機＝佔比升還沒當第一、次級距20高≤−8%，金控／銀行當停車格不拿來當先機"
        f"（回測略過停車格後細項次級有人後10日漲停或≥8%約{g:.0f}%；"
        f"含停車格約{gpre:.0f}%；追第一名約{gch:.0f}%"
        + (
            f"；電子細項這型約{float(el.get('gain') or 0):.0f}%"
            if int(el.get("n") or 0) >= 20
            else ""
        )
        + "）。"
        f"這{g:.0f}%是細項、不是單檔保證。"
        "航運／塑化／建築當先機沒贏過電子細項。軍工沒有 CMoney 細項、不發明一族。"
    )
    lag1 = rates.get("lag1") or {}
    lag2 = rates.get("lag2") or {}
    lag3 = rates.get("lag3") or {}
    if int(lag2.get("n") or 0) >= 20 and int(lag3.get("n") or 0) >= 20:
        notes[4] = (
            "確定細項後看最落後次級兩到三檔"
            f"（2檔約{float(lag2.get('gain') or 0):.0f}%、"
            f"3檔約{float(lag3.get('gain') or 0):.0f}%有人漲）；"
            f"1檔約{float(lag1.get('gain') or 0):.0f}%，不准當買訊。"
        )
    return notes


def want_field_scan(ask: str) -> bool:
    return bool(WANT_ASK.search(str(ask or "")))


def want_share_cross(ask: str) -> bool:
    """飆大問哪族／先機才帶官方佔比。個股怎麼看不灌。"""
    q = str(ask or "")
    if want_field_scan(q):
        return True
    return bool(SHARE_ASK.search(q))


def _cap(db_path: str) -> str:
    try:
        from import_health import latest_complete_quote_date

        return str(latest_complete_quote_date(db_path) or "").replace("-", "")[:8]
    except Exception:
        return ""


def _chip_cap(db_path: str, cap: str = "") -> str:
    """法人還沒寫進當日柱（全日 0）不當資金日。盤中未收不當官方收。"""
    cap = _ymd(cap) or _cap(db_path)
    if not db_path or not cap:
        return cap
    conn = sqlite3.connect(db_path, timeout=8.0)
    try:
        if not _has_chip_cols(conn):
            return cap
        row = conn.execute(
            """
            SELECT MAX(REPLACE(CAST(date AS TEXT),'-','')) FROM daily_quotes
            WHERE REPLACE(CAST(date AS TEXT),'-','') <= ?
              AND IFNULL(foreign_net,0)+IFNULL(trust_net,0)+IFNULL(dealer_net,0) != 0
            """,
            (cap,),
        ).fetchone()
    except sqlite3.Error:
        return cap
    finally:
        conn.close()
    day = _ymd(row[0] if row else "")
    return day or cap


def _ymd(raw: Any) -> str:
    return str(raw or "").replace("-", "")[:8]


def _split_chain_text(chain: str) -> List[str]:
    return [p.strip() for p in str(chain or "").replace("／", "-").split("-") if p.strip()]


def _taught_for_chain(parts: Sequence[str]) -> Optional[Dict[str, Any]]:
    """三層鏈對得上教過的次族群才沿用龍頭／落後檔名稱。對不上不准硬套。"""
    want = [str(x) for x in parts if str(x)]
    if not want:
        return None
    for g in _GROUPS:
        layers = [str(x) for x in (g.get("layers") or ()) if str(x)]
        if layers and want == layers:
            return g
    return None


def _bars(db_path: str, sid: str, cap: str) -> List[Tuple[str, float, float, float, float]]:
    if not db_path or not sid:
        return []
    conn = sqlite3.connect(db_path, timeout=8.0)
    try:
        rows = conn.execute(
            "SELECT date, high, low, close, volume FROM daily_quotes "
            "WHERE stock_id=? ORDER BY REPLACE(CAST(date AS TEXT),'-','')",
            (sid,),
        ).fetchall()
    except sqlite3.Error:
        return []
    finally:
        conn.close()
    out: List[Tuple[str, float, float, float, float]] = []
    for d, h, l, c, v in rows:
        day = _ymd(d)
        if cap and day > cap:
            continue
        try:
            out.append((day, float(h), float(l), float(c), float(v or 0)))
        except (TypeError, ValueError):
            continue
    return out


def _stats(rows: Sequence[Tuple[str, float, float, float, float]]) -> Optional[Dict[str, Any]]:
    if len(rows) < 21:
        return None
    last = rows[-1]
    w20 = rows[-20:]
    w60 = rows[-60:] if len(rows) >= 60 else rows
    h20 = max(x[1] for x in w20)
    h60 = max(x[1] for x in w60)
    avg_v = sum(x[4] for x in w20) / 20.0
    prior = rows[-45:-5] if len(rows) >= 25 else rows[:-5]
    prior_h = max(x[1] for x in prior) if prior else h60
    last5_h = max(x[1] for x in rows[-5:])
    return {
        "date": last[0],
        "close": last[3],
        "vs20": (last[3] / h20 - 1.0) * 100.0 if h20 else 0.0,
        "vs60": (last[3] / h60 - 1.0) * 100.0 if h60 else 0.0,
        "volr": (last[4] / avg_v) if avg_v else 0.0,
        "broke": last5_h > prior_h,
    }


def _px(val: float) -> str:
    if abs(val - round(val)) < 1e-9:
        return str(int(round(val)))
    return f"{val:.2f}".rstrip("0").rstrip(".")


def _pct(val: float) -> str:
    if val > 0:
        return f"＋{val:.1f}%"
    if val < 0:
        return f"{val:.1f}%".replace("-", "−")
    return "0.0%"


def latest_spoken(db_path: str) -> str:
    if not db_path:
        return ""
    conn = sqlite3.connect(db_path, timeout=8.0)
    try:
        hit = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='biaoke_posts'"
        ).fetchone()
        if not hit:
            return ""
        row = conn.execute(
            "SELECT text FROM biaoke_posts "
            "WHERE IFNULL(kind,'post')!='reply' "
            "ORDER BY date DESC, time DESC, id DESC LIMIT 1"
        ).fetchone()
    except sqlite3.Error:
        return ""
    finally:
        conn.close()
    return str(row[0] or "") if row else ""


def _named_keys(spoken: str) -> set:
    blob = spoken or ""
    out = set()
    for g in _GROUPS:
        if any(n and n in blob for n in g["names"]):
            out.add(g["key"])
    if any(k in blob for k in ("轉弱", "減碼", "整理三個月")) and "pcb" in out:
        pass
    return out


def _stirring(st: Dict[str, Any]) -> bool:
    """底部蠢蠢：贴近 20 高、60 高仍明顯在上、量起來。不是已先過前高的主戰場。"""
    try:
        vs20 = float(st["vs20"])
        vs60 = float(st["vs60"])
        volr = float(st["volr"])
        broke = bool(st["broke"])
    except (KeyError, TypeError, ValueError):
        return False
    return vs20 >= -5.0 and vs60 <= -8.0 and volr >= 1.5 and not broke


def _empty_pick(line: str, *, cap: str = "", named: Optional[set] = None, missing: int = 0) -> Dict[str, Any]:
    named = named or set()
    named_txt = "、".join(g["field"] for g in _GROUPS if g["key"] in named)
    return {
        "how": _HOW,
        "cap": cap,
        "field": "",
        "key": "",
        "group": None,
        "laggard": None,
        "leader": None,
        "named": [g["field"] for g in _GROUPS if g["key"] in named],
        "named_txt": named_txt,
        "missing": missing,
        "line": line,
    }


def pick_unnamed_field(db_path: str, *, ask: str = "", spoken: Optional[str] = None) -> Dict[str, Any]:
    """結構化找法。對不上就空 field，不准猜。spoken=None 才讀最新主文；空字＝他沒開口。"""
    del ask
    if not db_path:
        return _empty_pick(_HOW + " 官方日 K 還沒這列，不准猜。不是買訊。")
    cap = _cap(db_path)
    if not cap:
        return _empty_pick(_HOW + " 官方完整日還沒，盤中未收不當官方收。不是買訊。")
    if spoken is None:
        spoken = latest_spoken(db_path)
    named = _named_keys(spoken)
    hits: List[Tuple[float, Dict[str, Any], Dict[str, Any], Optional[Tuple[str, str, Dict[str, Any]]]]] = []
    missing = 0
    for g in _flow_groups():
        if g["key"] in named:
            continue
        leaders = []
        for sid, name in g["leaders"]:
            st = _stats(_bars(db_path, sid, cap))
            if st:
                leaders.append((sid, name, st))
            else:
                missing += 1
        watch = list(g.get("laggards") or g["leaders"])
        for sid, name in watch:
            st = _stats(_bars(db_path, sid, cap))
            if not st:
                missing += 1
                continue
            if not _stirring(st):
                continue
            lead = leaders[0] if leaders else None
            if lead and lead[2].get("broke"):
                continue
            hits.append((float(st["volr"]), g, {"sid": sid, "name": name, **st}, lead))
    named_txt = "、".join(g["field"] for g in _GROUPS if g["key"] in named)
    extra = " 已點名的 " + named_txt + " 不當新族群。" if named_txt else ""
    if not hits:
        if missing:
            line = (
                _HOW
                + extra
                + f" 官方收 {cap} 還沒對上「還沒熱＋贴近20高＋量起來＋第一名還沒先過前高」的次族群，不准發明。不是買訊。"
            )
        else:
            line = (
                _HOW
                + extra
                + f" 官方收 {cap} 還沒對上底部蠢蠢的次族群，不准發明。不是買訊。"
            )
        return _empty_pick(line, cap=cap, named=named, missing=missing)
    hits.sort(key=lambda x: -x[0])
    _volr, g, st, lead = hits[0]
    lead_bit = ""
    if lead:
        lead_bit = (
            f"龍頭 {lead[1]} {lead[0]} 收 {_px(lead[2]['close'])}"
            f"{' 還沒先過前高' if not lead[2]['broke'] else ' 已先過前高'}。"
        )
    named_bit = ("已點名的 " + named_txt + " 不當新族群。") if named_txt else ""
    line = (
        _HOW
        + f" 官方收 {st['date']}：最像 {g['field']}，落後檔 {st['name']} {st['sid']}"
        f" 收 {_px(st['close'])} 距20高 {_pct(st['vs20'])} 距60高 {_pct(st['vs60'])}"
        f" 量比 {st['volr']:.2f}。{lead_bit}{named_bit}"
        "不是他當下點名。不是買訊。"
    )
    why = (
        f"還沒點名；落後檔 {st['name']} 贴近20高、60高仍明顯在上、量起來。"
        + (f" {lead_bit}" if lead_bit else "")
        + named_bit
        + "不是他當下點名。"
    )
    return {
        "how": _HOW,
        "cap": str(st["date"]),
        "field": g["field"],
        "key": g["key"],
        "group": g,
        "laggard": st,
        "leader": {"sid": lead[0], "name": lead[1], **lead[2]} if lead else None,
        "named": [x["field"] for x in _GROUPS if x["key"] in named],
        "named_txt": named_txt,
        "missing": missing,
        "why": why.strip(),
        "line": line,
    }


def scan_unnamed_field(db_path: str, *, ask: str = "", spoken: Optional[str] = None) -> str:
    """跟洞燭鈕同一套：主推細項＋最落後次級。矽格只是範例，不是固定名單。"""
    del ask
    data = dongzhu_picks(db_path, spoken=spoken)
    field = str(data.get("field") or "")
    if not field:
        return str(
            data.get("line")
            or (_HOW + " 還沒對上底部蠢蠢的次族群，不准發明。不是買訊。")
        )
    cap = str(data.get("cap") or "")
    lags = [x for x in list(data.get("laggards") or []) if x.get("sid")]
    lag_txt = "還沒有過門檻的次級。"
    if lags:
        names = "、".join(f"{x.get('name')} {x.get('sid')}" for x in lags[:3])
        lag_txt = f"捕捉最落後次級 {names}"
        vs = lags[0].get("vs20")
        if vs is not None:
            lag_txt += f" 距20高 {_pct(float(vs))}"
        lag_txt += "。"
    lead = data.get("leader") if isinstance(data.get("leader"), dict) else None
    lead_bit = ""
    if lead and (lead.get("name") or lead.get("sid")):
        close = lead.get("close")
        close_s = _px(float(close)) if close is not None else "—"
        lead_bit = (
            f"龍頭 {lead.get('name') or ''} {lead.get('sid') or ''} 收 {close_s}"
            f"{' 還沒先過前高' if not lead.get('broke') else ' 已先過前高'}。"
        )
    named = [str(x) for x in (data.get("named") or []) if x]
    named_bit = ("已點名的 " + "、".join(named) + " 不當新族群。") if named else ""
    return (
        _HOW
        + f" 官方收 {cap}：最像 {field}，"
        + lag_txt
        + lead_bit
        + named_bit
        + "不是他當下點名。不是買訊。"
    )


def share_cross_lines(db_path: str, *, spoken: Optional[str] = None) -> List[str]:
    """飆大對話用：洞燭同一套佔比短列。不是買訊、不進海選、不改黃金買點。"""
    data = dongzhu_picks(db_path, spoken=spoken) if db_path else {}
    lines = ["官方佔比（洞燭同一套）"]
    field = str((data or {}).get("field") or "")
    if not field:
        lines.append("還沒對上先機細項")
        lines.append("不是買訊、不進海選")
        return lines
    lines.append(f"此刻最像 {field}")
    parts = [str(x) for x in list((data or {}).get("layers") or []) if str(x)]
    if parts:
        lines.append(f"產業鏈 {parts[-1]}")
    sign = str((data or {}).get("pre_sign") or "")
    if sign == "pre":
        lines.append("佔比升還沒第一＝先機")
    elif sign == "chase":
        lines.append("已是當天第一名，偏晚")
    elif sign == "leaving":
        lines.append("佔比在退，人去樓空")
    vs = (data or {}).get("pre_vs20")
    if vs is not None and (data or {}).get("pre_ok"):
        try:
            lines.append(f"次級距20高 {_pct(float(vs))}")
        except (TypeError, ValueError):
            pass
    elif vs is not None:
        try:
            fv = float(vs)
            if abs(fv) > 1e-9:
                lines.append(f"次級距20高 {_pct(fv)}")
        except (TypeError, ValueError):
            pass
    lines.extend(_share_path_lines((data or {}).get("flow") or {}))
    lines.append("點名只參考，不是唯一")
    lines.append("不是買訊、不進海選")
    lines.append("買只認黃金買點")
    return lines


def format_share_cross(db_path: str, *, spoken: Optional[str] = None) -> str:
    from tg_layout import html_escape

    return "\n".join(
        html_escape(x) for x in share_cross_lines(db_path, spoken=spoken) if x
    )


def _stock_name(db_path: str, sid: str, fallback: str = "") -> str:
    if fallback and fallback != sid:
        return fallback
    if not db_path or not sid:
        return sid
    conn = sqlite3.connect(db_path, timeout=8.0)
    try:
        row = conn.execute(
            "SELECT stock_name FROM daily_quotes WHERE stock_id=? "
            "AND IFNULL(stock_name,'')!='' AND stock_name!=stock_id "
            "ORDER BY REPLACE(CAST(date AS TEXT),'-','') DESC LIMIT 1",
            (sid,),
        ).fetchone()
        if not row:
            hit = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='stock_universe'"
            ).fetchone()
            if hit:
                row = conn.execute(
                    "SELECT stock_name FROM stock_universe WHERE stock_id=? LIMIT 1",
                    (sid,),
                ).fetchone()
    except sqlite3.Error:
        row = None
    finally:
        conn.close()
    name = str(row[0] or "").strip() if row else ""
    return name or fallback or sid


def group_members(db_path: str, group: Optional[Dict[str, Any]]) -> List[Tuple[str, str]]:
    """族內成員＝他點過的龍頭／落後檔 ＋ 籌碼K細項鏈對得上的。不准發明次族群。"""
    if not group:
        return []
    out: Dict[str, str] = {}
    for sid, name in (
        list(group.get("leaders") or ())
        + list(group.get("laggards") or ())
        + list(group.get("members") or ())
    ):
        sid = str(sid or "").strip()
        if sid:
            out[sid] = str(name or sid)
    needles = tuple(group.get("needles") or ())
    chain = str(group.get("chain") or "").strip()
    if db_path and (needles or chain):
        conn = sqlite3.connect(db_path, timeout=8.0)
        try:
            hit = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='stock_fine_industry'"
            ).fetchone()
            if hit:
                rows: List[Any] = []
                if chain:
                    rows.extend(
                        conn.execute(
                            "SELECT stock_id, chain FROM stock_fine_industry "
                            "WHERE REPLACE(chain,'／','-')=? OR chain=?",
                            (chain, chain),
                        ).fetchall()
                    )
                if needles:
                    clauses = " OR ".join(["chain LIKE ?" for _ in needles])
                    rows.extend(
                        conn.execute(
                            f"SELECT stock_id, chain FROM stock_fine_industry WHERE {clauses}",
                            tuple(f"%{n}%" for n in needles),
                        ).fetchall()
                    )
                for sid, _chain in rows:
                    sid = str(sid or "").strip()
                    if not sid or sid in out:
                        continue
                    out[sid] = _stock_name(db_path, sid, "")
        except sqlite3.Error:
            pass
        finally:
            conn.close()
    return [(sid, out[sid]) for sid in sorted(out)]


def _has_chip_cols(conn: sqlite3.Connection) -> bool:
    cols = {str(r[1]) for r in conn.execute("PRAGMA table_info(daily_quotes)")}
    return {"foreign_net", "trust_net", "dealer_net"} <= cols


def ensure_dongzhu_flow_table(db_path: str) -> None:
    if not db_path:
        return
    conn = sqlite3.connect(db_path, timeout=8.0)
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS dongzhu_flow_tape (
                date TEXT NOT NULL,
                group_key TEXT NOT NULL,
                field TEXT NOT NULL,
                three_net INTEGER DEFAULT 0,
                member_n INTEGER DEFAULT 0,
                pos_member INTEGER DEFAULT 0,
                market_in INTEGER DEFAULT 0,
                market_out INTEGER DEFAULT 0,
                share_pct REAL DEFAULT 0,
                share_chg REAL DEFAULT 0,
                fine_tag TEXT DEFAULT '',
                PRIMARY KEY (date, group_key)
            )
            """
        )
        cols = {str(r[1]) for r in conn.execute("PRAGMA table_info(dongzhu_flow_tape)")}
        for name, spec in (
            ("pos_member", "INTEGER DEFAULT 0"),
            ("market_in", "INTEGER DEFAULT 0"),
            ("market_out", "INTEGER DEFAULT 0"),
            ("share_pct", "REAL DEFAULT 0"),
            ("share_chg", "REAL DEFAULT 0"),
            ("fine_tag", "TEXT DEFAULT ''"),
        ):
            if name not in cols:
                conn.execute(f"ALTER TABLE dongzhu_flow_tape ADD COLUMN {name} {spec}")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_dongzhu_flow_key ON dongzhu_flow_tape(group_key, date)"
        )
        conn.commit()
    finally:
        conn.close()


_PRECURSOR_MEMO: Dict[str, Dict[str, Any]] = {}


def ensure_dongzhu_precursor_table(db_path: str) -> None:
    if not db_path:
        return
    conn = sqlite3.connect(db_path, timeout=8.0)
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS dongzhu_precursor (
                cap TEXT PRIMARY KEY,
                ran_at TEXT NOT NULL,
                payload TEXT NOT NULL
            )
            """
        )
        conn.commit()
    finally:
        conn.close()


def store_dongzhu_precursor(db_path: str, cap: str, payload: Dict[str, Any]) -> None:
    if not db_path or not cap:
        return
    ensure_dongzhu_precursor_table(db_path)
    blob = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    conn = sqlite3.connect(db_path, timeout=8.0)
    try:
        conn.execute(
            "INSERT OR REPLACE INTO dongzhu_precursor (cap, ran_at, payload) VALUES (?,?,?)",
            (str(cap)[:8], datetime_now_iso(), blob),
        )
        conn.commit()
    finally:
        conn.close()
    _PRECURSOR_MEMO.pop(str(db_path), None)


def datetime_now_iso() -> str:
    from datetime import datetime

    return datetime.now().isoformat(timespec="seconds")


def load_dongzhu_precursor(db_path: str) -> Dict[str, Any]:
    if not db_path:
        return {}
    hit = _PRECURSOR_MEMO.get(str(db_path))
    if hit is not None:
        return hit
    conn = sqlite3.connect(db_path, timeout=8.0)
    try:
        row = conn.execute(
            "SELECT cap, payload FROM dongzhu_precursor ORDER BY cap DESC LIMIT 1"
        ).fetchone()
    except sqlite3.Error:
        _PRECURSOR_MEMO[str(db_path)] = {}
        return {}
    finally:
        conn.close()
    if not row:
        _PRECURSOR_MEMO[str(db_path)] = {}
        return {}
    try:
        data = json.loads(row[1] or "{}")
    except (TypeError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    data["cap"] = str(row[0] or data.get("cap") or "")
    _PRECURSOR_MEMO[str(db_path)] = data
    return data


def live_dongzhu_flags(db_path: str) -> Dict[str, bool]:
    d = load_dongzhu_precursor(db_path)
    def _flag(key: str, default: bool) -> bool:
        if key in d and d[key] is not None:
            return bool(d[key])
        return default

    return {
        "prefer_rising_not_lead": _flag("prefer_rising_not_lead", PREFER_NOT_LEAD),
        "skip_leaving_hot": _flag("skip_leaving_hot", SKIP_LEAVING_HOT),
        "skip_parking": _flag("skip_parking", SKIP_PARKING),
        "prefer_elec": _flag("prefer_elec", PREFER_ELEC),
        "prefer_taught": _flag("prefer_taught", PREFER_TAUGHT),
    }


def _quote_dates(conn: sqlite3.Connection, cap: str, n: int = 10) -> List[str]:
    cap = _ymd(cap)
    if not cap:
        return []
    rows = conn.execute(
        "SELECT DISTINCT REPLACE(CAST(date AS TEXT),'-','') AS d FROM daily_quotes "
        "WHERE REPLACE(CAST(date AS TEXT),'-','') <= ? ORDER BY d DESC LIMIT ?",
        (cap, int(n)),
    ).fetchall()
    return sorted(_ymd(r[0]) for r in rows if _ymd(r[0]))


def _chip_dates(conn: sqlite3.Connection, cap: str, n: int = FLOW_LOOKBACK) -> List[str]:
    """近 n 個「有法人」交易日。全日 0 不當資金日。沒籌碼欄就退回日 K 日。"""
    cap = _ymd(cap)
    if not cap:
        return []
    if not _has_chip_cols(conn):
        return _quote_dates(conn, cap, n)
    rows = conn.execute(
        """
        SELECT d FROM (
          SELECT REPLACE(CAST(date AS TEXT),'-','') AS d,
                 SUM(IFNULL(foreign_net,0)+IFNULL(trust_net,0)+IFNULL(dealer_net,0)) AS t
          FROM daily_quotes
          WHERE REPLACE(CAST(date AS TEXT),'-','') <= ?
            AND length(stock_id)=4
          GROUP BY 1
          HAVING t != 0
        ) ORDER BY d DESC LIMIT ?
        """,
        (cap, int(n)),
    ).fetchall()
    return sorted(_ymd(r[0]) for r in rows if _ymd(r[0]))


def record_dongzhu_flow(db_path: str, cap: str = "", lookback: int = 10) -> int:
    """把教過的次族群寫進膠帶：細項、三大法人張、佔當日買超／賣超％。來源＝日 K 的 T86，不抓分點。"""
    if not db_path:
        return 0
    cap = _ymd(cap) or _cap(db_path)
    if not cap:
        return 0
    ensure_dongzhu_flow_table(db_path)
    conn = sqlite3.connect(db_path, timeout=8.0)
    written = 0
    try:
        if not _has_chip_cols(conn):
            return 0
        dates = _chip_dates(conn, cap, lookback)
        if not dates:
            return 0
        members = {g["key"]: [sid for sid, _n in group_members(db_path, g)] for g in _flow_groups()}
        qmarks_by_key = {}
        for key, sids in members.items():
            if sids:
                qmarks_by_key[key] = ",".join("?" * len(sids))
        prev_share: Dict[str, float] = {}
        for day in dates:
            mkt = conn.execute(
                """
                SELECT
                  IFNULL(SUM(CASE WHEN t>0 THEN t ELSE 0 END),0),
                  IFNULL(SUM(CASE WHEN t<0 THEN -t ELSE 0 END),0)
                FROM (
                  SELECT IFNULL(foreign_net,0)+IFNULL(trust_net,0)+IFNULL(dealer_net,0) AS t
                  FROM daily_quotes
                  WHERE REPLACE(CAST(date AS TEXT),'-','')=? AND length(stock_id)=4
                )
                """,
                (day,),
            ).fetchone()
            market_in = int(mkt[0] or 0) if mkt else 0
            market_out = int(mkt[1] or 0) if mkt else 0
            for g in _flow_groups():
                sids = members.get(g["key"]) or []
                if not sids or g["key"] not in qmarks_by_key:
                    continue
                row = conn.execute(
                    f"""
                    SELECT COUNT(*),
                           IFNULL(SUM(t),0),
                           IFNULL(SUM(CASE WHEN t>0 THEN 1 ELSE 0 END),0)
                    FROM (
                      SELECT IFNULL(foreign_net,0)+IFNULL(trust_net,0)+IFNULL(dealer_net,0) AS t
                      FROM daily_quotes
                      WHERE REPLACE(CAST(date AS TEXT),'-','')=?
                        AND stock_id IN ({qmarks_by_key[g['key']]})
                    )
                    """,
                    [day, *sids],
                ).fetchone()
                n = int(row[0] or 0) if row else 0
                three = int(row[1] or 0) if row else 0
                pos_n = int(row[2] or 0) if row else 0
                if three > 0 and market_in > 0:
                    share = 100.0 * three / market_in
                elif three < 0 and market_out > 0:
                    share = -100.0 * abs(three) / market_out
                else:
                    share = 0.0
                chg = share - float(prev_share.get(g["key"]) or 0.0) if g["key"] in prev_share else 0.0
                prev_share[g["key"]] = share
                needles = tuple(g.get("needles") or ())
                fine = str(needles[-1] if needles else g["field"])
                conn.execute(
                    """
                    INSERT INTO dongzhu_flow_tape(
                        date, group_key, field, three_net, member_n, pos_member,
                        market_in, market_out, share_pct, share_chg, fine_tag
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(date, group_key) DO UPDATE SET
                        field=excluded.field,
                        three_net=excluded.three_net,
                        member_n=excluded.member_n,
                        pos_member=excluded.pos_member,
                        market_in=excluded.market_in,
                        market_out=excluded.market_out,
                        share_pct=excluded.share_pct,
                        share_chg=excluded.share_chg,
                        fine_tag=excluded.fine_tag
                    """,
                    (day, g["key"], g["field"], three, n, pos_n, market_in, market_out, share, chg, fine),
                )
                written += 1
        conn.commit()
    except sqlite3.Error:
        return 0
    finally:
        conn.close()
    return written


def _ignite_from_nets(nets: Sequence[int], shares: Optional[Sequence[float]] = None) -> Dict[str, Any]:
    """流入／流出看佔比升降。沒有佔比才退回連日買超張。單日暴衝張不算流入。"""
    vals = [int(n) for n in nets][-5:]
    pos = sum(1 for n in vals if n > 0)
    cum = sum(vals)
    last = vals[-1] if vals else 0
    mx = max((abs(n) for n in vals), default=0)
    lots_in = bool(vals) and pos >= 3 and cum > 0 and last > 0 and (pos >= 4 or mx * 10 <= abs(cum) * 8)
    sh = [float(x) for x in (shares or [])][-5:]
    rise = sum(1 for i in range(1, len(sh)) if sh[i] > sh[i - 1] + 1e-9)
    up = (sh[-1] - sh[0]) if len(sh) >= 2 else 0.0
    share_in = len(sh) >= 3 and rise >= 2 and up > 0 and sh[-1] > 0
    share_out = len(sh) >= 2 and up < -1e-9
    if sh:
        flowing_in = bool(share_in and not share_out)
    else:
        flowing_in = bool(lots_in)
    return {
        "nets": vals,
        "pos_days": pos,
        "cum5": cum,
        "last": last,
        "shares": sh,
        "share_last": sh[-1] if sh else 0.0,
        "share_up": up,
        "share_rise_days": rise,
        "flowing_in": flowing_in,
        "slow_in": flowing_in,
    }


def _fine_members(conn: sqlite3.Connection) -> Dict[str, List[str]]:
    hit = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='stock_fine_industry'"
    ).fetchone()
    if not hit:
        return {}
    out: Dict[str, List[str]] = {}
    for sid, chain in conn.execute("SELECT stock_id, chain FROM stock_fine_industry"):
        sid = str(sid or "").strip()
        parts = _split_chain_text(str(chain or ""))
        if not sid or not parts or parts[-1] == "其他":
            continue
        out.setdefault("-".join(parts), []).append(sid)
    return out


def _turnover_leaders(
    db_path: str, sids: Sequence[str], cap: str, n: int = 2
) -> List[Tuple[str, str]]:
    if not db_path or not sids:
        return []
    cap = _ymd(cap)
    uniq = [str(s) for s in sids if str(s)]
    if not uniq:
        return []
    k = 1 if len(uniq) <= 3 else min(int(n), 2)
    q = ",".join("?" * len(uniq))
    conn = sqlite3.connect(db_path, timeout=8.0)
    try:
        rows = conn.execute(
            f"""
            SELECT stock_id, SUM(IFNULL(close,0)*IFNULL(volume,0)) tv
            FROM daily_quotes
            WHERE stock_id IN ({q})
              AND REPLACE(CAST(date AS TEXT),'-','')<=?
            GROUP BY stock_id
            ORDER BY tv DESC
            LIMIT ?
            """,
            [*uniq, cap, k],
        ).fetchall()
    except sqlite3.Error:
        rows = []
    finally:
        conn.close()
    return [(str(r[0]), _stock_name(db_path, str(r[0]), "")) for r in rows]


def _group_from_chain(
    db_path: str,
    chain: str,
    sids: Sequence[str],
    cap: str,
) -> Dict[str, Any]:
    del db_path, cap
    parts = _split_chain_text(chain)
    taught = _taught_for_chain(parts)
    if taught:
        g = dict(taught)
        g["chain"] = chain
        return g
    field = "／".join(parts[1:]) if len(parts) > 1 else (parts[0] if parts else chain)
    return {
        "key": f"fine:{chain}",
        "field": field,
        "chain": chain,
        "layers": tuple(parts),
        "needles": (),
        "leaders": (),
        "laggards": (),
        "members": [(str(s), "") for s in sids],
    }


def _fill_leaders(db_path: str, group: Optional[Dict[str, Any]], cap: str) -> Dict[str, Any]:
    g = dict(group or {})
    if g.get("leaders"):
        return g
    sids = [str(s) for s, _n in list(g.get("members") or ()) if s]
    g["leaders"] = tuple(_turnover_leaders(db_path, sids, cap))
    return g


def _chain_pre_ok(
    db_path: str, group: Optional[Dict[str, Any]], cap: str
) -> Tuple[bool, float]:
    """100日首漲停前：次級距20高中位 −8.6%。簡化＝至少一檔次級 vs20≤−8% 且仍低於60高。"""
    if not group or not db_path:
        return False, 0.0
    g = _fill_leaders(db_path, group, cap)
    leads = {str(x[0]) for x in (g.get("leaders") or ()) if x}
    pool = list(g.get("laggards") or ())
    if not pool:
        pool = [(s, n) for s, n in list(g.get("members") or ()) if str(s) not in leads]
    best: Optional[float] = None
    seen = set()
    n = 0
    for sid, _name in pool:
        sid = str(sid or "")
        if not sid or sid in seen or sid in leads:
            continue
        seen.add(sid)
        st = _stats(_bars_tail(db_path, sid, cap, 80))
        n += 1
        if not st or st.get("vs20") is None:
            if n >= 8:
                break
            continue
        vs20 = float(st["vs20"])
        vs60 = float(st.get("vs60") or 0)
        if vs60 < 0 and (best is None or vs20 < best):
            best = vs20
        if n >= 8:
            break
    if best is None:
        return False, 0.0
    return best <= PRE_VS20, best


def _chain_laggards(
    db_path: str,
    group: Optional[Dict[str, Any]],
    cap: str,
    *,
    n: int = LAG_CAPTURE_N,
    group_last: int = 0,
) -> List[Dict[str, Any]]:
    """細項內非龍頭、近季有賺、vs20≤−8% 且仍低於60高，距20高最深的 n 檔。
    虧損／沒季報不能做價／EPS 比價，不上捕捉。不鎖矽格／欣銓。不是買訊。
    """
    if not group or not db_path or n <= 0:
        return []
    g = _fill_leaders(db_path, group, cap)
    leads = {str(x[0]) for x in (g.get("leaders") or ()) if x}
    scored: List[Tuple[float, Dict[str, Any]]] = []
    seen = set()
    layers = list(g.get("layers") or [])
    try:
        from industry_brief import has_positive_eps as _eps_ok
    except Exception:

        def _eps_ok(_path, _sid):
            return False
    for sid, name in group_members(db_path, g):
        sid = str(sid or "")
        if not sid or sid in seen or sid in leads:
            continue
        seen.add(sid)
        if not _eps_ok(db_path, sid):
            continue
        item = _decorate(db_path, sid, name, cap, None, group_last=group_last)
        if item.get("close") is None or item.get("vs20") is None:
            continue
        vs20 = float(item["vs20"])
        vs60 = float(item.get("vs60") or 0)
        if vs20 > PRE_VS20 or vs60 >= 0:
            continue
        item["role"] = _stock_role(g, sid)
        item["layers"] = _chain_parts(db_path, sid) or layers
        scored.append((vs20, item))
    scored.sort(key=lambda x: x[0])
    return [item for _v, item in scored[:n]]


def _bars_tail(
    db_path: str, sid: str, cap: str, n: int = 80
) -> List[Tuple[str, float, float, float, float]]:
    if not db_path or not sid:
        return []
    cap = _ymd(cap)
    conn = sqlite3.connect(db_path, timeout=8.0)
    try:
        rows = conn.execute(
            "SELECT date, high, low, close, volume FROM daily_quotes "
            "WHERE stock_id=? AND REPLACE(CAST(date AS TEXT),'-','')<=? "
            "ORDER BY REPLACE(CAST(date AS TEXT),'-','') DESC LIMIT ?",
            (sid, cap, int(n)),
        ).fetchall()
    except sqlite3.Error:
        return []
    finally:
        conn.close()
    out: List[Tuple[str, float, float, float, float]] = []
    for d, h, l, c, v in reversed(rows):
        try:
            out.append((_ymd(d), float(h), float(l), float(c), float(v or 0)))
        except (TypeError, ValueError):
            continue
    return out


def _chain_is_named(spoken: str, parts: Sequence[str], named_keys: set) -> bool:
    taught = _taught_for_chain(parts)
    if taught and taught["key"] in named_keys:
        return True
    blob = spoken or ""
    last = str(parts[-1]) if parts else ""
    if last and len(last) >= 2 and last in blob:
        return True
    if taught and any(n and n in blob for n in (taught.get("names") or ())):
        return True
    return False


def fine_share_table(
    db_path: str, cap: str = "", lookback: int = FLOW_LOOKBACK
) -> Dict[str, Dict[str, Any]]:
    """全部 CMoney 三層鏈、近 lookback 個有法人日的佔比。沒細項表就空。"""
    if not db_path:
        return {}
    cap = _ymd(cap) or _chip_cap(db_path) or _cap(db_path)
    if not cap:
        return {}
    conn = sqlite3.connect(db_path, timeout=8.0)
    try:
        if not _has_chip_cols(conn):
            return {}
        dates = _chip_dates(conn, cap, lookback)
        members = _fine_members(conn)
        if not dates or not members:
            return {}
        sid_chain = {sid: chain for chain, sids in members.items() for sid in sids}
        q = ",".join("?" * len(dates))
        rows = conn.execute(
            f"""
            SELECT REPLACE(CAST(date AS TEXT),'-',''), stock_id,
                   IFNULL(foreign_net,0)+IFNULL(trust_net,0)+IFNULL(dealer_net,0)
            FROM daily_quotes
            WHERE REPLACE(CAST(date AS TEXT),'-','') IN ({q})
              AND length(stock_id)=4
            """,
            dates,
        ).fetchall()
    except sqlite3.Error:
        return {}
    finally:
        conn.close()
    mkt_in: Dict[str, int] = defaultdict(int)
    chain_net: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
    chain_pos: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for day_raw, sid, three in rows:
        day = _ymd(day_raw)
        sid = str(sid or "").strip()
        try:
            three = int(three or 0)
        except (TypeError, ValueError):
            three = 0
        if three > 0:
            mkt_in[day] += three
        chain = sid_chain.get(sid)
        if not chain:
            continue
        chain_net[chain][day] += three
        if three > 0:
            chain_pos[chain][day] += 1
    out: Dict[str, Dict[str, Any]] = {}
    for chain, sids in members.items():
        parts = _split_chain_text(chain)
        taught = _taught_for_chain(parts)
        if len(sids) < MIN_CHAIN_N and not taught:
            continue
        nets = [int(chain_net[chain].get(d) or 0) for d in dates]
        shares: List[float] = []
        for d, three in zip(dates, nets):
            inn = int(mkt_in.get(d) or 0)
            if inn > 0 and three > 0:
                shares.append(100.0 * three / inn)
            else:
                shares.append(0.0)
        last_n = nets[-SHARE_DAYS:]
        last_s = shares[-SHARE_DAYS:]
        last_d = dates[-SHARE_DAYS:]
        ign = _ignite_from_nets(last_n, last_s)
        last_day = last_d[-1] if last_d else ""
        ign["dates"] = last_d
        ign["fine_tag"] = parts[-1] if parts else chain
        ign["pos_member"] = int(chain_pos[chain].get(last_day) or 0)
        ign["member_n"] = len(sids)
        ign["share_chg"] = (last_s[-1] - last_s[-2]) if len(last_s) >= 2 else 0.0
        ign["sids"] = list(sids)
        ign["layers"] = parts
        ign["chain"] = chain
        ign["_shares_all"] = shares
        out[chain] = ign
    lead_n: Dict[str, int] = defaultdict(int)
    daily: List[Tuple[str, str, float]] = []
    if dates:
        for i in range(len(dates)):
            best_ch = ""
            best_sh = 0.0
            for chain, ign in out.items():
                sh = float((ign.get("_shares_all") or [0.0] * len(dates))[i] or 0)
                if sh > best_sh:
                    best_sh = sh
                    best_ch = chain
            if best_ch and best_sh > 0:
                lead_n[best_ch] += 1
                daily.append((dates[i], best_ch, best_sh))
    today_ch = daily[-1][1] if daily else ""
    yest_ch = daily[-2][1] if len(daily) >= 2 else ""
    for ign in out.values():
        series = list(ign.pop("_shares_all", []) or [])
        chain = str(ign.get("chain") or "")
        ign["in_lead_n"] = int(lead_n.get(chain, 0))
        ign["share_pos_n"] = sum(1 for x in series if float(x or 0) > 0)
        ign["lookback_n"] = len(dates)
        ign["is_lead_today"] = bool(chain and chain == today_ch)
        ign["was_lead_yest"] = bool(chain and chain == yest_ch)
        chg = float(ign.get("share_chg") or 0)
        ign["leaving"] = bool(
            ign["was_lead_yest"] and (not ign["is_lead_today"] or chg < -1e-9)
        )
    return out


def group_ignite(db_path: str, group_key: str, cap: str) -> Dict[str, Any]:
    empty = {
        "nets": [],
        "pos_days": 0,
        "cum5": 0,
        "last": 0,
        "slow_in": False,
        "dates": [],
        "shares": [],
        "share_last": 0.0,
        "share_up": 0.0,
        "share_rise_days": 0,
        "flowing_in": False,
        "fine_tag": "",
        "pos_member": 0,
        "member_n": 0,
        "share_chg": 0.0,
    }
    if not db_path or not group_key:
        return empty
    ensure_dongzhu_flow_table(db_path)
    cap = _ymd(cap)
    conn = sqlite3.connect(db_path, timeout=8.0)
    try:
        rows = conn.execute(
            "SELECT date, three_net, IFNULL(share_pct,0), IFNULL(fine_tag,''), "
            "IFNULL(pos_member,0), IFNULL(member_n,0), IFNULL(share_chg,0) "
            "FROM dongzhu_flow_tape WHERE group_key=? AND date<=? ORDER BY date",
            (group_key, cap),
        ).fetchall()
    except sqlite3.Error:
        rows = []
    finally:
        conn.close()
    last = rows[-5:] if rows else []
    ign = _ignite_from_nets(
        [int(r[1] or 0) for r in last],
        [float(r[2] or 0) for r in last],
    )
    ign["dates"] = [_ymd(r[0]) for r in last]
    if last:
        ign["fine_tag"] = str(last[-1][3] or "")
        ign["pos_member"] = int(last[-1][4] or 0)
        ign["member_n"] = int(last[-1][5] or 0)
        ign["share_chg"] = float(last[-1][6] or 0)
    else:
        ign["fine_tag"] = ""
        ign["pos_member"] = 0
        ign["member_n"] = 0
        ign["share_chg"] = 0.0
    return ign


def _member_nets(db_path: str, sid: str, cap: str, n: int = 5) -> List[int]:
    if not db_path or not sid:
        return []
    conn = sqlite3.connect(db_path, timeout=8.0)
    try:
        if not _has_chip_cols(conn):
            return []
        rows = conn.execute(
            "SELECT IFNULL(foreign_net,0)+IFNULL(trust_net,0)+IFNULL(dealer_net,0) "
            "FROM daily_quotes WHERE stock_id=? AND REPLACE(CAST(date AS TEXT),'-','')<=? "
            "ORDER BY REPLACE(CAST(date AS TEXT),'-','') DESC LIMIT ?",
            (sid, _ymd(cap), int(n)),
        ).fetchall()
    except sqlite3.Error:
        return []
    finally:
        conn.close()
    vals = [int(r[0] or 0) for r in rows]
    vals.reverse()
    return vals


def member_cum5(db_path: str, sid: str, cap: str) -> int:
    return int(sum(_member_nets(db_path, sid, cap, 5)))


def member_last_net(db_path: str, sid: str, cap: str) -> int:
    nets = _member_nets(db_path, sid, cap, 1)
    return int(nets[-1]) if nets else 0


def _fine_chain(db_path: str, sid: str) -> str:
    parts = _chain_parts(db_path, sid)
    return parts[-1] if parts else ""


def _chain_parts(db_path: str, sid: str) -> List[str]:
    if not db_path or not sid:
        return []
    conn = sqlite3.connect(db_path, timeout=8.0)
    try:
        hit = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='stock_fine_industry'"
        ).fetchone()
        if not hit:
            return []
        row = conn.execute(
            "SELECT chain FROM stock_fine_industry WHERE stock_id=? LIMIT 1", (sid,)
        ).fetchone()
    except sqlite3.Error:
        return []
    finally:
        conn.close()
    chain = str(row[0] or "").strip() if row else ""
    if not chain:
        return []
    return [p.strip() for p in chain.replace("／", "-").split("-") if p.strip()]


def _group_layers(db_path: str, group: Optional[Dict[str, Any]]) -> List[str]:
    if not group:
        return []
    declared = [str(x) for x in (group.get("layers") or ()) if str(x)]
    sid = ""
    leads = list(group.get("leaders") or ())
    if leads:
        sid = str(leads[0][0] or "")
    parts = _chain_parts(db_path, sid) if sid else []
    return parts or declared


def _layer_lines(layers: Sequence[str]) -> List[str]:
    labs = ("主產業", "次產業", "產業鏈")
    bits = []
    for i, part in enumerate(list(layers)[:3]):
        lab = labs[i] if i < len(labs) else "層"
        bits.append(f"{lab} {part}")
    return bits


def _layer_line(layers: Sequence[str]) -> str:
    return " → ".join(_layer_lines(layers))


def _layer_short(layers: Sequence[str]) -> str:
    return "／".join(str(x) for x in layers if x)


def _stock_role(group: Optional[Dict[str, Any]], sid: str) -> str:
    sid = str(sid or "")
    if not group or not sid:
        return ""
    leads = [str(x[0]) for x in (group.get("leaders") or ()) if x]
    if sid in leads:
        return "龍頭"
    return "次級"


def _sibling_txt(
    group: Optional[Dict[str, Any]],
    all_igns: Sequence[Dict[str, Any]],
    db_path: str = "",
) -> str:
    if not group or not all_igns:
        return ""
    layers = _group_layers(db_path, group)
    if not layers:
        return ""
    main = layers[0]
    by_key = {str(g["key"]): g for g in _GROUPS}
    scored: List[Tuple[float, str]] = []
    for ign in all_igns:
        gl = [str(x) for x in (ign.get("_layers") or []) if str(x)]
        if not gl:
            g = by_key.get(str(ign.get("_key") or ""))
            if not g:
                continue
            gl = _group_layers(db_path, g)
        if not gl or gl[0] != main:
            continue
        last = float(ign.get("share_last") or 0)
        up = float(ign.get("share_up") or 0)
        if last == 0 and abs(up) < 1e-9:
            continue
        sub = "／".join(gl[1:]) if len(gl) > 1 else gl[0]
        mark = "升" if up > 0 else ("退" if up < 0 else "平")
        scored.append((last, f"{sub} {_share_txt(last)}（{mark}）"))
    scored.sort(key=lambda x: -x[0])
    bits = [txt for _last, txt in scored[:8]]
    if len(bits) < 2:
        return ""
    return "同主產業 " + "｜".join(bits)


def _parity_txt(
    group: Optional[Dict[str, Any]],
    buys: Sequence[Dict[str, Any]],
    leader: Optional[Dict[str, Any]],
) -> str:
    if not group:
        return ""
    lead_sids = {str(x[0]) for x in (group.get("leaders") or ()) if x}
    buy_sids = {str(x.get("sid") or "") for x in buys}
    lead_bought = bool(lead_sids & buy_sids)
    sec_bought = any(str(x.get("role") or "") == "次級" for x in buys)
    broke = bool((leader or {}).get("broke"))
    if broke and sec_bought:
        return "龍頭已先過前高＝來不及買；比價下次級有黃金買點才切入。"
    if not lead_bought and sec_bought:
        return "龍頭這刻沒有黃金買點；比價下次級有買點才切入。"
    if lead_bought and sec_bought:
        return "龍頭有買點；次級只當比價，不是替代買訊。"
    if lead_bought:
        return "先看龍頭。次級還沒買點，不准發明比價切入。"
    return ""


def _lots_txt(val: int) -> str:
    n = int(val)
    body = f"{abs(n):,}"
    if n > 0:
        return f"＋{body}張"
    if n < 0:
        return f"−{body}張"
    return "0張"


def _share_txt(val: float) -> str:
    n = float(val)
    body = f"{abs(n):.1f}%"
    if n < 0:
        return "−" + body
    return body


def _pt_txt(val: float) -> str:
    n = float(val)
    body = f"{abs(n):.1f}pt"
    if n > 0:
        return "＋" + body
    if n < 0:
        return "−" + body
    return "0.0pt"


def _share_path(ign: Dict[str, Any]) -> str:
    shares = list(ign.get("shares") or [])
    if len(shares) >= 2:
        return f"{shares[0]:.1f}%→{shares[-1]:.1f}%（{_pt_txt(shares[-1] - shares[0])}）"
    if shares:
        return _share_txt(shares[-1])
    return ""


_PHONE_W = 18


def _pack_phone(bits: Sequence[str], sep: str = "→") -> List[str]:
    """一行最多約 18 字；數字不從中間切開。"""
    lines: List[str] = []
    buf = ""
    for bit in [str(x) for x in bits if str(x)]:
        piece = bit if not buf else f"{sep}{bit}"
        trial = bit if not buf else buf + piece
        if buf and len(trial) > _PHONE_W:
            lines.append(buf)
            buf = bit
        else:
            buf = trial
    if buf:
        lines.append(buf)
    return lines


def _share_path_lines(ign: Dict[str, Any]) -> List[str]:
    shares = list(ign.get("shares") or [])
    if len(shares) >= 2:
        body = f"{shares[0]:.1f}%→{shares[-1]:.1f}%"
        pt = _pt_txt(shares[-1] - shares[0])
        one = f"佔比 {body}（{pt}）"
        if len(one) <= _PHONE_W:
            return [one]
        return [f"佔比 {body}", pt]
    if shares:
        return [f"佔比 {_share_txt(shares[-1])}"]
    return []


def _sibling_phone_lines(txt: str) -> List[str]:
    raw = str(txt or "").strip()
    if not raw:
        return []
    body = raw[len("同主產業 ") :] if raw.startswith("同主產業 ") else raw
    out: List[str] = []
    for item in _split_bar(body):
        if len(item) <= _PHONE_W:
            out.append(item)
            continue
        name, _, rest = item.rpartition(" ")
        if name and rest and len(name) <= _PHONE_W and len(rest) <= _PHONE_W:
            out.append(name)
            out.append(rest)
        else:
            out.extend(_pack_phone(item.split(" "), sep=" "))
    return out


def _flow_why_lines(ign: Dict[str, Any]) -> List[str]:
    nets = list(ign.get("nets") or [])
    shares = list(ign.get("shares") or [])
    if not nets and not shares:
        return ["法人佔比還沒這列", "資金進出不准猜。"]
    from industry_brief import share_flow_extra

    extra = share_flow_extra(
        flowing_in=bool(ign.get("flowing_in") or ign.get("slow_in")),
        share_last=float(ign.get("share_last") or 0),
        share_up=float(ign.get("share_up") or 0),
        last_net=int(ign.get("last") or 0),
    )
    lines: List[str] = []
    fine = str(ign.get("fine_tag") or "").strip()
    if fine:
        lines.append(fine)
    last_sh = float(ign.get("share_last") or 0)
    chg = float(ign.get("share_chg") or 0)
    if shares:
        one = f"佔當日買超 {_share_txt(last_sh)}"
        pt = _pt_txt(chg)
        if len(f"{one}（{pt}）") <= _PHONE_W:
            lines.append(f"{one}（{pt}）")
        else:
            lines.append(one)
            lines.append(pt)
        lines.append(f"近{len(shares)}日佔比")
        lines.extend(_pack_phone([f"{x:.1f}%" for x in shares]))
    if nets:
        lines.append(f"近{len(nets)}日法人")
        lines.extend(_lots_txt(n) for n in nets)
        lines.append(f"累計 {_lots_txt(int(ign.get('cum5') or 0))}")
    pos_n = int(ign.get("pos_member") or 0)
    mem_n = int(ign.get("member_n") or 0)
    if mem_n:
        lines.append(f"買超 {pos_n}/{mem_n} 檔")
    lines.append(extra)
    return lines


def _flow_why(ign: Dict[str, Any]) -> str:
    out: List[str] = []
    for ln in _flow_why_lines(ign):
        s = str(ln).rstrip("。")
        out.append(s + "。")
    return "".join(out)


def _flow_rank(ign: Dict[str, Any]) -> Tuple[float, float, int]:
    """先機＝佔比升最多；同分取還比較小的佔比。不拿張數壓過。"""
    return (
        float(ign.get("share_up") or 0.0),
        -float(ign.get("share_last") or 0.0),
        int(ign.get("cum5") or 0),
    )


def _is_money_hot(ign: Dict[str, Any], all_igns: Sequence[Dict[str, Any]]) -> bool:
    """當下資金主戰場＝佔比最高的那族。用數字，不靠他有沒有點名。"""
    last = float(ign.get("share_last") or 0)
    if last <= 0:
        return False
    mx = max((float(x.get("share_last") or 0) for x in all_igns), default=0.0)
    return last + 1e-9 >= mx


def _share_falling(ign: Dict[str, Any]) -> bool:
    return float(ign.get("share_chg") or 0) < -1e-9


def _share_rotating_out(ign: Dict[str, Any]) -> bool:
    """人去樓空：昨天第一名今天在退，或佔比單日掉超過 1pt。小數點稀釋不當流出。"""
    if ign.get("leaving"):
        return True
    return float(ign.get("share_chg") or 0) <= -1.0


def _is_parking_chain(ign: Dict[str, Any]) -> bool:
    """金控／銀行常當法人停車格。回測略過後先機勝率 71.4%→80.0%，套 4.3%→1.3%。"""
    blob = " ".join(
        [
            str(ign.get("fine_tag") or ""),
            str(ign.get("_field") or ""),
            "-".join(str(x) for x in (ign.get("_layers") or ())),
            str(ign.get("chain") or ""),
        ]
    )
    return any(n in blob for n in PARKING_NEEDLES)


def _is_elec_pick(ign: Dict[str, Any]) -> bool:
    """電子細項這型近100 勝83.0% 套0 n=47，贏全部非金控 80%。傳產航運塑化建築當先機沒贏。"""
    chain = "-".join(str(x) for x in (ign.get("_layers") or ()) if str(x))
    if chain.startswith("電子"):
        return True
    blob = str(ign.get("fine_tag") or ign.get("_field") or ign.get("chain") or "")
    return blob.startswith("電子")


_TAUGHT_FINE = (
    "IP/ASIC",
    "散熱零組件",
    "記憶體製造",
    "記憶體IC設計",
    "記憶體銷售",
    "ABF",
    "被動元件",
    "封測",
    "PCB",
    "半導體元件",
    "LED照明及光元件",
    "光學鏡片",
    "LCD",
    "太陽能",
)


def _is_taught_elec(ign: Dict[str, Any]) -> bool:
    """教過電子次族群先機近100 勝82.6% n=69。不含航運／塑化／建築／電信。"""
    chain = "-".join(str(x) for x in (ign.get("_layers") or ()) if str(x))
    blob = f"{chain} {ign.get('fine_tag') or ''} {ign.get('_field') or ''}"
    return any(n in blob for n in _TAUGHT_FINE)


def _precursor_sign(
    ign: Dict[str, Any], *, has_rival: bool, prefer_not_lead: bool = PREFER_NOT_LEAD
) -> str:
    """pre＝佔比升還沒當第一；chase＝已是當天第一；leaving＝人去樓空。"""
    if ign.get("leaving"):
        return "leaving"
    if prefer_not_lead and ign.get("is_lead_today") and has_rival:
        return "chase"
    return "pre"


def _inflow_board(all_igns: Sequence[Dict[str, Any]], n: int = 8) -> str:
    """近窗每天流入第一名的天數。不是只有此刻那一族。"""
    rows: List[Tuple[int, str]] = []
    seen = set()
    for ign in all_igns:
        days = int(ign.get("in_lead_n") or 0)
        if days <= 0:
            continue
        name = str(ign.get("_field") or ign.get("fine_tag") or ign.get("chain") or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        rows.append((days, name))
    rows.sort(key=lambda x: -x[0])
    bits = [f"{name} {days}天" for days, name in rows[:n]]
    return "｜".join(bits)


def _hot_ref_lines(hot: Dict[str, Any], spoken_named: Sequence[str]) -> List[str]:
    if not hot.get("field"):
        named = "、".join(spoken_named)
        return [f"飆大點名 {named} 只參考。"] if named else []
    lines = [
        f"佔比最高的 {hot['field']} 佔當日買超 {_share_txt(float(hot.get('share_last') or 0))}"
        f"（近5日 {_pt_txt(float(hot.get('share_up') or 0))}）",
        "當下資金主戰場。",
    ]
    named = [n for n in spoken_named if n and n != hot.get("field")]
    if hot.get("field") in spoken_named or named:
        lines.append("飆大點名 " + "、".join([hot["field"]] + named) + " 只參考，不是唯一。")
    else:
        lines.append("飆大只參考，不是唯一。")
    return lines


def _hot_ref_line(hot: Dict[str, Any], spoken_named: Sequence[str]) -> str:
    out: List[str] = []
    for ln in _hot_ref_lines(hot, spoken_named):
        s = str(ln).rstrip("。")
        out.append(s + "。")
    return "".join(out)


def _five_lines(pick: Dict[str, Any], ign: Dict[str, Any], named_hot: Dict[str, Any]) -> List[str]:
    """官方柱＋佔比為主；飆大五件當參考骨架，不准數 5／9。"""
    lead = pick.get("leader") or {}
    lag = pick.get("laggard") or {}
    fine = str(ign.get("fine_tag") or pick.get("field") or "").strip()
    bits = ["波浪不數在個股，這族還在底部這層。"]
    if lead:
        bits.append(
            "形態／碎形：龍頭 "
            + str(lead.get("name") or lead.get("sid") or "")
            + (" 還沒先過前高。" if not lead.get("broke") else " 已先過前高。")
        )
    else:
        bits.append("形態／碎形：次族群第一名還沒先過前高，才從底部找落後。")
    if lag and lag.get("vs20") is not None:
        try:
            vs = float(lag["vs20"])
            vol = lag.get("volr")
            vol_s = f"、量比 {float(vol):.2f}" if vol is not None else ""
            near = "贴近20高" if vs >= -5.0 else f"距20高 {_pct(vs)}"
            bits.append(f"量價：捕捉次級{near}{vol_s}。")
        except (TypeError, ValueError):
            bits.append("量價：從底部找最落後次級，不是單檔買訊。")
    path = _share_path(ign)
    if path:
        bits.append(f"主判是佔比：{fine}佔法人買超 {path}。")
    hot = named_hot or {}
    if hot.get("field"):
        bits.append(
            f"佔比最高 {hot['field']} {_share_txt(float(hot.get('share_last') or 0))} 當下資金主戰場，只參考點名。"
        )
    bits.append("關鍵K只用官方收。")
    return bits


def _five_line(pick: Dict[str, Any], ign: Dict[str, Any], named_hot: Dict[str, Any]) -> str:
    return "對五件（參考）：" + "".join(_five_lines(pick, ign, named_hot))


def _bucket_by_id(db_path: str, bucket: str) -> Dict[str, Dict[str, Any]]:
    if not db_path:
        return {}
    try:
        from screen_sessions import load_bucket_rows
        from universe import is_screen_equity
    except Exception:
        return {}
    out: Dict[str, Dict[str, Any]] = {}
    try:
        rows = load_bucket_rows(db_path, bucket) or []
    except Exception:
        return {}
    for raw in rows:
        sid = str(raw.get("stock_id") or raw.get("code") or "").strip()
        name = str(raw.get("stock_name") or raw.get("name") or "")
        if not sid:
            continue
        try:
            if not is_screen_equity(sid, name):
                continue
        except Exception:
            pass
        out[sid] = dict(raw)
    return out


def _score_member(
    st: Optional[Dict[str, Any]], row: Optional[Dict[str, Any]], role: str = ""
) -> Tuple:
    """越高越值得：先這檔佔族流入，再次級落後檔，再蠢蠢欲動的量價，只在黃金買點列上排。"""
    del row
    st = st or {}
    try:
        volr = float(st.get("volr") or 0.0)
    except (TypeError, ValueError):
        volr = 0.0
    try:
        vs20 = float(st["vs20"]) if st.get("vs20") is not None else -999.0
    except (TypeError, ValueError):
        vs20 = -999.0
    stir = 1.0 if _stirring(st) else 0.0
    try:
        gshare = float(st.get("group_share") or 0.0)
    except (TypeError, ValueError):
        gshare = 0.0
    try:
        cum = int(st.get("cum5") or 0)
    except (TypeError, ValueError):
        cum = 0
    lag = 1.0 if str(role or st.get("role") or "") == "次級" else 0.0
    return (1.0 if gshare > 0 or cum > 0 else 0.0, gshare, float(cum), stir, lag, volr, vs20)


def _decorate(
    db_path: str,
    sid: str,
    name: str,
    cap: str,
    row: Optional[Dict[str, Any]],
    *,
    group_last: int = 0,
) -> Dict[str, Any]:
    st = _stats(_bars(db_path, sid, cap)) or {}
    shown = name or str((row or {}).get("stock_name") or "")
    if not shown or shown == sid:
        shown = _stock_name(db_path, sid, shown)
    last_net = member_last_net(db_path, sid, cap)
    item = {
        "sid": sid,
        "name": shown or sid,
        "close": st.get("close"),
        "vs20": st.get("vs20"),
        "vs60": st.get("vs60"),
        "volr": st.get("volr"),
        "date": st.get("date") or cap,
        "stirring": bool(st) and _stirring(st),
        "broke": bool(st.get("broke")),
        "chase_warning": bool((row or {}).get("chase_warning")),
        "cum5": member_cum5(db_path, sid, cap),
        "last_net": last_net,
        "group_share": (100.0 * last_net / group_last) if group_last > 0 else 0.0,
        "fine": _fine_chain(db_path, sid),
        "face": "",
    }
    try:
        from industry_fine import membership_face

        item["face"] = membership_face(sid, chain=str(item.get("fine") or ""))
    except Exception:
        item["face"] = str(item.get("fine") or "")
    if row:
        item["pick_close"] = row.get("pick_close") or row.get("close")
        item["entry_price"] = row.get("entry_price")
    return item


def dongzhu_picks(db_path: str, *, spoken: Optional[str] = None, record_flow: bool = True) -> Dict[str, Any]:
    """洞燭先機鈕：佔比如實主判，飆大找法只參考、不是唯一。推薦＝這型最落後次級兩到三檔；剛好剛離零才標黃金買點。"""
    if spoken is None:
        spoken = latest_spoken(db_path) if db_path else ""
    spoken = str(spoken or "")
    pick = pick_unnamed_field(db_path, spoken=spoken)
    cap = str(pick.get("cap") or _cap(db_path) or "")
    chip_cap = _chip_cap(db_path, cap) if db_path else cap
    if db_path and cap and record_flow:
        try:
            record_dongzhu_flow(db_path, cap)
        except Exception:
            pass
    named_keys = _named_keys(spoken)
    spoken_named = [g["field"] for g in _GROUPS if g["key"] in named_keys]
    flow_hit = None
    all_igns: List[Dict[str, Any]] = []
    named_hot: Dict[str, Any] = {
        "field": "",
        "cum5": 0,
        "share_last": 0.0,
        "share_up": 0.0,
        "share_chg": 0.0,
        "fine_tag": "",
    }
    cands: List[Dict[str, Any]] = []
    flow_cap = chip_cap or cap

    def _note_hot(field: str, ign: Dict[str, Any]) -> None:
        nonlocal named_hot
        if float(ign.get("share_last") or 0) > float(named_hot.get("share_last") or 0):
            named_hot = {
                "field": field,
                "cum5": int(ign.get("cum5") or 0),
                "share_last": float(ign.get("share_last") or 0),
                "share_up": float(ign.get("share_up") or 0),
                "share_chg": float(ign.get("share_chg") or 0),
                "fine_tag": str(ign.get("fine_tag") or ""),
            }

    def _lead_st(g: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        for sid, name in list(g.get("leaders") or ())[:1]:
            st = _stats(_bars(db_path, sid, cap)) if db_path else None
            if st:
                return {"sid": sid, "name": name, **st}
        return None

    def _has_share(ign: Dict[str, Any]) -> bool:
        return bool(
            ign.get("flowing_in")
            or ign.get("slow_in")
            or float(ign.get("share_last") or 0) > 0
            or float(ign.get("share_up") or 0) > 0
        )

    fine = fine_share_table(db_path, flow_cap) if db_path and flow_cap else {}
    if fine:
        for chain, raw in fine.items():
            parts = list(raw.get("layers") or _split_chain_text(chain))
            g = _group_from_chain(db_path, chain, raw.get("sids") or [], cap)
            ign = dict(raw)
            ign["_field"] = g["field"]
            ign["_key"] = g["key"]
            ign["_layers"] = parts
            all_igns.append(ign)
            _note_hot(g["field"], ign)
            if not _has_share(ign):
                continue
            cands.append(
                {
                    "group": g,
                    "ign": ign,
                    "leader": None,
                    "named": _chain_is_named(spoken, parts, named_keys),
                }
            )
        seen_keys = {str(ign.get("_key") or "") for ign in all_igns}
        for g in _flow_groups():
            if g["key"] in seen_keys:
                continue
            ign = group_ignite(db_path, g["key"], flow_cap) if db_path and flow_cap else {}
            ign = dict(ign or {})
            ign["_field"] = g["field"]
            ign["_key"] = g["key"]
            ign["_layers"] = list(g.get("layers") or ())
            all_igns.append(ign)
            _note_hot(g["field"], ign)
    else:
        for g in _flow_groups():
            ign = group_ignite(db_path, g["key"], flow_cap) if db_path and flow_cap else {}
            ign = dict(ign or {})
            ign["_field"] = g["field"]
            ign["_key"] = g["key"]
            ign["_layers"] = list(g.get("layers") or ())
            all_igns.append(ign)
            _note_hot(g["field"], ign)
            if not _has_share(ign):
                continue
            cands.append(
                {
                    "group": g,
                    "ign": ign,
                    "leader": _lead_st(g),
                    "named": g["key"] in named_keys,
                }
            )
    unnamed_pos = [
        c
        for c in cands
        if not c["named"] and float(c["ign"].get("share_last") or 0) > 0
    ]
    ranked: List[Dict[str, Any]] = []
    pre_sign = ""
    has_rival = False
    flags = live_dongzhu_flags(db_path)
    prefer_not = flags["prefer_rising_not_lead"]
    skip_leave = flags["skip_leaving_hot"]
    skip_park = flags["skip_parking"]
    prefer_elec = flags.get("prefer_elec", PREFER_ELEC)
    prefer_taught = flags.get("prefer_taught", PREFER_TAUGHT)
    if unnamed_pos:
        by_share = sorted(
            unnamed_pos,
            key=lambda c: float(c["ign"].get("share_last") or 0.0),
            reverse=True,
        )
        has_rival = len(by_share) >= 2
        not_lead = by_share[1:8] if prefer_not else []
        seen: set = set()
        picked = None

        def _consider(cands: Sequence[Dict[str, Any]], *, allow_leave: bool) -> None:
            nonlocal picked
            for cand in cands:
                if picked is not None:
                    return
                cid = id(cand)
                if cid in seen:
                    continue
                seen.add(cid)
                ign = cand["ign"]
                if not allow_leave and skip_leave and _share_rotating_out(ign):
                    continue
                if not allow_leave and skip_park and _is_parking_chain(ign):
                    continue
                if not allow_leave and prefer_elec and not _is_elec_pick(ign):
                    continue
                g0 = _fill_leaders(db_path, cand["group"], cap)
                cand["group"] = g0
                ok, best_vs20 = _chain_pre_ok(db_path, g0, cap)
                cand["pre_ok"] = ok
                cand["pre_vs20"] = best_vs20
                if ok:
                    picked = cand

        if prefer_taught:
            _consider(
                [c for c in not_lead if _is_taught_elec(c["ign"])],
                allow_leave=False,
            )
            _consider(
                [c for c in not_lead if not _is_taught_elec(c["ign"])],
                allow_leave=False,
            )
        else:
            _consider(not_lead, allow_leave=False)
        if picked is None:
            _consider(by_share[:1], allow_leave=False)
        if picked is None:
            _consider(by_share, allow_leave=True)
        flow_hit = picked or by_share[0]
        if picked is None:
            g0 = _fill_leaders(db_path, flow_hit["group"], cap)
            flow_hit["group"] = g0
            ok, best_vs20 = _chain_pre_ok(db_path, g0, cap)
            flow_hit["pre_ok"] = ok
            flow_hit["pre_vs20"] = best_vs20
            flow_hit["pre_late"] = True
        else:
            flow_hit["pre_late"] = False
        pre_sign = _precursor_sign(
            flow_hit["ign"], has_rival=has_rival, prefer_not_lead=prefer_not
        )
        flow_hit["pre_sign"] = pre_sign
        skipped_park = skip_park and any(
            _is_parking_chain(c["ign"]) for c in not_lead
        )
        skipped_trad = prefer_elec and any(
            not _is_elec_pick(c["ign"]) for c in not_lead
        )
        flow_hit["skipped_park"] = skipped_park
        flow_hit["skipped_trad"] = skipped_trad
        ranked = [flow_hit] + [c for c in by_share if c is not flow_hit]
    else:
        fresh = [c for c in cands if not _is_money_hot(c["ign"], all_igns)]
        pool = fresh if fresh else cands
        for cand in pool:
            if skip_park and _is_parking_chain(cand["ign"]):
                continue
            if prefer_elec and not _is_elec_pick(cand["ign"]):
                continue
            if flow_hit is None or _flow_rank(cand["ign"]) > _flow_rank(flow_hit["ign"]):
                flow_hit = cand
        if flow_hit:
            ranked = [flow_hit]
    k_ign = group_ignite(db_path, pick.get("key") or "", flow_cap) if pick.get("key") else {}
    if flow_hit:
        g = _fill_leaders(db_path, flow_hit["group"], cap)
        flow_hit["group"] = g
        if not flow_hit.get("leader"):
            flow_hit["leader"] = _lead_st(g)
        ign = flow_hit["ign"]
        path = _share_path(ign)
        rot = ""
        if float(named_hot.get("share_up") or 0) < 0 and float(ign.get("share_up") or 0) > 0:
            rot = f"佔比最高的 {named_hot['field']} 在退、這族在升＝輪動。"
        miss = "他沒點名這族。" if not flow_hit.get("named") else ""
        spoken_named = spoken_named or list(pick.get("named") or [])
        pick = {
            **pick,
            "field": g["field"],
            "key": g["key"],
            "group": g,
            "leader": flow_hit.get("leader") or pick.get("leader"),
            "why": (
                f"主判佔比；{ign.get('fine_tag') or g['field']}"
                + (f" 佔當日法人買超 {path}，資金流入。" if path else " 資金流入。")
                + rot
                + miss
                + ("金控／銀行當停車格，不拿來當先機。" if flow_hit.get("skipped_park") else "")
                + ("航運／塑化／建築當先機沒贏過電子細項，不拿來當先機。" if flow_hit.get("skipped_trad") else "")
                + (
                    "昨天流入第一名今天佔比在退＝人去樓空，不推買。"
                    if pre_sign == "leaving" or ign.get("leaving")
                    else (
                        "這族已是當天流入第一名；回測追第一名勝率較差，不推新買。"
                        if pre_sign == "chase"
                        else (
                            f"次級距20高 {float(flow_hit.get('pre_vs20') or 0):+.1f}%≤{PRE_VS20:.0f}%（佔比升還沒當第一＝先機）。"
                            if flow_hit.get("pre_ok")
                            else "次級已靠近20高＝偏晚，只參考佔比。"
                        )
                    )
                )
                + "不靠他有沒有說蠢蠢欲動。飆大點名只參考，不是唯一。"
            ),
            "named": spoken_named,
        }
        k_ign = ign
    pick["named"] = spoken_named or list(pick.get("named") or [])
    pick["flow"] = k_ign if pick.get("key") else (flow_hit["ign"] if flow_hit else {})
    pick["flow_named_hot"] = named_hot
    pick["hot_ref"] = _hot_ref_line(named_hot, pick.get("named") or [])
    pick["five"] = _five_line(pick, pick.get("flow") or {}, named_hot)
    pick["chip_cap"] = chip_cap
    pick["flow_window"] = FLOW_LOOKBACK
    pick["pre_ok"] = bool(flow_hit.get("pre_ok")) if flow_hit else False
    pick["pre_vs20"] = float(flow_hit.get("pre_vs20") or 0) if flow_hit else 0.0
    pick["pre_late"] = bool(flow_hit.get("pre_late")) if flow_hit else False
    pick["in_lead_n"] = int((flow_hit["ign"] if flow_hit else {}).get("in_lead_n") or 0)
    pick["share_pos_n"] = int((flow_hit["ign"] if flow_hit else {}).get("share_pos_n") or 0)
    pick["inflow_board"] = _inflow_board(all_igns)
    pick["pre_sign"] = pre_sign or str((flow_hit or {}).get("pre_sign") or "")
    pick["leaving"] = bool((flow_hit["ign"] if flow_hit else {}).get("leaving"))
    members = group_members(db_path, pick.get("group"))
    buys_map = _bucket_by_id(db_path, "leave_zero")
    watch_map = _bucket_by_id(db_path, "golden_buy")
    group_last = int((pick.get("flow") or {}).get("last") or 0)
    group = pick.get("group")
    layers = _group_layers(db_path, group)
    buys: List[Dict[str, Any]] = []
    watches: List[Dict[str, Any]] = []
    for sid, name in members:
        if sid in buys_map:
            item = _decorate(db_path, sid, name, cap, buys_map[sid], group_last=group_last)
        elif sid in watch_map:
            item = _decorate(
                db_path, sid, name, cap, watch_map[sid], group_last=group_last
            )
            if item.get("close") is None:
                continue
        else:
            continue
        item["role"] = _stock_role(group, sid)
        item["layers"] = _chain_parts(db_path, sid) or layers
        if sid in buys_map:
            buys.append(item)
        else:
            watches.append(item)
    if pick.get("leaving") or pick.get("pre_late") or pick.get("pre_sign") in ("leaving", "chase"):
        buys = []
    if pick.get("pre_sign") == "pre":
        buys.sort(
            key=lambda x: (
                0 if str(x.get("role") or "") == "次級" else 1,
                float(x["vs20"]) if x.get("vs20") is not None else 0.0,
            )
        )
    else:
        buys.sort(key=lambda x: _score_member(x, None, str(x.get("role") or "")), reverse=True)
    watches.sort(key=lambda x: _score_member(x, None, str(x.get("role") or "")), reverse=True)
    pick["layers"] = layers
    pick["layer_txt"] = _layer_line(layers)
    pick["sibling_txt"] = _sibling_txt(group, all_igns, db_path)
    pick["parity"] = _parity_txt(group, buys, pick.get("leader") if isinstance(pick.get("leader"), dict) else None)
    laggard = pick.get("laggard")
    if isinstance(laggard, dict) and laggard.get("sid"):
        lag_item = _decorate(
            db_path,
            str(laggard.get("sid")),
            str(laggard.get("name") or ""),
            cap,
            None,
            group_last=group_last,
        )
        lag_item.update({k: laggard[k] for k in ("vs20", "vs60", "volr", "close", "broke") if k in laggard})
        lag_item["role"] = _stock_role(group, str(laggard.get("sid") or ""))
        lag_item["layers"] = _chain_parts(db_path, str(laggard.get("sid") or "")) or layers
        pick["laggards_note"] = lag_item
    capture = _chain_laggards(
        db_path, group, cap, n=LAG_CAPTURE_N, group_last=group_last
    )
    alts: List[Dict[str, Any]] = []
    alt_lags: List[Dict[str, Any]] = []
    primary_key = str((pick.get("group") or {}).get("key") or "")
    for cand in ranked[1:3]:
        ag = _fill_leaders(db_path, cand["group"], cap)
        aign = cand["ign"]
        alts.append(
            {
                "field": ag.get("field") or "",
                "key": ag.get("key") or "",
                "share_last": float(aign.get("share_last") or 0),
                "share_up": float(aign.get("share_up") or 0),
                "fine_tag": str(aign.get("fine_tag") or ""),
            }
        )
        if str(ag.get("key") or "") == primary_key:
            continue
        rows = _chain_laggards(
            db_path,
            ag,
            cap,
            n=LAG_CAPTURE_N,
            group_last=int(aign.get("last") or 0),
        )
        if rows:
            alt_lags.append({"field": ag.get("field") or "", "items": rows})
    pick["laggards"] = capture
    if capture:
        pick["laggard"] = capture[0]
        pick["laggards_note"] = capture[0]
        pick["five"] = _five_line(pick, pick.get("flow") or {}, named_hot)
    recs: List[Dict[str, Any]] = []
    if (
        str(pick.get("pre_sign") or "") == "pre"
        and not pick.get("leaving")
        and not pick.get("pre_late")
    ):
        recs = list(capture)
    pick["recs"] = recs
    pick["alts"] = alts
    pick["alt_laggards"] = alt_lags
    return {
        **pick,
        "members": members,
        "buys": buys[:5],
        "watches": watches[:5],
        "laggards": pick.get("laggards") or [],
        "laggards_note": pick.get("laggards_note") or laggard,
        "recs": recs,
        "alts": alts,
        "alt_laggards": alt_lags,
    }


def _esc(val: Any) -> str:
    return (
        str(val if val is not None else "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _stock_action_lines(item: Dict[str, Any], tag: str, *, held: bool = False) -> List[str]:
    """每檔先寫動作：可買／不買／已持有怎麼做。不是猜。"""
    is_buy = str(tag or "").startswith("買點")
    vs20 = item.get("vs20")
    late = False
    try:
        late = vs20 is not None and float(vs20) >= -5.0
    except (TypeError, ValueError):
        late = False
    lines: List[str] = []
    if held:
        lines.append("已持有")
        if is_buy:
            lines.append("可留")
            lines.append("可加碼")
        elif late:
            lines.append("偏晚")
            lines.append("不加碼")
        else:
            lines.append("可留觀察")
            lines.append("不加碼")
        return lines
    if is_buy:
        return ["可買", "點左邊選"]
    if str(tag or "").startswith("先機"):
        return ["可看", "點左邊選", "不是買訊"]
    return ["不買", "只觀察"]


def _stock_line(
    item: Dict[str, Any],
    idx: int,
    tag: str,
    *,
    compact: bool = True,
    held: bool = False,
) -> str:
    del compact
    sid = _esc(item.get("sid"))
    name = _esc(item.get("name"))
    vs20 = item.get("vs20")
    vs60 = item.get("vs60")
    role = str(item.get("role") or "").strip()
    face = str(item.get("face") or "").strip()
    if role == "龍頭":
        rows = [f"{idx}. <b>龍頭</b> {sid} {name}"]
    else:
        rows = [f"{idx}. {sid} {name}"]
    if face:
        rows.append(_esc(face))
    rows.extend(_esc(x) for x in _stock_action_lines(item, tag, held=held))
    if str(tag or "").startswith("買點"):
        rows.append(f"<b>{_esc(PRE_BUY_WIN_LABEL)}</b>")
    if role and role != "龍頭":
        rows.append(_esc(role))
    if vs20 is not None:
        rows.append(f"距20高 {_pct(float(vs20))}")
    if vs60 is not None:
        rows.append(f"距60高 {_pct(float(vs60))}")
    return "\n".join(rows)


def _rec_why(pick: Dict[str, Any], item: Dict[str, Any]) -> str:
    field = str(pick.get("field") or item.get("fine") or "這產業鏈")
    role = str(item.get("role") or "次級")
    vs20 = item.get("vs20")
    vs_s = f"、距20高 {_pct(float(vs20))}" if vs20 is not None else ""
    return (
        f"{field}佔比升還沒當第一（回測這型後10日漲停或≥8% {PRE_BUY_WIN_LABEL}）。"
        f"{role}{vs_s}。這檔是黃金買點，點左邊選。"
    )


def _phone_note_lines(text: str) -> List[str]:
    from tg_layout import wrap_cjk_lines

    out: List[str] = []
    for sent in _break_sentences(_esc(text)):
        out.extend(wrap_cjk_lines(sent, 18, unit="chars") or [sent])
    return out


def rotation_screen_block(db_path: str, *, spoken: Optional[str] = None) -> str:
    """海選大盤狀況末段：台股產業鏈資金輪動＋注意事項。沒庫就空。"""
    from tg_layout import join_dashed, pack_phone_bits, wrap_cjk_lines

    if not db_path:
        return ""
    try:
        data = dongzhu_picks(db_path, spoken=spoken)
    except Exception:
        return ""
    now_rows = ["＝＝台股資金輪動＝＝"]
    field = str(data.get("field") or "").strip()
    sign = str(data.get("pre_sign") or "")
    if field:
        tag = {
            "pre": "先機（佔比升還沒當第一）",
            "chase": "已是當天第一名＝追了勝率較差",
            "leaving": "人去樓空",
        }.get(sign, "")
        now_rows.extend(
            pack_phone_bits(_esc(f"此刻 {field}"), _esc(tag) if tag else "")
        )
        if data.get("pre_ok") and data.get("pre_vs20") is not None:
            now_rows.append(
                _esc(
                    f"次級距20高 {float(data.get('pre_vs20') or 0):+.1f}%（門檻 {PRE_VS20:.0f}%）。"
                )
            )
        buys = list(data.get("buys") or [])
        recs = list(data.get("recs") or [])
        if recs and sign == "pre":
            bits = [
                f"{x.get('sid')} {x.get('name')}".strip()
                for x in recs[:3]
                if x.get("sid")
            ]
            if bits:
                now_rows.extend(
                    _phone_note_lines("這型次級落後：" + "、".join(bits) + "。按洞燭先機可選。")
                )
            buy_bits = [
                f"{x.get('sid')} {x.get('name')}".strip()
                for x in buys[:3]
                if x.get("sid")
            ]
            if buy_bits:
                now_rows.extend(_phone_note_lines("其中黃金買點：" + "、".join(buy_bits) + "。"))
        else:
            now_rows.extend(_phone_note_lines("這型此刻沒有可捕捉的次級；下單進場仍只認剛離零。"))
    board = str(data.get("inflow_board") or "").strip()
    win_n = int(data.get("flow_window") or FLOW_LOOKBACK)
    board_rows: List[str] = []
    if board:
        board_line = _esc(f"近{win_n}日每天流入第一名：{board}")
        board_rows.extend(wrap_cjk_lines(board_line, 18, unit="chars") or [board_line])
    note_rows: List[str] = []
    for n in rotation_notice_lines(db_path):
        note_rows.extend(_phone_note_lines(n))
    blocks = [_blk(*now_rows)]
    if board_rows:
        blocks.append(_blk(*board_rows))
    if note_rows:
        blocks.append(_blk(*note_rows))
    return join_dashed(*blocks)


def _chain_key(parts: Sequence[str]) -> str:
    return "-".join(str(p) for p in parts if str(p).strip())


def _ign_for_parts(
    fine: Dict[str, Dict[str, Any]], parts: Sequence[str]
) -> Tuple[str, Optional[Dict[str, Any]]]:
    key = _chain_key(parts)
    if key and key in fine:
        return key, fine[key]
    last = str(parts[-1]) if parts else ""
    hits = []
    for k, ign in fine.items():
        layers = [str(x) for x in (ign.get("layers") or _split_chain_text(k)) if x]
        if last and layers and layers[-1] == last:
            hits.append((k, ign))
    if len(hits) == 1:
        return hits[0]
    if len(parts) >= 2:
        tail = [str(x) for x in parts[-2:]]
        hits = []
        for k, ign in fine.items():
            layers = [str(x) for x in (ign.get("layers") or _split_chain_text(k)) if x]
            if layers[-2:] == tail:
                hits.append((k, ign))
        if len(hits) == 1:
            return hits[0]
    return key, None


def dongzhu_hold(db_path: str, sid: str, *, spoken: Optional[str] = None) -> Dict[str, Any]:
    """任一檔：用它自己的主／次／產業鏈看資金還在不在，不是整層電子。"""
    del spoken
    sid = str(sid or "").strip()
    empty = {
        "sid": sid,
        "name": "",
        "face": "",
        "layers": [],
        "verdict": "還沒",
        "hold": False,
        "buy": False,
        "why": "這檔還沒產業鏈，不准猜能不能留。",
        "role": "",
        "pre_sign": "",
        "pre_ok": False,
        "leave_zero": False,
        "flow": {},
        "cap": "",
        "chip_cap": "",
    }
    if not db_path or not sid:
        return empty
    name = _stock_name(db_path, sid, sid)
    empty["name"] = name
    parts = _chain_parts(db_path, sid)
    try:
        from industry_fine import membership_face

        empty["face"] = membership_face(sid, chain=_chain_key(parts))
    except Exception:
        empty["face"] = ""
    cap = _chip_cap(db_path) or _cap(db_path)
    chip_cap = _chip_cap(db_path, cap) if cap else ""
    empty["cap"] = cap
    empty["chip_cap"] = chip_cap or cap
    if not parts:
        empty["why"] = f"{sid} {name} 還沒主產業／次產業／產業鏈，不准猜能不能留。"
        return empty
    fine = fine_share_table(db_path, chip_cap or cap) if chip_cap or cap else {}
    chain, ign = _ign_for_parts(fine, parts)
    ign = dict(ign or {})
    g = _group_from_chain(db_path, chain or _chain_key(parts), ign.get("sids") or [sid], cap)
    g = _fill_leaders(db_path, g, cap)
    role = _stock_role(g, sid)
    st = _stats(_bars_tail(db_path, sid, cap, 80)) or {}
    pre_ok, best_vs20 = _chain_pre_ok(db_path, g, cap)
    leave_zero = sid in _bucket_by_id(db_path, "leave_zero")
    sign = _precursor_sign(ign, has_rival=True) if ign else ""
    vs20 = st.get("vs20")
    vs60 = st.get("vs60")
    hold = False
    buy = False
    verdict = "還沒"
    if ign.get("leaving") or sign == "leaving" or _share_rotating_out(ign):
        verdict = "不留"
        why = "這產業鏈昨天流入第一名、今天佔比在退＝人去樓空。"
        if not (ign.get("leaving") or sign == "leaving"):
            why = "這檔產業鏈佔比單日在退，資金不像要留下。"
    elif vs20 is not None and float(vs20) >= 0:
        verdict = "偏晚"
        why = "這檔已貼近或超過20高，不是先機。"
    elif sign == "chase":
        verdict = "小心"
        why = "這產業鏈已是當天流入第一名；回測追第一名較容易接到要走的錢。"
    elif sign == "pre" and (pre_ok or (vs20 is not None and float(vs20) <= PRE_VS20)):
        hold = True
        if leave_zero:
            buy = True
            verdict = "可留"
            why = (
                "這產業鏈佔比升還沒當第一、次級距20高"
                f"{float(best_vs20 or vs20 or 0):+.1f}%≤{PRE_VS20:.0f}%，且這檔是黃金買點。"
            )
        else:
            verdict = "可留觀察"
            why = "這產業鏈資金準備留下，這檔本身不是黃金買點。"
    elif float(ign.get("share_last") or 0) > 0 and not _share_rotating_out(ign):
        verdict = "還在"
        why = "這產業鏈還有買超佔比，但不是先機徵兆。"
    elif ign:
        verdict = "沒先機"
        why = "這檔產業鏈佔比沒升或在退，不當先機。"
    else:
        why = (
            f"{sid} {name} 主產業／次產業／產業鏈是 {_layer_short(parts)}，"
            "但這產業鏈還沒進佔比表（成員太少或法人日還沒這列），不准猜能不能留。"
        )
    return {
        "sid": sid,
        "name": name,
        "face": str(empty.get("face") or ""),
        "layers": list(parts),
        "layer_txt": _layer_line(parts),
        "field": g.get("field") or (parts[-1] if parts else ""),
        "role": role,
        "verdict": verdict,
        "hold": hold,
        "buy": buy,
        "why": why,
        "pre_sign": sign,
        "pre_ok": pre_ok,
        "pre_vs20": best_vs20,
        "leave_zero": leave_zero,
        "vs20": vs20,
        "vs60": vs60,
        "volr": st.get("volr"),
        "close": st.get("close"),
        "flow": ign,
        "cap": cap,
        "chip_cap": chip_cap or cap,
        "chain": chain,
    }


def _blk(*rows: Any) -> str:
    out: List[str] = []
    for r in rows:
        if r is None:
            continue
        s = str(r).rstrip("\n")
        if not s.strip():
            continue
        out.append(s)
    return "\n".join(out)


def _break_sentences(text: str) -> List[str]:
    raw = str(text or "").strip()
    if not raw:
        return []
    parts: List[str] = []
    buf: List[str] = []
    for ch in raw:
        buf.append(ch)
        if ch in "。":
            bit = "".join(buf).strip()
            if bit:
                parts.append(bit)
            buf = []
    if buf:
        bit = "".join(buf).strip()
        if bit:
            parts.append(bit)
    return parts


def _split_bar(text: str) -> List[str]:
    return [p.strip() for p in str(text or "").split("｜") if p.strip()]


def _stock_blocks(
    items: Sequence[Dict[str, Any]],
    tag: str,
    *,
    compact: bool = True,
    held_sids: Optional[Sequence[str]] = None,
) -> str:
    held = {str(x) for x in (held_sids or ()) if str(x)}
    rows = [
        _stock_line(
            item,
            i,
            tag,
            compact=compact,
            held=str(item.get("sid") or "") in held,
        )
        for i, item in enumerate(items, start=1)
    ]
    return "\n\n".join(r for r in rows if r)


def dongzhu_hold_page(
    db_path: str, sid: str, *, spoken: Optional[str] = None, held: bool = False
) -> str:
    """打任一檔：用這檔自己的細項回答能不能留。動作寫在最前面。"""
    from tg_layout import join_dashed

    data = dongzhu_hold(db_path, sid, spoken=spoken)
    sid_s = _esc(data.get("sid") or sid)
    name = _esc(data.get("name") or "")
    cap = _esc(data.get("cap") or "")
    chip = _esc(data.get("chip_cap") or "")
    verdict = str(data.get("verdict") or "還沒")
    buy = bool(data.get("buy"))
    act_rows: List[str] = []
    if held:
        act_rows.append(_esc("已持有"))
    act_rows.append(f"<b>{_esc(verdict)}</b>")
    if buy:
        act_rows.append(_esc("可買"))
        act_rows.append(_esc("點左邊選"))
    elif held:
        act_rows.append(_esc("不買"))
        act_rows.append(_esc("不加碼"))
    else:
        act_rows.append(_esc("不買"))
        act_rows.append(_esc("只觀察"))
    head = [
        "<b>洞燭先機・能不能留</b>",
        f"{sid_s} {name}".strip(),
        *([_esc(data.get("face"))] if str(data.get("face") or "").strip() else []),
        *act_rows,
    ]
    if cap:
        head.append(f"官方收 {cap}")
        if chip and chip != cap:
            head.append(f"法人日 {chip}")
    blocks = [_blk(*head)]
    parts = list(data.get("layers") or [])
    if parts:
        blocks.append(_blk(*(_esc(x) for x in _layer_lines(parts))))
    px_rows: List[str] = []
    role = str(data.get("role") or "")
    if role:
        px_rows.append(_esc(role))
    if data.get("vs20") is not None:
        px_rows.append(_esc(f"距20高 {_pct(float(data['vs20']))}"))
    if data.get("vs60") is not None:
        px_rows.append(_esc(f"距60高 {_pct(float(data['vs60']))}"))
    if px_rows:
        blocks.append(_blk(*px_rows))
    flow = data.get("flow") or {}
    if flow.get("shares") or flow.get("nets"):
        blocks.append(
            _blk("<b>資金進出</b>", *(_esc(x) for x in _flow_why_lines(flow)))
        )
    why_lines = [_esc(x) for x in _break_sentences(str(data.get("why") or ""))]
    if why_lines:
        blocks.append(_blk(*why_lines))
    return join_dashed(*blocks)


def dongzhu_page(
    db_path: str, *, spoken: Optional[str] = None, held_sids: Optional[Sequence[str]] = None
) -> str:
    """主選單洞燭先機頁。每檔先寫買或不買；已持有寫留或不加碼。"""
    from tg_layout import join_dashed

    data = dongzhu_picks(db_path, spoken=spoken)
    held_sids = [str(x) for x in (held_sids or ()) if str(x)]
    cap = _esc(data.get("cap") or "")
    blocks: List[str] = [
        _blk("<b>洞燭先機</b>", *(_esc(x) for x in _HOW_LINES)),
        _blk(*(_esc(x) for x in _PAGE_RULES)),
    ]
    if cap:
        chip = _esc(data.get("chip_cap") or "")
        date_rows = [f"官方收 {cap}"]
        if chip and chip != cap:
            date_rows.append(f"法人日 {chip}")
        blocks.append(_blk(*date_rows))
    board = str(data.get("inflow_board") or "").strip()
    if board:
        win_n = int(data.get("flow_window") or FLOW_LOOKBACK)
        blocks.append(
            _blk(
                f"<b>近{win_n}日流入第一名</b>",
                *(_esc(x) for x in _split_bar(board)),
            )
        )
    blocks.append(_blk("<b>資金輪動要注意</b>", *(_esc(x) for x in _PAGE_NOTES)))
    field = str(data.get("field") or "")
    if not field:
        blocks.append(
            _blk(
                f"<i>{_esc(data.get('line') or '還沒對上底部蠢蠢的次族群，不准發明。不是買訊。')}</i>"
            )
        )
        return join_dashed(*blocks)
    now_rows = ["<b>此刻最像</b>", _esc(field)]
    parts = list(data.get("layers") or [])
    if parts:
        now_rows.extend(_esc(x) for x in _layer_lines(parts))
    ign = data.get("flow") or {}
    lead_n = int(data.get("in_lead_n") or 0)
    pos_n = int(data.get("share_pos_n") or 0)
    if lead_n:
        now_rows.append(_esc(f"流入第一 {lead_n}天"))
    if pos_n:
        now_rows.append(_esc(f"買超佔比 {pos_n}天"))
    now_rows.extend(_esc(x) for x in _share_path_lines(ign))
    if data.get("pre_sign") == "pre":
        now_rows.append(_esc("佔比升還沒第一＝先機"))
    elif data.get("pre_sign") == "chase":
        now_rows.append(_esc("已是當天第一名，偏晚"))
    elif data.get("pre_sign") == "leaving":
        now_rows.append(_esc("佔比在退，人去樓空"))
    cap_vs = None
    for item in list(data.get("laggards") or []):
        if item.get("vs20") is not None:
            cap_vs = float(item["vs20"])
            break
    if cap_vs is not None:
        now_rows.append(_esc(f"次級距20高 {_pct(cap_vs)}"))
    elif data.get("pre_vs20") is not None:
        now_rows.append(_esc(f"次級距20高 {_pct(float(data.get('pre_vs20') or 0))}"))
    named = [str(x) for x in (data.get("named") or []) if x]
    if field not in named:
        now_rows.append(_esc("還沒點名"))
    blocks.append(_blk(*now_rows))
    sib_lines = _sibling_phone_lines(str(data.get("sibling_txt") or ""))
    if sib_lines:
        blocks.append(_blk("<b>同主產業佔比</b>", *(_esc(x) for x in sib_lines)))
    if ign:
        blocks.append(
            _blk("<b>資金進出</b>", *(_esc(x) for x in _flow_why_lines(ign)))
        )
    rec_rows = ["<b>此刻推薦</b>"]
    buys = list(data.get("buys") or [])
    recs = list(data.get("recs") or [])
    buy_sids = {str(x.get("sid") or "") for x in buys if x.get("sid")}
    rec_sids = {str(x.get("sid") or "") for x in recs if x.get("sid")}
    if recs:
        rec_rows.append(_esc("這型最落後次級兩到三檔"))
        rec_rows.append(_esc("不是單檔保證"))
        rec_rows.append(_esc("點左邊選"))
        rec_rows.append(_esc("剛好剛離零才標買點"))
        rec_bits: List[str] = []
        for i, item in enumerate(recs, start=1):
            tag = "買點" if str(item.get("sid") or "") in buy_sids else "先機"
            rec_bits.append(
                _stock_line(
                    item,
                    i,
                    tag,
                    compact=True,
                    held=str(item.get("sid") or "") in set(held_sids),
                )
            )
        rec_rows.append("\n\n".join(rec_bits))
        extra_buys = [x for x in buys if str(x.get("sid") or "") not in rec_sids]
        if extra_buys:
            rec_rows.append(_esc("這族黃金買點（剛離零，另表）"))
            rec_rows.append(
                _stock_blocks(extra_buys, "買點", compact=True, held_sids=held_sids)
            )
    elif buys:
        rec_rows.append(_esc("這型此刻沒有可捕捉的次級"))
        rec_rows.append(_esc("這族黃金買點（剛離零，另表）"))
        rec_rows.append(_esc("下單進場仍只認剛離零"))
        rec_rows.append(_stock_blocks(buys, "買點", compact=True, held_sids=held_sids))
    else:
        rec_rows.append(_esc("這型此刻沒有可捕捉的次級"))
        rec_rows.append(_esc("近季要有賺才上捕捉"))
        rec_rows.append(_esc("下單進場仍只認剛離零"))
    blocks.append(_blk(*rec_rows))
    watches = list(data.get("watches") or [])
    watches = [x for x in watches if str(x.get("sid") or "") not in rec_sids]
    if watches:
        blocks.append(
            _blk(
                "<b>還在零・嚴重低估觀察</b>",
                _esc("60低超跌，只觀察不是買"),
                _stock_blocks(watches, "觀察", compact=True, held_sids=held_sids),
            )
        )
    shown = rec_sids | {
        str(x.get("sid") or "") for x in buys + watches if x.get("sid")
    }
    lags = [
        x
        for x in list(data.get("laggards") or [])
        if str(x.get("sid") or "") and str(x.get("sid") or "") not in shown
    ]
    if lags:
        blocks.append(
            _blk(
                "<b>捕捉・同鏈比價落後</b>",
                _esc("沒買點只觀察，不是單檔保證"),
                _stock_blocks(lags, "捕捉", compact=True, held_sids=held_sids),
            )
        )
    alts = list(data.get("alts") or [])
    alt_bits: List[str] = []
    for a in alts:
        name = str(a.get("field") or "")
        if not name:
            continue
        alt_bits.append(_esc(name))
        alt_bits.append(
            _esc(
                f"{_share_txt(float(a.get('share_last') or 0))}"
                f"（{_pt_txt(float(a.get('share_up') or 0))}）"
            )
        )
    if alt_bits:
        blocks.append(_blk("<b>次熱</b>", *alt_bits, _esc("不是買訊。")))
    blocks.append(_blk(_esc("紅箭頭不是買訊。"), _esc("飆大只參考。")))
    return join_dashed(*blocks)
