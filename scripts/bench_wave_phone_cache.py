#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""波浪位階加速前後對照（本機・不搶 getUpdates）。

量測：
1) teach_kit_reusable（磁碟／記憶命中）
2) 若有 production DB：流水線冷／暖（同 tip 記憶）

結果寫 stdout＋可選 --out。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _png(path: Path, n: int = 9000) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x89PNG\r\n" + b"0" * n)
    return str(path)


def bench_kit_reuse() -> dict:
    from biaoke_level_learn import (
        clear_wave_phone_caches,
        remember_wave_kit_paths,
        teach_kit_reusable_for_phone,
    )

    clear_wave_phone_caches()
    tip = {
        "tw_asof": "20261121",
        "tw_close": 28000.0,
        "tw_live": 0,
        "sox_asof": "20261121",
        "sox_close": 5000.0,
        "sox_live": 0,
        "tx_asof": "20261121",
        "tx_close": 28000.0,
        "tx_live": 0,
    }
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        far = _png(base / "far.png")
        near = _png(base / "near.png")
        micro = _png(base / "micro.png")
        stored = {
            "far_path": far,
            "near_path": near,
            "micro_path": micro,
            "thesis": "bench",
            "as_of": "20261121",
            "teach_tip": tip,
        }
        db = str(base / "x.db")
        # 模擬「加速前」：每次都當要重渲（只量 helper 對照＋標記）
        cold_samples = []
        for _ in range(5):
            clear_wave_phone_caches()
            t0 = time.perf_counter()
            # 加速前語意：tip 對不上就不 reuse（強制 miss）→ 呼叫端會活畫
            miss = teach_kit_reusable_for_phone(
                {**stored, "teach_tip": {**tip, "tw_close": tip["tw_close"] + 99}},
                tip,
                db_path=db,
            )
            cold_samples.append(time.perf_counter() - t0)
            assert miss["ok"] is False
        # 加速後：disk → mem
        clear_wave_phone_caches()
        t0 = time.perf_counter()
        disk = teach_kit_reusable_for_phone(stored, tip, db_path=db)
        disk_s = time.perf_counter() - t0
        assert disk["ok"] and disk["reason"] == "disk_hit"
        mem_samples = []
        for _ in range(20):
            t0 = time.perf_counter()
            mem = teach_kit_reusable_for_phone({}, tip, db_path=db)
            mem_samples.append(time.perf_counter() - t0)
            assert mem["ok"] and mem["reason"] == "mem_hit"
        remember_wave_kit_paths(
            db,
            {
                "far_path": far,
                "near_path": near,
                "micro_path": micro,
                "teach_tip": tip,
            },
            tip=tip,
        )
        return {
            "kit_miss_median_ms": round(
                sorted(cold_samples)[len(cold_samples) // 2] * 1000, 3
            ),
            "kit_disk_hit_ms": round(disk_s * 1000, 3),
            "kit_mem_hit_median_ms": round(
                sorted(mem_samples)[len(mem_samples) // 2] * 1000, 3
            ),
            "note": "miss＝加速前必走活畫；disk/mem＝加速後跳過三窗重渲",
        }


def bench_pipeline(db_path: str) -> dict:
    from biaoke_level_learn import (
        clear_wave_phone_caches,
        run_teach_trio_preflight_pipeline,
    )

    if not db_path or not os.path.isfile(db_path):
        return {"skipped": "no_db"}
    clear_wave_phone_caches()
    t0 = time.perf_counter()
    cold = run_teach_trio_preflight_pipeline(db_path)
    cold_s = time.perf_counter() - t0
    t0 = time.perf_counter()
    warm = run_teach_trio_preflight_pipeline(db_path)
    warm_s = time.perf_counter() - t0
    return {
        "pipe_cold_s": round(cold_s, 3),
        "pipe_warm_s": round(warm_s, 3),
        "pipe_cold_ok": bool((cold or {}).get("ok")),
        "pipe_warm_ok": bool((warm or {}).get("ok")),
        "pipe_warm_from_cache": bool((warm or {}).get("from_cache")),
        "speedup_x": (
            round(cold_s / warm_s, 2) if warm_s > 0 else None
        ),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=os.environ.get("WAYNE_DB", ""))
    ap.add_argument("--out", default="")
    args = ap.parse_args()
    if not args.db:
        try:
            from config import get_db_path

            args.db = get_db_path()
        except Exception:
            args.db = str(ROOT / "data" / "wayne_market.db")
    out = {
        "kit": bench_kit_reuse(),
        "pipeline": bench_pipeline(args.db),
    }
    text = json.dumps(out, ensure_ascii=False, indent=2)
    print(text)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(text + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
