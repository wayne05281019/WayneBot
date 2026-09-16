# -*- coding: utf-8 -*-
"""飆大視窗的思考鏈：六顆神經元按他的推論順序開火。

不是 CNN、不是別人的 AGI 規格。材料只准官方庫＋他自己公開文。
每句對話都要整條走完，不准只命中一個關鍵字就答。

順序＝他真正在用的：
  1 大盤巢穴（細微波／15／60／夜盤看大盤；覆巢之下無完卵；沒疊滿不篤定）
  2 產業／主戰場還在不在（個股最重要是產業趨勢）
  3 這族龍頭現在攻還是休（跟漲先看龍頭）
  4 這檔官方日 K 量先價行（爆大量日高當壓、低當撐；個股不數浪）
  5 長抱還是進出（7/24 切勿輕易調節 vs F10 等回測；聯發科不是 4/16）
  6 可能看錯（沒疊滿、沒點名、改口一起留）

圖是第 4 顆的眼睛，不是大腦。右灰區只演算最可能碰到哪，不是保證。不是買訊、不進海選。
"""
from __future__ import annotations

import re
import time
from typing import Any, Dict, List, Optional, Tuple

NEURON_IDS = ("nest", "field", "leader", "tape", "hold", "doubt")
NEURON_TITLES = {
    "nest": "大盤巢穴",
    "field": "產業／主戰場",
    "leader": "這族龍頭",
    "tape": "這檔量價",
    "hold": "長抱或進出",
    "doubt": "可能看錯",
}


def _px(val: Any) -> str:
    try:
        n = float(val)
    except (TypeError, ValueError):
        return ""
    if abs(n - round(n)) < 1e-9:
        return str(int(round(n)))
    return f"{n:.2f}".rstrip("0").rstrip(".")


def _chg(val: Any) -> str:
    try:
        n = float(val)
    except (TypeError, ValueError):
        return ""
    if n > 0:
        return f"＋{n:.2f}%"
    if n < 0:
        return f"{n:.2f}%".replace("-", "−")
    return "0.00%"


def _latest_us_overnight(db_path: str) -> Dict[str, Any]:
    """只讀庫裡最後一筆隔夜費半／那指。不准現抓、不准編今天沒有的點。"""
    if not db_path:
        return {}
    try:
        import sqlite3

        conn = sqlite3.connect(db_path, timeout=8.0)
        try:
            row = conn.execute(
                "SELECT as_of, sox_pct, ixic_pct FROM us_overnight ORDER BY as_of DESC LIMIT 1"
            ).fetchone()
        except sqlite3.Error:
            row = None
        finally:
            conn.close()
        if not row:
            return {}
        as_of = str(row[0] or "").replace("-", "")[:8]
        if not as_of:
            return {}
        out: Dict[str, Any] = {"as_of": as_of}
        if row[1] is not None:
            try:
                out["sox_pct"] = float(row[1])
            except (TypeError, ValueError):
                pass
        if len(row) > 2 and row[2] is not None:
            try:
                out["ixic_pct"] = float(row[2])
            except (TypeError, ValueError):
                pass
        return out
    except Exception:
        return {}


def _view_line(nid: str, *, n: int = 160) -> str:
    """這顆神經元重讀他的說法。沒問到關鍵字也要讀，不准抽完就丟。"""
    try:
        from biaoke_mind import views_for_neuron
    except Exception:
        return ""
    clips: List[str] = []
    for title, body in views_for_neuron(nid):
        bit = _clip(body, n)
        if bit:
            clips.append(f"{title}：{bit}")
        if len(clips) >= 2:
            break
    if not clips:
        return ""
    return "他的說法：" + " ".join(clips)


def _own_holding(db_path: str, uid: str, sid: str) -> Dict[str, Any]:
    """只讀這人倉。不准改倉、不准看別人倉。"""
    if not db_path or not uid or not sid:
        return {}
    try:
        from wayne_db import get_user_portfolio

        want = str(sid).strip()
        for row in get_user_portfolio(db_path, str(uid)):
            if str(row.get("stock_code") or "").strip() == want:
                return dict(row)
    except Exception:
        return {}
    return {}


_NEW_HIGH_NAMES = (
    ("3017", "奇鋐"),
    ("3653", "健策"),
    ("3081", "聯亞"),
    ("3443", "創意"),
    ("2408", "南亞科"),
)


def _new_high_retract(db_path: str) -> str:
    """9/16 之後只回撤他點過的新高檔官方日K，不准編升息結果。"""
    if not db_path:
        return ""
    try:
        from biaoke_brain import load_bars, volume_first_price
    except Exception:
        return ""
    parts: List[str] = []
    for sid, name in _NEW_HIGH_NAMES:
        try:
            bars = load_bars(db_path, sid, n=40)
        except Exception:
            bars = []
        st = volume_first_price(bars) if len(bars) >= 8 else {}
        if not st:
            continue
        if st.get("broke_resistance"):
            flag = "過壓"
        elif st.get("above_support"):
            flag = "站上撐"
        else:
            flag = "撐下"
        parts.append(f"{name}收{_px(st.get('close')) or '—'}{flag}")
    return "新高檔官方日K：" + "、".join(parts) if parts else ""


def _pointed_calendar(db_path: str, as_of: str) -> str:
    """他自己點的日曆／國際局勢。不是看新聞做股票。

    9/16 台股日 ≠ Fed 已過：決策在 9/15～9/16，台北 9/16 收盤仍可能還沒公布。
    9/17 起才准說這顆日曆過了，升息結果仍不准編。
    """
    ymd = "".join(ch for ch in str(as_of or "") if ch.isdigit())[:8]
    dual = (
        "三個9/16不准混：Fed升息結果不准編；"
        "奇鋐「明天只能上不能下」的明天＝9/16、盤中未收不當官方收；"
        "C-5低點＝收盤不破45398，還是如果句。"
        "周四／周五夜盤才查46767，不是9/16日盤。"
    )
    if not ymd or ymd < "20260917":
        return (
            "他自己點的日曆：還在等 9/16 Fed（9/15～9/16 利率決策），不是看新聞做股票。"
            + dual
            + "9/4：目前影響股市最大因素是 FED 是否升息。"
            "9/7 樓下：指標龍頭要有效過前高再拉一波，等 9/16 以後可能性較大。"
            "9/8：沒升息則已在新史新高的個股理應再表態；到時還在高檔震盪就積極調節、找新標的。"
            "真正下一波主流要下星期才能確認。升息結果不准編"
        )
    bits = [
        "他自己點的 9/16 Fed 已過。升息有沒有這顆庫沒這列，不准編新聞",
        dual,
        "回撤他的如果／就：沒升息→新高檔理應再表態；還在高檔震盪→積極調節",
    ]
    tape = _new_high_retract(db_path)
    if tape:
        bits.append(tape)
    return "。".join(bits)


def _overnight_bit(label: str, pct: Any, as_of: str, twii_ymd: str, miss_key: str) -> str:
    ymd = str(as_of or "")
    if pct is None:
        return f"{label}官方這顆庫還沒這列，{miss_key}，不准編"
    chg = _chg(pct)
    if twii_ymd and ymd and ymd < twii_ymd:
        return (
            f"{label}隔夜官方 {ymd} {chg}；還沒對上最新加權日 {twii_ymd}，"
            f"{miss_key}、不准編今天的{label}"
        )
    return f"{label}隔夜官方 {ymd} {chg}；沒{label} 15 分不數段、先行不是保證"


def _clip(text: str, n: int) -> str:
    s = " ".join(str(text or "").split())
    return s if len(s) <= n else s[: n - 1] + "…"


