# -*- coding: utf-8 -*-
"""SYNC-RETRACT：改口開火句（上一句位→官方碰到沒→改口／還在等／未完）。

對齊 MISSION_LOCK／WR-RETRACT-COND／BK-CORPUS 改口原子。
不是買訊；不准補他沒說過的價；離開敘事不准進產品；不准改黃金買點。
時區 Asia/Taipei。
"""
from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
from datetime import datetime
from html import escape as html_escape
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo

logger = logging.getLogger("wayne.sync_retract")

TAIPEI = ZoneInfo("Asia/Taipei")
ROOT = Path(__file__).resolve().parent
MANUAL = ROOT / "docs" / "expert_notes" / "飆客" / "observe_manual"
SAMPLE_PATH = MANUAL / "sync_retract_latest.json"
SAMPLE_MD = MANUAL / "sync_retract_latest.md"

TRACK = "SYNC-RETRACT"
RULE_ID = "WR-RETRACT-COND"
PHONE_WARNING_FIXED = "試標・推論／非他原文・非買訊・對質未過閘"

STATUS_RETRACT = "改口"
STATUS_WAIT = "還在等"
STATUS_OPEN = "未完"

# 與 biaoke_level_learn／observe atoms 對齊的改口用語
_RETRACT_MARK = re.compile(
    r"("
    r"更正|改口|動態修正|重新修訂|重新規劃|重新畫|穿刺原規劃|"
    r"被.?誤導|看錯|講錯|收回|之前.{0,8}(錯|不對)|"
    r"完成某一段之後|隨時.*檢視"
    r")",
    re.I,
)
_LEAVE_NOISE = re.compile(
    r"(不想再發文|離開社|退學|壓力很大|被檢舉|禁止發文|不想太多評論)",
    re.I,
)
_MARKET = re.compile(
    r"(大盤|加權|台指|台指期|夜盤|細微波|波浪|位階|TWII|費半|SOX)",
    re.I,
)
_SUPPORT = re.compile(r"(支撐|不破|不跌破|守住|站穩|底)")
_PRESSURE = re.compile(r"(壓力|壓|關上|不過|頸線)")
_BREAK = re.compile(r"(跌破|穿刺|失守|有效破|有效跌破)")

TOL_PCT = 0.003  # 近窗容差 ~0.3%


def _now_taipei() -> str:
    return datetime.now(TAIPEI).strftime("%Y-%m-%d %H:%M:%S")


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


def _level_face(level: float) -> str:
    n = float(level)
    if abs(n - round(n)) < 1e-9:
        return f"{int(round(n))}"
    return f"{n:g}"


def _is_leave_only(text: str) -> bool:
    s = str(text or "").strip()
    if not s or not _LEAVE_NOISE.search(s):
        return False
    # 夾著大盤位階句仍可當材料；純離開敘事丟棄
    if _MARKET.search(s) and re.search(r"\d{4,5}", s):
        return False
    return True


def load_retract_atoms(*, root: Optional[Path] = None) -> List[Dict[str, Any]]:
    """讀 BK-CORPUS 改口條件原子（缺檔＝空）。社團／離開敘事不當核心。"""
    base = Path(root) if root else MANUAL
    for name in ("atoms_latest.json", "observe_atoms.json", "atoms.json"):
        path = base / name
        if not path.is_file():
            continue
        try:
            blob = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        atoms = blob.get("atoms") or blob.get("items") or []
        out: List[Dict[str, Any]] = []
        for a in atoms:
            if not isinstance(a, dict):
                continue
            if str(a.get("theme") or "") != "retract":
                continue
            if a.get("leave_noise") or a.get("source") == "club_backend":
                continue
            if a.get("core") is False:
                continue
            out.append(a)
        return out
    return []


def load_wr_retract_card(*, root: Optional[Path] = None) -> Dict[str, Any]:
    """讀 WR-RETRACT-COND 浪則卡；缺檔回內建摘要（不發明價）。"""
    base = Path(root) if root else MANUAL
    path = base / "wave_rules_cards.json"
    if path.is_file():
        try:
            blob = json.loads(path.read_text(encoding="utf-8"))
            for c in blob.get("cards") or []:
                if str(c.get("id") or "") == RULE_ID:
                    return dict(c)
        except Exception:
            logger.debug("讀 WR-RETRACT-COND 略過", exc_info=True)
    return {
        "id": RULE_ID,
        "title_zh": "改口／重訂位階條件",
        "category": "retract",
        "ops_check_zh": (
            "官方柱有效失守他鎖的帶、或鐵律違規、或多標籤被台積電量價否決→改口；"
            "沒說過的價不准當他的下一步。"
        ),
        "not_buy_signal": True,
        "phone_ok_with_warning": True,
    }


