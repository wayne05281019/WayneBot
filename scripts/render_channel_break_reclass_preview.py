#!/usr/bin/env python3
"""WB-28 本機試渲：破上升軌→升通道失效／改判下降（before／after）。

結構第 3 張＋大量區第 4 張。新檔名含台北時戳＋tip sha，不准覆寫。
before＝WAYNE_CHANNEL_NO_RECLASS=1（舊臉：破了仍畫上翹升通道）。
不准搶正式 TELEGRAM_BOT_TOKEN；WAYNE_SKIP_POLLING=1。
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("MPLBACKEND", "Agg")
os.environ.setdefault("WAYNE_SKIP_POLLING", "1")

_TAIPEI = ZoneInfo("Asia/Taipei")
_DEFAULT_OUT = Path(
    "/cursor/stores/bc-01a0d9ba-b7e3-7f56-802d-4c6e57f8ad9e/media/channel-break-20261025"
)


def _db() -> str:
    from config import get_db_path

    p = Path(get_db_path())
    if not p.is_file():
        raise SystemExit(f"missing db: {p}")
    return str(p.resolve())


def _tip_sha() -> str:
    try:
        return (
            subprocess.check_output(
                ["git", "rev-parse", "--short=8", "HEAD"],
                cwd=str(ROOT),
                stderr=subprocess.DEVNULL,
                text=True,
            ).strip()
            or "nosha"
        )
    except Exception:
        return "nosha"


def _stamp() -> str:
    now = datetime.now(_TAIPEI).strftime("%Y%m%d-%H%M%S")
    return f"{now}-{_tip_sha()}"


def _unique(out_dir: Path, stem: str, *, suffix: str = ".png") -> Path:
    base = out_dir / f"{stem}{suffix}"
    if not base.exists():
        return base
    for i in range(2, 100):
        cand = out_dir / f"{stem}-r{i}{suffix}"
        if not cand.exists():
            return cand
    return out_dir / f"{stem}-{_stamp()}{suffix}"


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


def _render_one(
    sid: str,
    name: str,
    db: str,
    out_dir: Path,
    tag: str,
    stamp: str,
    *,
    structure: bool = True,
) -> None:
    from three_in_one_chart import render_lookup_structure_result
    from vol_zone_chart import render_volume_zone_result

    if structure:
        sp = _unique(out_dir, f"{sid}-structure-{tag}-{stamp}")
        path, cap = render_lookup_structure_result(sid, name, db, str(sp), card=None)
        if not path or not Path(path).is_file():
            raise SystemExit(f"structure fail {sid} {tag}")
        if Path(path).resolve() != sp.resolve():
            shutil.copy2(path, sp)
        (out_dir / f"{sid}-structure-{tag}-{stamp}.caption.txt").write_text(
            str(cap or ""), encoding="utf-8"
        )
        print("structure", sp, "bytes", sp.stat().st_size)

    # 檔名帶 fullwidth：滿版底＋軌道智能標（不准 0.72 黑邊）
    vp = _unique(out_dir, f"{sid}-volzone-{tag}-fullwidth-{stamp}")
    tmp = vp.with_suffix(".jpg")
    path, cap = render_volume_zone_result(
        sid,
        name,
        db,
        str(tmp),
        with_nav_signals=True,
        lookup_portrait=False,
        with_ma5_ma10=True,
        with_parallel_channel=True,
    )
    if not path or not Path(path).is_file():
        raise SystemExit(f"volzone fail {sid} {tag}")
    src = Path(path)
    if vp.suffix.lower() == ".png" and src.suffix.lower() in {".jpg", ".jpeg"}:
        from PIL import Image

        Image.open(src).convert("RGB").save(vp, format="PNG", optimize=True)
    elif src.resolve() != vp.resolve():
        shutil.copy2(src, vp)
    (out_dir / f"{sid}-volzone-{tag}-fullwidth-{stamp}.caption.txt").write_text(
        str(cap or ""), encoding="utf-8"
    )
    print("volzone", vp, "bytes", vp.stat().st_size)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sids", default="2454,3081")
    ap.add_argument("--out", type=Path, default=_DEFAULT_OUT)
    ap.add_argument("--phase", choices=("before", "after", "both"), default="both")
    ap.add_argument(
        "--vol-only",
        action="store_true",
        help="只渲大量區滿版（跳過結構）",
    )
    args = ap.parse_args()
    db = _db()
    out_dir = args.out
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = _stamp()
    sids = [s.strip() for s in str(args.sids).split(",") if s.strip()]
    meta_lines = [
        f"stamp={stamp}",
        f"db={db}",
        f"phase={args.phase}",
        "volzone=fullwidth+smart-channel-labels",
        "VOL_ZONE_TAG_PT=14(main-role-large)",
        "LAYER_TAG_PT=8.5(next-layer-small)",
    ]

    def _clear_caches() -> None:
        try:
            from vol_zone_chart import clear_vol_zone_render_cache

            clear_vol_zone_render_cache()
        except Exception:
            pass
        try:
            from wayne_navigator import clear_lookup_render_cache

            clear_lookup_render_cache()
        except Exception:
            pass

    if args.phase in ("before", "both"):
        os.environ["WAYNE_CHANNEL_NO_RECLASS"] = "1"
        _clear_caches()
        for sid in sids:
            _render_one(
                sid,
                _name(sid, db),
                db,
                out_dir,
                "before",
                stamp,
                structure=not args.vol_only,
            )

    if args.phase in ("after", "both"):
        os.environ.pop("WAYNE_CHANNEL_NO_RECLASS", None)
        _clear_caches()
        for sid in sids:
            _render_one(
                sid,
                _name(sid, db),
                db,
                out_dir,
                "after",
                stamp,
                structure=not args.vol_only,
            )

    from biaoke_brain import load_bars
    from biaoke_chart import _BARS, infer_parallel_channel

    os.environ.pop("WAYNE_CHANNEL_NO_RECLASS", None)
    for sid in sids:
        bars = load_bars(db, sid, n=360)
        ch = infer_parallel_channel((bars or [])[-_BARS:]) if bars else {}
        meta_lines.append(
            f"{sid}: kind={ch.get('kind')} alive={ch.get('alive')} "
            f"reclass={ch.get('reclass_from')} label={ch.get('label')}"
        )
    meta = out_dir / f"meta-{stamp}.txt"
    meta.write_text("\n".join(meta_lines) + "\n", encoding="utf-8")
    print("meta", meta)


if __name__ == "__main__":
    main()
