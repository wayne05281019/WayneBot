#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""近一年飆大公開主文＋自回 → 黃交叉注意 MD＋JSON.gz（可上傳 Drive 融合）。

底圖仍認 Drive 1709／社團20／72；本腳本產「近一年補丁＋讀黃對照」。
非買訊。
"""
from __future__ import annotations

import gzip
import json
import re
import shutil
import sqlite3
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
DB_DEFAULT = ROOT / "data" / "wayne_market.db"
OUT_MANUAL = ROOT / "docs" / "expert_notes" / "飆客" / "observe_manual"
ART = Path("/opt/cursor/artifacts")
SINCE = "2025-11-28"

BUCKETS = {
    "浪頂／耗盡／末升": r"末升|浪頂|耗盡|5-5|末升段|結束這波|走完",
    "回檔／回測／給回": r"回測|回檔|回吐|給回|拉回|壓回|修正",
    "出清／減碼／勿追": r"出清|減碼|勿追|不要追|先出|下車|反彈減",
    "費半／台指／電子夜": r"費半|SOX|台指|電子期|夜盤|那指|費城",
    "量價／沉澱／爆量": r"量價|沉澱|爆量|量縮|放量|量能",
    "細微波／中繼／刪去": r"細微|中繼|刪去|鐵律|1.?4重疊|第三波最短|失敗5",
    "反彈／回馬槍／止穩": r"反彈|回馬槍|止穩|破底翻|第二腳",
    "形態／關鍵K／結構": r"形態|關鍵.?K|量價結構|碎形|五件",
}


def _load_rows(db: Path, since: str) -> List[sqlite3.Row]:
    con = sqlite3.connect(str(db))
    con.row_factory = sqlite3.Row
    rows = list(
        con.execute(
            "SELECT id,date,time,kind,layer,parent,text,reply_to_text,tags "
            "FROM biaoke_posts WHERE date>=? ORDER BY date,time,id",
            (since,),
        )
    )
    con.close()
    return rows


def build_cross_md(rows: List[sqlite3.Row], since: str) -> str:
    hits: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in rows:
        t = str(r["text"] or "")
        if len(t) < 8:
            continue
        for name, pat in BUCKETS.items():
            if re.search(pat, t):
                snip = re.sub(r"\s+", " ", t)[:180]
                hits[name].append(
                    {
                        "date": r["date"],
                        "kind": r["kind"],
                        "id": str(r["id"]),
                        "layer": r["layer"],
                        "snip": snip,
                    }
                )
    n_post = sum(1 for r in rows if r["kind"] != "reply")
    n_reply = sum(1 for r in rows if r["kind"] == "reply")
    lines = [
        "# 飆大近一年 × 黃培碩今年影音・交叉注意（一次到位）",
        "",
        "- as_of Taipei：2026-11-28",
        f"- 窗：{since} → 庫內最新",
        f"- 列數：{len(rows)}（主文 {n_post}／自回 {n_reply}）",
        "- 底圖：Drive「飆大所有紀錄」1709＋社團20／72；本檔＝近一年公開主文＋樓中樓自回融合注意點",
        "- 非買訊；讀黃片時對照，不准漏",
        "",
        "## 讀黃片時強制對照（一個不漏）",
        "1. 他講浪頂／末升／耗盡 → 對飆大同窗「出清／減碼／勿追」與給回帶",
        "2. 他講回測／回檔／修正帶 → 對飆大量價沉澱／爆量與回測句",
        "3. 他講細微波／中繼／鐵律刪去 → 對飆大細微／1-4重疊／失敗5",
        "4. 他講費半／台指／電子日夜 → 對飆大費半聯動與夜盤句",
        "5. 他講反彈／回馬槍／止穩 → 對飆大第二腳／破底翻／反彈減碼節奏",
        "6. 出場學：黃口播減碼／出清 ↔ 飆大如何賣窗（20高）與本檔出清桶",
        "",
    ]
    for name in BUCKETS:
        xs = hits[name]
        mains = [x for x in xs if x["kind"] != "reply"]
        reps = [x for x in xs if x["kind"] == "reply"]
        pick = (mains[-12:] if mains else []) + (
            reps[-6:] if not mains else reps[-4:]
        )
        seen = set()
        uniq = []
        for x in pick:
            if x["id"] in seen:
                continue
            seen.add(x["id"])
            uniq.append(x)
        lines.append(f"## {name}（命中 {len(xs)}）")
        if not uniq:
            lines.append("（本窗無命中）")
            lines.append("")
            continue
        for x in uniq[-10:]:
            kind = "主" if x["kind"] != "reply" else f"回L{x['layer']}"
            lines.append(
                f"- `{x['date']}` {kind} `{x['id']}`　{x['snip']}"
            )
        lines.append("")
    lines.extend(
        [
            "## 融合進 Drive 的做法",
            "- 保留原 1709／社團20／72 三檔不動當底圖",
            "- 新增本交叉注意＋近一年 JSON 補丁（公開主文＋自回）；讀黃時與 API 深抓增量一起用",
            "- 過閘後再升級話筒提醒力道（huang §14b）",
            "",
        ]
    )
    return "\n".join(lines)


def build_year_blob(rows: List[sqlite3.Row], since: str) -> Dict[str, Any]:
    pack = []
    for r in rows:
        t = str(r["text"] or "")
        pack.append(
            {
                "id": str(r["id"]),
                "date": r["date"],
                "time": r["time"],
                "kind": r["kind"],
                "layer": int(r["layer"] or 0),
                "parent": str(r["parent"] or ""),
                "text": t[:4000],
                "reply_to_text": str(r["reply_to_text"] or "")[:500],
                "tags": r["tags"],
            }
        )
    return {
        "as_of_taipei": "2026-11-28T18:15:00+0800",
        "since": since,
        "n": len(pack),
        "source": "biaoke_posts year fuse for Drive merge",
        "baseline_note": "merge with archive_1709; club packs stay separate",
        "posts": pack,
    }


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(DB_DEFAULT))
    ap.add_argument("--since", default=SINCE)
    args = ap.parse_args()
    db = Path(args.db)
    rows = _load_rows(db, args.since)
    md = build_cross_md(rows, args.since)
    OUT_MANUAL.mkdir(parents=True, exist_ok=True)
    ART.mkdir(parents=True, exist_ok=True)
    md_name = "biaoke_huang_cross_watch_20261128.md"
    (OUT_MANUAL / md_name).write_text(md, encoding="utf-8")
    (ART / md_name).write_text(md, encoding="utf-8")
    blob = build_year_blob(rows, args.since)
    gz_name = "biaoke_public_year_fuse_20261128.json.gz"
    for dest in (ART / gz_name, OUT_MANUAL / gz_name):
        with gzip.open(dest, "wt", encoding="utf-8") as fh:
            json.dump(blob, fh, ensure_ascii=False)
    print(
        json.dumps(
            {
                "ok": True,
                "n": len(rows),
                "md_chars": len(md),
                "gz_bytes": (ART / gz_name).stat().st_size,
                "md": str(OUT_MANUAL / md_name),
                "gz": str(OUT_MANUAL / gz_name),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