def extract_levels_from_text(text: str) -> List[Dict[str, Any]]:
    """只抽大盤／台指位；個股價不進。委派 extract_index_levels。"""
    try:
        from biaoke_walk import extract_index_levels

        return list(extract_index_levels(str(text or "")) or [])
    except Exception:
        logger.debug("extract_index_levels 略過", exc_info=True)
        return []


def _role_hint(text: str, level: float, ctx: str = "") -> str:
    blob = f"{ctx} {text}"
    # 以該位附近上下文為準
    face = _level_face(level)
    idx = blob.find(face)
    window = blob[max(0, idx - 24) : idx + len(face) + 24] if idx >= 0 else blob
    if _BREAK.search(window):
        return "break"
    if _SUPPORT.search(window):
        return "support"
    if _PRESSURE.search(window):
        return "pressure"
    return "touch"


def load_latest_market_level_sentence(
    db_path: str,
    *,
    lookback_days: int = 120,
) -> Optional[Dict[str, Any]]:
    """讀他最新大盤／位階相關句（主文＋自回；路人／離開敘事不算）。"""
    if not db_path or not os.path.isfile(db_path):
        return None
    from datetime import timedelta

    floor = (datetime.now(TAIPEI) - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
    conn = sqlite3.connect(db_path, timeout=15.0)
    try:
        rows = conn.execute(
            """
            SELECT id, date, time, kind, text FROM biaoke_posts
            WHERE IFNULL(kind,'post') != 'bystander'
              AND date >= ?
              AND IFNULL(text,'') != ''
            ORDER BY date DESC, time DESC
            LIMIT 80
            """,
            (floor,),
        ).fetchall()
    except sqlite3.Error:
        return None
    finally:
        conn.close()

    for pid, day, hm, kind, text in rows:
        body = str(text or "").strip()
        if not body or _is_leave_only(body):
            continue
        if not _MARKET.search(body):
            continue
        levels = extract_levels_from_text(body)
        if not levels:
            continue
        enriched = []
        for hit in levels:
            try:
                lv = float(hit.get("level"))
            except (TypeError, ValueError):
                continue
            role = _role_hint(body, lv, str(hit.get("ctx") or ""))
            enriched.append(
                {
                    "level": lv,
                    "face": _level_face(lv),
                    "role": role,
                    "oral_role": str(hit.get("role") or "點位"),
                    "ctx": str(hit.get("ctx") or "")[:90],
                }
            )
        if not enriched:
            continue
        return {
            "post_id": str(pid or ""),
            "date": str(day or ""),
            "time": str(hm or ""),
            "kind": str(kind or "post"),
            "text": body,
            "levels": enriched,
            "he_said_retract": bool(_RETRACT_MARK.search(body)),
        }
    return None


def load_near_window_bars(
    db_path: str,
    *,
    n: int = 5,
    as_of: str = "",
) -> List[Dict[str, Any]]:
    """官方加權近窗（已收柱；盤中未收不當收）。"""
    if not db_path or not os.path.isfile(db_path):
        return []
    try:
        from trading_calendar import is_official_daily_bar
    except Exception:
        is_official_daily_bar = None  # type: ignore
    conn = sqlite3.connect(db_path, timeout=15.0)
    try:
        rows = conn.execute(
            """
            SELECT date, open, high, low, close FROM index_daily
            WHERE symbol IN ('TWII','^TWII')
              AND high IS NOT NULL AND low IS NOT NULL AND close IS NOT NULL
            ORDER BY date DESC LIMIT 24
            """
        ).fetchall()
    except sqlite3.Error:
        return []
    finally:
        conn.close()
    cutoff = _ymd(as_of)
    out: List[Dict[str, Any]] = []
    for raw_d, o, h, lo, c in rows:
        day = _ymd(raw_d)
        if not day:
            continue
        if cutoff and day > cutoff:
            continue
        if is_official_daily_bar is not None:
            try:
                if not is_official_daily_bar(day):
                    continue
            except Exception:
                continue
        oo, hh, ll, cc = _f(o), _f(h), _f(lo), _f(c)
        if hh is None or ll is None or cc is None:
            continue
        out.append(
            {
                "date": day,
                "open": oo if oo is not None else cc,
                "high": hh,
                "low": ll,
                "close": cc,
            }
        )
        if len(out) >= max(1, int(n)):
            break
    return out


def grade_level_vs_bars(
    level: float,
    role: str,
    bars: Sequence[Dict[str, Any]],
    *,
    tol_pct: float = TOL_PCT,
) -> Dict[str, Any]:
    """上一句位 vs 官方近窗：碰到／失守／還在上方或下方。"""
    lv = float(level)
    if not bars or lv <= 0:
        return {
            "level": lv,
            "face": _level_face(lv),
            "role": role,
            "touched": False,
            "broke": False,
            "held": False,
            "status_hint": STATUS_OPEN,
        }
    tol = lv * float(tol_pct)
    hi = max(float(b["high"]) for b in bars)
    lo = min(float(b["low"]) for b in bars)
    last = float(bars[0]["close"])  # bars 近→遠
    touched = any(
        float(b["low"]) - tol <= lv <= float(b["high"]) + tol for b in bars
    )
    role_l = str(role or "touch")
    broke = False
    held = False
    if role_l == "support":
        broke = last < lv - tol and lo < lv - tol
        held = lo >= lv - tol or (touched and last >= lv - tol)
    elif role_l == "break":
        broke = lo <= lv + tol
        held = not broke
    elif role_l == "pressure":
        broke = last > lv + tol and hi > lv + tol  # 有效站上壓＝結構改口條件
        held = hi < lv - tol
        touched = touched or hi >= lv - tol
    else:
        # touch：碰到＝觀察；有效收破（低於位）當條件觸發
        broke = last < lv - tol and lo < lv - tol
        held = not broke
    return {
        "level": lv,
        "face": _level_face(lv),
        "role": role_l,
        "touched": bool(touched),
        "broke": bool(broke),
        "held": bool(held),
        "near_hi": hi,
        "near_lo": lo,
        "near_close": last,
        "bar_date": str(bars[0].get("date") or ""),
    }


def decide_status(
    *,
    sentence: Optional[Dict[str, Any]],
    grades: Sequence[Dict[str, Any]],
    bars: Sequence[Dict[str, Any]],
) -> str:
    """輸出改口／還在等／未完（不准發明下一步價）。"""
    if not sentence or not sentence.get("levels"):
        return STATUS_OPEN
    if not bars:
        return STATUS_OPEN
    if sentence.get("he_said_retract"):
        return STATUS_RETRACT
    # 官方有效失守他鎖的帶 → 改口條件觸發（WR-RETRACT-COND）
    if any(g.get("broke") for g in grades):
        return STATUS_RETRACT
    return STATUS_WAIT


def format_fire_line(
    *,
    status: str,
    sentence: Optional[Dict[str, Any]],
    grades: Sequence[Dict[str, Any]],
    bars: Sequence[Dict[str, Any]],
    warning: str = PHONE_WARNING_FIXED,
) -> str:
    """開火句形狀：上一句位 → 官方碰到沒 → 改口／還在等／未完｜警語。"""
    if status == STATUS_OPEN and (not sentence or not sentence.get("levels")):
        return f"開火：上一句位（缺）→ 官方近窗（缺）→ {STATUS_OPEN}｜{warning}"
    faces = []
    if grades:
        faces = [str(g.get("face") or "") for g in grades if g.get("face")]
    elif sentence:
        faces = [
            str(x.get("face") or _level_face(float(x["level"])))
            for x in (sentence.get("levels") or [])[:4]
        ]
    face_s = "／".join(faces[:4]) if faces else "（缺）"
    if not bars:
        return (
            f"開火：上一句位 {face_s} → 官方近窗未齊／未收 → "
            f"{STATUS_OPEN}｜{warning}"
        )
    ymd = str(bars[0].get("date") or "")
    ymd_zh = ymd
    if len(ymd) == 8:
        ymd_zh = f"{ymd[4:6]}/{ymd[6:8]}"
    touched_any = any(g.get("touched") for g in grades)
    broke_any = any(g.get("broke") for g in grades)
    if broke_any:
        touch_bit = "有效失守／條件觸發"
    elif touched_any:
        touch_bit = "已碰到"
    else:
        touch_bit = "還沒碰到"
    # 改口時不准補新價；只標狀態
    if status == STATUS_RETRACT:
        if sentence and sentence.get("he_said_retract"):
            tail = "他後文已改口（舊位只參考）"
        else:
            tail = "改口條件觸發（不准發明下一步價）"
        return (
            f"開火：上一句位 {face_s} → 官方近窗 {ymd_zh} {touch_bit} → "
            f"{STATUS_RETRACT}・{tail}｜{warning}"
        )
    if status == STATUS_WAIT:
        if touched_any:
            wait_bit = "官方已碰到・他尚未改口"
        else:
            wait_bit = "等官方碰到他自己點過的位"
        return (
            f"開火：上一句位 {face_s} → 官方近窗 {ymd_zh} {touch_bit} → "
            f"{STATUS_WAIT}・{wait_bit}｜{warning}"
        )
    return (
        f"開火：上一句位 {face_s} → 官方近窗 {ymd_zh} {touch_bit} → "
        f"{STATUS_OPEN}｜{warning}"
    )


def run_sync_retract(
    db_path: str = "",
    *,
    near_n: int = 5,
    as_of: str = "",
    sentence: Optional[Dict[str, Any]] = None,
    bars: Optional[Sequence[Dict[str, Any]]] = None,
    root: Optional[Path] = None,
    write_sample: bool = False,
) -> Dict[str, Any]:
    """可重跑：讀最新大盤位階句 → 對官方近窗 → 開火句＋狀態。"""
    card = load_wr_retract_card(root=root)
    atoms = load_retract_atoms(root=root)
    sent = sentence if sentence is not None else load_latest_market_level_sentence(db_path)
    win = list(bars) if bars is not None else load_near_window_bars(
        db_path, n=near_n, as_of=as_of
    )
    grades: List[Dict[str, Any]] = []
    if sent:
        for hit in sent.get("levels") or []:
            grades.append(
                grade_level_vs_bars(
                    float(hit["level"]),
                    str(hit.get("role") or "touch"),
                    win,
                )
            )
    status = decide_status(sentence=sent, grades=grades, bars=win)
    fire = format_fire_line(
        status=status, sentence=sent, grades=grades, bars=win
    )
    payload: Dict[str, Any] = {
        "track": TRACK,
        "rule_id": RULE_ID,
        "generated_at_taipei": _now_taipei(),
        "buy_signal": False,
        "not_buy_signal": True,
        "phone_warning_fixed": PHONE_WARNING_FIXED,
        "leave_narrative_blocked": True,
        "golden_buy_untouched": True,
        "status": status,
        "fire_line": fire,
        "fire_shape_zh": "上一句的位 → 官方柱碰到沒 → 改口或還在等／未完｜固定警語",
        "sentence": (
            {
                "post_id": sent.get("post_id"),
                "date": sent.get("date"),
                "time": sent.get("time"),
                "kind": sent.get("kind"),
                "he_said_retract": bool(sent.get("he_said_retract")),
                "levels": sent.get("levels") or [],
                "excerpt": str(sent.get("text") or "")[:160],
            }
            if sent
            else None
        ),
        "near_window": [
            {
                "date": b.get("date"),
                "open": b.get("open"),
                "high": b.get("high"),
                "low": b.get("low"),
                "close": b.get("close"),
            }
            for b in win
        ],
        "grades": grades,
        "wr_retract": {
            "id": card.get("id"),
            "title_zh": card.get("title_zh"),
            "ops_check_zh": card.get("ops_check_zh"),
        },
        "retract_atoms_n": len(atoms),
        "retract_atom_ids": [str(a.get("atom_id") or "") for a in atoms[:12]],
    }
    if write_sample:
        try:
            MANUAL.mkdir(parents=True, exist_ok=True)
            SAMPLE_PATH.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            SAMPLE_MD.write_text(summarize_md(payload), encoding="utf-8")
        except Exception:
            logger.debug("寫 sync_retract 樣例略過", exc_info=True)
    return payload


def summarize_md(payload: Dict[str, Any]) -> str:
    lines = [
        "# SYNC-RETRACT 開火樣例",
        "",
        f"- as_of：`{payload.get('generated_at_taipei')}`（Asia/Taipei）",
        f"- 狀態：**{payload.get('status')}**",
        f"- 規則：`{payload.get('rule_id')}`",
        f"- 警語：`{payload.get('phone_warning_fixed')}`",
        "- 非買訊；不准補沒說過的價；離開敘事不進產品；黃金買點不動。",
        "",
        "## 開火句",
        "",
        f"`{payload.get('fire_line')}`",
        "",
        "## 形狀",
        "",
        str(payload.get("fire_shape_zh") or ""),
        "",
    ]
    sent = payload.get("sentence") or {}
    if sent:
        faces = "／".join(
            str(x.get("face") or "") for x in (sent.get("levels") or [])[:4]
        )
        lines.extend(
            [
                "## 上一句",
                "",
                f"- 文：{sent.get('date')} {sent.get('time')} `{sent.get('post_id')}`",
                f"- 位：{faces}",
                f"- 他文已改口標記：{sent.get('he_said_retract')}",
                "",
            ]
        )
    return "\n".join(lines) + "\n"


def format_wave_retract_html(
    db_path: str = "",
    *,
    payload: Optional[Dict[str, Any]] = None,
) -> str:
    """波浪位階敘述槽：開火一句＋固定警語（HTML）。

    沒有他上一句真位階句 → 空（不准用缺料句塞話筒）。
    """
    try:
        blob = payload or run_sync_retract(db_path)
    except Exception:
        logger.debug("format_wave_retract_html 略過", exc_info=True)
        return ""
    if not (blob.get("sentence") or {}).get("levels"):
        return ""
    fire = str(blob.get("fire_line") or "").strip()
    if not fire:
        return ""
    status = str(blob.get("status") or STATUS_OPEN)
    return "\n".join(
        [
            "<b>改口開火</b>",
            html_escape(fire),
            html_escape(f"狀態：{status}・非買訊"),
        ]
    )


def attach_retract_to_teach_brief(html: str, db_path: str = "") -> str:
    """波浪位階開場敘述末端掛開火句；失敗／缺上一句不擋主文。"""
    raw = str(html or "").strip()
    if not raw or not db_path:
        return raw
    if "改口開火" in raw or "開火：上一句位" in raw:
        return raw
    try:
        slot = format_wave_retract_html(db_path).strip()
    except Exception:
        return raw
    if not slot:
        return raw
    return raw + "\n\n" + slot


def enrich_level_hit_html(html: str, db_path: str = "") -> str:
    """既有 level-hit 推播若適合：補一行開火狀態（不改關卡主句、不發明價）。"""
    raw = str(html or "").strip()
    if not raw or not db_path:
        return raw
    if "開火：" in raw:
        return raw
    # 只在「碰到關卡」類推播上掛
    if "碰到" not in raw and "關卡" not in raw:
        return raw
    try:
        blob = run_sync_retract(db_path)
        if not (blob.get("sentence") or {}).get("levels"):
            return raw
        fire = str(blob.get("fire_line") or "").strip()
        status = str(blob.get("status") or "")
    except Exception:
        return raw
    if not fire:
        return raw
    # level-hit 已是「碰到」；開火句補「改口／還在等」口徑
    if status not in (STATUS_RETRACT, STATUS_WAIT, STATUS_OPEN):
        return raw
    return raw.rstrip() + "\n" + html_escape(fire)


__all__ = [
    "PHONE_WARNING_FIXED",
    "STATUS_OPEN",
    "STATUS_RETRACT",
    "STATUS_WAIT",
    "TRACK",
    "RULE_ID",
    "attach_retract_to_teach_brief",
    "decide_status",
    "enrich_level_hit_html",
    "extract_levels_from_text",
    "format_fire_line",
    "format_wave_retract_html",
    "grade_level_vs_bars",
    "load_latest_market_level_sentence",
    "load_near_window_bars",
    "load_retract_atoms",
    "load_wr_retract_card",
    "run_sync_retract",
    "summarize_md",
]
