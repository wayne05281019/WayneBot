# -*- coding: utf-8 -*-
"""飆大觀測手冊・話筒穩定介面（BK-PHONE）。

掛「波浪位階」：觀測手冊摘要／今日觀測槽位。
手冊原子／三層鏈由 BK-CORPUS／BK-CHAIN 等軌落檔後再填滿；
目前可讀 lock 說明＋可選 JSON，缺檔時回 placeholder，介面鍵穩定。

不准：改黃金買點、離開敘事進產品、當買訊、冒充他原文。
時區 Asia/Taipei。
"""
from __future__ import annotations

import json
import logging
import os
from html import escape as html_escape
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("wayne.observe_manual")

# 話筒固定警語（MISSION_LOCK B1／B4／C11）
OBSERVE_PHONE_DISCLAIMER = "試標・推論／非他原文・非買訊・對質未過閘"

_MANUAL_DIR = Path(__file__).resolve().parent / "docs" / "expert_notes" / "飆客" / "observe_manual"
_ATOM_CANDIDATES = (
    "atoms_latest.json",  # BK-CORPUS 產出
    "observe_atoms.json",
    "atoms.json",
    "chain_atoms.json",
)
_CHAIN_CANDIDATES = (
    "chain_playbook.json",  # BK-CHAIN 產出
    "observe_chain.json",
    "chain_ops.json",
    "三層觀測操作手.json",
)


def manual_dir() -> Path:
    return _MANUAL_DIR


