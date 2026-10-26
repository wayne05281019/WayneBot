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


def _install_hits_overlay_savefig(hits_stem: Path):
    """after 存檔時：先寫淨圖，再疊紅框／命中 K 另存 *-hits.png。"""
    from matplotlib.figure import Figure

    from vol_zone_chart import (
        _channel_artist_pixel_hits,
        draw_channel_label_hits_overlay,
    )

    real = Figure.savefig
    reports: list = []

    def _sf(self, fname, *a, **k):
        out = real(self, fname, *a, **k)
        for ax in self.axes:
            arts = getattr(ax, "_wayne_channel_label_artists", None)
            ohlc = getattr(ax, "_wayne_channel_label_ohlc", None)
            if not arts or not ohlc:
                continue
            hi, lo, n = ohlc
            self.canvas.draw()
            ren = self.canvas.get_renderer()
            for art in arts:
                hits, _bb = _channel_artist_pixel_hits(
                    ax, art, n=int(n), highs=hi, lows=lo, renderer=ren
                )
                try:
                    txt = str(art.get_text() or "")
                except Exception:
                    txt = ""
                reports.append({"text": txt, "k_hits": len(hits), "bars": hits})
                print(
                    f"pixel-hits {hits_stem.name}: {txt!r} k_hits={len(hits)} bars={hits}"
                )
            draw_channel_label_hits_overlay(
                ax,
                n=int(n),
                highs=hi,
                lows=lo,
                label_artists=arts,
                renderer=ren,
            )
            hits_path = Path(str(hits_stem) + "-hits.png")
            try:
                real(self, str(hits_path), dpi=int(k.get("dpi") or 120), format="png")
            except TypeError:
                real(self, str(hits_path), format="png")
            except OSError as exc:
                print("hits-overlay-skip", hits_path, exc)
            else:
                print("hits-overlay", hits_path, "bytes", hits_path.stat().st_size)
                hits_path.with_suffix(".txt").write_text(
                    "\n".join(
                        f"{r['text']}\tk_hits={r['k_hits']}\tbars={r['bars']}"
                        for r in reports
                    )
                    + "\n",
                    encoding="utf-8",
                )
            break
        return out

    Figure.savefig = _sf

    def _restore() -> None:
        Figure.savefig = real

    return _restore


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
        restore = None
        if tag == "after":
            restore = _install_hits_overlay_savefig(
                out_dir / f"{sid}-structure-{tag}"
            )
        try:
            path, cap = render_lookup_structure_result(
                sid, name, db, str(sp), card=None
            )
        finally:
            if restore:
                restore()
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
    restore = None
    if tag == "after":
        # overlay 檔名用簡名 stem（交審會改名）
        restore = _install_hits_overlay_savefig(
            out_dir / f"{sid}-volzone-{tag}"
        )
    try:
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
    finally:
        if restore:
            restore()
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
    ap.add_argument(
        "--before-from",
        type=Path,
        default=None,
        help="未修標籤底圖目錄（review-*）：複製為 before，避免 3081 NO_RECLASS 前後同檔假對照",
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
    if args.before_from:
        meta_lines.append(f"before_from={args.before_from.resolve()}")

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

    def _copy_before_from(src_dir: Path) -> None:
        """把舊審 after（未修標籤臉）拷成本輪 before；結構／大量區 png+jpg+caption。"""
        from PIL import Image

        src_dir = src_dir.resolve()
        if not src_dir.is_dir():
            raise SystemExit(f"before-from missing: {src_dir}")
        for sid in sids:
            pairs = [
                (f"{sid}-structure-after", f"{sid}-structure-before-{stamp}"),
                (f"{sid}-volzone-after", f"{sid}-volzone-before-fullwidth-{stamp}"),
            ]
            if args.vol_only:
                pairs = [pairs[1]]
            for src_stem, dst_stem in pairs:
                src_png = src_dir / f"{src_stem}.png"
                src_jpg = src_dir / f"{src_stem}.jpg"
                if not src_png.is_file() and not src_jpg.is_file():
                    raise SystemExit(f"before-from lack {src_stem} in {src_dir}")
                dst_png = out_dir / f"{dst_stem}.png"
                dst_jpg = out_dir / f"{dst_stem}.jpg"
                if src_png.is_file():
                    shutil.copy2(src_png, dst_png)
                elif src_jpg.is_file():
                    Image.open(src_jpg).convert("RGB").save(
                        dst_png, format="PNG", optimize=True
                    )
                if src_jpg.is_file():
                    shutil.copy2(src_jpg, dst_jpg)
                else:
                    Image.open(dst_png).convert("RGB").save(
                        dst_jpg, quality=92, optimize=True
                    )
                print("before-from", dst_png, "bytes", dst_png.stat().st_size)

    if args.before_from is not None and args.phase in ("before", "both"):
        _copy_before_from(args.before_from)
    elif args.phase in ("before", "both"):
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