# 巢穴 900 字不准把 9/16 晨交叉擠掉。官方柱／日曆可短，這段必留。
_NEST_KEY = (
    "9/16晨：收盤不破45398才是C-5低點確認，還是如果句；未收不當官方。"
    "不到46767≠一定C-3；夜盤不到則C-2可能性高。"
    "頭肩底至少3周（鏡射）才可能主升段；10月中買回測支撐或起漲第一根，不是買訊。"
    "45398≠45839。"
    "9/15夜：築底是形態蓄積過下降壓，不是已表態過線；高檔震盪沒表態可能性較大。"
    "周四／周五夜盤才查46767，不是9/16日盤；官方夜盤對46506／46767還沒走完。"
    "三個9/16不准混：還在等 9/16 Fed不准編≠奇鋐只能上不能下≠C-5低點45398。不是看新聞做股票。"
    "C-2轉C-3未確認；末端估43500；某商品量價說43500非常難，兩條不准合成。"
    "9波擴延到36000約5%微乎其微，36000≠43500。"
    "三種形態：強勢整理＝拉回淺等時間；破線1～3天站回＝洗盤；爆大量跌破平台＝轉折K。"
    "形態沒爆大量不准升成轉折K。真正有用＝波浪／形態／量價／關鍵K（碎形）。"
    "個股不數5／9。覆巢之下無完卵；確認要四路對質。"
)


def _fit_nest(body: str, extra: str = "") -> str:
    """交叉鑰放最前，官方必留句次之，他自己最新最後；不准從尾巴把鑰裁掉。"""
    key = _NEST_KEY
    extra = _clip(str(extra or "").strip(), 140)
    core = str(body or "")
    if key in core:
        core = core.replace(key, "").strip(" 。")
    core = re.sub(r"他的說法：.*", "", core).strip(" 。")
    must_need = ("45839", "47578", "費半", "那指", "9/16", "官方加權", "台積電官方")
    must: List[str] = []
    rest: List[str] = []
    for sent in core.split("。"):
        s = sent.strip()
        if not s:
            continue
        if any(k in s for k in must_need):
            must.append(s)
        else:
            rest.append(s)
    must_t = "。".join(must)
    rest_t = "。".join(rest)
    extra_len = len(extra) + 1 if extra else 0
    key_extra = len(key) + extra_len
    if len(must_t) + key_extra + 2 > 900:
        must_t = _clip(must_t, max(80, 900 - key_extra - 2))
    used = key_extra + (len(must_t) + 1 if must_t else 0)
    room = 900 - used - 2
    rest_t = _clip(rest_t, room) if room > 24 else ""
    return "。".join(p for p in (key, must_t, rest_t, extra) if p)


def _step(nid: str, text: str, *, ok: bool = True, skip: bool = False) -> Dict[str, Any]:
    return {
        "id": nid,
        "title": NEURON_TITLES[nid],
        "ok": bool(ok) and not skip,
        "skip": bool(skip),
        "text": _clip(text, 900),
    }


def _live_bit(bundle: Optional[Dict[str, str]], nid: str, already: str = "") -> str:
    """捕獲後進神經元的最近一句。已在舊材料裡就不重貼。"""
    t = str((bundle or {}).get(nid) or "").strip()
    if not t:
        return ""
    blob = already or ""
    if t in blob or t[:24] in blob:
        return ""
    return "他自己最新：" + t


_NEST_OFFICIAL: Dict[Tuple[str, int], Dict[str, Any]] = {}


def _resolve_sid(db_path: str, ask: str) -> Tuple[str, str]:
    sid = ""
    name = ""
    try:
        from biaoke_brain import is_market_question, resolve_stock

        hits = resolve_stock(db_path, ask) if ask else []
        if is_market_question(ask) and not hits:
            return "", ""
        if hits:
            sid = str(hits[0].get("stock_id") or "")
            name = str(hits[0].get("stock_name") or "")
    except Exception:
        sid, name = "", ""
    if not sid:
        try:
            from biaoke_facts import names_in_ask

            names = names_in_ask(ask)
            if names:
                sid, name = str(names[0][0]), str(names[0][1])
        except Exception:
            sid, name = "", ""
    # 先掛117-117.5、19500~19650 這種價位／點位區間不是股票代號。
    if sid and re.search(
        rf"(?<!\d){re.escape(sid)}\s*[~\-～]\s*\d", ask or ""
    ):
        return "", ""
    if sid and re.search(
        rf"\d\s*[~\-～]\s*{re.escape(sid)}(?!\d)", ask or ""
    ):
        return "", ""
    # 他自己點過的大盤水平不是股票代號。
    if sid in {
        "43500",
        "45415",
        "45839",
        "46250",
        "46506",
        "46767",
        "47578",
        "48218",
        "45398",
        "19650",
        "19844",
        "19250",
        "36000",
    }:
        return "", ""
    return sid, name


def _nest_compute(db_path: str) -> Dict[str, Any]:
    bits: List[str] = []
    ok = False
    twii_ymd = ""
    try:
        from biaoke_wave import format_wave_head

        head = format_wave_head(db_path)
        if head:
            bits.append(head)
    except Exception:
        pass
    try:
        from biaoke_brain import load_index_bars

        bars = load_index_bars(db_path, n=8) if db_path else []
        cap = ""
        try:
            from import_health import latest_complete_quote_date

            cap = str(latest_complete_quote_date(db_path) or "").replace("-", "")[:8]
        except Exception:
            cap = ""
        if cap:
            bars = [
                b
                for b in bars
                if str(b.get("date") or "").replace("-", "")[:8] <= cap
            ]
        if bars:
            last = bars[-1]
            twii_ymd = str(last.get("date") or "").replace("-", "")[:8]
            bits.append(
                f"官方加權 {last.get('date') or ''} 收 {_px(last.get('close')) or '—'} "
                f"高 {_px(last.get('high')) or '—'} 低 {_px(last.get('low')) or '—'}"
            )
            ok = True
            try:
                close = float(last.get("close") or 0)
            except (TypeError, ValueError):
                close = 0.0
            if close >= 45839:
                bits.append(
                    f"官方收 {_px(close)} 還在他自己點的 9/3 低 45839 之上，"
                    "右肩低先當沒破，不是已確認末端"
                )
            elif close > 0:
                bits.append(
                    f"官方收 {_px(close)} 已低於他自己點的 9/3 低 45839，覆巢先當有事"
                )
            try:
                hi = float(last.get("high") or 0)
            except (TypeError, ValueError):
                hi = 0.0
            if hi >= 47578:
                bits.append(
                    f"官方高 {_px(hi)} 已過他自己點的前波高 47578，才比較像維持右肩"
                )
            elif hi > 0:
                bits.append(
                    f"官方高 {_px(hi)} 還沒過他自己點的前波高 47578，右肩還沒做完"
                )
            lows: List[float] = []
            for b in bars[-3:]:
                try:
                    v = float(b.get("low") or 0)
                except (TypeError, ValueError):
                    v = 0.0
                if v > 0:
                    lows.append(v)
            three_low = min(lows) if lows else 0.0
            if three_low > 0:
                bits.append(
                    f"官方3日低 {_px(three_low)}對C-5線45398，未收不當官方"
                )
        else:
            bits.append("官方加權這顆庫還沒這列，不准自己寫點位")
    except Exception:
        bits.append("官方加權讀不到，不准編")
    try:
        from taiwan_market import load_futures_daily, load_futures_night

        tx = load_futures_daily(db_path) if db_path else None
        if tx:
            bits.append(
                f"台指期日盤 {tx.get('date') or ''} 收 {_px(tx.get('close')) or '—'} "
                f"高 {_px(tx.get('high')) or '—'} 低 {_px(tx.get('low')) or '—'}"
            )
            ok = True
        night = load_futures_night(db_path) if db_path else None
        if night:
            bits.append(
                f"夜盤 {night.get('date') or ''} 收 {_px(night.get('close')) or '—'} "
                f"高 {_px(night.get('high')) or '—'} 低 {_px(night.get('low')) or '—'}；"
                "有官方柱也只報高低，不數段"
            )
            try:
                night_hi = float(night.get("high") or 0)
            except (TypeError, ValueError):
                night_hi = 0.0
            if night_hi > 0:
                if night_hi >= 46767:
                    bits.append(
                        f"夜盤高 {_px(night_hi)} 已過他自己點的 46767；"
                        "築底過線仍要四路對質，不准單靠這一價"
                    )
                else:
                    bits.append(
                        f"夜盤高 {_px(night_hi)} 還沒過他自己點的 46767；"
                        "周四／周五夜盤才是檢查日，不是9/16日盤"
                    )
                if night_hi >= 46506:
                    bits.append(
                        f"夜盤高 {_px(night_hi)} 已過他自己點的 46506；"
                        "確認末端還要四路對質，不准單靠這一價"
                    )
                else:
                    bits.append(
                        f"夜盤高 {_px(night_hi)} 還沒過他自己點的 46506"
                    )
    except Exception:
        pass
    try:
        from biaoke_brain import load_bars, volume_first_price

        tsmc = load_bars(db_path, "2330", n=50) if db_path else []
        st = volume_first_price(tsmc) if len(tsmc) >= 8 else {}
        if st.get("close") is not None and st.get("spike_high") is not None:
            bits.append(
                f"台積電官方日K {st.get('date') or ''} 收 {_px(st.get('close'))} "
                f"爆量日高 {_px(st.get('spike_high'))}＝壓、低 {_px(st.get('spike_low'))}＝撐，"
                f"站上撐={st.get('above_support')} 過壓={st.get('broke_resistance')}；"
                "只報量價，不數這檔段、不是個股買訊"
            )
    except Exception:
        pass
    us = _latest_us_overnight(db_path)
    as_of = str(us.get("as_of") or "")
    bits.append(
        _overnight_bit("費半", us.get("sox_pct"), as_of, twii_ymd, "費半這路先當缺")
        if "sox_pct" in us
        else "費半官方這顆庫還沒這列，四路先缺這路，不准編"
    )
    bits.append(
        _overnight_bit("那指", us.get("ixic_pct"), as_of, twii_ymd, "那指這路先當缺")
        if "ixic_pct" in us
        else "那指官方這顆庫還沒這列，那指這路先當缺、不准編"
    )
    cal = _pointed_calendar(db_path, twii_ymd)
    if cal:
        if "還在等 9/16" in cal:
            bits.append(
                "他自己點的日曆：還在等 9/16 Fed，不是看新聞做股票。升息結果不准編。"
            )
        else:
            bits.append(cal)
    body = "。".join(b.rstrip("。") for b in bits if b)
    out = _step("nest", _fit_nest(body), ok=ok)
    return out


