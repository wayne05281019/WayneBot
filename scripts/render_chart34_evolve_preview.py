#!/usr/bin/env python3
"""本機試渲：查股第 3 張結構細虛線、第 4 張大量區＋五日／十日空白標。

只寫媒體檔，不改話筒預設。結構＝細虛線通道＋細壓撐（另 worker）；
大量區＝五日／十日細線、月／季較粗、均線短標中左。
官方日 K 來自本地 DB（缺洞先 STOCK_DAY 補），不准假柱。
檔名必含台北時分秒或 tip sha，不准覆寫同路徑。
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
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


def _db() -> str:
    from config import get_db_path

    p = Path(get_db_path())
    if not p.is_file():
        raise SystemExit(f"missing db: {p}")
    return str(p.resolve())


def _tip_sha() -> str:
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "--short=8", "HEAD"],
            cwd=str(ROOT),
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
        return out or "nosha"
    except Exception:
        return "nosha"


def _stamp() -> str:
    """台北 YYYYMMDD-HHMMSS＋tip sha，保證新檔名。"""
    now = datetime.now(_TAIPEI).strftime("%Y%m%d-%H%M%S")
    return f"{now}-{_tip_sha()}"


def _unique_path(out_dir: Path, stem: str, *, suffix: str = ".png") -> Path:
    """永不覆寫：若撞名再加序號。"""
    base = out_dir / f"{stem}{suffix}"
    if not base.exists():
        return base
    for i in range(2, 100):
        cand = out_dir / f"{stem}-r{i}{suffix}"
        if not cand.exists():
            return cand
    return out_dir / f"{stem}-{_stamp()}{suffix}"


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


def _patch_structure_thin_dash() -> None:
    """v2 試渲：通道細虛線、壓／撐細水平線、末日 K 右側細勾（不擋影線／收價）。"""
    import biaoke_chart as bc
    import wayne_navigator as wn

    _DASH = (0, (3.6, 2.6))

    def _rail_thin_dash(ax, x1, y1, x2, y2, *, seam, x_lo, x_hi, y_lo, y_hi, color):
        clipped = bc._clip_line(
            x1, y1, x2, y2, x_lo=x_lo, x_hi=x_hi, y_lo=y_lo, y_hi=y_hi
        )
        if not clipped:
            return
        xa, ya, xb, yb = clipped
        # 全程較細虛線（長 dash）；無粗暈、無粗實線
        ax.plot(
            [xa, xb],
            [ya, yb],
            color=color,
            linewidth=0.70,
            linestyle=_DASH,
            zorder=4,
            solid_capstyle="butt",
            solid_joinstyle="miter",
            alpha=0.88,
        )

    bc._paint_extended_rail = _rail_thin_dash  # type: ignore[assignment]

    # 通道樞紐／觸點圓點拿掉：細虛線本身已標軌，圓點易被看成「藍圓蓋 K」
    _orig_channel = bc._paint_parallel_channel

    def _channel_no_dots(ax, ch, **kw):
        if not ch:
            return
        kind = str(ch.get("kind") or "")
        color = bc._UP_TRACK if kind == "asc" else bc._DOWN_TRACK
        if not bool(ch.get("alive")):
            color = "#90a4ae"
        upper = ch.get("upper") or ()
        lower = ch.get("lower") or ()
        if len(upper) < 2 or len(lower) < 2:
            return
        (ux1, uy1, _ud1), (ux2, uy2, _ud2) = upper
        (lx1, ly1, _ld1), (lx2, ly2, _ld2) = lower
        seam = float(kw["seam"])
        x_lo = float(kw["x_lo"])
        x_hi = float(kw["x_hi"])
        y_lo = float(kw["y_lo"])
        y_hi = float(kw["y_hi"])
        rail_hi = float(x_hi) if bool(ch.get("alive")) else float(seam)
        for x1, y1, x2, y2 in (
            (ux1, uy1, ux2, uy2),
            (lx1, ly1, lx2, ly2),
        ):
            bc._paint_extended_rail(
                ax,
                float(x1),
                float(y1),
                float(x2),
                float(y2),
                seam=seam,
                x_lo=x_lo,
                x_hi=rail_hi,
                y_lo=y_lo,
                y_hi=y_hi,
                color=color,
            )
        # 刻意不画 scatter 觸點／樞紐圓

    bc._paint_parallel_channel = _channel_no_dots  # type: ignore[assignment]

    _orig_paint = bc.paint_lookup_ohlc_candles

    def _paint_last_tick(ax, xs, opens, highs, lows, closes, **kw):
        """末日 K：實體細邊＋右側收價細勾；不重畫影線、不蓋收價標籤。"""
        import numpy as np

        up = _orig_paint(ax, xs, opens, highs, lows, closes, **kw)
        xs_a = np.asarray(xs, dtype=float)
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
        x = float(xs_a[i])
        c = float(closes_a[i])
        if not (c > 0):
            return up
        z = int(kw.get("z") or 3)
        span = kw.get("span")
        if span is None or not (float(span) > 0):
            highs_a = np.asarray(highs, dtype=float)
            lows_a = np.asarray(lows, dtype=float)
            span = max(float(np.nanmax(highs_a) - np.nanmin(lows_a)), 1e-6)
        # 只做右側收價細勾（短橫＋小三角）；不描實體外框，避免又變粗框蓋 K
        x0 = x + float(wn.LOOKUP_CANDLE_BODY_W) * 0.55 + 0.14
        x1 = x0 + 0.85
        ink = "#37474f"
        ax.plot(
            [x0, x1],
            [c, c],
            color=ink,
            linewidth=1.20,
            zorder=z + 6,
            solid_capstyle="butt",
            alpha=0.96,
        )
        tri_w = 0.32
        tri_h = float(span) * 0.012
        ax.fill(
            [x1, x1 + tri_w, x1],
            [c + tri_h * 0.55, c, c - tri_h * 0.55],
            color=ink,
            zorder=z + 7,
            alpha=0.94,
            linewidth=0,
            clip_on=False,
        )
        return up

    bc.paint_lookup_ohlc_candles = _paint_last_tick  # type: ignore[assignment]

    _orig_render = bc.render_biaoke_structure_png

    def _render_with_thin_sr(*args, **kwargs):
        import matplotlib.axes

        Axes = matplotlib.axes.Axes
        _hl = Axes.hlines

        def _hl_thin(self, y, xmin, xmax, **kw):
            color = str(kw.get("color") or "")
            if color in (bc._PRESS, bc._HOLD):
                kw = dict(kw)
                # 細線可辨色；zorder 低於 K，勿蓋影線
                kw["linewidth"] = 0.70
                kw["alpha"] = 0.82
                kw["zorder"] = 2
            return _hl(self, y, xmin, xmax, **kw)

        Axes.hlines = _hl_thin  # type: ignore[assignment]
        try:
            return _orig_render(*args, **kwargs)
        finally:
            Axes.hlines = _hl  # type: ignore[assignment]

    bc.render_biaoke_structure_png = _render_with_thin_sr  # type: ignore[assignment]


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
    ap.add_argument(
        "--mode",
        default="volzone-labels",
        choices=("thin-dash", "before", "volzone", "volzone-labels", "all"),
        help="volzone-labels＝大量區空白均線標（預設）；thin-dash＝結構細虛線；all＝全套",
    )
    args = ap.parse_args()
    out_dir = Path(args.out_dir)
    # store symlink may resolve; keep requested path
    out_dir.mkdir(parents=True, exist_ok=True)
    db = _db()
    sids = [s.strip() for s in str(args.sids).split(",") if s.strip()]

    mode = str(getattr(args, "mode", "volzone-labels") or "volzone-labels")

    def _clear_memo() -> None:
        try:
            import wayne_navigator as wn

            with wn._LOOKUP_RENDER_LOCK:
                wn._LOOKUP_RENDER_MEMO.clear()
        except Exception:
            pass

    stamp = _stamp()
    written: list[Path] = []

    if mode in ("all", "before"):
        for sid in sids:
            name = _name(sid, db)
            before = _unique_path(out_dir, f"{sid}-struct-before-{stamp}")
            print(f"[before] structure {sid} {name} -> {before}", flush=True)
            written.append(_render_structure(sid, name, db, before))

    if mode in ("all", "thin-dash"):
        _clear_memo()
        _patch_structure_thin_dash()
        for sid in sids:
            name = _name(sid, db)
            out = _unique_path(out_dir, f"{sid}-struct-thin-dash-{stamp}")
            print(f"[thin-dash] structure {sid} {name} -> {out}", flush=True)
            written.append(_render_structure(sid, name, db, out))

    if mode in ("all", "volzone", "volzone-labels"):
        try:
            from vol_zone_chart import clear_vol_zone_render_cache

            clear_vol_zone_render_cache()
        except Exception:
            pass
        _patch_volzone_thin_ma5_ma10()
        for sid in sids:
            name = _name(sid, db)
            blank = _unique_path(
                out_dir, f"{sid}-volzone-ma-short-auto-{stamp}"
            )
            print(f"[volzone+ma-auto] {sid} {name} -> {blank}", flush=True)
            written.append(
                _render_volzone(sid, name, db, blank, with_ma5_ma10=True)
            )

    print("done", flush=True)
    print(f"stamp={stamp}", flush=True)
    for p in written:
        print(f"  NEW {p.resolve()}  {p.stat().st_size}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
