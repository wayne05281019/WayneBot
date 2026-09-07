"""作者公開「如何賣」：最高價 vs 最高溫。查股紀律標，不是買訊、不改海選。

來源：CMoney CaryBot 公開說明（形態學/高低卡編碼.md）。
- 最高價＝高低格 20高（收盤貼近 20 日收盤高）
- 最高溫＝升降溫主標「最高溫」
- 同步＝同一天兩者都有
- 不同步＝只有其中一個（聯一光 9/4 最高價但非最高溫；萬海 8/25 最高價＋降溫）
- 脫離＝今天既沒最高價也沒最高溫
- 不同步（含脫離前）→ 直接減碼
- 先前同步再脫離 → 準備減碼

只顯示在查股協助判斷／介紹圖紀律列／決策卡態度第二行／持股與 AI 模擬倉。不刪當沖、不改黃金買點桶（leave_zero）、不自動賣。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

LINGER = 3  # 脫離後還標幾根（含今天的前幾根）


def _state(hl: Any, temp_label: Any) -> str:
    hp = str(hl or "") == "20高"
    ht = str(temp_label or "") == "最高溫"
    if hp and ht:
        return "sync"
    if hp or ht:
        return "desync"
    return "off"


def classify_how_to_sell(
    hl_tags: Sequence[Any],
    temp_labels: Sequence[Any],
    *,
    linger: int = LINGER,
) -> Dict[str, Any]:
    """看最新一根，回傳減碼動作。空字串＝這檔今天不標。"""
    n = min(len(hl_tags) if hl_tags is not None else 0, len(temp_labels) if temp_labels is not None else 0)
    empty = {
        "sell_action": "",
        "sell_why": "",
        "hi_price": False,
        "hi_temp": False,
        "sell_sync": False,
    }
    if n <= 0:
        return empty
    hl0 = str(hl_tags[-1] or "")
    tl0 = str(temp_labels[-1] or "")
    hp = hl0 == "20高"
    ht = tl0 == "最高溫"
    today = _state(hl0, tl0)
    out = {
        "sell_action": "",
        "sell_why": "",
        "hi_price": hp,
        "hi_temp": ht,
        "sell_sync": today == "sync",
    }
    if today == "sync":
        out["sell_why"] = "最高價與最高溫同步"
        return out
    if today == "desync":
        why = "最高價但非最高溫" if hp else "最高溫但非最高價"
        out["sell_action"] = "直接減碼"
        out["sell_why"] = f"不同步（{why}）"
        return out
    last = ""
    start = n - 2
    stop = max(-1, n - 2 - int(linger))
    for i in range(start, stop, -1):
        st = _state(hl_tags[i], temp_labels[i])
        if st != "off":
            last = st
            break
    if last == "sync":
        out["sell_action"] = "準備減碼"
        out["sell_why"] = "先前同步再脫離"
    elif last == "desync":
        out["sell_action"] = "直接減碼"
        out["sell_why"] = "不同步再脫離"
    return out


def _chrono_table(tbl: Any):
    """決策卡 table 是新→舊；分類要依日期正序，否則會把最舊列當成今天。"""
    if tbl is None or not hasattr(tbl, "columns") or len(tbl) == 0:
        return tbl
    if "date" not in tbl.columns:
        return tbl
    try:
        return tbl.sort_values("date", kind="mergesort")
    except Exception:
        first = str(tbl.iloc[0].get("date") or "")
        last = str(tbl.iloc[-1].get("date") or "")
        if first > last:
            return tbl.iloc[::-1]
        return tbl


def attach_sell(card: Dict[str, Any], hl_tags=None, temp_labels=None) -> Dict[str, Any]:
    """寫入決策卡。hl／升降可從 table 補。"""
    if not card or card.get("error"):
        return card
    if hl_tags is None or temp_labels is None:
        src = _chrono_table(card.get("table"))
        if src is not None and hasattr(src, "columns"):
            if hl_tags is None and "高低" in src.columns:
                hl_tags = list(src["高低"])
            if temp_labels is None and "升降" in src.columns:
                temp_labels = list(src["升降"])
    flags = classify_how_to_sell(
        hl_tags if hl_tags is not None else [],
        temp_labels if temp_labels is not None else [],
    )
    card.update(flags)
    return card


def _why_short(why: str) -> str:
    why = str(why or "").strip()
    if why.startswith("不同步（") and why.endswith("）"):
        return why[len("不同步（") : -1]
    return why


# 查股看得到的句子：先講現況，再講現在怎麼做。不是術語、不是買訊。
NOTE_SYNC_LEFT = "現在高點跟熱度都退了，先別追、也先別加碼。有持股就先出一點"
NOTE_HI_PRICE = "現在價到高了、熱度沒跟上，先出一點、不要追"
NOTE_HI_TEMP = "現在很熱但價沒過前高，先出一點、不要追高"
NOTE_DESYNC_LEFT = "現在高點跟熱度都沒了，這波先當結束。有持股就先出一點"

_NOTE_BY_WHY = {
    "先前同步再脫離": NOTE_SYNC_LEFT,
    "最高價但非最高溫": NOTE_HI_PRICE,
    "最高溫但非最高價": NOTE_HI_TEMP,
    "不同步再脫離": NOTE_DESYNC_LEFT,
}


def _why_plain(why: str) -> str:
    raw = _why_short(why)
    return _NOTE_BY_WHY.get(raw, raw)


def sell_note_lines(card: Dict[str, Any]) -> List[str]:
    short = sell_note_short(card)
    if not short:
        return []
    if "不是叫你買" in short:
        return [short]
    return [f"{short}。不是叫你買。"]


def sell_note_short(card: Dict[str, Any]) -> str:
    """介紹圖／決策卡第二行：現況＋現在怎麼做。"""
    act = str(card.get("sell_action") or "").strip()
    if not act:
        return ""
    why = _why_short(card.get("sell_why") or "")
    note = _NOTE_BY_WHY.get(why)
    if note:
        return note
    if act == "準備減碼":
        return NOTE_SYNC_LEFT
    if act == "直接減碼":
        return NOTE_HI_PRICE
    return ""


def discipline_box_notes(card: Dict[str, Any], pink_note: str = "") -> List[str]:
    """介紹圖紀律盒：只留不打架的現況建議。已脫離高檔就不要再說貼在高檔。"""
    sell = sell_note_short(card)
    pink = str(pink_note or "").strip()
    why = str(card.get("sell_why") or "")
    if "再脫離" in why:
        pink = ""
    elif sell and pink.startswith("剛貼到高檔"):
        pink = ""
    return [n for n in (sell, pink) if n]


def sell_notes_for_stocks(
    stock_ids: Sequence[str],
    db_path: str,
    *,
    full: bool = False,
    as_of: Optional[str] = None,
    readings: Optional[Dict[str, Dict[str, str]]] = None,
) -> Dict[str, str]:
    """多檔一次查如何賣。值是短句或 HTML 長句；失敗的檔不出現。不自動賣。

    as_of：釘死某一完整交易日。不傳就用庫內最新完整日。
    readings：若傳入空 dict，會順便寫入 monthly_stage／monthly_stage_short。
    """
    out: Dict[str, str] = {}
    ids: List[str] = []
    seen = set()
    for raw in stock_ids or []:
        sid = str(raw or "").strip()
        if not sid or sid in seen:
            continue
        seen.add(sid)
        ids.append(sid)
    if not ids or not db_path:
        return out
    try:
        from wayne_navigator import NavigatorEngine

        engine = NavigatorEngine(db_path)
    except Exception:
        return out
    for sid in ids:
        try:
            card = engine.get_decision_card(sid, merge_live=False, as_of=as_of)
            if not card or card.get("error"):
                continue
            attach_sell(card)
            if readings is not None:
                readings[sid] = {
                    "monthly_stage": str(card.get("monthly_stage") or ""),
                    "monthly_stage_short": str(card.get("monthly_stage_short") or ""),
                }
            if full:
                lines = sell_note_lines(card)
                note = lines[0] if lines else ""
            else:
                note = sell_note_short(card)
            if note:
                out[sid] = note
        except Exception:
            continue
    return out
