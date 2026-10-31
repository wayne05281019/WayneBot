#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""重渲 3595（＋2383／3081 對照）大量區：as_of=官方最新完整日。不准搶 getUpdates。"""
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
    "media/volzone-3595-date-fix-20261030"
)

SAMPLE = [
    ("3595", "emerging", "山太士"),
    ("2383", "listed", "台光電"),
    ("3081", "otc", "聯亞"),
]


def _db() -> str:
    from config import get_db_path

    p = Path(get_db_path())
    if not p.is_file():
        raise SystemExit(f"missing db: {p}")
    return str(p.resolve())


def main() -> int:
    import matplotlib.pyplot as plt
    from matplotlib.figure import Figure

    from vol_zone_chart import clear_vol_zone_render_cache, render_volume_zone_result

    db = _db()
    OUT.mkdir(parents=True, exist_ok=True)
    rows = []
    for sid, mkt, name in SAMPLE:
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
        dest = OUT / f"date-fix-{sid}-{mkt}-volzone.jpg"
        err = None
        path = None
        try:
            path, _ = render_volume_zone_result(
                sid,
                name,
                db,
                str(dest),
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
        ok = bool(path and Path(path).is_file() and Path(path).stat().st_size > 20000)
        if ok and Path(path).suffix.lower() != ".png":
            try:
                from PIL import Image

                Image.open(path).convert("RGB").save(
                    OUT / f"date-fix-{sid}-{mkt}-volzone.png", format="PNG"
                )
            except Exception:
                pass
        elif ok:
            shutil.copy2(path, OUT / f"date-fix-{sid}-{mkt}-volzone.png")
        head = [t for t in texts if "收盤" in t or "最近" in t or "10/" in t][:8]
        rows.append(
            {
                "sid": sid,
                "market": mkt,
                "ok": ok,
                "error": err,
                "path": str(dest) if ok else None,
                "sample_texts": head,
                "has_1029": any("10/29" in t or "10月29" in t for t in texts),
                "has_1028": any("10/28" in t or "10月28" in t for t in texts),
            }
        )
        print(
            f"{sid} ok={ok} has_1029={rows[-1]['has_1029']} has_1028={rows[-1]['has_1028']} texts={head[:4]}",
            flush=True,
        )
    (OUT / "summary.json").write_text(
        json.dumps({"rows": rows}, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return 0 if all(r["ok"] and r["has_1029"] for r in rows) else 2


if __name__ == "__main__":
    raise SystemExit(main())
