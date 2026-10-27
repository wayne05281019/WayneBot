#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""正式查股入口的「訊號層級」試看；只產獨立樣張，不改話筒預設。"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

os.environ.setdefault("WAYNE_SKIP_POLLING", "1")
os.environ.setdefault("MPLBACKEND", "Agg")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PIL import Image

from three_in_one_chart import render_lookup_structure_result
from vol_zone_chart import (
    clear_vol_zone_render_cache,
    prepare_lookup_structure_bars,
    prepare_volume_zone,
    render_lookup_vol_result,
)
from wayne_navigator import clear_lookup_render_cache


def _positive_bar(row: dict) -> bool:
    try:
        return all(float(row.get(k) or 0) > 0 for k in ("open", "high", "low", "close", "volume"))
    except (TypeError, ValueError):
        return False


def _to_real_png(src: Path, dst: Path) -> None:
    if not src.is_file() or src.stat().st_size < 20_000:
        raise RuntimeError(f"正式出圖失敗：{src}")
    with Image.open(src) as im:
        rgb = im.convert("RGB")
        rgb.save(dst, format="PNG", optimize=True)
    if not dst.is_file() or dst.stat().st_size < 20_000:
        raise RuntimeError(f"PNG 轉檔失敗：{dst}")
    with Image.open(dst) as check:
        if check.format != "PNG" or check.width < 2000 or check.height < 1500:
            raise RuntimeError(f"PNG 規格不符：{dst} {check.format} {check.size}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sid", default="2233")
    ap.add_argument("--name", default="宇隆")
    ap.add_argument("--db", default=str(ROOT / "data" / "wayne_market.db"))
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    sid = str(args.sid).strip()
    name = str(args.name).strip() or sid
    db = str(Path(args.db).resolve())
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)

    clear_lookup_render_cache()
    clear_vol_zone_render_cache()
    struct_pack = prepare_lookup_structure_bars(sid, name, db)
    bars = list((struct_pack or {}).get("bars") or [])
    if len(bars) < 8 or not _positive_bar(dict(bars[-1] or {})):
        raise RuntimeError("缺官方完整開高低收量，不產試看圖")

    struct_tmp = out / f".{sid}-structure-signal.jpg"
    vol_tmp = out / f".{sid}-volzone-signal.jpg"
    struct_png = out / f"{sid}-structure.png"
    vol_png = out / f"{sid}-volzone.png"
    for path in (struct_tmp, vol_tmp, struct_png, vol_png):
        path.unlink(missing_ok=True)

    struct_path, _ = render_lookup_structure_result(
        sid,
        name,
        db,
        str(struct_tmp),
        pack=struct_pack,
        visual_variant="signal",
    )
    vol_pack = prepare_volume_zone(
        sid,
        name,
        db,
        str(vol_tmp),
        preloaded_work=(struct_pack or {}).get("work"),
        known_ensure=(struct_pack or {}).get("vol_ensure"),
    )
    if not vol_pack or not dict(vol_pack.get("zone") or {}):
        raise RuntimeError("缺官方大量區，不產試看圖")
    vol_path, _ = render_lookup_vol_result(
        sid,
        name,
        db,
        str(vol_tmp),
        pack=vol_pack,
        visual_variant="signal",
    )

    _to_real_png(Path(struct_path), struct_png)
    _to_real_png(Path(vol_path), vol_png)
    struct_tmp.unlink(missing_ok=True)
    vol_tmp.unlink(missing_ok=True)

    latest = dict(bars[-1])
    zone = dict(vol_pack.get("zone") or {})
    print(
        json.dumps(
            {
                "sid": sid,
                "name": name,
                "latest_official": {
                    k: latest.get(k)
                    for k in ("date", "open", "high", "low", "close", "volume")
                },
                "main_zone": {
                    k: zone.get(k) for k in ("date", "high", "low", "volume")
                },
                "structure": str(struct_png),
                "volzone": str(vol_png),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
