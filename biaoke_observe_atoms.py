# -*- coding: utf-8 -*-
"""BK-CORPUS：語料 → 觀測原子（方法／位／改口／三層／SOX／鐵律）。

只認他自己（公開 1709＋overlay／DB 自回＋社團後台內化）。
社團標 club_backend，不准當話筒原文。離開敘事不准進核心規則。
不是買訊；不准改黃金買點。時區戳 Asia/Taipei。
"""
from __future__ import annotations

import gzip
import hashlib
import json
import os
import re
import sqlite3
import unicodedata
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo

TAIPEI = ZoneInfo("Asia/Taipei")

_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs", "expert_notes", "飆客")
_OUT_DIR = os.path.join(_DIR, "observe_manual")
ATOMS_JSON = os.path.join(_OUT_DIR, "atoms_latest.json")
ATOMS_MD = os.path.join(_OUT_DIR, "ATOMS_INDEX.md")

THEME_ORDER = (
    "three_layer",
    "sox",
    "level",
    "retract",
    "iron_rule",
    "pv_structure",
    "pattern",
    "key_k",
    "fractal",
    "stock_observe",
    "misc_observe",
)

THEME_LABEL = {
    "three_layer": "三層觀測（夜盤→早盤TX→現貨）",
    "sox": "SOX／費半連動",
    "level": "他點過的位／條件",
    "retract": "改口條件",
    "iron_rule": "波浪鐵律",
    "pv_structure": "量價結構",
    "pattern": "形態",
    "key_k": "關鍵K",
    "fractal": "碎形／軌道線",
    "stock_observe": "大盤→個股觀測",
    "misc_observe": "其他觀測法（附）",
}

# 離開／壓力敘事：可附但不當規則核心（MISSION A9）
_LEAVE_NOISE = re.compile(
    r"(不想再發文|離開社|退學|壓力很大|被檢舉|禁止發文|不想太多評論)",
    re.I,
)

_THREE = re.compile(
    r"("
    r"夜盤.{0,24}(明.?天|早盤|開盤|日盤|現貨|大盤)|"
    r"(明早|早盤|開盤).{0,20}(觀察|確認|表態)|"
    r"(明早|早盤).{0,12}大盤|"
    r"台指期.{0,12}夜盤|夜盤.{0,12}台指|"
    r"e-?mini|小道瓊|那指期|美期|那斯達克期"
    r")",
    re.I,
)
_NIGHT = re.compile(r"夜盤")
_MORNING_TX = re.compile(r"(早盤|開盤|明早|日盤).{0,16}(台指|期)|台指.{0,12}(早盤|開盤|日盤)")
_SPOT = re.compile(r"(現貨|加權|大盤).{0,20}(確認|驗證|表態|觀察)|明早大盤")

_SOX = re.compile(r"(費半|費城半導體|SOX|sox|那斯達[克科])", re.I)

_LEVEL_NUM = re.compile(
    r"(?<![\d.])(\d{4,5}(?:\.\d+)?)(?![\d])"
)
_LEVEL_CTX = re.compile(
    r"(支撐|壓力|穿刺|跌破|站上|站穩|不破|不跌破|頸線|目標|測到|看到|"
    r"低點|高點|軌道|下降壓|上升軌|回測|有效)"
)
_INDEX_BATTLE = re.compile(r"(大盤|加權|台指|台指期|夜盤|細微波|TWII)")

_RETRACT = re.compile(
    r"("
    r"更正|改口|動態修正|重新修訂|重新規劃|重新畫|穿刺原規劃|"
    r"被.?誤導|看錯|講錯|收回|之前.{0,8}(錯|不對)|"
    r"完成某一段之後|隨時.*檢視"
    r")",
    re.I,
)

