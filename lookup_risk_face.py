"""查股下行／高檔回檔觀察臉。

使用者常查股、不報持股：把「該小心＋高檔／回檔帶」做進查股顯眼處。
只認：作者公開如何賣、官方隔夜／費半／台指電子夜、卡片既有獲利％與高低標。
不准發明「幾天內下跌機率 XX%」或未過閘「最多漲到 X」。
黃回測 §14b 才練浪頂耗盡→回檔／反彈帶；過閘前話筒只用已驗證規則＋事實帶。
§11 全過後必須升級本模組／持股／大盤提醒力道（huang_master_consolidate §14b）；不准學完仍弱提醒。
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("WayneBot.LookupRiskFace")


def _f(*vals: Any) -> Optional[float]:
    for v in vals:
        try:
            if v is None or v == "":
                continue
            return float(v)
        except (TypeError, ValueError):
            continue
    return None


def _env_bits(db_path: str) -> Dict[str, Any]:
    """隔夜＋夜盤官方片段。缺就空。"""
    out: Dict[str, Any] = {
        "regime": "unknown",
        "sox_pct": None,
        "alert": False,
        "night_line": "",
        "label": "",
    }
    us: Dict[str, Any] = {}
    try:
        from us_overnight import (
            classify_us_regime,
            effective_sox_pct,
            load_us_overnight,
            regime_face_label,
            should_alert_us_drop,
        )
        from taiwan_market import resolve_market_as_of

        as_of = resolve_market_as_of(db_path, None)
        us = load_us_overnight(db_path, as_of) or {}
        if us:
            regime = str(us.get("regime") or classify_us_regime(us) or "unknown")
            out["regime"] = regime
            out["sox_pct"] = effective_sox_pct(us)
            out["alert"] = bool(should_alert_us_drop(us))
            out["label"] = str(regime_face_label(us) or "")
    except Exception:
        logger.debug("查股風險臉美股略過", exc_info=True)
    try:
        from taiwan_market import format_sox_tx_te_night_oneline

        out["night_line"] = (
            format_sox_tx_te_night_oneline(db_path, us_snap=us or None) or ""
        ).strip()
    except Exception:
        logger.debug("查股風險臉夜盤一句略過", exc_info=True)
    return out


def _card_px(card: Dict[str, Any]) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    """現價／當日高／近窗參考高（有才回）。"""
    close = _f(card.get("close"), card.get("last_close"), card.get("price"))
    high = _f(card.get("high"), card.get("day_high"))
    ref_hi = _f(
        card.get("hold_prior_new_high"),
        card.get("cal60_high"),
        card.get("hi20"),
        card.get("high_20"),
    )
    return close, high, ref_hi


def high_zone_observe_bits(card: Dict[str, Any]) -> List[str]:
    """高檔／回檔觀察事實句（非預測頂價）。"""
    bits: List[str] = []
    close, day_hi, ref_hi = _card_px(card)
    gain = _f(card.get("gain_pct"), card.get("profit_pct"), card.get("profit"))
    hl = str(card.get("hl") or card.get("hl_tag") or "").strip()
    streak = card.get("k20_high_streak")
    try:
        streak_n = int(streak) if streak is not None else 0
    except (TypeError, ValueError):
        streak_n = 0

    if gain is not None:
        if gain >= 25:
            bits.append(f"相對60低已＋{gain:.1f}%（高檔浮盈區・回檔風險升高）")
        elif gain >= 15:
            bits.append(f"相對60低已＋{gain:.1f}%（進入常見給回觀察區）")
        elif gain >= 10:
            bits.append(f"相對60低＋{gain:.1f}%（開始留意高檔節奏）")

    if "20高" in hl or "K20高" in hl or streak_n >= 1:
        bit = "貼近／觸及20日高"
        if streak_n >= 1:
            bit += f"連{streak_n}日"
        bit += "＝作者如何賣觀察窗"
        bits.append(bit)

    if close is not None and ref_hi is not None and ref_hi > 0:
        dist = (ref_hi - close) / ref_hi * 100.0
        if dist <= 3.0:
            bits.append(f"距近窗高{ref_hi:.2f}剩{dist:.1f}%（靠近前高／耗盡觀察）")
        elif dist <= 8.0:
            bits.append(f"距近窗高{ref_hi:.2f}約{dist:.1f}%（回檔／續攻分歧帶）")

    if close is not None and day_hi is not None and day_hi > 0 and close < day_hi:
        give = (day_hi - close) / day_hi * 100.0
        if give >= 1.5:
            bits.append(f"今日高{day_hi:.2f}→現{close:.2f}已回{give:.1f}%（當日給回）")

    st = str(card.get("hold_prior_state") or "").strip()
    if st == "broke":
        bits.append("前波低點線已破（持有風險升高・非買訊）")
    elif st:
        bits.append(f"前波狀態{st}")

    stance = str(card.get("stance") or "").strip()
    if stance and ("別追" in stance or "漲多" in stance or "熱度" in stance):
        bits.append(stance)
    return bits


def lookup_risk_level(card: Optional[Dict[str, Any]], env: Optional[Dict[str, Any]] = None) -> str:
    """silent｜observe｜watch｜alert。"""
    card = card or {}
    env = env or {}
    act = str(card.get("sell_action") or "").strip()
    if act in ("直接減碼", "準備減碼"):
        return "alert"
    if env.get("alert") or str(env.get("regime") or "") == "risk_off":
        return "alert"
    if str(env.get("regime") or "") == "caution":
        return "watch"
    sox = _f(env.get("sox_pct"))
    if sox is not None and sox <= -1.2:
        return "watch"
    gain = _f(card.get("gain_pct"), card.get("profit_pct"), card.get("profit"))
    hl = str(card.get("hl") or card.get("hl_tag") or "")
    if gain is not None and gain >= 20:
        return "watch"
    if "20高" in hl or "K20高" in hl:
        return "watch"
    kind = str(card.get("stance_kind") or "")
    if kind == "avoid":
        return "watch"
    if high_zone_observe_bits(card):
        return "observe"
    return "silent"


def build_lookup_risk_html(
    db_path: str,
    card: Optional[Dict[str, Any]],
    *,
    code: str = "",
) -> str:
    """查股第一則顯眼提醒。silent 回空；有料才出。不是買訊、不是機率％。"""
    from tg_layout import html_escape

    if not card or card.get("error"):
        return ""
    try:
        from sell_discipline import attach_sell, sell_note_short

        if not str(card.get("sell_action") or "").strip():
            attach_sell(card)
    except Exception:
        pass

    env = _env_bits(db_path)
    level = lookup_risk_level(card, env)
    if level == "silent":
        return ""

    titles = {
        "alert": "出場／下行提醒",
        "watch": "小心＋高檔觀察",
        "observe": "高檔／回檔觀察",
    }
    title = titles.get(level, "小心提醒")
    sid = str(code or card.get("stock_id") or card.get("stock_code") or "").strip()
    head = f"<b>⚠ {html_escape(title)}</b>"
    if sid:
        head += f"　<code>{html_escape(sid)}</code>"
    head += "（非買訊・非假機率％・非發明頂價）"
    lines: List[str] = [head]

    act = str(card.get("sell_action") or "").strip()
    note = ""
    try:
        from sell_discipline import sell_note_short

        note = str(sell_note_short(card) or "").strip()
    except Exception:
        note = ""
    if act:
        lines.append(
            f"<b>出場</b>　{html_escape(act)}"
            + (f"　{html_escape(note)}" if note else "")
        )
        lines.append("依據＝作者如何賣（20高 vs 最高溫）。有浮盈先想減，不是叫你加碼。")

    regime = str(env.get("regime") or "unknown")
    if regime in ("risk_off", "caution") or env.get("alert"):
        lab = str(env.get("label") or "")
        sox = _f(env.get("sox_pct"))
        bit = lab or ("大盤逆風" if regime == "risk_off" else "隔夜偏空")
        if sox is not None:
            bit = f"{bit}　費半{sox:+.2f}%"
        lines.append(f"<b>環境</b>　{html_escape(bit)}")
        lines.append("覆巢之下：好股票也先降風險，不要只看個股故事。")

    night = str(env.get("night_line") or "").strip()
    if night:
        lines.append(html_escape(night))

    zone = high_zone_observe_bits(card)
    if zone:
        lines.append("<b>高檔／回檔帶</b>（事實觀察・待黃回測對質浪頂後才升級）")
        for z in zone[:6]:
            lines.append("・" + html_escape(z))
        lines.append(
            "目標＝練到能標「大概衝到哪容易耗盡、回檔常見帶、哪裡像止穩反彈」；"
            "現在未過閘＝不報假頂價、不報幾天跌幾％。"
        )
    else:
        lines.append("沒有「幾天跌幾％」假機率；只標已驗證出場規則＋官方環境。")

    return "\n".join(lines)


def market_risk_head_line(db_path: str, *, us_snap: Optional[Dict[str, Any]] = None) -> str:
    """大盤頁頭加強：逆風／大跌才出；平常空。"""
    try:
        from us_overnight import (
            effective_sox_pct,
            load_us_overnight,
            regime_face_label,
            should_alert_us_drop,
        )
        from taiwan_market import resolve_market_as_of

        us = us_snap if isinstance(us_snap, dict) else None
        if not us:
            as_of = resolve_market_as_of(db_path, None)
            us = load_us_overnight(db_path, as_of) or {}
        if not us or not should_alert_us_drop(us):
            return ""
        lab = regime_face_label(us) or "大盤逆風"
        sox = effective_sox_pct(us)
        bit = lab
        if sox is not None:
            bit = f"{lab}　費半{float(sox):+.2f}%"
        return f"⚠下行環境　{bit}　有持股先想減風險（非買訊）"
    except Exception:
        logger.debug("大盤風險頭略過", exc_info=True)
        return ""
