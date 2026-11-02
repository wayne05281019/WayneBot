#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""十年回測旁路｜序A：從 knowhow／backtest_18m 抽出錯案／改口／硬句年表 → JSONL。

只讀筆記、寫 decade_lab JSONL。鍋標分列：他說／實驗室（對質判定）。
不是買訊；不准寫回黃金買點／海選／洞燭。
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
NOTE_DIR = ROOT / "docs" / "expert_notes" / "飆客"
OUT_DIR = NOTE_DIR / "decade_lab"
TP = ZoneInfo("Asia/Taipei")

# 判定關鍵字 → outcome 桶
WRONG_MARKERS = ("**錯", "錯，", "錯成", "錯估", "認錯", "偏早", "偏高", "偏緊", "偏淺", "早了")
REVISION_MARKERS = ("改口", "更正", "自己改", "他自己改", "公開檢討", "道歉")
HARD_MARKERS = (
    "絕對不可能",
    "絕對不會",
    "100%",
    "九成",
    "超過 90%",
    "超過90%",
    "不准",
    "一定",
)


def _now() -> str:
    return datetime.now(TP).isoformat()


def _norm_year(year_hint: Optional[int], raw: str) -> Optional[str]:
    """把表內 7/16、2026-07-16、2025-03-04 收成 YYYY-MM-DD（能定年才收）。"""
    s = (raw or "").strip()
    m = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})", s)
    if m:
        return f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    m = re.match(r"^(\d{4})/(\d{1,2})/(\d{1,2})", s)
    if m:
        return f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    m = re.match(r"^(\d{1,2})/(\d{1,2})", s)
    if m and year_hint:
        return f"{year_hint:04d}-{int(m.group(1)):02d}-{int(m.group(2)):02d}"
    return None


def _section_year(title: str) -> Optional[int]:
    m = re.search(r"(20\d{2})", title or "")
    return int(m.group(1)) if m else None


def _parse_md_tables(text: str) -> List[Tuple[str, List[str], List[List[str]]]]:
    """粗抓 markdown 表：回 (前置標題列, headers, rows)。"""
    lines = text.splitlines()
    out: List[Tuple[str, List[str], List[List[str]]]] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.strip().startswith("|") and i + 1 < len(lines) and re.match(
            r"^\|[\s:-]+\|", lines[i + 1].strip()
        ):
            headers = [c.strip() for c in line.strip().strip("|").split("|")]
            i += 2
            rows: List[List[str]] = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                if len(cells) == len(headers):
                    rows.append(cells)
                i += 1
            # 往前找最近 ## / ###
            title = ""
            for j in range(i - 1, max(-1, i - 40), -1):
                if lines[j].startswith("#"):
                    title = lines[j].lstrip("#").strip()
                    break
            out.append((title, headers, rows))
            continue
        i += 1
    return out


def _classify(blob: str) -> List[str]:
    tags: List[str] = []
    if any(m in blob for m in WRONG_MARKERS):
        tags.append("錯案")
    if any(m in blob for m in REVISION_MARKERS):
        tags.append("改口")
    if any(m in blob for m in HARD_MARKERS):
        tags.append("硬句")
    # 絕對化語氣
    if re.search(r"絕對|不可能|一定|100%|九成以上|超過\s*90%", blob):
        if "硬句" not in tags:
            tags.append("硬句")
    return tags


