# -*- coding: utf-8 -*-
"""飆大視窗的思考鏈：六顆神經元按他的推論順序開火。

不是 CNN、不是別人的 AGI 規格。材料只准官方庫＋他自己公開文。
每句對話都要整條走完，不准只命中一個關鍵字就答。

順序＝他真正在用的：
  1 大盤巢穴（細微波／15／60／夜盤看大盤；覆巢之下無完卵；沒疊滿不篤定）
  2 產業／主戰場還在不在（個股最重要是產業趨勢）
  3 這族龍頭現在攻還是休（跟漲先看龍頭）
  4 這檔官方日 K 量先價行（爆大量日高當壓、低當撐；個股不數浪）
  5 長抱還是進出（7/24 勿輕易調整 vs F10 等回測；聯發科不是 4/16）
  6 可能看錯（沒疊滿、沒點名、改口一起留）

圖是第 4 顆的眼睛，不是大腦。右灰區只演算最可能碰到哪，不是保證。不是買訊、不進海選。
"""
from __future__ import annotations

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


def _clip(text: str, n: int) -> str:
    s = " ".join(str(text or "").split())
    return s if len(s) <= n else s[: n - 1] + "…"


def _step(nid: str, text: str, *, ok: bool = True, skip: bool = False) -> Dict[str, Any]:
    return {
        "id": nid,
        "title": NEURON_TITLES[nid],
        "ok": bool(ok) and not skip,
        "skip": bool(skip),
        "text": _clip(text, 640),
    }


def _resolve_sid(db_path: str, ask: str) -> Tuple[str, str]:
    try:
        from biaoke_brain import is_market_question, resolve_stock

        hits = resolve_stock(db_path, ask) if ask else []
        if is_market_question(ask) and not hits:
            return "", ""
        if hits:
            return str(hits[0].get("stock_id") or ""), str(hits[0].get("stock_name") or "")
    except Exception:
        pass
    try:
        from biaoke_facts import names_in_ask

        names = names_in_ask(ask)
        if names:
            return str(names[0][0]), str(names[0][1])
    except Exception:
        pass
    return "", ""


def _nest(db_path: str, ask: str) -> Dict[str, Any]:
    bits: List[str] = []
    ok = False
    try:
        from biaoke_brain import load_index_bars

        bars = load_index_bars(db_path, n=2) if db_path else []
        if bars:
            last = bars[-1]
            bits.append(
                f"官方加權 {last.get('date') or ''} 收 {_px(last.get('close')) or '—'} "
                f"高 {_px(last.get('high')) or '—'} 低 {_px(last.get('low')) or '—'}"
            )
            ok = True
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
    except Exception:
        pass
    bits.append(
        "覆巢之下無完卵：大盤不穩，個股先當會出問題。"
        "波浪／細微波／15／60 只看大盤，個股不數 5／9 段。"
        "確認要四路對質（加權、台積電量價、費半、台指期日／夜），沒疊滿不講已確認。"
    )
    if any(x in (ask or "") for x in ("45839", "46506", "右肩", "細微波", "波浪", "大盤", "夜盤")):
        bits.append("大盤位階用他自己點過的 45839／46506／48218，禁止 17000。")
    return _step("nest", "。".join(bits), ok=ok)


def _field(ask: str, brief: Dict[str, Any]) -> Dict[str, Any]:
    bits: List[str] = []
    try:
        from biaoke_mind import match_methods

        for title, body in match_methods(ask, limit=3):
            if title in ("個股先看產業趨勢", "長抱主流／F4→F10／聯發科", "去年年底"):
                bits.append(_clip(body, 280))
    except Exception:
        pass
    ind = str(brief.get("industry") or "")
    rot = str(brief.get("rotation") or "")
    if ind:
        bits.append("這檔產業 " + ind)
    if rot:
        bits.append(rot)
    if not bits:
        if brief.get("sid"):
            bits.append(
                "這句沒點到產業關鍵字，仍要先想趨勢還在不在；"
                "沒有產業材料就不要裝篤定。"
            )
            return _step("field", " ".join(bits), ok=False)
        bits.append("這句沒點檔，產業先擱；大盤仍用第 1 顆。")
        return _step("field", " ".join(bits), skip=True)
    return _step("field", " ".join(bits), ok=True)


def _leader(brief: Dict[str, Any], *, named: bool) -> Dict[str, Any]:
    if not named:
        return _step("leader", "這句沒點檔，不套個股龍頭。", skip=True)
    leader = brief.get("leader") or {}
    lid = str(leader.get("sid") or "")
    if not lid:
        return _step("leader", "沒對上這族龍頭，跟漲沒指引，不能裝這族剛起漲。", ok=False)
    ls = leader.get("struct") or {}
    why = str(leader.get("why") or "同族跟漲先看龍頭")
    bit = f"{leader.get('sid')} {leader.get('name') or ''}（{why}）"
    if ls:
        bit += (
            f" 收 {_px(ls.get('close')) or '—'}"
            f" 爆量日 {ls.get('spike_date') or '—'}"
            f" 高 {_px(ls.get('spike_high')) or '—'} 低 {_px(ls.get('spike_low')) or '—'}"
            f" 站上撐={ls.get('above_support')} 過壓={ls.get('broke_resistance')} 量縮={ls.get('shrinking')}"
        )
    else:
        bit += " 龍頭官方 K 還沒齊，跟漲對不上"
        return _step("leader", bit, ok=False)
    return _step("leader", bit, ok=True)


