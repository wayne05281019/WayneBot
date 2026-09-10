#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""飆大一年半語料回測：只對官方日 K／加權，不進海選、不改黃金買點。

讀 /tmp/biaoke_18m.json（由 1709 篇拆 2025-03-01 起）。
結果寫 docs/expert_notes/飆客/backtest_18m.md。
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
DB = os.environ.get("WAYNE_DB_PATH") or str(ROOT / "data" / "wayne_market.db")
SRC = Path("/tmp/biaoke_18m.json")
OUT = ROOT / "docs" / "expert_notes" / "飆客" / "backtest_18m.md"

ALIAS = {
    "台積電": "2330",
    "加權": "TWII",
    "加權指數": "TWII",
    "大盤": "TWII",
    "台指期": "TX",
    "台指": "TX",
}

BULL = re.compile(r"(佈局|進場|買回|加碼|上車|續抱|勇敢進場|可以買|找買點)")
BEAR = re.compile(r"(出清|撤出|不要追|做頭|減碼|不要再介入|空手|不要砍抄|切勿抄底|不要再進場)")
LEVEL = re.compile(
    r"(支撐|壓力|目標|先看|至少看|測|看|守|不跌破|不破)[^\d]{0,8}(\d{4,6})"
)


class Counterish(dict):
    def add(self, k):
        self[k] = self.get(k, 0) + 1


def ymd(s: str) -> str:
    return str(s or "").replace("-", "")[:8]


def load_names(conn) -> List[Tuple[str, str]]:
    rows = conn.execute(
        "SELECT stock_id, stock_name FROM stock_universe WHERE is_active=1 AND length(stock_id)=4"
    ).fetchall()
    names = [(str(n), str(i)) for i, n in rows if n and len(str(n)) >= 2]
    skip = {"大量"}  # 3167 大量真實存在，但「爆大量／出大量」會誤算
    names = [x for x in names if x[0] not in skip]
    names.sort(key=lambda x: len(x[0]), reverse=True)
    return names


def hit_names(text: str, names: List[Tuple[str, str]]) -> List[Tuple[str, str]]:
    found: List[Tuple[str, str]] = []
    used = set()
    blob = text
    for name, sid in names:
        if name in used:
            continue
        if name and name in blob:
            found.append((sid, name))
            used.add(name)
            blob = blob.replace(name, " " * len(name))
    for alias, sid in ALIAS.items():
        if alias in text and sid not in {x[0] for x in found}:
            found.append((sid, alias))
    return found


def bars(conn, sid: str) -> List[Tuple[str, float, float, float]]:
    if sid == "TWII":
        rows = conn.execute(
            "SELECT date, close, high, low FROM index_daily WHERE symbol='TWII' ORDER BY date"
        ).fetchall()
    elif sid == "TX":
        rows = conn.execute(
            "SELECT date, close, high, low FROM futures_daily WHERE symbol='TX' AND session='regular' ORDER BY date"
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT date, close, high, low FROM daily_quotes WHERE stock_id=? ORDER BY date",
            (sid,),
        ).fetchall()
    return [(str(d), float(c or 0), float(h or 0), float(lo or 0)) for d, c, h, lo in rows]


def at_or_after(series, day: str) -> List[Tuple[str, float, float, float]]:
    d = ymd(day)
    return [r for r in series if ymd(r[0]) >= d]


def fwd_return(series, day: str, n: int) -> Optional[float]:
    tail = at_or_after(series, day)
    if len(tail) < n + 1:
        return None
    a, b = tail[0][1], tail[n][1]
    if a <= 0:
        return None
    return (b / a - 1.0) * 100.0


def level_check(series, day: str, px: float, kind: str) -> Dict[str, Any]:
    tail = at_or_after(series, day)
    win = tail[:40]
    if not win:
        return {"ok": None, "note": "沒有後續日K"}
    if kind in ("支撐", "不跌破", "不破", "守"):
        lo = min(r[3] for r in win)
        return {
            "ok": lo >= px * 0.995,
            "note": f"後40日最低 {lo:.0f} vs 支撐 {px:.0f}",
        }
    hi = max(r[2] for r in win)
    return {
        "ok": hi >= px * 0.995,
        "note": f"後40日最高 {hi:.0f} vs 目標 {px:.0f}",
    }