def _nest(db_path: str, ask: str) -> Dict[str, Any]:
    tick = int(time.time()) // 60
    key = (str(db_path or ""), tick)
    core = _NEST_OFFICIAL.get(key)
    if core is None:
        core = _nest_compute(db_path)
        _NEST_OFFICIAL.clear()
        _NEST_OFFICIAL[key] = core
    text = str(core.get("text") or "")
    if not any(
        x in (ask or "")
        for x in (
            "45839",
            "46506",
            "右肩",
            "細微波",
            "波浪",
            "大盤",
            "夜盤",
            "46767",
            "築底",
            "43500",
            "C-2",
            "逃命波",
            "碎形",
            "關鍵K",
            "36000",
            "9波",
            "橫台",
            "洗盤",
            "只能上不能下",
            "周四",
            "Fed",
            "C-5",
            "45398",
            "頭肩底",
            "鏡射",
            "10月中",
        )
    ):
        return core
    extra = "大盤位階用他自己點過的 45839／46506／48218／46767／45398，禁止 17000。"
    out = dict(core)
    out["text"] = _fit_nest(text + "。" + extra)
    return out


def _field(ask: str, brief: Dict[str, Any]) -> Dict[str, Any]:
    """第 2 顆只講產業／主戰場。長抱 vs 進出留給第 5 顆，不准兩顆各貼一次。"""
    bits: List[str] = []
    sid = str(brief.get("sid") or "")
    named = bool(sid)
    want_trend = any(
        k in (ask or "")
        for k in (
            "產業趨勢",
            "主戰場",
            "篤定",
            "抱到明年",
            "抄底",
            "為什麼",
            "為何",
            "趨勢還在",
            "去年年底",
            "年底",
            "散熱",
            "光通訊",
            "下飄旗",
            "破線",
            "Apple",
            "光學",
            "殺低",
            "末端",
            "CPO",
            "FAU",
            "上詮",
            "碎形",
            "關鍵K",
            "裸K",
            "築底",
            "散熱轉弱",
        )
    )
    if named:
        bits.append("個股最重要是產業趨勢還在不在；技術分析最有用在大盤。")
        try:
            from biaoke_foresight import field_line

            fl = field_line(sid)
            if fl:
                bits.append(fl)
        except Exception:
            pass
        try:
            from biaoke_foresight import battle_line

            bl = battle_line(sid)
            if bl:
                bits.append(bl)
        except Exception:
            pass
        if sid == "2383":
            bits.append(
                "純 AI 他看到台光電護城河最高，至少可抱到 2027 年大盤第五波結束；"
                "這條第五波他改口過，9/11 沒標這級第 1 浪起點，不准編死。"
                "2026-09-15 10:41：CCL 是前一波漲勢最後倒的，當然要整理比較久；AI 關鍵材料 InP 在前、CCL 在後。"
                "09:27：一直都在支撐＝超強整理。12:24：漲太多又最後跌，拉回淺，整理時間要等。"
                "12:30：想起 2024 年 9 月光聖非常強勢的整理，應該再整理 2 個月又有大行情。"
                "10:28：台光電先不用管。13:37：強勢整理＝漲幅超大、拉回沒到正常修正，只是等待時間長。"
            )
        elif sid == "3081":
            bits.append(
                "下一個台光電他最看好聯亞及建築兩檔；聯亞＝矽光子風向球，不是再找一檔 CCL。"
                "建築兩檔沒點名代號。"
                "2026-09-14：InP 龍頭回到次級四浪、中期支撐區，中線多頭結構未破壞。"
                "2026-09-15 10:24 樓下：InP 族還強，龍頭聯亞做下飄旗型強力洗盤，不能保證 100%。"
                "10:41：AI 關鍵材料最重要 InP，再來 CCL。"
            )
        elif sid == "3105":
            bits.append(
                "2026-09-15 09:45 樓下：穩懋昨天跌破支撐立刻站回，細微觀察近期會比台達電強。"
                "InP 族跟漲先看聯亞。IET＝IET-KY 4971。"
            )
        elif sid == "4971":
            bits.append(
                "IET＝IET-KY 4971。2026-09-15 10:24 樓下 InP 族還強，跟漲先看龍頭聯亞。"
                "10:30：IET 做 abc 修正，昨天破線目前又站回支撐，尾盤才能確定。"
                "不能保證 100%。官方 20260914 收 531。"
            )
        elif sid == "3653":
            bits.append(
                "散熱轉弱由健策關鍵K確認不是新聞。"
                "官方 3653 20260915 開 5735 高 5765 低 5240 收 5310 量 2469："
                "爆大量跌破平台＝轉折K、多頭量價破壞；籌碼交換至少 2 周；假跌破過幾天才知道。"
                "噴出去才確認大盤不會 C 波下殺 43500 的那句還沒改口，難操作跟確認噴是兩件事。"
            )
        elif sid == "3017":
            bits.append(
                "不看月線。2026-09-15 14:52：奇鋐走到技術分析模糊地帶；"
                "明天只能上不能下（明天＝9/16，盤中未收不當官方收），再下去拉長整理、對大盤是不好的訊號。"
                "夜：因健策轉折K盤中調奇鋐 1/2。官方 3017 收 3115。"
                "模糊≠轉折K；不准用2天漲1000把這檔說回去。"
            )
        elif sid == "3443":
            bits.append(
                "ASIC 風向球，9/14 取代旺矽。9/15 主文：創意從細微處觀察是目前台股精神指標，如同去年旺矽、台光電。"
                "10:49：創意只是波動。散熱轉弱後資金轉來，但風險大；止漲整理K 一定調節。"
                "官方 3443 20260915 收 6035＝當日低，還沒連續漲勢，不能說不會下殺 43500。"
            )
        elif sid in ("3363", "3163", "6442"):
            bits.append(
                "CPO／FAU ≠ InP。9/15：上詮、波若威、光聖／合聖是 CPO／FAU；聯亞才是 InP。"
                "合聖這顆庫沒這列。上詮回測頸線、還在底部整理、光通訊僅次 InP。"
                "跟漲先看上詮形態，不准把聯亞當這族龍頭。官方 3363 20260915 收 648。"
            )
        elif sid == "2368":
            bits.append(
                "PCB 長期趨勢向上、目前底部整理；金像電、台燿同一套。"
                "3 個月回來看一定反彈一大段；會不會測前高主力也不敢保證。"
                "官方 20260915 金像電收 972。"
            )
        elif sid == "6274":
            bits.append(
                "PCB 長期趨勢向上、目前底部整理。官方 20260915 台燿收 1370。"
                "10:39：台燿就是要等台光電表態，一定還會再創高，只是不是主力、無法知道何時發動。"
            )
        elif sid == "6683":
            bits.append(
                "2026-09-15 09:23：高階測試二軍雍智已經整理完成。"
                "跟漲先看一軍旺矽、穎崴，應該就是時間問題。不是轉折K。"
            )
        elif sid == "6510":
            bits.append(
                "2026-09-15 09:23：精測之前也完成、目前進行回測洗盤。"
                "高階測試二軍；一軍旺矽、穎崴時間問題。IET＝IET-KY 4971 不是這族。"
            )
        elif sid in ("6223", "6515"):
            bits.append(
                "2026-09-15 09:23：高階測試一軍旺矽、穎崴應該就是時間問題。"
                "穎崴 7/24 出清過，不准用沒破線續抱改寫。"
            )
        elif sid == "1815":
            bits.append(
                "2026-09-14：富喬再度回到支撐區。"
                "2026-09-15 13:49：前波低點沒破，正常修正。"
                "14:44：有可能初升段走完、目前進入 2 整理，多頭沒破，比南亞科／記憶體強太多。"
            )
        elif sid == "2454":
            bits.append(
                "2026-04-22 公開 IC 設計主線點創意、力旺、世芯，當天沒點發哥；5 月起當平台龍頭。"
                "產業還在不在留給這顆，長抱名單留給第 5 顆。"
            )
    if want_trend:
        try:
            from biaoke_mind import match_methods

            for title, body in match_methods(ask, limit=3):
                if title in (
                    "個股先看產業趨勢",
                    "去年年底",
                    "9/10 主戰場",
                    "9/14 指數末端",
                    "9/15夜思考",
                    "真正有用的五件",
                ):
                    bits.append(_clip(body, 280))
        except Exception:
            pass
    ind = str(brief.get("industry") or "")
    rot = str(brief.get("rotation") or "")
    if rot:
        bits.append(rot)
    elif ind:
        bits.append("這檔產業 " + ind)
    if named:
        return _step("field", " ".join(bits), ok=True)
    if bits:
        return _step("field", " ".join(bits), ok=True)
    bits.append("這句沒點檔，產業先擱；大盤仍用第 1 顆。")
    return _step("field", " ".join(bits), skip=True)


