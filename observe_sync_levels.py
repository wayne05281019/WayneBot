# -*- coding: utf-8 -*-
"""SYNC-LEVELS：他點過的位 → 可畫清單 → 三窗／壓撐／有點名結構。

只認他自己點過的價；近窗官方柱可驗則標驗況；不准發明新價。
非買訊；固定警語；盤中未收不當收。Asia/Taipei。
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo

TAIPEI = ZoneInfo("Asia/Taipei")

ROOT = Path(__file__).resolve().parent
MANUAL = ROOT / "docs" / "expert_notes" / "飆客" / "observe_manual"
ATOMS_PATH = MANUAL / "atoms_latest.json"
EVIDENCE_PATH = MANUAL / "segment_evidence.json"
DRAWABLE_PATH = MANUAL / "drawable_levels_latest.json"
DRAWABLE_MD = MANUAL / "drawable_levels.md"

PHONE_WARNING_FIXED = "試標・推論／非他原文・非買訊・對質未過閘"
TRACK = "SYNC-LEVELS"

# 大盤／期點可畫窗（與 extract_index_levels／教具梯大致對齊）
_INDEX_LO = 15000.0
_INDEX_HI = 60000.0
# 個股絕對價：過高當指數；過低雜訊略
_STOCK_LO = 5.0
_STOCK_HI = 12000.0

_LEVEL_NUM = re.compile(r"(?<![\d.])(\d{4,5}(?:\.\d+)?)(?![\d])")
_SID_RE = re.compile(r"(?<!\d)(\d{4})(?:-?[A-Za-z]{0,2})?(?!\d)")
_IDX_CTX = re.compile(r"(大盤|加權|台指|台指期|夜盤|現貨|TWII|細微波)")
_STOCK_CTX = re.compile(
    r"(股|KY|目標|頸線|支撐|壓力|不破|跌破|站上|前高|漲停)"
)

# 已知他寫死個股絕對價（與 biaoke_next_support.WRITTEN_ABSOLUTE_TARGETS 對齊）
_SEED_STOCK: Dict[str, Tuple[Dict[str, Any], ...]] = {
    "3081": (
        {
            "price": 2000.0,
            "note": "第二段下殺頸線",
            "role": "down",
            "as_of": "20261025",
            "post_id": "written-3081-2000",
        },
    ),
    "3017": (
        {
            "price": 3000.0,
            "note": "先測",
            "role": "down",
            "as_of": "20261025",
            "post_id": "written-3017-3000",
        },
        {
            "price": 2700.0,
            "note": "守不住頭部確認再測",
            "role": "down",
            "as_of": "20261025",
            "post_id": "written-3017-2700",
        },
    ),
}


def _taipei_now_stamp() -> str:
    return datetime.now(TAIPEI).strftime("%Y-%m-%d %H:%M:%S")


def _ymd(raw: Any) -> str:
    s = str(raw or "").strip()
    digits = re.sub(r"\D", "", s)
    if len(digits) >= 8:
        return digits[:8]
    return ""


def _num(raw: Any) -> float:
    try:
        return float(str(raw or "").replace(",", "").strip())
    except (TypeError, ValueError):
        return 0.0


def _load_json(path: Path) -> Dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _round_key(px: float, *, kind: str) -> float:
    if kind == "index":
        return round(float(px), 1)
    return round(float(px), 2)


def _is_index_px(px: float) -> bool:
    return _INDEX_LO <= float(px) <= _INDEX_HI


def _is_stock_px(px: float) -> bool:
    return _STOCK_LO <= float(px) <= _STOCK_HI and not _is_index_px(px)


def _prov_stamp(
    *,
    source: str,
    post_id: str = "",
    taipei: str = "",
    as_of: str = "",
    atom_id: str = "",
    evidence_id: str = "",
    excerpt: str = "",
) -> Dict[str, Any]:
    return {
        "source": source,
        "post_id": str(post_id or ""),
        "taipei": str(taipei or ""),
        "as_of": _ymd(as_of) or _ymd(taipei),
        "atom_id": str(atom_id or ""),
        "evidence_id": str(evidence_id or ""),
        "excerpt": str(excerpt or "")[:120],
    }


def _merge_level(
    bucket: Dict[Tuple[str, float], Dict[str, Any]],
    *,
    kind: str,
    price: float,
    instrument: str,
    role: str,
    stamp: Dict[str, Any],
    label: str = "",
) -> None:
    px = _num(price)
    if px <= 0:
        return
    if kind == "index" and not _is_index_px(px):
        return
    if kind == "stock" and not _is_stock_px(px):
        return
    key = (str(instrument or ("TWII" if kind == "index" else "")), _round_key(px, kind=kind))
    if not key[0] and kind == "stock":
        return
    row = bucket.get(key)
    if row is None:
        row = {
            "kind": kind,
            "instrument": key[0],
            "price": key[1],
            "role": str(role or "點位"),
            "label": str(label or ""),
            "provenance": [],
            "hit_n": 0,
            "buy_signal": False,
            "phone_warning": PHONE_WARNING_FIXED,
            "official_verify": {"status": "unchecked"},
        }
        bucket[key] = row
    prov = list(row.get("provenance") or [])
    # 同出處不重複堆
    pid = str(stamp.get("post_id") or "")
    eid = str(stamp.get("evidence_id") or "")
    aid = str(stamp.get("atom_id") or "")
    dup = False
    for p in prov:
        if pid and str(p.get("post_id") or "") == pid:
            dup = True
            break
        if eid and str(p.get("evidence_id") or "") == eid:
            dup = True
            break
        if aid and not pid and str(p.get("atom_id") or "") == aid:
            dup = True
            break
    if not dup:
        prov.append(stamp)
        row["provenance"] = prov
        row["hit_n"] = len(prov)
    if label and not row.get("label"):
        row["label"] = label
    if role and row.get("role") in ("", "點位"):
        row["role"] = role


def _levels_from_atoms(atoms_blob: Dict[str, Any]) -> Dict[Tuple[str, float], Dict[str, Any]]:
    bucket: Dict[Tuple[str, float], Dict[str, Any]] = {}
    atoms = atoms_blob.get("atoms") or []
    if not isinstance(atoms, list):
        return bucket
    for a in atoms:
        if not isinstance(a, dict):
            continue
        theme = str(a.get("theme") or "")
        # 離開敘事／雜訊不進可畫核心
        if a.get("leave_noise"):
            continue
        levels = a.get("levels") or []
        if not levels:
            continue
        provs = a.get("provenance") or [{}]
        p0 = provs[0] if isinstance(provs, list) and provs else {}
        excerpt = " ".join(
            str(p.get("excerpt") or "") for p in (provs if isinstance(provs, list) else [])
        )
        rule = str(a.get("rule") or "")
        blob = f"{excerpt} {rule}"
        indexish = bool(_IDX_CTX.search(blob)) or theme in (
            "level",
            "three_layer",
            "iron_rule",
            "retract",
        )
        # 個股點名：文內四碼＋股語境（且非整段只講大盤）
        sids = []
        if theme == "stock_observe" or (_STOCK_CTX.search(blob) and not indexish):
            for m in _SID_RE.finditer(blob):
                sid = m.group(1)
                if sid in _SEED_STOCK or (_STOCK_CTX.search(blob[max(0, m.start() - 12) : m.end() + 24])):
                    sids.append(sid)
        for raw in levels:
            px = _num(raw)
            if px <= 0:
                continue
            stamp = _prov_stamp(
                source="atoms_latest",
                post_id=str(p0.get("post_id") or ""),
                taipei=str(p0.get("taipei") or ""),
                atom_id=str(a.get("atom_id") or ""),
                excerpt=str(p0.get("excerpt") or ""),
            )
            if indexish and _is_index_px(px):
                role = "支撐" if "支撐" in rule or "低" in rule else (
                    "壓力" if "壓" in rule or "高" in rule else "點位"
                )
                _merge_level(
                    bucket,
                    kind="index",
                    price=px,
                    instrument="TWII",
                    role=role,
                    stamp=stamp,
                    label=f"他點・{theme}",
                )
            elif sids and _is_stock_px(px):
                for sid in sids[:3]:
                    _merge_level(
                        bucket,
                        kind="stock",
                        price=px,
                        instrument=sid,
                        role="目標",
                        stamp=stamp,
                        label=f"他點名・{sid}",
                    )
    return bucket


def _levels_from_evidence(ev: Dict[str, Any]) -> Dict[Tuple[str, float], Dict[str, Any]]:
    bucket: Dict[Tuple[str, float], Dict[str, Any]] = {}
    for s in ev.get("samples") or []:
        if not isinstance(s, dict):
            continue
        # 只認 his_levels（他點過）；不准把試標段號發明價灌進可畫清單
        his = s.get("his_levels") or []
        if not his:
            continue
        pot = str(s.get("label_pot") or "")
        # trial_infer 列若仍有 his_levels＝他原文價，可收；純試標無 his 已 skip
        stamp = _prov_stamp(
            source="segment_evidence",
            as_of=str(s.get("as_of") or ""),
            evidence_id=str(s.get("id") or ""),
            excerpt=str(s.get("his_claim_zh") or "")[:120],
            post_id=str(s.get("provenance") or "")[:80],
        )
        for raw in his:
            px = _num(raw)
            if not _is_index_px(px):
                continue
            _merge_level(
                bucket,
                kind="index",
                price=px,
                instrument="TWII",
                role="點位",
                stamp=stamp,
                label="段證・他點" if pot != "trial_infer" else "段證・他點（列含試標）",
            )
    return bucket


def _levels_from_snaps(db_path: str) -> Dict[Tuple[str, float], Dict[str, Any]]:
    bucket: Dict[Tuple[str, float], Dict[str, Any]] = {}
    if not db_path or not os.path.isfile(db_path):
        return bucket
    try:
        con = sqlite3.connect(db_path, timeout=8.0)
    except sqlite3.Error:
        return bucket
    try:
        row = con.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='biaoke_level_snaps'"
        ).fetchone()
        if not row:
            return bucket
        rows = con.execute(
            "SELECT post_id, as_of, IFNULL(snippet,''), IFNULL(verdict,'') "
            "FROM biaoke_level_snaps ORDER BY as_of DESC LIMIT 400"
        ).fetchall()
    except sqlite3.Error:
        return bucket
    finally:
        try:
            con.close()
        except Exception:
            pass
    for post_id, as_of, snippet, _verdict in rows:
        text = str(snippet or "")
        if not text:
            continue
        stamp = _prov_stamp(
            source="biaoke_level_snaps",
            post_id=str(post_id or ""),
            as_of=str(as_of or ""),
            excerpt=text[:120],
        )
        indexish = bool(_IDX_CTX.search(text))
        for m in _LEVEL_NUM.finditer(text):
            px = _num(m.group(1))
            if indexish and _is_index_px(px):
                _merge_level(
                    bucket,
                    kind="index",
                    price=px,
                    instrument="TWII",
                    role="點位",
                    stamp=stamp,
                    label="口語位階軌",
                )
    return bucket


def _levels_from_seed_stock() -> Dict[Tuple[str, float], Dict[str, Any]]:
    bucket: Dict[Tuple[str, float], Dict[str, Any]] = {}
    for sid, rows in _SEED_STOCK.items():
        for row in rows:
            px = _num(row.get("price"))
            stamp = _prov_stamp(
                source="written_absolute",
                post_id=str(row.get("post_id") or ""),
                as_of=str(row.get("as_of") or ""),
                excerpt=str(row.get("note") or ""),
            )
            _merge_level(
                bucket,
                kind="stock",
                price=px,
                instrument=sid,
                role=str(row.get("role") or "down"),
                stamp=stamp,
                label=f"原文目標・{sid}",
            )
    return bucket


def _levels_from_mentions_claims(
    db_path: str,
) -> Dict[Tuple[str, float], Dict[str, Any]]:
    """DB 點名＋claims lo/hi（有真價才收）。本機 overlay 空＝空桶。"""
    bucket: Dict[Tuple[str, float], Dict[str, Any]] = {}
    if not db_path or not os.path.isfile(db_path):
        return bucket
    try:
        con = sqlite3.connect(db_path, timeout=8.0)
    except sqlite3.Error:
        return bucket
    try:
        has_claims = con.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='biaoke_claims'"
        ).fetchone()
        if has_claims:
            for sid, lo, hi, post_id, post_date, snip in con.execute(
                "SELECT stock_id, lo, hi, post_id, post_date, IFNULL(snippet,'') "
                "FROM biaoke_claims WHERE IFNULL(club,0)=0 "
                "AND IFNULL(stock_id,'')!='' LIMIT 800"
            ):
                sid_s = str(sid or "").strip()
                if not sid_s:
                    continue
                for raw in (lo, hi):
                    px = _num(raw)
                    if not _is_stock_px(px):
                        continue
                    stamp = _prov_stamp(
                        source="biaoke_claims",
                        post_id=str(post_id or ""),
                        as_of=str(post_date or ""),
                        excerpt=str(snip or "")[:120],
                    )
                    _merge_level(
                        bucket,
                        kind="stock",
                        price=px,
                        instrument=sid_s,
                        role="點位",
                        stamp=stamp,
                        label=f"claims・{sid_s}",
                    )
        has_facts = con.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='biaoke_day_facts'"
        ).fetchone()
        if has_facts:
            for sid, claimed, post_id, post_date, snip in con.execute(
                "SELECT stock_id, claimed, post_id, post_date, IFNULL(snippet,'') "
                "FROM biaoke_day_facts WHERE IFNULL(club,0)=0 "
                "AND IFNULL(claimed,'')!='' LIMIT 800"
            ):
                sid_s = str(sid or "").strip()
                text = str(claimed or "")
                for m in _LEVEL_NUM.finditer(text):
                    px = _num(m.group(1))
                    if not _is_stock_px(px):
                        continue
                    stamp = _prov_stamp(
                        source="biaoke_day_facts",
                        post_id=str(post_id or ""),
                        as_of=str(post_date or ""),
                        excerpt=f"{text}｜{str(snip or '')[:80]}",
                    )
                    _merge_level(
                        bucket,
                        kind="stock",
                        price=px,
                        instrument=sid_s,
                        role="點位",
                        stamp=stamp,
                        label=f"day_facts・{sid_s}",
                    )
    except sqlite3.Error:
        return bucket
    finally:
        try:
            con.close()
        except Exception:
            pass
    return bucket


def _merge_buckets(
    *buckets: Dict[Tuple[str, float], Dict[str, Any]],
) -> Dict[Tuple[str, float], Dict[str, Any]]:
    out: Dict[Tuple[str, float], Dict[str, Any]] = {}
    for b in buckets:
        for key, row in b.items():
            if key not in out:
                out[key] = dict(row)
                out[key]["provenance"] = list(row.get("provenance") or [])
                continue
            for stamp in row.get("provenance") or []:
                _merge_level(
                    out,
                    kind=str(row.get("kind") or "index"),
                    price=float(row.get("price") or 0),
                    instrument=str(row.get("instrument") or ""),
                    role=str(row.get("role") or "點位"),
                    stamp=dict(stamp),
                    label=str(row.get("label") or ""),
                )
    return out


def _last_closed_ymd(db_path: str, symbol: str = "TWII") -> str:
    """官方已收完整日；盤中未收不當收。"""
    if not db_path or not os.path.isfile(db_path):
        return ""
    try:
        con = sqlite3.connect(db_path, timeout=8.0)
    except sqlite3.Error:
        return ""
    try:
        row = con.execute(
            "SELECT MAX(date) FROM index_daily WHERE symbol=? AND close IS NOT NULL",
            (str(symbol or "TWII").upper(),),
        ).fetchone()
    except sqlite3.Error:
        return ""
    finally:
        try:
            con.close()
        except Exception:
            pass
    ymd = _ymd(row[0] if row else "")
    # 若今天仍在盤中且庫末日＝今天：仍可視為未定稿 → 呼叫端用 as_of 對近窗，
    # 但「當收」驗證只用完整日；此處只回庫內最大日，驗證函式再擋盤中。
    return ymd


def _session_may_be_unclosed(now: Optional[datetime] = None) -> bool:
    dt = now or datetime.now(TAIPEI)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TAIPEI)
    else:
        dt = dt.astimezone(TAIPEI)
    # 台股常規 09:00–13:30；13:30 前今天柱不准當收
    minutes = dt.hour * 60 + dt.minute
    return (9 * 60) <= minutes < (13 * 60 + 30)


def verify_level_near_window(
    db_path: str,
    price: float,
    *,
    as_of: str = "",
    symbol: str = "TWII",
    window: int = 8,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """近窗官方高低是否碰到他點價。盤中未收日不當收。"""
    out: Dict[str, Any] = {
        "status": "no_bars",
        "symbol": str(symbol or "TWII").upper(),
        "price": float(price),
        "as_of_used": "",
        "touched": False,
        "note_zh": "",
    }
    px = _num(price)
    if px <= 0 or not db_path:
        out["status"] = "skip"
        out["note_zh"] = "無價或無庫"
        return out
    ymd = _ymd(as_of) or _last_closed_ymd(db_path, out["symbol"])
    if not ymd:
        out["note_zh"] = "無官方末日"
        return out
    today = (now or datetime.now(TAIPEI)).astimezone(TAIPEI).strftime("%Y%m%d")
    if ymd == today and _session_may_be_unclosed(now):
        # 退一天：盤中未收不當收
        try:
            con = sqlite3.connect(db_path, timeout=8.0)
            row = con.execute(
                "SELECT MAX(date) FROM index_daily WHERE symbol=? AND date<? AND close IS NOT NULL",
                (out["symbol"], today),
            ).fetchone()
            con.close()
            ymd = _ymd(row[0] if row else "") or ymd
            if ymd == today:
                out["status"] = "intraday_skip"
                out["note_zh"] = "盤中未收不當收"
                out["as_of_used"] = ymd
                return out
        except sqlite3.Error:
            out["status"] = "intraday_skip"
            out["note_zh"] = "盤中未收不當收"
            return out
    try:
        con = sqlite3.connect(db_path, timeout=8.0)
        rows = con.execute(
            "SELECT date, open, high, low, close, volume FROM index_daily "
            "WHERE symbol=? AND date<=? ORDER BY date DESC LIMIT ?",
            (out["symbol"], ymd, int(window)),
        ).fetchall()
        con.close()
    except sqlite3.Error:
        out["note_zh"] = "讀柱失敗"
        return out
    if not rows:
        out["note_zh"] = "近窗無柱"
        return out
    out["as_of_used"] = str(rows[0][0] or ymd)
    touched = False
    for _d, _o, h, l, _c, _v in rows:
        try:
            hi, lo = float(h), float(l)
        except (TypeError, ValueError):
            continue
        if lo <= px <= hi:
            touched = True
            break
    out["touched"] = touched
    out["status"] = "touched" if touched else "not_touched"
    out["note_zh"] = "近窗K碰到" if touched else "近窗未碰到"
    out["window_n"] = len(rows)
    return out


def build_drawable_levels(
    *,
    db_path: str = "",
    atoms_path: Optional[Path] = None,
    evidence_path: Optional[Path] = None,
    verify: bool = True,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """彙整 atoms／segment_evidence／level snaps／claims → 可畫位清單。"""
    atoms = _load_json(atoms_path or ATOMS_PATH)
    evidence = _load_json(evidence_path or EVIDENCE_PATH)
    bucket = _merge_buckets(
        _levels_from_atoms(atoms),
        _levels_from_evidence(evidence),
        _levels_from_snaps(db_path),
        _levels_from_seed_stock(),
        _levels_from_mentions_claims(db_path),
    )
    levels = sorted(
        bucket.values(),
        key=lambda r: (
            0 if r.get("kind") == "index" else 1,
            str(r.get("instrument") or ""),
            -float(r.get("price") or 0),
        ),
    )
    if verify and db_path:
        for row in levels:
            if row.get("kind") != "index":
                # 個股近窗驗另軌；此版只標 unchecked／seed
                if str((row.get("provenance") or [{}])[0].get("source")) == "written_absolute":
                    row["official_verify"] = {
                        "status": "seed_written",
                        "note_zh": "原文絕對目標（非發明）",
                    }
                continue
            as_of = ""
            for p in row.get("provenance") or []:
                as_of = _ymd(p.get("as_of") or p.get("taipei")) or as_of
            row["official_verify"] = verify_level_near_window(
                db_path,
                float(row.get("price") or 0),
                as_of=as_of,
                now=now,
            )
    index_n = sum(1 for r in levels if r.get("kind") == "index")
    stock_n = sum(1 for r in levels if r.get("kind") == "stock")
    named_sids = sorted(
        {str(r.get("instrument")) for r in levels if r.get("kind") == "stock" and r.get("instrument")}
    )
    gaps: List[str] = []
    if not atoms.get("atoms"):
        gaps.append("缺 atoms_latest.json（BK-CORPUS 未落地）")
    if not (evidence.get("samples") or []):
        gaps.append("缺 segment_evidence.json（BK-WAVE 未落地）")
    if not db_path or not os.path.isfile(db_path):
        gaps.append("無行情庫：近窗官方柱驗略過／level_snaps／claims 空")
    else:
        if not _levels_from_snaps(db_path):
            gaps.append("biaoke_level_snaps 空或無表（本機 overlay 常空；Render 碟另併）")
        if not _levels_from_mentions_claims(db_path):
            gaps.append("biaoke_claims／day_facts 無個股價（點名結構靠 seed＋atoms）")
    return {
        "track": TRACK,
        "generated_at_taipei": _taipei_now_stamp(),
        "tz": "Asia/Taipei",
        "warning": PHONE_WARNING_FIXED,
        "buy_signal": False,
        "phone_sync": "observe_overlay",  # 觀測疊圖；非主買訊
        "n_levels": len(levels),
        "n_index": index_n,
        "n_stock": stock_n,
        "named_stock_ids": named_sids,
        "hooks": {
            "teach_trio": "attach_sync_levels_to_pack → pred_levels.tw／key_levels",
            "pressure_support": "written_targets_for 合併 → 壓撐／大量圖原文線",
            "lookup_structure": "僅 stock_was_named(sid) 時疊結構圖",
        },
        "gaps": gaps,
        "levels": levels,
    }


def save_drawable_levels(blob: Dict[str, Any], *, path: Optional[Path] = None) -> Path:
    out = path or DRAWABLE_PATH
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(blob, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    md = [
        f"# 可畫位清單（{TRACK}）",
        "",
        f"- 產生：`{blob.get('generated_at_taipei')}` Asia/Taipei",
        f"- 警語：{PHONE_WARNING_FIXED}",
        f"- 位總數：**{blob.get('n_levels')}**（指數 {blob.get('n_index')}／個股 {blob.get('n_stock')}）",
        f"- 有點名檔：{', '.join(blob.get('named_stock_ids') or []) or '—'}",
        f"- 非買訊；`buy_signal={blob.get('buy_signal')}`",
        "",
        "## 接到",
        "",
        f"- 三窗：`{(blob.get('hooks') or {}).get('teach_trio')}`",
        f"- 壓撐：`{(blob.get('hooks') or {}).get('pressure_support')}`",
        f"- 結構：`{(blob.get('hooks') or {}).get('lookup_structure')}`",
        "",
        "## 缺口",
        "",
    ]
    for g in blob.get("gaps") or []:
        md.append(f"- {g}")
    if not blob.get("gaps"):
        md.append("- （無）")
    md.append("")
    md.append("## 指數位（價高→低・最多 40）")
    md.append("")
    idx = [r for r in (blob.get("levels") or []) if r.get("kind") == "index"]
    for r in idx[:40]:
        p0 = (r.get("provenance") or [{}])[0]
        md.append(
            f"- `{r.get('price')}` {r.get('role')}・hit={r.get('hit_n')}・"
            f"{p0.get('source')}／{p0.get('post_id') or p0.get('evidence_id') or '—'}"
        )
    md.append("")
    md.append("## 個股位")
    md.append("")
    for r in [r for r in (blob.get("levels") or []) if r.get("kind") == "stock"]:
        p0 = (r.get("provenance") or [{}])[0]
        md.append(
            f"- `{r.get('instrument')}` `{r.get('price')}` {r.get('role')}・"
            f"{p0.get('source')}／{p0.get('post_id') or '—'}"
        )
    DRAWABLE_MD.write_text("\n".join(md) + "\n", encoding="utf-8")
    return out


def load_drawable_levels(
    *,
    path: Optional[Path] = None,
    rebuild_if_missing: bool = True,
    db_path: str = "",
) -> Dict[str, Any]:
    p = path or DRAWABLE_PATH
    blob = _load_json(p)
    if blob.get("levels"):
        return blob
    if not rebuild_if_missing:
        return {
            "track": TRACK,
            "warning": PHONE_WARNING_FIXED,
            "buy_signal": False,
            "n_levels": 0,
            "levels": [],
            "gaps": ["drawable_levels_latest.json 缺"],
        }
    blob = build_drawable_levels(db_path=db_path, verify=bool(db_path))
    try:
        save_drawable_levels(blob, path=p)
    except OSError:
        pass
    return blob


def index_drawable_levels(
    blob: Optional[Dict[str, Any]] = None,
    *,
    max_n: int = 24,
    min_hit: int = 1,
) -> List[Dict[str, Any]]:
    data = blob if blob is not None else load_drawable_levels()
    rows = [
        r
        for r in (data.get("levels") or [])
        if r.get("kind") == "index" and int(r.get("hit_n") or 0) >= int(min_hit)
    ]
    rows.sort(key=lambda r: (-int(r.get("hit_n") or 0), -float(r.get("price") or 0)))
    return rows[: max(0, int(max_n))]


def stock_drawable_levels(
    sid: str,
    blob: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    key = re.sub(r"\D", "", str(sid or ""))[:4]
    if not key:
        return []
    data = blob if blob is not None else load_drawable_levels()
    rows = [
        r
        for r in (data.get("levels") or [])
        if r.get("kind") == "stock" and str(r.get("instrument") or "") == key
    ]
    rows.sort(key=lambda r: -float(r.get("price") or 0))
    return rows


def stock_was_named(sid: str, blob: Optional[Dict[str, Any]] = None, db_path: str = "") -> bool:
    """該檔他有點名才准疊結構／壓撐原文位。"""
    key = re.sub(r"\D", "", str(sid or ""))[:4]
    if not key:
        return False
    if stock_drawable_levels(key, blob):
        return True
    if key in _SEED_STOCK:
        return True
    if db_path and os.path.isfile(db_path):
        try:
            con = sqlite3.connect(db_path, timeout=5.0)
            try:
                row = con.execute(
                    "SELECT 1 FROM biaoke_mentions WHERE stock_id=? LIMIT 1",
                    (key,),
                ).fetchone()
                if row:
                    return True
            finally:
                con.close()
        except sqlite3.Error:
            pass
    return False


def attach_sync_levels_to_pack(
    pack: Dict[str, Any],
    *,
    blob: Optional[Dict[str, Any]] = None,
    max_n: int = 16,
) -> Dict[str, Any]:
    """波浪位階三窗：把他點過的指數位併進 pred_levels.tw／key_levels。

    不准發明；已有同價略過；標警語；非買訊。
    """
    if not isinstance(pack, dict):
        return {}
    data = blob if blob is not None else load_drawable_levels(
        db_path=str(pack.get("db_path") or "")
    )
    pred = pack.get("pred_levels") if isinstance(pack.get("pred_levels"), dict) else {}
    tw = list(pred.get("tw") or [])
    seen = set()
    for r in tw:
        try:
            seen.add(round(float(r.get("level")), 1))
        except (TypeError, ValueError, AttributeError):
            continue
    added = 0
    key_levels = pack.get("key_levels") if isinstance(pack.get("key_levels"), dict) else {}
    key_levels = dict(key_levels) if isinstance(key_levels, dict) else {}
    for row in index_drawable_levels(data, max_n=max_n):
        try:
            lv = round(float(row.get("price")), 1)
        except (TypeError, ValueError):
            continue
        if lv in seen:
            continue
        # 教具梯主窗約 3万～6万；過舊低點仍可進 key_levels，但 pred 右欄只收現役帶
        p0 = (row.get("provenance") or [{}])[0]
        stamp = (
            f"{p0.get('source')}:{p0.get('post_id') or p0.get('evidence_id') or ''}"
        )[:48]
        key_levels[f"sync_tw_{int(lv)}"] = float(lv)
        if 30000.0 <= lv <= 60000.0:
            tw.append(
                {
                    "level": float(lv),
                    "role": str(row.get("role") or "點位"),
                    "tag": "他點",
                    "label": f"飆預測{lv:g}・他點",
                    "sync_levels": True,
                    "provenance_stamp": stamp,
                    "phone_warning": PHONE_WARNING_FIXED,
                    "buy_signal": False,
                }
            )
            seen.add(lv)
            added += 1
        else:
            seen.add(lv)
    pack["key_levels"] = key_levels
    pack["pred_levels"] = {
        "tw": tw,
        "sox": list(pred.get("sox") or []),
        "note": str(pred.get("note") or ""),
    }
    pack["sync_levels_ref"] = {
        "track": TRACK,
        "added_tw": added,
        "n_index_src": int(data.get("n_index") or 0),
        "warning": PHONE_WARNING_FIXED,
        "buy_signal": False,
    }
    # 題旨輔句不蓋主文；只在 wait 末端輕標（非買訊）
    wait = str(pack.get("wait_struct") or "")
    if added and "SYNC-LEVELS" not in wait:
        pack["wait_struct"] = (
            f"{wait}｜SYNC-LEVELS 他點指數位×{added}（{PHONE_WARNING_FIXED}）"
        )[:480]
    return pack


def written_targets_merged(
    sid: str,
    *,
    blob: Optional[Dict[str, Any]] = None,
    base: Optional[Sequence[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """壓撐／結構圖原文線：seed＋可畫個股位；未點名＝只回 base。"""
    key = re.sub(r"\D", "", str(sid or ""))[:4]
    out: List[Dict[str, Any]] = [dict(x) for x in (base or [])]
    if not key or not stock_was_named(key, blob):
        return out
    seen = set()
    for row in out:
        try:
            seen.add(round(float(row.get("price")), 2))
        except (TypeError, ValueError):
            continue
    for row in stock_drawable_levels(key, blob):
        try:
            px = round(float(row.get("price")), 2)
        except (TypeError, ValueError):
            continue
        if px in seen or px <= 0:
            continue
        p0 = (row.get("provenance") or [{}])[0]
        out.append(
            {
                "price": float(px),
                "note": str(row.get("label") or row.get("role") or "他點"),
                "role": str(row.get("role") or "down"),
                "as_of": _ymd(p0.get("as_of") or p0.get("taipei")),
                "sid": key,
                "source": "原文目標",
                "label": f"飆大原文目標 {px:g}・非買訊",
                "sync_levels": True,
                "provenance_stamp": (
                    f"{p0.get('source')}:{p0.get('post_id') or ''}"
                )[:48],
                "phone_warning": PHONE_WARNING_FIXED,
                "buy_signal": False,
            }
        )
        seen.add(px)
    return out


def paint_sync_index_levels(
    ax,
    levels: Sequence[Dict[str, Any]],
    *,
    color: str = "#4dd0e1",
    lw: float = 0.7,
    alpha: float = 0.45,
    xmax: Optional[float] = None,
) -> List[float]:
    """三窗／大盤輔線：只畫傳入的他點價。回傳已畫 y。"""
    painted: List[float] = []
    if ax is None:
        return painted
    for row in levels or []:
        try:
            y = float(row.get("price") if isinstance(row, dict) else row)
        except (TypeError, ValueError):
            continue
        if y <= 0:
            continue
        if xmax is not None:
            ax.plot(
                [-0.5, float(xmax)],
                [y, y],
                color=color,
                lw=lw,
                ls=(0, (3, 2)),
                alpha=alpha,
                zorder=3.5,
            )
        else:
            ax.axhline(y, color=color, lw=lw, ls=(0, (3, 2)), alpha=alpha, zorder=3.5)
        painted.append(y)
    return painted


def summarize_drawable_md(blob: Optional[Dict[str, Any]] = None) -> str:
    data = blob if blob is not None else load_drawable_levels()
    return (
        f"{TRACK} 可畫位 {data.get('n_levels')} "
        f"(index={data.get('n_index')} stock={data.get('n_stock')}) "
        f"named={','.join(data.get('named_stock_ids') or []) or '—'} "
        f"｜{PHONE_WARNING_FIXED}"
    )


if __name__ == "__main__":
    import sys

    db = ""
    for a in sys.argv[1:]:
        if a.endswith(".db"):
            db = a
    # 專案預設庫
    if not db:
        cand = ROOT / "data" / "wayne_market.db"
        if cand.is_file():
            db = str(cand)
    blob = build_drawable_levels(db_path=db, verify=bool(db))
    path = save_drawable_levels(blob)
    print(summarize_drawable_md(blob))
    print("wrote", path)
    for g in blob.get("gaps") or []:
        print("gap:", g)
