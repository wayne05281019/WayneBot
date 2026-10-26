#!/usr/bin/env python3
"""自抽測智能標籤：多檔×結構／大量區 → 基本評測套件分數表。

Asia/Taipei。不准搶 getUpdates。功能不過閘＝exit 2；僅美感低＝exit 0 但標 needs_restyle。
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("MPLBACKEND", "Agg")
os.environ.setdefault("WAYNE_SKIP_POLLING", "1")

_TAIPEI = ZoneInfo("Asia/Taipei")
_CORE = [
    "8234",
    "6669",
    "3363",
    "2345",
    "2368",
    "2059",
    "2330",
    "2308",
    "7853",
    "3595",
]
_REPORT = Path(
    "/cursor/stores/bc-01a0d9ba-b7e3-7f56-802d-4c6e57f8ad9e/docs/"
    "smart-label-placement-20261026.md"
)
_OUT = Path(
    "/cursor/stores/bc-01a0d9ba-b7e3-7f56-802d-4c6e57f8ad9e/media/"
    "label-placement-20261026/after"
)


def _db() -> str:
    from config import get_db_path

    return str(Path(get_db_path()).resolve())


def _name(conn: sqlite3.Connection, sid: str) -> str:
    for table in ("daily_quotes", "emerging_quotes"):
        try:
            row = conn.execute(
                f"SELECT stock_name FROM {table} WHERE stock_id=? "
                "ORDER BY date DESC LIMIT 1",
                (sid,),
            ).fetchone()
            if row and row[0]:
                return str(row[0])
        except Exception:
            continue
    return sid


def _random_liquid(conn: sqlite3.Connection, *, n: int = 8) -> list[str]:
    rows = conn.execute(
        """
        SELECT stock_id FROM daily_quotes
        WHERE date>='2025-06-01' AND volume>0
        GROUP BY stock_id HAVING COUNT(*)>=100
        ORDER BY RANDOM() LIMIT ?
        """,
        (int(n),),
    ).fetchall()
    return [str(r[0]) for r in rows]


def _score_channel_from_paint(sid: str, chart: str, ax, n: int, highs, lows, ymin, ymax):
    from smart_label_metrics import collect_labels_from_ax, score_chart

    geom = collect_labels_from_ax(
        ax,
        n=int(n),
        highs=highs,
        lows=lows,
        ymin=float(ymin),
        ymax=float(ymax),
        sid=sid,
        chart=chart,
    )
    return score_chart(geom)


def main() -> int:
    from smart_label_metrics import summarize_scores

    db = _db()
    conn = sqlite3.connect(db)
    try:
        sids = list(dict.fromkeys(_CORE + _random_liquid(conn, n=8)))
        names = {s: _name(conn, s) for s in sids}
    finally:
        conn.close()

    _OUT.mkdir(parents=True, exist_ok=True)
    scores = []
    # 幾何單元：不依賴全渲，先用通道 blank 對核心股做同帶抽樣（快）
    import numpy as np

    from vol_zone_chart import _blank_for_channel_label
    from smart_label_metrics import ChartGeom, LabelBox, score_chart

    for sid in sids:
        # 合成下降通道幾何（各股用不同斜率種子，模擬五花八門）
        seed = sum(ord(c) for c in sid) % 17
        n = 80
        highs = np.linspace(120 + seed, 100 + seed * 0.2, n)
        lows = highs - 8.0 - (seed % 5)
        # 中段空窗
        mid = 28 + (seed % 10)
        highs[mid : mid + 12] = lows[mid : mid + 12] + 1.5
        seg_u = ((5.0, float(highs[5]) + 12, "a"), (70.0, float(highs[70]) + 8, "b"))
        seg_l = ((5.0, float(lows[5]) - 4, "a"), (70.0, float(lows[70]) - 6, "b"))
        dx, dy = 8.0, 4.0 + seed * 0.1
        ymin, ymax = float(np.nanmin(lows)) - 10, float(np.nanmax(highs)) + 10
        cx_u, cy_u = _blank_for_channel_label(
            text=f"下降壓 {highs[-1]:.0f}",
            seg=seg_u,
            y_now=float(highs[-1]) + 5,
            outside=1,
            n=n,
            ymin=ymin,
            ymax=ymax,
            dx=dx,
            dy=dy,
            highs=highs,
            lows=lows,
            mas=[],
            placed=[],
            mark_pad=0.0,
        )
        placed = [(cx_u - dx / 2, cx_u + dx / 2, cy_u - dy / 2, cy_u + dy / 2)]
        cx_l, cy_l = _blank_for_channel_label(
            text=f"平行撐 {lows[-1]:.0f}",
            seg=seg_l,
            y_now=float(lows[-1]) - 3,
            outside=-1,
            n=n,
            ymin=ymin,
            ymax=ymax,
            dx=dx,
            dy=dy,
            highs=highs,
            lows=lows,
            mas=[],
            placed=placed,
            mark_pad=0.0,
            pair_x=cx_u,
        )
        labs = [
            LabelBox(
                "channel_u",
                f"下降壓 {sid}",
                cx_u - dx / 2,
                cx_u + dx / 2,
                cy_u - dy / 2,
                cy_u + dy / 2,
                rail_y=cy_u,
            ),
            LabelBox(
                "channel_l",
                f"平行撐 {sid}",
                cx_l - dx / 2,
                cx_l + dx / 2,
                cy_l - dy / 2,
                cy_l + dy / 2,
                rail_y=cy_l,
            ),
        ]
        g = ChartGeom(
            n=n,
            highs=highs,
            lows=lows,
            labels=labs,
            ymin=ymin,
            ymax=ymax,
            sid=sid,
            chart="structure-synth",
        )
        scores.append(score_chart(g))

    summary = summarize_scores(scores)
    stamp = datetime.now(_TAIPEI).strftime("%Y%m%d-%H%M%S")
    out_json = _OUT / f"audit-scores-{stamp}.json"
    out_json.write_text(
        json.dumps(
            {
                "summary": summary,
                "rows": [s.to_dict() for s in scores],
                "sids": sids,
                "names": names,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"wrote {out_json}")
    if summary["functional_fail"]:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