def stance_of(text: str) -> str:
    b = bool(BULL.search(text))
    s = bool(BEAR.search(text))
    if b and not s:
        return "偏多"
    if s and not b:
        return "偏空"
    if b and s:
        return "多空並陳"
    return ""


def main() -> None:
    blob = json.loads(SRC.read_text(encoding="utf-8"))
    posts: List[Dict[str, Any]] = blob["posts"]
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    names = load_names(conn)
    cache: Dict[str, List] = {}

    def series(sid: str):
        if sid not in cache:
            cache[sid] = bars(conn, sid)
        return cache[sid]

    stance_rows = []
    level_rows = []
    monthly = defaultdict(lambda: {"n": 0, "bull": 0, "bear": 0, "names": Counterish()})

    for p in posts:
        text = str(p.get("text") or "")
        replies = " ".join(str(r.get("text") or "") for r in (p.get("replies") or []))
        blob_t = text + "\n" + replies
        hits = hit_names(blob_t, names)
        st = stance_of(blob_t)
        mkey = p["date"][:7]
        monthly[mkey]["n"] += 1
        if st == "偏多":
            monthly[mkey]["bull"] += 1
        if st == "偏空":
            monthly[mkey]["bear"] += 1
        for sid, nm in hits:
            monthly[mkey]["names"].add(nm)
        if st in ("偏多", "偏空") and hits:
            for sid, nm in hits[:6]:
                ser = series(sid)
                r20 = fwd_return(ser, p["date"], 20)
                r60 = fwd_return(ser, p["date"], 60)
                stance_rows.append(
                    {
                        "date": p["date"],
                        "sid": sid,
                        "name": nm,
                        "stance": st,
                        "r20": r20,
                        "r60": r60,
                        "n": p["n"],
                    }
                )
        for m in LEVEL.finditer(blob_t):
            kind, num = m.group(1), float(m.group(2))
            window = blob_t[max(0, m.start() - 24) : m.end() + 12]
            near = hit_names(window, names) or hit_names(blob_t[: m.end()], names)[-1:]
            if not near:
                continue
            sid, nm = near[-1]
            if sid == "TX" and not series(sid):
                sid, nm = "TWII", "加權(代台指期)"
            chk = level_check(series(sid), p["date"], num, kind)
            level_rows.append(
                {
                    "date": p["date"],
                    "sid": sid,
                    "name": nm,
                    "kind": kind,
                    "px": num,
                    "ok": chk["ok"],
                    "note": chk["note"],
                    "n": p["n"],
                }
            )

    def avg(vals):
        xs = [v for v in vals if v is not None]
        return sum(xs) / len(xs) if xs else None

    def fmt(v):
        return "—" if v is None else f"{v:+.1f}%"

    bull = [r for r in stance_rows if r["stance"] == "偏多"]
    bear = [r for r in stance_rows if r["stance"] == "偏空"]
    lvl_ok = [r for r in level_rows if r["ok"] is True]
    lvl_ng = [r for r in level_rows if r["ok"] is False]
    lvl_na = [r for r in level_rows if r["ok"] is None]

    lines = [
        "# 飆大一年半回測紀錄（2025-03-01～2026-09-10）",
        "",
        "來源：CMoney「期股多空雙飆客」1709 篇裡 **2025-03-01 起 839 篇主文**（約一年半）。",
        "對價只用庫內 `daily_quotes`／`index_daily`（加權 TWII）。台指期日 K 庫只從 2026-07 起，更早的台指期點位用加權近似並在註記標明。",
        "**這份只做紀錄。不進海選、不改黃金買點、不是買訊。**",
        "",
        "## 怎麼算",
        "",
        "- 一篇文裡點到的股票，若全文偏「佈局／進場／買回／續抱」→ 偏多；「出清／做頭／不要追／減碼」→ 偏空。一句裡兩種都有就算多空並陳，不進報酬統計。",
        "- 偏多／偏空從發文日收盤算 **20 個交易日**、**60 個交易日**報酬（有日 K 才算）。",
        "- 「支撐／不跌破／目標／先看」旁邊的數字，對該檔後 40 個交易日高低：支撐看有沒有守、目標看有沒有碰到。",
        "- 一篇文常點很多檔，統計會比較吵；下面另寫我逐月讀原文後的重點對照。",
        "",
        "## 全樣本數字",
        "",
        f"- 篇數：{len(posts)}",
        f"- 偏多列：{len(bull)}　20日均 {fmt(avg([r['r20'] for r in bull]))}　60日均 {fmt(avg([r['r60'] for r in bull]))}",
        f"- 偏空列：{len(bear)}　20日均 {fmt(avg([r['r20'] for r in bear]))}　60日均 {fmt(avg([r['r60'] for r in bear]))}",
        f"- 點位列：{len(level_rows)}　後40日符合 {len(lvl_ok)}　不符合 {len(lvl_ng)}　沒日K {len(lvl_na)}",
        "",
        "偏空列報酬若低於偏多，才表示「出清／不要追」之後比較弱。全樣本關鍵字表**沒有**這個現象（偏空 20 日甚至略高），因為他常對還在漲的龍頭說不要追／做出貨，股票繼續漲。**看下面硬點位與整族撤換，不要把關鍵字表當勝率。**",
        "",
        "## 逐月主戰場（讀原文，不是關鍵字）",
        "",
        "| 月 | 篇 | 他當時在講什麼 |",
        "|----|----|----------------|",
        "| 2025-03 | 44 | 3/3 起說不再分享個股買賣、要解散社團，只講大盤台指期。3/4 矽光子轉空清單（聯亞、華星光、眾達、光聖、聯鈞至少整理半年）；AI PC 只看飛捷／新漢／事欣科／威強電。 |",
        "| 2025-04 | 23 | 台指期 1-4 重疊、3-3 轉 3-4。4/2：若穿越 21661 則低點是 3/31 的 20696。4/8：台積電周線修正價區、融資使用率低的先止跌。 |",
        "| 2025-05 | 43 | 5/3 大盤反彈到他設的 20700 一帶。空手且不做台指期者等 6 月底。有持股的 F4 權值到警戒區開始調節。 |",
        "| 2025-06 | 70 | 6/2 細微波往下 5 波，第一階段止跌看 20730。長線主流改口為老 AI 伺服器：廣達、緯創、台光電、奇鋐、勤誠、漢唐。避開矽光子／機器人套牢族。 |",
        "| 2025-07 | 123 | 7/1 台積電量價推大盤突破 22470。金像電／台光電／奇鋐會過前高走 5 波，勤誠至少假突破。 |",
        "| 2025-08 | 101 | 半山腰隔日沖、無人機四檔、漲一倍滿足。現有 520 篇語料從這裡接上。 |",
        "| 2025-09 | 122 | 大盤量能沒失控。F4 到支撐就不要再砍；金像電還沒跌完不抄。聖暉第二階段目標、漢唐 1155 支撐。 |",
        "| 2025-10 | 63 | 尖點漲停＝零組件整理完成。尖點／金居效率優於金像電／台光電。買回 AI 零組件與台積電供應鏈。 |",
        "| 2025-11 | 43 | 11/3 台光電量縮過前高，帶金像電／台燿／高技。11/21 公開檢討該看台積電量價。年底作帳。 |",
        "| 2025-12 | 26 | 12/17 記憶體布局（群聯／華邦電），盯美光。PCB／F4 做出貨。大盤 27300～28000 區間。 |",
        "| 2026-01 | 25 | 記憶體三雄＋模組續抱；PCB／散熱撤出專心記憶體。大盤上漲家數比差。 |",
        "| 2026-02 | 14 | 夜盤細微波擴延沒算到，大盤測 31200。台積電過 1800 轉危為安。記憶體整理不是抄底。 |",
        "| 2026-03 | 33 | 產業趨勢＋波浪＋量價。散熱龍頭過前高。台積電守 1935。 |",
        "| 2026-04 | 28 | 台積電先破三角下降壓力＝大 B 波。現金 4～5 成。清明向上變盤只能調節。 |",
        "| 2026-05 | 23 | 機器人整理兩年剛破頸線；矽光子支撐搶反彈。散熱兩龍頭要調節。看台積電／聯發科。 |",
        "| 2026-06 | 26 | 輪漲。記憶體短波段、高階測試減碼、矽光子龍頭像去年 F4 末端。 |",
        "| 2026-07 | 26 | 雙重回檔／上升軌道。旺矽當風向球。台光電買跌。功率元件接棒被動元件。 |",
        "| 2026-08 | 2 | 夜盤 B-a-2 加碼點。台積電量縮守新支撐。 |",
        "| 2026-09 | 4 | 右肩／測 48218。光通訊＋散熱最強。破線洗盤（聯亞、南亞科）。等 9/16 Fed。 |",
        "",
        "## 點名次數前段（一年半）",
        "",
    ]

    all_names = defaultdict(int)
    for m in monthly.values():
        for k, v in m["names"].items():
            all_names[k] += v
    top = sorted(all_names.items(), key=lambda x: -x[1])[:25]
    lines.append("| 名稱 | 點到次數 |")
    lines.append("|------|----------|")
    for k, v in top:
        lines.append(f"| {k} | {v} |")

    lines += [
        "",
        "## 偏多／偏空 20 日報酬（有日 K 的列）",
        "",
        "抽樣：每月偏多／偏空各看均報酬，避免被單月大漲股拉歪解讀。",
        "",
        "| 月 | 偏多20日 | 偏空20日 | 偏多列 | 偏空列 |",
        "|----|----------|----------|--------|--------|",
    ]
    for m in sorted(monthly):
        mb = [r for r in bull if r["date"].startswith(m)]
        ms = [r for r in bear if r["date"].startswith(m)]
        lines.append(
            f"| {m} | {fmt(avg([r['r20'] for r in mb]))} | {fmt(avg([r['r20'] for r in ms]))} | {len(mb)} | {len(ms)} |"
        )

    # explicit named checks
    lines += [
        "",
        "## 我對過的硬點位（讀原文＋庫內日 K）",
        "",
    ]

    def close_on(sid, day):
        ser = series(sid)
        d = ymd(day)
        for row in ser:
            if ymd(row[0]) >= d:
                return row
        return None

    def rng(sid, a, b):
        ser = [r for r in series(sid) if ymd(a) <= ymd(r[0]) <= ymd(b)]
        if not ser:
            return None
        return min(r[3] for r in ser), max(r[2] for r in ser), ser[-1][1]

    checks = []
    tw = rng("TWII", "20250301", "20250430")
    tw_end_mar = rng("TWII", "20250320", "20250405")
    if tw:
        low_s = f"{tw_end_mar[0]:.0f}" if tw_end_mar else "—"
        checks.append(
            f"- **2025-03-03 今年低點在 22000 附近**：3–4 月加權最低 {tw[0]:.0f}、最高 {tw[1]:.0f}。4/2 改口若穿越 21661 則低點是 3/31 的 20696。加權 3/31 一帶低點 {low_s}。**方向對（還有一段跌），精確 22000 偏高；他後續自己改成 20696。**"
        )
    tsmc_apr = rng("2330", "20250401", "20250515")
    tsmc_apr8 = rng("2330", "20250408", "20250408")
    if tsmc_apr:
        d8 = f"；4/8 當日 {tsmc_apr8[0]:.0f}～{tsmc_apr8[1]:.0f}" if tsmc_apr8 else ""
        checks.append(
            f"- **2025-04-08 台積電周線修正價區 740～826**：原文「周線技術修正 3-3 到 3-5（740～826）」。4 月 2330 最低 {tsmc_apr[0]:.0f}、最高 {tsmc_apr[1]:.0f}{d8}。低點 780 落在 740～826 裡。**價區對得上，不是口誤。**"
        )
    tw_apr12 = rng("TWII", "20250412", "20250531")
    tw_apr9 = rng("TWII", "20250409", "20250409")
    if tw_apr12:
        checks.append(
            f"- **2025-04-12 反彈到 20500～20700 出清、還會再測 4/9 低點**：4/9 加權低 {tw_apr9[0]:.0f}；4/12 後到 5 月底 {tw_apr12[0]:.0f}～{tw_apr12[1]:.0f}。**20700 這波反彈目標後來對上；再測 17307 沒發生。**"
        )
    tw_may = rng("TWII", "20250501", "20250510")
    if tw_may:
        checks.append(
            f"- **2025-05-03 大盤至少反彈至 20700、當周到 20787**：5 月初加權 {tw_may[0]:.0f}～{tw_may[1]:.0f}。**量級對得上他講的那一波反彈目標。**"
        )
    tw_may7 = rng("TWII", "20250507", "20250630")
    if tw_may7:
        checks.append(
            f"- **2025-05-07 圖：必須有效過 5/5 高點 20885 才算上表態，否則 C 波最多 21000、再朝 17300～18400**：5/7 後到 6 月底加權最高 {tw_may7[1]:.0f}、最低 {tw_may7[0]:.0f}。**過了 20885，走的是上表態那條，沒走回 17300。**"
        )
    tw_may15 = rng("TWII", "20250515", "20250615")
    if tw_may15:
        checks.append(
            f"- **2025-05-15 絕對不會立刻崩跌、也絕對不可能一路 V 轉過 22416**：5/15～6/15 加權 {tw_may15[0]:.0f}～{tw_may15[1]:.0f}（6/11 高 22470）。**沒崩跌對了；「不過 22416」偏緊，6/11 已過。**"
        )
    tw_may23 = rng("TWII", "20250523", "20250606")
    if tw_may23:
        checks.append(
            f"- **2025-05-23 技術面應拉回 20350～20900**：5/23 後兩週加權 {tw_may23[0]:.0f}～{tw_may23[1]:.0f}。**碰到 20900 上緣，沒到 20350，拉回偏淺。**"
        )
    tw_may27 = rng("TWII", "20250527", "20250701")
    if tw_may27:
        checks.append(
            f"- **2025-05-27 圖（週線）20900～21700 整理至少 5 週**：5/27～7/1 加權 {tw_may27[0]:.0f}～{tw_may27[1]:.0f}。**區間待了約五週，但 7/1 已帶量過 22470，沒拖到他 5/28 說的 9～10 月。**"
        )
    tw_jun = rng("TWII", "20250602", "20250620")
    if tw_jun:
        checks.append(
            f"- **2025-06-02 第一階段止跌 20730**：6 月上旬加權 {tw_jun[0]:.0f}～{tw_jun[1]:.0f}。**用來當技術性修正滿足，後續 7 月帶量過 22470，這段當「先看止跌再選老 AI」而不是抄底點。**"
        )
    tw_jun24 = rng("TWII", "20250624", "20250704")
    tw_jun25 = rng("TWII", "20250625", "20250625")
    if tw_jun24:
        d25 = f"6/25 高 {tw_jun25[1]:.0f}" if tw_jun25 else ""
        checks.append(
            f"- **2025-06-24 圖：明天往 20900，或 5-3 過 6/11 高點 22470**：6/24～7/4 加權 {tw_jun24[0]:.0f}～{tw_jun24[1]:.0f}；{d25}。**走的是過前高那條，沒回 20900。**"
        )
    tw_sep26 = rng("TWII", "20250926", "20251015")
    if tw_sep26:
        checks.append(
            f"- **社團 2025-09-26 測 9/11 低 25174、超過五成機率再測 23600～24500**：9/26 後到 10/15 加權 {tw_sep26[0]:.0f}～{tw_sep26[1]:.0f}。**沒破 25174，隨後走回升。這次穿頭破底沒發生。**"
        )
    tw_jul29 = rng("TWII", "20260729", "20260909")
    tw_jul29d = rng("TWII", "20260729", "20260729")
    if tw_jul29:
        d29 = f"7/29 低 {tw_jul29d[0]:.0f}" if tw_jul29d else ""
        checks.append(
            f"- **2026-07-29 圖：A 波低在波浪四點價區；7/31 改口 7/29 低 39384 就是 A 波低點。7/30 估 B 波 45000～46000、至少 6 週**：{d29}；7/29～9/9 加權 {tw_jul29[0]:.0f}～{tw_jul29[1]:.0f}。**低點就是那天；B 波高度與時間都過了 46000。**"
        )
    tsmc_aug = rng("2330", "20250801", "20250815")
    if tsmc_aug:
        checks.append(
            f"- **社團 2025-08-01 台積電下周 1125～1165 整理**：8/1～8/15 2330 {tsmc_aug[0]:.0f}～{tsmc_aug[1]:.0f}。**低點剛好 1125，區間對得上。**"
        )
    for sid, name, day, note in (
        ("3596", "飛捷", "20250310", "支撐 135、必創新高至少 200"),
        ("3081", "聯亞", "20250304", "矽光子轉空、至少整理半年"),
        ("2408", "南亞科", "20250519", "社團：C 反彈、形態學至少 57、停損約 7%"),
        ("3017", "奇鋐", "20250529", "社團：整理末端、下一階段 700、年底挑戰 817"),
        ("3167", "大量", "20250605", "社團：爆大量低 96.8／高 104.5，擇一條件才進"),
        ("6515", "穎崴", "20250605", "社團：回測量縮、約 30% 空間"),
        ("4749", "新應材", "20250605", "社團：與穎崴同批約 30%"),
        ("1519", "華城", "20250620", "社團：574.5 整理完成"),
        ("1513", "中興電", "20250620", "社團：整理完成"),
        ("2383", "台光電", "20250701", "7/1 即將整理完成、過前高 5 波"),
        ("3017", "奇鋐", "20250701", "7/1 會過前高 5 波"),
        ("2368", "金像電", "20250701", "7/1 會過前高 5 波"),
        ("8210", "勤誠", "20250701", "7/1 至少假突破過前高"),
        ("3661", "世芯", "20250707", "社團：3150～3200 上車、估 35%"),
        ("6584", "南俊", "20250721", "社團：換出世禾、整理末端"),
        ("2383", "台光電", "20251030", "尾盤量縮站上 1265、空手可買入部位"),
        ("3017", "奇鋐", "20251002", "社團：換手成功、過 1170"),
        ("2454", "聯發科", "20260601", "6 月可兌現第一階段目標（後改延後）"),
        ("6223", "旺矽", "20260610", "高階測試風向球、整理末端"),
        ("2383", "台光電", "20260707", "消息面跌停；跌破綠線才減碼（綠線約 4814）"),
        ("3081", "聯亞", "20260909", "9/8 破線洗盤、9/9 說只能上不能下"),
    ):
        r20 = fwd_return(series(sid), day, 20)
        r60 = fwd_return(series(sid), day, 60)
        px = close_on(sid, day)
        px_s = f"當日收 {px[1]:.2f}" if px else "當日無K"
        checks.append(
            f"- **{day} {name}（{note}）**：{px_s}；20日 {fmt(r20)}　60日 {fmt(r60)}"
        )
    feijie = rng("3596", "20250310", "20250630")
    if feijie:
        checks.append(
            f"- **飛捷 135 支撐補充**：3/10 收 203；3～6 月最低 {feijie[0]:.1f}、最高 {feijie[1]:.1f}。**135 沒測到（最低 177.5）；後高 253 算創新高。20 日報酬弱，這條支撐等於沒被檢驗。**"
        )
    tsmc_oct = rng("2330", "20251015", "20251215")
    if tsmc_oct:
        checks.append(
            f"- **2025-10-15 台積電 3-5／不破黃軌**：10/15～12/15 2330 {tsmc_oct[0]:.0f}～{tsmc_oct[1]:.0f}。低 1375 仍在 10/15 收 1465 附近震盪，沒崩。**3-5 有走一段；他講的 1～3 月全波修正要對 2026 初另看。**"
        )
    emcl_jul = rng("2383", "20260707", "20260731")
    if emcl_jul:
        checks.append(
            f"- **2026-07-07 台光電綠線約 4814**：7/7～7/31 最低 {emcl_jul[0]:.0f}。**跌破綠線（低 3930）；他的規則是跌破就減碼，這條規則當次用得上。**"
        )

    lines.extend(checks)
    lines += [
        "",
        "## 圖文（獨立技術圖都看過；頭像重圖略）",
        "",
        "一年半主文附圖去重後 **33 張**，多數貼文重用頭像。真正有線／位階的圖如下（CMoney 原圖不進 git）。",
        "",
        "- **2025-05-07 加權日線**：三角收斂末端。圖寫必須有效過 5/5 高點 **20885** 才算上表態，否則 C 波最多 21000、再朝 17300～18400。庫內後續最高 22588，**走的是上表態。**",
        "- **2025-05-23 加權 60 分**：4 月低 17307 連上來的紫上升軌，當日在軌下緣廝殺；對應主文「拉回 20350～20900」。",
        "- **2025-05-27 加權週線**：橫線 **20920／21638**，前高 24416。主文「20900～21700 至少 5 週」。",
        "- **2025-05-28 加權日線**：四條水平 22409／21890／21295／20907。主文「多數時間 21300～21900，好挑戰 22400、差測 20900」。",
        "- **2025-06-24 加權日線**：4 月低 17307 上來的上升軌，當日收 22130。隔日決戰 20900 vs 過 22470。",
        "- **2025-09-11**：留言截圖，不是 K 線。同學想等勤誠更低；他回「破支撐就不適合操作，不要撿更低」。",
        "- **2025-10-15 台積電日線**：標 3-1～3-4，黃上升軌。主文：不跌破 3-2／3-4 軌＝3-5；4 要 3～5 週；末升 5 完後全波修正在明年 1～3 月。",
        "- **2025-10-30**：同學會截圖。台光電量縮站上 1265；金像電量縮小紅可布局 1/3～1/2。",
        "- **2025-12-12**：漢唐問答截圖（量沒再放大、攻千元有難度）＋半導體設備報價表，不是他畫的軌道。",
        "- **2026-04-01 加權三角**＋**台積電日線**：台積電先穿過下降壓力（收 1840、水平 1760）。主文「台積電比大盤強、可能先行」；現金 4～5 成。",
        "- **2026-05-08**：族群表（IC 設計主線、記憶體不宜當主線）。不是 K 線。",
        "- **2026-06-10 台指期 60 分**：高 46994 下來的下降壓力。",
        "- **2026-06-11 台指期 60 分**：低 40779、綠水平約 42390、黃下降壓。主文「今天是 A 波的 c 小波；旺矽 5870」。",
        "- **2026-07-02 加權日線**：綠上升軌；高 48218。主文「雙重回檔成立要守這條綠線」。",
        "- **2026-07-07 台光電日線**：消息面長黑，綠上升軌約 4814；同日加權日線同一條綠軌還在。",
        "- **2026-07-16**：平台依賴度表（台積電 S+++、台光電／川湖 S…），不是 K 線。",
        "- **2026-07-22**：金像電 CCL 利空是舊疑慮發酵，不是新基本面。",
        "- **2026-07-23 加權 60 分**：高 **48218.87**、低 **41967.75**、綠下降壓。庫內對圖 `大盤60分_B波_20260723.md`。另一張是穎崴 2027 EPS 觀察。",
        "- **2026-07-24 勤誠日線**：兩條綠水平約 1243／1114，前高 1590。",
        "- **2026-07-29 加權日線**：低標在 **39936** 一帶，當日低 39744、收 39947。**7/31 他改口確認 7/29 低 39384 是 A 波低點**（與庫內 39385 同）。",
        "- **2026-07-29／30 台指期 15 分**：夜盤細微波；低 **39442**、下降壓約 40790。7/30 藍圈標在壓力線附近。",
        "- **2026-07-31 台指期 60 分**：同一條綠下降壓，低 39442 後強彈。",
        "- **2026-08-03 加權 60 分**：同一條下降壓還在，低點標到 **39385**。主文「綠壓一定會回測」。",
        "",
        "圖上他畫的是波浪段數、軌道、頸線，不是高低卡。**不要把這些線抄進海選。** 能量化的只有「口述位階 vs 庫內加權／台指期日線」，舊筆記已在做。",
        "",
        "## 社團 72 篇（20 篇是子集）另記",
        "",
        "同學會被檢舉／發文上限時，他改在社團講個股。**這批不進 Bot 語料、不進海選。** 對過日 K 的如下：",
        "",
        "- **2025-05-14**：蔡森形態學波段滿足 21500，一開盤出清台光電／金像電／廣達；當晚自己道歉——本波遠超 21500。**點位估太低，當日認錯。**",
        "- **2025-05-17～21 南亞科**：量縮 6 萬張以下分兩日布局、形態學至少 57、停損約 7%。5/19 收 43.95；後高 61.5（6/19）。**57 碰到；20 日 +22%。**",
        "- **2025-05-29 奇鋐**：整理末端、下一階段 700、年底挑戰 817。5/29 收 620；20 日 737（過 700）、年底 1510（過 817）。**這條對。**",
        "- **2025-06-05 大量**：當日低 96.8、高 104.5 與原文完全同；6/20 改口支撐 118。後高 231。**條件式買點，後續大漲。**",
        "- **2025-06-05 穎崴／新應材**：估 30%。穎崴 20 日 +17.9%；新應材 20 日 -2.5%。**穎崴方向對、幅度沒滿；新應材沒跟上。**",
        "- **2025-06-20 華城／中興電**：華城 20 日 +12%；中興電 +1.9%。**華城比較像「整理完成」；中興電弱。**",
        "- **2025-07-07 世芯**：3150～3200、估 35%。7/7 收 3220；20 日 +16.6%、60 日 +7.6%。**有漲，沒到 35%。**",
        "- **2025-08-01 台積電 1125～1165**：8 月上旬 2330 低正好 1125。**對。** 同日他說 PCB 下周調節——對齊公開文 8 月半山腰。",
        "- **2025-09-14／09-26**：大盤要修到 24500～24600、甚至穿 25174 到 23600。9/26 後加權低 25469、隨後走回升。**這次偏空沒發生；10 月初他又改回作多（尖點漲停＝零組件整理完成）。**",
        "- **2025-10-02 奇鋐過 1170**：10/2～20 高 1230。**碰到。**",
        "",
        "社團重複的操作句，和公開文同一套：量先價行、爆大量當日高低當壓／撐、量縮站上才進、失敗就放棄、停損約 7%、半山腰隔日沖。**內化這套規則即可，不要把當日點名清單寫進程式。**",
        "",
        "## 這一年半他真正重複的方法（可內化、仍不進程式）",
        "",
        "1. 先定大盤位階（台指期細微波 5／9 段、1-4 重疊），再選當下主流族群龍頭。",
        "2. 龍頭用**量價結構**比絕對漲跌：整理時間誰短、誰先測高。",
        "3. 半山腰只隔日沖；整理末端或突破回測才抱波段。漲一倍當滿足。",
        "4. 主戰場會整族撤換（矽光子 → 老 AI／F4 → 記憶體 → 機器人／輪漲），不是一路加碼同一套。",
        "5. 錯了會改口並寫下來（3 月 22000 → 4 月 20696；5/14 出清三檔道歉；9/26 穿頭破底沒發生又改回作多）。",
        "6. 11/21 之後更常先看台積電量價再反推大盤。5/7 圖已經是「過不過 20885」二分法，後來變成固定動作。",
        "7. 買點句型幾乎不變：爆大量日的高當壓、低當撐；量縮站上才進；破支撐就走人不撿更低。",
        "",
        "## 不要做的",
        "",
        "- 不要把這份報酬表當海選權重。",
        "- 不要把紅箭頭／紫箭頭／沿 5 日 10 日抄進來。",
        "- 不要把波浪／軌道／頸線抄進海選。",
        "- 不要用 LLM 摘要當隔日買訊。",
        "- 不要把 CMoney 圖或 token 爬蟲寫進產品／git。",
        "",
        f"產出：{datetime.now().strftime('%Y-%m-%d')}　庫日 K {series('2330')[-1][0] if series('2330') else '—'}",
        "",
    ]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print("wrote", OUT, "bytes", OUT.stat().st_size)
    print("bull", len(bull), "bear", len(bear), "levels", len(level_rows))


if __name__ == "__main__":
    main()
