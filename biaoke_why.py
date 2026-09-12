# -*- coding: utf-8 -*-
"""飆客逐則自問自答：1709 主文＋樓中樓＋兩個社團。

問「他怎麼判斷的」時走判斷鏈，不准再念稿。社團只內化規則，不貼原文、不進 overlay。
點位對官方加權／台指期日 K；庫沒 15 分就不數段。不是買訊。
"""
from __future__ import annotations

import gzip
import json
import os
import re
import sqlite3
from functools import lru_cache
from typing import Any, Dict, List, Optional, Sequence, Tuple

from tg_layout import html_escape

_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs", "expert_notes", "飆客")
WHY_GZ = os.path.join(_DIR, "why_index.json.gz")

_NAME_SID = {
    "台光電": "2383",
    "聯亞": "3081",
    "富喬": "1815",
    "奇鋐": "3017",
    "健策": "3653",
    "漢唐": "2404",
    "聖暉": "5536",
    "帆宣": "6196",
    "亞翔": "6139",
    "台積電": "2330",
    "台達電": "2308",
    "旺矽": "6230",
    "穎崴": "6515",
    "穎葳": "6515",
    "金像電": "2368",
    "金居": "8358",
    "南亞科": "2408",
    "華邦電": "2344",
    "群聯": "8299",
    "廣達": "2382",
    "勤誠": "8210",
    "致茂": "3030",
    "聯發科": "2454",
    "創意": "3443",
    "光聖": "6442",
    "全新": "2455",
    "鴻海": "2317",
    "智原": "3035",
    "欣興": "3037",
    "台燿": "6274",
    "川湖": "2059",
    "國巨": "2327",
    "大立光": "3008",
    "原相": "3227",
    "萬潤": "6187",
    "汎銓": "6830",
    "ABF": "8046",
}
_NAMES = sorted(_NAME_SID.keys(), key=len, reverse=True)
_NAME_RE = re.compile("|".join(re.escape(n) for n in _NAMES))
_WAVE = re.compile(
    r"(細微波|波浪|第[一二三四五1-5]波|第[一二三四五1-5]浪|位階|"
    r"下降軌|下降壓|上升軌|1-4|１-４|C-2|C-3|A-c|B-a|abc|5段|9段|右肩)"
)
_INDUSTRY = re.compile(
    r"(產業趨勢|護城河|龍頭|次族群|長線主流|買跌不買漲|抱到|"
    r"PCB|CCL|散熱|光通|矽光子|記憶體|無塵室|廠務|建築)"
)
_VOLUME = re.compile(r"(量先價行|爆大量|價穩量縮|窒息量|破線洗盤|破線翻)")
_IDX = re.compile(r"(大盤|加權|台指|夜盤|費半|那指|細微波|右肩|觀盤)")
_STOCKISH = re.compile(r"(股票|持股|這檔|次族群|龍頭股)")
_FIFTEEN = re.compile(r"(15\s*分|十五分|細微波.*[59]\s*段|[59]\s*段)")
_TRACK = re.compile(r"(下降軌|下降壓|上升軌|軌道)")
_RETRACT = re.compile(r"(已經沒了|沒了|失敗|開始做頭|改口|更正)")
_FIFTH = re.compile(r"第五波")
_YEAR = re.compile(r"^(?:19|20)\d{2}$")
_NUM = re.compile(r"(?<![\d.])(\d{2,5}(?:\.\d+)?)(?![\d])")
_ALIEN = re.compile(r"(模糊的精確|安全邊際|淨利息|估值位階|沉澱帶|因果鏈|和碩|仁寶)")
_WHY_ASK = re.compile(
    r"(怎麼來|怎麼判|如何知|為何|為什麼|起頭|哪兩檔|潛力|"
    r"走了?\s*5\s*段|下降軌|位階二|護城河|抱到|46506|47578|45839|48218|"
    r"建築|富喬|聯亞|奇鋐|健策|第五波|9:30|黑手|C-2|C-3|"
    r"貫通|串聯|融會|輪動|怎麼連|台光電)"
)


def _px(val: Any) -> str:
    try:
        n = float(val)
    except (TypeError, ValueError):
        return ""
    if abs(n - round(n)) < 1e-6:
        return str(int(round(n)))
    s = f"{n:.2f}".rstrip("0").rstrip(".")
    return s