def _leader(brief: Dict[str, Any], *, named: bool) -> Dict[str, Any]:
    if not named:
        return _step("leader", "這句沒點檔，不套個股龍頭。", skip=True)
    leader = brief.get("leader") or {}
    lid = str(leader.get("sid") or "")
    if not lid:
        return _step("leader", "沒對上這族龍頭，跟漲沒指引，不能裝這族剛起漲。", ok=False)
    ls = leader.get("struct") or {}
    why = str(leader.get("why") or "同族跟漲先看龍頭")
    name = str(leader.get("name") or "")
    self_sid = str(brief.get("sid") or "")
    view = _view_line("leader", n=140)
    if lid == self_sid:
        if ls:
            bit = f"{lid} {name}（{why}）。跟漲不另對一檔，這檔官方量價留給第 4 顆。"
            if view:
                bit += " " + view
            return _step("leader", bit, ok=True)
        bit = f"{lid} {name}（{why}）。自己就是龍頭，但官方 K 還沒齊，攻或休先不講。"
        if view:
            bit += " " + view
        return _step("leader", bit, ok=False)
    bit = f"{lid} {name}（{why}）"
    if ls:
        bit += (
            f" 收 {_px(ls.get('close')) or '—'}"
            f" 爆量日 {ls.get('spike_date') or '—'}"
            f" 高 {_px(ls.get('spike_high')) or '—'} 低 {_px(ls.get('spike_low')) or '—'}"
            f" 站上撐={ls.get('above_support')} 過壓={ls.get('broke_resistance')} 量縮={ls.get('shrinking')}"
        )
        if view:
            bit += " " + view
        return _step("leader", bit, ok=True)
    bit += " 龍頭官方 K 還沒齊，跟漲對不上"
    if view:
        bit += " " + view
    return _step("leader", bit, ok=False)


def _tape(brief: Dict[str, Any], *, named: bool, db_path: str = "") -> Dict[str, Any]:
    """第 4 顆只講這檔官方量價與圖上演算。產業資金在第 2 顆，長抱／半山腰在第 5 顆。"""
    if not named:
        return _step("tape", "這句沒點檔，不畫個股量價、不數這檔波浪。", skip=True)
    st = brief.get("struct") or {}
    sid = str(brief.get("sid") or "")
    if not st:
        bit = "官方日 K 量價還不夠。沒有爆大量日高低就不能講壓撐，不准編。"
        if sid:
            try:
                from biaoke_charts import format_charts_vs_official

                seen = format_charts_vs_official(sid, db_path, hold=False, limit=3)
                if seen:
                    bit += " " + seen
            except Exception:
                pass
            try:
                from biaoke_chrono import line_for as chrono_line

                ch = chrono_line(sid)
                if ch:
                    bit += " " + ch
            except Exception:
                pass
            try:
                from biaoke_tape import glance_for

                filed = glance_for(db_path, sid)
                if filed:
                    bit += " " + filed
            except Exception:
                pass
            try:
                from biaoke_forecast import glance_forecast

                fc = glance_forecast(db_path, sid)
                if fc:
                    bit += " " + fc
            except Exception:
                pass
        return _step("tape", bit, ok=False)
    bit = (
        f"{brief.get('sid')} {brief.get('name') or ''} "
        f"{st.get('date') or ''} 收 {_px(st.get('close')) or '—'}。"
        f"量先價行：爆大量日 {st.get('spike_date') or ''} "
        f"高 {_px(st.get('spike_high')) or '—'}＝壓、"
        f"低 {_px(st.get('spike_low')) or '—'}＝撐；"
        f"站上撐={st.get('above_support')} 過壓={st.get('broke_resistance')} 量縮={st.get('shrinking')}。"
        "站上撐後等價穩量縮才像進，收在低下先放棄。個股不數 5／9 段。"
    )
    sid = str(brief.get("sid") or "")
    if db_path and sid:
        try:
            from biaoke_brain import load_bars
            from biaoke_chart import analyze_structure

            bars = load_bars(db_path, sid, n=80)
            if len(bars) >= 8:
                proj = (analyze_structure(bars[-60:]) or {}).get("project") or {}
                label = str(proj.get("label") or "").strip()
                if label:
                    bit += " 圖上演算：" + label
        except Exception:
            pass
    if sid:
        try:
            from biaoke_charts import format_charts_vs_official

            seen = format_charts_vs_official(sid, db_path, hold=False, limit=3)
            if seen:
                bit += " " + seen
        except Exception:
            pass
        try:
            from biaoke_chrono import line_for as chrono_line

            ch = chrono_line(sid)
            if ch:
                bit += " " + ch
        except Exception:
            pass
    if db_path and sid:
        try:
            from biaoke_tape import glance_for

            filed = glance_for(db_path, sid)
            if filed:
                bit += " " + filed
        except Exception:
            pass
        try:
            from biaoke_forecast import glance_forecast

            fc = glance_forecast(db_path, sid)
            if fc:
                bit += " " + fc
        except Exception:
            pass
    view = _view_line("tape", n=140)
    if view:
        bit += " " + view
    return _step("tape", bit, ok=True)


