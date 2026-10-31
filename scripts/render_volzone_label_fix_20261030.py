#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""重渲 2383／3081／3595（＋抽樣）大量區標位修 → store media。不准搶 getUpdates。"""
from __future__ import annotations

import json
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
    "media/volzone-label-fix-20261030"
)

SAMPLE = [
    ("2383", "listed", "台光電"),
    ("3081", "otc", "聯亞"),
    ("3595", "emerging", "山太士"),
    ("2330", "listed", "台積電"),
    ("6274", "otc", "台燿"),
    ("7853", "emerging", "政美應用"),
]


def _db() -> str:
    from config import get_db_path

    p = Path(get_db_path())
    if not p.is_file():
        raise SystemExit(f"missing db: {p}")
    return str(p.resolve())


def _name(sid: str, db: str, fallback: str) -> str:
    import sqlite3

    conn = sqlite3.connect(db)
    try:
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
    finally:
        conn.close()
    return fallback


def _to_jpg(src: Path, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if src.suffix.lower() in {".png", ".jpg", ".jpeg"}:
        try:
            from PIL import Image

            Image.open(src).convert("RGB").save(
                dest, format="JPEG", quality=92, optimize=True
            )
            return dest
        except Exception:
            pass
    if src.resolve() != dest.resolve():
        shutil.copy2(src, dest)
    return dest


def _render_one(sid: str, name: str, db: str, dest_stem: Path) -> dict:
    import matplotlib.pyplot as plt
    from matplotlib.figure import Figure

    from vol_zone_chart import clear_vol_zone_render_cache, render_volume_zone_result

    clear_vol_zone_render_cache()
    texts: list[str] = []
    orig = Figure.savefig

    def hook(self, *a, **k):
        try:
            for ax in self.axes:
                for t in ax.texts:
                    if t.get_visible():
                        texts.append(str(t.get_text() or ""))
        except Exception:
            pass
        return orig(self, *a, **k)

    Figure.savefig = hook  # type: ignore
    tmp = dest_stem.with_suffix(".jpg")
    err = None
    path = None
    try:
        path, _cap = render_volume_zone_result(
            sid,
            name,
            db,
            str(tmp),
            with_nav_signals=True,
            lookup_portrait=False,
            with_parallel_channel=True,
            with_ma5_ma10=True,
        )
    except Exception as e:
        err = str(e)
    finally:
        Figure.savefig = orig  # type: ignore
        plt.close("all")

    if not path or not Path(path).is_file() or Path(path).stat().st_size < 20000:
        return {"sid": sid, "name": name, "ok": False, "error": err or "empty", "texts": texts}

    jpg = _to_jpg(Path(path), dest_stem.with_suffix(".jpg"))
    png = dest_stem.with_suffix(".png")
    try:
        from PIL import Image

        Image.open(path).convert("RGB").save(png, format="PNG", optimize=True)
    except Exception:
        shutil.copy2(path, png)

    has_press = any("大量區壓" in t for t in texts)
    has_hold = any("大量區撐" in t for t in texts)
    rails = [
        t
        for t in texts
        if any(k in t for k in ("下降壓", "平行撐", "平行壓", "上升軌", "上昇軌"))
    ]
    mas = [t for t in texts if t in ("5", "10", "月", "季")]
    exs = [t for t in texts if t.startswith("除息") or t.startswith("除權")]
    return {
        "sid": sid,
        "name": name,
        "ok": True,
        "jpg": str(jpg),
        "png": str(png),
        "size": jpg.stat().st_size,
        "press": has_press,
        "hold": has_hold,
        "rails": rails,
        "ma_stamps": mas,
        "ex_div": exs,
    }


def main() -> int:
    db = _db()
    OUT.mkdir(parents=True, exist_ok=True)
    rows = []
    for sid, mkt, fb in SAMPLE:
        name = _name(sid, db, fb)
        dest = OUT / f"label-fix-{sid}-{mkt}-volzone"
        print(f"== {sid} {name} ({mkt})", flush=True)
        row = _render_one(sid, name, db, dest)
        row["market"] = mkt
        rows.append(row)
        print(
            f"  ok={row.get('ok')} press={row.get('press')} hold={row.get('hold')} "
            f"rails={row.get('rails')} ma={row.get('ma_stamps')} ex={row.get('ex_div')}",
            flush=True,
        )
    summary = {"n": len(rows), "ok_n": sum(1 for r in rows if r.get("ok")), "rows": rows}
    (OUT / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"SUMMARY ok {summary['ok_n']}/{summary['n']}")
    return 0 if summary["ok_n"] == summary["n"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
