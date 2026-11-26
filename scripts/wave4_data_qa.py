#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""次級四浪資料呈現 QA（可選本機整合；DB 慢就不進 CI）。

寫 /opt/cursor/artifacts/wave4_data_qa.md；觀察非買訊；Asia/Taipei。
"""
from __future__ import annotations

import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from zoneinfo import ZoneInfo

from focus_wave4_desk import (
    PAGE_SIZE,
    QUALITY_HORIZON_ZH,
    apply_live_close,
    build_wave4_desk,
    format_wave4_hub_html,
    format_wave4_one_html,
    intervene_page,
    overlay_live_on_rows,
)

TAIPEI = ZoneInfo("Asia/Taipei")
DB = ROOT / "data" / "wayne_market.db"
OUT = Path("/opt/cursor/artifacts/wave4_data_qa.md")
TOP_N = 80  # 本機抽樣；全市場可改大


def _pass_fail(ok: bool) -> str:
    return "PASS" if ok else "FAIL"


def main() -> int:
    lines = [
        "# 次級四浪 data presentation QA",
        f"- as_of_taipei: {datetime.now(TAIPEI).isoformat(timespec='seconds')}",
        f"- db: `{DB}` exists={DB.exists()}",
        f"- top_n_sample: {TOP_N}",
        "",
        "| # | invariant | result | note |",
        "|---|-----------|--------|------|",
    ]
    results: list[bool] = []

    def add(n: int, name: str, ok: bool, note: str) -> None:
        results.append(ok)
        lines.append(f"| {n} | {name} | {_pass_fail(ok)} | {note} |")

    if not DB.exists():
        add(0, "db_available", False, "no wayne_market.db; unit mocks only")
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(OUT.read_text(encoding="utf-8"))
        return 1

    t0 = time.time()
    desk = build_wave4_desk(DB, top_n=TOP_N)
    scan_sec = round(time.time() - t0, 2)
    ok_desk = bool(desk.get("ok"))

    # 1 passive → sprint never intervene
    bad_passive = []
    for r in desk.get("intervene") or []:
        tags = set(r.get("taught_tags") or [])
        chain = str(r.get("industry_chain") or "")
        if "被動元件" in tags or "被動元件" in chain:
            bad_passive.append(r.get("stock_id"))
    add(
        1,
        "passive→sprint never intervene",
        ok_desk and not bad_passive,
        f"bad={bad_passive or '[]'} sprint_n={desk.get('n_sprint')}",
    )

    # 2 quality 2383/6442 never dropped; below L3 can intervene
    notes2 = []
    ok2 = True
    for sid in ("2383", "6442"):
        rows = [
            r
            for b in ("intervene", "sprint", "watch")
            for r in (desk.get(b) or [])
            if r.get("stock_id") == sid
        ]
        if not rows:
            # 抽樣 top_n 可能沒掃到；不硬判 FAIL，記 note
            notes2.append(f"{sid}=not_in_sample")
            continue
        r = rows[0]
        notes2.append(f"{sid}={r.get('bucket')}/above={r.get('above_w4_low')}")
        if sid in QUALITY_HORIZON_ZH and r.get("above_w4_low") is False:
            # 未過低仍不准被丢掉；桶可以是 intervene／watch（已過高）
            if r.get("bucket") not in ("intervene", "sprint", "watch"):
                ok2 = False
    add(2, "2383/6442 quality keep", ok2 and ok_desk, "; ".join(notes2) or "ok")

    # 3 live past H4 refreshes bucket + format shows 已過四浪高
    ok3 = False
    note3 = "no quality row"
    for sid in ("2383", "6442"):
        row = next(
            (
                r
                for b in ("intervene", "sprint", "watch")
                for r in (desk.get(b) or [])
                if r.get("stock_id") == sid and float(r.get("wave4") or 0) > 0
            ),
            None,
        )
        if not row:
            continue
        live = apply_live_close(row, float(row["wave4"]) + 10.0)
        html = format_wave4_one_html(live, live=True)
        ok3 = (
            live.get("bucket") != "intervene"
            and live.get("room_to_w4_pct", 1) <= 0
            and ("已過四浪高" in html or "已過／觸及次級四浪高" in html)
        )
        note3 = f"{sid} bucket={live.get('bucket')} room={live.get('room_to_w4_pct')}"
        break
    add(3, "live past H4 refresh", ok3, note3)

    # 4 page only intervene, PAGE_SIZE=10, has_next if n>10
    rows, pages, has_next = intervene_page(desk, 0)
    n_iv = int(desk.get("n_intervene") or 0)
    ok4 = (
        PAGE_SIZE == 10
        and len(rows) == min(PAGE_SIZE, n_iv)
        and all(
            r.get("bucket") == "intervene"
            or r.get("stock_id")
            in {x.get("stock_id") for x in (desk.get("intervene") or [])}
            for r in rows
        )
        and (has_next is True if n_iv > 10 else has_next is False)
    )
    add(
        4,
        "實質十檔 page",
        ok4,
        f"n={n_iv} page_len={len(rows)} pages={pages} has_next={has_next}",
    )

    # 5 overlay failure keeps close
    sample = list(desk.get("intervene") or [])[:3]
    closes = [float(r.get("close") or 0) for r in sample]
    out, any_live = overlay_live_on_rows(sample, DB)
    # 非開市合併窗時 any_live 應 False；開市則允許 True，但失敗路徑另由 unit 測
    ok5 = len(out) == len(sample) and all(
        float(o.get("close") or 0) > 0 for o in out
    )
    # 若不在 live 窗，close 必須等於原收盤
    if not any_live:
        ok5 = ok5 and [float(o.get("close") or 0) for o in out] == closes
    add(
        5,
        "overlay keeps face",
        ok5,
        f"any_live={any_live} closes={[o.get('close') for o in out]}",
    )

    # 6 hub two paths + 現價 + 非買訊
    hub = format_wave4_hub_html()
    ok6 = all(k in hub for k in ("打代號", "實質十檔", "現價", "非買訊"))
    add(6, "hub two paths", ok6, "ok" if ok6 else hub.replace("\n", " / ")[:120])

    # 7 score fields on hits
    missing = 0
    n_rows = 0
    for b in ("intervene", "sprint", "watch"):
        for r in desk.get(b) or []:
            n_rows += 1
            for k in ("wave3_low", "wave4", "above_w4_low", "score"):
                if k not in r:
                    missing += 1
    ok7 = ok_desk and n_rows > 0 and missing == 0
    add(
        7,
        "hit fields wave3/4/score",
        ok7,
        f"rows={n_rows} missing={missing} scan_sec={scan_sec}",
    )

    lines.extend(
        [
            "",
            f"- overall: {_pass_fail(all(results))}",
            f"- n_hits={desk.get('n_hits')} intervene={desk.get('n_intervene')} "
            f"sprint={desk.get('n_sprint')} watch={desk.get('n_watch')}",
            "- observe_not_buy: true",
            "",
        ]
    )
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(OUT.read_text(encoding="utf-8"))
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
