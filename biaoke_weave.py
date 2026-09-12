# -*- coding: utf-8 -*-
"""飆客貫通：把 1709＋樓下＋社團沿時間軸串成同一條判斷。

逐則自問自答是零件。這裡做的是左右則互證、方法互證、點位家族、產業輪動。
社團只內化。庫沒 15 分就不數段。不是買訊。
"""
from __future__ import annotations

import gzip
import json
import os
import re
import sqlite3
from collections import Counter, defaultdict
from functools import lru_cache
from typing import Any, Dict, List, Optional, Sequence, Tuple

from tg_layout import html_escape

_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs", "expert_notes", "飆客")
WEAVE_GZ = os.path.join(_DIR, "weave_index.json.gz")

_MARK = re.compile(
    r"(買跌不買漲|抱到明年|護城河|風向球|創新高|出清|抄底|破線洗盤|"
    r"長抱|首選|做頭|半山腰|買跌|續抱|不要再介入|整理完成)"
)
_FLIP = re.compile(r"(出清|做頭|更正|已經沒了|看錯|不要再介入|失敗的第五|改口)")
_WEAVE_ASK = re.compile(
    r"(貫通|串聯|串起來|融會|輪動|怎麼連|怎麼串|全部|整套|"
            r"資金剛起|主流現在|現在主流|點位.*連|連在一起|"
            r"改口|看錯|跟漲|龍頭怎麼|開口.*對|接棒.*對|對不對|"
            r"那晚|同一晚|這幾晚|事件夜|翻案|"
            r"還能抱|要不要賣|現在什麼強|大盤怎樣|他最近|晚上那則|"
            r"有緣人|輔助判|多重比對|沒講出來)"
)
_SUBJECT_NEAR = re.compile(
    r"(滿足|目標價|破底|續抱|出清|護城河|買跌|首選|站上|支撐|"
    r"不要再介入|長抱|風向球|抄底|整理完成|做頭|減碼|換到|"
    r"可抱到|僅次|世界第一)"
)


def _px(val: Any) -> str:
    try:
        n = float(val)
    except (TypeError, ValueError):
        return ""
    if abs(n - round(n)) < 1e-6:
        return str(int(round(n)))
    return f"{n:.2f}".rstrip("0").rstrip(".")


def _ymd(raw: Any) -> str:
    t = str(raw or "").replace("-", "")[:8]
    return t if len(t) == 8 and t.isdigit() else ""


def _clip(text: str, n: int) -> str:
    s = re.sub(r"\s+", " ", str(text or "")).strip()
    return s if len(s) <= n else s[: n - 1] + "…"


def _clip_about(text: str, name: str, n: int) -> str:
    blob = re.sub(r"\s+", " ", str(text or "")).strip()
    i = blob.find(name)
    if i < 0:
        return _clip(blob, n)
    return _clip(blob[max(0, i - 8) :], n)


def _is_subject(text: str, name: str) -> bool:
    blob = text or ""
    if not name or name not in blob:
        return False
    stripped = blob.lstrip()
    if stripped.startswith(name) or name in blob[:48] or f"有關{name}" in blob[:90]:
        return True
    start = 0
    hits = 0
    while True:
        i = blob.find(name, start)
        if i < 0:
            break
        hits += 1
        window = blob[max(0, i - 16) : i + len(name) + 28]
        if _SUBJECT_NEAR.search(window):
            return True
        start = i + len(name)
    return hits >= 2


