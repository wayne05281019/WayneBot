# -*- coding: utf-8 -*-
"""飆大判斷方式：把公開文裡反覆出現的規則彙整成對話回答。

不是買訊、不進海選。社團 72 只內化規則，不引用社團網址。
三百／一百／三百是課綱（公開文對答、判斷問句、官方 K 盲測），不是 700 顆按鈕。
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

from tg_layout import html_escape

DISCLAIMER_LINE = (
    "⚠️ 這不是買訊。不是飆大本人；是把他公開文的思考在這邊彙整後回你。"
)

# 問句 → 彙整答案。社團規則寫成公開能講的句子，不貼社團連結。
_METHODS: List[Tuple[re.Pattern[str], str, str]] = [
    (
        re.compile(r"(融會貫通|三百.*一百|課綱|七百次|700.?次)"),
        "三百／一百／三百",
        "課綱是先融會 300 則公開文，再練 100 則判斷問句，再拿另外 300 則對官方日 K 回測。"
        "底圖是 Drive 1709 主文＋他自己的一／二層樓中樓。不進海選、不是買訊。"
        "問『融會貫通』時對話腦會帶本輪回測數字。",
    ),
    (
        re.compile(r"(細微波|四步|怎麼觀察|如何觀察|觀察方法)"),
        "細微波四步",
        "他自己 2026-04-07 寫的細微波四步：先認識調整型態 → 會拆線 → 完整結構出現後消去不符合的 → 升／降軌道破壞才算轉折。"
        "工具是台指期 15 分＋60 分＋夜盤連續盤，不是只看加權日 K。完整結構＝5 或 9 段。庫內沒 15 分就不數段。",
    ),
    (
        re.compile(r"(夜盤先|夜盤.*日盤|先於日盤)"),
        "夜盤先於日盤",
        "轉折他幾乎都先講夜盤，隔日才講日盤。夜盤沒過下降壓＝還可能擴延；夜盤有效穿刺他設的帶才比較像化解。",
    ),
    (
        re.compile(r"(1-4|１-４|一四重疊|1－4)"),
        "1-4 重疊",
        "1-4 重疊＝下跌趨勢化解。費半若出現 1-4 重疊，他當台股先行。這包沒費半 15 分，只看收盤是否不再破低，不編段數。",
    ),
    (
        re.compile(r"(費半|費城半導體|SOX|先行)"),
        "費半先行",
        "2026 他常用費半當台股先行。費半／那指還在逆風、夜盤再破，日盤先當擴延，不談止跌完成。",
    ),
    (
        re.compile(r"(台積電量價|多標籤|決勝|B-a-2|A-c-3|恐慌下殺|三種波浪)"),
        "台積電量價決勝",
        "同一晚可以並存多種波浪標籤。他 2026-07-16 夜盤寫過三種：B-a-2、A-c 擴延、A-c-3，"
        "用「不公開的台積電量價」選第一種九成。能從結果還原的只有：低檔爆大量＋收在撐上。"
        "這塊他稱不公開，這裡不發明公式。7/16「不破 40000」與 7/24「今天最低」後來都錯"
        "（7/29 低 39385），對跟錯一起留。",
    ),
    (
        re.compile(r"(洗盤|出貨|破線翻|破線洗盤)"),
        "洗盤還是出貨",
        "2024-07-08 樓中樓原文：整理完成起漲突然跌停＝洗盤；漲很多的飆股跌停＝出貨。"
        "破線翻＝跌破支撐當日站回（2023-12-14 小時線；2024-12-17 均豪跌破頸線隔日站回＝洗盤）。"
        "2025-08-21：要看到主力作價洗盤痕跡＝洗盤型態＋作量 K 棒；帶量突破要站上帶量高點。"
        "2026-03-06 南亞科洗盤痕跡明顯、群聯用型態。2026-09-08 聯亞、9/3 南亞科他當破線洗盤。"
        "不是買訊、不進海選。",
    ),
    (
        re.compile(r"(連三天|連三日|三日不破|三日之內|三日內站回|三日不回補|破三日低|假跌破)"),
        "連三天／三日不破",
        "字面「連三天不破點」公開 1709 對不到這六個字。近義是：假跌破三日之內必需重新站上"
        "（2024-04-16 雷科頸線）；跳空缺口三日不回補才算有效（2024-04-24 廣達）。"
        "同學寫「短線收盤破三日低點」他 2026-06-24 回現在不能看這麼短。不是固定公式。不是買訊。",
    ),
    (
        re.compile(r"(次級四|次級波|次級 4|次級4浪|回測四浪)"),
        "次級四浪",
        "次級四浪＝回測同一次級第 4 浪價區，他常當回測支撐。"
        "例子：廣達 2026-06-05 回測 375～393；費半／台指期 60 分 2026-06-17 回測次級四浪有撐才談主升；"
        "萬潤 2024-10-18 盤中跌破次級 4 浪、收盤站回＝洗浮額。"
        "上升軌也是同一次級浪 2 低連浪 4 低。不是買訊。",
    ),
    (
        re.compile(
            r"(右肩|45839|低不破前低|高有過前高|高檔震[盪檔]|追高殺低|汰弱留強|汰弱擇強|"
            r"抱長線主流|觀盤重點)"
        ),
        "右肩／45839",
        "2026-09-11 08:43 公開文：未來 2～3 交易日觀盤重點是 9/3 加權低點 45839 有沒有守住。"
        "有守住＝右肩還是高有過前高、低不破前低，高檔震盪趨勢向上。"
        "這段不要追高殺低，只汰弱留強（他說很難）；建議抱長線主流龍頭。"
        "資料庫：20260903 TWII 低 45839.36、收 45857.66；9/4～9/10 的低都高於 45839（最近 9/4 低 45966.86）。"
        "9/11 起那 2～3 日庫還沒有日 K，守不守還在走。不是買訊。",
    ),
    (
        re.compile(r"(量先價行|爆大量|價穩量縮|窒息量)"),
        "量先價行",
        "介入買點先看量先價行：爆大量那一天最高當壓、最低當撐；站上撐或壓力轉撐之後，等價穩量縮才進，否則放棄。"
        "窒息量＝相對這波攻擊量縮到極致，沒有公式。KD／MACD／布林他不算技術分析。",
    ),
    (
        re.compile(r"(三個買點|三買點|買點只有|整理末端|突破回測|隔日沖)"),
        "三個買點",
        "2026-02-13 他說超過 90% 的買點只有三個：整理末端（難）、突破回測、行進中強行介入＝隔日沖。"
        "半山腰只隔日沖。買越低如果在支撐之下＝錯。核心是產業趨勢＋波浪＋量價結構。",
    ),
    (
        re.compile(r"(半山腰|漲一倍|見好就收)"),
        "半山腰只隔日沖",
        "半山腰只隔日沖；漲一倍見好就收（2025-08-06 無人機那組）。不要把半山腰當波段左側買點。",
    ),
    (
        re.compile(r"(量價背離|背離)"),
        "量價背離",
        "2025-06-27 原文：量價背離只認連續一波上漲攻擊到頂（或至少波段高點、要整理約 3 周）。"
        "不是大盤反彈、也不是台積電緩漲。他當下點名台光電、勤誠能用，明確排除台積電。不要寫進海選。",
    ),
    (
        re.compile(r"(次族群|第一名|誰先過前高|接棒|領頭|族群發動|怎麼抓龍頭)"),
        "次族群第一名",
        "看次族群第一名是否整理完成、誰先過前高，不比絕對漲跌。領頭羊做頭，同族其他檔先找賣點。"
        "不是等新聞；公開能還原的是整理時間誰短、誰先測高。",
    ),
    (
        re.compile(r"(盲測|沒講過|沒點名|沒寫過)"),
        "盲測要疊條件",
        "資料庫沒點名的檔，仍用同一套框架套官方 K：量先價行＋不是半山腰＋同族第一名已整理完＋大盤不是他認定的主跌＋新聞沒變多。"
        "單條爆量視窗一換就換日，假陽性多。不是買訊。",
    ),
    (
        re.compile(r"(止跌|何時止|哪時候止|大概.*止)"),
        "止跌不猜日期",
        "他不猜日曆。止跌是結構先出現：費半不再破低、夜盤先於日盤過下降壓、多標籤時台積電量價站上、細微波 5／9 走完。"
        "缺 15 分就不數段。這不是『下週幾』保證。",
    ),
    (
        re.compile(r"(停損|7%|百分之七|風控)"),
        "停損",
        "公開能講的：停損大約 7～10%（長線龍頭另論）。不是海選條件、也不自動下單。",
    ),
    (
        re.compile(r"(不看均線|不算技術|KD|MACD|布林)"),
        "不算的東西",
        "他 2023-12-21 就寫：只看型態、K 線、量價，不看均線指標。後來也明確 KD／MACD／布林不算技術分析。認支撐、窒息量、波浪段數。",
    ),
    (
        re.compile(r"(新聞|消息面|技術面領先|法說)"),
        "技術面領先新聞",
        "不要看新聞／雜誌做股票。新聞變多、平台狂貼法說＝中短期高點（汎銓 2026-04-18）。技術面永遠領先消息面。",
    ),
    (
        re.compile(r"(去年年底|去年底|年底|年終|記憶體布局)"),
        "去年年底",
        "2025 年底～2026 年初主戰場是記憶體。12/17 起布局；PCB／F4／散熱當時當做出貨或做頭。"
        "他明講其他族群不要再介入、專心做記憶體。之後位階有改口，問當下那一檔再套官方 K。",
    ),
    (
        re.compile(r"(連點|連線|浪\s*2|浪\s*4|上升軌|下降壓|黃軌|三角)"),
        "連哪兩天的點",
        "上升軌＝同一次級兩個低點連起來（浪 2 低連浪 4 低）。下降壓＝同一次級兩個更低的高連起來。三角＝兩條一起，看收在不在上下區間。"
        "他看大盤常先畫台積電。2025-12-03 明講：台積電 9/3 低連 11/24 低，或加權 9/3 低連 11/21 低；不破才談第五波。"
        "2025-12-16 他說台積電已跌破。資料庫日 K：2330 9/3 低 1145、11/24 低 1375；12/16 收 1435，交易日延長那條軌約 1443，收盤跌破。加權同日還沒破 9/3–11/21 那條——他用台積電當先行。不是買訊。",
    ),
]


def match_methods(ask: str, *, limit: int = 3) -> List[Tuple[str, str]]:
    q = ask or ""
    hits: List[Tuple[str, str]] = []
    for pat, title, body in _METHODS:
        if pat.search(q):
            hits.append((title, body))
        if len(hits) >= limit:
            break
    return hits


def format_methods_html(ask: str) -> str:
    hits = match_methods(ask)
    if not hits:
        return ""
    return "\n".join(html_escape(body) for _title, body in hits)


def is_method_query(ask: str) -> bool:
    q = (ask or "").strip()
    if not q:
        return False
    return bool(match_methods(q, limit=1))


def follow_up_ask(ask: str, history: Optional[Sequence[Any]] = None) -> str:
    """『那呢／那一檔』接上一句題目，才像對話不是考卷。"""
    q = (ask or "").strip()
    if not q or not history:
        return q
    if not re.match(r"^(那|這個|剛剛|同上|繼續|所以|然後|對啊|對阿|嗯|喔|那呢)", q):
        return q
    if len(q) >= 16:
        return q
    last = ""
    for item in reversed(list(history)):
        if isinstance(item, dict):
            last = str(item.get("ask") or "")
        elif isinstance(item, (list, tuple)) and item:
            last = str(item[0])
        else:
            last = str(item)
        if last.strip():
            break
    if not last:
        return q
    return f"{last} {q}".strip()


def method_curriculum() -> List[str]:
    """一百題判斷問句。答案走 match_methods，不是 100 顆按鈕。"""
    stems = [
        "融會貫通是什麼",
        "三百一百三百課綱",
        "細微波四步是什麼",
        "他怎麼觀察細微波",
        "夜盤先於日盤是什麼意思",
        "1-4 重疊代表什麼",
        "費半為什麼是台股先行",
        "多標籤時為什麼看台積電量價",
        "量先價行怎麼看",
        "爆大量那根高低怎麼用",
        "價穩量縮才進是什麼",
        "三個買點是哪三個",
        "整理末端怎麼認定",
        "突破回測怎麼看",
        "半山腰為什麼只隔日沖",
        "漲一倍見好就收是哪次說的",
        "量價背離什麼時候才能用",
        "台積電能不能講量價背離",
        "次族群第一名怎麼看接棒",
        "誰先過前高為什麼重要",
        "盲測沒點名的股票怎麼套",
        "大概何時止跌",
        "止跌為什麼不猜日期",
        "停損大概多少",
        "他算不算 KD MACD",
        "為什麼不看均線",
        "新聞變多為什麼常是高點",
        "去年年底在做什麼",
        "浪 2 連浪 4 是什麼軌",
        "下降壓怎麼連",
        "夜盤沒過下降壓還能談止跌嗎",
        "費半還在跌台股能抄底嗎",
        "量先價行要不要寫進海選",
        "半山腰只隔日沖對不對",
        "窒息量有沒有公式",
        "KD 他算技術分析嗎",
        "細微波沒 15 分怎麼辦",
        "1-4 重疊和費半一起看嗎",
        "三買點超過 90% 是哪天說的",
        "產業加波浪加量價是哪天",
        "2023 他就說不看均線了嗎",
        "汎銓新聞變多是哪次",
        "勤誠量價背離他出清過嗎",
        "盲測要疊條件嗎",
        "資料庫沒寫過也能套這套嗎",
        "官方 K 套上去是不是買訊",
        "食衣住行這邊答不答" if False else "止跌不猜日期對不對",
        "夜盤先於日盤有沒有例外",
        "連點浪 2 浪 4",
        "去年底記憶體布局",
        "費半先行還在逆風",
        "台積電量價決勝怎麼用",
        "洗盤跟出貨怎麼分",
        "破線翻是什麼",
        "連三天不破點",
        "假跌破三日內站回",
        "三日不回補缺口",
        "次級四浪是什麼",
        "次級波怎麼看",
        "右肩型態怎麼看",
        "45839 有沒有守住",
        "高有過前高低不破前低",
        "不要追高殺低",
        "恐慌下殺多標籤怎麼選",
    ]
    out: List[str] = []
    seen = set()
    variants = [
        "{}",
        "{} 用他的規則講",
        "哥哥問：{}",
        "再講一次{}",
    ]
    for tmpl in variants:
        for s in stems:
            q = tmpl.format(s).strip()
            if q in seen or not match_methods(q, limit=1):
                continue
            seen.add(q)
            out.append(q)
            if len(out) >= 100:
                return out[:100]
    return out


def main_posts(posts: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [p for p in posts if (p.get("kind") or "post") != "reply"]


def stratified_main_posts(
    posts: Sequence[Dict[str, Any]], n: int, *, phase: int = 0
) -> List[Dict[str, Any]]:
    """沿時間軸均勻抽 n 則主文。phase=1 錯開半步，給第二輪 300 用。"""
    mains = sorted(
        main_posts(posts),
        key=lambda p: (str(p.get("date") or ""), str(p.get("id") or "")),
    )
    if not mains or n <= 0:
        return []
    if len(mains) <= n:
        return list(mains)
    out: List[Dict[str, Any]] = []
    seen = set()
    step = len(mains) / float(n)
    shift = 0.5 * step if int(phase) else 0.0
    for i in range(n):
        idx = int(i * step + shift) % len(mains)
        p = mains[idx]
        aid = str(p.get("id") or "")
        if aid in seen:
            for j in range(1, len(mains)):
                q = mains[(idx + j) % len(mains)]
                qid = str(q.get("id") or "")
                if qid not in seen:
                    p, aid = q, qid
                    break
        seen.add(aid)
        out.append(p)
    return out


def corpus_curriculum(posts: Sequence[Dict[str, Any]], *, limit: int = 300) -> List[str]:
    """三百題公開文對答：沿 1709 時間軸均勻抽，不是只拿最早 300 則。"""
    asks: List[str] = []
    seen = set()

    def add(q: str) -> None:
        q = (q or "").strip()
        if q and q not in seen:
            seen.add(q)
            asks.append(q)

    for p in stratified_main_posts(posts, int(limit), phase=0):
        for t in p.get("tags") or []:
            add(str(t))
        date = str(p.get("date") or "")
        tags = [str(t) for t in (p.get("tags") or [])[:2]]
        if date and tags:
            add(f"{date} {' '.join(tags)}")
        text = re.sub(r"\s+", " ", str(p.get("text") or "")).strip()
        if date and text:
            add(f"{date} {text[:18]}")
        if len(asks) >= limit:
            break
    return asks[:limit]


def k_curriculum(
    named: Sequence[str],
    quotes: Sequence[Tuple[str, str]],
    *,
    limit: int = 300,
) -> List[Tuple[str, str]]:
    """三百檔官方 K：資料庫沒點名的上市櫃，套量先價行。"""
    blob = " ".join(str(x) for x in named)
    out: List[Tuple[str, str]] = []
    for sid, name in quotes:
        sid = str(sid)
        name = str(name)
        if not sid or sid in blob or name in blob:
            continue
        out.append((sid, name))
        if len(out) >= limit:
            break
    return out
