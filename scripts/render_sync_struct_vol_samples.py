# -*- coding: utf-8 -*-
"""本機渲 SYNC-STRUCT-VOL 樣張到 /opt/cursor/artifacts（非買訊）。

用法：
  WAYNE_SKIP_POLLING=1 WAYNE_STRUCT_VOL_NOTES=1 \\
    python3 scripts/render_sync_struct_vol_samples.py [sid]
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

ART = Path(os.environ.get("WAYNE_ARTIFACT_DIR") or "/opt/cursor/artifacts")
ART.mkdir(parents=True, exist_ok=True)


def main() -> int:
    os.environ.setdefault("WAYNE_SKIP_POLLING", "1")
    os.environ["WAYNE_STRUCT_VOL_NOTES"] = "1"
    os.environ.setdefault("MPLBACKEND", "Agg")

    from config import get_db_path

    sid = (sys.argv[1] if len(sys.argv) > 1 else "2330").strip() or "2330"
    name = (sys.argv[2] if len(sys.argv) > 2 else "台積電").strip() or sid
    db = get_db_path()
    # 示範：有他點名位才疊（樣張用假他位＝試標標鍋；真實路徑只餵真點名）
    card = {
        "stock_id": sid,
        "struct_vol_notes": True,
        "his_named_levels": [
            {"price": 0, "label": "占位"},  # 無效略過
        ],
    }
    # 用該檔近窗低當「他點名」示範位（標試標；不是真原文）
    try:
        from vol_zone_chart import load_official_ohlc

        raw = load_official_ohlc(sid, db, 40)
        lows = []
        if raw is not None and hasattr(raw, "iloc"):
            for v in list(raw["low"].values):
                try:
                    f = float(v)
                except (TypeError, ValueError):
                    continue
                if f > 0:
                    lows.append(f)
        elif raw:
            for r in raw:
                try:
                    f = float((r or {}).get("low") or 0)
                except (TypeError, ValueError):
                    continue
                if f > 0:
                    lows.append(f)
        if lows:
            lo = min(lows)
            card["his_named_levels"] = [
                {
                    "price": round(lo, 2),
                    "label": "樣張試標低",
                    "pot": "試標推論",
                }
            ]
    except Exception:
        pass

    out_struct = ART / f"sync-struct-vol-struct-{sid}.png"
    out_vol = ART / f"sync-struct-vol-zone-{sid}.png"
    meta = {
        "sid": sid,
        "name": name,
        "db": str(db),
        "warning": "試標・推論／非他原文・非買訊・對質未過閘",
        "buy_signal": False,
        "his_named_levels": card.get("his_named_levels"),
    }

    from three_in_one_chart import render_lookup_structure_result
    from vol_zone_chart import render_lookup_vol_result

    sp, scap = render_lookup_structure_result(
        sid, name, db, str(out_struct), card=card
    )
    vp, vcap = render_lookup_vol_result(sid, name, db, str(out_vol), card=card)
    meta["structure"] = {
        "path": sp,
        "bytes": os.path.getsize(sp) if sp and os.path.isfile(sp) else 0,
        "caption": scap,
    }
    meta["vol_zone"] = {
        "path": vp,
        "bytes": os.path.getsize(vp) if vp and os.path.isfile(vp) else 0,
        "caption": vcap,
    }
    meta_path = ART / f"sync-struct-vol-meta-{sid}.json"
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(meta, ensure_ascii=False, indent=2))
    ok = bool(sp and vp and meta["structure"]["bytes"] > 20000 and meta["vol_zone"]["bytes"] > 20000)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