def _tape(brief: Dict[str, Any], *, named: bool, db_path: str = "") -> Dict[str, Any]:
    if not named:
        return _step("tape", "這句沒點檔，不畫個股量價、不數這檔波浪。", skip=True)
    st = brief.get("struct") or {}
    if not st:
        return _step(
            "tape",
            "官方日 K 量價還不夠。沒有爆大量日高低就不能講壓撐，不准編。",
            ok=False,
        )
    pace = str(brief.get("pace") or "")
    bit = (
        f"{brief.get('sid')} {brief.get('name') or ''} "
        f"{st.get('date') or ''} 收 {_px(st.get('close')) or '—'}。"
        f"量先價行：爆大量日 {st.get('spike_date') or ''} "
        f"高 {_px(st.get('spike_high')) or '—'}＝壓、"
        f"低 {_px(st.get('spike_low')) or '—'}＝撐；"
        f"站上撐={st.get('above_support')} 過壓={st.get('broke_resistance')} 量縮={st.get('shrinking')}。"
        "站上撐後等價穩量縮才像進，收在低下先放棄。個股不數 5／9 段。"
    )
    if pace:
        bit += " " + pace
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
    return _step("tape", bit, ok=True)


def _hold(brief: Dict[str, Any], ask: str, *, named: bool) -> Dict[str, Any]:
    if not named:
        if any(k in (ask or "") for k in ("F10", "F4", "長抱", "聯發科", "抱著波段")):
            try:
                from biaoke_mind import match_methods

                hits = [
                    body
                    for title, body in match_methods(ask, limit=3)
                    if title == "長抱主流／F4→F10／聯發科"
                ]
                if hits:
                    return _step("hold", hits[0], ok=True)
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
    return _step("hold", " ".join(bits), ok=bool(hold or sid))


def _doubt(brief: Dict[str, Any], nest_ok: bool, *, named: bool) -> Dict[str, Any]:
    audit = brief.get("audit") or {}
    miss = [str(x) for x in (audit.get("miss") or [])]
    ok_bits = [str(x) for x in (audit.get("ok") or [])]
    bits: List[str] = []
    if not nest_ok:
        bits.append("大盤官方點位沒齊，確認末端不准講死")
    if named and not brief.get("in_corpus"):
        bits.append("公開文沒點名這檔，只是觸類旁通量價，可能看錯")
    if named and miss:
        bits.extend(miss[:4])
    if named and ok_bits:
        bits.append("已疊：" + "、".join(ok_bits[:4]))
    if audit.get("verdict"):
        bits.append(str(audit.get("verdict")))
    if not bits:
        bits.append("沒疊滿就不講死。對跟錯一起留。這不是買訊。")
    return _step("doubt", " ".join(bits), ok=not miss)


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
        parts.append("大盤官方點位有了。" if nest.get("ok") else "大盤官方點位還缺，確認末端不准講死。")
        parts.append("產業有材料。" if field.get("ok") else "產業材料不夠，不要裝篤定。")
        parts.append("龍頭對得上。" if leader.get("ok") else "龍頭還沒對上。")
        parts.append("量價有官方柱。" if tape.get("ok") else "這檔量價還沒齊，不准編壓撐。")
        if "圖上演算" in str(tape.get("text") or ""):
            parts.append("圖上後續只是壓撐＋連點延長演算，不是保證。")
        if hold.get("text"):
            parts.append(_clip(str(hold.get("text")), 180))
        verdict = str(doubt.get("text") or "")
        if "自問" in verdict:
            parts.append(_clip(verdict[verdict.find("自問") :], 220))
        else:
            parts.append("沒疊滿就不講死。這不是買訊。")
        return _clip("".join(parts), 720)
    return _clip(
        "這句沒點檔：先把大盤巢穴走完（官方高低、四路對質、個股不數浪）。"
        "產業／長抱只在問句有點到時才串進去。",
        420,
    )


def fire_chain(db_path: str, ask: str, uid: str = "") -> Dict[str, Any]:
    """對一句問話開火。uid 預留給之後讀這人持股，現在不改別人倉。"""
    del uid
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
        _hold(brief, q, named=named),
        _doubt(brief, bool(nest.get("ok")), named=named),
    ]
    return {
        "sid": sid,
        "name": name,
        "named": named,
        "steps": steps,
        "think": _think(steps, sid, name),
        "firm": bool((brief.get("audit") or {}).get("firm")),
    }


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
    lines.append("圖只解釋第 4 顆量價。右灰區是壓撐＋連點延長演算，不是保證、不是買訊。")
    return "\n".join(lines)


def chain_order_ok(text: str) -> bool:
    """測試用：材料裡六顆照順序出現。"""
    blob = text or ""
    pos = [blob.find(NEURON_TITLES[i]) for i in NEURON_IDS]
    return all(p >= 0 for p in pos) and pos == sorted(pos)
