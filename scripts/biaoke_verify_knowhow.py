#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""飆大判斷方式：把他講的時間戳對庫內日 K／台指期。

只做紀錄。不進海選、不改黃金買點。
"""
from __future__ import annotations

import os
import sqlite3
import sys
from typing import Any, Dict, List, Optional, Sequence, Tuple

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from config import get_db_path  # noqa: E402


def _conn(db: str) -> sqlite3.Connection:
    return sqlite3.connect(db)


def twii_bar(cur: sqlite3.Cursor, ymd: str) -> Optional[Tuple]:
    return cur.execute(
        "SELECT date, open, high, low, close, pct_change FROM index_daily WHERE symbol='TWII' AND date=?",
        (ymd,),
    ).fetchone()


def quote_bar(cur: sqlite3.Cursor, sid: str, ymd: str) -> Optional[Tuple]:
    return cur.execute(
        "SELECT date, open, high, low, close, volume, pct_change FROM daily_quotes WHERE stock_id=? AND date=?",
        (sid, ymd),
    ).fetchone()


def fut_bar(cur: sqlite3.Cursor, ymd: str, session: str) -> Optional[Tuple]:
    return cur.execute(
        "SELECT date, session, open, high, low, close FROM futures_daily WHERE date=? AND session=?",
        (ymd, session),
    ).fetchone()


def r20(cur: sqlite3.Cursor, sid: str, start: str, n: int = 21) -> Optional[Dict[str, Any]]:
    rows = cur.execute(
        "SELECT date, close, high, low FROM daily_quotes WHERE stock_id=? AND date>=? ORDER BY date LIMIT ?",
        (sid, start, n),
    ).fetchall()
    if not rows:
        return None
    a, b = rows[0], rows[-1]
    return {
        "first": a,
        "last": b,
        "n": len(rows),
        "ret": round((b[1] - a[1]) / a[1] * 100, 1) if a[1] else None,
        "maxh": max(x[2] for x in rows),
        "minl": min(x[3] for x in rows),
    }


def fmt_twii(row: Optional[Tuple]) -> str:
    if not row:
        return "無"
    _d, _o, h, lo, cl, pct = row
    return f"高 {h:.0f} 低 {lo:.0f} 收 {cl:.0f} ({pct:+.2f}%)"


def main() -> None:
    db = os.environ.get("WAYNE_DB_PATH") or get_db_path()
    cur = _conn(db).cursor()

    print("# 飆大時間戳對庫內（可重跑）")
    print(f"db={db}")
    span = cur.execute(
        "SELECT min(date), max(date) FROM index_daily WHERE symbol='TWII'"
    ).fetchone()
    print(f"TWII {span[0]}～{span[1]}")
    fut_span = cur.execute("SELECT min(date), max(date) FROM futures_daily").fetchone()
    print(f"TX {fut_span[0]}～{fut_span[1]}（更早夜盤庫沒有）")
    print()

    print("## 細微波／夜盤他講的點 vs 當日 TWII")
    cases: List[Tuple[str, str, str]] = [
        ("20250304", "細微波主跌完、估破 22000", "3/11 低 21770 微破；真正深跌在 3/31 20696"),
        ("20250424", "19340 支撐前止跌、夜盤看方向", "當日低 19433，未到 19340（多半是期點）"),
        ("20250509", "再測 5/5 高 20885", "當日高 20915，過了 20885"),
        ("20250602", "往下 5 波、第一階段止跌 20730", "當日低 20941，沒到 20730"),
        ("20250624", "紫軌＝4/22 低連 6/2 低", "4/22 低 18793、6/2 低 20941"),
        ("20250926", "15 分 5 波下跌、測 25174", "當日低 25469，沒破 25174"),
        ("20251105", "他後來說的 a 低 27373", "當日低 27373"),
        ("20251110", "周五夜盤破底翻＋15 分 1-4 重疊", "11/7 低 27621；11/10 低 27681 收 27870"),
        ("20251121", "加權 9/3～11/21 上升軌右端", "當日低 26396"),
        ("20251216", "夜盤往下、測 27300", "當日低 27356"),
        ("20251217", "60 分跌 5 波、穿越 27685＝不走 9", "當日低 27470 收 27525"),
        ("20260129", "夜盤大修、盯 31800", "當日高 32996 低 32472"),
        ("20260202", "周五夜盤擴延沒算到、測 31200", "當日低 31360；2/6 低 31164"),
        ("20260319", "夜盤 33613 是這幾天底部", "當日低 33664（現貨；期點差約 50）"),
        ("20260324", "觀盤 32434", "當日低 32435"),
        ("20260407", "清明向上變盤、B-c-3 測 34423", "當日收 33230；4/8 高 34761 過 34423"),
        ("20260518", "支撐 39607、15 分剛走完 5 小波", "當日低 40170；5/20 低 39967，沒到 39607"),
        ("20260521", "夜盤下降軌破壞→B 波反彈", "當日 +3.37% 收 41368"),
        ("20260611", "他後來說的 6/11 低 42206", "現貨低 42006（差約 200，應是期點）"),
        ("20260623", "60 分高 48218", "當日高 48219"),
        ("20260625", "不穿刺夜盤 47668 還有第 5 段", "當日高 46785；隔日低 44454"),
        ("20260626", "6/26 低 44454", "當日低 44454"),
        ("20260720", "現貨低 41967.75", "當日低 41968"),
        ("20260729", "A 波低 39384（他 7/31 改口確認）", "當日低 39385"),
        ("20260731", "確認 7/29 是 A 波低", "當日 +7.98% 收 43120"),
        ("20260825", "他 9/2 說的更深前低 44210", "當日低 44210"),
        ("20260831", "TX 低 45415", "現貨低 45450"),
        ("20260901", "現貨高 46948.72（他 9/4 要去測）", "當日高 46949"),
        ("20260902", "TX 高剛好 46746；現貨收 46165", "見期貨列"),
    ]
    print("| 他的日期 | 他講什麼 | 庫內 TWII | 對照 |")
    print("|----------|----------|-----------|------|")
    for ymd, said, note in cases:
        print(f"| {ymd} | {said} | {fmt_twii(twii_bar(cur, ymd))} | {note} |")

    print()
    print("## 台指期日／夜（庫只從 20260730）")
    print("| 日期 | session | 高 | 低 | 收 | 對他哪句 |")
    print("|------|---------|----|----|----|----------|")
    fut_notes = {
        ("20260730", "regular"): "日線低 39701，貼他 15 分圖 39442 附近",
        ("20260731", "regular"): "日盤大彈 收 43678",
        ("20260813", "regular"): "高 46250＝他 9/2 夜盤突破帶下緣",
        ("20260831", "regular"): "低 45415＝他 9/2 前波低",
        ("20260901", "regular"): "高 47220 收 47209",
        ("20260902", "regular"): "高剛好 46746（穿刺才不走 9 段）收 46189 沒站穩",
        ("20260904", "night"): "夜盤高 46559 收 46487，過 46250～46300",
        ("20260904", "regular"): "日盤高 46756 收 46704",
    }
    for ymd, session in [
        ("20260730", "regular"),
        ("20260731", "regular"),
        ("20260813", "regular"),
        ("20260831", "regular"),
        ("20260901", "regular"),
        ("20260902", "regular"),
        ("20260904", "night"),
        ("20260904", "regular"),
    ]:
        row = fut_bar(cur, ymd, session)
        if not row:
            print(f"| {ymd} | {session} | — | — | — | {fut_notes[(ymd, session)]} |")
            continue
        _d, _s, _o, h, lo, cl = row
        print(f"| {ymd} | {session} | {h:.0f} | {lo:.0f} | {cl:.0f} | {fut_notes[(ymd, session)]} |")

    print()
    print("## 台積電（他用來當多標籤決勝）")
    print("| 日期 | 高 | 低 | 收 | 量 | 對他哪句 |")
    print("|------|----|----|----|----|----------|")
    tsmc = [
        ("20250903", "9/3 低連 11/24 低＝黃軌"),
        ("20251124", "黃軌右端"),
        ("20260717", "低檔爆一年大量 100022、收＝低 2290"),
        ("20260729", "低 2180 量 68887；他 7/28 說已跌完→早 1 日"),
        ("20260731", "收 2425 +9.98%"),
    ]
    for ymd, note in tsmc:
        row = quote_bar(cur, "2330", ymd)
        if not row:
            print(f"| {ymd} | — | — | — | — | {note} |")
            continue
        _d, _o, h, lo, cl, vol, pct = row
        print(f"| {ymd} | {h:.0f} | {lo:.0f} | {cl:.0f} | {vol} | {note} |")

    print()
    print("## 汎銓 6830（線圖先於新聞）")
    for ymd in ["20250903", "20260224", "20260417", "20260506", "20260720"]:
        print(ymd, quote_bar(cur, "6830", ymd))
    for label, ymd, n in [("9月型態確認 20日", "20250903", 21), ("2月檢測 20日", "20260224", 21), ("4月新聞擁擠 20日", "20260417", 21), ("4月 60日", "20260417", 61)]:
        print(label, r20(cur, "6830", ymd, n))

    print()
    print("## 產業輪動（他開口那天 → 龍頭 20 或 40 日）")
    rot: Sequence[Tuple[str, str, str, int]] = [
        ("矽光子轉空 聯亞", "3081", "20250304", 61),
        ("老AI 廣達", "2382", "20250425", 41),
        ("老AI 台光電", "2383", "20250425", 41),
        ("無人機 事欣科", "4916", "20250806", 21),
        ("無人機 中光電", "5371", "20250806", 21),
        ("無人機 雷虎", "8033", "20250806", 21),
        ("無人機 長榮航太", "2645", "20250806", 21),
        ("尖點整理完成", "8021", "20251030", 21),
        ("記憶體 群聯", "8299", "20251217", 21),
        ("記憶體 南亞科", "2408", "20251217", 21),
        ("PCB出貨對照 台光電", "2383", "20251217", 21),
        ("IC設計 聯發科 4/22", "2454", "20260422", 21),
        ("IC設計 聯發科 5/08", "2454", "20260508", 21),
        ("記憶體不宜主線 南亞科", "2408", "20260508", 21),
        ("高階測試 穎崴", "6515", "20260224", 21),
        ("高階測試 旺矽", "6223", "20260224", 21),
        ("散熱先彈 奇鋐 7/21", "3017", "20260721", 21),
        ("散熱先彈 奇鋐 7/23", "3017", "20260723", 21),
    ]
    for name, sid, ymd, n in rot:
        print(name, sid, r20(cur, sid, ymd, n))

    print()
    print("## 量價背離他舉的股（連續攻擊才算；20／60 日）")
    for name, sid, ymd in [
        ("金像電 6/12", "2368", "20250612"),
        ("富喬 6/17", "1815", "20250617"),
        ("台燿 6/17", "6274", "20250617"),
        ("台光電 6/18", "2383", "20250618"),
        ("勤誠 6/19", "8210", "20250619"),
    ]:
        bar = quote_bar(cur, sid, ymd)
        print(name, sid, bar, "r20", r20(cur, sid, ymd, 21), "r60", r20(cur, sid, ymd, 61))

    print()
    print("## 聯亞 9/9（他說開盤鎖漲停）")
    print(quote_bar(cur, "3081", "20260909"))

    print()
    print("## 量先價行盲測（視窗內最大量日高低當壓撐；12 日內量<0.65×且收盤≥撐 → 從量縮日起 20 日）")
    print("視窗一換，爆量日就換。單規則不穩。要疊次族群第一名＋大盤位階。")


if __name__ == "__main__":
    main()