_IRON = [
    (
        "overlap_14",
        re.compile(r"(1\s*[-–～]?\s*4\s*重疊|一四.?重疊|1\s+4\s*重疊)"),
        "同次級 1–4 重疊＝下跌趨勢化解／調整結構訊號（觀測用，非買訊）",
    ),
    (
        "wave3_not_shortest",
        re.compile(
            r"(第三.?浪.{0,16}(不|非).{0,8}最短|(不|非)最短.{0,12}第三|"
            r"3.?浪.?不.?最短|鐵律.{0,12}第三)"
        ),
        "推動浪第三浪不得為三浪中最短（鐵律觀測）",
    ),
    (
        "complete_5_or_9",
        re.compile(
            r"(細微波.{0,24}(完整結構|5\s*段|9\s*段|走\s*[59])|"
            r"完整結構.{0,12}(5|9)|"
            r"(走完|完成).{0,8}(5\s*段|9\s*段|五段|九段))"
        ),
        "細微波完整結構＝5 段或 9 段（3／5 可擴延）；結構未完不提早鎖死",
    ),
    (
        "channel_2_4",
        re.compile(r"(浪\s*2.{0,8}浪\s*4|2\s*低.{0,8}4\s*低|上升軌.{0,12}(2|二).{0,8}(4|四))"),
        "上升軌連同次級浪 2 低與浪 4 低；破軌＝結構破壞觀測",
    ),
]

_PV = re.compile(
    r"(量價結構|量先價行|爆大量|窒息量|量縮|價穩量縮|攻擊量|量能)"
)
_PATTERN = re.compile(
    r"(頭肩頂|頭肩底|雙底|雙頂|W\s*底|M\s*頭|三角|旗型|破底翻|右肩|左肩|頸線)"
)
_KEY_K = re.compile(
    r"(關鍵.?K|長紅|長黑|十字線|孕線|跳空缺口|實體)"
)
_FRACTAL = re.compile(
    r"(碎形|上升軌|下降軌|下降壓|軌道線|畫線|連.?低|連.?高)"
)
_STOCK_OBS = re.compile(
    r"("
    r"族群.{0,12}(龍頭|輪動|第一)|"
    r"龍頭.{0,12}(量價|過前高|整理)|"
    r"次族群|"
    r"對照同族群|"
    r"大盤.{0,16}(個股|族群)|"
    r"台積電.{0,12}(量價|位階)|"
    r"用.?台積電"
    r")"
)

_SPLIT = re.compile(r"[。！？!?\n；;]+")
_WS = re.compile(r"\s+")


def _norm(text: str) -> str:
    return unicodedata.normalize("NFKC", str(text or ""))


def _clip(text: str, n: int = 72) -> str:
    s = _WS.sub(" ", _norm(text)).strip()
    return s if len(s) <= n else s[: n - 1] + "…"


def _taipei_stamp(date_s: str, time_s: str) -> str:
    d = str(date_s or "").strip()
    t = str(time_s or "").strip()
    if not d:
        return ""
    if t:
        return f"{d} {t[:5]}"
    return d


def _rule_key(theme: str, rule: str) -> str:
    blob = f"{theme}|{_WS.sub('', _norm(rule)).lower()}"
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()[:12]


def _atom_id(theme: str, slug: str) -> str:
    safe = re.sub(r"[^a-z0-9_]+", "_", slug.lower()).strip("_")[:48]
    return f"{theme}.{safe}" if safe else f"{theme}.x"


def _is_leave_only(text: str) -> bool:
    blob = _norm(text)
    if not _LEAVE_NOISE.search(blob):
        return False
    # 同時有位階／夜盤鐵律／SOX 才不算純離開敘事（早盤口語不夠）
    if _LEVEL_CTX.search(blob) and _LEVEL_NUM.search(blob):
        return False
    if _NIGHT.search(blob) and _LEVEL_CTX.search(blob):
        return False
    if _IRON[0][1].search(blob) or _SOX.search(blob):
        return False
    return True


def _best_sentence(text: str, needle: re.Pattern[str]) -> str:
    blob = _norm(text)
    parts = [p.strip() for p in _SPLIT.split(blob) if p and p.strip()]
    for p in parts:
        if needle.search(p) and len(p) >= 8:
            return _clip(p, 96)
    # 退回含關鍵字的窗
    m = needle.search(blob)
    if not m:
        return _clip(blob, 96)
    i = max(0, m.start() - 24)
    return _clip(blob[i : m.end() + 48], 96)


