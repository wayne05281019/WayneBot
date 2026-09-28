# -*- coding: utf-8 -*-
"""多檔出圖兩段式：平行 prepare → 串行 paint（mpl 鎖）。

壓撐名單、之後海選若加多檔預覽，都走這條。不准每檔在鎖內重抓 DB／重對齊。
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger("WayneBot.ChartBatch")


def prepare_volume_zones_parallel(
    jobs: Sequence[Tuple[str, str, str]],
    db_path: str,
    *,
    max_workers: int = 8,
) -> List[Optional[Dict[str, Any]]]:
    """jobs＝(code, name, save_path)。回傳與 jobs 同序的 prepare pack（失敗＝None）。"""
    from vol_zone_chart import prepare_volume_zone

    if not jobs:
        return []
    out: List[Optional[Dict[str, Any]]] = [None] * len(jobs)

    def _one(idx: int, code: str, name: str, path: str):
        try:
            return idx, prepare_volume_zone(code, name, db_path, path)
        except Exception:
            logger.exception("prepare_volume_zone fail code=%s", code)
            return idx, None

    workers = max(1, min(int(max_workers or 1), len(jobs)))
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = [
            ex.submit(_one, i, c, n, p) for i, (c, n, p) in enumerate(jobs)
        ]
        for fut in as_completed(futs):
            idx, pack = fut.result()
            out[idx] = pack
    return out


def paint_volume_zones_serial(
    packs: Sequence[Optional[Dict[str, Any]]],
    *,
    with_nav_signals: bool = True,
    db_path: str = "",
    card: Optional[Dict[str, Any]] = None,
) -> List[Tuple[str, str]]:
    """在單一執行緒串行 paint（mpl_render 鎖）。回傳 (path, caption)。"""
    from vol_zone_chart import (
        VOL_ZONE_BARS,
        VOL_ZONE_LOOKBACK,
        _paint_volume_zone,
        _vz_memo_key,
        _vz_memo_put,
        vol_zone_photo_caption,
    )
    from wayne_navigator import mpl_render

    outs: List[Tuple[str, str]] = []
    for pack in packs:
        if not pack:
            outs.append(("", ""))
            continue
        try:
            cap = vol_zone_photo_caption(
                pack["sid"],
                str(db_path or ""),
                card,
                zone=pack["zone"],
                last=pack["last"],
                bars=pack["bars"],
                ex_events=pack["ex_events"],
            )
            with mpl_render():
                path = _paint_volume_zone(
                    pack["sid"],
                    pack["name"],
                    pack["view"],
                    pack["zone"],
                    pack["spike_i"],
                    pack["spike_date"],
                    pack["hi"],
                    pack["lo"],
                    pack["halt"],
                    pack["xs"],
                    pack["n"],
                    pack["ex_events"],
                    pack["out"],
                    with_nav_signals=with_nav_signals,
                    card=card,
                )
            path_s, cap_s = str(path or ""), str(cap or "")
            if path_s and not card:
                _vz_memo_put(
                    _vz_memo_key(
                        pack["sid"],
                        pack["zone"],
                        pack["last"],
                        with_nav_signals=with_nav_signals,
                        lookback=VOL_ZONE_LOOKBACK,
                        bars=VOL_ZONE_BARS,
                    ),
                    path_s,
                    cap_s,
                )
            outs.append((path_s, cap_s))
        except Exception:
            logger.exception("paint_volume_zone fail sid=%s", pack.get("sid"))
            outs.append(("", ""))
    return outs


def render_volume_zones_two_phase(
    jobs: Sequence[Tuple[str, str, str]],
    db_path: str,
    *,
    with_nav_signals: bool = True,
    max_workers: int = 8,
) -> List[Tuple[str, str]]:
    """多檔壓力區／大量區：prepare∥ → paint 串行。"""
    packs = prepare_volume_zones_parallel(jobs, db_path, max_workers=max_workers)
    return paint_volume_zones_serial(
        packs, with_nav_signals=with_nav_signals, db_path=db_path, card=None
    )


def prepare_nav_charts_parallel(
    jobs: Sequence[Tuple[str, str, str]],
    db_path: str,
    *,
    max_workers: int = 4,
) -> List[Tuple[str, str, Any]]:
    """jobs＝(code, name, save_path)。回傳 (code, name, df_or_None) 供後續串行 generate。"""
    from wayne_navigator import _load_ohlc

    if not jobs:
        return []
    out: List[Tuple[str, str, Any]] = [("", "", None)] * len(jobs)

    def _one(idx: int, code: str, name: str, _path: str):
        try:
            df = _load_ohlc(code, db_path, 180)
            return idx, code, name, df
        except Exception:
            logger.exception("nav load fail code=%s", code)
            return idx, code, name, None

    workers = max(1, min(int(max_workers or 1), len(jobs)))
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = [ex.submit(_one, i, c, n, p) for i, (c, n, p) in enumerate(jobs)]
        for fut in as_completed(futs):
            idx, code, name, df = fut.result()
            out[idx] = (code, name, df)
    return out


def paint_nav_charts_serial(
    prepared: Sequence[Tuple[str, str, Any]],
    save_paths: Sequence[str],
) -> List[str]:
    """串行 generate_chart（已載入 df，走對齊快取＋渲圖 memo）。"""
    from wayne_navigator import generate_chart

    outs: List[str] = []
    for (code, name, df), path in zip(prepared, save_paths):
        if df is None or getattr(df, "empty", True):
            outs.append("")
            continue
        try:
            outs.append(
                generate_chart(code, name, None, path, df, already_normalized=False)
                or ""
            )
        except Exception:
            logger.exception("nav paint fail code=%s", code)
            outs.append("")
    return outs
