#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""重渲大量區表頭收旁漲跌點／％：2383／3081／3595。不准搶 getUpdates。"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("MPLBACKEND", "Agg")
os.environ.setdefault("WAYNE_SKIP_POLLING", "1")

OUT = Path(
    "/cursor/stores/bc-01a0d9ba-b7e3-7f56-802d-4c6e57f8ad9e/"
    "media/volzone-header-chg-20261030"
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
                for t in self.texts:
                    if t.get_visible():
                        texts.append(str(t.get_text() or ""))
            except Exception:
                pass
            return orig(self, *a, **k)

        Figure.savefig = hook  # type: ignore
        dest = OUT / f"header-chg-{sid}-{mkt}-volzone.jpg"
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
        joined = "\n".join(texts)
        has_move = any(
            ("▲" in t or "▼" in t) and "%" in t for t in texts
        ) or ("▲" in joined and "%" in joined) or ("▼" in joined and "%" in joined)
        rows.append(
            {
                "sid": sid,
                "mkt": mkt,
                "path": str(path or dest),
                "ok": bool(path) and Path(path or "").is_file() and not err,
                "has_move": bool(has_move),
                "err": err,
                "sample_texts": [t for t in texts if ("收" in t or "現" in t or "▲" in t or "▼" in t)][:12],
            }
        )
        print(json.dumps(rows[-1], ensure_ascii=False))
    meta = OUT / "header-chg-meta.json"
    meta.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    bad = [r for r in rows if not r["ok"] or not r["has_move"]]
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
