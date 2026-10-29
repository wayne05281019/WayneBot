#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v2e 十檔大量區抽樣＋smart_label 閘。臉鎖 v2e；平行軌標不准蓋縮圖 K。"""
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
    "media/volzone-v2e-ten-sample-20261029"
)

# 上市4／上櫃3／興櫃3
SAMPLE = [
    ("2383", "listed", "台光電"),
    ("2330", "listed", "台積電"),
    ("1303", "listed", "南亞"),
    ("2454", "listed", "聯發科"),
    ("3081", "otc", "聯亞"),
    ("6274", "otc", "台燿"),
    ("4966", "otc", "譜瑞-KY"),
    ("3595", "emerging", "山太士"),
    ("7853", "emerging", "政美應用"),
    ("2758", "emerging", "路易莎咖啡"),
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


def _to_png(src: Path, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if src.suffix.lower() in {".jpg", ".jpeg"} and dest.suffix.lower() == ".png":
        from PIL import Image

        Image.open(src).convert("RGB").save(dest, format="PNG", optimize=True)
    elif src.resolve() != dest.resolve():
        shutil.copy2(src, dest)
    return dest


def _required_ok(texts: list[str]) -> dict:
    """必要標齊：主壓／撐；平行軌若有線則要名＋價。"""
    joined = "\n".join(texts)
    has_press = any("大量區壓" in t for t in texts)
    has_hold = any("大量區撐" in t for t in texts)
    rail_names = [
        t
        for t in texts
        if any(
            k in t
            for k in ("下降壓", "平行撐", "平行壓", "上升軌", "上昇軌")
        )
    ]
    # 價：含數字
    import re

    rail_with_price = [
        t for t in rail_names if re.search(r"\d", t.replace(",", ""))
    ]
    return {
        "press": has_press,
        "hold": has_hold,
        "rail_labels": len(rail_names),
        "rail_with_price": len(rail_with_price),
        "required_main": has_press and has_hold,
    }


def _load_score_figure():
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "audit_smart_label_placement",
        ROOT / "scripts" / "audit_smart_label_placement.py",
    )
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod._score_figure


def _render_score(sid: str, name: str, db: str, dest: Path) -> dict:
    import matplotlib.pyplot as plt
    from matplotlib.figure import Figure

    _score_figure = _load_score_figure()
    from vol_zone_chart import clear_vol_zone_render_cache, render_volume_zone_result

    clear_vol_zone_render_cache()
    scores = []
    texts_cap: list[str] = []
    orig = Figure.savefig

    def hook(self, *a, **k):
        try:
            for ax in self.axes:
                for t in ax.texts:
                    if t.get_visible():
                        texts_cap.append(str(t.get_text() or ""))
            scores.append(_score_figure(sid, "volzone", self))
        except Exception as e:
            scores.append(e)
        return orig(self, *a, **k)

    Figure.savefig = hook  # type: ignore
    tmp = dest.with_suffix(".jpg")
    err = None
    path = None
    try:
        path, _ = render_volume_zone_result(
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
        return {
            "sid": sid,
            "name": name,
            "render_ok": False,
            "error": err or "empty",
        }
    png = _to_png(Path(path), dest)
    sc = None
    if scores and not isinstance(scores[0], Exception):
        sc = scores[0]
    req = _required_ok(texts_cap)
    # 通道標：若圖上有平行線文案才要求價；無通道則 rail=0 可過
    channel_ok = True
    if req["rail_labels"] > 0:
        channel_ok = req["rail_with_price"] >= min(2, req["rail_labels"])
    elif any("平行" in t or "下降壓" in t or "上升軌" in t for t in texts_cap):
        channel_ok = False

    out = {
        "sid": sid,
        "name": name,
        "path": str(png),
        "render_ok": True,
        "size": png.stat().st_size,
        "required": req,
        "channel_labels_ok": channel_ok,
        "functional_pass": bool(getattr(sc, "functional_pass", False)) if sc else False,
        "aesthetic_pass": bool(getattr(sc, "aesthetic_pass", False)) if sc else False,
        "pass_gate": bool(getattr(sc, "pass_gate", False)) if sc else False,
        "k_hit_bars": int(getattr(sc, "k_hit_bars", -1)) if sc else -1,
        "label_overlaps": int(getattr(sc, "label_overlaps", -1)) if sc else -1,
        "fail_reasons": list(getattr(sc, "fail_reasons", []) or []) if sc else ["no_score"],
        "aesthetic_score": float(getattr(sc, "aesthetic_score", 0) or 0) if sc else 0.0,
        "n_labels": int(getattr(sc, "n_labels", 0) or 0) if sc else 0,
        "score_error": str(scores[0]) if scores and isinstance(scores[0], Exception) else None,
    }
    # 整檔過閘＝必要主標＋功能閘＋通道價（若有）
    out["ship_ok"] = bool(
        out["render_ok"]
        and req["required_main"]
        and out["functional_pass"]
        and channel_ok
    )
    return out


def main() -> int:
    db = _db()
    OUT.mkdir(parents=True, exist_ok=True)
    rows = []
    for sid, mkt, fb in SAMPLE:
        name = _name(sid, db, fb)
        dest = OUT / f"v2e-ten-{sid}-{mkt}-volzone.png"
        print(f"== {sid} {name} ({mkt})", flush=True)
        row = _render_score(sid, name, db, dest)
        row["market"] = mkt
        rows.append(row)
        print(
            "  ship_ok={ship_ok} func={functional_pass} k_hit={k_hit_bars} "
            "overlap={label_overlaps} press/hold={required} fails={fail_reasons}".format(
                **{
                    **row,
                    "required": f"{row.get('required', {}).get('press')}/"
                    f"{row.get('required', {}).get('hold')} "
                    f"rails={row.get('required', {}).get('rail_with_price')}",
                }
            ),
            flush=True,
        )

    summary = {
        "n": len(rows),
        "ship_ok_n": sum(1 for r in rows if r.get("ship_ok")),
        "all_ship_ok": all(r.get("ship_ok") for r in rows),
        "rows": rows,
    }
    (OUT / "score-summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        f"SUMMARY ship_ok {summary['ship_ok_n']}/{summary['n']} "
        f"all={summary['all_ship_ok']}"
    )
    return 0 if summary["all_ship_ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
