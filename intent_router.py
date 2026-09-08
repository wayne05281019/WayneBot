"""平常話 → 官方資料路徑。不編新聞、不編成本、不跑 LLM。

只把關鍵字對到既有功能：查股三張圖、籌碼、產業、營收、如何賣、
大盤、資金、海選、持股、觀察、當沖、隔日沖、連買、AI倉。
「為什麼跌」沒有官方新聞欄，對到決策卡／籌碼等真資料。
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Optional, Tuple

# 需要帶一檔代號才出得了正確資料。
NEEDS_STOCK = frozenset(
    {
        "why",
        "lookup",
        "card",
        "chips",
        "industry",
        "fund",
        "sell",
        "no_cost",
    }
)

# 全市場頁，代號可有可無（有就記住，不改頁）。
GLOBAL_KINDS = frozenset(
    {
        "hub",
        "market",
        "flow",
        "screen",
        "portfolio",
        "watch",
        "daytrade",
        "overnight",
        "streak",
        "ai",
        "help",
        "report",
    }
)

# 最長優先。勿用單字「賣／買／看」以免誤觸記買入。
_PHRASES: Tuple[Tuple[str, str], ...] = (
    ("三大法人買賣超", "chips"),
    ("三大法人", "chips"),
    ("法人買賣超", "chips"),
    ("外資買超", "chips"),
    ("外資賣超", "chips"),
    ("投信買超", "chips"),
    ("投信賣超", "chips"),
    ("自營買超", "chips"),
    ("自營賣超", "chips"),
    ("外資連買", "streak"),
    ("投信連買", "streak"),
    ("連買區域", "streak"),
    ("連買區", "streak"),
    ("資金移動", "flow"),
    ("產業輪動", "flow"),
    ("產業說明", "industry"),
    ("如何賣", "sell"),
    ("怎麼賣", "sell"),
    ("該賣嗎", "sell"),
    ("要不要賣", "sell"),
    ("準備減碼", "sell"),
    ("直接減碼", "sell"),
    ("出場協助", "sell"),
    ("為什麼下跌", "why"),
    ("為甚麼下跌", "why"),
    ("為什麼跌這麼多", "why"),
    ("為甚麼跌這麼多", "why"),
    ("為何下跌", "why"),
    ("為什麼跌", "why"),
    ("為甚麼跌", "why"),
    ("為何跌", "why"),
    ("怎麼跌這麼多", "why"),
    ("怎麼跌", "why"),
    ("跌這麼多", "why"),
    ("為什麼上漲", "why"),
    ("為甚麼上漲", "why"),
    ("為什麼漲這麼多", "why"),
    ("為甚麼漲這麼多", "why"),
    ("為何上漲", "why"),
    ("為什麼漲", "why"),
    ("為甚麼漲", "why"),
    ("為何漲", "why"),
    ("怎麼漲這麼多", "why"),
    ("怎麼漲", "why"),
    ("漲這麼多", "why"),
    ("什麼原因", "why"),
    ("啥原因", "why"),
    ("什麼緣故", "why"),
    ("主力成本", "no_cost"),
    ("外資成本", "no_cost"),
    ("投信成本", "no_cost"),
    ("融資成本", "no_cost"),
    ("自營成本", "no_cost"),
    ("黃金買點", "screen"),
    ("重點觀察", "screen"),
    ("觀察清單", "watch"),
    ("自選清單", "watch"),
    ("自選股", "watch"),
    ("我的持股", "portfolio"),
    ("真實持股", "portfolio"),
    ("AI模擬倉", "ai"),
    ("模擬持倉", "ai"),
    ("模擬倉", "ai"),
    ("加權指數", "market"),
    ("台股大盤", "market"),
    ("台股今天", "market"),
    ("月營收", "fund"),
    ("使用說明", "help"),
    ("圖文說明", "help"),
    ("決策卡", "card"),
    ("介紹圖", "lookup"),
    ("導航圖", "lookup"),
    ("高低卡", "lookup"),
    ("隔日沖", "overnight"),
    ("隔日", "overnight"),
    ("隔沖", "overnight"),
    ("當沖", "daytrade"),
    ("連買", "streak"),
    ("籌碼", "chips"),
    ("法人", "chips"),
    ("外資", "chips"),
    ("投信", "chips"),
    ("自營", "chips"),
    ("同業", "industry"),
    ("產業", "industry"),
    ("營收", "fund"),
    ("毛利", "fund"),
    ("財報", "fund"),
    ("本益", "fund"),
    ("殖利率", "fund"),
    ("融資", "fund"),
    ("融券", "fund"),
    ("資金", "flow"),
    ("輪動", "flow"),
    ("大盤", "market"),
    ("加權", "market"),
    ("指數", "market"),
    ("美股", "market"),
    ("台指期", "market"),
    ("海選", "screen"),
    ("起漲", "screen"),
    ("選股", "screen"),
    ("持股", "portfolio"),
    ("持倉", "ai"),
    ("自選", "watch"),
    ("觀察", "watch"),
    ("AI倉", "ai"),
    ("假錢", "ai"),
    ("進化", "ai"),
    ("減碼", "sell"),
    ("出場", "sell"),
    ("停利", "sell"),
    ("為何", "why"),
    ("為什麼", "why"),
    ("為甚麼", "why"),
    ("原因", "hub"),
    ("怎麼用", "help"),
    ("說明書", "help"),
    ("說明", "help"),
    ("幫助", "help"),
    ("回報問題", "report"),
    ("回報", "report"),
    ("查股", "lookup"),
    ("查一下", "lookup"),
    ("看看", "lookup"),
    ("why", "why"),
    ("chips", "chips"),
    ("industry", "industry"),
    ("market", "market"),
    ("screen", "screen"),
    ("help", "help"),
)

_PHRASES = tuple(sorted(_PHRASES, key=lambda kv: len(kv[0]), reverse=True))

_FILLERS = tuple(
    sorted(
        (
            "請問一下",
            "幫我看一下",
            "幫我查一下",
            "看一下這檔",
            "查一下這檔",
            "我想問",
            "我想看",
            "告訴我",
            "跟我說",
            "請問",
            "幫我看",
            "幫我查",
            "幫我",
            "看一下",
            "查一下",
            "怎麼了",
            "怎麼樣",
            "怎樣",
            "一下",
            "這個",
            "這檔",
            "那檔",
            "這支",
            "那支",
            "今日",
            "今天",
            "目前",
            "現在",
            "最近",
            "名單",
            "結果",
            "報告",
            "清單",
            "股票",
            "是不是",
            "能不能",
            "可不可以",
            "可以嗎",
            "可以",
            "麻煩",
            "謝謝",
            "顯示",
            "我的",
            "我們",
            "的啊",
            "的呀",
            "請",
        ),
        key=len,
        reverse=True,
    )
)

_PUNCT = "？?！!。．，,、；;：:「」『』\"'“”‘’（）()【】[]…·．~～-—_/\\"
_CODE_RE = re.compile(r"(?<![A-Za-z0-9])(\d{4,6}[A-Za-z]?)(?![A-Za-z0-9])")


@dataclass(frozen=True)
class IntentHit:
    kind: str
    query: str
    code: str
    matched: str
    needs_stock: bool


def compact_text(text: str) -> str:
    t = unicodedata.normalize("NFKC", text or "").strip()
    t = t.replace("\u3000", "").replace(" ", "")
    if t.startswith("/"):
        t = t[1:]
    for ch in _PUNCT:
        t = t.replace(ch, "")
    return t


def _strip_fillers(s: str) -> str:
    prev = None
    while prev != s:
        prev = s
        for f in _FILLERS:
            s = s.replace(f, "")
        s = s.strip("的了啊呀呢嗎嘛喔哦嗯")
    return s


def parse_intent(text: str, *, default_kind: str = "") -> Optional[IntentHit]:
    """把一句平常話拆成 kind + 可能的代號／股名。沒命中關鍵字且沒有 default 就回 None。"""
    raw = compact_text(text)
    if not raw:
        if default_kind:
            return IntentHit(default_kind, "", "", "", default_kind in NEEDS_STOCK)
        return None

    codes = _CODE_RE.findall(raw)
    work = _CODE_RE.sub("", raw)
    matched = ""
    kind = ""
    for phrase, mapped in _PHRASES:
        if phrase and phrase in work:
            matched = phrase
            kind = mapped
            work = work.replace(phrase, "", 1)
            break

    if not kind:
        kind = default_kind
    if not kind:
        return None

    query = _strip_fillers(work)
    code = (codes[0].upper() if codes else "")
    if kind == "hub" and (code or query):
        kind = "why"
    if kind == "flow" and (code or query):
        # 「2330資金／台積電資金」對個股法人，不是全市場資金頁。
        kind = "chips"
    if kind in ("help", "report", "watch", "portfolio") and (code or query):
        # 「2330說明／台積電觀察」帶檔就出這檔資料，不整頁說明。
        kind = "why"
    if kind == "ai" and code:
        kind = "why"
    needs = kind in NEEDS_STOCK
    return IntentHit(
        kind=kind,
        query=query,
        code=code,
        matched=matched,
        needs_stock=needs,
    )


def why_honest_html() -> str:
    return (
        "官方<b>沒有</b>「為什麼漲跌」新聞欄，也不編新聞、不編成本。\n"
        "下面是這檔<b>決策卡／介紹圖／導航圖</b>（官方價量）。籌碼／產業／營收在圖下面。"
    )


def sell_honest_html() -> str:
    return (
        "<b>如何賣</b>只標作者公開規則：最高價＝20日高，對最高溫。"
        "不是買訊、不改海選、不自動賣。"
    )


def no_cost_honest_html() -> str:
    return (
        "官方<b>沒有</b>外資／投信／融資／主力成本價。三大法人不是主力。\n"
        "沒有真分點列就不上「主力成本」。改看<b>籌碼</b>（官方法人張數）。"
    )


def why_hub_html(last_code: str = "") -> str:
    last = f"<code>{last_code}</code>" if last_code else "（還沒查過，請打四碼）"
    return (
        "<b>原因</b>（輸入列左邊三條槓）\n"
        "用平常的話問，會對到<b>官方資料</b>，不編新聞、不編成本。\n"
        "也可以直接<b>對麥克風說話</b>（Telegram 語音），聽成文字後走同一條路。\n"
        "\n"
        "例：\n"
        "• 為什麼跌／為什麼漲　→ 這檔決策卡（沒有官方跌因欄）\n"
        "• 2330怎麼賣　→ 如何賣（20日高對最高溫）\n"
        "• 外資／籌碼／法人　→ 三大法人圖\n"
        "• 產業／營收　→ 產業圖卡／月營收\n"
        "• 大盤／海選／持股　→ 對應那一頁\n"
        "• 主力成本　→ 說明沒有這欄，改看出官方法人\n"
        "\n"
        f"上一檔：{last}\n"
        "沒寫代號就用上一檔。也可直接在聊天室打這些詞，不必先開選單。"
    )
