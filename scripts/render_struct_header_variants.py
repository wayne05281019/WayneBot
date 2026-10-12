#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""結構圖頭欄多款試渲（官方柱 only；新檔名；不准覆寫）。Asia/Taipei。"""
from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("WAYNE_SKIP_POLLING", "1")
os.environ.setdefault("MPLBACKEND", "Agg")

from biaoke_brain import load_bars
from biaoke_chart import (
    _BARS,
    _STRUCTURE_HEADER_VARIANTS,
    _STRUCTURE_LOOKUP_FIG,
    render_biaoke_structure_png,
    stock_nameplate,
)
from vol_zone_chart import VOL_ZONE_DPI
from wayne_navigator import clear_lookup_render_cache

TP = ZoneInfo("Asia/Taipei")
DB = str(ROOT / "data" / "wayne_market.db")
OUT = Path(
    os.environ.get(
        "WAYNE_STRUCT_VARIANT_OUT",
        "/cursor/stores/bc-01a0d9ba-b7e3-7f56-802d-4c6e57f8ad9e/media/struct-header-variants",
    )
)


def main() -> int:
    sids = [a for a in sys.argv[1:] if a.isdigit()] or ["6669"]
    stamp = datetime.now(TP).strftime("%Y%m%d-%H%M%S")
    OUT.mkdir(parents=True, exist_ok=True)
    clear_lookup_render_cache()
    written: list[str] = []
    for sid in sids:
        bars = load_bars(DB, sid, n=max(int(_BARS) + 40, 220))
        if len(bars) < 8:
            print(f"skip {sid}: no official bars", file=sys.stderr)
            continue
        name = str(bars[-1].get("stock_name") or sid)
        plate = stock_nameplate(sid, name, DB)
        for var in _STRUCTURE_HEADER_VARIANTS:
            path = OUT / f"{sid}-struct-hdr-{var}-{stamp}.png"
            # 新檔名 only：若碰巧撞名就加秒後綴
            if path.exists():
                path = OUT / f"{sid}-struct-hdr-{var}-{stamp}-b.png"
            out = render_biaoke_structure_png(
                bars,
                str(path),
                sid=sid,
                name=name,
                plate=plate,
                db_path=DB,
                figsize=_STRUCTURE_LOOKUP_FIG,
                dpi=VOL_ZONE_DPI,
                press_band=None,
                header_variant=var,
            )
            if out and path.is_file() and path.stat().st_size > 20000:
                written.append(str(path))
                print(f"OK {var} {path} bytes={path.stat().st_size}")
            else:
                print(f"FAIL {var} {path}", file=sys.stderr)
                return 1
            # 另存頭欄裁切（新檔名）
            try:
                from PIL import Image

                im = Image.open(path)
                w, h = im.size
                crop = im.crop((0, 0, w, int(h * 0.32)))
                crop_path = OUT / f"{sid}-struct-hdr-{var}-crop-{stamp}.png"
                if crop_path.exists():
                    crop_path = OUT / f"{sid}-struct-hdr-{var}-crop-{stamp}-b.png"
                crop.save(crop_path)
                written.append(str(crop_path))
                print(f"OK {var}-crop {crop_path}")
            except Exception as exc:
                print(f"crop skip {var}: {exc}", file=sys.stderr)
    print(f"stamp={stamp} n={len(written)}")
    return 0 if written else 1


if __name__ == "__main__":
    raise SystemExit(main())
