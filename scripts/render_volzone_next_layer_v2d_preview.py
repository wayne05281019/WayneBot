#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v2d：桃色加深＋主區壓撐標略縮＋收價紅黑綠。不合／不上話筒。"""
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


def _render_vol(sid: str, name: str, db: str, out: Path, *, force_broke: bool = False) -> Path | None:
    import biaoke_next_support as bns
    from vol_zone_chart import clear_vol_zone_render_cache, render_volume_zone_result

    clear_vol_zone_render_cache()
    orig = bns.resolve_next_support

    def _wrap(*a, **k):
        if force_broke:
            k["under_support"] = True
            k["over_pressure"] = False
        return orig(*a, **k)

    if force_broke:
        bns.resolve_next_support = _wrap  # type: ignore
    try:
        tmp = out.with_suffix(".jpg")
        path, _ = render_volume_zone_result(
            sid,
            name,
            db,
            str(tmp),
            with_nav_signals=True,
            lookup_portrait=False,
            with_ma5_ma10=True,
        )
    finally:
        bns.resolve_next_support = orig  # type: ignore
    if not path or not Path(path).is_file() or Path(path).stat().st_size < 20000:
        return None
    return _to_png(Path(path), out)


def main() -> int:
    db = _db()
    OUT.mkdir(parents=True, exist_ok=True)
    written = []
    for sid in ("3081", "2454"):
        p = _render_vol(sid, _name(sid, db), db, OUT / f"preview-v2d-{sid}-volzone.png")
        if p:
            written.append(str(p))
            print("ok", p)
        else:
            print("fail", sid)
    # 2454 常貼撐無下一層：demo 破撐看灰帶仍在
    p = _render_vol(
        "2454",
        _name("2454", db),
        db,
        OUT / "preview-v2d-2454-volzone-demo-broke.png",
        force_broke=True,
    )
    if p:
        written.append(str(p))
        print("ok", p)
    print(f"n={len(written)}")
    return 0 if len(written) >= 2 else 1


if __name__ == "__main__":
    raise SystemExit(main())