def _read_json(path: Path) -> Optional[Dict[str, Any]]:
    try:
        if not path.is_file():
            return None
        raw = json.loads(path.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {"items": raw}
    except Exception:
        logger.debug("observe_manual 讀 JSON 略過 path=%s", path, exc_info=True)
        return None


def load_observe_atoms(*, root: Optional[Path] = None) -> Dict[str, Any]:
    """讀觀測原子表（方法／位／改口／三層／SOX／鐵律）。缺檔＝空殼＋來源說明。"""
    base = Path(root) if root else _MANUAL_DIR
    out: Dict[str, Any] = {
        "ok": False,
        "source": "",
        "atoms": [],
        "missing": [],
    }
    for name in _ATOM_CANDIDATES:
        hit = _read_json(base / name)
        if hit is None:
            out["missing"].append(name)
            continue
        atoms = hit.get("atoms") or hit.get("items") or hit.get("rows") or []
        if not isinstance(atoms, list):
            atoms = []
        out["ok"] = bool(atoms)
        out["source"] = str(base / name)
        out["atoms"] = atoms[:40]
        out["raw"] = hit
        return out
    out["missing"] = list(_ATOM_CANDIDATES)
    return out


def load_observe_chain(*, root: Optional[Path] = None) -> Dict[str, Any]:
    """讀三層觀測鏈（夜盤 e-mini → 早盤 TX → 現貨加權＋SOX）。缺檔＝空殼。"""
    base = Path(root) if root else _MANUAL_DIR
    out: Dict[str, Any] = {
        "ok": False,
        "source": "",
        "steps": [],
        "missing": [],
    }
    for name in _CHAIN_CANDIDATES:
        hit = _read_json(base / name)
        if hit is None:
            out["missing"].append(name)
            continue
        steps = (
            hit.get("steps")
            or hit.get("chain")
            or hit.get("checklist")
            or hit.get("items")
            or []
        )
        if not isinstance(steps, list) or not steps:
            layers = hit.get("layers")
            if isinstance(layers, list) and layers:
                steps = layers
        if not isinstance(steps, list) or not steps:
            checklist = hit.get("daily_checklist")
            if isinstance(checklist, list) and checklist:
                steps = checklist
        if not isinstance(steps, list):
            steps = []
        out["ok"] = bool(steps)
        out["source"] = str(base / name)
        out["steps"] = steps[:12]
        out["raw"] = hit
        return out
    out["missing"] = list(_CHAIN_CANDIDATES)
    return out


def load_mission_lock_blurb(*, root: Optional[Path] = None) -> str:
    """手冊尚未落原子時，從 MISSION_LOCK 抽一句觀盤鏈說明（非他原文）。"""
    base = Path(root) if root else _MANUAL_DIR
    path = base / "MISSION_LOCK_20261123.md"
    try:
        if not path.is_file():
            return (
                "觀盤鏈：夜盤 e-mini → 早盤 TX 確認 → 現貨加權驗證＋SOX 連動"
                "（手冊原子尚未落地）。"
            )
        text = path.read_text(encoding="utf-8")
    except Exception:
        return "觀盤鏈說明暫缺（MISSION_LOCK 讀不到）。"
    # 鎖檔內「實用觀盤交付」第 1 點
    for line in text.splitlines():
        s = line.strip()
        if "夜盤" in s and "TX" in s and ("加權" in s or "SOX" in s):
            # 去掉 markdown 列表前綴
            s = s.lstrip("0123456789.-*、．）) ").strip()
            if s.startswith("**"):
                s = s.strip("*").strip()
            if "：" in s[:12]:
                s = s.split("：", 1)[-1].strip()
            return s[:180]
    return (
        "觀盤鏈：夜盤 e-mini → 早盤 TX 確認 → 現貨加權驗證＋SOX 連動"
        "（手冊原子尚未落地）。"
    )


def missing_manual_files(*, root: Optional[Path] = None) -> List[str]:
    """回報還缺哪份手冊檔才能填滿摘要（給 PR／對質用）。"""
    base = Path(root) if root else _MANUAL_DIR
    need = list(_ATOM_CANDIDATES[:1]) + list(_CHAIN_CANDIDATES[:1])
    # 也接受任一候選已存在
    missing: List[str] = []
    if not any((base / n).is_file() for n in _ATOM_CANDIDATES):
        missing.append(_ATOM_CANDIDATES[0])
    if not any((base / n).is_file() for n in _CHAIN_CANDIDATES):
        missing.append(_CHAIN_CANDIDATES[0])
    lock = base / "MISSION_LOCK_20261123.md"
    if not lock.is_file():
        missing.append("MISSION_LOCK_20261123.md")
    return missing


def _atom_lines(atoms: List[Any], *, limit: int = 4) -> List[str]:
    lines: List[str] = []
    for row in atoms:
        if len(lines) >= limit:
            break
        if isinstance(row, str) and row.strip():
            lines.append(row.strip()[:80])
            continue
        if not isinstance(row, dict):
            continue
        title = str(
            row.get("title")
            or row.get("theme_label")
            or row.get("method")
            or row.get("label")
            or row.get("name")
            or ""
        ).strip()
        body = str(
            row.get("summary")
            or row.get("rule")
            or row.get("text")
            or row.get("note")
            or ""
        ).strip()
        bit = title
        if body and body != title:
            bit = f"{title}：{body}" if title else body
        if bit:
            lines.append(bit[:100])
    return lines


def _chain_lines(steps: List[Any], *, limit: int = 4) -> List[str]:
    lines: List[str] = []
    for i, row in enumerate(steps):
        if len(lines) >= limit:
            break
        if isinstance(row, str) and row.strip():
            lines.append(f"{i + 1}. {row.strip()[:90]}")
            continue
        if not isinstance(row, dict):
            continue
        lab = str(
            row.get("label")
            or row.get("label_zh")
            or row.get("title_zh")
            or row.get("step")
            or row.get("name")
            or row.get("title")
            or ""
        ).strip()
        note = str(
            row.get("check")
            or row.get("role_zh")
            or row.get("note")
            or row.get("text")
            or row.get("window_taipei")
            or ""
        ).strip()
        bit = lab if lab else note
        if lab and note and note != lab:
            bit = f"{lab}：{note}"
        if bit:
            lines.append(f"{i + 1}. {bit[:90]}")
    return lines


def format_wave_observe_slot(
    db_path: str = "",
    *,
    pack: Optional[Dict[str, Any]] = None,
    root: Optional[Path] = None,
) -> str:
    """波浪位階回覆槽：觀測手冊摘要／今日觀測＋固定警語（HTML）。

    pack／db 可選；目前不依賴盤中價。缺原子／鏈 → lock 說明 placeholder。
    """
    del db_path, pack  # 介面預留；原子檔齊了再接當日勾選
    atoms = load_observe_atoms(root=root)
    chain = load_observe_chain(root=root)
    lines: List[str] = [
        "<b>觀測手冊摘要／今日觀測</b>",
        html_escape(OBSERVE_PHONE_DISCLAIMER),
        "",
    ]
    if chain.get("ok"):
        lines.append("<b>三層鏈</b>")
        for ln in _chain_lines(list(chain.get("steps") or [])):
            lines.append(html_escape(f"· {ln}"))
    else:
        blurb = load_mission_lock_blurb(root=root)
        lines.append("<b>三層鏈（暫）</b>")
        lines.append(html_escape(f"· {blurb}"))
        lines.append(
            html_escape(
                "· 待 BK-CHAIN 落 chain_playbook.json 後改為當日勾選欄。"
            )
        )
    lines.append("")
    if atoms.get("ok"):
        lines.append("<b>觀測原子</b>")
        for ln in _atom_lines(list(atoms.get("atoms") or [])):
            lines.append(html_escape(f"· {ln}"))
    else:
        lines.append("<b>觀測原子（暫）</b>")
        lines.append(
            html_escape(
                "· 待 BK-CORPUS 落 atoms_latest.json（方法／位／改口／鐵律）。"
            )
        )
        miss = missing_manual_files(root=root)
        if miss:
            lines.append(
                html_escape("· 還缺：" + "、".join(miss[:4]))
            )
    lines.append("")
    lines.append(
        html_escape("預計／試標可講，但只當輔助層；進場仍只認黃金買點＋已過閘紅箭。")
    )
    return "\n".join(lines)


def merge_wave_phone_html(
    brief: str,
    *,
    db_path: str = "",
    pack: Optional[Dict[str, Any]] = None,
    root: Optional[Path] = None,
) -> str:
    """先文後圖：波浪敘述＋觀測槽合成一則 HTML（截斷前由呼叫端處理）。"""
    bits: List[str] = []
    b = str(brief or "").strip()
    if b:
        bits.append(b)
    slot = format_wave_observe_slot(db_path, pack=pack, root=root).strip()
    if slot:
        bits.append(slot)
    if not bits:
        bits.append(
            "<b>波浪位階・預估・非買訊</b>\n"
            + html_escape(OBSERVE_PHONE_DISCLAIMER)
        )
    return "\n\n".join(bits)