def _hold(brief: Dict[str, Any], ask: str, *, named: bool, db_path: str = "", uid: str = "") -> Dict[str, Any]:
    if not named:
        try:
            from biaoke_mind import match_methods

            picked = match_methods(ask, limit=4)
            by = {t: b for t, b in picked}
            for title in (
                "能長抱的產業鏈",
                "長抱主流／F4→F10／聯發科",
                "南亞 1303 長抱或進出",
                "洞燭先機",
            ):
                if title in by:
                    return _step("hold", by[title], ok=True)
            for title, body in picked:
                if str(title).startswith("圖文時間軸"):
                    return _step("hold", body, ok=True)
        except Exception:
            pass
        if any(
            k in (ask or "")
            for k in (
                "F10",
                "F4",
                "長抱",
                "抱到明年",
                "聯發科",
                "抱著波段",
                "南亞",
                "1303",
                "洞燭",
                "先機",
                "汎銓",
                "很少人提",
                "台塑",
                "無人機",
                "倒了",
                "CoWoS",
                "賣設備",
                "過路費",
                "AI時代",
                "圖文時間軸",
                "智原",
                "萬海",
                "華碩",
                "廣達",
                "做頭",
                "台通",
                "頎邦",
                "光聖",
                "19250",
                "鴻海",
                "樺漢",
                "最後上車",
                "多空支撐線",
                "144-145",
                "反壓區",
                "洗到282",
                "必過400",
                "站穩300",
                "不可能像鴻海",
                "四月下旬",
                "苦盡甘來",
                "至少還有20%",
                "真的非常強",
                "長下引線",
                "下星期要噴出",
                "下星期上半週就可以站穩",
                "賺了幾%",
                "波段漲勢確認",
                "轉成支撐線",
                "測前高161.5",
                "整理半年",
                "多空分界",
                "289.5-291",
                "站在291",
                "回測109",
                "先測124",
                "三成獲利",
                "多方最低標準282",
                "多空廝殺激烈",
                "昨天說的今天還是適用",
                "挑戰前高298",
                "放假前就到了",
                "回測114-114.5",
                "去年兩個高點壓力線",
                "回測365",
                "測350",
                "350應該守得住",
                "6117上車",
                "建立所有部位持股",
                "最小漲幅目標價是810",
                "目標價9XX",
                "漲得較慢",
                "急殺買",
                "今天早盤應該是低點",
                "剛好止漲回測",
                "先買1/2",
                "明或後天再加碼",
                "美超微機殼",
                "收大黑K",
                "最佳上車時機",
                "會影響到迎廣走勢",
                "剛公佈的業績",
                "有哪位高手可解惑",
                "支撐線沿著5日均線",
                "10日均線撐住",
                "單純以技術面來說",
                "讓佳能跑掉漲停",
                "第二選擇協易機",
                "找拉回上車時機",
                "雷科雖然被關",
                "第二階段型態目標價",
                "第三階段型態極限目標價",
                "抱到7-8月",
                "支撐線不是282",
                "還原權值K線",
                "從K線量價結構",
                "上車最佳時機",
                "今天應該是上車",
                "上星期五中午我說的上車時間",
                "挑戰歷史高點85.2",
                "洗個1-3天",
                "回測5MA支撐線",
                "不用賣",
                "空手上車時間",
                "這兩檔列入鎖股",
                "協易機爆大量",
                "已經賣了",
                "早盤在37.4",
                "今日10點之前多空交界區",
                "先買一半",
                "先掛117-117.5",
                "兩個價位",
                "先買1/3",
                "打到頸線56.5",
                "第一次不太可能直接跌破",
                "以上是雷科操作的技術分析",
                "直探19650",
                "星期四前就會來",
                "19650會測兩次",
                "19500~19650",
                "缺口至頸線區間",
                "櫃買指數技術分析",
                "我沒有弘塑",
                "也會過前高",
                "也會過前高64.5",
                "漲停過前高",
                "對 CoWos",
                "對CoWos族群具有指標性",
                "台指期夜盤",
                "最多打到19650",
                "破19844",
                "留下影線",
                "昨天漲300多點",
                "黃培碩",
                "18752-19012",
                "18752",
                "3-3浪走擴延",
                "技術分析班課程",
                "兩階段跌幅滿足",
                "成本230不會再買",
                "優先佈局金像電",
                "滿足是350",
                "小時線站上119",
                "漲勢確認爲下一波主流",
                "6669我比較看好",
                "機殼8210持續看好",
                "先以跌深反談",
                "站上289以上",
                "過前高323",
                "型態滿足目標價會過前高323",
                "二月份有操作這檔股票",
                "行進中上車短線買點",
                "第二階段目標價到了就會賣掉",
                "含成本不到48",
                "3234被處置",
                "換確認不是假突破的6442",
                "不是假突破的6442",
            )
        ):
            try:
                from biaoke_mind import match_methods

                picked = match_methods(ask, limit=4)
                by = {t: b for t, b in picked}
                for title in (
                    "能長抱的產業鏈",
                    "長抱主流／F4→F10／聯發科",
                    "南亞 1303 長抱或進出",
                    "洞燭先機",
                ):
                    if title in by:
                        return _step("hold", by[title], ok=True)
            except Exception:
                pass
        return _step("hold", "這句沒點檔，長抱／進出不套死某一檔。", skip=True)
    hold = str(brief.get("hold") or "")
    pace = str(brief.get("pace") or "")
    sid = str(brief.get("sid") or "")
    bits: List[str] = []
    if hold:
        bits.append(hold)
    elif sid == "2454":
        bits.append("聯發科不是 4/16 可抱到明年名單。")
    else:
        bits.append("不是 4/16 長抱名單時，這腳量價只當進出，不要偷換成可抱到明年。")
    if brief.get("long_hold") and "半山腰" in pace:
        bits.append("量價過壓是半山腰那套；長抱另論，不要用過壓叫人出長抱。")
    elif "半山腰" in pace:
        bits.append("已過爆大量日高，這腳進出比較像半山腰，不是落後補漲。")
    mine = _own_holding(db_path, uid, sid)
    if mine:
        bits.append("這人持股有這檔，長抱／進出對這倉看，不准改別人倉。")
    if sid:
        try:
            from biaoke_charts import format_charts_vs_official

            seen = format_charts_vs_official(sid, db_path, hold=True, limit=2)
            if seen:
                bits.append(seen)
        except Exception:
            pass
        try:
            from biaoke_chrono import line_for as chrono_line

            ch = chrono_line(sid)
            if ch:
                bits.append(ch)
        except Exception:
            pass
    if sid == "2383":
        bits.append(
            "9/15：台光電先不用管；一直都在支撐＝超強整理，拉回淺所以整理時間要等。"
            "想起 2024/9 光聖非常強勢的整理，應該再整理 2 個月。不是轉折K。"
        )
    elif sid == "3653":
        bits.append(
            "9/15 爆大量跌破平台＝轉折K確認；籌碼交換至少 2 周。"
            "假跌破過幾天。止漲整理K 才調節。"
        )
    elif sid == "3017":
        bits.append(
            "不看月線。因健策轉折K盤中調 1/2。"
            "9/16 只能上不能下是大盤碎形窗，盤中未收不當官方；下去才拉長整理。"
            "模糊≠轉折K，不准套2天漲1000續抱。"
        )
    elif sid == "3443":
        bits.append("散熱資金轉來風險大；止漲整理K 一定調節。還沒連續漲勢。")
    elif sid in ("3363", "3163", "6442"):
        bits.append("CPO／FAU 還在底部／回測頸線；沒破線續抱。合聖沒這列。")
    elif sid == "6683":
        bits.append("09:23：二軍整理完成；跟漲先看一軍時間問題。不是轉折K。")
    elif sid == "6510":
        bits.append("09:23：回測洗盤。不是轉折K，也不是C波出清。")
    elif sid in ("6223", "6515"):
        bits.append("09:23：一軍時間問題。穎崴 7/24 出清過，不准用沒破線續抱改寫。")
    elif sid == "6274":
        bits.append("等台光電表態才知何時創高；自己還在底部。")
    view = _view_line("hold", n=150)
    if view:
        bits.append(view)
    return _step("hold", " ".join(bits), ok=bool(hold or sid))


