#!/usr/bin/env python3
"""自抽測智能標籤：多檔×結構／大量區 → 基本評測套件分數表。

三輪抽測：--round 1|2|3；每輪標的互不重複；真渲＋量化。
Asia/Taipei。不准搶 getUpdates。paint 單線（本機 Agg）。
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
    "label-placement-20261027"
)
# 先前輪次＋例圖股：三輪互斥時一律排除
_ALREADY = {
    "00683L",
    "009800",
    "1229",
    "1259",
    "1316",
    "1325",
    "1441",
    "1506",
    "1907",
    "2059",
    "2308",
    "2330",
    "2345",
    "2367",
    "2368",
    "2376",
    "2380",
    "2618",
    "3189",
    "3288",
    "3363",
    "3388",
    "3441",
    "3501",
    "3570",
    "3588",
    "3595",
    "3596",
    "4129",
    "4142",
    "4192",
    "4304",
    "4414",
    "4552",
    "4747",
    "4770",
    "5457",
    "5478",
    "5520",
    "5876",
    "6104",
    "6142",
    "6148",
    "6170",
    "6180",
    "6414",
    "6477",
    "6496",
    "6577",
    "6592",
    "6614",
    "6641",
    "6669",
    "6698",
    "6739",
    "6792",
    "6803",
    "6829",
    "6863",
    "6931",
    "7717",
    "7730",
    "7853",
    "8103",
    "8183",
    "8234",
    "8473",
    "8481",
    "9912",
    "9934",
    "9942",
}


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


def _is_etf_like(sid: str) -> bool:
    s = str(sid or "")
    if not s:
        return True
    if s.endswith(("L", "R")):
        return True
    if s.startswith("00") and len(s) >= 4:
        return True
    return False


def _random_liquid(
    conn: sqlite3.Connection, *, n: int, exclude: set[str], seed_tag: str
) -> list[str]:
    rows = conn.execute(
        """
        SELECT stock_id, COUNT(*) c FROM daily_quotes
        WHERE date>='2025-01-01' AND volume>0
        GROUP BY stock_id HAVING c>=120
        """
    ).fetchall()
    pool = [
        str(r[0])
        for r in rows
        if str(r[0]) not in exclude and not _is_etf_like(str(r[0]))
    ]
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
        elif txt.startswith("大量區"):
            kind = "key"
        elif txt.startswith(("壓 ", "撐 ")) or txt in ("壓", "撐"):
            kind = "key"
        elif "月" in txt[:6] and ("撐為" in txt or "壓為" in txt or "收盤" in txt):
            kind = "path"
        elif txt in ("5", "10", "月", "季"):
            kind = "ma"
        elif any(
            k in txt
            for k in ("下降壓", "平行撐", "上昇軌", "上升軌", "平行壓", "上軌", "下軌")
        ):
            # 與 collect_labels_from_ax 同源：上升／平行撐＝下軌欄；下降／平行壓＝上軌欄
            kind = "channel_u"
            if any(k in txt for k in ("平行撐", "上昇軌", "上升軌", "下軌")):
                kind = "channel_l"
            if any(k in txt for k in ("下降壓", "平行壓", "上軌")):
                kind = "channel_u"
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
                    # clip_on=False 且仍在 figure 內＝可視，不算裁切
                    if bool(getattr(art, "get_clip_on", lambda: True)()):
                        clipped = True
                    else:
                        fbb = ax.figure.bbox
                        if (
                            bb.x0 < fbb.x0 - 2
                            or bb.x1 > fbb.x1 + 2
                            or bb.y0 < fbb.y0 - 2
                            or bb.y1 > fbb.y1 + 2
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


def _dedupe_labels(labels):
    """同一文案只留一次（artist／record／Text 三路常重複）；保留較緊 bbox。"""
    from smart_label_metrics import LabelBox

    best: dict = {}
    for L in labels:
        key = (str(L.kind), str(L.text).strip())
        area = max(0.0, float(L.x1) - float(L.x0)) * max(
            0.0, float(L.y1) - float(L.y0)
        )
        prev = best.get(key)
        if prev is None:
            best[key] = (area, L)
            continue
        # 同文案取較小盒（record 常高估 half_h 誤判壓 K）
        if area < prev[0] * 0.92 or (
            abs(area - prev[0]) < 1e-6 and (L.clipped or L.orphan)
        ):
            best[key] = (area, L)
    out = [v[1] for v in best.values()]
    # 型別保險
    return [x for x in out if isinstance(x, LabelBox)]


def _score_figure(sid: str, chart: str, fig) -> object:
    from smart_label_metrics import ChartGeom, collect_labels_from_ax, score_chart

    ax = fig.axes[0] if fig.axes else None
    if ax is None:
        raise RuntimeError("no axes")
    ohlc = getattr(ax, "_wayne_channel_label_ohlc", None)
    if ohlc is not None:
        highs, lows, n = ohlc
        ymin, ymax = ax.get_ylim()
    else:
        import numpy as np

        ymin, ymax = ax.get_ylim()
        xlim = ax.get_xlim()
        n = max(int(xlim[1]), 40)
        highs = np.full(n, ymax - (ymax - ymin) * 0.2)
        lows = np.full(n, ymin + (ymax - ymin) * 0.2)
    # 先清掉粗估 record 盒，改以 Text 實測為準；通道仍認 artist
    try:
        saved = getattr(ax, "_wayne_smart_label_boxes", None)
        ax._wayne_smart_label_boxes = []  # type: ignore[attr-defined]
    except Exception:
        saved = None
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
    if saved is not None:
        try:
            ax._wayne_smart_label_boxes = saved  # type: ignore[attr-defined]
        except Exception:
            pass
    geom = _enrich_labels_from_texts(ax, geom)
    if len(fig.axes) > 1:
        try:
            geom = _enrich_labels_from_texts(fig.axes[1], geom)
        except Exception:
            pass
    geom = ChartGeom(
        n=geom.n,
        highs=geom.highs,
        lows=geom.lows,
        labels=_dedupe_labels(geom.labels),
        vol_heights=geom.vol_heights,
        ymin=geom.ymin,
        ymax=geom.ymax,
        xmin=geom.xmin,
        xmax=geom.xmax,
        chart=geom.chart,
        sid=geom.sid,
    )
    return score_chart(geom)


def _score_sid_official_channel(sid: str, db: str, *, chart: str):
    """用官方柱推平行通道＋同帶標位，量化一筆（結構／大量區共用定位碼）。"""
    import numpy as np
    import sqlite3 as _sql

    from biaoke_chart import infer_parallel_channel
    from smart_label_metrics import ChartGeom, LabelBox, score_chart
    from vol_zone_chart import _blank_for_channel_label, _channel_box_k_hits

    conn = _sql.connect(db)
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
            continue
        box = (cx - dx / 2, cx + dx / 2, cy - dy / 2, cy + dy / 2)
        hits = _channel_box_k_hits(
            *box, n=n, highs=highs, lows=lows, mark_pad=0.0, span=span
        )
        if hits >= 1:
            continue
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


def _render_and_score(sid: str, name: str, db: str, out_dir: Path, round_id: int):
    import matplotlib.pyplot as plt
    from matplotlib.figure import Figure

    from smart_label_metrics import MetricScore
    from three_in_one_chart import render_lookup_structure_result
    from vol_zone_chart import render_volume_zone_result

    scores: list[MetricScore] = []
    captured: list = []
    pending_chart = {"chart": None}

    orig_savefig = Figure.savefig

    def _hook_savefig(self, *args, **kwargs):
        chart = pending_chart.get("chart") or getattr(
            self, "_wayne_audit_chart", None
        )
        try:
            if chart:
                captured.append(_score_figure(str(sid), str(chart), self))
        except Exception as e:
            print(f"score-hook fail {sid}/{chart}: {e}", flush=True)
        return orig_savefig(self, *args, **kwargs)

    Figure.savefig = _hook_savefig  # type: ignore[method-assign]
    try:
        sp = out_dir / f"r{round_id}-{sid}-structure.jpg"
        try:
            pending_chart["chart"] = "structure"
            path, _ = render_lookup_structure_result(
                sid, name, db, str(sp), card=None
            )
            print(f"struct ok {sid} {path}")
        except Exception as e:
            print(f"struct fail {sid}: {e}", flush=True)
        vp = out_dir / f"r{round_id}-{sid}-volzone.jpg"
        try:
            pending_chart["chart"] = "volzone"
            path, _ = render_volume_zone_result(
                sid,
                name,
                db,
                str(vp),
                with_nav_signals=True,
                lookup_portrait=False,
                with_ma5_ma10=True,
            )
            print(f"vol ok {sid} {path}")
        except Exception as e:
            print(f"vol fail {sid}: {e}", flush=True)
    finally:
        pending_chart["chart"] = None
        Figure.savefig = orig_savefig  # type: ignore[method-assign]
        plt.close("all")

    scores.extend([s for s in captured if isinstance(s, MetricScore)])
    # 通道定位碼（合成）補一筆；真渲分數為主
    scores.extend(_score_sid_official_channel(sid, db, chart="structure-ch"))
    scores.extend(_score_sid_official_channel(sid, db, chart="volzone-ch"))
    return scores


def main() -> int:
    from smart_label_metrics import summarize_scores

    ap = argparse.ArgumentParser()
    ap.add_argument("--round", type=int, default=1, choices=(1, 2, 3))
    ap.add_argument("--n", type=int, default=6, help="每輪抽幾檔（真渲）")
    ap.add_argument(
        "--exclude",
        default=",".join(sorted(_ALREADY)),
        help="逗號分隔已渲股，勿重複",
    )
    ap.add_argument(
        "--sids",
        default="",
        help="逗號分隔指定股（測試用）；空＝自抽",
    )
    args = ap.parse_args()
    exclude = {x.strip() for x in str(args.exclude).split(",") if x.strip()}
    round_id = int(args.round)
    seed_tag = f"20261027-r{round_id}"

    db = _db()
    conn = sqlite3.connect(db)
    try:
        # 併入本目錄先前輪 JSON 的 sids（互斥）
        for prev_r in range(1, round_id):
            for prev in sorted(_OUT.glob(f"audit-round-{prev_r}-*.json")):
                try:
                    prev_data = json.loads(prev.read_text(encoding="utf-8"))
                    for s in prev_data.get("sids") or []:
                        exclude.add(str(s))
                except Exception:
                    pass
        if str(args.sids).strip():
            sids = [
                x.strip()
                for x in str(args.sids).split(",")
                if x.strip() and x.strip() not in exclude
            ][: int(args.n)]
        else:
            sids = _random_liquid(
                conn, n=int(args.n), exclude=exclude, seed_tag=seed_tag
            )
            if len(sids) < int(args.n):
                more = _random_liquid(
                    conn,
                    n=int(args.n) * 4,
                    exclude=exclude | set(sids),
                    seed_tag=seed_tag + "b",
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

    # 互斥硬閘
    overlap = set(sids) & exclude
    if overlap:
        print(f"exclude overlap: {sorted(overlap)}", file=sys.stderr)
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
    print(
        json.dumps(
            {"round": round_id, "sids": sids, "summary": summary},
            ensure_ascii=False,
            indent=2,
        )
    )
    print(f"wrote {out_json}")
    if summary.get("functional_fail", 0) > 0:
        return 2
    if float(summary.get("aesthetic_mean") or 0) < 70.0:
        return 3
    if summary.get("n") and summary.get("needs_restyle", 0) > summary["n"] // 2:
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