def _ymd(raw: Any) -> str:
    t = str(raw or "").replace("-", "")[:8]
    if len(t) == 8 and t.isdigit():
        return t
    s = str(raw or "").strip()
    if len(s) == 10 and s[4] == "-" and s[7] == "-":
        return s.replace("-", "")
    return ""


def _dash(ymd: str) -> str:
    t = _ymd(ymd)
    return f"{t[:4]}-{t[4:6]}-{t[6:8]}" if len(t) == 8 else str(ymd or "")


def _clip(text: str, n: int) -> str:
    s = re.sub(r"\s+", " ", str(text or "")).strip()
    return s if len(s) <= n else s[: n - 1] + "…"


# 手寫判斷鏈：問為什麼時先走這裡，不是再貼原文。
_TOPICS: List[Dict[str, Any]] = [
    {
        "id": "46506",
        "keys": re.compile(r"(46506|穿越.?465|今晚.*末端|確認.*末端)"),
        "q": "46506 怎麼來？",
        "a": (
            "2026-09-11 17:49 主文：確認短線修正末端，今晚夜盤至少穿越 46506。"
            "官方台指期 20260910 日盤（regular）低剛好 46506，不是加權 9/10 低 46573。"
            "這是前一日台指日盤低當確認水平。9/11 夜盤官方高 46663、收 46576，已過這水平。"
            "同則「15 分細微波走 5 段、下降軌已破壞」是他夜盤 15 分圖上數的；庫沒 15 分，不數段、不假裝畫過那條軌。"
        ),
    },
    {
        "id": "47578",
        "keys": re.compile(r"(47578|過前波高|下周.*右肩|高有過前高)"),
        "q": "47578 怎麼來？下周過它才維持右肩？",
        "a": (
            "2026-09-12 10:34：下周要過前波高點 47578，才能維持高有過前高做右肩，還在波浪位階二。"
            "官方加權 20260908 高 47578.24。台指期日盤 9/8 高 47593。所以「前波高」＝9/8 這波高，不是亂編。"
            "更大一級前高是加權 20260623 高 48218.87（他 9/10 說下波起漲至少測 48218）。"
            "過 47578＝近波右肩還在；還沒把計數升成大 3。位階不講死。"
        ),
    },
    {
        "id": "45839",
        "keys": re.compile(r"(45839|9/3.*低|守住.*低|低不破前低)"),
        "q": "45839 怎麼來？",
        "a": (
            "2026-09-11 08:43：未來 2～3 日觀盤重點是 9/3 低 45839 有沒有守。"
            "官方加權 20260903 低 45839.36。有守＝右肩還是高有過前高、低不破前低。"
            "9/11 加權低 45942 收 46185，當日沒破 45839；這不是保證後面不破。"
        ),
    },
    {
        "id": "48218",
        "keys": re.compile(r"(48218|下波起漲|測.?482)"),
        "q": "48218 怎麼來？",
        "a": (
            "2026-09-10 主文：細微波 9/8 起 abc、當天 c 末端；下波起漲目標至少測 48218。"
            "官方加權 20260623 高 48218.87。他 7/23 畫 60 分下降壓也是從這高連下來。"
            "47578 是 9/8 近波高；48218 是更大一級前高。兩檔不要混。"
        ),
    },
    {
        "id": "fifth",
        "keys": re.compile(r"(第五波|起頭|2027.*第五|第五波.*結束|第五波.*起)"),
        "q": "台光電抱到 2027 第五波結束——第五波起頭在哪？沒起頭怎麼結束？",
        "a": (
            "他改口過，不准釘死一個起點。2025-12-03：台積電 9/3 低連 11/24 低（官方 2330 低 1145／1375），"
            "或加權 9/3 低連 11/21 低（官方 11/21 低 26396），不破才談那組第五波。"
            "2025-12-15：1-4 重疊、軌道幾乎破壞，那組末升第五波他判定失敗、開始做頭。"
            "2026-07-02：最樂觀＝第五波兩次擴延，綠上升軌不能破，風向球旺矽。"
            "2026-07-07：這條樂觀第五波沒了，改 A-c，目標破 44454 往 42206。"
            "2026-09-11 23:15「抱到 2027 年大盤第五波結束」是更大一級、產業趨勢還在才講得出口；"
            "那則沒標這級第 1 浪起點。對得上的是：12 月那組與 7 月擴延都被他否決；"
            "7/29 加權低 39385 可視為大 A；現在高檔震盪／右肩／位階二＝還沒把計數升成大 3。"
            "沒起頭就講結束＝產業趨勢期限，不是已經數到第五波推動段。不准編一個起點。"
        ),
    },
    {
        "id": "emc",
        "keys": re.compile(
            r"(台光電.*護城河|護城河.*台光電|抱到.?2027|抱到明年|7\s*月抄底|"
            r"為何.{0,12}篤定|為什麼.{0,12}篤定|買跌不買漲)"
        ),
        "q": "台光電護城河最高、可抱到 2027——怎麼判？",
        "a": (
            "不是把波浪套在 2383。鏈是產業趨勢＋龍頭＋大盤大跌窗口。"
            "2025-11-21：賺錢永遠產業趨勢＋該產業龍頭；技術分析主要逃股災或賺價差。"
            "2026-04-16：台積電、台達電、台光電、旺矽、穎崴、奇鋐＝可抱到明年，要在大盤大跌時介入。"
            "2026-07-06：AI 長線龍頭買跌不買漲；台光電倒了就是 AI 時代結束。"
            "2026-07-22：PCB 是 AI 供應鏈最重要，台光電地位僅次台積電。"
            "2026-07-23：AI 高速 CCL 世界第一。"
            "2026-07-29／30：大盤抄底窗口對上加權 7/29 低 39385；台光電官方日 K 7/29 低 3985 收 4100，7/30 低 3930 收 4315。"
            "2026-07-30：F4 有護城河高毛利。9/11 是這條鏈收斂，不是新發明。不是買訊。"
        ),
    },
    {
        "id": "lianya",
        "keys": re.compile(r"(聯亞|下一個台光電|矽光子最重要|風向球)"),
        "q": "下一個台光電為什麼是聯亞？",
        "a": (
            "不是再找一檔 CCL，是下一個有護城河的產業龍頭位。"
            "2026-09-10 樓下：矽光子最重要一檔就是聯亞；龍頭不見得最會漲，但是風向球。"
            "光通訊跟漲先看聯亞，同他看散熱一定看奇鋐、健策。9/9 聯亞破線洗盤後鎖漲停，他當龍頭確認。"
            "9/11 才把聯亞收成「下一個台光電」。沒寫聯亞目標價就不准編。"
        ),
    },
    {
        "id": "build",
        "keys": re.compile(r"(建築兩檔|建築|哪兩檔|漢唐|聖暉|無塵室|廠務)"),
        "q": "建築兩檔是哪兩檔？",
        "a": (
            "2026-09-11 沒點名代號，不准假裝已點名。"
            "公開文裡他常把漢唐 2404、聖暉 5536 當台積電廠務／無塵室指標"
            "（2025-06 漢唐；2025-08 漢唐、帆宣、聖暉；2025-08-26 指標股是漢唐及聖暉）。"
            "社團 2026-06-16 內化：漢唐其實包含聖暉，當時轉弱先不要碰——規則可內化，原文不上話筒。"
            "9/11 的「建築兩檔」最像這條廠務鏈收成兩檔，但沒寫死漢唐＋聖暉。帆宣也曾並提。沒點名就明講沒點名。"
        ),
    },
    {
        "id": "fuqiao",
        "keys": re.compile(r"(富喬|上游材料|1815)"),
        "q": "富喬也很有潛力——如何知道？",
        "a": (
            "不是忽然喊。2026-09-09 樓下：請 AI 分析 PCB 上游材料，答案和他用技術分析一樣，首選富喬。"
            "2026-09-10 主文：PCB 除次族群龍頭 CCL 台光電、高階 PCB 金像電可長抱外，"
            "上游材料關鍵供應商尤其富喬應該是首選。9/11 才說也很有潛力。"
            "判斷＝CCL 龍頭之下的次族群＋技術面與產業材料分析對上。官方 1815 9/9 高 135 低 126 收 126。"
        ),
    },
    {
        "id": "heat",
        "keys": re.compile(r"(奇鋐|健策|第一批創新高|長線主流|散熱.*最強)"),
        "q": "奇鋐、健策為什麼是第一批創新高的長線主流？",
        "a": (
            "方法是次族群第一名、誰先過前高，不是事後看新聞。"
            "2026-09-10：目前長線主流股族群最為強勢＝散熱。7/21 他說過散熱奇鋐已修正完成。"
            "2026-04-16 奇鋐已在可抱到明年的長線龍頭名單。9/12 00:36：因為也是第一批創新高的長線主流股。"
            "官方近高：奇鋐 3017 在 20260907 高 3595；健策 3653 在 20260901 高 6095。"
            "第一批創新高＝這套領頭羊規則。不是買訊。"
        ),
    },
    {
        "id": "five_seg",
        "keys": re.compile(r"(走了?\s*5\s*段|五段|細微波.*5|完整結構)"),
        "q": "夜盤 15 分細微波走 5 段——怎麼看出五段？",
        "a": (
            "方法在 2026-04-07 細微波四步：認識調整型態 → 拆線 → 完整結構出現（5 或 9 段）後消去不符合的"
            " → 升／降軌道破壞才算轉折。工具＝台指期 15＋60＋夜盤連續盤。"
            "9/11 17:49 是他夜盤 15 分圖上數完 5 段。庫沒 15 分 K，不能假裝數過這則的段。"
            "同則下降軌破壞＝四步第 4 步的初步止訊號，還要穿越 46506 才談確認末端。"
        ),
    },
    {
        "id": "downtrend",
        "keys": re.compile(r"(下降軌|下降壓|軌道.*破壞|怎麼畫)"),
        "q": "下降軌破壞——軌道在哪、怎麼畫？",
        "a": (
            "軌道＝圖上連點，不是均線。下降壓／下降軌＝同一次級兩個更低的高連起來；"
            "上升軌＝同一次級浪 2 低連浪 4 低。"
            "9/11 17:49：夜盤 15 分下降軌道已破壞＝初步止訊號。22:41：夜盤已破夜盤 60 分下降壓、在回測。"
            "庫沒 15 分就不能假裝畫過圖上那條線。60 分下降壓他公開過從 48218 連下來（7/23）。"
            "有畫才知道被破壞——沒附圖、沒 15 分就只准講方法，不准發明連哪兩根。"
        ),
    },
    {
        "id": "degree2",
        "keys": re.compile(r"(位階二|波浪位階二|還是在波浪)"),
        "q": "還在波浪位階二——怎麼判？",
        "a": (
            "跟 9/10「9/8 起 abc、當天 c 末端」、9/11「細微波走 5 段」、"
            "9/12「過 47578 才維持右肩」同一組。"
            "他沒把計數升成大 3；右肩還在整理。位階不講死：可能先當 A，同一晚可並存多標籤，用點數一驗再驗。"
            "過 47578 只是維持高有過前高，不是自動升浪。"
        ),
    },
    {
        "id": "0930",
        "keys": re.compile(r"(9:30|9：30|黑手|第二段)"),
        "q": "9:30 第二段黑手表態——是日盤還是夜盤？",
        "a": (
            "2025-04-24 已寫「今日 9:30 以後的夜盤可看密切觀察」。"
            "2026-09-11 20:52：市場黑手真正會表態是在 9:30 的第二段，通常也是夜盤指數波動最大的時候。"
            "這則掛在夜盤主文樓下，最像夜盤 21:30 那一根／第二段，不要當成日盤 09:30 開盤就講死。"
            "沒 15 分連續盤就看不到他說的第二段。"
        ),
    },
    {
        "id": "c2c3",
        "keys": re.compile(r"(C-2|C-3|C2轉C3|轉 C-3)"),
        "q": "C-2 轉 C-3 他怎麼判？",
        "a": (
            "他自己說出現 C-2 轉 C-3 一定會發文通知。9/11 主文是細微波修正 5 段＋下降軌破壞＝初步止訊號，"
            "還沒升成 C-3。9/5 前後文有 B 波 vs C-2 逃命波的判斷框架：輕易越過壓力反而要小心是 C-2。"
            "沒看到他發文就不要替他升浪。"
        ),
    },
]


