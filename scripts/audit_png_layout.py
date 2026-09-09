# -*- coding: utf-8 -*-
"""本機渲出所有對外 PNG，供目視壓字／左擠右空。不碰 Telegram。"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("MPLBACKEND", "Agg")
os.environ.setdefault("WAYNE_SKIP_POLLING", "1")

OUT = Path(os.environ.get("WAYNE_PNG_AUDIT_DIR") or "/opt/cursor/artifacts/png-audit")
CODES = ["2330", "2383", "4915", "2454"]


def _db() -> str:
    from config import get_db_path

    return get_db_path()


def _ok(path: str) -> bool:
    try:
        return os.path.isfile(path) and os.path.getsize(path) > 8000
    except OSError:
        return False


def render_all(out_dir: Path | None = None) -> dict:
    out_dir = Path(out_dir or OUT)
    out_dir.mkdir(parents=True, exist_ok=True)
    db = _db()
    from wayne_navigator import NavigatorEngine, generate_chart, render_decision_card_png, render_first_glance_png
    from chip_tape import build_tape
    from chips import generate_chips_image
    from industry_card import render_industry_png
    from index_kline_chart import build_market_kline_chart
    from picture_guide import PAGE_SLUGS, ensure_page

    eng = NavigatorEngine(db)
    done = {}

    for code in CODES:
        card = eng.get_decision_card(code, merge_live=False)
        if not card or card.get("error"):
            done[f"{code}.skip"] = str((card or {}).get("error") or "no card")
            continue
        tape = build_tape(db, code, card) or {}
        p_card = str(out_dir / f"{code}_card.png")
        p_glance = str(out_dir / f"{code}_glance.png")
        p_nav = str(out_dir / f"{code}_nav.png")
        p_ind = str(out_dir / f"{code}_industry.png")
        p_chips = str(out_dir / f"{code}_chips.png")
        done[f"{code}.card"] = render_decision_card_png(card, p_card)
        done[f"{code}.glance"] = render_first_glance_png(code, card, tape, p_glance, db)
        try:
            done[f"{code}.nav"] = generate_chart(code, db_path=db, save_path=p_nav) or p_nav
        except Exception as e:
            done[f"{code}.nav"] = f"err:{e}"
        try:
            done[f"{code}.industry"] = render_industry_png(code, db, p_ind, allow_fetch=False)
        except Exception as e:
            done[f"{code}.industry"] = f"err:{e}"
        try:
            done[f"{code}.chips"] = generate_chips_image(code, db, p_chips) or "no-rows"
        except Exception as e:
            done[f"{code}.chips"] = f"err:{e}"

    try:
        done["index.kline"] = build_market_kline_chart(str(out_dir / "index_kline.png"), db_path=db) or "empty"
    except Exception as e:
        done["index.kline"] = f"err:{e}"

    guide_dir = out_dir / "guide"
    guide_dir.mkdir(exist_ok=True)
    for slug in PAGE_SLUGS:
        try:
            done[f"guide.{slug}"] = ensure_page(slug, str(guide_dir), force=True)
        except Exception as e:
            done[f"guide.{slug}"] = f"err:{e}"

    summary = {k: ("ok" if _ok(str(v)) else str(v)) for k, v in done.items()}
    return {"dir": str(out_dir), "results": summary, "raw": {k: str(v) for k, v in done.items()}}


if __name__ == "__main__":
    import json

    info = render_all()
    print(json.dumps(info["results"], ensure_ascii=False, indent=2))
    print("dir", info["dir"])
