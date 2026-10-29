#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""重渲大量區：表頭開／高補回＋停發明全市場空日假量柱。2383／3081／3595。不准搶 getUpdates。"""
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
    "media/volzone-header-bar-fix-20261030"
)
# 相容 symlink／self 掛載
OUT_SELF = Path("/cursor/stores/self/media/volzone-header-bar-fix-20261030")

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

    from vol_zone_chart import (
        clear_ensure_official_volume_cache,
        clear_vol_zone_render_cache,
        load_official_ohlc,
        market_wide_empty_open_days,
        official_work,
        render_volume_zone_result,
    )
    from wayne_navigator import clear_align_ohlc_cache

    db = _db()
    OUT.mkdir(parents=True, exist_ok=True)
    if OUT_SELF != OUT:
        try:
            OUT_SELF.parent.mkdir(parents=True, exist_ok=True)
            if OUT_SELF.is_symlink() or OUT_SELF.exists():
                pass
            else:
                OUT_SELF.symlink_to(OUT, target_is_directory=True)
        except Exception:
            OUT_SELF.mkdir(parents=True, exist_ok=True)

    clear_align_ohlc_cache()
    clear_ensure_official_volume_cache()
    empty = sorted(market_wide_empty_open_days(db, "20261001", "20261031"))
    rows = []
    for sid, mkt, name in SAMPLE:
        clear_vol_zone_render_cache()
        clear_align_ohlc_cache()
        work = official_work(load_official_ohlc(sid, db, 60))
        last6 = []
        if work is not None and not work.empty:
            tail = work.tail(6)
            last6 = [
                {
                    "date": str(r.date),
                    "volume": float(r.volume or 0),
                    "halt": bool(getattr(r, "is_halt", False)),
                    "invent": bool(getattr(r, "no_trade_fill", False)),
                }
                for r in tail.itertuples()
            ]
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
        dest = OUT / f"header-bar-fix-{sid}-{mkt}-volzone.jpg"
        dest_png = OUT / f"header-bar-fix-{sid}-{mkt}-volzone.png"
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
            # 另存 PNG（話筒對質用 jpg；docs 要 png）
            if path and Path(path).is_file():
                from PIL import Image

                Image.open(path).save(dest_png, format="PNG", optimize=True)
                if OUT_SELF.exists() and OUT_SELF.resolve() != OUT.resolve():
                    for src, name2 in ((dest, dest.name), (dest_png, dest_png.name)):
                        if src.is_file():
                            (OUT_SELF / name2).write_bytes(src.read_bytes())
        except Exception as e:
            err = str(e)
        finally:
            Figure.savefig = orig  # type: ignore
        joined = "\n".join(texts)
        has_ohlc = ("824" in joined or "開" in joined) and (
            any(x in joined for x in ("812", "146", "395", "高", "低"))
        )
        # 墨線拆字：開／高／低與數字分開 Text
        vis_nums = [t for t in texts if t.replace(",", "").replace(".", "").isdigit() or (
            t.replace(",", "").replace(".", "").replace("-", "").isdigit()
        )]
        has_open_high = any(t in texts for t in ("開", "高", "低")) and len(vis_nums) >= 3
        has_move = ("▲" in joined or "▼" in joined) and "%" in joined
        invent_in_last6 = any(x.get("invent") for x in last6)
        rows.append(
            {
                "sid": sid,
                "mkt": mkt,
                "path_jpg": str(path or dest),
                "path_png": str(dest_png),
                "ok": bool(path) and Path(path or "").is_file() and not err,
                "has_open_high_labels": has_open_high,
                "has_move": bool(has_move),
                "last6": last6,
                "invent_in_last6": invent_in_last6,
                "err": err,
                "sample_texts": [
                    t
                    for t in texts
                    if any(k in t for k in ("收", "開", "高", "低", "▲", "▼", "824", "812", "395"))
                ][:20],
            }
        )
        print(json.dumps(rows[-1], ensure_ascii=False))
    meta = {
        "market_wide_empty_oct": empty,
        "samples": rows,
    }
    (OUT / "summary.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    if OUT_SELF.exists() and OUT_SELF.resolve() != OUT.resolve():
        (OUT_SELF / "summary.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    bad = [
        r
        for r in rows
        if (not r["ok"]) or r["invent_in_last6"] or (r["sid"] == "3595" and not r["has_open_high_labels"])
    ]
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
