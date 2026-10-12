#!/usr/bin/env python3
"""本機試渲：查股第 3 張結構更清楚、第 4 張大量區＋五日／十日。

只寫媒體檔，不改話筒預設。壓／撐／通道略粗、末日 K 醒目；五日／十日細線。
官方日 K 來自本地 DB，不准假柱。時區說明：檔名／圖內日期皆台北日曆日。
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("MPLBACKEND", "Agg")
os.environ.setdefault("WAYNE_SKIP_POLLING", "1")


def _db() -> str:
    from config import get_db_path

    p = Path(get_db_path())
    if not p.is_file():
        raise SystemExit(f"missing db: {p}")
    return str(p.resolve())


def _name(sid: str, db: str) -> str:
    import sqlite3

    conn = sqlite3.connect(db)
    try:
        row = conn.execute(
            "SELECT stock_name FROM daily_quotes WHERE stock_id=? ORDER BY date DESC LIMIT 1",
            (sid,),
        ).fetchone()
    finally:
        conn.close()
    return str(row[0]) if row and row[0] else sid


def _render_structure(sid: str, name: str, db: str, out: Path) -> Path:
    from three_in_one_chart import render_lookup_structure_result

    out.parent.mkdir(parents=True, exist_ok=True)
    path, _cap = render_lookup_structure_result(
        sid, name, db, str(out), card=None
    )
    if not path or not Path(path).is_file() or Path(path).stat().st_size < 20000:
        raise SystemExit(f"structure render failed: {sid} -> {out}")
    if Path(path).resolve() != out.resolve():
        shutil.copy2(path, out)
    return out


def _render_volzone(
    sid: str, name: str, db: str, out: Path, *, with_ma5_ma10: bool
) -> Path:
    from vol_zone_chart import render_volume_zone_result

    out.parent.mkdir(parents=True, exist_ok=True)
    # 大量區產品寫 jpeg；預覽要 png 檔名時先渲到旁檔再轉存
    tmp = out.with_suffix(".jpg") if out.suffix.lower() == ".png" else out
    path, _cap = render_volume_zone_result(
        sid,
        name,
        db,
        str(tmp),
        with_nav_signals=True,
        lookup_portrait=False,
        with_ma5_ma10=with_ma5_ma10,
    )
    if not path or not Path(path).is_file() or Path(path).stat().st_size < 20000:
        raise SystemExit(f"volzone render failed: {sid} -> {out}")
    src = Path(path)
    if src.resolve() != out.resolve():
        if out.suffix.lower() == ".png" and src.suffix.lower() in {".jpg", ".jpeg"}:
            from PIL import Image

            Image.open(src).convert("RGB").save(out, format="PNG", optimize=True)
        else:
            shutil.copy2(src, out)
    return out


def _patch_structure_clearer() -> None:
    """壓／撐／通道略粗＋對比；最新一根 K 略寬＋外框。只影響本行程。"""
    import biaoke_chart as bc
    import wayne_navigator as wn

    def _rail_thicker(ax, x1, y1, x2, y2, *, seam, x_lo, x_hi, y_lo, y_hi, color):
        clipped = bc._clip_line(
            x1, y1, x2, y2, x_lo=x_lo, x_hi=x_hi, y_lo=y_lo, y_hi=y_hi
        )
        if not clipped:
            return
        xa, ya, xb, yb = clipped
        if xa < seam:
            xs = [xa, min(xb, seam)]
            ys = [ya, bc._line_at(x1, y1, x2, y2, xs[1])]
            bc._halo_line(ax, xs, ys, color, lw=2.05, halo=1.15, ls="-", z=5)
        if xb > seam:
            xs = [max(xa, seam), xb]
            ys = [bc._line_at(x1, y1, x2, y2, xs[0]), yb]
            bc._halo_line(
                ax, xs, ys, color, lw=2.05, halo=1.15, ls=(0, (4, 2.2)), z=5
            )

    bc._paint_extended_rail = _rail_thicker  # type: ignore[assignment]

    # biaoke_chart 已 from-import paint_lookup_ohlc_candles，要改它自己的綁定
    _orig_paint = bc.paint_lookup_ohlc_candles

    def _paint_last_loud(ax, xs, opens, highs, lows, closes, **kw):
        import numpy as np

        up = _orig_paint(ax, xs, opens, highs, lows, closes, **kw)
        xs_a = np.asarray(xs, dtype=float)
        opens_a = np.asarray(opens, dtype=float)
        highs_a = np.asarray(highs, dtype=float)
        lows_a = np.asarray(lows, dtype=float)
        closes_a = np.asarray(closes, dtype=float)
        n = int(closes_a.shape[0])
        if n < 1:
            return up
        i = n - 1
        halt = kw.get("halt")
        if halt is not None:
            halt_arr = np.asarray(halt, dtype=bool)
            if halt_arr.shape[0] == n and bool(halt_arr[i]):
                return up
        span = kw.get("span")
        if span is None or not (float(span) > 0):
            span = max(float(np.nanmax(highs_a) - np.nanmin(lows_a)), 1e-6)
        z = int(kw.get("z") or 3)
        col = wn.LOOKUP_CANDLE_UP if bool(up[i]) else wn.LOOKUP_CANDLE_DN
        x = float(xs_a[i])
        o = float(opens_a[i])
        h = float(highs_a[i])
        l = float(lows_a[i])
        c = float(closes_a[i])
        # 外框強調末日 K，不另塞標籤
        ax.plot(
            [x, x],
            [l, h],
            color="#212121",
            linewidth=2.35,
            zorder=z + 4,
            solid_capstyle="round",
            alpha=0.88,
        )
        body_h = max(abs(c - o), float(span) * 0.002)
        body_bot = min(o, c)
        ax.bar(
            [x],
            [body_h],
            bottom=[body_bot],
            width=wn.LOOKUP_CANDLE_BODY_W + 0.10,
            color=[col],
            edgecolor="#212121",
            linewidth=1.55,
            zorder=z + 5,
            align="center",
        )
        return up

    bc.paint_lookup_ohlc_candles = _paint_last_loud  # type: ignore[assignment]

    _orig_render = bc.render_biaoke_structure_png

    def _render_with_thick_sr(*args, **kwargs):
        import matplotlib.axes

        Axes = matplotlib.axes.Axes
        _hl = Axes.hlines

        def _hl_thick(self, y, xmin, xmax, **kw):
            color = str(kw.get("color") or "")
            if color in (bc._PRESS, bc._HOLD):
                kw = dict(kw)
                kw["linewidth"] = max(float(kw.get("linewidth") or 1.15), 1.95)
                kw["alpha"] = max(float(kw.get("alpha") or 0.92), 0.98)
                kw["zorder"] = max(int(kw.get("zorder") or 4), 6)
            return _hl(self, y, xmin, xmax, **kw)

        Axes.hlines = _hl_thick  # type: ignore[assignment]
        try:
            return _orig_render(*args, **kwargs)
        finally:
            Axes.hlines = _hl  # type: ignore[assignment]

    bc.render_biaoke_structure_png = _render_with_thick_sr  # type: ignore[assignment]


def _patch_volzone_thin_ma5_ma10() -> None:
    """五日／十日細線；壓／撐主線維持（或略加粗）。月／季仍較醒目於五日十日。"""
    import vol_zone_chart as vz

    _orig_paint = vz._paint_volume_zone

    def _paint(*args, **kwargs):
        kwargs = dict(kwargs)
        # 強制開五日十日（呼叫端也會開；雙保險）
        kwargs["with_ma5_ma10"] = True
        # 暫改模組線寬常數式：包 plot
        import matplotlib.axes

        Axes = matplotlib.axes.Axes
        _plot = Axes.plot
        _hl = Axes.hlines if hasattr(Axes, "hlines") else None
        _axhline = Axes.axhline

        def _plot_thin(self, *a, **kw):
            color = str(kw.get("color") or "")
            if color == vz._MA5:
                kw = dict(kw)
                kw["linewidth"] = 0.95
                kw["alpha"] = 0.92
                kw["zorder"] = 3
            elif color == vz._MA10:
                kw = dict(kw)
                kw["linewidth"] = 1.05
                kw["alpha"] = 0.92
                kw["zorder"] = 3
            elif color == vz._MA20:
                kw = dict(kw)
                kw["linewidth"] = max(float(kw.get("linewidth") or 1.75), 1.75)
            elif color == vz._MA60:
                kw = dict(kw)
                kw["linewidth"] = max(float(kw.get("linewidth") or 1.85), 1.85)
            return _plot(self, *a, **kw)

        def _axhline_press(self, y, **kw):
            color = str(kw.get("color") or "")
            if color in (vz._PRESS, vz._HOLD):
                kw = dict(kw)
                kw["linewidth"] = max(float(kw.get("linewidth") or 1.35), 1.85)
                kw["zorder"] = max(int(kw.get("zorder") or 5), 7)
            return _axhline(self, y, **kw)

        Axes.plot = _plot_thin  # type: ignore[assignment]
        Axes.axhline = _axhline_press  # type: ignore[assignment]
        try:
            return _orig_paint(*args, **kwargs)
        finally:
            Axes.plot = _plot  # type: ignore[assignment]
            Axes.axhline = _axhline  # type: ignore[assignment]

    vz._paint_volume_zone = _paint  # type: ignore[assignment]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--out-dir",
        default="/cursor/stores/self/media/chart34-evolve",
        help="preview png dir",
    )
    ap.add_argument("--sids", default="3081,2330")
    args = ap.parse_args()
    out_dir = Path(args.out_dir)
    # store symlink may resolve; keep requested path
    out_dir.mkdir(parents=True, exist_ok=True)
    db = _db()
    sids = [s.strip() for s in str(args.sids).split(",") if s.strip()]

    # 1) before：現況結構（僅主檔 3081；副檔可選）
    for sid in sids:
        name = _name(sid, db)
        before = out_dir / f"{sid}-struct-before.png"
        print(f"[before] structure {sid} {name} -> {before}", flush=True)
        _render_structure(sid, name, db, before)

    # 2) clearer structure（清 memo，避免 before 快取蓋掉試渲）
    try:
        import wayne_navigator as wn

        with wn._LOOKUP_RENDER_LOCK:
            wn._LOOKUP_RENDER_MEMO.clear()
    except Exception:
        pass
    _patch_structure_clearer()
    for sid in sids:
        name = _name(sid, db)
        clearer = out_dir / (
            "3081-struct-clearer.png" if sid == "3081" else f"{sid}-struct-clearer.png"
        )
        print(f"[clearer] structure {sid} {name} -> {clearer}", flush=True)
        _render_structure(sid, name, db, clearer)

    # 3) volzone + MA5/MA10（細線）
    _patch_volzone_thin_ma5_ma10()
    for sid in sids:
        name = _name(sid, db)
        vz_out = out_dir / (
            "3081-volzone-ma5-ma10.png"
            if sid == "3081"
            else f"{sid}-volzone-ma5-ma10.png"
        )
        print(f"[volzone+ma] {sid} {name} -> {vz_out}", flush=True)
        _render_volzone(sid, name, db, vz_out, with_ma5_ma10=True)

    print("done", flush=True)
    for p in sorted(out_dir.glob("*.png")):
        print(f"  {p}  {p.stat().st_size}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
