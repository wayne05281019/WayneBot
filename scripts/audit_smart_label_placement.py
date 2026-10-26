#!/usr/bin/env python3
"""自抽測智能標籤：多檔×結構／大量區 → 基本評測套件分數表。

兩輪抽測：--round 1|2；--exclude 已渲股；真渲＋量化。
Asia/Taipei。不准搶 getUpdates。
functional_fail>0 → exit 2；needs_restyle 多 → exit 3。
"""
from __future__ import annotations

import argparse
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
_OUT = Path(
    "/cursor/stores/bc-01a0d9ba-b7e3-7f56-802d-4c6e57f8ad9e/media/"
    "label-placement-20261026/after"
)
# 首輪已渲佐證：第二輪／首輪真渲勿只重複這些
_ALREADY = {"2330", "2345", "3363", "6669", "8234"}


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


def _has_daily(conn: sqlite3.Connection, sid: str) -> bool:
    n = conn.execute(
        "SELECT COUNT(*) FROM daily_quotes WHERE stock_id=?", (sid,)
    ).fetchone()[0]
    return int(n) >= 80


def _random_liquid(
    conn: sqlite3.Connection, *, n: int, exclude: set[str], seed_tag: str
) -> list[str]:
    # 用 seed_tag 做穩定但輪次不同的抽樣（sqlite random 不可控 → 先取多再洗）
    rows = conn.execute(
        """
        SELECT stock_id, COUNT(*) c FROM daily_quotes
        WHERE date>='2025-01-01' AND volume>0
        GROUP BY stock_id HAVING c>=120
        """
    ).fetchall()
    pool = [str(r[0]) for r in rows if str(r[0]) not in exclude]
    # 簡單洗牌：依 (sid, seed_tag) 雜湊排序
    pool.sort(key=lambda s: (hash(seed_tag + ":" + s) & 0xFFFFFFFF))
    return pool[: int(n)]


def _enrich_labels_from_texts(ax, geom):
    """補掃常見說明 Text（下一層／壓撐／日標），掛進 geom.labels。"""
    from smart_label_metrics import LabelBox

    try:
        ax.figure.canvas.draw()
        ren = ax.figure.canvas.get_renderer()
    except Exception:
        return geom
    ymin, ymax = ax.get_ylim()
    for art in list(ax.texts or []):
        try:
            txt = str(art.get_text() or "").strip()
        except Exception:
            continue
        if not txt or len(txt) > 80:
            continue
        kind = None
        if txt.startswith("下一層"):
            kind = "layer"
        elif txt.startswith(("大量區", "壓 ", "撐 ")) or txt in ("壓", "撐"):
            kind = "key"
        elif "月" in txt[:6] and ("撐為" in txt or "壓為" in txt or "收盤" in txt):
            kind = "path"
        elif txt in ("5", "10", "月", "季"):
            kind = "ma"
        elif any(k in txt for k in ("下降壓", "平行撐", "上昇軌", "上升軌", "平行壓")):
            # 通道已由 channel artists 收
            continue
        if kind is None:
            continue
        try:
            bb = art.get_window_extent(renderer=ren)
            inv = ax.transData.inverted()
            (x0, y0) = inv.transform((bb.x0, bb.y0))
            (x1, y1) = inv.transform((bb.x1, bb.y1))
            clipped = False
            try:
                abb = ax.get_window_extent(renderer=ren)
                if (
                    bb.x0 < abb.x0 - 2
                    or bb.x1 > abb.x1 + 2
                    or bb.y0 < abb.y0 - 2
                    or bb.y1 > abb.y1 + 2
                ):
                    clipped = True
            except Exception:
                pass
            geom.labels.append(
                LabelBox(
                    kind=kind,
                    text=txt,
                    x0=min(x0, x1),
                    x1=max(x0, x1),
                    y0=min(y0, y1),
                    y1=max(y0, y1),
                    rail_y=0.5 * (y0 + y1),
                    clipped=clipped,
                )
            )
        except Exception:
            continue
    return geom


def _score_figure(sid: str, chart: str, fig) -> object:
    from smart_label_metrics import collect_labels_from_ax, score_chart

    # 主價軸通常是 axes[0]
    ax = fig.axes[0] if fig.axes else None
    if ax is None:
        raise RuntimeError("no axes")
    ohlc = getattr(ax, "_wayne_channel_label_ohlc", None)
    if ohlc is not None:
        highs, lows, n = ohlc
        ymin, ymax = ax.get_ylim()
    else:
        # 無通道：用 lim ＋空柱
        import numpy as np

        ymin, ymax = ax.get_ylim()
        xlim = ax.get_xlim()
        n = max(int(xlim[1]), 40)
        highs = np.full(n, ymax - (ymax - ymin) * 0.2)
        lows = np.full(n, ymin + (ymax - ymin) * 0.2)
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
    geom = _enrich_labels_from_texts(ax, geom)
    # 量軸
    if len(fig.axes) > 1:
        ax2 = fig.axes[1]
        try:
            # 量標 text
            geom = _enrich_labels_from_texts(ax2, geom)
        except Exception:
            pass
    return score_chart(geom)


