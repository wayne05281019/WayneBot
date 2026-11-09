#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""大盤多路推論＋官方驗證（段號必標）。

使用者鎖（2026-11-09）：
- 每次必先推論；每路必標暫定段號（推論／未定案），不標＝無法對質＝沒做完。
- 官方柱驗證；錯了拆實際路徑／未推到的數；回頭對八循環細拆並落檔。
- 正確率升高前不當成一定發生；不是買訊；phone_sync=blocked。
- 飆大不一定永遠在 → 已知內化成自有庫，靠此迴圈練獨立判斷。
"""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
MARKET_DB = Path(os.environ.get("WAYNE_DB_PATH") or (ROOT / "data" / "wayne_market.db"))
OUT_DIR = ROOT / "docs" / "expert_notes" / "飆客" / "decade_lab"
ART = Path("/opt/cursor/artifacts")
TAIPEI = ZoneInfo("Asia/Taipei")
PHONE_SYNC = "blocked"


def _now() -> str:
    return datetime.now(TAIPEI).strftime("%Y-%m-%dT%H:%M:%S")


def _ymd(raw: Any) -> str:
    t = str(raw or "").replace("-", "")[:8]
    return t if len(t) == 8 and t.isdigit() else ""


def _f(v: Any) -> Optional[float]:
    try:
        if v is None or v == "":
            return None
        n = float(v)
    except (TypeError, ValueError):
        return None
    if n != n:
        return None
    return n


def _load_tx(con: sqlite3.Connection, since: str = "20261001") -> List[Dict[str, Any]]:
    rows = con.execute(
        """
        SELECT REPLACE(CAST(date AS TEXT),'-',''), session, open, high, low, close
        FROM futures_daily WHERE symbol='TX' AND date>=?
        ORDER BY 1, session
        """,
        (since,),
    ).fetchall()
    out = []
    for d, sess, o, h, l, c in rows:
        day = _ymd(d)
        cc = _f(c)
        if not day or not cc:
            continue
        out.append(
            {
                "date": day,
                "session": str(sess or ""),
                "open": _f(o) or cc,
                "high": _f(h) or cc,
                "low": _f(l) or cc,
                "close": cc,
            }
        )
    return out


def _load_twii(con: sqlite3.Connection, since: str = "20261001") -> List[Dict[str, Any]]:
    rows = con.execute(
        """
        SELECT REPLACE(CAST(date AS TEXT),'-',''), open, high, low, close
        FROM index_daily WHERE symbol='TWII' AND date>=?
        ORDER BY 1
        """,
        (since,),
    ).fetchall()
    out = []
    for d, o, h, l, c in rows:
        day = _ymd(d)
        cc = _f(c)
        if not day or not cc:
            continue
        out.append(
            {
                "date": day,
                "open": _f(o) or cc,
                "high": _f(h) or cc,
                "low": _f(l) or cc,
                "close": cc,
            }
        )
    return out


def _require_segments(path: Dict[str, Any]) -> None:
    segs = path.get("segments_provisional")
    if not isinstance(segs, list) or not segs:
        raise ValueError(f"path {path.get('id')} missing segments_provisional — 段號必標")
    for s in segs:
        if not str(s.get("label") or "").strip():
            raise ValueError(f"path {path.get('id')} blank segment label")


def _infer_paths_20261109(*, fri_low_twii: float, fri_low_tx: float) -> List[Dict[str, Any]]:
    """依 11/09 09:09 文＋已內化規則做多路推論（暫定段號必標）。"""
    paths = [
        {
            "id": "A_main_his",
            "status": "推論／未定案",
            "thesis_zh": (
                "他認最後一組下跌脈動 C3-5 已與 1 4 重疊；"
                "上週五低為最低候選；再測／戳破＝假跌破觀察。"
                "41760 為第一道壓力，未過壓轉撐則易再打低測週五低。"
            ),
            "segments_provisional": [
                {"label": "C3-1", "role": "下跌脈動起", "note": "暫定；待細拆對折點"},
                {"label": "C3-2", "role": "反彈", "note": "暫定"},
                {"label": "C3-3", "role": "主跌", "note": "暫定"},
                {"label": "C3-4", "role": "反彈／與1重疊候選", "note": "1 4重疊關鍵"},
                {"label": "C3-5", "role": "末跌＝上週五低附近完成候選", "level": fri_low_twii},
                {"label": "post_C_rebound", "role": "C走完後反彈／再測", "note": "非新五波升定案"},
            ],
            "levels": {
                "pressure_41760": 41760.0,
                "friday_low_twii": fri_low_twii,
                "friday_low_tx": fri_low_tx,
            },
            "expect": [
                "近窗再測 friday_low（可戳破後快速站回＝假跌破劇本）",
                "若 41760 未轉支撐，反彈夭折機率升",
            ],
            "invalidate": [
                "收盤有效站穩 41760 上方且不再回測 friday_low（壓力轉撐成立）",
                "深破 friday_low 後無法快速站回（假跌破劇本失效→改走更深殺備線）",
            ],
            "not_buy_signal": True,
        },
        {
            "id": "B_fail_41760_retest",
            "status": "推論／未定案",
            "thesis_zh": "41760 不過→快速回測週五低；C3-5 後 B 反彈失敗再測底。",
            "segments_provisional": [
                {"label": "C3-5", "role": "已完成候選", "level": fri_low_twii},
                {"label": "B-a", "role": "反彈段", "note": "暫定；挑戰 41760"},
                {"label": "B-b", "role": "回測段", "note": "再測 friday_low"},
            ],
            "levels": {
                "pressure_41760": 41760.0,
                "retest": fri_low_twii,
            },
            "expect": ["日盤／夜盤高點壓在 41760 下", "低點靠近 friday_low±1%"],
            "invalidate": ["有效站上 41760"],
            "not_buy_signal": True,
        },
        {
            "id": "C_deeper_kill_fake",
            "status": "推論／未定案",
            "thesis_zh": (
                "若戳破 friday_low 後無法站回，則 C3-5／1 4 重疊底劇本失效；"
                "八循環改拆更深一層（備：35579→31705 他先前提過的深殺帶）。"
            ),
            "segments_provisional": [
                {"label": "C3-5", "role": "看似完成但被否決", "note": "若假跌破失效"},
                {"label": "C9_ext_or_deeper_C", "role": "更深殺備線暫定", "note": "只沿用他點過 35579／31705"},
            ],
            "levels": {
                "friday_low": fri_low_twii,
                "deep_hi": 35579.0,
                "deep_lo": 31705.0,
            },
            "expect": ["收在 friday_low 下且次日無法站回"],
            "invalidate": ["戳破後快速站回 friday_low（回到 A 假跌破）"],
            "not_buy_signal": True,
        },
    ]
    for p in paths:
        _require_segments(p)
    return paths


def _verify(
    paths: List[Dict[str, Any]],
    *,
    tx: List[Dict[str, Any]],
    twii: List[Dict[str, Any]],
    as_of: str,
) -> Dict[str, Any]:
    """用 as_of 當日／最近可用官方柱對各路。盤中未收不當最終收。"""
    twii_by = {b["date"]: b for b in twii}
    tx_reg = {b["date"]: b for b in tx if b["session"] == "regular"}
    tx_night = {b["date"]: b for b in tx if b["session"] == "night"}
    fri = "20261106"
    fri_tw = twii_by.get(fri)
    fri_tx = tx_reg.get(fri)
    # 最近一根：優先 as_of 日盤，否則夜盤
    latest_tw = twii_by.get(as_of) or (twii[-1] if twii else None)
    latest_tx_r = tx_reg.get(as_of)
    latest_tx_n = tx_night.get(as_of) or (tx_night.get(max(tx_night)) if tx_night else None)

    official = {
        "as_of": as_of,
        "friday_twii": fri_tw,
        "friday_tx_reg": fri_tx,
        "latest_twii": latest_tw,
        "latest_tx_regular": latest_tx_r,
        "latest_tx_night": latest_tx_n,
        "bar_final": bool(latest_tw is not None and latest_tx_r is not None),
        "note_zh": "無日盤收＝盤中／休市；夜盤可作進行中對照，不當最終定案收",
    }

    results = []
    for p in paths:
        hits: List[str] = []
        misses: List[str] = []
        actual_path: List[str] = []
        lv = p.get("levels") or {}
        p41760 = float(lv.get("pressure_41760") or 41760.0)
        fri_lv = float(lv.get("friday_low_twii") or lv.get("friday_low") or lv.get("retest") or 37837.0)

        # 夜盤／日盤相對 41760、friday_low
        probe = latest_tx_r or latest_tx_n
        if probe:
            if float(probe["high"]) >= p41760:
                hits.append(f"碰到壓力41760（{probe['session']} high={probe['high']}）")
                actual_path.append("touch_41760")
            else:
                misses.append(f"尚未碰到41760（{probe['session']} high={probe['high']}）")
                actual_path.append("below_41760")
            if float(probe["low"]) <= fri_lv * 1.01:
                hits.append(f"靠近／測 friday_low 區（low={probe['low']} vs {fri_lv}）")
                actual_path.append("near_friday_low")
            if float(probe["low"]) < fri_lv and float(probe["close"]) > fri_lv:
                hits.append("戳破後收回 friday_low 上＝假跌破進行中樣")
                actual_path.append("fake_break_candidate")
            elif float(probe["close"]) < fri_lv:
                misses.append("收在 friday_low 下＝假跌破未確認／偏深殺")
                actual_path.append("close_below_friday_low")

        # 段號對質狀態（進行中）
        seg_status = []
        for s in p["segments_provisional"]:
            lab = s["label"]
            st = "進行中／未決"
            if lab == "C3-5" and fri_tw:
                st = "他認完成候選；官方上週五低已在；待再測確認"
            if lab in ("B-a", "post_C_rebound") and probe and float(probe["high"]) < p41760:
                st = "反彈未過41760＝與B-a失敗／再測劇本相容"
            seg_status.append({"label": lab, "status": st, "mark": "推論／未定案"})

        # 哪條路目前較合
        score = len(hits) - 0.5 * len(misses)
        results.append(
            {
                "path_id": p["id"],
                "segments_check": seg_status,
                "hits": hits,
                "misses": misses,
                "actual_path_tags": actual_path,
                "score_rough": score,
                "verdict_zh": "進行中" if not official["bar_final"] else ("偏合" if score > 0 else "偏不合／待拆"),
            }
        )

    results.sort(key=lambda r: -float(r["score_rough"]))
    return {"official": official, "path_results": results, "leading_path": results[0]["path_id"] if results else None}


def run_for_post_20261109() -> Dict[str, Any]:
    as_of = "20261109"
    con = sqlite3.connect(f"file:{MARKET_DB}?mode=ro", uri=True)
    try:
        tx = _load_tx(con)
        twii = _load_twii(con)
    finally:
        con.close()

    fri_tw = next((b for b in twii if b["date"] == "20261106"), None)
    fri_tx = next((b for b in tx if b["date"] == "20261106" and b["session"] == "regular"), None)
    fri_low_twii = float(fri_tw["low"]) if fri_tw else 37837.05
    fri_low_tx = float(fri_tx["low"]) if fri_tx else 37694.0

    paths = _infer_paths_20261109(fri_low_twii=fri_low_twii, fri_low_tx=fri_low_tx)
    verify = _verify(paths, tx=tx, twii=twii, as_of=as_of)

    # 八循環回拆筆記（每次必留；錯了之後往這填）
    cycle8_note = {
        "required": True,
        "textbook_8cycle": ["1", "2", "3", "4", "5", "A", "B", "C"],
        "this_infer_map_zh": (
            "他層級：大A→大B→大C 內之 C3 脈動＝C3-1…C3-5；"
            "1 4重疊落在 C3-1 與 C3-4；C3-5≈上週五低。"
            "之後反彈暫標 post_C／B-a，不准未驗證就升成新五波1。"
        ),
        "miss_analysis_template": {
            "expected_segments": "必填",
            "actual_path": "必填",
            "unexpected_level": "走到哪個沒推到的數",
            "which_segment_broke": "哪一段暫定段號先失效",
            "rule_patch": "回寫八循環切法",
        },
        "pending_zh": "待日盤收完再填 miss_analysis；現有夜盤僅進行中對照",
    }

    out = {
        "phone_sync": PHONE_SYNC,
        "buy_signal": False,
        "certainty": False,
        "segment_numbers": "REQUIRED",
        "as_of_taipei": _now(),
        "event": {
            "source": "user_paste_biaoke_2026-11-09_09:09",
            "post_in_local_db": False,
            "levels_he_said": [41760],
            "oral": "C3-5＋1 4重疊；再測上週五低；假跌破＝上車點（他說）",
        },
        "paths": paths,
        "verify": verify,
        "cycle8_review": cycle8_note,
        "accuracy_gate": {
            "promote_to_phone": False,
            "note_zh": "正確率升高前只練習；不上話筒定論",
        },
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    ART.mkdir(parents=True, exist_ok=True)
    text = json.dumps(out, ensure_ascii=False, indent=2)
    name = f"wave_infer_verify_{as_of}.json"
    (OUT_DIR / name).write_text(text, encoding="utf-8")
    (OUT_DIR / "wave_infer_verify_latest.json").write_text(text, encoding="utf-8")
    (ART / name).write_text(text, encoding="utf-8")
    (ART / "wave_infer_verify_latest.json").write_text(text, encoding="utf-8")
    print("GATE", f"wave_infer_verify {as_of} paths={len(paths)} leading={verify.get('leading_path')} segments=REQUIRED phone_sync=blocked")
    print("LEADING", verify.get("leading_path"), verify["path_results"][0] if verify["path_results"] else None)
    return out


if __name__ == "__main__":
    run_for_post_20261109()
