# -*- coding: utf-8 -*-
"""啾哈每日觀盤桌（非買訊）。

今日盤後：官方柱數字＋附圖，看清當日結構。
明日要注意：只列「盤中就能觀察」的檢查點；盤後才更新的欄
（融資餘額、期貨法人 OI 日結）標成對質欄，不准當明早唯一應對鈕。

不准改黃金買點／海選／洞燭選股。時區 Asia/Taipei。
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from jiuha_observe import (
    DESK_LAYERS,
    PRINCIPLES,
    TAIPEI,
    compute_daily_structure,
    load_index_bars,
)

DEFAULT_MARKET = Path("/workspace/data/wayne_market.db")
DEFAULT_OUT = Path("/opt/cursor/artifacts/jiuha")


def _fp(size: int, weight: str = "normal"):
    """Noto CJK font for phone-readable charts."""
    from wayne_navigator import _fp as nav_fp

    return nav_fp(size, weight)


def _ymd8(s: Any) -> str:
    return "".join(ch for ch in str(s or "") if ch.isdigit())[:8]


def _is_tw_open_day(ymd: str, market_db: str = "") -> bool:
    key = _ymd8(ymd)
    if len(key) != 8:
        return False
    try:
        from tw_holidays import lookup_tw_session
        return lookup_tw_session(key, market_db or None).get("kind") == "open"
    except Exception:
        try:
            return datetime.strptime(key, "%Y%m%d").weekday() < 5
        except ValueError:
            return False


def next_tw_trading_day(ymd: str, market_db: str = "") -> str:
    from datetime import timedelta
    key = _ymd8(ymd)
    try:
        dt = datetime.strptime(key, "%Y%m%d")
    except ValueError:
        return ""
    for _ in range(18):
        dt += timedelta(days=1)
        cand = dt.strftime("%Y%m%d")
        if _is_tw_open_day(cand, market_db):
            return cand
    return ""


def _slash_ymd(ymd: str, *, with_year: bool = False) -> str:
    key = _ymd8(ymd)
    if len(key) != 8:
        return str(ymd or "")
    if with_year:
        return f"{key[0:4]}/{key[4:6]}/{key[6:8]}"
    return f"{key[4:6]}/{key[6:8]}"


def _filter_open_bars(bars: List[Any], market_db: str, *, day: str = "") -> List[Any]:
    out = []
    for b in bars or []:
        d = _ymd8(getattr(b, "date", None) or (b.get("date") if isinstance(b, dict) else ""))
        if day and d > day:
            continue
        if _is_tw_open_day(d, market_db):
            out.append(b)
    return out


def _wrap_at_punct(text: str, max_chars: int = 22) -> str:
    """CJK 換行：優先在標點／箭頭切斷；不准切斷數字、％、×、英文碼中段。"""
    s = str(text or "").strip()
    if not s:
        return ""
    soft = set("；、。｜＝→←＜＞%）】」』，,/")
    lines: List[str] = []

    def _ok_break_at(buf: str, i: int) -> bool:
        """可否在 buf[i] 前切斷（即上行＝buf[:i]）。"""
        if i <= 0 or i >= len(buf):
            return False
        left, right = buf[i - 1], buf[i]
        if (left.isdigit() or left in ".×+") and (right.isdigit() or right in ".%％×"):
            return False
        if left.isascii() and left.isalnum() and right.isascii() and right.isalnum():
            return False
        return True

    while s:
        if len(s) <= max_chars:
            lines.append(s)
            break
        cut = -1
        # 1) 視窗內最後一個軟標點後切斷
        for i, ch in enumerate(s[: max_chars + 1]):
            if i == 0:
                continue
            if ch in soft and _ok_break_at(s, i):
                cut = i + 1  # 標點留上行
        # 2) 無標點：從 max_chars 往回找安全切點
        if cut <= 0:
            for i in range(min(max_chars, len(s)), max(max_chars // 2, 8), -1):
                if _ok_break_at(s, i):
                    cut = i
                    break
        if cut <= 0:
            cut = max_chars
            while cut > 8 and not _ok_break_at(s, cut):
                cut -= 1
        piece = s[:cut].rstrip("；、，, ")
        s = s[cut:].lstrip("；、，, ")
        if piece:
            lines.append(piece)
        if len(lines) >= 3:
            if s:
                lines[-1] = lines[-1].rstrip("…") + "…"
            break
    return "\n".join(lines)


def _short_when(when: str) -> str:
    """長時段縮成手機可掃：保留關鍵時刻，不准一行撐爆。"""
    w = str(when or "").strip()
    if len(w) <= 14:
        return w
    # 08:30／09:30／11:00／13:00 → 08:30・09:30・11・13
    parts = [p for p in w.replace("–", "／").replace("-", "／").split("／") if p]
    if len(parts) >= 3:
        slim = []
        for p in parts[:4]:
            p = p.strip()
            if ":" in p and p.count(":") == 1:
                hh, mm = p.split(":", 1)
                slim.append(hh if mm in ("00", "0") else f"{hh}:{mm}")
            else:
                slim.append(p[:6])
        return "・".join(slim)
    return w[:14] + "…"


def build_tomorrow_intraday_checks(pack: Dict[str, Any]) -> List[Dict[str, Any]]:
    """明日盤中可觀測檢查點（依當日結構動態加權）。

    每條必含：when（台北時段）、watch、how（怎樣算觸發）、principle、
    data_hint。禁止把純盤後欄當唯一應對。
    """
    tw = pack.get("twii") or {}
    labs = pack.get("structure_labels") or []
    chg = tw.get("chg_pct")
    vol_vs_5 = tw.get("vol_vs_5")
    checks: List[Dict[str, Any]] = []

    # 1) 開盤 15 分——他最強調的盤中門；庫缺分K仍要列成手算／即時看板
    checks.append(
        {
            "id": "T_open15_vol",
            "when": "09:00–09:15",
            "watch": "加權開盤15分成交金額（或成交量）vs 近5日同時段",
            "how": "明顯縮鎖、幾乎無換手 → 標「開盤量鎖死」（P07）；有量換手再往下看結構",
            "principle": "P07_open15_vol",
            "data_hint": "盤中即時累計／分K；日庫常缺→以看板手算，不准假填歷史",
            "intraday": True,
            "priority": 1,
        }
    )

    # 2) 午前量速——不用等收盤才知道「今天有沒有量」
    checks.append(
        {
            "id": "T_am_vol_pace",
            "when": "09:15–11:00",
            "watch": "累計量／近5日全日均量的進度（午前應大致過半才像有換手）",
            "how": "大漲但累計量嚴重落後 → 先當「縮量反彈／逃命窗假設」（P04），不是追高證成",
            "principle": "P04_volume_rebound",
            "data_hint": "盤中累計量即可；全日比要等收盤只做對質",
            "intraday": True,
            "priority": 2,
        }
    )

    # 3) 櫃買相對——盤中看漲跌幅差
    checks.append(
        {
            "id": "T_otc_rel",
            "when": "09:30–13:00",
            "watch": "櫃買漲跌％ − 加權漲跌％",
            "how": "加權弱而櫃買相對先穩 → 融資止血偏有利假設（P06）；櫃買更弱 → 壓力警訊",
            "principle": "P06_otc_first",
            "data_hint": "盤中報價即可；完整 OHLC 若庫內僅戳記，收盤對質另標缺",
            "intraday": True,
            "priority": 3,
        }
    )

    # 4) 台幣——盤中可看
    checks.append(
        {
            "id": "T_fx_lead",
            "when": "終日（台北早盤優先）",
            "watch": "美金台幣即時／早盤方向",
            "how": "台幣升值（USDTWD 跌）＋指數反彈 → 資金面偏暖訊號之一（P05）；台幣貶而指數漲 → 加權可能騙人",
            "principle": "P05_fx_lead",
            "data_hint": "銀行／報價盤中可得；日結欄落後只標 stale，不擋盤中看",
            "intraday": True,
            "priority": 4,
        }
    )

    # 5) 關鍵位刺穿——只在已有「假突破」標籤時列；不准用昨收冒充前高／頸線
    if any("假突破" in (x or "") for x in labs):
        checks.append(
            {
                "id": "T_level_probe",
                "when": "試高／試低當下",
                "watch": "是否刺穿近頸線／前高，以及刺穿後是否立刻被打回",
                "how": "小突破＋爆量無力 → 假突破／獵殺結構假設（P03）；盤中回落即可先定性，收盤站上才是盤尾確認",
                "principle": "P03_false_break",
                "data_hint": "盤中高低＋量；有點名價才對該價，不准發明新價",
                "intraday": True,
                "priority": 2,
            }
        )

    # 6) 縮量大漲翌日——特別盯開盤有沒有量把故事延續
    if any("縮量反彈" in (x or "") for x in labs) or (
        chg is not None and chg > 1.5 and vol_vs_5 is not None and vol_vs_5 < 0.85
    ):
        checks.insert(
            1,
            {
                "id": "T_escape_follow",
                "when": "09:00–10:30",
                "watch": "昨標「縮量反彈」後：今早是否補量，或高開後量縮回吐",
                "how": "高開無量／迅速翻黑 → 逃命窗延續假設偏強（P04）；開盤即帶量站穩再觀察，仍非買訊",
                "principle": "P04_volume_rebound",
                "data_hint": "盤中量價即可",
                "intraday": True,
                "priority": 1,
            },
        )

    # 7) 正二／槓桿 ETF 價格量能——融資日結盤後才有，盤中用價量代理
    checks.append(
        {
            "id": "T_lever_etf_proxy",
            "when": "09:00–13:30",
            "watch": "正二／槓桿 ETF（如 00685L）盤中價量：急殺無量 vs 有換手",
            "how": "只當「去槓桿是否仍激烈」的盤中側證（P08）；融資停加／轉減要等日結，不准用盤中價假裝融資餘額",
            "principle": "P08_lever_etf",
            "data_hint": "盤中報價；融資餘額屬盤後對質",
            "intraday": True,
            "priority": 5,
        }
    )

    # 8) W5：期貨空單盤中代理——日終 OI 不准當唯一鈕
    checks.append(
        {
            "id": "T_tx_proxy",
            "when": "08:45／09:15／11:00／13:00",
            "watch": "台指期日盤／夜盤活價＋當日量（相對加權是否虛漲）",
            "how": "急漲但期貨量萎縮、或夜盤已失守而日盤虛漲 →「回補／軋空未確認」（P02／P05）；真實減空仍等日終外資 OI 對質",
            "principle": "P02_forced_buy",
            "data_hint": "盤中期價／量；futures_inst_oi 日結只進盤後對質欄",
            "intraday": True,
            "priority": 4,
        }
    )

    # 9) W7：存活閘——無行情欄，開盤前複誦
    checks.insert(
        0,
        {
            "id": "T_l0_survive",
            "when": "08:50 開盤前（W1／W2 觸發再唸）",
            "watch": "停損／最大虧損／部位／現金／睡得著嗎",
            "how": "未設好＝L0 未過，後面燈先不當操作解讀（P09）；仍非買訊",
            "principle": "P09_risk_first",
            "data_hint": "自檢清單，無官方行情欄",
            "intraday": True,
            "priority": 0,
        },
    )

    checks.sort(key=lambda x: (x.get("priority", 9), x.get("id")))
    return checks


def build_after_close_audit_only(pack: Dict[str, Any]) -> List[Dict[str, Any]]:
    """盤後才更新＝對質用，不是明天盤中應對鈕。"""
    return [
        {
            "id": "A_margin_speed",
            "title": "融資速度差 vs 指數",
            "why_not_intraday": "市場融資餘額多為日結／T+1，盤中無法用官方餘額即時算速度差",
            "principle": "P01_margin_speed",
            "use": "今日盤後對質；明日盤中改看開盤量／櫃買／台幣",
        },
        {
            "id": "A_futures_oi",
            "title": "外資期貨淨空口數",
            "why_not_intraday": "期交所法人 OI 多為盤後日結；盤中可看期價／基差，但淨空變動不能假裝已更新",
            "principle": "P02_forced_buy／P11",
            "use": "翻篇條件的對質燈；缺列＝unverifiable",
        },
        {
            "id": "A_full_day_vol",
            "title": "全日量／5日均",
            "why_not_intraday": "比值要等收盤才定案；盤中只用累計量進度",
            "principle": "P04_volume_rebound",
            "use": "收盤後重貼結構標籤",
        },
        {
            "id": "A_triple_sync",
            "title": "減空×現貨轉買×台幣三同步",
            "why_not_intraday": "外資現貨／淨空日結常齊不了；台幣可盤中看，但三燈齊亮多在盤後",
            "principle": "P05_fx_lead",
            "use": "反轉敘事對質；缺一燈就暗",
        },
    ]


def _is_stamp_bar(o: Any, h: Any, l: Any, c: Any) -> bool:
    vals = [_finite_local(o), _finite_local(h), _finite_local(l), _finite_local(c)]
    if any(v is None for v in vals):
        return False
    return vals[0] == vals[1] == vals[2] == vals[3]


def _finite_local(v: Any) -> Optional[float]:
    try:
        if v is None:
            return None
        n = float(v)
    except (TypeError, ValueError):
        return None
    if n != n:
        return None
    return n


def _load_foreign_oi(market_db: str, day: str) -> Dict[str, Any]:
    import sqlite3

    if not market_db or not os.path.isfile(market_db):
        return {"ok": False}
    con = sqlite3.connect(market_db, timeout=30.0)
    try:
        row = con.execute(
            """
            SELECT date, oi_net, oi_short, oi_long
            FROM futures_inst_oi
            WHERE contract LIKE '%臺股%' AND item LIKE '%外資%'
              AND REPLACE(CAST(date AS TEXT),'-','')=?
            LIMIT 1
            """,
            (day,),
        ).fetchone()
        if not row:
            # 最近一筆（標 stale）
            row = con.execute(
                """
                SELECT date, oi_net, oi_short, oi_long
                FROM futures_inst_oi
                WHERE contract LIKE '%臺股%' AND item LIKE '%外資%'
                ORDER BY REPLACE(CAST(date AS TEXT),'-','') DESC
                LIMIT 1
                """
            ).fetchone()
            if not row:
                return {"ok": False}
            asof = "".join(ch for ch in str(row[0]) if ch.isdigit())[:8]
            return {
                "ok": True,
                "asof": asof,
                "stale": asof != day,
                "oi_net": _finite_local(row[1]),
                "oi_short": _finite_local(row[2]),
                "oi_long": _finite_local(row[3]),
            }
        return {
            "ok": True,
            "asof": day,
            "stale": False,
            "oi_net": _finite_local(row[1]),
            "oi_short": _finite_local(row[2]),
            "oi_long": _finite_local(row[3]),
        }
    except sqlite3.Error:
        return {"ok": False}
    finally:
        con.close()


def _load_bfi_foreign(market_db: str, day: str) -> Dict[str, Any]:
    import sqlite3

    if not market_db or not os.path.isfile(market_db):
        return {"ok": False}
    con = sqlite3.connect(market_db, timeout=30.0)
    try:
        row = con.execute(
            """
            SELECT date, foreign_net_yi
            FROM market_inst_bfi_daily
            WHERE REPLACE(CAST(date AS TEXT),'-','')=?
            LIMIT 1
            """,
            (day,),
        ).fetchone()
        if not row:
            row = con.execute(
                """
                SELECT date, foreign_net_yi FROM market_inst_bfi_daily
                ORDER BY REPLACE(CAST(date AS TEXT),'-','') DESC LIMIT 1
                """
            ).fetchone()
            if not row:
                return {"ok": False}
            asof = "".join(ch for ch in str(row[0]) if ch.isdigit())[:8]
            return {
                "ok": True,
                "asof": asof,
                "stale": asof != day,
                "foreign_net_yi": _finite_local(row[1]),
            }
        return {
            "ok": True,
            "asof": day,
            "stale": False,
            "foreign_net_yi": _finite_local(row[1]),
        }
    except sqlite3.Error:
        return {"ok": False}
    finally:
        con.close()


def build_concrete(pack: Dict[str, Any], market_db: str, twii_bars: List[Any]) -> Dict[str, Any]:
    """只收有官方數的具體數字；缺就不進畫面。"""
    day = pack.get("asof") or ""
    tw = pack.get("twii") or {}
    otc = pack.get("otc") or {}
    mg = pack.get("margin") or {}
    fx = pack.get("usdtwd") or {}
    # 找當日完整柱＋昨收
    day_bar = next((b for b in twii_bars if b.date == day), None)
    older = [b for b in twii_bars if b.date < day]
    prev = older[0] if older else None
    stamp = False
    if day_bar:
        stamp = _is_stamp_bar(day_bar.open, day_bar.high, day_bar.low, day_bar.close)
    prev_c = prev.close if prev else None
    close = tw.get("close")
    chg_pct = tw.get("chg_pct")
    chg_pts = None
    if close is not None and prev_c:
        chg_pts = close - prev_c
    vol = tw.get("volume")
    out: Dict[str, Any] = {
        "twii_close": close,
        "twii_prev": prev_c,
        "twii_chg_pts": None if chg_pts is None else round(chg_pts, 2),
        "twii_chg_pct": chg_pct,
        "twii_vol": vol,
        "twii_vol_wan": None if vol is None else round(vol / 10000.0, 1),
        "twii_vol_vs_5": tw.get("vol_vs_5"),
        "twii_vol_vs_20": tw.get("vol_vs_20"),
        "twii_stamp": stamp,
        "twii_o": day_bar.open if day_bar else None,
        "twii_h": day_bar.high if day_bar else None,
        "twii_l": day_bar.low if day_bar else None,
    }
    # 櫃買：必須同日才出
    if otc.get("close") is not None and (otc.get("asof") or "") == day:
        out.update(
            {
                "otc_ok": True,
                "otc_close": otc.get("close"),
                "otc_chg_pct": otc.get("chg_pct"),
                "otc_rel_pp": otc.get("rel_vs_twii_pp"),
            }
        )
    else:
        out["otc_ok"] = False
    # 台幣：同日才當當日；落後就不出主卡（可進附註）
    if fx.get("close") is not None and not fx.get("stale"):
        out.update(
            {
                "fx_ok": True,
                "fx_close": round(float(fx["close"]), 3),
                "fx_chg_pct": fx.get("chg_pct"),
            }
        )
    else:
        out["fx_ok"] = False
        if fx.get("close") is not None:
            out["fx_stale_close"] = round(float(fx["close"]), 3)
            out["fx_stale_asof"] = fx.get("asof")
    # 融資：同日
    if mg.get("bal_k") is not None and (mg.get("asof") or "") == day:
        bal_k = float(mg["bal_k"])
        delta_k = mg.get("delta_k")
        out.update(
            {
                "margin_ok": True,
                "margin_bal_yi": round(bal_k / 100000.0, 1),  # 千元→億
                "margin_delta_yi": (
                    None if delta_k is None else round(float(delta_k) / 100000.0, 1)
                ),
                "margin_chg_pct": mg.get("chg_pct_vs_prev_row"),
                "speed_gap_pp": mg.get("speed_gap_pp"),
            }
        )
    else:
        out["margin_ok"] = False
    oi = _load_foreign_oi(market_db, day)
    if oi.get("ok") and oi.get("oi_net") is not None and not oi.get("stale"):
        oi_net = int(oi["oi_net"])
        prev_day = ""
        try:
            from tw_holidays import previous_tw_trading_day
            prev_day = previous_tw_trading_day(day, market_db) or ""
        except Exception:
            prev_day = ""
        oi_prev = _load_foreign_oi(market_db, prev_day) if prev_day else {"ok": False}
        oi_delta = None
        if oi_prev.get("ok") and not oi_prev.get("stale") and oi_prev.get("oi_net") is not None:
            oi_delta = oi_net - int(oi_prev["oi_net"])
        out.update(
            {
                "oi_ok": True,
                "oi_net": oi_net,
                "oi_short": int(oi["oi_short"]) if oi.get("oi_short") is not None else None,
                "oi_delta": oi_delta,
                "oi_prev_asof": prev_day or None,
            }
        )
    else:
        out["oi_ok"] = False
    bfi = _load_bfi_foreign(market_db, day)
    if bfi.get("ok") and bfi.get("foreign_net_yi") is not None and not bfi.get("stale"):
        out.update(
            {
                "bfi_ok": True,
                "foreign_net_yi": round(float(bfi["foreign_net_yi"]), 1),
            }
        )
    else:
        out["bfi_ok"] = False
        if bfi.get("ok") and bfi.get("foreign_net_yi") is not None:
            out["bfi_stale_yi"] = round(float(bfi["foreign_net_yi"]), 1)
            out["bfi_stale_asof"] = bfi.get("asof")
    return out


def build_watch_desk(
    market_db: str,
    *,
    asof: str = "",
) -> Dict[str, Any]:
    pack = compute_daily_structure(market_db, asof=asof)
    if not pack.get("ok"):
        return {
            "ok": False,
            "note": pack.get("note") or "daily structure failed",
            "not_buy_signal": True,
        }
    tomorrow = build_tomorrow_intraday_checks(pack)
    audit = build_after_close_audit_only(pack)
    # 近窗柱：只留開市日，濾掉週末／休市假柱；三圖對齊加權窗
    twii = load_index_bars(market_db, "TWII", limit=80)
    otc = load_index_bars(market_db, "OTC", limit=80)
    fx = load_index_bars(market_db, "USDTWD", limit=80)
    day = pack["asof"]
    twii_open = _filter_open_bars(list(reversed(twii)), market_db, day=day)
    otc_open = _filter_open_bars(list(reversed(otc)), market_db, day=day)
    fx_open = _filter_open_bars(list(reversed(fx)), market_db, day=day)
    twii_w = twii_open[-28:]
    win_dates = {b.date for b in twii_w}
    otc_w = [b for b in otc_open if b.date in win_dates][-28:]
    fx_w = [b for b in fx_open if b.date in win_dates][-28:]
    vols = [float(b.volume) for b in twii_open if b.volume]
    vol_now = vols[-1] if vols else None

    def _avg(xs):
        return (sum(xs) / len(xs)) if xs else None

    vol5 = _avg(vols[-5:]) if len(vols) >= 5 else None
    vol20 = _avg(vols[-20:]) if len(vols) >= 20 else None
    concrete = build_concrete(pack, market_db, list(reversed(twii_open)))
    if vol_now is not None:
        concrete["twii_vol"] = vol_now
        concrete["twii_vol_wan"] = round(vol_now / 10000.0, 1)
        if vol5:
            concrete["twii_vol_vs_5"] = round(vol_now / vol5, 2)
        if vol20:
            concrete["twii_vol_vs_20"] = round(vol_now / vol20, 2)
    next_day = next_tw_trading_day(day, market_db)
    return {
        "ok": True,
        "asof": day,
        "next_session": next_day,
        "not_buy_signal": True,
        "author": "啾哈觀察",
        "daily": pack,
        "concrete": concrete,
        "today_focus": pack.get("focus") or [],
        "structure_labels": pack.get("structure_labels") or [],
        "tomorrow_intraday": tomorrow,
        "after_close_audit_only": audit,
        "desk_layers": DESK_LAYERS,
        "series": {
            "twii": [
                {
                    "date": b.date,
                    "o": b.open,
                    "h": b.high,
                    "l": b.low,
                    "c": b.close,
                    "v": b.volume,
                    "stamp": _is_stamp_bar(b.open, b.high, b.low, b.close),
                }
                for b in twii_w
            ],
            "otc": [
                {
                    "date": b.date,
                    "o": b.open,
                    "h": b.high,
                    "l": b.low,
                    "c": b.close,
                    "v": b.volume,
                }
                for b in otc_w
                if b.close is not None
            ],
            "usdtwd": [
                {"date": b.date, "c": b.close} for b in fx_w if b.close is not None
            ],
        },
        "headline": _headline(pack),
    }


def _headline(pack: Dict[str, Any]) -> str:
    labs = pack.get("structure_labels") or []
    if labs:
        return "／".join(labs[:2])
    tw = pack.get("twii") or {}
    chg = tw.get("chg_pct")
    if chg is None:
        return "結構未觸發明確標籤"
    if chg >= 1.5:
        return "偏強日・先辨真假換手"
    if chg <= -1.5:
        return "偏弱日・先看清算進度"
    return "震盪日・看量與櫃買相對"


def plain_today_line(desk: Dict[str, Any]) -> str:
    """手機白話一句：今天發生什麼＋具體數字（不准買訊口吻）。"""
    c = desk.get("concrete") or {}
    labs = desk.get("structure_labels") or []
    bits: List[str] = []
    chg = c.get("twii_chg_pct")
    pts = c.get("twii_chg_pts")
    if chg is not None:
        pts_s = f"{pts:+.0f}點" if pts is not None else ""
        if chg <= -3:
            bits.append(f"大盤大跌 {chg:.2f}%（{pts_s}）".replace("（）", ""))
        elif chg <= -1:
            bits.append(f"大盤偏弱 {chg:.2f}%（{pts_s}）".replace("（）", ""))
        elif chg >= 3:
            bits.append(f"大盤大漲 {chg:.2f}%（{pts_s}）".replace("（）", ""))
        elif chg >= 1:
            bits.append(f"大盤偏強 {chg:.2f}%（{pts_s}）".replace("（）", ""))
        else:
            bits.append(f"大盤震盪 {chg:.2f}%（{pts_s}）".replace("（）", ""))
    if c.get("twii_stamp"):
        bits.append("加權當日僅收盤戳記（高低未齊）")
    if c.get("otc_ok") and c.get("otc_rel_pp") is not None:
        bits.append(
            f"櫃買 {c.get('otc_chg_pct'):+.2f}%、相對加權 {c.get('otc_rel_pp'):+.2f}百分點"
        )
    if c.get("margin_ok") and c.get("speed_gap_pp") is not None:
        bits.append(
            f"融資 {c.get('margin_chg_pct'):+.2f}%（速度差 {c.get('speed_gap_pp'):+.2f}百分點）"
        )
    if c.get("fx_ok") and c.get("fx_chg_pct") is not None:
        bits.append(
            f"匯率 {c.get('fx_close')}（{c.get('fx_chg_pct'):+.3f}%＝"
            + ("台幣貶" if c["fx_chg_pct"] > 0 else "台幣升")
            + "）"
        )
    if not bits:
        for lab in labs[:2]:
            bits.append(lab)
    if not bits:
        bits.append(desk.get("headline") or "今天沒觸發明確標籤")
    return "；".join(bits[:3])


def plain_tomorrow_rows(
    checks: List[Dict[str, Any]],
    concrete: Optional[Dict[str, Any]] = None,
    *,
    next_session: str = "",
    asof: str = "",
) -> List[Dict[str, str]]:
    """下一開市日盤中：時段＋門檻＋控車語（非買訊）。"""
    c = concrete or {}
    otc_rel = c.get("otc_rel_pp")
    fx_c = c.get("fx_close")
    ns = _slash_ymd(next_session) if next_session else "下一開市日"
    asof_s = _slash_ymd(asof) if asof else "上一開市日"
    table = {
        "T_l0_survive": (
            "08:50開盤前",
            "停損／最多虧多少設好了嗎；未設好＝後面燈先不當操作解讀（空手／等待）",
        ),
        "T_open15_vol": (
            "09:00–09:15",
            "第一根15分量＜近20日同時段中位×0.70＝量縮鎖死→空手等待；無同時段基準＝不判（不准拿全日量頂替）",
        ),
        "T_escape_follow": (
            "09:00–10:30",
            "昨標縮量反彈後：今早無補量／高開回吐→逃命窗延續假設；仍非買訊",
        ),
        "T_am_vol_pace": (
            "09:30／10:30／11:30",
            "大漲＞+1.5%且累計＜同時點中位×0.85→縮量反彈假設，不追；無同時段基準＝不判",
        ),
        "T_level_probe": (
            "碰到已點名價時",
            "有點名頸線／前高才對該價；刺穿後立刻打回→假突破假設；沒點名價＝本列不啟用",
        ),
        "T_otc_rel": (
            "09:30起每30分",
            (
                f"櫃買％−加權％持續＜−0.5百分點逾60分→融資壓力↑（{asof_s}相對 {otc_rel:+.2f}）；控車＝提高警戒／等待"
                if otc_rel is not None
                else "櫃買％−加權％持續＜−0.5百分點逾60分→融資壓力↑；控車＝提高警戒／等待"
            ),
        ),
        "T_fx_lead": (
            "08:30／09:30／11:00／13:00",
            (
                f"USDTWD較{asof_s}收（{fx_c}）貶≥0.15%＝壓力燈、升≥0.15%＝偏暖；與指數背離優先信台幣"
                if fx_c
                else "台幣較昨收貶≥0.15%＝壓力、升≥0.15%＝偏暖；與指數背離優先信台幣"
            ),
        ),
        "T_tx_proxy": (
            "08:45／09:15／11:00／13:00",
            "台指期價量是否跟著；急漲但期量萎縮→回補未確認；外資OI今晚才對質",
        ),
        "T_lever_etf_proxy": (
            "09:00–13:30",
            "正二／槓桿ETF急殺無量vs有換手＝去槓桿側證；融資餘額盤後才對質",
        ),
    }
    if not c.get("otc_ok"):
        table.pop("T_otc_rel", None)
    prefer = [
        "T_l0_survive",
        "T_open15_vol",
        "T_escape_follow",
        "T_am_vol_pace",
        "T_otc_rel",
        "T_fx_lead",
        "T_tx_proxy",
        "T_lever_etf_proxy",
        "T_level_probe",
    ]
    by_id = {str(ch.get("id") or ""): ch for ch in (checks or [])}
    out: List[Dict[str, str]] = []
    for cid in prefer:
        if cid not in by_id or cid not in table:
            continue
        when, line = table[cid]
        out.append({"when": when, "line": line, "id": cid, "session": ns})
        if len(out) >= 7:
            break
    return out


def _fmt_num(v: Any, n: int = 2) -> str:
    if v is None:
        return "—"
    try:
        return f"{float(v):.{n}f}"
    except (TypeError, ValueError):
        return str(v)


def render_watch_desk_markdown(desk: Dict[str, Any]) -> str:
    if not desk.get("ok"):
        return f"# 啾哈觀盤（非買訊）\n\n缺資料：{desk.get('note')}\n"
    c = desk.get("concrete") or {}
    asof = desk.get("asof") or ""
    ns = desk.get("next_session") or ""
    labs = desk.get("structure_labels") or []
    lines = [
        f"# 啾哈觀盤 {_slash_ymd(asof, with_year=True)}（非買訊）",
        "",
        f"**結構：** {'／'.join(labs[:2]) if labs else (desk.get('headline') or '')}",
        f"**今天：** {plain_today_line(desk)}",
        "",
        "## 盤中可對照（有才列）",
    ]
    if c.get("twii_close") is not None:
        stamp = "［僅收盤戳記］" if c.get("twii_stamp") else ""
        lines.append(
            f"- 加權收 {_fmt_num(c.get('twii_close'))}（{_fmt_num(c.get('twii_chg_pts'), 0)}點／{_fmt_num(c.get('twii_chg_pct'))}%）{stamp}"
        )
        lines.append(
            f"- 成交量 {_fmt_num(c.get('twii_vol_wan'), 1)}萬張（／五日 {_fmt_num(c.get('twii_vol_vs_5'))}×、／二十日 {_fmt_num(c.get('twii_vol_vs_20'))}×）"
        )
    if c.get("otc_ok"):
        lines.append(
            f"- 櫃買收 {_fmt_num(c.get('otc_close'))}（{_fmt_num(c.get('otc_chg_pct'))}%），相對加權 {_fmt_num(c.get('otc_rel_pp'))} 百分點"
        )
    if c.get("fx_ok"):
        fx_dir = "台幣貶" if (c.get("fx_chg_pct") or 0) > 0 else "台幣升"
        lines.append(
            f"- 美金台幣 {_fmt_num(c.get('fx_close'), 3)}（{_fmt_num(c.get('fx_chg_pct'), 3)}%＝{fx_dir}）"
        )
    lines += ["", "## 盤後對質（非盤中鈕）"]
    if c.get("margin_ok"):
        gap = c.get("speed_gap_pp")
        gap_txt = ""
        if gap is not None:
            if gap < 0:
                gap_txt = f"，融資跌更快 {abs(float(gap)):.2f}百分點"
            else:
                gap_txt = f"，融資跌較慢 {float(gap):.2f}百分點"
        lines.append(
            f"- 融資餘額 {_fmt_num(c.get('margin_bal_yi'), 1)}億（{_fmt_num(c.get('margin_delta_yi'), 1)}億／{_fmt_num(c.get('margin_chg_pct'))}%）{gap_txt}［對質］"
        )
    if c.get("oi_ok"):
        net = c.get("oi_net")
        delta = c.get("oi_delta")
        net_txt = f"淨部位 {int(net):+,}口" if net is not None else ""
        if delta is not None:
            dlt = int(delta)
            dlt_txt = (
                f"減空 {abs(dlt):,}口"
                if dlt > 0
                else (f"加空 {abs(dlt):,}口" if dlt < 0 else "淨空持平")
            )
            lines.append(f"- 外資期貨{net_txt}（較上開市日{dlt_txt}）［對質］")
        else:
            lines.append(f"- 外資期貨{net_txt}［對質］")
    if c.get("bfi_ok"):
        lines.append(f"- 外資現貨淨買賣 {_fmt_num(c.get('foreign_net_yi'), 1)}億［對質］")
    if not any(c.get(k) for k in ("margin_ok", "oi_ok", "bfi_ok")):
        lines.append("- （當日對質欄未齊）")
    sess = _slash_ymd(ns, with_year=True) if ns else "下一開市日"
    lines += ["", f"## {sess} 盤中這樣看（只觀察；切入仍只認高低卡）"]
    for i, r in enumerate(
        plain_tomorrow_rows(
            desk.get("tomorrow_intraday") or [],
            c,
            next_session=ns,
            asof=asof,
        ),
        1,
    ):
        lines.append(f"{i}. {r.get('when')}｜{r.get('line')}")
    lines += [
        "",
        "缺欄不畫。觀察≠買訊。怎麼買仍看高低卡已過關規則。",
        "",
    ]
    return "\n".join(lines)


def _checklist_blocks(
    rows: List[Dict[str, str]], *, body_width: int = 24
) -> List[Dict[str, Any]]:
    """盤中清單：時段一行、內文可換行（最多 2 行）；回傳每列實際行數方便量高。"""
    out: List[Dict[str, Any]] = []
    for r in rows[:6]:
        when = _short_when(str(r.get("when") or "").strip())
        body = _wrap_at_punct(str(r.get("line") or "").strip(), body_width)
        body_lines = [ln for ln in body.split("\n") if ln] or ["—"]
        if len(body_lines) > 2:
            body_lines = body_lines[:2]
            if not body_lines[-1].endswith("…"):
                body_lines[-1] = body_lines[-1].rstrip("；、。") + "…"
        out.append({"when": when, "body_lines": body_lines, "n_lines": 1 + len(body_lines)})
    return out


def render_watch_desk_png(desk: Dict[str, Any], path: str) -> str:
    """v4：由上往下量測排版；盤中卡／對質區分開；開市日窗；戳記不畫完整K。

    畫布高度跟內容走：缺櫃買／匯／對質時不准留大片空白；清單時段與內文分行，不准互壓。
    """
    if not desk.get("ok"):
        return ""
    import matplotlib

    matplotlib.use("Agg", force=False)
    import matplotlib.pyplot as plt
    from matplotlib.patches import FancyBboxPatch, Rectangle
    from matplotlib.lines import Line2D
    from matplotlib.ticker import FuncFormatter

    asof = desk.get("asof") or ""
    ns = desk.get("next_session") or ""
    c = desk.get("concrete") or {}
    series = desk.get("series") or {}
    twii_s = series.get("twii") or []
    otc_s = series.get("otc") or []
    fx_s = series.get("usdtwd") or []
    labs = desk.get("structure_labels") or []
    plain = plain_today_line(desk)
    rows = plain_tomorrow_rows(
        desk.get("tomorrow_intraday") or [], c, next_session=ns, asof=asof
    )
    blocks = _checklist_blocks(rows, body_width=30)

    bg, ink, mute, card = "#f4f2ec", "#1a1a1a", "#5a5a5a", "#ffffff"
    red, green, audit_bg = "#c62828", "#2e7d32", "#fff8e7"
    chg = c.get("twii_chg_pct")
    up = chg is not None and chg >= 0
    chg_color = red if up else green

    # 先算要畫哪些卡，才能估畫布高（缺欄就不佔位）
    intra: List[Tuple[str, str, str, str]] = []
    if c.get("twii_close") is not None:
        pts = c.get("twii_chg_pts")
        sub = (
            f"{pts:+.0f}點／{chg:+.2f}%"
            if pts is not None and chg is not None
            else (f"{chg:+.2f}%" if chg is not None else "")
        )
        if c.get("twii_stamp"):
            sub += " · 僅收盤戳記"
        intra.append(("加權收", f"{c['twii_close']:,.0f}", sub, chg_color))
    if c.get("twii_vol_wan") is not None:
        intra.append(
            (
                "成交量",
                f"{c['twii_vol_wan']:,.1f}萬張",
                f"／5日 {c.get('twii_vol_vs_5')}×  ／20日 {c.get('twii_vol_vs_20')}×",
                ink,
            )
        )
    if c.get("otc_ok"):
        intra.append(
            (
                "櫃買收",
                f"{c['otc_close']:.2f}",
                f"{c.get('otc_chg_pct'):+.2f}% · 相對 {c.get('otc_rel_pp'):+.2f}百分點",
                green if (c.get("otc_chg_pct") or 0) < 0 else red,
            )
        )
    if c.get("fx_ok"):
        fx_dir = "台幣貶" if (c.get("fx_chg_pct") or 0) > 0 else "台幣升"
        intra.append(
            (
                "美金台幣",
                f"{c['fx_close']:.3f}",
                f"{c.get('fx_chg_pct'):+.3f}%＝{fx_dir}",
                ink,
            )
        )
    have_otc = bool(c.get("otc_ok") and otc_s)
    have_fx = bool(c.get("fx_ok") and fx_s)
    n_audit = sum(
        1
        for k in ("margin_ok", "oi_ok", "bfi_ok")
        if c.get(k)
    )
    n_intra_rows = max(1, (len(intra) + 1) // 2)
    n_audit_rows = (n_audit + 1) // 2 if n_audit else 0
    # 清單槽：每列 when+body 行＋列間隙；每槽至少 0.30" 才不互壓
    checklist_slots_est = sum(int(b["n_lines"]) for b in blocks) + max(len(blocks) - 1, 0)
    checklist_inch = max(2.8, 0.55 + checklist_slots_est * 0.30)
    fig_w, dpi = 9.2, 150
    inch = (
        0.55  # title
        + (0.32 if labs else 0.0)
        + 0.95  # today
        + n_intra_rows * 0.95
        + 3.7  # K+vol
        + (1.85 if (have_otc or have_fx) else 0.0)
        + (0.4 + n_audit_rows * 0.9 if n_audit else 0.0)
        + checklist_inch
        + 0.6  # footer pad
    )
    fig_h = max(12.5, min(22.0, inch))
    fig = plt.figure(figsize=(fig_w, fig_h), dpi=dpi, facecolor=bg)
    y = 0.985  # top cursor in figure fraction

    def _advance(h: float, gap: float = 0.008) -> float:
        nonlocal y
        top = y - h
        y = top - gap
        return top
    # title
    fig.text(
        0.045,
        y,
        f"啾哈觀盤  {_slash_ymd(asof, with_year=True)}",
        color=ink,
        fontproperties=_fp(26, "bold"),
        ha="left",
        va="top",
    )
    fig.text(
        0.955,
        y,
        "非買訊",
        color=mute,
        fontproperties=_fp(15, "bold"),
        ha="right",
        va="top",
    )
    y -= 0.028
    if labs:
        fig.text(
            0.045,
            y,
            "／".join(str(x) for x in labs[:2]),
            color=red,
            fontproperties=_fp(14, "bold"),
            ha="left",
            va="top",
        )
        y -= 0.022

    # today box
    h_today = 0.07
    top = _advance(h_today)
    ax_h = fig.add_axes([0.045, top, 0.91, h_today])
    ax_h.set_xlim(0, 1)
    ax_h.set_ylim(0, 1)
    ax_h.axis("off")
    ax_h.add_patch(
        FancyBboxPatch(
            (0, 0),
            1,
            1,
            boxstyle="round,pad=0.01,rounding_size=0.025",
            facecolor=card,
            edgecolor="#ddd7cb",
            linewidth=1.4,
            transform=ax_h.transAxes,
        )
    )
    ax_h.text(0.03, 0.82, "今天（已收）", color=mute, fontproperties=_fp(12, "bold"), va="top")
    ax_h.text(
        0.03,
        0.38,
        _wrap_at_punct(plain, 26),
        color=ink,
        fontproperties=_fp(15, "bold"),
        va="center",
        linespacing=1.3,
    )

    # intraday metric cards (2-col) — exclude margin/OI；內容已在上方組好
    card_h = 0.072
    for i in range(0, len(intra), 2):
        top = _advance(card_h)
        pair = intra[i : i + 2]
        for j, (title, big, sub, col) in enumerate(pair):
            x0 = 0.045 + j * 0.465
            ax = fig.add_axes([x0, top, 0.445, card_h])
            ax.set_xlim(0, 1)
            ax.set_ylim(0, 1)
            ax.axis("off")
            ax.add_patch(
                FancyBboxPatch(
                    (0, 0),
                    1,
                    1,
                    boxstyle="round,pad=0.02,rounding_size=0.04",
                    facecolor=card,
                    edgecolor="#ddd7cb",
                    linewidth=1.1,
                    transform=ax.transAxes,
                )
            )
            ax.text(0.06, 0.78, title, color=mute, fontproperties=_fp(13, "bold"), va="top")
            ax.text(0.06, 0.42, big, color=col, fontproperties=_fp(22, "bold"), va="center")
            ax.text(0.06, 0.12, sub, color=mute, fontproperties=_fp(12), va="bottom")

    # K + volume（量圖與下方小圖之間多留縫，不准標籤互壓）
    k_h, v_h = 0.155, 0.052
    top_k = _advance(k_h + v_h + 0.018)
    ax_k = fig.add_axes([0.11, top_k + v_h + 0.006, 0.80, k_h])
    ax_v = fig.add_axes([0.11, top_k, 0.80, v_h], sharex=ax_k)
    for ax in (ax_k, ax_v):
        ax.set_facecolor(card)
        for sp in ax.spines.values():
            sp.set_color("#ddd7cb")
        ax.tick_params(colors=mute, labelsize=10)
    ax_k.set_title(
        "加權日K＋量（開市日窗；◆＝僅收盤戳記）",
        color=ink,
        fontproperties=_fp(13, "bold"),
        loc="left",
        pad=4,
    )
    if twii_s:
        closes_line = []
        for i, b in enumerate(twii_s):
            o, h, l, cl = b.get("o"), b.get("h"), b.get("l"), b.get("c")
            if cl is None:
                closes_line.append(None)
                continue
            closes_line.append(cl)
            stamp = bool(b.get("stamp")) or _is_stamp_bar(o, h, l, cl)
            prev_c = twii_s[i - 1].get("c") if i > 0 else None
            if stamp:
                col = red if (prev_c is None or cl >= prev_c) else green
            else:
                col = red if (o is None or cl >= o) else green
            if stamp or o is None or h is None or l is None:
                ax_k.plot([i], [cl], marker="D", color=col, markersize=6, zorder=5)
            else:
                ax_k.add_line(Line2D([i, i], [l, h], color=col, lw=1.2, zorder=3))
                body_lo = min(o, cl)
                body_h = abs(cl - o) or max((h - l) * 0.02, 1.0)
                ax_k.add_patch(
                    Rectangle(
                        (i - 0.32, body_lo),
                        0.64,
                        body_h,
                        facecolor=col,
                        edgecolor=col,
                        linewidth=0.6,
                        zorder=4,
                    )
                )
            vol = (b.get("v") or 0) / 10000.0  # 萬張
            ax_v.bar(i, vol, width=0.7, color=col, alpha=0.85)
        xs = [i for i, v in enumerate(closes_line) if v is not None]
        ys = [closes_line[i] for i in xs]
        if len(xs) >= 2:
            ax_k.plot(xs, ys, color="#666666", lw=1.0, alpha=0.55, zorder=2)
        ax_k.set_xlim(-0.8, len(twii_s) - 0.2)
        ticks = [0, len(twii_s) // 2, len(twii_s) - 1]
        labs_x = []
        for ti in ticks:
            d0 = str(twii_s[ti].get("date") or "")
            labs_x.append(_slash_ymd(d0))
        ax_v.set_xticks(ticks)
        ax_v.set_xticklabels(labs_x, fontproperties=_fp(11))
        ax_k.tick_params(labelbottom=False)
        ax_k.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:,.0f}"))
        ax_v.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:.0f}"))
        for lab in ax_k.get_yticklabels():
            lab.set_fontproperties(_fp(10))
        for lab in ax_v.get_yticklabels():
            lab.set_fontproperties(_fp(9))
        ax_v.set_ylabel("萬張", color=mute, fontproperties=_fp(10))

    # small charts（缺欄不畫、不留空位）
    if have_otc or have_fx:
        sm_h = 0.095
        top = _advance(sm_h, gap=0.014)
        if have_otc and have_fx:
            boxes = [(0.08, 0.41), (0.51, 0.41)]
        else:
            boxes = [(0.08, 0.84)]
        idx = 0
        if have_otc:
            x0, w = boxes[idx]
            idx += 1
            ax_o = fig.add_axes([x0, top, w, sm_h])
            ax_o.set_facecolor(card)
            for sp in ax_o.spines.values():
                sp.set_color("#ddd7cb")
            ax_o.tick_params(colors=mute, labelsize=9)
            ax_o.set_title(
                f"櫃買收盤（{_slash_ymd(asof)}相對 {c.get('otc_rel_pp'):+.2f}百分點）",
                color=ink,
                fontproperties=_fp(12, "bold"),
                loc="left",
            )
            oc = [x.get("c") for x in otc_s if x.get("c") is not None]
            if oc:
                ax_o.plot(range(len(oc)), oc, color="#1565c0", lw=2.0)
                ax_o.fill_between(range(len(oc)), oc, min(oc), color="#1565c0", alpha=0.08)
                d0 = str(otc_s[0].get("date") or "")
                d1 = str(otc_s[-1].get("date") or "")
                ax_o.set_xticks([0, len(oc) - 1])
                ax_o.set_xticklabels([_slash_ymd(d0), _slash_ymd(d1)], fontproperties=_fp(10))
        if have_fx:
            x0, w = boxes[idx] if idx < len(boxes) else (0.51, 0.41)
            ax_f = fig.add_axes([x0, top, w, sm_h])
            ax_f.set_facecolor(card)
            for sp in ax_f.spines.values():
                sp.set_color("#ddd7cb")
            ax_f.tick_params(colors=mute, labelsize=9)
            ax_f.set_title(
                "美金台幣（線往上＝台幣貶）",
                color=ink,
                fontproperties=_fp(12, "bold"),
                loc="left",
            )
            ys = [x.get("c") for x in fx_s]
            ax_f.plot(range(len(ys)), ys, color="#b8860b", lw=2.0)
            ax_f.set_xticks([0, len(ys) - 1])
            d0, d1 = str(fx_s[0].get("date")), str(fx_s[-1].get("date"))
            ax_f.set_xticklabels([_slash_ymd(d0), _slash_ymd(d1)], fontproperties=_fp(10))

    # audit section
    audit_bits: List[Tuple[str, str, str]] = []
    if c.get("margin_ok"):
        gap = c.get("speed_gap_pp")
        if gap is not None and gap < 0:
            gap_s = f"融資跌更快 {abs(float(gap)):.2f}百分點"
        elif gap is not None:
            gap_s = f"融資跌較慢 {float(gap):.2f}百分點"
        else:
            gap_s = ""
        audit_bits.append(
            (
                "融資餘額［對質］",
                f"{c['margin_bal_yi']:,.1f}億",
                f"{c.get('margin_delta_yi'):+.1f}億／{c.get('margin_chg_pct'):+.2f}% · {gap_s}",
            )
        )
    if c.get("oi_ok"):
        net = c.get("oi_net")
        delta = c.get("oi_delta")
        big = f"淨部位 {int(net):+,}口" if net is not None else "—"
        if delta is not None:
            dlt = int(delta)
            sub = (
                f"較上開市日減空 {abs(dlt):,}口"
                if dlt > 0
                else (f"較上開市日加空 {abs(dlt):,}口" if dlt < 0 else "淨空持平")
            )
        else:
            sub = "日變缺"
        if c.get("oi_short") is not None:
            sub += f" · 空單 {c['oi_short']:,}口"
        audit_bits.append(("外資期貨［對質］", big, sub))
    if c.get("bfi_ok"):
        audit_bits.append(
            ("外資現貨［對質］", f"{c['foreign_net_yi']:+.1f}億", "當日三大法人外資欄")
        )
    if audit_bits:
        fig.text(
            0.045,
            y,
            "盤後對質（非盤中鈕）",
            color=mute,
            fontproperties=_fp(13, "bold"),
            ha="left",
            va="top",
        )
        y -= 0.02
        ah = 0.055
        for i in range(0, len(audit_bits), 2):
            top = _advance(ah)
            for j, (title, big, sub) in enumerate(audit_bits[i : i + 2]):
                x0 = 0.045 + j * 0.465
                ax = fig.add_axes([x0, top, 0.445, ah])
                ax.set_xlim(0, 1)
                ax.set_ylim(0, 1)
                ax.axis("off")
                ax.add_patch(
                    FancyBboxPatch(
                        (0, 0),
                        1,
                        1,
                        boxstyle="round,pad=0.02,rounding_size=0.04",
                        facecolor=audit_bg,
                        edgecolor="#e0c97a",
                        linewidth=1.1,
                        transform=ax.transAxes,
                    )
                )
                ax.text(0.06, 0.78, title, color=mute, fontproperties=_fp(12, "bold"), va="top")
                ax.text(0.06, 0.42, big, color=ink, fontproperties=_fp(16, "bold"), va="center")
                ax.text(0.06, 0.12, sub, color=mute, fontproperties=_fp(11), va="bottom")

    # tomorrow checklist：時段／內文分行；ylim 貼齊內容，不准白肚
    sess = _slash_ymd(ns, with_year=True) if ns else "下一開市日"
    row_slots: List[Tuple[str, Any]] = []
    for b in blocks:
        row_slots.append(("when", b))
        for ln in b["body_lines"]:
            row_slots.append(("body", ln))
        row_slots.append(("gap", None))
    if row_slots and row_slots[-1][0] == "gap":
        row_slots.pop()
    n_slots = max(len(row_slots), 1)
    # 內容單位：標題1.2 + 各槽 + 底墊0.4
    content_units = 1.2 + sum(0.35 if k == "gap" else 1.0 for k, _ in row_slots) + 0.45
    list_h = min(0.50, max(0.18, (content_units * 0.28) / fig_h))
    remain = max(y - 0.05, 0.16)
    list_h = min(list_h, remain)
    top = _advance(list_h, gap=0.012)
    if top < 0.04:
        top = 0.04
        list_h = max(0.14, y - 0.018)
    ax_t = fig.add_axes([0.045, top, 0.91, list_h])
    ymax = content_units
    ax_t.set_xlim(0, 1)
    ax_t.set_ylim(0, ymax)  # 底貼齊，不留大段空白座標
    ax_t.axis("off")
    ax_t.add_patch(
        FancyBboxPatch(
            (0, 0),
            1,
            1,
            boxstyle="round,pad=0.01,rounding_size=0.025",
            facecolor=card,
            edgecolor="#ddd7cb",
            linewidth=1.4,
            transform=ax_t.transAxes,
            zorder=0,
        )
    )
    y_cursor = ymax - 0.25
    ax_t.text(
        0.03,
        y_cursor,
        f"{sess} 盤中這樣看（只觀察；切入仍只認高低卡）",
        color=ink,
        fontproperties=_fp(13, "bold"),
        va="top",
        zorder=2,
    )
    y_cursor -= 1.15
    item_i = 0
    for kind, payload in row_slots:
        if kind == "gap":
            y_cursor -= 0.35
            continue
        if kind == "when":
            item_i += 1
            b = payload
            ax_t.text(
                0.03,
                y_cursor,
                f"{item_i}",
                color=red,
                fontproperties=_fp(13, "bold"),
                va="top",
                zorder=2,
            )
            ax_t.text(
                0.09,
                y_cursor,
                b["when"],
                color=mute,
                fontproperties=_fp(12, "bold"),
                va="top",
                zorder=2,
            )
            y_cursor -= 1.0
            continue
        ax_t.text(
            0.09,
            y_cursor,
            payload,
            color=ink,
            fontproperties=_fp(12, "bold"),
            va="top",
            zorder=2,
        )
        y_cursor -= 1.0

    foot_y = max(0.012, top - 0.016)
    fig.text(
        0.045,
        foot_y,
        "缺欄不畫。觀察≠買訊。怎麼買仍看高低卡已過關規則。",
        color=mute,
        fontproperties=_fp(11),
        ha="left",
        va="top",
    )
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(
        path,
        facecolor=fig.get_facecolor(),
        edgecolor="none",
        bbox_inches="tight",
        pad_inches=0.25,
    )
    plt.close(fig)
    return path


def _fuse_log_path(out_dir: Path) -> Path:
    return out_dir / "desk_fuse_log.jsonl"


def append_fuse_log(desk: Dict[str, Any], out_dir: str) -> str:
    """每日融會紀要：可重畫、可追加，不准當買訊。"""
    outp = Path(out_dir)
    outp.mkdir(parents=True, exist_ok=True)
    path = _fuse_log_path(outp)
    row = {
        "fused_at_taipei": datetime.now(TAIPEI).isoformat(),
        "asof": desk.get("asof"),
        "headline": desk.get("headline"),
        "structure_labels": desk.get("structure_labels") or [],
        "tomorrow_ids": [c.get("id") for c in (desk.get("tomorrow_intraday") or [])],
        "missing_official": (desk.get("daily") or {}).get("missing_official") or [],
        "not_buy_signal": True,
    }
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    latest = outp / "desk_fuse_latest.json"
    latest.write_text(json.dumps(row, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path)


def _phone_caption(desk: Dict[str, Any]) -> str:
    if not desk.get("ok"):
        return "啾哈觀盤暫時組不出（非買訊）。"
    asof = desk.get("asof") or ""
    ns = desk.get("next_session") or ""
    lines = [
        f"啾哈觀盤 {_slash_ymd(asof, with_year=True)}（非買訊）",
        plain_today_line(desk),
    ]
    c = desk.get("concrete") or {}
    rows = plain_tomorrow_rows(
        desk.get("tomorrow_intraday") or [], c, next_session=ns, asof=asof
    )
    if rows:
        tip = "；".join(f"{r['when']} {r['line']}" for r in rows[:2])
        sess = _slash_ymd(ns) if ns else "下一開市日"
        lines.append(f"{sess}先看：{tip}")
    return "\n".join(lines)


def write_watch_desk_artifacts(
    *,
    market_db: str = str(DEFAULT_MARKET),
    out_dir: str = str(DEFAULT_OUT),
    asof: str = "",
    png_path: str = "",
    fuse_log: bool = True,
) -> Dict[str, Any]:
    """產出觀盤桌。每次呼叫重算＋重畫（圖不准一成不變鎖死）。"""
    outp = Path(out_dir)
    outp.mkdir(parents=True, exist_ok=True)
    desk = build_watch_desk(market_db, asof=asof)
    stamp = desk.get("asof") or datetime.now(TAIPEI).strftime("%Y%m%d")
    md = render_watch_desk_markdown(desk)
    md_path = outp / f"watch_desk_{stamp}.md"
    json_path = outp / f"watch_desk_{stamp}.json"
    target_png = Path(png_path) if png_path else (outp / f"watch_desk_{stamp}.png")
    target_png.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(md, encoding="utf-8")
    json_path.write_text(json.dumps(desk, ensure_ascii=False, indent=2), encoding="utf-8")
    png = ""
    if desk.get("ok"):
        try:
            if target_png.is_file():
                target_png.unlink()
        except OSError:
            pass
        png = render_watch_desk_png(desk, str(target_png))
    log_path = ""
    if fuse_log and desk.get("ok"):
        log_path = append_fuse_log(desk, str(outp))
    return {
        "ok": bool(desk.get("ok")),
        "asof": stamp,
        "md": str(md_path),
        "json": str(json_path),
        "png": png or str(target_png),
        "fuse_log": log_path,
        "n_tomorrow_intraday": len(desk.get("tomorrow_intraday") or []),
        "desk": desk,
        "caption": _phone_caption(desk),
    }


def run_jiuha_daily_fuse(
    *,
    market_db: str = str(DEFAULT_MARKET),
    out_dir: str = str(DEFAULT_OUT),
    charts_dir: str = "",
) -> Dict[str, Any]:
    """盤後融會：依最新官方柱重算觀盤桌＋追加融會日誌（圖每次重畫）。"""
    res = write_watch_desk_artifacts(
        market_db=market_db,
        out_dir=out_dir,
        fuse_log=True,
    )
    if charts_dir and res.get("ok"):
        stamp = res.get("asof") or "na"
        dest = Path(charts_dir) / "jiuha" / f"watch_desk_{stamp}.png"
        dest.parent.mkdir(parents=True, exist_ok=True)
        src = Path(res.get("png") or "")
        if src.is_file():
            dest.write_bytes(src.read_bytes())
            res["charts_png"] = str(dest)
            res["png"] = str(dest)
    return res


__all__ = [
    "append_fuse_log",
    "build_after_close_audit_only",
    "build_tomorrow_intraday_checks",
    "build_watch_desk",
    "plain_today_line",
    "plain_tomorrow_rows",
    "render_watch_desk_markdown",
    "render_watch_desk_png",
    "run_jiuha_daily_fuse",
    "write_watch_desk_artifacts",
]