def _doubt(brief: Dict[str, Any], nest_ok: bool, *, named: bool, nest_text: str = "") -> Dict[str, Any]:
    audit = brief.get("audit") or {}
    miss = [str(x) for x in (audit.get("miss") or [])]
    ok_bits = [str(x) for x in (audit.get("ok") or [])]
    bits: List[str] = []
    extra_miss: List[str] = []
    nt = nest_text or ""
    if not nest_ok:
        bits.append("大盤官方點位沒齊，確認末端不准講死")
    if "費半這路先當缺" in nt or "四路先缺這路" in nt:
        extra_miss.append("費半這路官方沒跟上最新加權日，四路沒疊滿")
    if "那指這路先當缺" in nt:
        extra_miss.append("那指隔夜官方沒跟上最新加權日")
    if "還在等 9/16" in nt:
        extra_miss.append("他自己點的 9/16 Fed 還沒到，下一波主流不准裝已確認")
    if named:
        try:
            from biaoke_foresight import doubt_line

            dl = doubt_line(str(brief.get("sid") or ""))
            if dl:
                bits.append(dl)
        except Exception:
            pass
    if named and not brief.get("in_corpus"):
        bits.append("公開文沒點名這檔，只是觸類旁通量價，可能看錯")
    if named and miss:
        bits.extend(miss[:4])
    bits.extend(extra_miss)
    if named and ok_bits:
        bits.append("已疊：" + "、".join(ok_bits[:4]))
    if audit.get("verdict"):
        bits.append(str(audit.get("verdict")))
    view = _view_line("doubt", n=140)
    if view:
        bits.append(view)
    if not bits:
        bits.append("沒疊滿就不講死。對跟錯一起留。這不是買訊。")
    return _step("doubt", " ".join(bits), ok=not miss and not extra_miss)


def _five_cross(steps: List[Dict[str, Any]], sid: str, name: str = "") -> str:
    """五件交叉：波浪／形態／量價／關鍵K／碎形對質，不是六顆各貼一句。

    新啟發只從交叉來：大盤築底×個股轉折K＝輪動不是覆巢；同族轉折K＝跟漲先調節。
    """
    by = {str(s.get("id") or ""): s for s in steps}

    def _core(raw: str) -> str:
        return re.sub(r"他的說法：.*", "", str(raw or ""))

    nest = _core((by.get("nest") or {}).get("text") or "")
    field = _core((by.get("field") or {}).get("text") or "")
    leader = _core((by.get("leader") or {}).get("text") or "")
    tape = _core((by.get("tape") or {}).get("text") or "")
    hold = _core((by.get("hold") or {}).get("text") or "")
    fh = field + hold
    nest_build = any(k in nest for k in ("築底", "蓄積過下降壓", "46767"))
    nest_cover = "覆巢先當有事" in nest or "已低於他自己點的 9/3 低 45839" in nest
    nest_c3 = "C-3" in nest or "C-2" in nest
    own_keyk = any(
        k in tape
        for k in ("轉折K", "爆大量跌破平台", "爆大量破平台", "確認出現轉折")
    )
    shown = str(name or "")
    if shown and re.search(rf"{re.escape(shown)}.{{0,16}}轉折", fh):
        own_keyk = True
    if sid == "3653" and "轉折K" in (fh + tape):
        own_keyk = True
    sib_keyk = (not own_keyk) and bool(
        re.search(r"(因.{0,6}轉折K|健策轉折K|龍頭.{0,8}轉折)", fh)
        or (sid != "3653" and "轉折K" in fh and "健策" in fh)
    )
    wash = (not own_keyk) and any(
        k in (tape + fh)
        for k in (
            "重新站回支撐",
            "立刻站回",
            "站回支撐",
            "下飄旗",
            "1~3天又站回",
            "隔個1~3天又站回",
            "回測洗盤",
        )
    )
    strong = (not own_keyk) and (not wash) and any(
        k in (tape + fh)
        for k in ("強勢整理", "超強整理", "拉回淺", "再整理2個月", "一直都在支撐")
    )
    stopk = "止漲整理" in (fh + tape)
    # 這檔形態才算。CCL 龍頭句裡「很多 PCB 還在底部」不是台光電自己回測頸線。
    neck = "回測頸線" in fh or "目前就是在底部" in fh
    sold = any(k in hold for k in ("出清", "不要再布局"))
    longh = (not sold) and any(k in hold for k in ("勿輕易調節", "先不用管", "沒破線", "續抱"))
    waitime = (not own_keyk) and any(
        k in (fh + tape) for k in ("時間問題", "整理完成")
    )
    follow_emc = "等台光電表態" in fh
    fuzzy = (not own_keyk) and any(
        k in fh for k in ("只能上不能下", "模糊地帶", "技術分析模糊")
    )
    night_short = ("還沒過" in nest) and any(k in nest for k in ("46506", "46767"))
    if not sid:
        bits: List[str] = []
        if nest_build and nest_c3:
            bits.append(
                "五件交叉：夜盤築底是形態蓄積，C-2轉C-3仍是如果句，兩條不准合成已確認末端。"
            )
        elif nest_c3:
            bits.append("五件交叉：C-2轉C-3未確認，不是個股出清指令。")
        if "C-5" in nest or "45398" in nest:
            bits.append(
                "五件交叉：收盤不破45398才是C-5低點確認，還是如果句；未收不當官方，不是已確認C-5，也不是主升段。"
            )
            bits.append("45398≠45839：C-5確認線不是右肩低。")
        if "不到46767" in nest or "≠一定C-3" in nest or "一定C-3" in nest:
            bits.append("不到46767≠一定C-3；夜盤不到則C-2可能性高。")
        if "頭肩底至少3周" in nest or "鏡射" in nest:
            bits.append(
                "即使化解C波，頭肩底至少3周（鏡射）才可能主升段；"
                "10月中買回測支撐或起漲第一根，不是買訊。"
            )
        if night_short or ("46767" in nest and "築底" in nest):
            bits.append("官方夜盤還沒到他自己點的46767，築底不是已過下降壓。")
        if "不是9/16日盤" in nest or "周四" in nest:
            bits.append("周四／周五夜盤才查46767，不是9/16日盤。")
        if "三個9/16" in nest:
            bits.append(
                "三個9/16不准混：Fed升息結果不准編，奇鋐只能上不能下盤中未收不當官方，"
                "C-5低點45398也未收不當官方。"
            )
        elif "兩個9/16" in nest or "只能上不能下" in nest:
            bits.append("兩個9/16不准混：Fed升息結果不准編，奇鋐只能上不能下盤中未收不當官方。")
        if "36000" in nest:
            bits.append("36000是9波擴延極差、約5%微乎其微，不准跟43500混成一條C。")
        if "沒表態" in nest or "高檔震盪" in nest:
            bits.append("大盤沒表態＝高檔震盪整理，築底不是已開牌過下降壓。")
        if "形態沒爆大量" in nest:
            bits.append("形態沒爆大量不准升成轉折K。")
        if "43500" in nest and ("難" in nest or "非常難" in nest):
            bits.append("某商品量價說43500難破，不是官方收。")
        bits.append("個股不數5／9。")
        return "".join(bits)
    prefix = ""
    if nest_cover:
        prefix = "日K收已低於45839，右肩低先當破；"
    bits = []
    if (nest_build or nest_cover) and own_keyk:
        bits.append(
            prefix
            + "五件交叉：夜盤築底×這檔轉折K＝資金輪動不是覆巢，也不是確認C-3出清。"
        )
        bits.append("碎形：產業轉弱由這檔量價確認，不跟名冊等另一檔龍頭才算。")
        bits.append("形態真破約22%，破線當天不篤定出貨，假跌破過幾天。")
        if "2 周" in (fh + tape) or "2周" in (fh + tape) or sid == "3653":
            bits.append("籌碼交換至少2周，不准用2天漲1000把轉折K說回去。")
    elif (nest_build or nest_cover) and sib_keyk:
        bits.append(
            prefix
            + "五件交叉：同族龍頭已出轉折K，這檔跟漲先當轉弱，即使自己形態模糊。"
        )
        bits.append("這是碎形／關鍵K，不是C波出清。")
        if fuzzy:
            bits.append("9/16只能上不能下是大盤碎形窗，盤中未收不當官方；下去才拉長整理。")
    elif wash:
        bits.append(
            prefix
            + "五件交叉：破線後站回／下飄旗＝洗盤量價，證據不足；不是轉折K，也不是C波出清。"
        )
        if longh:
            bits.append("長抱另論，不要用這腳站回改寫切勿輕易調節。")
    elif strong:
        bits.append(
            prefix
            + "五件交叉：這檔強勢整理＝拉回淺等時間，不是轉折K，也不是C波出清。"
        )
        if longh:
            bits.append("C-3如果句不准改寫成長抱出清。")
        if "光聖" in (fh + leader) or "2個月" in (fh + tape + leader):
            bits.append("想起2024/9光聖，時間換空間。")
    elif follow_emc:
        bits.append(
            prefix
            + "五件交叉：跟漲等這族龍頭台光電表態，自己還在底部，不是轉折K。"
        )
    elif waitime:
        bits.append(
            prefix
            + "五件交叉：二軍整理完成／一軍時間問題，不是轉折K，也不是C波出清。"
        )
        if "出清" in hold:
            bits.append("出清過的檔不准用沒破線續抱改寫。")
        elif "不要再布局" in hold:
            bits.append("已叫不要再布局，不准用沒破線續抱改寫。")
    elif nest_build and neck:
        bits.append(
            prefix
            + "五件交叉：夜盤築底×這檔頸線／底部＝形態還沒轉折K，跟漲先看這族龍頭。"
        )
    elif stopk:
        bits.append(prefix + "五件交叉：止漲整理K是這檔進出規則，不是C波出清。")
        if "還沒連續漲勢" in (fh + leader) or "精神指標" in (fh + leader):
            bits.append("風向球還沒連續漲勢，43500危機沒解除。")
        if nest_build:
            bits.append("夜盤仍在築底，C-3未確認末端。")
    elif (nest_build or nest_cover) and longh and not own_keyk:
        bits.append(
            prefix
            + "五件交叉：這檔沒破線＝續抱；C-3如果句不准改寫成長抱出清。"
        )
    elif nest_build:
        bits.append(
            prefix
            + "五件交叉：夜盤築底、C-2轉C-3未確認；這檔用自己的量價／關鍵K，不准套空sid出清。"
        )
    elif nest_cover:
        bits.append(
            "五件交叉：日K已低於45839，覆巢先當有事；C-3仍未確認，個股仍看自己的關鍵K。"
        )
    else:
        bits.append("五件交叉：波浪／形態／量價／關鍵K還沒疊滿，不講死。")
    return "".join(bits)