def named_stocks(text: str, tags: Optional[Sequence[Any]] = None, *, limit: int = 8) -> List[str]:
    found: List[str] = []
    for t in tags or []:
        s = str(t or "").strip()
        if s in _NAME_SID and s not in found:
            found.append(s)
    blob = text or ""
    for m in _NAME_RE.finditer(blob):
        s = m.group(0)
        if s not in found:
            found.append(s)
        if len(found) >= limit:
            break
    return found[:limit]


def _scope(text: str, stocks: Sequence[str], levels: Sequence[Any]) -> str:
    blob = text or ""
    has_idx = bool(_IDX.search(blob) or levels)
    has_stk = bool(stocks) or bool(_STOCKISH.search(blob))
    if has_idx and has_stk:
        return "mix"
    if has_idx:
        return "index"
    if has_stk:
        return "stock"
    return "talk"


def _family(text: str) -> str:
    blob = text or ""
    bits: List[str] = []
    if _INDUSTRY.search(blob):
        bits.append("industry")
    if _WAVE.search(blob):
        bits.append("wave")
    if _VOLUME.search(blob):
        bits.append("volume")
    if _TRACK.search(blob):
        bits.append("track")
    return "+".join(bits) or "other"


class _Ohlc:
    def __init__(self, db_path: str = "") -> None:
        self.twii: List[Tuple[str, float, float, float]] = []
        self.tx: List[Tuple[str, str, float, float, float]] = []
        self.stock: Dict[str, List[Tuple[str, float, float, float]]] = {}
        self._twii_lv: Dict[int, List[Tuple[str, str, float]]] = {}
        self._tx_lv: Dict[int, List[Tuple[str, str, str, float]]] = {}
        self._st_lv: Dict[str, Dict[int, List[Tuple[str, str, float]]]] = {}
        if db_path and os.path.isfile(db_path):
            self._load(db_path)

    def _load(self, db_path: str) -> None:
        conn = sqlite3.connect(db_path, timeout=30.0)
        try:
            for date, high, low, close in conn.execute(
                "SELECT date, high, low, close FROM index_daily WHERE symbol='TWII' "
                "AND high IS NOT NULL AND low IS NOT NULL"
            ):
                try:
                    h, l, c = float(high), float(low), float(close)
                except (TypeError, ValueError):
                    continue
                if h - l > 3500:
                    continue
                ymd = _ymd(date)
                if not ymd:
                    continue
                self.twii.append((ymd, h, l, c))
                for role, val in (("高", h), ("低", l), ("收", c)):
                    self._twii_lv.setdefault(int(round(val)), []).append((ymd, role, val))
            try:
                for date, session, high, low, close in conn.execute(
                    "SELECT date, session, high, low, close FROM futures_daily "
                    "WHERE high IS NOT NULL AND low IS NOT NULL"
                ):
                    try:
                        h, l, c = float(high), float(low), float(close)
                    except (TypeError, ValueError):
                        continue
                    ymd = _ymd(date)
                    if not ymd:
                        continue
                    sess = str(session or "regular")
                    self.tx.append((ymd, sess, h, l, c))
                    for role, val in (("高", h), ("低", l), ("收", c)):
                        self._tx_lv.setdefault(int(round(val)), []).append(
                            (ymd, sess, role, val)
                        )
            except sqlite3.Error:
                pass
            sids = sorted(set(_NAME_SID.values()))
            qmarks = ",".join("?" * len(sids))
            try:
                rows = conn.execute(
                    f"SELECT stock_id, date, high, low, close FROM daily_quotes "
                    f"WHERE stock_id IN ({qmarks}) AND high IS NOT NULL AND low IS NOT NULL",
                    sids,
                )
            except sqlite3.Error:
                rows = []
            for sid, date, high, low, close in rows:
                try:
                    h, l, c = float(high), float(low), float(close)
                except (TypeError, ValueError):
                    continue
                ymd = _ymd(date)
                if not ymd:
                    continue
                sid_s = str(sid)
                self.stock.setdefault(sid_s, []).append((ymd, h, l, c))
                bucket = self._st_lv.setdefault(sid_s, {})
                for role, val in (("高", h), ("低", l), ("收", c)):
                    bucket.setdefault(int(round(val)), []).append((ymd, role, val))
        finally:
            conn.close()

    def match_index(self, level: float, post_ymd: str, *, prefer: str = "") -> str:
        key = int(round(float(level)))
        post = _ymd(post_ymd)
        cands: List[Tuple[int, str]] = []
        want_tx = prefer in {"夜盤", "台指"}
        want_tw = prefer in {"加權", "大盤", "點位", ""}
        if want_tx or not want_tw:
            for delta in (0, 1, -1):
                for ymd, sess, role, val in self._tx_lv.get(key + delta, []):
                    dist = abs(int(ymd) - int(post or ymd))
                    label = "夜盤" if sess == "night" else "日盤"
                    cands.append(
                        (dist, f"台指期{label} { _dash(ymd) } {role} {_px(val)}")
                    )
        if want_tw or not cands:
            for delta in (0, 1, -1):
                for ymd, role, val in self._twii_lv.get(key + delta, []):
                    dist = abs(int(ymd) - int(post or ymd))
                    cands.append((dist, f"加權 {_dash(ymd)} {role} {_px(val)}"))
        if not cands:
            return ""
        cands.sort(key=lambda x: x[0])
        best_dist, best = cands[0]
        if best_dist > 40000:
            return ""
        return best

    def match_stock(self, sid: str, level: float, post_ymd: str) -> str:
        bucket = self._st_lv.get(str(sid) or "")
        if not bucket:
            return ""
        key = int(round(float(level)))
        post = _ymd(post_ymd)
        cands: List[Tuple[int, str]] = []
        for delta in (0, 1, -1):
            for ymd, role, val in bucket.get(key + delta, []):
                dist = abs(int(ymd) - int(post or ymd))
                if dist > 14:
                    continue
                cands.append((dist, f"{sid} {_dash(ymd)} {role} {_px(val)}"))
        if not cands:
            return ""
        cands.sort(key=lambda x: x[0])
        return cands[0][1]


