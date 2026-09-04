"""作者公開「如何賣」：最高價 vs 最高溫。查股紀律標，不是買訊、不改海選。

來源：CMoney CaryBot 公開說明（形態學/高低卡編碼.md）。
- 最高價＝高低格 20高（收盤貼近 20 日收盤高）
- 最高溫＝升降溫主標「最高溫」
- 同步＝同一天兩者都有
- 不同步＝只有其中一個（聯一光 9/4 最高價但非最高溫；萬海 8/25 最高價＋降溫）
- 脫離＝今天既沒最高價也沒最高溫
- 不同步（含脫離前）→ 直接減碼
- 先前同步再脫離 → 準備減碼

只顯示在查股協助判斷／介紹圖紀律列／決策卡態度第二行。不刪當沖、不改起漲桶。
"""
from __future__ import annotations

from typing import Any, Dict, List, Sequence

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


def sell_note_lines(card: Dict[str, Any]) -> List[str]:
    act = str(card.get("sell_action") or "").strip()
    if not act:
        return []
    why = _why_short(card.get("sell_why") or "")
    if why:
        return [f"{act}（{why}；作者如何賣，不是買訊）"]
    return [f"{act}（作者如何賣，不是買訊）"]


def sell_note_short(card: Dict[str, Any]) -> str:
    """介紹圖窄欄用：不要把「作者如何賣，不是買訊」整句塞進去。"""
    act = str(card.get("sell_action") or "").strip()
    if not act:
        return ""
    why = _why_short(card.get("sell_why") or "")
    if why:
        return f"{act}（{why}）"
    return act