# 手寫貫通主軸：問整套／輪動／點位家族時走這裡。
_MASTERS: List[Dict[str, Any]] = [
    {
        "id": "system",
        "keys": re.compile(
            r"(貫通|串聯|串起來|融會|整套|怎麼判|判斷方式|他怎麼看|"
            r"全部|怎麼串|骨架|反向想)"
        ),
        "a": (
            "他不是並排三套指標。先用產業趨勢決定做哪一條鏈、誰是龍頭；"
            "再用次族群第一名、誰先過前高決定跟哪一檔；"
            "大盤細微波（夜盤 15／60、費半先行）決定能不能做、何時回收；"
            "個股買點才用量先價行。波浪只解大盤，不准百分之百套個股。"
            "長線龍頭（2026-04-16：台積電、台達電、台光電、旺矽、穎崴、奇鋐）是大盤大跌時介入、買跌不買漲；"
            "半山腰只隔日沖。位階不講死，錯了就改口——9/11 說勝負在及時修正不是預測。"
            "覆巢之下無完卵：大盤不穩，個股先規劃回收。"
            "主音是細微波／軌道，他自己說波浪沒辦法 100%。確認低點還要疊沒講完的輔助："
            "台積電量價、費半／那指先行、夜盤是否先過下降壓、第一次碰到次級四；風向球只是領先不是低點保證。"
            "單講趨勢向上、初步止訊號、右肩有守＝還不到確認。"
            "對跟錯一起留：改口本身就是方法，不要只背對的那天。不是買訊。"
        ),
    },
    {
        "id": "index",
        "keys": re.compile(
            r"(點位.*連|怎麼連|48218|47578|46506|45839|39385|"
            r"右肩|位階二|大盤結構|這些點|大盤怎樣|會跌嗎|守得住)"
        ),
        "a": (
            "2026 下半年大盤是同一組結構，不是五個孤立數字。"
            "7/29 加權低 39385＝他認定的大 A 低（7/16「不破 40000」、7/24「今天最低」後來都錯，改口留著）。"
            "6/23 高 48218＝更大一級前高，7/23 的 60 分下降壓從這裡連，9/10 說下波起漲至少測它。"
            "9/3 低 45839＝右肩低，有守才是高有過前高、低不破前低。"
            "9/8 高 47578＝近波前高，下周過了才維持右肩，還在波浪位階二，不是升成大 3。"
            "9/10 台指日盤低 46506＝9/11 夜盤確認短線末端的水平，不是加權 9/10 低 46573。"
            "15 分 5 段＋下降軌破壞只是這組結構裡的微觀；庫沒 15 分就不數。不是買訊。"
        ),
    },
    {
        "id": "rotate",
        "keys": re.compile(
            r"(輪動|接棒|主流現在|現在主流|資金剛起|哪個族群|產業輪動|"
            r"散熱|記憶體布局|老 AI|現在什麼強|資金去哪)"
        ),
        "a": (
            "資金輪動是一條時間軸，不是當天新聞。"
            "2025-04 老 AI 伺服器（廣達、台光電）最整齊；2025-06～08 PCB＋散熱＋廠務無塵室（漢唐、聖暉）接棒；"
            "2025-08 無人機他當半山腰隔日沖，漲一倍見好就收。"
            "2025-12-17 主戰場改記憶體，PCB 當做出貨／做頭先撤。"
            "2026-04-16 PCB 又起，但長線龍頭等大盤大跌才介入。"
            "2026-07-06 功率接棒被動元件；AI 龍頭買跌不買漲，台光電倒了就是 AI 時代結束。"
            "7/29 大盤窗口對上抄底。2026-09-10：散熱當下最為強勢；光通訊看聯亞風向球；"
            "PCB 長抱台光電／金像電，上游材料首選富喬。9/11 把聯亞＋建築兩檔收成下一個台光電——建築沒點名代號。"
            "看一檔先看這族龍頭攻還是休息。領頭羊做頭，同族其他檔先找賣點。不是買訊。"
        ),
    },
    {
        "id": "family911",
        "keys": re.compile(
            r"(下一個台光電|護城河|抱到.?2027|聯亞|建築|富喬|奇鋐|健策|台光電|"
            r"還能抱|要不要賣|那檔還)"
        ),
        "a": (
            "9/11～9/12 樓下是同一晚的產業收斂，不是四則無關留言。"
            "台光電＝純 AI 護城河最高，鏈從 2025-11-21 產業趨勢＋龍頭、4/16 可抱到明年、7/6 買跌、"
            "7/22 地位僅次台積電、7/23 高速 CCL 世界第一、7/29～30 對上大盤 A 低（官方 2383 低 3930）。"
            "聯亞＝下一個龍頭位（矽光子風向球），不是再找一檔 CCL。"
            "7/24 樓下曾因壓力區爆大量叫矽光子全面出清；9/9 破線洗盤鎖漲停、9/10 才明講龍頭不見得最會漲但是風向球——這條要對跟錯一起留。"
            "建築兩檔沒點名；公開文廠務鏈是漢唐、聖暉（帆宣也曾並提），社團 6/16 漢唐包含聖暉當時轉弱。"
            "富喬＝CCL 之下的上游材料，9/9 技術面與材料分析對上才首選。"
            "奇鋐、健策＝散熱次族群第一批創新高（9/10 散熱最強；3017 9/7 高 3595，3653 9/1 高 6095）。"
            "抱到 2027 第五波結束＝產業期限，第五波他改口過，不准編起點。不是買訊。"
        ),
    },
    {
        "id": "timing",
        "keys": re.compile(
            r"(夜盤先|9:30|黑手|C-2|C-3|細微波四步|何時.*進|什麼時候.*看)"
        ),
        "a": (
            "時間軸也是一條：轉折幾乎都先夜盤、隔日才日盤；夜盤沒過下降壓＝還可能擴延。"
            "細微波四步（2026-04-07）把 5／9 段數完，升／降軌道破壞才算轉折。"
            "9/11：15 分走 5 段＋下降軌破壞＝初步止訊號 → 穿越 46506 才確認末端 → 9:30 第二段黑手表態"
            "（夜盤時間軸，2025-04-24 已寫 9:30 以後的夜盤；不要先當日盤開盤）。"
            "C-2 轉 C-3 他自己說出現才發文，沒發文不要替他升浪。"
            "費半組合 K 至少三段反彈、取其最穩定，不是全部用波浪。庫沒 15 分就不數段。"
            "主音（波浪）他自己說不是 100%。確認低點還要疊台積電量價、費半先行、夜盤是否過壓；"
            "單講趨勢向上／初步止訊號／右肩有守不夠。某金融商品沒點名，不准寫死。"
        ),
    },
    {
        "id": "vol_club",
        "keys": re.compile(r"(量先價行|爆大量|價穩量縮|社團.*買點|介入買點)"),
        "a": (
            "量先價行是社團 2025-06-05 寫成可重複的買點句（3167 當日高 104.5 低 96.8，與庫完全同），"
            "公開文後來反覆用同一套：爆大量日高當壓、低當撐，價穩量縮才進，否則放棄。"
            "它排在產業趨勢和龍頭之後，不是單獨掃全市場爆量。半山腰只隔日沖。"
            "社團點名停損價不上話筒；公開能講約 7～10%。不是買訊。"
        ),
    },
    {
        "id": "retract",
        "keys": re.compile(r"(改口|看錯|認錯|對跟錯|不破\s*40000|今天最低|及時修正|他改了|講錯)"),
        "a": (
            "改口是方法，不是瑕疵。對跟錯要一起留。"
            "2024-06-12 公開認錯波浪高點，主因是台積電走出延伸浪。"
            "2025-03 估破 22000 偏高，真正深跌 3/31 低 20696。"
            "2025-06 用日 K 講 CCL／勤誠量價背離當波段頂，後來都還大漲；真正改口做頭是 8/4 與 12/17。"
            "2025-06-10 說台光電型態滿足不要再介入＝早了，6～8 月高到 1345。"
            "2025-12-03 不破軌才談第五波，12-15 判定那組失敗做頭。"
            "2026-07-02 最樂觀第五波兩次擴延，7/07 說沒了改 A-c；7/16「不破 40000」、7/24「今天最低」→ 7/29 加權低 39385。"
            "2026-07-24 矽光子聯亞到壓力區爆大量，下星期全面出清；9/9 改口破線洗盤鎖漲停當風向球。"
            "2026-09-09 聯亞「鎖漲停」：官方高確實到漲停 3150，收 2850 打開，不是一字。"
            "9/11：勝負在及時修正不是預測。不是買訊。"
        ),
    },
    {
        "id": "leader",
        "keys": re.compile(
            r"(跟漲|風向球|龍頭怎麼|誰先過前高|次族群第一名|領頭|"
            r"金像電|勤誠|廣達)"
        ),
        "a": (
            "跟漲先看這族龍頭現在攻還是休息，不是看誰當天漲最多。"
            "光通訊／矽光子風向球＝聯亞（7/24 出清過，9/9 又當風向球，跟的是位不是單則金句）；"
            "散熱＝奇鋐，健策同列第一批創新高；"
            "PCB／CCL＝台光電，金像電常先過前高（2025-06-30 他點過），上游材料首選富喬；"
            "廠務／無塵室＝漢唐，社團內化其實包含聖暉；記憶體指標＝南亞科，但 2026-05 他說不宜當長線主線。"
            "公開文共現最多：台光電＋奇鋐、台光電＋金像電、勤誠＋奇鋐、健策＋奇鋐——同族一起判，不是四檔各走各的。"
            "領頭羊做頭，同族其他檔先找賣點。不是買訊。"
        ),
    },
    {
        "id": "degree",
        "keys": re.compile(r"(位階怎麼變|波浪位階|失敗的第五|擴延|雙重回檔|位階時間)"),
        "a": (
            "大盤位階是一條改口鏈，不要釘死一個字母。"
            "2024-05-30：樂觀第三浪延伸 vs 失敗第五波，機率因跳空拉到五成。"
            "2025-12-03：台積電 9/3～11/24 低或加權 9/3～11/21 低連線不破才談第五波；12-15 1-4 重疊、那組失敗做頭。"
            "2026-07-02：最樂觀雙重回檔（第五波擴延兩次），綠升軌不能破、風向球旺矽；7/07 這條沒了，改 A-c。"
            "7/29 低 39385 當大 A。2026-09 高檔震盪／右肩／位階二，過 47578 只是維持近波前高，不是升成大 3。"
            "9/11「抱到 2027 第五波結束」是產業期限，沒標這級第 1 浪起點。不准編。不是買訊。"
        ),
    },
    {
        "id": "verify",
        "keys": re.compile(
            r"(開口.*對|接棒.*對|有沒有對|對得上|20\s*日|回測對錯|核對開口)"
        ),
        "a": (
            "開口那天對官方日 K，對跟錯都留。"
            "2025-04-25 老 AI 最整齊：廣達／台光電之後 40 日約 +23%／+52%。"
            "2025-12-17 專心記憶體、PCB 撤：群聯／南亞科 20 日約 +73%／+52%，台光電同期只 +8.7%（相對弱這句對）。"
            "2026-04-22 IC 設計主線：聯發科 20 日約 +86%。2026-07-21 奇鋐 20 日約 +31%。"
            "2025-06 那批 CCL／勤誠「背離確認高點」用日 K 對都還在波段中段，不是終點。"
            "公開目標／支撐表：台光電後續對 23、未到或跌破 20；奇鋐後續對 19、未到或跌破 7。"
            "單條爆量視窗一換就換日。不是買訊。"
        ),
    },
    {
        "id": "nights",
        "keys": re.compile(
            r"(同一晚|那晚|那一夜|這幾晚|事件夜|同日還|"
            r"9/9|9/10|9/11|7/24|7/29|12/17|4/16)"
        ),
        "a": (
            "他不是一天一篇互不相關。同一晚的主文＋樓下是同一條判斷。"
            "9/9～9/12：破線洗盤→聯亞風向球＋富喬上游＋右肩 45839＋15 分 5 段穿越 46506"
            "＋下一個台光電＋奇鋐健策第一批創新高。"
            "7/29～7/30：大 A 低 39385 抄底窗口，台光電官方低 3930；記憶體不要和 F4 碰瓷。"
            "7/24 同一晚：長線龍頭勿調節，卻叫矽光子聯亞全面出清——9/9 又把聯亞當風向球。"
            "12/15～12/17：第五波失敗做頭，主戰場改記憶體、PCB 先撤。"
            "4/16 可抱到明年名單等大盤大跌，7/6 買跌不買漲接到 7/29 窗口。"
            "不要拆成單則金句。不是買訊。"
        ),
    },
    {
        "id": "aux",
        "keys": re.compile(
            r"(有緣人|沒講出來|沒有講完|輔助判|多重比對|某金融商品|"
            r"波浪沒辦法|100%\s*確認|主音|除了波浪)"
        ),
        "a": (
            "他明講的主音是細微波／軌道／1-4 重疊，但 2026-07-31 自己寫波浪沒辦法 100% 確認 A 波低。"
            "真正讓他 100% 的是台積電＋某金融商品的量價結構；那則他說不會刪、希望有緣人解讀。"
            "某金融商品沒點名，不准寫死。"
            "沒講完、可從原文交叉還原的輔助：台積電量價決勝（低檔爆量收撐、假跌破站回、量縮上漲過壓；"
            "大盤沒爆月最大量時用台積電當日最大量當籌碼代理）；費半／那指先行；夜盤是否先過下降壓；"
            "第一次碰到次級四＋下跌走 5；風向球／長線龍頭是否先修正完成。"
            "濾網：新聞變多、半山腰、初步止訊號、無法判斷 5 或 9、右肩有守＝趨勢仍向上的整理不是新底。"
            "確認常常晚 1～2 日。不是買訊。"
        ),
    },
]


