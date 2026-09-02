#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""匯出高低決策卡 PNG + 文字列，供與 CaryBot／本機截圖對照（不走 Telegram）。

用法：
  python scripts/export_compare_card.py 建準
  python scripts/export_compare_card.py 2421 2330 1303
  python scripts/export_compare_card.py 2421 --out data/compare

產出（每檔）：
  <out>/<代號>_card.png      高低決策卡圖
  <out>/<代號>_rows.tsv      最近 20 列欄位（日期、股價、獲利…）
  <out>/<代號>_meta.txt      摘要（名稱、收盤、MA60S、量排名等）
"""
from __future__ import annotations

import argparse
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from config import get_db_path
from wayne_db import lookup_stocks
from wayne_navigator import NavigatorEngine, prewarm_card_fonts, render_decision_card_png

_COMPARE_COLS = ("date", "close", "獲利", "高低", "預警", "溫度計", "升降", "月乖離", "120日量")


def _resolve(query: str, db_path: str) -> tuple[str, str]:
    q = (query or "").strip()
    hits = lookup_stocks(db_path, q, limit=3)
    if not hits:
        raise SystemExit(f"找不到：{q}")
    if len(hits) > 1:
        lines = [f"  {h['stock_id']} {h.get('stock_name')}" for h in hits]
        raise SystemExit(f"「{q}」對到多檔，請改打代號：\n" + "\n".join(lines))
    sid = str(hits[0]["stock_id"])
    name = str(hits[0].get("stock_name") or sid)
    return sid, name


def export_one(code: str, db_path: str, out_dir: str, lookback: int = 20) -> dict:
    sid, name = _resolve(code, db_path)
    engine = NavigatorEngine(db_path)
    card = engine.get_decision_card(sid, lookback=lookback, merge_live=False)
    if card.get("error"):
        raise SystemExit(f"{sid} {name}: {card['error']}")

    os.makedirs(out_dir, exist_ok=True)
    png_path = os.path.join(out_dir, f"{sid}_card.png")
    tsv_path = os.path.join(out_dir, f"{sid}_rows.tsv")
    meta_path = os.path.join(out_dir, f"{sid}_meta.txt")

    render_decision_card_png(card, png_path)
    table = card.get("table")
    if table is not None and not getattr(table, "empty", True):
        cols = [c for c in _COMPARE_COLS if c in table.columns]
        with open(tsv_path, "w", encoding="utf-8") as f:
            f.write("\t".join(cols) + "\n")
            for _, row in table[cols].iterrows():
                f.write("\t".join(str(row[c]) for c in cols) + "\n")
    else:
        tsv_path = ""

    meta_lines = [
        f"stock_id={sid}",
        f"stock_name={name}",
        f"latest_date={card.get('latest_date')}",
        f"close={card.get('close')}",
        f"gain_pct={card.get('gain_pct')}",
        f"cal60_low={card.get('cal60_low')}",
        f"ma60s={card.get('ma60s')}",
        f"vol_rank={card.get('vol_rank')}",
        f"vol_rank_480={card.get('vol_rank_480')}",
        f"badges={','.join(card.get('badges') or [])}",
    ]
    with open(meta_path, "w", encoding="utf-8") as f:
        f.write("\n".join(meta_lines) + "\n")

    return {"code": sid, "name": name, "png": png_path, "tsv": tsv_path, "meta": meta_path}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="匯出高低卡供與 CaryBot 對照")
    parser.add_argument("queries", nargs="+", help="代號或股名，如 建準 2421")
    parser.add_argument("--out", default=os.path.join("data", "compare"), help="輸出目錄")
    parser.add_argument("--lookback", type=int, default=20)
    args = parser.parse_args(argv)

    db_path = get_db_path()
    prewarm_card_fonts()
    results = []
    for q in args.queries:
        hit = export_one(q, db_path, args.out, lookback=args.lookback)
        results.append(hit)
        print(f"✓ {hit['code']} {hit['name']}")
        print(f"  圖　{hit['png']}")
        if hit["tsv"]:
            print(f"  列　{hit['tsv']}")
        print(f"  摘要 {hit['meta']}")
    print(f"\n共 {len(results)} 檔 → {os.path.abspath(args.out)}")
    print("請把你的 CaryBot 截圖與上述 PNG／TSV 並排對照；不必經 Telegram。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