def _think(steps: List[Dict[str, Any]], sid: str, name: str) -> str:
    """用他的順序把六顆收成一句推論，不是清單。五件交叉當脊骨。"""
    by = {s["id"]: s for s in steps}
    nest = by.get("nest") or {}
    field = by.get("field") or {}
    leader = by.get("leader") or {}
    tape = by.get("tape") or {}
    hold = by.get("hold") or {}
    doubt = by.get("doubt") or {}
    if sid:
        parts = [
            f"問的是 {sid} {name}。".strip(),
        ]
        nest_t = str(nest.get("text") or "")
        cross = _five_cross(steps, sid, name)
        if cross:
            parts.append(cross)
        if "45839 之上" in nest_t:
            nest_bit = "大盤官方收還在 45839 之上，右肩低先當沒破"
        elif "已低於他自己點的 9/3 低 45839" in nest_t:
            nest_bit = "大盤官方收已低於 45839，覆巢先當有事"
        else:
            nest_bit = "大盤官方點位有了" if nest.get("ok") else "大盤官方點位還缺，確認末端不准講死"
        if "還在等 9/16" in nest_t:
            nest_bit += "；還在等他自己點的 9/16 Fed"
        elif "9/16 Fed 已過" in nest_t:
            nest_bit += "；他自己點的 9/16 已過，升息結果不准編，用新高檔官方日K回撤"
        live_m = re.search(r"他自己最新：[^。]+", nest_t)
        if live_m:
            nest_bit += "；" + _clip(live_m.group(0), 100)
        if "已過他自己點的 46506" in nest_t:
            nest_bit += "；夜盤高已過 46506，確認仍要四路對質"
        elif "還沒過他自己點的 46506" in nest_t:
            nest_bit += "；夜盤高還沒過 46506"
        elif "46506" in nest_t:
            nest_bit += "；官方夜盤對 46506／46767 還沒走完"
        if "還沒過他自己點的前波高 47578" in nest_t:
            nest_bit += "；官方高還沒過 47578"
        elif "已過他自己點的前波高 47578" in nest_t:
            nest_bit += "；官方高已過 47578"
        if "台積電官方" in nest_t:
            nest_bit += "；台積電官方量價有了"
        if "費半這路先當缺" in nest_t or "四路先缺這路" in nest_t:
            nest_bit += "；費半這路缺官方"
        elif "費半隔夜官方" in nest_t:
            nest_bit += "；費半隔夜有官方"
        if "那指這路先當缺" in nest_t:
            nest_bit += "；那指這路缺官方"
        elif "那指隔夜官方" in nest_t:
            nest_bit += "；那指隔夜有官方"
        if "46767" in nest_t:
            nest_bit += "；周四／周五夜盤反彈至少 46767，不是官方收"
        if "43500 非常難" in nest_t:
            nest_bit += "；某商品量價說 43500 難破，不是已確認"
        if not cross and "波浪／形態／量價／關鍵K" not in nest_bit:
            nest_bit += "；真正有用＝波浪／形態／量價／關鍵K（碎形）"
        parts.append(_clip(nest_bit, 220) + "。")
        parts.append("產業有材料。" if field.get("ok") else "產業材料不夠，不要裝篤定。")
        lead_t = str(leader.get("text") or "")
        if "不另對" in lead_t or "自己就是" in lead_t:
            parts.append("自己就是這族龍頭。")
        elif leader.get("ok"):
            core = re.sub(r"他自己最新：.*", "", lead_t).strip(" 。；")
            head = core.split("（", 1)[0].strip()
            parts.append(f"這族龍頭是 {head}。" if head else "龍頭對得上。")
        else:
            parts.append("龍頭還沒對上。")
        tt = str(tape.get("text") or "")
        if tape.get("ok"):
            close_m = re.search(r"收 ([0-9.]+)", tt)
            press_m = re.search(r"高 ([0-9.]+)＝壓", tt)
            hold_m = re.search(r"低 ([0-9.]+)＝撐", tt)
            if close_m and press_m and hold_m:
                parts.append(
                    f"這檔官方收 {close_m.group(1)}，壓 {press_m.group(1)}、撐 {hold_m.group(1)}。"
                )
            else:
                parts.append("量價有官方柱。")
            if "圖上演算" in tt:
                parts.append("圖上後續只是壓撐＋連點延長演算，不是保證。")
            if "轉折" in tt or "爆大量" in tt or "關鍵K" in tt:
                parts.append("這檔關鍵K／量價已對官方柱。")
        else:
            parts.append("這檔量價還沒齊，不准編壓撐。")
        if hold.get("text"):
            ht = str(hold.get("text") or "")
            core = re.sub(r"他自己最新：[^。]*。?", "", ht)
            core = re.sub(r"他的說法：.*", "", core)
            if "勿輕易調節" in ht:
                core = ("切勿輕易調節。" + core).strip()
            parts.append(_clip(core.strip(" 。；") or ht, 160))
        verdict = str(doubt.get("text") or "")
        if "自問" in verdict:
            parts.append(_clip(verdict[verdict.find("自問") :], 220))
        else:
            parts.append("沒疊滿就不講死。這不是買訊。")
        return _clip("".join(parts), 900)
    nest_t = str(nest.get("text") or "")
    parts = ["這句沒點檔：先把大盤巢穴走完。"]
    if "現在位階" in nest_t:
        m = re.search(r"(現在位階[^。]+)", nest_t)
        if m:
            parts.append(m.group(1).strip() + "。")
    live_m = re.search(r"他自己最新：[^。]+", nest_t)
    if live_m:
        parts.append(_clip(live_m.group(0), 100) + "。")
    if "45839 之上" in nest_t:
        parts.append("官方收還在 45839 之上，右肩低先當沒破。")
    elif "已低於他自己點的 9/3 低 45839" in nest_t:
        parts.append("官方收已低於 45839，覆巢先當有事。")
    if "已過他自己點的 46506" in nest_t:
        parts.append("夜盤高已過 46506，確認仍要四路對質。")
    elif "還沒過他自己點的 46506" in nest_t:
        parts.append("夜盤高還沒過 46506。")
    elif "46506" in nest_t:
        parts.append("官方夜盤對 46506／46767 還沒走完。")
    if "還沒過他自己點的前波高 47578" in nest_t:
        parts.append("官方高還沒過 47578，右肩還沒做完。")
    elif "已過他自己點的前波高 47578" in nest_t:
        parts.append("官方高已過 47578。")
    if "費半這路先當缺" in nest_t or "四路先缺這路" in nest_t:
        parts.append("費半這路缺官方。")
    elif "費半隔夜官方" in nest_t:
        parts.append("費半隔夜有官方。")
    if "那指這路先當缺" in nest_t:
        parts.append("那指這路缺官方。")
    elif "那指隔夜官方" in nest_t:
        parts.append("那指隔夜有官方。")
    cross = _five_cross(steps, "", "")
    if cross:
        parts.append(cross)
    if "還在等 9/16" in nest_t:
        parts.append("還在等他自己點的 9/16 Fed，下一波主流不准裝已確認。")
    elif "9/16 Fed 已過" in nest_t:
        parts.append("他自己點的 9/16 已過，升息結果不准編，用新高檔官方日K回撤。")
    if "個股不數" not in "".join(parts):
        parts.append("個股不數浪。產業／長抱看法每顆都重讀，沒點檔就不套某一檔。真正有用＝波浪／形態／量價／關鍵K（碎形）。")
    return _clip("".join(parts), 560)