def _bar(conn: sqlite3.Connection, sid: str, ymd: str) -> str:
    key = _ymd(ymd)
    if not key or not sid:
        return ""
    try:
        if sid == "TWII":
            row = conn.execute(
                "SELECT high, low, close FROM index_daily WHERE symbol='TWII' AND date=?",
                (key,),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT high, low, close FROM daily_quotes WHERE stock_id=? AND date=?",
                (sid, key),
            ).fetchone()
    except sqlite3.Error:
        return ""
    if not row:
        return ""
    return f"{key} 高{_px(row[0])} 低{_px(row[1])} 收{_px(row[2])}"


def _open_db(db_path: str) -> Optional[sqlite3.Connection]:
    if not db_path or not os.path.isfile(db_path):
        return None
    try:
        conn = sqlite3.connect(db_path, timeout=30.0)
        return conn
    except sqlite3.Error:
        return None


def _stance(text: str) -> str:
    try:
        from biaoke_fuse import stance_of

        return stance_of(text) or ""
    except Exception:
        return ""


def build_weave_index(db_path: Optional[str] = None) -> Dict[str, Any]:
    from biaoke_net import family_ids
    from biaoke_why import _NAME_SID, _iter_rows, named_stocks

    if not db_path:
        try:
            from config import get_db_path

            cand = get_db_path()
            db_path = cand if cand and os.path.isfile(cand) else ""
        except Exception:
            db_path = ""
    conn = _open_db(db_path or "")
    rows = _iter_rows(db_path or None)
    by_name: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    method_names: Dict[str, Counter] = defaultdict(Counter)
    day_names: Dict[str, set] = defaultdict(set)
    for p in rows:
        text = str(p.get("text") or "")
        names = named_stocks(text, p.get("tags"), limit=8)
        st = _stance(text)
        rec = {
            "date": str(p.get("date") or ""),
            "kind": "reply" if p.get("kind") == "reply" else "post",
            "club": bool(p.get("club")),
            "stance": st,
            "mark": bool(_MARK.search(text)),
            "flip": bool(_FLIP.search(text)),
            "id": str(p.get("id") or ""),
            "clip": _clip(text, 72),
            "tags": [str(t) for t in (p.get("tags") or [])],
            "head": text[:80],
        }
        day = str(rec["date"] or "")[:10]
        for n in names:
            in_body = n in text
            rec_n = dict(rec)
            rec_n["in_body"] = in_body
            rec_n["subject"] = _is_subject(text, n)
            rec_n["clip"] = _clip_about(text, n, 72) if in_body else rec["clip"]
            rec_n["score"] = 0
            if rec_n["subject"]:
                rec_n["score"] += 10
            elif n in rec["head"]:
                rec_n["score"] += 6
            elif in_body:
                rec_n["score"] += 4
            elif n in rec["tags"] and rec["mark"]:
                rec_n["score"] += 2
            elif n in rec["tags"]:
                rec_n["score"] += 1
            if rec["mark"]:
                rec_n["score"] += 3
            if rec["kind"] == "post":
                rec_n["score"] += 1
            if rec["club"]:
                rec_n["score"] -= 8
            by_name[n].append(rec_n)
            if in_body and not rec["club"] and day:
                day_names[day].add(n)
        if not rec["club"]:
            for fam in family_ids(text):
                for n in names[:4]:
                    method_names[fam][n] += 1
    claim_note: Dict[str, str] = {}
    if conn:
        try:
            for name, n, ok, bad in conn.execute(
                """
                SELECT stock_name,
                       SUM(CASE WHEN hit NOT LIKE '庫沒%' AND hit!='' THEN 1 ELSE 0 END),
                       SUM(CASE WHEN hit LIKE '%後續高碰到%' OR hit LIKE '%後續低有守%' THEN 1 ELSE 0 END),
                       SUM(CASE WHEN hit LIKE '%後續高還沒到%' OR hit LIKE '%後續低跌破%' THEN 1 ELSE 0 END)
                FROM biaoke_claims
                WHERE club=0 AND stock_name!=''
                GROUP BY stock_name
                """
            ):
                if int(n or 0) < 3:
                    continue
                claim_note[str(name)] = (
                    f"公開目標／撐壓 {int(n)} 則，後續對 {int(ok or 0)}、未到或跌破 {int(bad or 0)}。"
                )
        except sqlite3.Error:
            claim_note = {}
    siblings = {
        "台光電": ["金像電", "奇鋐", "富喬", "聯亞"],
        "金像電": ["台光電", "富喬"],
        "富喬": ["台光電", "金像電"],
        "聯亞": ["台光電", "奇鋐", "光聖"],
        "奇鋐": ["健策", "台光電", "勤誠"],
        "健策": ["奇鋐"],
        "勤誠": ["奇鋐", "台光電"],
        "漢唐": ["聖暉", "帆宣"],
        "聖暉": ["漢唐"],
        "南亞科": ["群聯", "華邦電"],
        "廣達": ["台光電", "鴻海"],
        "旺矽": ["穎崴", "穎葳"],
        "穎崴": ["旺矽"],
        "穎葳": ["旺矽"],
    }
    stocks: Dict[str, Dict[str, Any]] = {}
    for name, hits in by_name.items():
        pub = [h for h in hits if not h["club"]]
        body_hits = [h for h in (pub or hits) if h.get("in_body")]
        subj = [h for h in body_hits if h.get("subject")]
        if len(body_hits) < 2:
            continue
        use = subj or body_hits
        first = use[0]
        last = body_hits[-1]
        flips = [h for h in body_hits if h.get("flip")]
        mid = flips[-1] if flips else (use[len(use) // 2] if len(use) >= 3 else None)
        picked: List[Dict[str, Any]] = []
        for h in (first, mid, last):
            if not h:
                continue
            if h["id"] in {x["id"] for x in picked}:
                continue
            picked.append(h)
        sid = _NAME_SID.get(name) or ""
        k_first = _bar(conn, sid, first["date"]) if conn and sid else ""
        k_last = _bar(conn, sid, last["date"]) if conn and sid else ""
        n_pub = len([h for h in pub if h.get("in_body")]) or len(pub)
        bits = [
            f"{name}{(' '+sid) if sid else ''}：公開 {n_pub} 則"
            f"{'＋社團'+str(len(hits)-len(pub)) if len(hits)>len(pub) else ''}"
            f" {first['date']}→{last['date']}。"
        ]
        for h in picked:
            tag = "社團內化" if h["club"] else h["kind"]
            st = h["stance"] or ""
            bits.append(f"{h['date']}{tag}{st}：{_clip(h['clip'], 48)}")
        if k_first:
            bits.append("最早當日官方K " + k_first + "。")
        if k_last and k_last != k_first:
            bits.append("最近當日官方K " + k_last + "。")
        if claim_note.get(name):
            bits.append(claim_note[name])
        sib = [s for s in siblings.get(name) or [] if s in by_name]
        if sib:
            bits.append("同族一起判：" + "、".join(sib[:4]) + "。")
        others = [
            s
            for s in sorted(day_names.get(str(last["date"] or "")[:10], set()) - {name})
        ]
        if others:
            bits.append("最近同日還點：" + "、".join(others[:5]) + "。")
        a = "".join(x if x.endswith("。") else x + "。" for x in bits)
        stocks[name] = {
            "name": name,
            "sid": sid,
            "n": n_pub,
            "n_club": len(hits) - len(pub),
            "first": first["date"],
            "last": last["date"],
            "a": _clip(a, 560),
        }
    methods: Dict[str, str] = {}
    labels = {
        "volfirst": "量先價行",
        "micro": "細微波",
        "leader": "次族群第一名",
        "rail": "升／降軌道",
        "wash": "洗盤／破線翻",
        "sox": "費半先行",
        "shoulder": "右肩",
        "buy3": "三個買點",
    }
    for fam, counter in method_names.items():
        top = "、".join(n for n, _ in counter.most_common(6))
        title = labels.get(fam, fam)
        methods[fam] = f"{title}在公開文裡常跟 {top} 一起出現；方法要帶著名義例，不要空講。"
    if conn:
        conn.close()
    return {
        "source": "1709+club-weave",
        "n_stocks": len(stocks),
        "n_masters": len(_MASTERS),
        "stocks": stocks,
        "methods": methods,
        "masters": [{"id": m["id"], "a": m["a"]} for m in _MASTERS],
    }


def save_weave_index(blob: Optional[Dict[str, Any]] = None, path: str = "") -> str:
    dest = path or WEAVE_GZ
    parent = os.path.dirname(dest)
    if parent:
        os.makedirs(parent, exist_ok=True)
    payload = blob or build_weave_index()
    tmp = dest + ".tmp"
    with gzip.open(tmp, "wt", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, dest)
    load_weave.cache_clear()
    return dest


@lru_cache(maxsize=1)
def load_weave() -> Dict[str, Any]:
    if os.path.isfile(WEAVE_GZ):
        with gzip.open(WEAVE_GZ, "rt", encoding="utf-8") as fh:
            blob = json.load(fh) or {}
        if int(blob.get("n_stocks") or 0) >= 20:
            return blob
    return build_weave_index()


def is_weave_query(ask: str) -> bool:
    return bool(_WEAVE_ASK.search(ask or ""))


def weave_lookup(ask: str, *, limit: int = 3) -> str:
    q = (ask or "").strip()
    if not q:
        return ""
    bits: List[str] = []
    for m in _MASTERS:
        if m["keys"].search(q):
            bits.append(m["a"])
        if len(bits) >= 2:
            break
    if is_weave_query(q):
        prefer = (
            ("nights", "rotate", "index")
            if re.search(r"(那晚|同一晚|這幾晚|事件夜)", q)
            else ("rotate", "index")
        )
        for m in _MASTERS:
            if m["id"] in prefer and m["a"] not in bits:
                bits.append(m["a"])
            if len(bits) >= 3:
                break
    blob = load_weave()
    stocks = blob.get("stocks") or {}
    try:
        from biaoke_why import named_stocks

        names = named_stocks(q, limit=6)
    except Exception:
        names = []
    for n in names:
        row = stocks.get(n)
        if row and row.get("a"):
            bits.append(str(row["a"]))
        if len(bits) >= limit:
            break
    if not bits and is_weave_query(q):
        bits.append(str(_MASTERS[0]["a"]))
        bits.append(str(_MASTERS[1]["a"]))
    # 方法族帶例
    if re.search(r"(量先價行|細微波|次族群|誰先過前高)", q):
        methods = blob.get("methods") or {}
        key = "volfirst" if "量先" in q else "micro" if "細微" in q else "leader"
        extra = methods.get(key) or ""
        if extra:
            bits.append(extra)
    out: List[str] = []
    seen = set()
    for b in bits:
        b = (b or "").strip()
        if not b or b in seen:
            continue
        seen.add(b)
        out.append(b)
        if len(out) >= limit:
            break
    return "\n".join(out)


def format_weave_notes(ask: str) -> str:
    body = weave_lookup(ask)
    if not body:
        return ""
    return "貫通 " + _clip(body.replace("\n", "／"), 1200)


def format_weave_html(ask: str) -> str:
    body = weave_lookup(ask)
    return html_escape(body) if body else ""


def weave_counts() -> Dict[str, int]:
    blob = load_weave()
    return {
        "n_stocks": int(blob.get("n_stocks") or 0),
        "n_masters": int(blob.get("n_masters") or 0),
        "n_methods": len(blob.get("methods") or {}),
    }


if __name__ == "__main__":
    dest = save_weave_index()
    print(dest, weave_counts())
    print(weave_lookup("把他全部貫通"))
