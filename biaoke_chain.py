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
    """他自己點的日曆／國際局勢。不是看新聞做股票。"""
    ymd = "".join(ch for ch in str(as_of or "") if ch.isdigit())[:8]
    if not ymd or ymd < "20260916":
        return (
            "他自己點的日曆：還在等 9/16 Fed（9/15～9/16 利率決策），不是看新聞做股票。"
            "9/4：目前影響股市最大因素是 FED 是否升息。"
            "9/7 樓下：指標龍頭要有效過前高再拉一波，等 9/16 以後可能性較大。"
            "9/8：沒升息則已在新史新高的個股理應再表態；到時還在高檔震盪就積極調節、找新標的。"
            "真正下一波主流要下星期才能確認。升息結果不准編"
        )
    bits = [
        "他自己點的 9/16 Fed 已過。升息有沒有這顆庫沒這列，不准編新聞",
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


def _step(nid: str, text: str, *, ok: bool = True, skip: bool = False) -> Dict[str, Any]:
    return {
        "id": nid,
        "title": NEURON_TITLES[nid],
        "ok": bool(ok) and not skip,
        "skip": bool(skip),
        "text": _clip(text, 900),
    }


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
    return sid, name


def _nest(db_path: str, ask: str) -> Dict[str, Any]:
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

        bars = load_index_bars(db_path, n=2) if db_path else []
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
            if night_hi >= 46506:
                bits.append(
                    f"夜盤高 {_px(night_hi)} 已過他自己點的 46506；"
                    "確認末端還要四路對質，不准單靠這一價"
                )
            elif night_hi > 0:
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
        bits.append(cal)
    bits.append(
        "覆巢之下無完卵：大盤不穩，個股先當會出問題。"
        "波浪／細微波／15／60 只看大盤，個股不數 5／9 段。"
        "確認要四路對質（加權、台積電量價、費半、台指期日／夜），沒疊滿不講已確認。"
    )
    if any(x in (ask or "") for x in ("45839", "46506", "右肩", "細微波", "波浪", "大盤", "夜盤")):
        bits.append("大盤位階用他自己點過的 45839／46506／48218，禁止 17000。")
    view = _view_line("nest", n=140)
    if view:
        bits.append(view)
    return _step("nest", "。".join(b.rstrip("。") for b in bits if b), ok=ok)


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
            )
        elif sid == "3081":
            bits.append(
                "下一個台光電他最看好聯亞及建築兩檔；聯亞＝矽光子風向球，不是再找一檔 CCL。"
                "建築兩檔沒點名代號。"
                "2026-09-14：InP 龍頭回到次級四浪、中期支撐區，中線多頭結構未破壞。"
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
                if title in ("個股先看產業趨勢", "去年年底", "9/10 主戰場", "9/14 指數末端"):
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


def _think(steps: List[Dict[str, Any]], sid: str, name: str) -> str:
    """用他的順序把六顆收成一句推論，不是清單。"""
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
            "先看大盤巢穴會不會覆巢，再問產業趨勢還在不在，再看這族龍頭，才輪到這檔官方日 K 量先價行；長抱跟進出分開，最後才講能不能篤定。",
        ]
        nest_t = str(nest.get("text") or "")
        if "45839 之上" in nest_t:
            nest_bit = "大盤官方收還在 45839 之上，右肩低先當沒破"
        elif "已低於他自己點的 9/3 低 45839" in nest_t:
            nest_bit = "大盤官方收已低於 45839，覆巢先當有事"
        else:
            nest_bit = "大盤官方點位有了" if nest.get("ok") else "大盤官方點位還缺，確認末端不准講死"
        if "已過他自己點的 46506" in nest_t:
            nest_bit += "；夜盤高已過 46506，確認仍要四路對質"
        elif "還沒過他自己點的 46506" in nest_t:
            nest_bit += "；夜盤高還沒過 46506"
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
        if "還在等 9/16" in nest_t:
            nest_bit += "；還在等他自己點的 9/16 Fed"
        elif "9/16 Fed 已過" in nest_t:
            nest_bit += "；他自己點的 9/16 已過，升息結果不准編，用新高檔官方日K回撤"
        parts.append(nest_bit + "。")
        parts.append("產業有材料。" if field.get("ok") else "產業材料不夠，不要裝篤定。")
        lead_t = str(leader.get("text") or "")
        if "不另對" in lead_t or "自己就是" in lead_t:
            parts.append("自己就是這族龍頭。")
        elif leader.get("ok"):
            head = lead_t.split("（", 1)[0].strip()
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
        else:
            parts.append("這檔量價還沒齊，不准編壓撐。")
        if hold.get("text"):
            parts.append(_clip(str(hold.get("text")), 180))
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
    if "45839 之上" in nest_t:
        parts.append("官方收還在 45839 之上，右肩低先當沒破。")
    elif "已低於他自己點的 9/3 低 45839" in nest_t:
        parts.append("官方收已低於 45839，覆巢先當有事。")
    if "已過他自己點的 46506" in nest_t:
        parts.append("夜盤高已過 46506，確認仍要四路對質。")
    elif "還沒過他自己點的 46506" in nest_t:
        parts.append("夜盤高還沒過 46506。")
    if "還沒過他自己點的前波高 47578" in nest_t:
        parts.append("官方高還沒過 47578，右肩還沒做完。")
    elif "已過他自己點的前波高 47578" in nest_t:
        parts.append("官方高已過 47578。")
    if "費半這路先當缺" in nest_t or "四路先缺這路" in nest_t:
        parts.append("費半這路缺官方。")
    if "那指這路先當缺" in nest_t:
        parts.append("那指這路缺官方。")
    if "還在等 9/16" in nest_t:
        parts.append("還在等他自己點的 9/16 Fed，下一波主流不准裝已確認。")
    elif "9/16 Fed 已過" in nest_t:
        parts.append("他自己點的 9/16 已過，升息結果不准編，用新高檔官方日K回撤。")
    parts.append("個股不數浪。產業／長抱看法每顆都重讀，沒點檔就不套某一檔。")
    return _clip("".join(parts), 520)


def fire_chain(db_path: str, ask: str, uid: str = "") -> Dict[str, Any]:
    """對一句問話開火。uid 只讀這人持股，不改倉、不看別人倉。偉權哥哥功能全同。"""
    q = (ask or "").strip()
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
    return {
        "sid": sid,
        "name": name,
        "named": named,
        "steps": steps,
        "think": _think(steps, sid, name),
        "firm": bool((brief.get("audit") or {}).get("firm")),
    }


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
    lines = [
        "神經元鏈（必須按 1→6 串成一句推論，不准只抽一顆關鍵字答完；缺的標缺，不准編）："
    ]
    for i, step in enumerate(fired.get("steps") or [], 1):
        flag = "〔缺〕" if not step.get("ok") and not step.get("skip") else ("〔此句不套〕" if step.get("skip") else "")
        lines.append(f"{i} {step.get('title')}{flag}｜{step.get('text')}")
    think = str(fired.get("think") or "").strip()
    if think:
        lines.append("推論｜" + think)
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