_FIRE_CACHE: Dict[Tuple[str, str, str], Tuple[float, Dict[str, Any]]] = {}
_HI_ASK = re.compile(r"^(你好|哈囉|嗨|在嗎|hello)[。！!？\s]*$", re.I)


def format_five_lead(fired: Optional[Dict[str, Any]]) -> str:
    """話筒開口第一句：五件交叉收成一句，並標未收／如果句。"""
    fired = fired or {}
    five = " ".join(str(fired.get("five") or "").split())
    nest = ""
    for step in fired.get("steps") or []:
        if str(step.get("id") or "") == "nest":
            nest = str(step.get("text") or "")
            break
    blob = five + nest + str(fired.get("think") or "")
    core = re.sub(r"五件交叉：", "", five)
    parts = [p.strip() for p in re.split(r"[。]", core) if p.strip()]
    core = "。".join(parts[:2]) if parts else ""
    if not core:
        core = "波浪／形態／量價／關鍵K還沒疊滿，不講死"
    core = _clip(core, 140).rstrip("。…")
    flags: List[str] = []
    if any(k in blob for k in ("如果句", "未確認", "還是如果")):
        flags.append("如果句")
    if any(k in blob for k in ("未收", "不當官方", "還在等 9/16", "盤中未收")):
        flags.append("未收")
    flags.append("不是買訊")
    return core + "。〔" + "／".join(flags) + "〕"


def attach_five_lead(html: str, db_path: str, ask: str, uid: str = "") -> str:
    """回覆最前鎖一句五件結論。已經有開口句就不再貼。"""
    q = (ask or "").strip()
    raw = str(html or "")
    if not q or not raw or _HI_ASK.match(q):
        return raw
    fired = fire_chain(db_path, q, uid=uid)
    lead = format_five_lead(fired)
    if not lead:
        return raw
    plain = re.sub(r"<[^>]+>", "", raw)
    if lead[:18] in plain[:220]:
        return raw
    try:
        from tg_layout import html_escape

        head = html_escape(lead)
    except Exception:
        head = lead
    return head + "\n\n" + raw


def fire_chain(db_path: str, ask: str, uid: str = "") -> Dict[str, Any]:
    """對一句問話開火。uid 只讀這人持股，不改倉、不看別人倉。偉權哥哥功能全同。"""
    q = (ask or "").strip()
    key = (str(db_path or ""), q, str(uid or ""))
    now = time.time()
    hit = _FIRE_CACHE.get(key)
    if hit and now - hit[0] < 12:
        return hit[1]
    sid, name = _resolve_sid(db_path, q)
    named = bool(sid)
    brief: Dict[str, Any] = {}
    if named:
        try:
            from biaoke_judge import judge_stock

            brief = judge_stock(db_path, sid, name=name) or {}
            brief.setdefault("sid", sid)
            brief.setdefault("name", name or sid)
        except Exception:
            brief = {"sid": sid, "name": name or sid}
    nest = _nest(db_path, q)
    steps = [
        nest,
        _field(q, brief),
        _leader(brief, named=named),
        _tape(brief, named=named, db_path=db_path),
        _hold(brief, q, named=named, db_path=db_path, uid=uid),
        _doubt(brief, bool(nest.get("ok")), named=named, nest_text=str(nest.get("text") or "")),
    ]
    live: Dict[str, str] = {}
    if db_path:
        try:
            from biaoke_neurons import latest_bundle

            live = latest_bundle(db_path, sid)
        except Exception:
            live = {}
    if live:
        for step in steps:
            nid = str(step.get("id") or "")
            extra = _live_bit(live, nid, str(step.get("text") or ""))
            if not extra:
                continue
            body = str(step.get("text") or "")
            if nid == "nest":
                step["text"] = _fit_nest(body, extra)
            elif nid == "leader":
                step["text"] = _clip(body + "。" + extra, 900)
            else:
                step["text"] = _clip(extra + "。" + body, 900)
    five = _five_cross(steps, sid, name)
    if five:
        for step in steps:
            if str(step.get("id") or "") != "doubt":
                continue
            body = str(step.get("text") or "")
            if five[:18] not in body:
                step["text"] = _clip(five + " " + body, 900)
    think = _think(steps, sid, name)
    out = {
        "sid": sid,
        "name": name,
        "named": named,
        "steps": steps,
        "five": five,
        "think": think,
        "firm": bool((brief.get("audit") or {}).get("firm")),
    }
    out["lead"] = format_five_lead(out)
    if len(_FIRE_CACHE) > 4:
        _FIRE_CACHE.clear()
    _FIRE_CACHE[key] = (now, out)
    return out


def _reread_block() -> str:
    """六顆用到的看法標題＋摘句，每句對話都重讀，不是關鍵字抽完就丟。"""
    try:
        from biaoke_mind import views_for_neuron
    except Exception:
        return ""
    lines = ["他的看法（這條鏈每顆都重讀，不是關鍵字抽完就丟）："]
    for nid in NEURON_IDS:
        views = views_for_neuron(nid)
        if not views:
            continue
        titles = "；".join(t for t, _b in views)
        lines.append(f"{NEURON_TITLES[nid]}｜{titles}")
        _title, body = views[0]
        lines.append(_clip(body, 180))
    return "\n".join(lines)


def format_chain_notes(db_path: str, ask: str, uid: str = "") -> str:
    """給對話線的材料：大腦先走這條，後面的原文／最新發文是記憶不是推論。"""
    q = (ask or "").strip()
    if not q:
        return ""
    fired = fire_chain(db_path, q, uid=uid)
    lead = str(fired.get("lead") or format_five_lead(fired))
    lines = [
        "開口｜" + lead,
        "神經元鏈（必須按 1→6 串成一句推論，不准只抽一顆關鍵字答完；缺的標缺，不准編）："
    ]
    for i, step in enumerate(fired.get("steps") or [], 1):
        flag = "〔缺〕" if not step.get("ok") and not step.get("skip") else ("〔此句不套〕" if step.get("skip") else "")
        lines.append(f"{i} {step.get('title')}{flag}｜{step.get('text')}")
    think = str(fired.get("think") or "").strip()
    if think:
        lines.append("推論｜" + think)
    five = str(fired.get("five") or "").strip()
    if five:
        lines.append("五件交叉｜" + five)
    reread = _reread_block()
    if reread:
        lines.append(reread)
    lines.append(
        "圖只解釋第 4 顆量價；問一檔要讀他的公開附圖對官方日K。"
        "右灰區是壓撐＋連點延長演算，不是保證、不是買訊。"
        "社團附圖只對價，不進話筒原文。"
    )
    return "\n".join(lines)


def chain_order_ok(text: str) -> bool:
    """測試用：材料裡六顆照順序出現。"""
    blob = text or ""
    pos = [blob.find(NEURON_TITLES[i]) for i in NEURON_IDS]
    return all(p >= 0 for p in pos) and pos == sorted(pos)
