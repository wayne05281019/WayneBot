#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v2 鎖臉預覽：深灰下一層＋虛線標；主區只留桃色帶；量標上緣空帶。

只寫新檔名 preview-v2-*；不准覆寫舊 preview-*；不合／不上話筒。
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


def _render_vol(sid: str, name: str, db: str, out: Path, *, force_broke: bool = False) -> Path | None:
    import biaoke_next_support as bns
    from vol_zone_chart import clear_vol_zone_render_cache, render_volume_zone_result

    clear_vol_zone_render_cache()
    orig_resolve = bns.resolve_next_support

    def _wrap_resolve(*args, **kwargs):
        if force_broke:
            kwargs["under_support"] = True
            kwargs["over_pressure"] = False
        return orig_resolve(*args, **kwargs)

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
        bns.resolve_next_support = orig_resolve  # type: ignore
    if not path or not Path(path).is_file() or Path(path).stat().st_size < 20000:
        print(f"[skip-vol] {sid}")
        return None
    return _to_png(Path(path), out)


def _render_struct(sid: str, name: str, db: str, out: Path) -> Path | None:
    from three_in_one_chart import render_lookup_structure_result

    out.parent.mkdir(parents=True, exist_ok=True)
    path, _cap = render_lookup_structure_result(sid, name, db, str(out), card=None)
    if not path or not Path(path).is_file() or Path(path).stat().st_size < 20000:
        print(f"[skip-struct] {sid}")
        return None
    if Path(path).resolve() != out.resolve():
        shutil.copy2(path, out)
    return out


def main() -> int:
    db = _db()
    OUT.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    picks = ["3081", "2454"]
    print("next?", [(s, _has_next_layer(s, db)) for s in picks])

    for sid in picks:
        name = _name(sid, db)
        p = _render_vol(sid, name, db, OUT / f"preview-v2-{sid}-volzone.png")
        if p:
            written.append(str(p))
            print("[ok]", p)
        s = _render_struct(sid, name, db, OUT / f"preview-v2-{sid}-structure.png")
        if s:
            written.append(str(s))
            print("[ok]", s)

    # 2454 自然無下一層時補 demo
    if not _has_next_layer("2454", db):
        name = _name("2454", db)
        d = _render_vol(
            "2454",
            name,
            db,
            OUT / "preview-v2-2454-volzone-demo-broke.png",
            force_broke=True,
        )
        if d:
            written.append(str(d))
            print("[ok-demo]", d)

    print("written", len(written))
    for w in written:
        print(" ", w)
    return 0 if written else 1


if __name__ == "__main__":
    raise SystemExit(main())