def _levels_in(text: str) -> List[str]:
    blob = _norm(text)
    out: List[str] = []
    for m in _LEVEL_NUM.finditer(blob):
        raw = m.group(1)
        before = blob[max(0, m.start() - 14) : m.start()]
        after = blob[m.end() : m.end() + 10]
        if not _LEVEL_CTX.search(before + after) and not _INDEX_BATTLE.search(
            before + blob[m.start() : m.end() + 20]
        ):
            # 個股短價也收，但要有支撐壓力語
            if not _LEVEL_CTX.search(blob[max(0, m.start() - 30) : m.end() + 20]):
                continue
        try:
            v = float(raw)
        except ValueError:
            continue
        if v < 20:  # 過短數字多半不是位
            continue
        if raw not in out:
            out.append(raw)
        if len(out) >= 6:
            break
    return out


def _is_tw_index_level(raw: str) -> bool:
    """加權／台指觀測位（現代語料 ≥10000）。股價／代號／振幅點數一律 False。"""
    try:
        v = float(raw)
    except ValueError:
        return False
    return 10000.0 <= v <= 100000.0

def _levels_for_theme(theme: str, rule: str, text: str) -> List[str]:
    """依主題濾位：三層／大盤只留指數級；個股鍋留非指數。"""
    raw = _levels_in(text)
    if theme == "three_layer" or (
        theme == "level" and rule.startswith("大盤")
    ):
        return [x for x in raw if _is_tw_index_level(x)]
    if theme == "level" and rule.startswith("個股"):
        return [x for x in raw if not _is_tw_index_level(x)]
    return raw

def _prov(
    row: Dict[str, Any], excerpt: str, *, club: bool
) -> Dict[str, Any]:
    return {
        "post_id": str(row.get("id") or ""),
        "taipei": _taipei_stamp(str(row.get("date") or ""), str(row.get("time") or "")),
        "kind": str(row.get("kind") or "post"),
        "club": bool(club),
        "excerpt": _clip(excerpt, 96),
    }


def load_db_posts(db_path: str) -> List[Dict[str, Any]]:
    if not db_path or not os.path.isfile(db_path):
        return []
    conn = sqlite3.connect(db_path, timeout=15.0)
    try:
        hit = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='biaoke_posts'"
        ).fetchone()
        if not hit:
            return []
        rows = conn.execute(
            "SELECT id, date, time, parent, layer, kind, text FROM biaoke_posts"
        ).fetchall()
    except sqlite3.Error:
        return []
    finally:
        conn.close()
    out: List[Dict[str, Any]] = []
    for r in rows:
        out.append(
            {
                "id": r[0],
                "date": r[1] or "",
                "time": r[2] or "",
                "parent": r[3] or "",
                "layer": int(r[4] or 0),
                "kind": r[5] or "post",
                "text": r[6] or "",
                "source": "db_overlay",
                "club": False,
            }
        )
    return out


def load_overlay_delta_posts() -> List[Dict[str, Any]]:
    """git 凍的 overlay 增量（無碟／CI 也能合併至今日）。"""
    try:
        from biaoke_overlay_sync import load_overlay_delta

        blob = load_overlay_delta() or {}
    except Exception:
        return []
    out: List[Dict[str, Any]] = []
    for row in blob.get("posts") or []:
        if not isinstance(row, dict):
            continue
        out.append(
            {
                "id": row.get("id"),
                "date": row.get("date") or "",
                "time": row.get("time") or "",
                "parent": row.get("parent") or "",
                "layer": int(row.get("layer") or 0),
                "kind": row.get("kind") or "post",
                "text": row.get("text") or "",
                "source": "overlay_delta",
                "club": False,
            }
        )
    return out


