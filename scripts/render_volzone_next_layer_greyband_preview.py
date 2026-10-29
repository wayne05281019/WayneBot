#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""本機預覽：下一層淺灰價帶（無虛線／無下一層壓撐標）＋主區標略縮。

只寫媒體檔；不准合 main／不准上話筒。官方柱來自本地 DB。
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("MPLBACKEND", "Agg")
os.environ.setdefault("WAYNE_SKIP_POLLING", "1")

OUT = Path(
    "/cursor/stores/bc-01a0d9ba-b7e3-7f56-802d-4c6e57f8ad9e/"
    "media/volzone-next-layer-preview-20261029"
)
SIDS = ("2454", "3081", "1605", "2383", "1303")


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
            "SELECT stock_name FROM daily_quotes WHERE stock_id=? "
            "ORDER BY date DESC LIMIT 1",
            (sid,),
        ).fetchone()
    finally:
        conn.close()
    return str(row[0]) if row and row[0] else sid


def _to_png(src: Path, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if src.suffix.lower() in {".jpg", ".jpeg"} and dest.suffix.lower() == ".png":
        from PIL import Image

        Image.open(src).convert("RGB").save(dest, format="PNG", optimize=True)
    elif src.resolve() != dest.resolve():
        shutil.copy2(src, dest)
    return dest


def _render_vol(
    sid: str,
    name: str,
    db: str,
    out: Path,
    *,
    layer_marks: str | None = None,
    band_alpha: float | None = None,
    color_band: str | None = None,
    hairline: bool = False,
    force_broke: bool = False,
) -> Path | None:
    import biaoke_next_support as bns
    from vol_zone_chart import clear_vol_zone_render_cache, render_volume_zone_result

    # 預覽改 layer_marks／alpha／強制破撐時必須清 memo，否則同指紋會複製舊圖
    clear_vol_zone_render_cache()

    orig_paint = bns.paint_written_and_next_levels
    orig_resolve = bns.resolve_next_support

    def _wrap_paint(ax, *args, **kwargs):
        if layer_marks is not None:
            kwargs["layer_marks"] = layer_marks
        if band_alpha is not None:
            kwargs["band_alpha"] = float(band_alpha)
        if color_band is not None:
            kwargs["color_band"] = color_band
        ys = orig_paint(ax, *args, **kwargs)
        if hairline:
            pack = dict(kwargs.get("next_pack") or {})
            layer = dict(pack.get("layer") or {})
            if not layer and pack.get("primary"):
                layer = dict((pack.get("primary") or {}).get("layer") or {})
            show = bool(pack.get("broke") or pack.get("over")) and bool(layer)
            if show:
                try:
                    lo = float(layer.get("low") or layer.get("support") or 0)
                    hi = float(layer.get("high") or layer.get("pressure") or 0)
                except (TypeError, ValueError):
                    lo = hi = 0.0
                if lo > 0 and hi >= lo:
                    xmin = float(kwargs.get("xmin", -0.55))
                    xmax = float(kwargs.get("xmax", 0.0))
                    for y in (lo, hi):
                        try:
                            ax.hlines(
                                y,
                                xmin=xmin,
                                xmax=xmax,
                                colors="#78909c",
                                linestyles=(0, (1.2, 1.8)),
                                linewidth=0.55,
                                zorder=1.2,
                                alpha=0.45,
                            )
                        except Exception:
                            pass
        return ys

    def _wrap_resolve(*args, **kwargs):
        if force_broke:
            kwargs["under_support"] = True
            kwargs["over_pressure"] = False
        return orig_resolve(*args, **kwargs)

    bns.paint_written_and_next_levels = _wrap_paint  # type: ignore
    if force_broke:
        bns.resolve_next_support = _wrap_resolve  # type: ignore
    try:
        tmp = out.with_suffix(".jpg")
        path, _cap = render_volume_zone_result(
            sid,
            name,
            db,
            str(tmp),
            with_nav_signals=True,
            lookup_portrait=False,
            with_ma5_ma10=True,
        )
    finally:
        bns.paint_written_and_next_levels = orig_paint  # type: ignore
        bns.resolve_next_support = orig_resolve  # type: ignore
    if not path or not Path(path).is_file() or Path(path).stat().st_size < 20000:
        print(f"[skip-vol] {sid} render failed")
        return None
    return _to_png(Path(path), out)


def _render_struct(sid: str, name: str, db: str, out: Path) -> Path | None:
    from three_in_one_chart import render_lookup_structure_result

    out.parent.mkdir(parents=True, exist_ok=True)
    path, _cap = render_lookup_structure_result(
        sid, name, db, str(out), card=None
    )
    if not path or not Path(path).is_file() or Path(path).stat().st_size < 20000:
        print(f"[skip-struct] {sid} render failed")
        return None
    if Path(path).resolve() != out.resolve():
        shutil.copy2(path, out)
    return out


def _has_next_layer(sid: str, db: str) -> bool:
    from biaoke_brain import load_bars, volume_first_price
    from biaoke_next_support import resolve_next_support

    bars = load_bars(db, sid, n=120)
    if len(bars) < 40:
        return False
    st = volume_first_price(bars[-60:], lookback=40)
    pack = resolve_next_support(
        bars[-80:],
        sid=sid,
        close=float(bars[-1].get("close") or 0),
        support=float(st.get("spike_low") or 0),
        pressure=float(st.get("spike_high") or 0),
        spike_date=str(st.get("spike_date") or ""),
    )
    return bool(
        (pack.get("broke") or pack.get("over"))
        and (pack.get("layer") or (pack.get("primary") or {}).get("layer"))
    )


def main() -> int:
    db = _db()
    OUT.mkdir(parents=True, exist_ok=True)
    written: list[str] = []

    # 2454（使用者參考）＋至少一檔自然有下一層
    natural_next = [s for s in SIDS if s != "2454" and _has_next_layer(s, db)]
    picks = ["2454"] + natural_next[:1]
    if len(picks) < 2 and natural_next:
        picks.append(natural_next[0])
    print("picks", picks, [(s, _has_next_layer(s, db)) for s in picks])

    for sid in picks:
        name = _name(sid, db)
        p = _render_vol(
            sid,
            name,
            db,
            OUT / f"preview-{sid}-volzone-greyband.png",
        )
        if p:
            written.append(str(p))
            print("[ok]", p, "next=", _has_next_layer(sid, db))
        s = _render_struct(
            sid, name, db, OUT / f"preview-{sid}-structure-greyband.png"
        )
        if s:
            written.append(str(s))
            print("[ok]", s)

    # 2454 目前收在撐上＝自然無下一層；強制破撐 demo 灰帶（對照使用者參考）
    name = _name("2454", db)
    demo = _render_vol(
        "2454",
        name,
        db,
        OUT / "preview-2454-volzone-greyband-demo-broke.png",
        force_broke=True,
    )
    if demo:
        written.append(str(demo))
        print("[ok-demo]", demo)

    # 建議A／B：用有下一層的自然檔（或 2454 demo）
    polish_sid = natural_next[0] if natural_next else "2454"
    polish_name = _name(polish_sid, db)
    force = polish_sid == "2454"
    a = _render_vol(
        polish_sid,
        polish_name,
        db,
        OUT / f"preview-{polish_sid}-volzone-建議A-band-stronger.png",
        band_alpha=0.30,
        color_band="#78909c",
        force_broke=force,
    )
    if a:
        written.append(str(a))
        print("[ok-A]", a)
    b = _render_vol(
        polish_sid,
        polish_name,
        db,
        OUT / f"preview-{polish_sid}-volzone-建議B-band-hairline.png",
        band_alpha=0.16,
        color_band="#90a4ae",
        hairline=True,
        force_broke=force,
    )
    if b:
        written.append(str(b))
        print("[ok-B]", b)

    # 對照：同一檔舊臉（虛線＋標）
    before = _render_vol(
        polish_sid,
        polish_name,
        db,
        OUT / f"preview-{polish_sid}-volzone-before-lines.png",
        layer_marks="both",
        force_broke=force,
    )
    if before:
        written.append(str(before))
        print("[ok-before]", before)

    print("written", len(written))
    for w in written:
        print(" ", w)
    return 0 if written else 1


if __name__ == "__main__":
    raise SystemExit(main())