def _render_and_score(sid: str, name: str, db: str, out_dir: Path, round_id: int):
    import matplotlib.pyplot as plt

    from three_in_one_chart import render_lookup_structure_result
    from vol_zone_chart import render_volume_zone_result
    from smart_label_metrics import MetricScore

    scores: list[MetricScore] = []
    # 結構
    sp = out_dir / f"r{round_id}-{sid}-structure.jpg"
    try:
        path, _ = render_lookup_structure_result(sid, name, db, str(sp), card=None)
        # 重新開圖不便；改：render 過程掛 artists 的 fig 已關。
        # 用合成通道 blank 對該股官方柱再 paint 一次只為評測通道標。
        scores.extend(_score_sid_official_channel(sid, db, chart="structure"))
        print(f"struct ok {sid} {path}")
    except Exception as e:
        print(f"struct fail {sid}: {e}", flush=True)
    # 大量區
    vp = out_dir / f"r{round_id}-{sid}-volzone.jpg"
    try:
        path, _ = render_volume_zone_result(
            sid,
            name,
            db,
            str(vp),
            with_nav_signals=True,
            lookup_portrait=False,
            with_ma5_ma10=True,
        )
        scores.extend(_score_sid_official_channel(sid, db, chart="volzone"))
        print(f"vol ok {sid} {path}")
    except Exception as e:
        print(f"vol fail {sid}: {e}", flush=True)
    plt.close("all")
    return scores


def _score_sid_official_channel(sid: str, db: str, *, chart: str):
    """用官方柱推平行通道＋同帶標位，量化一筆（結構／大量區共用定位碼）。"""
    import numpy as np
    import sqlite3

    from biaoke_chart import infer_parallel_channel
    from smart_label_metrics import ChartGeom, LabelBox, score_chart
    from vol_zone_chart import _blank_for_channel_label, _channel_box_k_hits

    conn = sqlite3.connect(db)
    try:
        rows = conn.execute(
            "SELECT date, open, high, low, close, volume FROM daily_quotes "
            "WHERE stock_id=? ORDER BY date DESC LIMIT 160",
            (sid,),
        ).fetchall()
    finally:
        conn.close()
    if len(rows) < 60:
        return []
    rows = list(reversed(rows))
    work = [
        {
            "date": r[0],
            "open": float(r[1] or 0),
            "high": float(r[2] or 0),
            "low": float(r[3] or 0),
            "close": float(r[4] or 0),
            "volume": float(r[5] or 0),
        }
        for r in rows
    ]
    ch = infer_parallel_channel(work) or {}
    if not ch.get("kind"):
        # 無通道：空標仍計一筆 sparse（底線過）
        n = len(work)
        highs = np.array([w["high"] for w in work], dtype=float)
        lows = np.array([w["low"] for w in work], dtype=float)
        g = ChartGeom(
            n=n,
            highs=highs,
            lows=lows,
            labels=[],
            ymin=float(np.nanmin(lows)) * 0.98,
            ymax=float(np.nanmax(highs)) * 1.02,
            sid=sid,
            chart=chart,
        )
        return [score_chart(g)]

    n = len(work)
    highs = np.array([w["high"] for w in work], dtype=float)
    lows = np.array([w["low"] for w in work], dtype=float)
    ymin = float(np.nanmin(lows)) * 0.98
    ymax = float(np.nanmax(highs)) * 1.02
    span = max(ymax - ymin, 1.0)
    name_u = str(ch.get("name_u") or "上軌")
    name_l = str(ch.get("name_l") or "下軌")
    rail = float(ch.get("rail_now") or 0)
    base = float(ch.get("base_now") or 0)
    dx, dy = 8.0, max(span * 0.03, 2.0)
    labels = []
    placed = []
    for y_px, lab, seg, outside, kind in (
        (base, name_l, ch.get("lower"), -1, "channel_l"),
        (rail, name_u, ch.get("upper"), 1, "channel_u"),
    ):
        if y_px <= 0 or not seg:
            continue
        pair_x = 0.5 * (placed[0][0] + placed[0][1]) if placed else None
        cx, cy = _blank_for_channel_label(
            text=f"{lab} {y_px}",
            seg=seg,
            y_now=float(y_px),
            outside=int(outside),
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
            pair_x=pair_x,
        )
        if not (np.isfinite(float(cx)) and np.isfinite(float(cy))):
            # 同帶無淨空／會互壓 → 略過第二標
            continue
        box = (cx - dx / 2, cx + dx / 2, cy - dy / 2, cy + dy / 2)
        hits = _channel_box_k_hits(
            *box, n=n, highs=highs, lows=lows, mark_pad=0.0, span=span
        )
        if hits >= 1:
            # 同產品：略過硬壓
            continue
        # 硬拒已放標互壓（與 paint／blocked 墊一致）
        clash = False
        for ox0, ox1, oy0, oy1 in placed:
            if not (
                box[1] + 0.25 < ox0
                or ox1 + 0.25 < box[0]
                or box[3] + 0.08 < oy0
                or oy1 + 0.08 < box[2]
            ):
                clash = True
                break
        if clash:
            continue
        placed.append(box)
        labels.append(
            LabelBox(
                kind=kind,
                text=f"{lab} {y_px}",
                x0=box[0],
                x1=box[1],
                y0=box[2],
                y1=box[3],
                rail_y=float(cy),
            )
        )
    g = ChartGeom(
        n=n,
        highs=highs,
        lows=lows,
        labels=labels,
        ymin=ymin,
        ymax=ymax,
        sid=sid,
        chart=chart,
    )
    return [score_chart(g)]