def load_corpus_rows(
    *,
    db_path: str = "",
    include_club: bool = True,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """合併 1709＋catchup＋overlay_delta＋DB overlay＋社團（後台）。

    同 id 以較長正文／較新為準。社團只後台。
    """
    from biaoke_archive import load_bundled_archive, load_bundled_club

    meta: Dict[str, Any] = {
        "archive_n": 0,
        "archive_replies": 0,
        "catchup_n": 0,
        "delta_n": 0,
        "db_n": 0,
        "club_n": 0,
        "club_replies": 0,
        "merged_n": 0,
        "from": "",
        "to": "",
    }
    by_id: Dict[str, Dict[str, Any]] = {}

    def _put(row: Dict[str, Any], *, club: bool, source: str) -> None:
        aid = str(row.get("id") or "").strip()
        text = str(row.get("text") or "").strip()
        if not aid or not text:
            return
        prev = by_id.get(aid)
        packed = {
            "id": aid,
            "date": str(row.get("date") or ""),
            "time": str(row.get("time") or ""),
            "parent": str(row.get("parent") or ""),
            "layer": int(row.get("layer") or 0),
            "kind": str(row.get("kind") or "post"),
            "text": text,
            "source": source,
            "club": bool(club),
        }
        if prev is None or len(text) > len(str(prev.get("text") or "")):
            by_id[aid] = packed
        elif str(row.get("date") or "") > str(prev.get("date") or ""):
            by_id[aid] = packed

    pub = load_bundled_archive() or {}
    for row in pub.get("posts") or []:
        _put(row, club=False, source="archive_1709")
    meta["archive_n"] = int(pub.get("n") or 0)
    meta["archive_replies"] = int(pub.get("replies") or 0)

    try:
        from biaoke_desk import catchup_seed_rows

        catchup_rows = catchup_seed_rows() or []
    except Exception:
        catchup_rows = []
    for row in catchup_rows:
        _put(row, club=False, source="catchup")
    meta["catchup_n"] = len(
        [1 for r in by_id.values() if r.get("source") == "catchup"]
    )

    for row in load_overlay_delta_posts():
        _put(row, club=False, source="overlay_delta")
    meta["delta_n"] = len(
        [1 for r in by_id.values() if r.get("source") == "overlay_delta"]
    )

    db_rows = load_db_posts(db_path)
    for row in db_rows:
        _put(row, club=False, source="db_overlay")
    # 以實際庫列數為準（同文被 delta 先佔 source 時仍算有 overlay）
    meta["db_n"] = len(db_rows)

    if include_club:
        club = load_bundled_club() or {}
        for row in club.get("posts") or []:
            _put(row, club=True, source="archive_club")
        meta["club_n"] = int(club.get("n") or 0)
        meta["club_replies"] = int(club.get("replies") or 0)

    rows = list(by_id.values())
    rows.sort(key=lambda r: (str(r.get("date") or ""), str(r.get("time") or ""), str(r.get("id"))))
    dates = [str(r.get("date") or "") for r in rows if r.get("date")]
    meta["merged_n"] = len(rows)
    meta["from"] = min(dates) if dates else ""
    meta["to"] = max(dates) if dates else ""
    return rows, meta


def _ensure_bucket(
    buckets: Dict[str, Dict[str, Any]],
    *,
    theme: str,
    slug: str,
    rule: str,
    core: bool,
    row: Dict[str, Any],
    excerpt: str,
) -> None:
    key = _rule_key(theme, rule)
    club = bool(row.get("club"))
    leave = _is_leave_only(str(row.get("text") or ""))
    core_flag = bool(core) and not leave and not club
    # 社團只後台內化：可進原子但 core=False、source=club_backend
    source = "club_backend" if club else "self"
    if key not in buckets:
        # atom_id 帶 rule 指紋，避免同 slug 不同規則撞名
        buckets[key] = {
            "atom_id": _atom_id(theme, f"{slug}_{key[:6]}"),
            "theme": theme,
            "theme_label": THEME_LABEL.get(theme, theme),
            "rule": rule,
            "core": core_flag,
            "source": source,
            "levels": _levels_in(excerpt) or _levels_in(str(row.get("text") or "")),
            "provenance": [_prov(row, excerpt, club=club)],
            "hit_n": 1,
            "leave_noise": bool(leave),
        }
        return
    atom = buckets[key]
    atom["hit_n"] = int(atom.get("hit_n") or 1) + 1
    # 自有公開文可把 core 往上抬；社團／離開不可
    if core_flag:
        atom["core"] = True
        if atom.get("source") == "club_backend":
            atom["source"] = "self"
    prov = atom.setdefault("provenance", [])
    pid = str(row.get("id") or "")
    if pid and all(str(p.get("post_id")) != pid for p in prov):
        if len(prov) < 5:
            prov.append(_prov(row, excerpt, club=club))
    # 補位階數字
    lv = atom.setdefault("levels", [])
    for x in _levels_in(excerpt):
        if x not in lv and len(lv) < 8:
            lv.append(x)


def extract_atoms(rows: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """從列抽出觀測原子；同規則去重，核心優先可操作句。"""
    buckets: Dict[str, Dict[str, Any]] = {}

    for row in rows:
        text = _norm(str(row.get("text") or ""))
        if len(text) < 10:
            continue
        leave = _is_leave_only(text)

        # --- 三層 ---
        if _THREE.search(text) or (_NIGHT.search(text) and (_MORNING_TX.search(text) or _SPOT.search(text))):
            excerpt = _best_sentence(text, _THREE if _THREE.search(text) else _NIGHT)
            if re.search(r"e-?mini|小道瓊|那指期|美期", text, re.I):
                _ensure_bucket(
                    buckets,
                    theme="three_layer",
                    slug="us_futures_to_tx_spot",
                    rule="美期／e-mini 隔夜方向先參考 → 台指夜盤結構 → 早盤 TX／現貨加權確認",
                    core=not leave,
                    row=row,
                    excerpt=excerpt,
                )
            _ensure_bucket(
                buckets,
                theme="three_layer",
                slug="night_to_spot",
                rule="夜盤先看結構／下降壓或支撐是否有效 → 早盤台指確認 → 現貨加權驗證（他常先講夜盤隔日才講日盤）",
                core=not leave,
                row=row,
                excerpt=excerpt,
            )
            # 具體夜盤條件句另成原子（指數級 4+ 位數字才 core）
            if _NIGHT.search(text) and _LEVEL_NUM.search(text) and _LEVEL_CTX.search(text):
                ex2 = _best_sentence(text, _NIGHT)
                raw_lv = _levels_in(ex2) or _levels_in(text)
                idx_lv = [x for x in raw_lv if len(x.split(".")[0]) >= 4]
                if idx_lv and _INDEX_BATTLE.search(text):
                    lv = "／".join(idx_lv[:3])
                    _ensure_bucket(
                        buckets,
                        theme="three_layer",
                        slug=f"night_level_{lv.replace('.', '_').replace('／', '_')[:24]}",
                        rule=f"夜盤觀測位：{lv}（有效穿刺／站上或跌破才改結構判斷）",
                        core=True,
                        row=row,
                        excerpt=ex2,
                    )

        # --- SOX ---
        if _SOX.search(text):
            excerpt = _best_sentence(text, _SOX)
            rule = "大盤位階對照費半／那指結構（關聯度極高時用來重訂或確認台股位階）"
            if "頭肩" in text:
                rule = "費半型態（如頭肩）可當台股大盤關聯觀測，不單獨當買訊"
            _ensure_bucket(
                buckets,
                theme="sox",
                slug="sox_link",
                rule=rule,
                core=not leave,
                row=row,
                excerpt=excerpt,
            )

        # --- 鐵律 ---
        for slug, pat, rule in _IRON:
            if pat.search(text):
                _ensure_bucket(
                    buckets,
                    theme="iron_rule",
                    slug=slug,
                    rule=rule,
                    core=True,
                    row=row,
                    excerpt=_best_sentence(text, pat),
                )

        # --- 改口 ---
        if _RETRACT.search(text):
            excerpt = _best_sentence(text, _RETRACT)
            lv = "／".join(_levels_in(excerpt) or _levels_in(text)[:3])
            if lv:
                rule = f"改口／重訂條件觸發後，舊位 {lv} 只當參考，以後文為準"
                slug = f"retract_{lv.replace('.', '_')[:20]}"
                core = True
            else:
                rule = "位階是預估：動態修正／被誤導／結構不符就重訂；以後文改口壓前文"
                slug = "revise_general"
                core = bool(_INDEX_BATTLE.search(text))
            _ensure_bucket(
                buckets,
                theme="retract",
                slug=slug,
                rule=rule,
                core=core and not leave,
                row=row,
                excerpt=excerpt,
            )

        # --- 他點過的位（深度優先：大盤／夜盤戰場；個股短價不堆）---
        if _LEVEL_CTX.search(text) and _LEVEL_NUM.search(text):
            indexish = bool(_INDEX_BATTLE.search(text))
            levels = _levels_in(text)
            # 指數位通常 ≥4 位數；過濾明顯個股短價堆疊
            idx_levels = [x for x in levels if len(x.split(".")[0]) >= 4]
            if indexish and idx_levels:
                excerpt = _best_sentence(text, _LEVEL_CTX)
                lv = "／".join(idx_levels[:4])
                rule = f"大盤／期點觀測位：{lv}（支撐／壓力／穿刺條件以原文為準）"
                _ensure_bucket(
                    buckets,
                    theme="level",
                    slug=f"lv_{'_'.join(idx_levels[:3]).replace('.', '')[:28]}",
                    rule=rule,
                    core=True,
                    row=row,
                    excerpt=excerpt,
                )
            elif (not indexish) and levels and _NIGHT.search(text):
                # 夜盤個股／期點夾敘：附檔
                excerpt = _best_sentence(text, _LEVEL_CTX)
                lv = "／".join(levels[:3])
                _ensure_bucket(
                    buckets,
                    theme="level",
                    slug=f"lv_aux_{'_'.join(levels[:2]).replace('.', '')[:24]}",
                    rule=f"附檔觀測位：{lv}",
                    core=False,
                    row=row,
                    excerpt=excerpt,
                )

        # --- 量價 ---
        if _PV.search(text):
            excerpt = _best_sentence(text, _PV)
            if "量先價行" in text or "爆大量" in text:
                rule = "量先價行：爆大量日高＝壓、低＝撐；站上撐／壓轉撐後等價穩量縮才談介入（觀測／非主買訊）"
                slug = "vol_lead_price"
                core = True
            elif "量價結構" in text and ("台積電" in text or "決勝" in text):
                rule = "多標籤並存時用台積電量價結構決勝一條路徑（他稱不公開細節，只留觀測口）"
                slug = "tsmc_pv_tiebreak"
                core = True
            else:
                rule = "觀盤看型態／K／量價結構；均線指標不當主判"
                slug = "pv_over_ma"
                core = "量價結構" in text
            _ensure_bucket(
                buckets,
                theme="pv_structure",
                slug=slug,
                rule=rule,
                core=core and not leave,
                row=row,
                excerpt=excerpt,
            )

        # --- 形態 ---
        if _PATTERN.search(text):
            excerpt = _best_sentence(text, _PATTERN)
            m = _PATTERN.search(text)
            name = m.group(1) if m else "形態"
            rule = f"形態觀測：{name}（完成／假突破／右肩等以他原文條件為準）"
            _ensure_bucket(
                buckets,
                theme="pattern",
                slug=f"pat_{name}",
                rule=rule,
                core=bool(_INDEX_BATTLE.search(text) or "頸線" in text),
                row=row,
                excerpt=excerpt,
            )

        # --- 關鍵K ---
        if _KEY_K.search(text):
            excerpt = _best_sentence(text, _KEY_K)
            _ensure_bucket(
                buckets,
                theme="key_k",
                slug="key_bar",
                rule="關鍵K／缺口／長紅黑當結構確認或破壞的輔助觀察，不單根當買訊",
                core=bool(_INDEX_BATTLE.search(text)),
                row=row,
                excerpt=excerpt,
            )

        # --- 碎形／軌道 ---
        if _FRACTAL.search(text) and (_INDEX_BATTLE.search(text) or "碎形" in text):
            excerpt = _best_sentence(text, _FRACTAL)
            rule = "用上升／下降軌道（或碎形線）研判細微波結構破壞與轉折啟動"
            _ensure_bucket(
                buckets,
                theme="fractal",
                slug="channel_fractal",
                rule=rule,
                core=True,
                row=row,
                excerpt=excerpt,
            )

        # --- 大盤→個股 ---
        if _STOCK_OBS.search(text):
            excerpt = _best_sentence(text, _STOCK_OBS)
            if "龍頭" in text or "族群" in text:
                rule = "族群開口→找整理完成／量價轉強／先過前高的龍頭與次級（大盤位階對時才加重）"
                slug = "sector_leader"
            elif "台積電" in text:
                rule = "大盤多標籤時對照台積電位階／量價，不反過來改黃金買點"
                slug = "tsmc_as_index_proxy"
            else:
                rule = "個股觀測跟大盤／族群結構走，半山腰只當短打觀察"
                slug = "stock_follow_index"
            _ensure_bucket(
                buckets,
                theme="stock_observe",
                slug=slug,
                rule=rule,
                core=not leave,
                row=row,
                excerpt=excerpt,
            )

        # 純空話附檔：有觀盤字但抽不出位／鐵律
        if leave:
            _ensure_bucket(
                buckets,
                theme="misc_observe",
                slug="leave_noise_attach",
                rule="離開／壓力敘事僅附檔，不准進產品規則核心",
                core=False,
                row=row,
                excerpt=_clip(text, 96),
            )

    atoms = list(buckets.values())

    def _sort_key(a: Dict[str, Any]) -> Tuple:
        theme = str(a.get("theme") or "")
        try:
            ti = THEME_ORDER.index(theme)
        except ValueError:
            ti = 99
        return (0 if a.get("core") else 1, ti, -int(a.get("hit_n") or 0), str(a.get("atom_id")))

    capped = _cap_level_atoms(atoms)
    capped.sort(key=_sort_key)
    return capped


def _cap_level_atoms(
    atoms: List[Dict[str, Any]],
    *,
    max_level_core: int = 48,
    max_level_attach: int = 36,
) -> List[Dict[str, Any]]:
    """位階原子易爆炸：核心留 hit 高者；附檔再截斷。"""
    levels = [a for a in atoms if a.get("theme") == "level"]
    others = [a for a in atoms if a.get("theme") != "level"]
    levels.sort(key=lambda a: (-int(a.get("hit_n") or 0), str(a.get("atom_id"))))
    kept_levels: List[Dict[str, Any]] = []
    core_n = 0
    attach_n = 0
    for a in levels:
        a = dict(a)
        if a.get("core"):
            core_n += 1
            if core_n > max_level_core:
                a["core"] = False
                a["note"] = "位階核心額滿，降附檔"
        if not a.get("core"):
            # 單次命中且無夜盤／改口語的附檔直接丟（深度優先）
            if int(a.get("hit_n") or 0) < 2 and not a.get("note"):
                blob = " ".join(
                    str(p.get("excerpt") or "") for p in (a.get("provenance") or [])
                )
                if not (_NIGHT.search(blob) or _RETRACT.search(blob)):
                    continue
            attach_n += 1
            if attach_n > max_level_attach:
                continue
        kept_levels.append(a)
    return others + kept_levels


def coverage_report(atoms: Sequence[Dict[str, Any]], meta: Dict[str, Any]) -> Dict[str, Any]:
    by_theme: Dict[str, int] = defaultdict(int)
    core_by: Dict[str, int] = defaultdict(int)
    for a in atoms:
        t = str(a.get("theme") or "")
        by_theme[t] += 1
        if a.get("core"):
            core_by[t] += 1
    gaps: List[str] = []
    if by_theme.get("sox", 0) < 3:
        gaps.append("SOX／費半連動原文偏少，需 BK-CHART／後續 overlay 補圖註")
    if int(meta.get("db_n") or 0) <= 0 and int(meta.get("delta_n") or 0) <= 0:
        gaps.append(
            "DB overlay 與 overlay_delta 皆空；需跑 scripts/biaoke_sync_overlay_heal.py "
            "（Render 碟或本機）補至今日"
        )
    to_s = str(meta.get("to") or "")
    today = datetime.now(TAIPEI).strftime("%Y-%m-%d")
    # 深夜／他尚未發當日文：差 1 曆日不算缺；≥2 天才標落後
    if to_s and to_s < today:
        try:
            d0 = datetime.strptime(to_s, "%Y-%m-%d").date()
            d1 = datetime.strptime(today, "%Y-%m-%d").date()
            if (d1 - d0).days >= 2:
                gaps.append(f"語料末日 {to_s} 早於今日 {today}；overlay 仍落後")
        except ValueError:
            gaps.append(f"語料末日 {to_s} 早於今日 {today}；overlay 仍落後")
    if by_theme.get("three_layer", 0) and not any(
        "e-mini" in str(a.get("rule") or "").lower() or "美期" in str(a.get("rule") or "")
        for a in atoms
        if a.get("theme") == "three_layer"
    ):
        gaps.append("美期／e-mini 明文鏈路稀缺，三層鏈多從夜盤台指起算")
    if by_theme.get("key_k", 0) < 3:
        gaps.append("關鍵K 獨立表述少，多夾在形態／細微波句")
    if by_theme.get("fractal", 0) < 3:
        gaps.append("碎形專名少，多數是上升／下降軌道用語")
    return {
        "by_theme": dict(by_theme),
        "core_by_theme": dict(core_by),
        "gaps": gaps,
        "core_n": sum(1 for a in atoms if a.get("core")),
        "attach_n": sum(1 for a in atoms if not a.get("core")),
    }


def build_payload(
    *,
    db_path: str = "",
    include_club: bool = True,
) -> Dict[str, Any]:
    rows, meta = load_corpus_rows(db_path=db_path, include_club=include_club)
    atoms = extract_atoms(rows)
    cov = coverage_report(atoms, meta)
    now = datetime.now(TAIPEI).strftime("%Y-%m-%d %H:%M:%S")
    return {
        "track": "BK-CORPUS",
        "generated_at_taipei": now,
        "warning": "試標・推論／非他原文・非買訊・對質未過閘",
        "corpus": meta,
        "atom_n": len(atoms),
        "coverage": cov,
        "atoms": atoms,
    }


def write_atoms_json(payload: Dict[str, Any], path: str = "") -> str:
    dest = path or ATOMS_JSON
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    tmp = dest + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    os.replace(tmp, dest)
    return dest


def write_atoms_index_md(payload: Dict[str, Any], path: str = "") -> str:
    dest = path or ATOMS_MD
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    cov = payload.get("coverage") or {}
    meta = payload.get("corpus") or {}
    lines: List[str] = [
        "# 觀測原子索引（BK-CORPUS）",
        "",
        f"產生：`{payload.get('generated_at_taipei')}`（Asia/Taipei）",
        "",
        f"語料：公開主文 {meta.get('archive_n')}＋回文 {meta.get('archive_replies')}；"
        f"catchup {meta.get('catchup_n')}；overlay_delta {meta.get('delta_n')}；"
        f"DB overlay {meta.get('db_n')}；社團後台主文 {meta.get('club_n')}＋回文 {meta.get('club_replies')}；"
        f"合併列 {meta.get('merged_n')}（{meta.get('from')}→{meta.get('to')}）。",
        "",
        f"原子 **{payload.get('atom_n')}**（核心 {cov.get('core_n')}／附檔 {cov.get('attach_n')}）。",
        "",
        "警語：試標・推論／非他原文・非買訊・對質未過閘。社團只後台。不准改黃金買點。",
        "",
        "## 主題覆蓋",
        "",
    ]
    by = cov.get("by_theme") or {}
    core_by = cov.get("core_by_theme") or {}
    for theme in THEME_ORDER:
        if theme not in by:
            continue
        lines.append(
            f"- **{THEME_LABEL.get(theme, theme)}**：{by[theme]}（核心 {core_by.get(theme, 0)}）"
        )
    gaps = cov.get("gaps") or []
    if gaps:
        lines.extend(["", "## 缺料", ""])
        for g in gaps:
            lines.append(f"- {g}")
    lines.extend(["", "## 核心原子（可操作）", ""])
    for a in payload.get("atoms") or []:
        if not a.get("core"):
            continue
        prov = (a.get("provenance") or [{}])[0]
        stamp = prov.get("taipei") or ""
        pid = prov.get("post_id") or ""
        lines.append(
            f"- `{a.get('atom_id')}` 〔{a.get('theme_label')}〕 {a.get('rule')} "
            f"— {stamp}／{pid}／hit={a.get('hit_n')}"
        )
    lines.extend(
        [
            "",
            "## 機器可讀",
            "",
            "完整出處見同目錄 `atoms_latest.json`。",
            "",
        ]
    )
    with open(dest, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))
    return dest


def run_extract(
    *,
    db_path: str = "",
    out_json: str = "",
    out_md: str = "",
    include_club: bool = True,
) -> Dict[str, Any]:
    payload = build_payload(db_path=db_path, include_club=include_club)
    write_atoms_json(payload, out_json or ATOMS_JSON)
    write_atoms_index_md(payload, out_md or ATOMS_MD)
    return payload
