#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SYNC-FWD CLI：eod miss → observe_manual 下一版鍵／證據桶回寫。

用法：
  python3 scripts/observe_sync_fwd_writeback.py --write
  python3 scripts/observe_sync_fwd_writeback.py --write --patch-forward
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import observe_sync_fwd as sf  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="SYNC-FWD miss writeback")
    ap.add_argument("--write", action="store_true", help="寫入 observe_manual 檔")
    ap.add_argument(
        "--patch-forward",
        action="store_true",
        help="把敘述修正建議掛進 wave_forward_infer_latest／當令 dated",
    )
    ap.add_argument("--dry-run", action="store_true", help="只印摘要不寫檔")
    args = ap.parse_args()
    write = bool(args.write) and not args.dry_run
    payload = sf.apply_writeback(write=write)
    print(
        "GATE",
        f"sync_fwd actionable={payload.get('n_actionable')}/{payload.get('n_eod_miss')} "
        f"cards+={payload.get('cards_added')} ev+={payload.get('evidence_samples_added')} "
        f"next={((payload.get('next_variant') or {}).get('variant'))} "
        f"phone_sync=blocked buy_signal=0",
    )
    latest = payload.get("latest_actionable") or {}
    print(
        "LATEST",
        latest.get("as_of"),
        latest.get("kind"),
        latest.get("prefer_path_id"),
        (latest.get("code_fix_zh") or "")[:120],
    )
    if args.patch_forward and write:
        lab = sf.LAB
        for name in ("wave_forward_infer_latest.json",):
            path = lab / name
            if not path.is_file():
                continue
            fwd = json.loads(path.read_text(encoding="utf-8"))
            patched = sf.propose_forward_narrative_patch(fwd, writeback=payload)
            path.write_text(
                json.dumps(patched, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            infer_for = patched.get("infer_for")
            if infer_for:
                dated = lab / f"wave_forward_infer_{infer_for}.json"
                if dated.is_file():
                    dated.write_text(
                        json.dumps(patched, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8",
                    )
            print("PATCH_FORWARD", path.name, "prefer", (payload.get("narrative_fix") or {}).get("prefer_path_id"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
