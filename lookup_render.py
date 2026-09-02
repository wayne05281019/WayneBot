# -*- coding: utf-8 -*-
"""查股 PNG：程序池並行產圖（避開單程序 matplotlib 鎖）。"""
from __future__ import annotations

import os
from concurrent.futures import ProcessPoolExecutor
from typing import Any, Dict, Optional, Tuple


def _worker_card(card: Dict[str, Any], save_path: str) -> str:
    from wayne_navigator import render_decision_card_png

    return render_decision_card_png(card, save_path) or ""


def _worker_glance(
    code: str,
    card: Dict[str, Any],
    tape: Dict[str, Any],
    save_path: str,
    db_path: str,
) -> str:
    from wayne_navigator import render_first_glance_png

    return render_first_glance_png(code, card, tape, save_path, db_path) or ""


def render_card_and_glance_parallel(
    card: Dict[str, Any],
    card_path: str,
    code: str,
    tape: Dict[str, Any],
    glance_path: str,
    db_path: str,
) -> Tuple[str, str]:
    """決策卡 + 介紹圖並行渲染；失敗時退回同程序串行。"""
    os.makedirs(os.path.dirname(card_path) or ".", exist_ok=True)
    os.makedirs(os.path.dirname(glance_path) or ".", exist_ok=True)
    try:
        with ProcessPoolExecutor(max_workers=2) as pool:
            fc = pool.submit(_worker_card, card, card_path)
            fg = pool.submit(_worker_glance, code, card, tape or {}, glance_path, db_path)
            return fc.result() or card_path, fg.result() or glance_path
    except Exception:
        from wayne_navigator import render_decision_card_png, render_first_glance_png

        cp = render_decision_card_png(card, card_path) or card_path
        gp = render_first_glance_png(code, card, tape or {}, glance_path, db_path) or glance_path
        return cp, gp
