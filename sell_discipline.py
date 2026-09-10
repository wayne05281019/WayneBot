"""作者公開「如何賣」：最高價 vs 最高溫。查股紀律標，不是買訊、不改海選。

來源：CMoney CaryBot 公開說明（形態學/高低卡編碼.md）。
- 最高價＝高低格 20高（收盤貼近 20 日收盤高）
- 最高溫＝升降溫主標「最高溫」
- 同步＝同一天兩者都有
- 不同步＝只有其中一個（聯一光 9/4 最高價但非最高溫；萬海 8/25 最高價＋降溫）
- 脫離＝今天既沒最高價也沒最高溫
- 不同步（含脫離前）→ 直接減碼
- 先前同步再脫離 → 準備減碼

使用時機（同一把鑰匙＝當日高低／預警／升降＋如何賣原因）：
- 介紹圖粉紅「紀律」
- 決策卡「今日態度」標題（短）＋第二行（五十句）
- 圖說 Ai建議、持股／AI 模擬倉「紀律」
沒有減碼標（今天同步、或從來沒高檔）就不上這五十句。低檔表不上減碼句。升溫／最高溫不准寫已降、退了、都沒了。

不刪當沖、不改黃金買點桶（leave_zero）、不自動賣。
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
    """寫入決策卡。hl／升降可從 table 補。有減碼標就把今日態度標題對到五十句。"""
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
    apply_face_stance(card)
    return card


def _why_short(why: str) -> str:
    why = str(why or "").strip()
    if why.startswith("不同步（") and why.endswith("）"):
        return why[len("不同步（") : -1]
    return why


# 查股看得到的句子：先講現況，再講現在怎麼做。不是術語、不是買訊。
# 這四句是「沒有當日格子」時的退路；有表就改對當日高低／升降溫，避免升溫寫成熱度退了。
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

_WHY_CODE = {
    "先前同步再脫離": "sync_left",
    "最高價但非最高溫": "hi_price",
    "最高溫但非最高價": "hi_temp",
    "不同步再脫離": "desync_left",
}

# 對高低卡當日格子。鍵＝(位置, 升降溫, 如何賣原因)。每句現況先、動作後。
FACE_NOTES: Dict[tuple, str] = {
    ("hi20", "up", "hi_price"): "價已貼20日高、熱度在升但不是最高溫。先出一點、不要追",
    ("hi20", "down", "hi_price"): "價貼20日高、熱度在降沒跟上。先出一點、不要追",
    ("hi20", "floor", "hi_price"): "價在20日高、熱度掉到最低。先出一點、不要追",
    ("hi20", "diverge", "hi_price"): "價在20日高、價溫背離。少追、先出一點",
    ("hi20", "up", "hi_price_hot"): "價貼20日高、溫度過熱還在升。先出一點、不要追",
    ("hi10", "peak", "hi_temp"): "熱度最高，價只到10日高、還沒過20日高。先出一點、不要追高",
    ("hi10", "up", "sync_left"): "價在10日高、熱度在升，20日高還沒過。先別追。有持股先出一點",
    ("hi10", "down", "sync_left"): "價在10日高、熱度在降。先別追、先別加碼。有持股先出一點",
    ("hi10", "floor", "sync_left"): "價在10日高、熱度在最低。先看、不要追。有持股先出一點",
    ("hi10", "diverge", "sync_left"): "價在10日高、價溫背離。少追。有持股先出一點",
    ("hi10", "up", "desync_left"): "價停在10日高、熱度在升。不要追高。有持股先出一點",
    ("hi10", "down", "desync_left"): "價在10日高、熱度在降。這波先當過熱。有持股先出一點",
    ("hi10", "floor", "desync_left"): "價在10日高、熱度在最低。不要追。有持股先出一點",
    ("hi10", "diverge", "desync_left"): "價在10日高且價溫背離。少追。有持股先出一點",
    ("near_hi", "up", "sync_left"): "價靠近20日高、熱度在升。今天別追。有持股就先出一點",
    ("near_hi", "down", "sync_left"): "價靠近20日高，熱度已降。先別追、先別加碼。有持股就先出一點",
    ("near_hi", "floor", "sync_left"): "價靠近20日高，熱度在最低。先看、不要追。有持股就先出一點",
    ("near_hi", "diverge", "sync_left"): "價靠近高檔但價溫背離。少追。有持股就先出一點",
    ("near_hi", "up", "desync_left"): "高點剛離開又靠回來、熱度在升。今天別追。有持股就先出一點",
    ("near_hi", "down", "desync_left"): "價靠近20日高、熱度在降。先別追。有持股就先出一點",
    ("near_hi", "floor", "desync_left"): "價靠近20日高、熱度在最低。不要追。有持股就先出一點",
    ("near_hi", "diverge", "desync_left"): "價靠近高檔且價溫背離。少追。有持股就先出一點",
    ("near_hi", "peak", "hi_temp"): "熱度最高、價靠近但還沒貼死20日高。先出一點、不要追高",
    ("near_hi", "up", "sync_left_run"): "價靠近20日高、熱度在升、這段已經漲多。今天別追。有持股就先出一點",
    ("left_hi", "up", "sync_left"): "高點已離開，熱度又升回來。先別追、也先別加碼。有持股就先出一點",
    ("left_hi", "down", "sync_left"): NOTE_SYNC_LEFT,
    ("left_hi", "floor", "sync_left"): "高點離開、熱度掉到最低。先別追。有持股就先出一點",
    ("left_hi", "diverge", "sync_left"): "高點離開且價溫背離。少追、先別加碼。有持股就先出一點",
    ("left_hi", "up", "desync_left"): "高點已離開，熱度卻還在升。今天別追。有持股就先出一點",
    ("left_hi", "down", "desync_left"): "高點跟熱度都在退。這波先當結束。有持股就先出一點",
    ("left_hi", "floor", "desync_left"): "高點離開、熱度在最低。這波先當結束。有持股就先出一點",
    ("left_hi", "diverge", "desync_left"): "高點離開且價溫背離。少追。有持股就先出一點",
    ("left_hi", "peak", "hi_temp"): "熱度最高、價已離開20日高。先出一點、不要追高",
    ("left_hi", "up", "desync_left_run"): "高點已離開，熱度還在升、獲利已經很大。今天別追。有持股就先出一點",
    ("mid", "up", "sync_left"): "高點已離開，熱度又升。先別追、先別加碼。有持股就先出一點",
    ("mid", "down", "sync_left"): NOTE_SYNC_LEFT,
    ("mid", "floor", "sync_left"): "高點離開、熱度在最低。先別追。有持股就先出一點",
    ("mid", "diverge", "sync_left"): "高點離開且價溫背離。少追。有持股就先出一點",
    ("mid", "up", "desync_left"): "高點已離開，熱度還在升。今天別追。有持股就先出一點",
    ("mid", "down", "desync_left"): NOTE_DESYNC_LEFT,
    ("mid", "floor", "desync_left"): NOTE_DESYNC_LEFT,
    ("mid", "diverge", "desync_left"): "高點沒了且價溫背離。少追。有持股就先出一點",
    ("mid", "peak", "hi_temp"): NOTE_HI_TEMP,
    ("near_lo", "up", "sync_left"): "表靠近低檔、熱度在升。先看、先別急著追。有持股先出一點",
    ("near_lo", "down", "sync_left"): "表靠近低檔、熱度在降。先看。有持股先出一點",
    ("near_lo", "floor", "sync_left"): "表靠近低檔、熱度在最低。低點訊號也先別樂觀，獲利還沒離開0先不要動作",
    ("near_lo", "diverge", "sync_left"): "表靠近低檔且價溫背離。先看。有持股先出一點",
    ("near_lo", "up", "desync_left"): "表靠近低檔、熱度在升。不要當突破追。有持股先出一點",
    ("near_lo", "down", "desync_left"): "表靠近低檔、熱度在降。這波高檔先結束。有持股先出一點",
    ("near_lo", "floor", "desync_left"): "表靠近低檔、熱度在最低。低點訊號也先別樂觀。先看。有持股先出一點",
    ("near_lo", "diverge", "desync_left"): "表靠近低檔且價溫背離。先看。有持股先出一點",
    ("near_lo", "peak", "hi_temp"): "熱度最高、價卻在低附近。先出一點、不要追高",
    ("hi10", "down", "hi_temp"): "熱度標最高但格子在降、價只到10日高。先出一點、不要追高",
    ("near_hi", "down", "hi_temp"): "熱度標最高但格子在降、價靠近20日高。先出一點、不要追高",
    ("mid", "up", "hi_temp"): "熱度最高、價還在區間裡沒過20日高。先出一點、不要追高",
    ("left_hi", "up", "hi_temp"): "熱度最高、價已離開20日高還在升。先出一點、不要追高",
    ("near_hi", "flat", "sync_left"): "價靠近20日高、熱度沒再走。先別追。有持股就先出一點",
    ("near_hi", "flat", "desync_left"): "價靠近20日高、熱度沒再走。少追。有持股就先出一點",
    ("left_hi", "flat", "sync_left"): "高點已離開，熱度沒再走。先別追。有持股就先出一點",
    ("left_hi", "flat", "desync_left"): "高點離開、熱度沒再走。這波先當結束。有持股就先出一點",
    ("hi10", "flat", "sync_left"): "價在10日高、熱度沒再走。先別追。有持股先出一點",
    ("hi10", "flat", "desync_left"): "價停在10日高、熱度沒再走。不要追高。有持股先出一點",
    ("mid", "flat", "sync_left"): "高點已離開，熱度沒再走。先別追、先別加碼。有持股就先出一點",
    ("mid", "flat", "desync_left"): "高點沒了，熱度也沒再走。這波先當結束。有持股就先出一點",
    ("hi20", "flat", "hi_price"): "價貼20日高、熱度沒再走沒跟上。先出一點、不要追",
    ("near_lo", "flat", "sync_left"): "表靠近低檔、熱度沒再走。先看。有持股先出一點",
    ("near_lo", "flat", "desync_left"): "表靠近低檔、熱度沒再動。先看。有持股先出一點",
    # 獲利已大：同一把格子再加「這段已經漲多」，未來漲多卡才對得上。
    ("near_hi", "down", "sync_left_run"): "價靠近20日高、熱度已降、這段已經漲多。先別追、先別加碼。有持股就先出一點",
    ("near_hi", "flat", "sync_left_run"): "價靠近20日高、熱度沒再走、這段已經漲多。先別追。有持股就先出一點",
    ("near_hi", "floor", "sync_left_run"): "價靠近20日高、熱度在最低、這段已經漲多。先看、不要追。有持股就先出一點",
    ("near_hi", "diverge", "sync_left_run"): "價靠近高檔、價溫背離、這段已經漲多。少追。有持股就先出一點",
    ("near_hi", "up", "desync_left_run"): "高點剛離開又靠回來、熱度在升、這段已經漲多。今天別追。有持股就先出一點",
    ("near_hi", "down", "desync_left_run"): "價靠近20日高、熱度在降、這段已經漲多。先別追。有持股就先出一點",
    ("near_hi", "flat", "desync_left_run"): "價靠近20日高、熱度沒再走、這段已經漲多。少追。有持股就先出一點",
    ("near_hi", "floor", "desync_left_run"): "價靠近20日高、熱度在最低、這段已經漲多。不要追。有持股就先出一點",
    ("hi20", "up", "hi_price_run"): "價已貼20日高、熱度在升不是最高溫、這段已經漲多。先出一點、不要追",
    ("hi20", "down", "hi_price_run"): "價貼20日高、熱度在降沒跟上、這段已經漲多。先出一點、不要追",
    ("hi20", "flat", "hi_price_run"): "價貼20日高、熱度沒再走、這段已經漲多。先出一點、不要追",
    ("hi20", "diverge", "hi_price_run"): "價在20日高、價溫背離、這段已經漲多。少追、先出一點",
    ("hi20", "floor", "hi_price_run"): "價在20日高、熱度掉到最低、這段已經漲多。先出一點、不要追",
    ("left_hi", "up", "sync_left_run"): "高點已離開，熱度又升回來、這段已經漲多。先別追。有持股就先出一點",
    ("left_hi", "down", "sync_left_run"): "高點跟熱度都退了、這段已經漲多。先別追、也先別加碼。有持股就先出一點",
    ("left_hi", "floor", "desync_left_run"): "高點離開、熱度在最低、獲利已經很大。這波先當結束。有持股就先出一點",
    ("left_hi", "down", "desync_left_run"): "高點跟熱度都在退、獲利已經很大。這波先當結束。有持股就先出一點",
    ("hi10", "up", "sync_left_run"): "價在10日高、熱度在升、這段已經漲多。先別追。有持股先出一點",
    ("hi10", "down", "sync_left_run"): "價在10日高、熱度在降、這段已經漲多。先別追。有持股先出一點",
    ("hi10", "up", "desync_left_run"): "價停在10日高、熱度在升、這段已經漲多。不要追高。有持股先出一點",
    ("hi10", "peak", "hi_temp_run"): "熱度最高，價只到10日高、這段已經漲多。先出一點、不要追高",
    ("near_hi", "peak", "hi_temp_run"): "熱度最高、價靠近20日高、這段已經漲多。先出一點、不要追高",
    ("left_hi", "peak", "hi_temp_run"): "熱度最高、價已離開20日高、這段已經漲多。先出一點、不要追高",
    ("mid", "up", "sync_left_run"): "高點已離開，熱度又升、這段已經漲多。先別追。有持股就先出一點",
    ("mid", "down", "sync_left_run"): "高點跟熱度都退了、這段已經漲多。先別追。有持股就先出一點",
}


def _why_plain(why: str) -> str:
    raw = _why_short(why)
    return _NOTE_BY_WHY.get(raw, raw)


def latest_table_row(card: Dict[str, Any] | None) -> Dict[str, Any]:
    """當日列＝日期最新那根。決策卡表是新→舊，分類用正序，這裡兩邊都對到同一天。"""
    tbl = (card or {}).get("table")
    if tbl is None:
        return {}
    if hasattr(tbl, "iloc") and len(tbl):
        try:
            src = _chrono_table(tbl)
            return src.iloc[-1].to_dict()
        except Exception:
            try:
                return tbl.iloc[0].to_dict()
            except Exception:
                return {}
    if isinstance(tbl, (list, tuple)) and tbl:
        rows = [dict(x) for x in tbl if isinstance(x, dict)]
        if not rows:
            return {}
        dated = [r for r in rows if str(r.get("date") or "").strip()]
        if dated:
            return max(dated, key=lambda r: str(r.get("date") or ""))
        return dict(rows[0])
    return {}


def _row0(card: Dict[str, Any] | None) -> Dict[str, Any]:
    return latest_table_row(card)


def _fnum(*vals) -> float | None:
    for v in vals:
        if v in (None, ""):
            continue
        try:
            return float(v)
        except (TypeError, ValueError):
            s = str(v).replace("°C", "").replace("%", "").replace("+", "").replace(",", "").strip()
            try:
                return float(s)
            except ValueError:
                continue
    return None


def card_discipline_face(card: Dict[str, Any] | None) -> Dict[str, str]:
    """當日高低卡怎麼讀：位置／升降溫／如何賣原因。沒有格子就空。"""
    card = card or {}
    row = _row0(card)
    hl = str(row.get("高低") or card.get("hl") or "").strip()
    alert = str(row.get("預警") or card.get("alert") or "").strip()
    trend = str(row.get("升降") or "").strip()
    tnote = str(row.get("升降註") or row.get("升降注") or "").strip()
    dist_h = _fnum(card.get("dist_h20"), row.get("dist_h20"))
    gain = _fnum(card.get("gain_pct"), card.get("profit_pct"), row.get("profit_pct"))
    temp = _fnum(card.get("temp_num"), row.get("temp_num"), row.get("溫度計"), card.get("temp_c"))

    if hl == "20高":
        pos = "hi20"
    elif hl in ("10高", "5高"):
        pos = "hi10"
    elif alert == "K20高" or (dist_h is not None and dist_h >= -2.0):
        pos = "near_hi"
    elif dist_h is not None and dist_h >= -8.0:
        pos = "left_hi"
    elif alert in ("60低", "K20低") or hl in ("60低", "20低", "10低", "5低"):
        pos = "near_lo"
    else:
        pos = "mid"

    if tnote == "價溫背離":
        heat = "diverge"
    elif trend == "最高溫":
        heat = "peak"
    elif trend == "最低溫":
        heat = "floor"
    elif trend == "升溫":
        heat = "up"
    elif trend == "降溫":
        heat = "down"
    elif trend in ("No", "—"):
        heat = "flat"
    else:
        heat = ""

    why = _WHY_CODE.get(_why_short(card.get("sell_why") or ""), "")
    if why == "hi_price" and pos == "hi20" and heat == "up" and temp is not None and temp >= 80:
        why = "hi_price_hot"
    elif why and gain is not None and gain >= 20:
        run = f"{why}_run"
        if (pos, heat, run) in FACE_NOTES:
            why = run
    return {"pos": pos, "heat": heat, "why": why, "trend": trend}


_COOL_IN_NOTE = ("已降", "退了", "都沒了", "在降", "掉到最低", "熱度在最低")
_WARM_IN_NOTE = ("熱度在升", "還在升", "又升回來", "過熱還在升")

_WARM_BY_POS = {
    "hi20": "價已貼20日高、熱度在升但不是最高溫。先出一點、不要追",
    "hi10": "價在10日高、熱度在升，20日高還沒過。先別追。有持股先出一點",
    "near_hi": "價靠近20日高、熱度在升。今天別追。有持股就先出一點",
    "left_hi": "高點已離開，熱度又升回來。先別追、也先別加碼。有持股就先出一點",
    "mid": "高點已離開，熱度又升。先別追、先別加碼。有持股就先出一點",
    "near_lo": "表靠近低檔、熱度在升。先看、先別急著追。有持股先出一點",
}


def _note_fits_heat(heat: str, note: str) -> bool:
    n = str(note or "")
    if not n:
        return False
    if heat in ("up", "peak"):
        return not any(m in n for m in _COOL_IN_NOTE)
    if heat in ("down", "floor"):
        return not any(m in n for m in _WARM_IN_NOTE)
    return True


def _note_from_face(card: Dict[str, Any]) -> str:
    face = card_discipline_face(card)
    pos, heat, why = face["pos"], face["heat"], face["why"]
    if heat and why:
        note = FACE_NOTES.get((pos, heat, why))
        if note and _note_fits_heat(heat, note):
            return note
        base_why = {
            "hi_price_hot": "hi_price",
            "hi_price_run": "hi_price",
            "hi_temp_run": "hi_temp",
            "sync_left_run": "sync_left",
            "desync_left_run": "desync_left",
        }.get(why, why)
        note = FACE_NOTES.get((pos, heat, base_why))
        if note and _note_fits_heat(heat, note):
            return note
    if heat in ("up", "peak"):
        warm = _WARM_BY_POS.get(pos) or FACE_NOTES.get((pos, "up", why or "sync_left"), "")
        if warm and _note_fits_heat(heat, warm):
            return warm
    raw = _why_short(card.get("sell_why") or "")
    fallback = _NOTE_BY_WHY.get(raw, "")
    if heat in ("up", "peak") and not _note_fits_heat(heat, fallback):
        return _WARM_BY_POS.get(pos, "價在高檔附近、熱度在升。今天別追。有持股就先出一點")
    return fallback


def sell_note_lines(card: Dict[str, Any]) -> List[str]:
    short = sell_note_short(card)
    if not short:
        return []
    if "不是叫你買" in short:
        return [short]
    return [f"{short}。不是叫你買。"]


def sell_note_short(card: Dict[str, Any]) -> str:
    """介紹圖紀律／決策卡態度第二行／持股／圖說：五十句對當日格子。沒有減碼標就空白。"""
    try:
        from decision_card_signals import table_reads_as_low

        if table_reads_as_low(card):
            return ""
    except Exception:
        pass
    act = str(card.get("sell_action") or "").strip()
    if not act:
        return ""
    note = _note_from_face(card)
    if note:
        return note
    heat = card_discipline_face(card).get("heat") or ""
    why = _why_short(card.get("sell_why") or "")
    note = _NOTE_BY_WHY.get(why, "")
    if note and _note_fits_heat(heat, note):
        return note
    if heat in ("up", "peak"):
        pos = card_discipline_face(card).get("pos") or "mid"
        return _WARM_BY_POS.get(pos, "價在高檔附近、熱度在升。今天別追。有持股就先出一點")
    if act == "準備減碼":
        return NOTE_SYNC_LEFT
    if act == "直接減碼":
        return NOTE_HI_PRICE
    return ""


def stance_title_from_face(card: Dict[str, Any] | None) -> tuple[str, str]:
    """今日態度標題：跟五十句同一把（位置＋升降）。短句，給同一行排版。"""
    card = card or {}
    face = card_discipline_face(card)
    pos, heat = face.get("pos") or "mid", face.get("heat") or ""
    gain = _fnum(card.get("gain_pct"), card.get("profit_pct"), card.get("profit"))
    high = pos in ("hi20", "hi10", "near_hi", "left_hi")
    if pos == "near_lo" and heat != "peak":
        return "靠近低點，先看表", "watch"
    if heat in ("peak", "diverge"):
        return "今天別追高", "avoid"
    if high and heat == "down":
        if gain is not None and gain >= 15:
            return "漲多了，熱度已降", "avoid"
        return "熱度已降，別追", "avoid"
    if high and heat == "floor":
        return "熱度在最低，別追", "avoid"
    if high and heat == "up":
        if gain is not None and gain >= 15:
            return "漲多了，今天別追", "avoid"
        return "今天別追", "avoid"
    if high and heat == "flat":
        if gain is not None and gain >= 15:
            return "漲多了，今天別追", "avoid"
        return "今天別追", "avoid"
    if heat == "up":
        return "今天別追", "avoid"
    if heat == "down":
        if gain is not None and gain >= 15:
            return "漲多了，今天別追", "avoid"
        return "今天別追", "avoid"
    if gain is not None and gain >= 15:
        return "漲多了，今天別追", "avoid"
    return "今天別追", "avoid"


def sell_highlight_kind(card: Dict[str, Any] | None) -> str:
    """作者提醒當下要打底色。cut＝不同步／不同步再脫離；prepare＝同步再脫離。"""
    act = str((card or {}).get("sell_action") or "").strip()
    if act == "直接減碼":
        return "cut"
    if act == "準備減碼":
        return "prepare"
    return ""


def apply_face_stance(card: Dict[str, Any]) -> Dict[str, Any]:
    """有如何賣標時，今日態度標題改跟五十句同一把鑰匙。沒標／表在低檔就不動。"""
    if not card or card.get("error"):
        return card
    if not str(card.get("sell_action") or "").strip():
        return card
    try:
        from decision_card_signals import table_reads_as_low

        if table_reads_as_low(card):
            return card
    except Exception:
        pass
    title, kind = stance_title_from_face(card)
    if title:
        card["stance"] = title
        card["stance_kind"] = kind
    return card


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
