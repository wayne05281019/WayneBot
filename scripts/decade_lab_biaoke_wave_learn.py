#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""飆大學習驗證迴路（靜默）｜波浪（含細微波／碎形）＋五件＋他說過的全部。

目的對齊 decade 回測鎖：
- 預判大盤方向＋幅度；波浪是主結構；飆大軌並列對質學習
- 五件：波浪／形態／量價結構／關鍵K／碎形線 — 叠同一他點過的位才叫交叉
- 細微波／子浪：只在他點過的大盤語境驗證，不准發明個股 5／9
- 學他全部說過的（主文＋自回）對官方柱；不是買訊；不上話筒

輸出：decade_lab/biaoke_wave_learn_*.json（數字表，不准 PNG）
"""
from __future__ import annotations

import gzip
import json
import os
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in __import__("sys").path:
    __import__("sys").path.insert(0, str(ROOT))

MARKET_DB = Path(os.environ.get("WAYNE_DB_PATH") or (ROOT / "data" / "wayne_market.db"))
OUT_DIR = ROOT / "docs" / "expert_notes" / "飆客" / "decade_lab"
TAIPEI = ZoneInfo("Asia/Taipei")

MIN_N = 20
# 神經元未對齊前永遠 blocked（使用者／AGENTS 鎖）
WAVE_NEURONS_MATCH = False

_MICRO = re.compile(
    r"(細微波|子浪|碎形線|碎形|C-?\s*[12345]|C3-3|小波|微觀浪|"
    r"①|②|③|④|⑤|九組推升|9\s*波)"
)
_FIVE_LABELS = ("wave", "morph", "vol", "keyk", "fractal")
_FRACTAL_LINE = re.compile(r"(碎形線|碎形\s*線|細微波.*線|下降壓|上升軌|軌道)")


def _now() -> str:
    return datetime.now(TAIPEI).strftime("%Y-%m-%dT%H:%M:%S")


def _ymd(raw: Any) -> str:
    t = str(raw or "").replace("-", "")[:8]
    return t if len(t) == 8 and t.isdigit() else ""


def _spoken(raw: str) -> str:
    try:
        from biaoke_ingest import spoken_text

        return spoken_text(raw or "")
    except Exception:
        return re.sub(r"\s+", " ", str(raw or "")).strip()


def _load_posts(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
    """主文＋自回；排除路人（kind=bystander）。"""
    from biaoke_five_bt import load_posts

    out: List[Dict[str, Any]] = []
    for p in load_posts(conn):
        day = _ymd(p.get("date"))
        text = _spoken(p.get("text") or "")
        if not day or not text:
            continue
        out.append({"post_id": str(p.get("id")), "date": day, "text": text, "kind": p.get("kind")})
    return out


def _five_tags(text: str) -> List[str]:
    from biaoke_five_bt import _tools

    tags = list(_tools(text))
    if _FRACTAL_LINE.search(text) and "fractal" not in tags:
        tags.append("fractal")
    if _MICRO.search(text) and "wave" not in tags:
        tags.append("wave")
    return tags


def run_five_bt_refresh(db_path: Path = MARKET_DB) -> Dict[str, Any]:
    """重跑五件對官方柱（既有引擎），拷摘要進 decade_lab。"""
    from biaoke_five_bt import run_five_bt, save_snapshot

    snap = run_five_bt(str(db_path))
    if snap.get("ok"):
        try:
            save_snapshot(snap)
        except Exception:
            pass
    # 正規化命中率
    tools = {}
    for k, v in (snap.get("tools") or {}).items():
        n = int(v.get("n") or 0)
        hit = int(v.get("hit") or 0)
        miss = int(v.get("miss") or 0)
        decided = hit + miss
        tools[k] = {
            "n": n,
            "hit": hit,
            "miss": miss,
            "pending": int(v.get("pending") or 0),
            "hit_rate": (hit / decided) if decided else None,
            "gate_n20": decided >= MIN_N,
        }
    out = {
        "written_at": _now(),
        "tz": "Asia/Taipei",
        "source": "biaoke_five_bt",
        "n_posts": snap.get("n_posts"),
        "n_tool": snap.get("n_tool"),
        "last_official": snap.get("last_official"),
        "tools": tools,
        "five_zh": ["波浪", "形態", "量價結構", "關鍵K", "碎形線"],
        "not_buy_signal": True,
        "phone_sync": "blocked",
        "WAVE_NEURONS_MATCH": WAVE_NEURONS_MATCH,
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "biaoke_five_learn_latest.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return out


def verify_micro_fractal(conn: sqlite3.Connection, posts: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """細微波／碎形：他點過的大盤語 → 後窗官方柱對質（不准發明個股浪）。"""
    tw = {
        _ymd(d): (float(h), float(lo), float(c))
        for d, h, lo, c in conn.execute(
            "SELECT REPLACE(CAST(date AS TEXT),'-',''), high, low, close "
            "FROM index_daily WHERE symbol='TWII'"
        )
        if _ymd(d) and c
    }
    keys = sorted(tw)
    idx = {d: i for i, d in enumerate(keys)}
    rows: List[Dict[str, Any]] = []
    for p in posts:
        text = p["text"]
        if not _MICRO.search(text):
            continue
        day = p["date"]
        if day not in idx:
            rows.append({**p, "verdict": "缺柱", "ok": None})
            continue
        i = idx[day]
        if i + 5 >= len(keys):
            rows.append({**p, "verdict": "未完", "ok": None})
            continue
        # 簡核：若提「不破／支撐」→ 後5日低不破當日低太多；若提續跌／逃命 → 後5日收弱
        supportish = bool(re.search(r"(不破|守住|支撐|築底|難破)", text))
        bearish = bool(re.search(r"(逃命|續跌|主跌|南下|C\s*波|修正末端)", text))
        px0 = tw[day][2]
        lo0 = tw[day][1]
        fut_closes = [tw[keys[i + j]][2] for j in range(1, 6)]
        fut_lows = [tw[keys[i + j]][1] for j in range(1, 6)]
        ok: Optional[bool]
        note = ""
        if supportish and not bearish:
            ok = min(fut_lows) >= lo0 * 0.985
            note = f"支撐語後5低{min(fut_lows):.0f} vs 當日低{lo0:.0f}"
        elif bearish:
            ok = fut_closes[-1] < px0
            note = f"偏空語後5收{fut_closes[-1]:.0f} vs 當日{px0:.0f}"
        else:
            # 細微波僅標記出現＝材料；方向不明不硬判
            ok = None
            note = "細微波／碎形提及但方向語不足，記材料不硬判"
        verd = "對" if ok is True else ("偏" if ok is False else ("未完" if ok is None and "不足" not in note else "材料"))
        if ok is None and "不足" in note:
            verd = "材料"
        rows.append(
            {
                "post_id": p["post_id"],
                "date": day,
                "verdict": verd,
                "ok": ok,
                "note": note,
                "has_fractal_line": bool(_FRACTAL_LINE.search(text)),
            }
        )
    decided = [r for r in rows if r.get("ok") is True or r.get("ok") is False]
    hit = sum(1 for r in decided if r["ok"] is True)
    miss = sum(1 for r in decided if r["ok"] is False)
    summary = {
        "written_at": _now(),
        "tz": "Asia/Taipei",
        "n_micro_posts": len(rows),
        "n_decided": len(decided),
        "hit": hit,
        "miss": miss,
        "hit_rate": (hit / len(decided)) if decided else None,
        "gate_n20": len(decided) >= MIN_N,
        "rule_zh": "細微波／碎形只驗證他點過的大盤語；個股不數浪",
        "not_buy_signal": True,
        "phone_sync": "blocked",
        "WAVE_NEURONS_MATCH": WAVE_NEURONS_MATCH,
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "biaoke_micro_fractal_latest.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    with gzip.open(OUT_DIR / "biaoke_micro_fractal_rows.jsonl.gz", "wt", encoding="utf-8") as f:
        for r in rows[-5000:]:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return summary


def five_cooccur_same_post(posts: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """五件交叉：同一則他說裡叠到 ≥3／≥4／五件齊。"""
    counts = {"ge1": 0, "ge3": 0, "ge4": 0, "all5": 0}
    samples: List[Dict[str, Any]] = []
    for p in posts:
        tags = _five_tags(p["text"])
        # fractal 獨立計；keyk 含碎形語時也算 fractal
        if "keyk" in tags and _FRACTAL_LINE.search(p["text"]) and "fractal" not in tags:
            tags.append("fractal")
        n = len(set(tags))
        if n >= 1:
            counts["ge1"] += 1
        if n >= 3:
            counts["ge3"] += 1
        if n >= 4:
            counts["ge4"] += 1
        if n >= 5 or set(tags) >= {"wave", "morph", "vol", "keyk"}:
            # 五件定義：浪／形／量／關鍵K／碎形 — 若碎形併入 keyk，四件核心+fractal語也算交叉
            if "fractal" in tags or _FRACTAL_LINE.search(p["text"]) or "keyk" in tags:
                if n >= 4:
                    counts["all5"] += 1
                    if len(samples) < 30:
                        samples.append(
                            {
                                "post_id": p["post_id"],
                                "date": p["date"],
                                "tags": tags,
                                "snip": p["text"][:120],
                            }
                        )
    return {
        "written_at": _now(),
        "tz": "Asia/Taipei",
        "n_posts": len(posts),
        "counts": counts,
        "samples": samples,
        "note_zh": "五件叠同一則＝交叉候選；仍須官方柱對質才算學成",
        "not_buy_signal": True,
    }


def corpus_cover(posts: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """他說過的覆蓋：有幾則進學習、五件／細微波占比。"""
    n = len(posts)
    n_five = sum(1 for p in posts if _five_tags(p["text"]))
    n_micro = sum(1 for p in posts if _MICRO.search(p["text"]))
    return {
        "n_posts_spoken": n,
        "n_with_five_tool": n_five,
        "n_with_micro_fractal": n_micro,
        "pct_five": round(n_five / n, 4) if n else None,
        "pct_micro": round(n_micro / n, 4) if n else None,
        "learn_scope_zh": "主文＋樓下自回全部；路人正文不當他的判斷",
    }


def load_wave_structure_vote() -> Dict[str, Any]:
    """讀 wave8 雙軌摘要 → 路徑預測用的結構主判偏好。"""
    p = OUT_DIR / "wave8_dual_summary.json"
    if not p.exists():
        return {"ok": False, "bias_pref": None}
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"ok": False, "bias_pref": None}
    adopt = (d.get("adopt") or {}).get("pick")
    tracks = d.get("tracks") or {}
    text = tracks.get("textbook_8cycle") or {}
    biao = tracks.get("biaoke_degree") or {}
    return {
        "ok": True,
        "adopt": adopt,
        "textbook_hit": text.get("hit_rate"),
        "textbook_n": text.get("n_decided"),
        "biaoke_hit": biao.get("hit_rate"),
        "biaoke_n": biao.get("n_decided"),
        "structural_primary": "wave",
        "phone_sync": "blocked",
        "WAVE_NEURONS_MATCH": WAVE_NEURONS_MATCH,
    }


def load_level_bar_hit() -> Dict[str, Any]:
    """讀位→柱靜默對質摘要（沒檔＝略過，不准假數）。"""
    p = OUT_DIR / "biaoke_level_bar_hit_latest.json"
    if not p.exists():
        return {"ok": False}
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"ok": False}
    cur = str(d.get("current_variant") or "")
    nxt = d.get("next_variant") or {}
    tracks = d.get("tracks") or {}
    cur_s = tracks.get(cur) or {}
    return {
        "ok": True,
        "current_variant": cur,
        "current_n": cur_s.get("n_decided"),
        "current_hit": cur_s.get("hit_rate"),
        "next_variant": nxt.get("variant"),
        "next_n": nxt.get("n_decided"),
        "next_hit": nxt.get("hit_rate"),
        "replace": bool(nxt.get("replace")),
        "phone_sync": "blocked",
        "WAVE_NEURONS_MATCH": WAVE_NEURONS_MATCH,
    }


def run_all(db_path: Path = MARKET_DB) -> Dict[str, Any]:
    conn = sqlite3.connect(str(db_path), timeout=60.0)
    try:
        posts = _load_posts(conn)
        cover = corpus_cover(posts)
        co = five_cooccur_same_post(posts)
        micro = verify_micro_fractal(conn, posts)
    finally:
        conn.close()
    five = run_five_bt_refresh(db_path)
    wave = load_wave_structure_vote()
    level_bar = load_level_bar_hit()
    # 學成閘：五件各軌／細微波 n≥20 且命中可讀；神經元對齊另鎖
    learn_ready = bool(
        WAVE_NEURONS_MATCH
        and wave.get("ok")
        and (wave.get("biaoke_n") or 0) >= MIN_N
        and micro.get("gate_n20")
    )
    summary = {
        "written_at": _now(),
        "tz": "Asia/Taipei",
        "purpose_zh": (
            "驗證學習：波浪（含細微波／碎形）＋飆大五件＋他說過的全部；"
            "服務大盤方向＋幅度主判；不是買訊"
        ),
        "corpus": cover,
        "five_cooccur": co,
        "five_bt": five,
        "micro_fractal": {
            "n_decided": micro.get("n_decided"),
            "hit_rate": micro.get("hit_rate"),
            "gate_n20": micro.get("gate_n20"),
        },
        "wave8_structure": wave,
        "level_bar_hit": level_bar,
        "learn_ready_for_phone": learn_ready,
        "phone_sync": "blocked",
        "WAVE_NEURONS_MATCH": WAVE_NEURONS_MATCH,
        "not_buy_signal": True,
        "next_zh": [
            "位→柱下一鍵 level_bar_vnext_explicit_hybrid 續收集（未贏不准換）",
            "細微波未過閘→續收他點過的大盤細微波句對官方柱",
            "五件交叉日另對質同日官方柱（叠位）",
            "WAVE_NEURONS_MATCH 未真對齊前不准上話筒、不准發明 5／9",
        ],
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "biaoke_wave_learn_latest.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (OUT_DIR / "five_cooccur_latest.json").write_text(
        json.dumps(co, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return summary


def main() -> int:
    summary = run_all()
    print(json.dumps(summary, ensure_ascii=False, indent=2)[:6000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