def _iter_rows(db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    from biaoke_archive import load_bundled_club
    from biaoke_desk import load_corpus

    out: List[Dict[str, Any]] = []
    seen = set()
    blob = load_corpus(db_path if db_path else None)
    for p in blob.get("posts") or []:
        row = dict(p)
        row["club"] = False
        aid = str(row.get("id") or "")
        if not aid:
            continue
        seen.add(aid)
        out.append(row)
    club = load_bundled_club() or {}
    for p in club.get("posts") or []:
        row = dict(p)
        row["club"] = True
        aid = "club:" + str(row.get("id") or "")
        row["id"] = str(row.get("id") or "")
        if not row["id"] or aid in seen:
            continue
        seen.add(aid)
        out.append(row)
    out.sort(
        key=lambda p: (
            str(p.get("date") or ""),
            str(p.get("time") or ""),
            0 if p.get("kind") != "reply" else 1,
            str(p.get("id") or ""),
        )
    )
    return out


def _level_hits(text: str, date: str, ohlc: _Ohlc) -> List[str]:
    from biaoke_walk import extract_index_levels

    hits: List[str] = []
    for item in extract_index_levels(text):
        level = item.get("level")
        role = str(item.get("role") or "")
        try:
            n = float(level)
        except (TypeError, ValueError):
            continue
        note = ohlc.match_index(n, date, prefer=role)
        if note:
            hits.append(f"{_px(n)}→{note}")
        else:
            hits.append(f"{_px(n)}→庫內對不到官方高／低，不編")
    return hits[:6]


def _stock_level_hits(
    text: str, date: str, stocks: Sequence[str], ohlc: _Ohlc
) -> List[str]:
    blob = text or ""
    if not stocks:
        return []
    out: List[str] = []
    seen = set()
    for m in _NUM.finditer(blob):
        raw = m.group(1)
        whole = raw.split(".")[0]
        if _YEAR.fullmatch(whole) and "." not in raw:
            continue
        try:
            n = float(raw)
        except ValueError:
            continue
        if n >= 15000 or n < 5:
            continue
        ctx = blob[max(0, m.start() - 24) : m.end() + 12]
        sid = ""
        for name in stocks:
            if name in ctx:
                sid = _NAME_SID.get(name) or ""
                break
        if not sid and len(stocks) == 1:
            sid = _NAME_SID.get(stocks[0]) or ""
        if not sid:
            continue
        key = (sid, round(n, 2))
        if key in seen:
            continue
        seen.add(key)
        note = ohlc.match_stock(sid, n, date)
        if note:
            out.append(f"{_px(n)}→{note}")
        if len(out) >= 4:
            break
    return out


def _qa_for(
    row: Dict[str, Any],
    ohlc: _Ohlc,
    prev_fifth: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    text = str(row.get("text") or "")
    date = str(row.get("date") or "")
    kind = "樓下" if row.get("kind") == "reply" else "主文"
    club = bool(row.get("club"))
    stocks = named_stocks(text, row.get("tags"))
    levels = _level_hits(text, date, ohlc)
    stock_lv = _stock_level_hits(text, date, stocks, ohlc)
    scope = _scope(text, stocks, levels)
    family = _family(text)
    q = f"{date} {kind}這則在判什麼？點位從哪來？"
    bits: List[str] = []
    if club:
        bits.append("社團內化，不引用原文。")
    if scope == "index":
        bits.append("這則在判大盤／台指／夜盤。")
    elif scope == "stock":
        bits.append("這則在判個股／族群。")
    elif scope == "mix":
        bits.append("這則大盤與個股一起判。")
    else:
        bits.append("這則是方法或補充。")
    if family == "industry":
        bits.append("主軸是產業趨勢／龍頭，不是把波浪套個股。")
    elif family == "wave":
        bits.append("主軸是大盤波浪／細微波。")
    elif "industry" in family and "wave" in family:
        bits.append("產業趨勢與大盤波浪並用。")
    elif "volume" in family:
        bits.append("主軸是量價／洗盤。")
    elif "track" in family:
        bits.append("主軸是升／降軌道連點。")
    if stocks:
        bits.append("點名 " + "、".join(stocks[:6]) + "。")
    for h in levels:
        bits.append("點位 " + h + "。")
    for h in stock_lv:
        bits.append("個股價 " + h + "。")
    if _FIFTEEN.search(text):
        bits.append("庫沒 15 分，不數這則的段。")
    if _TRACK.search(text):
        bits.append("軌道＝同一次級兩個更低的高（降）或浪2低連浪4低（升），不是均線。沒附圖就不發明連哪兩根。")
    if club and re.search(r"量先價行|爆.*大量", text):
        bits.append("介入先看量先價行：爆大量日高當壓、低當撐，價穩量縮才進。")
    if club and "停損" in text:
        bits.append("社團有點名停損價，話筒不貼；公開能講停損大約 7～10%。")
    if _FIFTH.search(text) and prev_fifth is not None and _RETRACT.search(text):
        bits.append(f"相對 {prev_fifth.get('date')} 那則第五波規劃，這則是改口。")
    a = "".join(bits)
    if len(a) > 420:
        a = a[:419] + "…"
    return {
        "id": str(row.get("id") or ""),
        "date": date,
        "time": str(row.get("time") or ""),
        "kind": "reply" if row.get("kind") == "reply" else "post",
        "club": club,
        "q": q,
        "a": a,
        "scope": scope,
        "family": family,
        "stocks": stocks,
        "levels": levels[:6],
    }


def build_why_index(db_path: Optional[str] = None) -> Dict[str, Any]:
    if not db_path:
        try:
            from config import get_db_path

            cand = get_db_path()
            db_path = cand if cand and os.path.isfile(cand) else ""
        except Exception:
            db_path = ""
    ohlc = _Ohlc(db_path or "")
    rows = _iter_rows(db_path or None)
    cards: List[Dict[str, Any]] = []
    prev_fifth: Optional[Dict[str, Any]] = None
    for row in rows:
        card = _qa_for(row, ohlc, prev_fifth)
        cards.append(card)
        if _FIFTH.search(str(row.get("text") or "")):
            prev_fifth = row
    topics = [
        {"id": t["id"], "q": t["q"], "a": t["a"]} for t in _TOPICS
    ]
    n_pub = sum(1 for c in cards if not c.get("club") and c.get("kind") != "reply")
    n_club = sum(1 for c in cards if c.get("club") and c.get("kind") != "reply")
    n_rep = sum(1 for c in cards if c.get("kind") == "reply")
    return {
        "source": "1709+club+catchup-why",
        "n": n_pub,
        "n_club": n_club,
        "n_replies": n_rep,
        "n_cards": len(cards),
        "topics": topics,
        "cards": cards,
    }


def save_why_index(blob: Optional[Dict[str, Any]] = None, path: str = "") -> str:
    dest = path or WHY_GZ
    parent = os.path.dirname(dest)
    if parent:
        os.makedirs(parent, exist_ok=True)
    payload = blob or build_why_index()
    tmp = dest + ".tmp"
    with gzip.open(tmp, "wt", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, dest)
    load_why.cache_clear()
    return dest


@lru_cache(maxsize=1)
def load_why() -> Dict[str, Any]:
    if os.path.isfile(WHY_GZ):
        with gzip.open(WHY_GZ, "rt", encoding="utf-8") as fh:
            blob = json.load(fh) or {}
        if int(blob.get("n_cards") or 0) >= 1700:
            return blob
    return build_why_index()


def is_why_query(ask: str) -> bool:
    q = (ask or "").strip()
    if not q:
        return False
    if _ALIEN.search(q):
        return True
    return bool(_WHY_ASK.search(q))


def _topic_hits(ask: str) -> List[Dict[str, str]]:
    q = ask or ""
    out: List[Dict[str, str]] = []
    for t in _TOPICS:
        if t["keys"].search(q):
            out.append({"id": t["id"], "q": t["q"], "a": t["a"]})
    return out


def _card_hits(ask: str, blob: Dict[str, Any], *, limit: int = 3) -> List[Dict[str, Any]]:
    q = ask or ""
    tokens = [t for t in re.findall(r"[\u4e00-\u9fff]{2,}|[A-Za-z0-9.]{3,}", q) if t not in {"怎麼", "如何", "為什麼", "為何", "什麼"}]
    stocks = named_stocks(q)
    scored: List[Tuple[int, Dict[str, Any]]] = []
    for c in blob.get("cards") or []:
        if c.get("club"):
            blob_s = " ".join(
                [
                    str(c.get("date") or ""),
                    str(c.get("q") or ""),
                    str(c.get("a") or ""),
                    " ".join(c.get("stocks") or []),
                ]
            )
        else:
            blob_s = " ".join(
                [
                    str(c.get("date") or ""),
                    str(c.get("q") or ""),
                    str(c.get("a") or ""),
                    " ".join(c.get("stocks") or []),
                    " ".join(c.get("levels") or []),
                ]
            )
        score = 0
        for t in tokens:
            if t and t in blob_s:
                score += 2 if t.isdigit() or len(t) >= 3 else 1
        for s in stocks:
            if s in (c.get("stocks") or []) or s in blob_s:
                score += 3
        if score:
            scored.append((score, c))
    scored.sort(key=lambda x: (x[0], str(x[1].get("date") or "")), reverse=True)
    out: List[Dict[str, Any]] = []
    seen = set()
    for _s, c in scored:
        aid = str(c.get("id") or "")
        if aid in seen:
            continue
        seen.add(aid)
        out.append(c)
        if len(out) >= limit:
            break
    return out


def lookup(ask: str, *, limit: int = 4) -> str:
    q = (ask or "").strip()
    if not q:
        return ""
    if _ALIEN.search(q) and not re.search(r"(46506|47578|台光電|聯亞|細微波|飆客)", q):
        return "這不是飆客本人的聲音，不拿來當他的判斷。"
    bits: List[str] = []
    try:
        from biaoke_weave import weave_lookup

        woven = weave_lookup(q, limit=3)
        if woven:
            bits.extend(x for x in woven.split("\n") if x)
    except Exception:
        pass
    for t in _topic_hits(q):
        if t["a"] not in bits:
            bits.append(t["a"])
        if len(bits) >= 3:
            break
    blob = load_why()
    if len(bits) < 3:
        for c in _card_hits(q, blob, limit=limit):
            prefix = "社團內化：" if c.get("club") else f"{c.get('date') or ''} {c.get('kind') or ''}："
            line = _clip(prefix + str(c.get("a") or ""), 280)
            if line and line not in bits:
                bits.append(line)
            if len(bits) >= limit + 1:
                break
    return "\n".join(x for x in bits if x)


def format_why_html(ask: str) -> str:
    body = lookup(ask)
    if not body:
        return ""
    return html_escape(body)


def format_why_notes(ask: str, *, limit: int = 3) -> str:
    body = lookup(ask, limit=limit)
    if not body:
        return ""
    return "判斷鏈 " + _clip(body.replace("\n", "／"), 1400)


def why_counts() -> Dict[str, int]:
    blob = load_why()
    return {
        "n": int(blob.get("n") or 0),
        "n_club": int(blob.get("n_club") or 0),
        "n_replies": int(blob.get("n_replies") or 0),
        "n_cards": int(blob.get("n_cards") or 0),
        "n_topics": len(blob.get("topics") or []),
    }


if __name__ == "__main__":
    dest = save_why_index()
    c = why_counts()
    print(dest, c)