def _row_record(
    *,
    source_file: str,
    section: str,
    headers: List[str],
    cells: List[str],
    year_hint: Optional[int],
    kind_force: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    mapping = {headers[i]: cells[i] for i in range(len(headers))}
    blob = "｜".join(cells)
    tags = _classify(blob)
    if kind_force and kind_force not in tags:
        tags.append(kind_force)
    if not tags:
        return None
    # 日期欄候選
    date_raw = ""
    for key in ("日期", "他的時間", "時間", "他開口", "位階"):
        if key in mapping and mapping[key]:
            date_raw = mapping[key]
            break
    if not date_raw and cells:
        date_raw = cells[0]
    # 從字串抓 20xx-xx-xx
    ymd = None
    m = re.search(r"(20\d{2}-\d{1,2}-\d{1,2})", date_raw)
    if m:
        ymd = _norm_year(None, m.group(1))
    if not ymd:
        # 7/16 夜 → 依 section year
        m2 = re.search(r"(\d{1,2}/\d{1,2})", date_raw)
        if m2:
            ymd = _norm_year(year_hint, m2.group(1))
    said = mapping.get("他說") or mapping.get("原文") or ""
    evidence = (
        mapping.get("對當時資料")
        or mapping.get("庫內 TWII")
        or mapping.get("圖／庫")
        or mapping.get("庫內")
        or mapping.get("對當時")
        or ""
    )
    verdict = mapping.get("判定") or mapping.get("之後") or ""
    pot_teacher = "他說／飆預測"
    pot_lab = "實驗室"
    return {
        "id": None,  # 後填
        "event_date": ymd,
        "event_raw": date_raw,
        "section": section,
        "source_file": source_file,
        "tags": tags,
        "said": said or blob[:240],
        "evidence": evidence,
        "verdict": verdict,
        "pot": {
            "teacher_claim": pot_teacher,
            "lab_label": pot_lab,
            "dc_estimate": None,
        },
        "table_row": mapping,
        "extracted_at": _now(),
        "tz": "Asia/Taipei",
        "not_buy_signal": True,
    }


def _bullet_hard_sentences(text: str, source_file: str) -> List[Dict[str, Any]]:
    """從段落抓含絕對化／改口的條列。"""
    out: List[Dict[str, Any]] = []
    year_hint = None
    section = ""
    for line in text.splitlines():
        if line.startswith("#"):
            section = line.lstrip("#").strip()
            y = _section_year(section)
            if y:
                year_hint = y
            continue
        if not line.strip().startswith(("-", "*", "•")):
            # 也收 **2025-03-03 ...** 這種粗體條
            if not re.match(r"^-?\s*\*\*20\d{2}", line.strip()):
                continue
        blob = line.strip().lstrip("-*• ").strip()
        tags = _classify(blob)
        if not tags:
            continue
        m = re.search(r"(20\d{2}-\d{1,2}-\d{1,2})", blob)
        ymd = _norm_year(None, m.group(1)) if m else None
        out.append(
            {
                "id": None,
                "event_date": ymd,
                "event_raw": (m.group(0) if m else ""),
                "section": section,
                "source_file": source_file,
                "tags": tags,
                "said": blob[:500],
                "evidence": "",
                "verdict": "",
                "pot": {
                    "teacher_claim": "他說／飆預測",
                    "lab_label": "實驗室",
                    "dc_estimate": None,
                },
                "table_row": {"line": blob},
                "extracted_at": _now(),
                "tz": "Asia/Taipei",
                "not_buy_signal": True,
            }
        )
    return out


def extract_from_file(path: Path) -> List[Dict[str, Any]]:
    text = path.read_text(encoding="utf-8")
    rel = str(path.relative_to(ROOT))
    records: List[Dict[str, Any]] = []
    for title, headers, rows in _parse_md_tables(text):
        yh = _section_year(title)
        for cells in rows:
            rec = _row_record(
                source_file=rel,
                section=title,
                headers=headers,
                cells=cells,
                year_hint=yh,
            )
            if rec:
                records.append(rec)
    records.extend(_bullet_hard_sentences(text, rel))
    return records


def dedupe(records: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = set()
    out: List[Dict[str, Any]] = []
    for r in records:
        key = (
            r.get("event_date"),
            r.get("source_file"),
            "|".join(r.get("tags") or []),
            (r.get("said") or "")[:120],
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    # 穩定排序
    out.sort(key=lambda x: (x.get("event_date") or "9999", x.get("source_file") or "", x.get("said") or ""))
    for i, r in enumerate(out, 1):
        r["id"] = f"tl-{i:04d}"
    return out


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    paths = [
        NOTE_DIR / "knowhow.md",
        NOTE_DIR / "backtest_18m.md",
    ]
    all_recs: List[Dict[str, Any]] = []
    for p in paths:
        if not p.exists():
            continue
        all_recs.extend(extract_from_file(p))
    final = dedupe(all_recs)
    # 分類檔
    by_tag = {"錯案": [], "改口": [], "硬句": []}
    for r in final:
        for t in r.get("tags") or []:
            if t in by_tag:
                by_tag[t].append(r)

    stamp = datetime.now(TP).strftime("%Y%m%d")
    out_all = OUT_DIR / f"timeline_wrong_revision_hard_{stamp}.jsonl"
    with out_all.open("w", encoding="utf-8") as f:
        for r in final:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    # 穩定別名
    alias = OUT_DIR / "timeline_wrong_revision_hard_latest.jsonl"
    alias.write_text(out_all.read_text(encoding="utf-8"), encoding="utf-8")

    summary = {
        "extracted_at": _now(),
        "tz": "Asia/Taipei",
        "sources": [str(p.relative_to(ROOT)) for p in paths if p.exists()],
        "n_total": len(final),
        "n_錯案": len(by_tag["錯案"]),
        "n_改口": len(by_tag["改口"]),
        "n_硬句": len(by_tag["硬句"]),
        "jsonl": str(alias.relative_to(ROOT)),
        "note": "空代號不算；本檔是年表材料。不是買訊。",
    }
    (OUT_DIR / "timeline_extract_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    md_lines = [
        "# 序A｜錯案／改口／硬句年表摘要",
        "",
        f"抽出時刻：`{summary['extracted_at']}`（Asia/Taipei）。",
        f"總筆數：**{summary['n_total']}**（錯案 {summary['n_錯案']}／改口 {summary['n_改口']}／硬句 {summary['n_硬句']}；一筆可多標）。",
        f"JSONL：`{summary['jsonl']}`",
        "",
        "鍋：**他說／飆預測**＝原文主張；**實驗室**＝對質判定欄。DC→我估本輪未寫入。",
        "",
        "不是買訊。",
        "",
    ]
    (OUT_DIR / "timeline_extract_summary.md").write_text(
        "\n".join(md_lines), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