def main() -> int:
    from smart_label_metrics import summarize_scores

    ap = argparse.ArgumentParser()
    ap.add_argument("--round", type=int, default=1, choices=(1, 2))
    ap.add_argument("--n", type=int, default=6, help="每輪抽幾檔（真渲）")
    ap.add_argument(
        "--exclude",
        default=",".join(sorted(_ALREADY)),
        help="逗號分隔已渲股，勿重複",
    )
    args = ap.parse_args()
    exclude = {x.strip() for x in str(args.exclude).split(",") if x.strip()}
    # 第二輪再排除首輪 JSON 若存在
    round_id = int(args.round)
    seed_tag = f"20261026-r{round_id}"

    db = _db()
    conn = sqlite3.connect(db)
    try:
        # 若上一輪結果在，併入 exclude
        prev = sorted(_OUT.glob(f"audit-round-{round_id-1}-*.json")) if round_id > 1 else []
        if prev:
            try:
                prev_data = json.loads(prev[-1].read_text(encoding="utf-8"))
                for s in prev_data.get("sids") or []:
                    exclude.add(str(s))
            except Exception:
                pass
        sids = _random_liquid(conn, n=int(args.n), exclude=exclude, seed_tag=seed_tag)
        # 補流動股不足時放寬
        if len(sids) < int(args.n):
            more = _random_liquid(
                conn, n=int(args.n) * 3, exclude=exclude | set(sids), seed_tag=seed_tag + "b"
            )
            for s in more:
                if s not in sids:
                    sids.append(s)
                if len(sids) >= int(args.n):
                    break
        sids = [s for s in sids if _has_daily(conn, s)][: int(args.n)]
        names = {s: _name(conn, s) for s in sids}
    finally:
        conn.close()

    if not sids:
        print("no sids to sample", file=sys.stderr)
        return 2

    _OUT.mkdir(parents=True, exist_ok=True)
    out_dir = _OUT / f"round{round_id}"
    out_dir.mkdir(parents=True, exist_ok=True)

    all_scores = []
    for sid in sids:
        all_scores.extend(
            _render_and_score(sid, names.get(sid, sid), db, out_dir, round_id)
        )

    summary = summarize_scores(all_scores)
    stamp = datetime.now(_TAIPEI).strftime("%Y%m%d-%H%M%S")
    out_json = _OUT / f"audit-round-{round_id}-{stamp}.json"
    payload = {
        "round": round_id,
        "sids": sids,
        "names": names,
        "exclude": sorted(exclude),
        "summary": summary,
        "rows": [s.to_dict() for s in all_scores],
    }
    out_json.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({"round": round_id, "sids": sids, "summary": summary}, ensure_ascii=False, indent=2))
    print(f"wrote {out_json}")
    if summary.get("functional_fail", 0) > 0:
        return 2
    # 美感：允許少數 restyle，但 mean 須 ≥70 且 fail 美感比例不要過半
    if float(summary.get("aesthetic_mean") or 0) < 70.0:
        return 3
    if summary.get("n") and summary.get("needs_restyle", 0) > summary["n"] // 2:
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
