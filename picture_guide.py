# -*- coding: utf-8 -*-
"""哥哥圖文說明：手機長圖 16 頁，說明頁「圖文」一次一張、按第 N 張換頁。

藍底白字青標對齊產業圖卡／大盤跑馬燈；金線當層次。一次只渲正在看的那一張。
"""
from __future__ import annotations

import os
import re
from typing import Dict, List, Optional, Sequence, Tuple

CACHE_VER = "v19"
# 十六頁同一張 9:16 一屏。超長海報在話筒裡會整張縮小，字會小到不能看。
# 1080×1920＝手機直式一屏；點開幾乎滿版。內文以 ≥50px 畫，390 寬話筒點開約 18–20 點。
PAGE_WIDTH = 1080
PAGE_HEIGHT = 1920
MARGIN = 40
TITLE_SIZE = 76
BODY_SIZE = 52
MAX_TITLE_SIZE = 84
MAX_BODY_SIZE = 64
MIN_TITLE_SIZE = 68
MIN_BODY_SIZE = 48
BOTTOM_PAD = 48
TEXT_SHOT_GAP = 96
SHOT_TOP_RATIO = 0.52
CHROME_TOP = 8
PROGRESS_H = 22
KICKER_H = 44
TG_PHOTO_MAX_BYTES = 9_800_000
FLIP_W = 540
FLIP_H = 960
FLIP_FRAMES = 8
FLIP_MS = 55
_BREAK_AFTER = set("、。；：，,．）)」」】》 \u3000")

# 禁止 emoji：NotoSansTC 會畫成方塊。鍵盤寫「鍵盤」，加號寫「+」。
PAGES: Sequence[Tuple[str, str, str]] = (
    (
        "cover",
        "第一次用，先做這三步",
        "這本說明給手機看。一次只看一張。\n"
        "\n"
        "1  點四格鍵盤圖示叫出兩排。不見就打 /menu\n"
        "2  直接打四碼看圖，例如 2330。不要先按「決策卡」\n"
        "3  三張圖出來後，籌碼／營收／產業在圖下面那一排\n"
        "\n"
        "點輸入列旁邊的四格鍵盤圖示展開兩排。\n"
        "按「第 2 張」看下一張；要回去按上一張。\n"
        "換頁時這一張會滑走，換成下一張。\n"
        "挑股只認高低卡表的黃金買點。\n"
        "圖上紅箭頭不是買訊。",
    ),
    (
        "menu",
        "兩排主選單在哪",
        "不在訊息最下面。點輸入列旁邊的四格鍵盤圖示展開兩排。也可打 /menu。\n"
        "\n"
        "第一排（左到右）\n"
        "決策卡　當沖　持股　觀察　海選　AI倉\n"
        "\n"
        "第二排（左到右）\n"
        "隔日沖　大盤　資金　連買區　說明　回報\n"
        "\n"
        "決策卡＝刷新上一檔，不是海選。還沒查過請直接打四碼。\n"
        "畫面怪按最右「回報」。",
    ),
    (
        "lookup",
        "直接打四碼",
        "打股名或代號，例如 2330 或 台積電。不要先按「決策卡」。\n"
        "\n"
        "1  輸入列打四碼，送出就出圖\n"
        "2  一次出三張，點縮圖可放大\n"
        "3  名稱撞名時：藍字＝奇摩網頁；左邊＝看這檔；右邊「+」＝加入觀察\n"
        "\n"
        "找不到就再打一次四碼，比打股名準。",
    ),
    (
        "charts",
        "查一檔：一次三張圖",
        "打完四碼會一次出三張。點縮圖可放大。\n"
        "\n"
        "1  介紹圖：這一檔現在熱不熱、獲利離 0 多遠\n"
        "2  決策卡：高低卡表。進場只認表，不認紅箭頭\n"
        "3  導航圖：近半年走勢，對照自己在哪\n"
        "\n"
        "黃金買點＝獲利剛離開 0。重點觀察＝還壓在近 60 個日曆天收盤低，不是立刻買。",
    ),
    (
        "hub",
        "圖下面那一排",
        "查完才出現，不是主選單那兩排。找不到產業：在圖下面，不在右邊四格鍵盤。\n"
        "\n"
        "1  籌碼　三大法人買賣超圖\n"
        "2  營收　月營收、季報毛利\n"
        "3  產業　一張圖卡：同業中位＋本產業法人；股名旁公開細項小框，沒抓到不畫、不留空白\n"
        "4  觀察　加入自選（還沒買）\n"
        "5  記買入　記真實持股。接著打「張數 價格」，例 1 68.5\n"
        "\n"
        "零股請寫「200股 631.6」。不要只打 2，會被當成 2 張。",
    ),
    (
        "discipline",
        "粉紅紀律不是買訊",
        "介紹圖「紀律」、決策卡「今日態度」只講現在怎樣，不是買訊。句子跟下面那張 20 日表的數字、底色對齊。不改海選。徽章才寫月K還在往上、已走空或在整理。不是買訊。\n"
        "\n"
        "1  高點跟熱度都退了 → 先別追；有持股先出一點\n"
        "2  價到高了、熱度沒跟上 → 先出一點、不要追\n"
        "3  很熱但價沒過前高 → 先出一點、不要追高\n"
        "4  高點跟熱度都沒了 → 這波先當結束；先出一點",
    ),
    (
        "sell",
        "如何賣",
        "作者公開「如何賣」，只協助出場，不是買訊，不自動賣，不改海選。\n"
        "\n"
        "1  最高價＝20日高，對最高溫\n"
        "2  同步再脫離＝準備減碼；不同步＝直接減碼\n"
        "3  只標在介紹圖／決策卡／持股／AI倉\n"
        "\n"
        "進場仍只認高低卡表的黃金買點。紅箭頭不是買訊。",
    ),
    (
        "screen",
        "海選怎麼轉 LINE",
        "海選＝依最近一次官方收盤掃全市場。不是盤中即時掃描。主選單第一排「海選」就是圖上紅圈那顆。按一次等 2～5 分鐘，不要連按。\n"
        "\n"
        "1  左鍵（代號＋股名）＝看這檔完整圖；右「+」＝加入觀察\n"
        "2  股名右「開 LINE・傳這檔」＝只傳這一檔，直跳 LINE，再選聯絡人\n"
        "3  區底「一鍵傳 LINE」＝進勾選頁，可勾好幾檔再傳（介紹圖＋決策卡一組）\n"
        "\n"
        "當沖／隔日沖不在晨間海選。請按主選單那兩顆。",
    ),
    (
        "lists",
        "三種清單不要搞混",
        "1  觀察＝自選，還沒買。頁上每檔兩排：上排股名（看這檔）／籌碼；下排買入（記真實持股）／刪\n"
        "2  持股＝你手記的真實買入。頁上：股名、賣出；底下還有成交／復盤／AI倉\n"
        "3  AI倉＝假錢對照組（50 萬切 3 等份）。平常最多用 1 份；大盤超跌才動第 2 份抄低。第 3 份永遠留現金，不買滿。不是你口袋裡的股票。\n"
        "\n"
        "頁上「AI操盤」立刻跑一輪模擬買賣，不推播。盤後融合與每晚 20:00 雲端也會跑，不會傳到話筒。",
    ),
    (
        "ai",
        "AI倉怎麼進化",
        "AI倉是假錢對照組，不會真的下單，也不能把這支程式塞進手機下單軟體。\n"
        "\n"
        "1  按第一排最右「AI倉」看現金／持倉\n"
        "2  「AI操盤」立刻依海選跑一輪，不推播\n"
        "3  「進化」看目前編碼：只調單筆倍數與哪類少買，不改黃金買點\n"
        "4  週五收盤後寄一則進化回報。將來接到券商＝你用手把條件打進積木\n"
        "\n"
        "平常最多用 1 份，第 3 份留現金。",
    ),
    (
        "daytrade",
        "當沖與隔日沖",
        "這兩顆不在晨間海選。週末／收盤後按「當沖」本來就空，改看隔日沖或海選，不要連按。\n"
        "\n"
        "1  當沖：平日 09:00–13:30 才有。保險進場、停利、停損參考價\n"
        "2  隔日沖：尾盤佈局、明早目標。收盤後按只供明天開盤參考，不是叫你再買\n"
        "3  美股隔夜大跌、恐慌指數高時，當沖會故意不列，避免硬沖\n"
        "\n"
        "左鍵看現價＋圖，右「+」加入觀察。",
    ),
    (
        "market",
        "大盤跑馬燈",
        "第二排、隔日沖右邊。最上頭是時段跑馬燈（循環短圖），下面才是數字與橫式日K。\n"
        "\n"
        "1  抓證交所／期交所／公開即時報價的當下最後一筆\n"
        "2  開盤前電子數字倒數試搓／台指期；沒接到的市場不寫\n"
        "3  整條從最左跑到最右；長住那一則自己換價，也可按「刷新跑馬燈」\n"
        "4  美股當天沒開會寫原因，並附前一交易日收盤\n"
        "\n"
        "只讀、不寫進資料庫。不影響 16:30 官方收盤寫庫。",
    ),
    (
        "streak",
        "連買區",
        "官方法人連續買超名單，不是下單訊號。\n"
        "\n"
        "1  先選：外資／投信／外資+投信\n"
        "2  再點天數。上市櫃一起列，不再分市場\n"
        "3  選到一半按錯：改按別顆就取消，再按連買區重來\n"
        "\n"
        "名單：代號、股名、N日連買張數與佔成交%。點股名看出完整圖，按籌碼核對官方法人表。四格鍵盤被收掉時打 /menu 可重新釘住兩排。",
    ),
    (
        "why",
        "用平常話問原因",
        "輸入列左邊三條槓有「原因」。聊天室直接打這些詞也行。會對到官方資料，不編新聞、不編成本。\n"
        "\n"
        "1  為什麼跌／為什麼漲 → 介紹圖＋決策卡＋導航圖。沒有官方新聞跌因\n"
        "2  怎麼賣／如何賣 → 最高價＝20日高對最高溫。不是買訊、不自動賣\n"
        "3  外資／籌碼／產業／營收／大盤／海選 → 對到那一頁真資料\n"
        "4  主力成本／外資成本 → 說明官方沒這欄，改看籌碼\n"
        "\n"
        "沒寫代號用上一檔。還沒查過請打「2330為什麼跌」。也可傳語音，聽成文字後走同一條路。",
    ),
    (
        "rhythm",
        "一天什麼時候動",
        "時間都是台灣。平日自動跑，不會叫你盯著等。\n"
        "\n"
        "1  06:30 早報（對美股）\n"
        "2  12:45 尾盤可切版\n"
        "3  16:30 官方收盤寫庫（齊了發一則，不是海選）\n"
        "4  20:00 AI倉模擬買賣，不推播。晚間海選一併寫庫\n"
        "\n"
        "盤中查股用證交所即時價（不寫庫）。16:30 後以庫內官方收盤為準。",
    ),
    (
        "oops",
        "按錯了怎麼辦",
        "亂按沒關係。下面幾條最常見。\n"
        "\n"
        "1  一打開先按了「決策卡」：那顆是刷新上一檔。還沒查過就直接打四碼\n"
        "2  「當沖」沒名單：週末／收盤後本來就空。平日 09:00–13:30 才有\n"
        "3  「海選」等很久：掃全市場；不要連按。觀察＝還沒買；持股＝按過記買入才會在\n"
        "4  找不到產業：在圖下面那一排。想問為什麼跌：左邊三條槓點「原因」\n"
        "5  「回報」按下去又反悔：改按其他按鈕即可，不會送出。主選單不見：點四格鍵盤圖示，或打 /menu。畫面怪按第二排最右「回報」。不用給密鑰或密碼",
    ),
)

PAGE_SLUGS = tuple(slug for slug, _title, _body in PAGES)

# 每頁對應真實截圖（側欄已裁；紅圈標該頁要按的位置）。沒有對得上的頁就不配圖。
PAGE_SHOTS = {
    "cover": "cover_menu.png",
    "menu": "cover_menu.png",
    "lookup": "charts.png",
    "charts": "charts.png",
    "hub": "hub.png",
    "discipline": "discipline.png",
    "sell": "discipline.png",
    "screen": "screen.png",
    "lists": "lists.png",
    "ai": "lists.png",
    "streak": "streak.png",
    "oops": "oops.png",
}

PAGE_KICKERS: Dict[str, str] = {
    "cover": "說明書",
    "menu": "鍵盤",
    "lookup": "查股",
    "charts": "三張圖",
    "hub": "圖下按鈕",
    "discipline": "紀律",
    "sell": "出場",
    "screen": "海選",
    "lists": "清單",
    "ai": "AI倉",
    "daytrade": "短線",
    "market": "大盤",
    "streak": "連買",
    "why": "原因",
    "rhythm": "作息",
    "oops": "按錯",
}

PAGE_LAYOUT: Dict[str, str] = {
    "cover": "cover",
    "menu": "visual",
    "lookup": "visual",
    "charts": "visual",
    "hub": "visual",
    "discipline": "visual",
    "sell": "visual",
    "screen": "visual",
    "lists": "visual",
    "ai": "visual",
    "streak": "visual",
    "oops": "visual",
    "daytrade": "editorial",
    "market": "editorial",
    "why": "editorial",
    "rhythm": "editorial",
}

PAGE_PILLS: Dict[str, Tuple[str, ...]] = {
    "why": ("為什麼跌", "怎麼賣", "外資", "產業", "大盤", "海選"),
    "market": ("加權", "櫃買", "台指期", "美股", "刷新跑馬燈"),
    "daytrade": ("當沖 09:00–13:30", "隔日沖看尾盤", "週末改看隔日沖"),
    "rhythm": ("06:30 早報", "12:45 尾盤", "16:30 寫庫", "20:00 AI倉"),
}

PAGE_PANEL: Dict[str, str] = {
    "why": "可以這樣問",
    "market": "跑馬燈會寫這些",
    "daytrade": "先記住這三句",
    "rhythm": "台灣時間",
}

# 對齊產業圖卡／大盤跑馬燈：深藍底、白字、青標；金線當層次。
_BG = (18, 26, 38)
_INK = (236, 242, 248)
_MUTED = (168, 186, 204)
_ACCENT = (140, 210, 255)
_LINE = (70, 96, 122)
_CARD = (12, 20, 32)
_LABEL_BG = (28, 52, 78)
_GOLD = (196, 158, 88)
_GOLD_HI = (232, 208, 150)
_WATER = (28, 38, 52)
_STEP_BG = (22, 34, 50)


def _font_paths() -> Tuple[str, str]:
    here = os.path.dirname(os.path.abspath(__file__))
    regular = os.path.join(here, "fonts", "NotoSansTC-w560.ttf")
    bold = os.path.join(here, "fonts", "NotoSansTC-w860.ttf")
    return regular, bold


def _load_font(size: int, *, bold: bool = False):
    from PIL import ImageFont

    regular, bold_path = _font_paths()
    path = bold_path if bold and os.path.isfile(bold_path) else regular
    if os.path.isfile(path):
        return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def _ink_box(font, text: str):
    bbox = font.getbbox(str(text or ""))
    return bbox[0], bbox[1], bbox[2], bbox[3]


def _centered_text_xy(font, text: str, box) -> tuple:
    """讓真實墨水框的中心對上 box 幾何中心。"""
    x0, y0, x1, y1 = box
    l, t, r, b = _ink_box(font, text)
    tw, th = r - l, b - t
    return x0 + (x1 - x0 - tw) / 2.0 - l, y0 + (y1 - y0 - th) / 2.0 - t


def _text_w(draw, text: str, font) -> float:
    """用實際墨水寬，避免 textlength 低估、最後一個句號被拼回去後超出右緣。"""
    try:
        tl = float(draw.textlength(text, font=font))
    except Exception:
        tl = len(text or "") * (getattr(font, "size", 28) * 0.9)
    try:
        l, _t, r, _b = font.getbbox(text)
        return max(tl, float(r - l))
    except Exception:
        return tl


def _wrap_line(draw, text: str, font, first_w: float, rest_w: float) -> List[str]:
    """CJK 折行：盡量在頓號／句號切開。不把 /menu 從斜線拆開；不把溢出的句號拼回去。"""
    if not text:
        return [""]
    pad = 12.0
    lines: List[str] = []
    buf = ""
    limit = max(24.0, float(first_w) - pad)
    for ch in text:
        trial = buf + ch
        if _text_w(draw, trial, font) <= limit or not buf:
            buf = trial
            continue
        cut = -1
        for i in range(len(buf) - 1, 0, -1):
            if buf[i] in _BREAK_AFTER:
                cut = i + 1
                break
        if cut > 0 and cut < len(buf):
            lines.append(buf[:cut].rstrip())
            buf = buf[cut:].lstrip() + ch
        else:
            lines.append(buf)
            buf = ch
        limit = max(24.0, float(rest_w) - pad)
    if buf:
        if (
            len(buf) <= 2
            and lines
            and _text_w(draw, lines[-1] + buf, font) <= limit
        ):
            lines[-1] = lines[-1] + buf
        else:
            lines.append(buf)
    out: List[str] = []
    for ln in lines:
        if out and ln.strip() in "。、；：，,．":
            out[-1] = out[-1] + ln.strip()
        elif ln.strip():
            out.append(ln)
        else:
            out.append(ln)
    return out or [""]


def _hang_prefix(para: str) -> str:
    m = re.match(r"^(\d{1,2}  )", para)
    if m:
        return m.group(1)
    for p in ("・", "→ "):
        if para.startswith(p):
            return p
    if para.startswith("   "):
        return "   "
    return ""


def _layout_body(draw, body: str, font, max_w: int) -> List[Tuple[int, str] | None]:
    """段落、編號、箭頭採懸吊縮排。None＝段距。編號列預留金圈寬，避免換行後超出右緣。"""
    out: List[Tuple[int, str] | None] = []
    badge_hang = 72
    for para in (body or "").split("\n"):
        if para == "":
            out.append(None)
            continue
        numbered = re.match(r"^(\d{1,2})  (.+)$", para)
        if numbered:
            rest_w = max(max_w - badge_hang, int(max_w * 0.62))
            wrapped = _wrap_line(draw, numbered.group(2), font, rest_w, rest_w)
            for i, ln in enumerate(wrapped):
                if i == 0:
                    out.append((0, f"{numbered.group(1)}  {ln}"))
                else:
                    out.append((badge_hang, ln))
            continue
        prefix = _hang_prefix(para)
        hang = int(_text_w(draw, prefix, font)) if prefix else 0
        rest_w = max(max_w - hang, int(max_w * 0.62))
        wrapped = _wrap_line(draw, para, font, max_w, rest_w)
        for i, ln in enumerate(wrapped):
            out.append((hang if i else 0, ln))
    return out


def _page_path(out_dir: str, slug: str) -> str:
    return os.path.join(out_dir, f"{CACHE_VER}-{slug}.png")


def _flip_path(out_dir: str, src: int, dst: int) -> str:
    return os.path.join(out_dir, f"{CACHE_VER}-flip-{int(src)}-{int(dst)}.gif")


def asset_dir() -> str:
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "picture_guide_assets")


def page_index(slug: str) -> int:
    try:
        return list(PAGE_SLUGS).index(slug)
    except ValueError:
        return 0


def page_copy(slug: str) -> Tuple[str, str]:
    for s, title, body in PAGES:
        if s == slug:
            return title, body
    raise KeyError(slug)


def _page_shot(slug: str):
    from PIL import Image

    name = PAGE_SHOTS.get(slug)
    if not name:
        return None
    path = os.path.join(asset_dir(), name)
    if not os.path.isfile(path) or os.path.getsize(path) < 8_000:
        return None
    im = Image.open(path).convert("RGB")
    return _trim_guide_shot(name, im)


def _is_caption_fill(c) -> bool:
    """配圖底那條米色說明條：(255, 246, 236)。"""
    r, g, b = c[:3]
    return r >= 240 and 228 <= g <= 252 and 200 <= b <= 245 and (r - b) >= 8


def _strip_caption_bar(im):
    """整條說明色帶裁掉。殘字「見就打/menu）」就是這條被切一半。"""
    w, h = im.size
    px = im.load()
    cut = h
    for y in range(h - 1, max(h // 4, 8), -1):
        n = 0
        hits = 0
        for x in range(0, w, 4):
            n += 1
            if _is_caption_fill(px[x, y]):
                hits += 1
        if n and hits / n >= 0.38:
            cut = y
            continue
        if cut < h:
            break
    if h - cut >= 8:
        return im.crop((0, 0, w, max(1, cut - 8)))
    return im


def _trim_guide_shot(name: str, im):
    """先去掉底欄說明，再裁聊天區。兩排按鈕與四格圖示要在，殘字不能在。"""
    im = _strip_caption_bar(im)
    keyboard = {
        "cover_menu.png",
        "lists.png",
        "streak.png",
        "oops.png",
        "screen.png",
    }
    w, h = im.size
    if name in keyboard and w >= 1400:
        left = int(w * 0.08)
        right = int(w * 0.93)
        top = int(h * 0.20)
        return im.crop((left, top, right, h))
    if name in {"charts.png", "hub.png"} and w >= 1400:
        left = int(w * 0.14)
        right = int(w * 0.86)
        return im.crop((left, 0, right, h))
    if name == "discipline.png" and w >= 900:
        left = int(w * 0.16)
        right = int(w * 0.84)
        return im.crop((left, 0, right, h))
    return im


def _fit_box(im, max_w: int, max_h: int):
    from PIL import Image

    w, h = im.size
    if w <= 0 or h <= 0 or max_w <= 0 or max_h <= 0:
        return im
    scale = min(max_w / w, max_h / h)
    nw = max(1, int(round(w * scale)))
    nh = max(1, int(round(h * scale)))
    if (nw, nh) == (w, h):
        return im
    return im.resize((nw, nh), Image.Resampling.LANCZOS)


def _fit_cover(im, max_w: int, max_h: int, *, keep: str = "center"):
    """鋪滿目標框：放大後裁切，不留左右空白。寬圖裁左右；高圖依 keep 留頂或置中。"""
    from PIL import Image

    w, h = im.size
    if w <= 0 or h <= 0 or max_w <= 0 or max_h <= 0:
        return im
    scale = max(max_w / w, max_h / h)
    nw = max(1, int(round(w * scale)))
    nh = max(1, int(round(h * scale)))
    if (nw, nh) != (w, h):
        im = im.resize((nw, nh), Image.Resampling.LANCZOS)
        w, h = im.size
    left = max(0, (w - max_w) // 2)
    if keep == "top":
        top = 0
    elif keep == "bottom":
        top = max(0, h - max_h)
    else:
        top = max(0, (h - max_h) // 2)
    return im.crop((left, top, left + max_w, top + max_h))


def _shot_card(shot, max_w: int, max_h: int, *, keep: str = "center"):
    """截圖等比放入卡片。不硬鋪滿、不裁按鈕、不留底欄殘字；不夠高就留深藍。"""
    from PIL import Image, ImageDraw

    pad = 14
    inner_w = max(1, max_w - pad * 2)
    inner_h = max(1, max_h - pad * 2)
    if keep == "cover":
        shot = _fit_cover(shot, inner_w, inner_h, keep="center")
        card_h = max_h
    else:
        shot = _fit_box(shot, inner_w, inner_h)
        card_h = min(max_h, shot.size[1] + pad * 2)
    sw, sh = shot.size
    out = Image.new("RGB", (max_w, card_h), _BG)
    d = ImageDraw.Draw(out)
    d.rounded_rectangle((0, 0, max_w - 1, card_h - 1), 18, fill=_CARD, outline=_ACCENT, width=3)
    d.rounded_rectangle((6, 6, max_w - 7, card_h - 7), 14, outline=_GOLD, width=1)
    x = pad + max(0, (inner_w - sw) // 2)
    y = pad + max(0, (card_h - pad * 2 - sh) // 2)
    out.paste(shot, (x, y))
    return out


def _text_block_h(rows: List[Tuple[int, str] | None], line_h: int, gap_h: int) -> int:
    h = 0
    for row in rows:
        h += gap_h if row is None else line_h
    return h


def _save_page_image(img, out_path: str) -> None:
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    img.save(out_path, "PNG", compress_level=3, dpi=(300, 300))
    if os.path.getsize(out_path) > TG_PHOTO_MAX_BYTES:
        img.convert("RGB").save(
            out_path,
            "JPEG",
            quality=95,
            optimize=True,
            subsampling=0,
            dpi=(300, 300),
        )


def _chrome_h() -> int:
    return CHROME_TOP + 8 + 32 + PROGRESS_H + 8 + KICKER_H


def _draw_progress(draw, y: int, current: int, n: int, x0: int, x1: int) -> None:
    """金／青進度條，取代十六顆小點。"""
    n = max(1, int(n))
    current = max(0, min(int(current), n - 1))
    track_y = y + 8
    h = 6
    draw.rounded_rectangle((x0, track_y, x1, track_y + h), 3, fill=_LINE)
    span = max(1.0, float(x1 - x0))
    fill_w = span * ((current + 1) / float(n))
    fx1 = x0 + fill_w
    if fx1 - x0 >= 8:
        draw.rounded_rectangle((x0, track_y, fx1, track_y + h), 3, fill=_ACCENT)
    cx = x0 + span * ((current + 0.5) / float(n))
    r = 7
    draw.ellipse((cx - r, track_y + h / 2 - r, cx + r, track_y + h / 2 + r), fill=_GOLD_HI)
    draw.ellipse(
        (cx - r + 2, track_y + h / 2 - r + 2, cx + r - 2, track_y + h / 2 + r - 2),
        fill=_GOLD,
    )


def _draw_badge(draw, n: int, cx: int, cy: int, r: int = 26) -> None:
    draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=_GOLD)
    font = _load_font(max(22, r + 2), bold=True)
    t = str(n)
    tx, ty = _centered_text_xy(font, t, (cx - r, cy - r, cx + r, cy + r))
    draw.text((tx, ty), t, font=font, fill=_BG)


def _parse_numbered_steps(body: str) -> List[Tuple[int, str]]:
    steps: List[Tuple[int, str]] = []
    cur: Optional[int] = None
    buf: List[str] = []
    for para in (body or "").split("\n"):
        m = re.match(r"^(\d{1,2})  (.+)$", para)
        if m:
            if cur is not None:
                steps.append((cur, " ".join(buf).strip()))
            cur = int(m.group(1))
            buf = [m.group(2).strip()]
            continue
        if cur is not None and para.startswith("   "):
            extra = para.strip()
            if extra:
                buf.append(extra)
            continue
        if cur is not None and para.strip() == "":
            continue
        if cur is not None:
            steps.append((cur, " ".join(buf).strip()))
            cur = None
            buf = []
    if cur is not None:
        steps.append((cur, " ".join(buf).strip()))
    return [(n, t) for n, t in steps if t]


def _cover_lead(body: str) -> str:
    lead: List[str] = []
    for para in (body or "").split("\n"):
        if re.match(r"^\d{1,2}  ", para):
            break
        if para.strip():
            lead.append(para.strip())
    return " ".join(lead)


def _draw_legend_panel(draw, title: str, labels: Sequence[str], box) -> None:
    """沒有截圖的頁：下半用金框面板放關鍵詞，不要留一大塊空海軍藍。"""
    x0, y0, x1, y1 = box
    draw.rounded_rectangle((x0, y0, x1, y1), 18, fill=_CARD, outline=_ACCENT, width=3)
    draw.rounded_rectangle((x0 + 6, y0 + 6, x1 - 6, y1 - 6), 14, outline=_GOLD, width=1)
    title_font = _load_font(36, bold=True)
    tx, ty = _centered_text_xy(title_font, title, (x0, y0 + 28, x1, y0 + 84))
    draw.text((tx, ty), title, font=title_font, fill=_GOLD)
    rule_y = y0 + 96
    draw.line((x0 + 80, rule_y, x1 - 80, rule_y), fill=_LINE, width=2)
    font = _load_font(32, bold=True)
    pad_x = 22
    gap = 16
    row_h = 58
    inner_w = x1 - x0 - 80
    x = x0 + 40
    y = rule_y + 36
    for lab in labels:
        tw = _text_w(draw, lab, font)
        w = int(tw + pad_x * 2)
        if x + w > x0 + 40 + inner_w and x > x0 + 40:
            x = x0 + 40
            y += row_h + gap
        if y + row_h > y1 - 36:
            break
        pill = (x, y, x + w, y + row_h)
        draw.rounded_rectangle(pill, 29, fill=_LABEL_BG, outline=_GOLD, width=2)
        px, py = _centered_text_xy(font, lab, pill)
        draw.text((px, py), lab, font=font, fill=_GOLD_HI)
        x += w + gap


def _draw_watermark(draw, idx: int, n: int) -> None:
    mark = f"{idx + 1:02d}"
    font = _load_font(280, bold=True)
    tw = _text_w(draw, mark, font)
    draw.text((PAGE_WIDTH - MARGIN - tw - 8, PAGE_HEIGHT - 340), mark, font=font, fill=_WATER)


def _draw_step_cards(img, draw, steps: Sequence[Tuple[int, str]], y: int, max_w: int, body_font) -> int:
    card_font = _load_font(40)
    card_h = 110
    gap = 16
    lh = 46
    for n, text in steps[:3]:
        box = (MARGIN, y, MARGIN + max_w, y + card_h)
        draw.rounded_rectangle(box, 18, fill=_STEP_BG, outline=_GOLD, width=2)
        _draw_badge(draw, n, MARGIN + 48, y + card_h // 2, r=28)
        inner_w = max_w - 110
        lines = _wrap_line(draw, text, card_font, inner_w, inner_w)[:2]
        ty = y + (card_h - lh * len(lines)) // 2
        for ln in lines:
            draw.text((MARGIN + 90, ty), ln, font=card_font, fill=_INK)
            ty += lh
        y += card_h + gap
    return y


def render_page(slug: str, title: str, body: str, out_path: str) -> str:
    """上半置中標題＋內文；配圖固定在下半，中間留空，不要黏在一起。"""
    from PIL import Image, ImageDraw

    max_w = PAGE_WIDTH - 2 * MARGIN
    shot_top_min = int(PAGE_HEIGHT * SHOT_TOP_RATIO)
    chrome = _chrome_h()
    layout = PAGE_LAYOUT.get(slug, "visual")
    probe = Image.new("RGB", (PAGE_WIDTH, 200), _BG)
    pdraw = ImageDraw.Draw(probe)
    title_size = TITLE_SIZE
    body_size = BODY_SIZE
    title_lines: List[str] = []
    body_rows: List[Tuple[int, str] | None] = []
    title_lh = body_lh = gap_h = 0
    title_font = body_font = None
    text_h = 0
    if layout == "editorial":
        text_budget = PAGE_HEIGHT - BOTTOM_PAD - 120
    else:
        text_budget = shot_top_min - TEXT_SHOT_GAP
    cover_steps = _parse_numbered_steps(body) if layout == "cover" else []
    scales = (1.22, 1.14, 1.08, 1.0, 0.94, 0.90)
    for scale in scales:
        title_size = max(MIN_TITLE_SIZE, min(MAX_TITLE_SIZE, int(round(TITLE_SIZE * scale))))
        body_size = max(MIN_BODY_SIZE, min(MAX_BODY_SIZE, int(round(BODY_SIZE * scale))))
        title_font = _load_font(title_size, bold=True)
        body_font = _load_font(body_size)
        title_lh = max(int(round(title_size * 1.34)), title_size + 18)
        body_lh = max(int(round(body_size * 1.36)), body_size + 10)
        gap_h = max(int(round(body_size * 0.28)), 10)
        title_lines = _wrap_line(pdraw, title, title_font, max_w, max_w)
        if layout == "cover":
            text_h = chrome + 8 + len(title_lines) * title_lh + 36 + 3 * 126 + 70
        else:
            body_rows = _layout_body(pdraw, body, body_font, max_w)
            text_h = (
                chrome
                + 8
                + len(title_lines) * title_lh
                + 36
                + _text_block_h(body_rows, body_lh, gap_h)
            )
        if text_h <= text_budget:
            break
    assert title_font is not None and body_font is not None
    img = Image.new("RGB", (PAGE_WIDTH, PAGE_HEIGHT), _BG)
    draw = ImageDraw.Draw(img)
    idx = page_index(slug)
    n = len(PAGE_SLUGS)
    _draw_watermark(draw, idx, n)
    draw.rectangle((0, 0, PAGE_WIDTH, CHROME_TOP), fill=_ACCENT)
    draw.rectangle((0, 0, 10, PAGE_HEIGHT), fill=_ACCENT)
    draw.rectangle((10, 0, 14, PAGE_HEIGHT), fill=_GOLD)
    brand_font = _load_font(26, bold=True)
    mark_font = _load_font(28, bold=True)
    y = CHROME_TOP + 8
    draw.text((MARGIN, y), "WayneBot 圖文", font=brand_font, fill=_ACCENT)
    mark = f"{idx + 1:02d} ／ {n:02d}"
    mw = _text_w(draw, mark, mark_font)
    draw.text((PAGE_WIDTH - MARGIN - mw, y), mark, font=mark_font, fill=_GOLD_HI)
    y += 32
    _draw_progress(draw, y, idx, n, MARGIN, PAGE_WIDTH - MARGIN)
    y += PROGRESS_H + 8
    kicker = PAGE_KICKERS.get(slug, "WayneBot")
    kicker_font = _load_font(28, bold=True)
    kx, ky = _centered_text_xy(
        kicker_font, kicker, (MARGIN, y, PAGE_WIDTH - MARGIN, y + KICKER_H - 8)
    )
    draw.text((kx, ky), kicker, font=kicker_font, fill=_GOLD)
    y += KICKER_H
    title_box_h = max(title_lh, 72)
    for line in title_lines:
        tx, ty = _centered_text_xy(
            title_font, line, (MARGIN, y, PAGE_WIDTH - MARGIN, y + title_box_h)
        )
        draw.text((tx, ty), line, font=title_font, fill=_INK)
        y += title_lh
    y += 10
    tw0 = 0.0
    for ln in title_lines:
        tw0 = max(tw0, _text_w(draw, ln, title_font))
    rule_w = min(max_w - 48, max(tw0 + 64, 220))
    rx0 = (PAGE_WIDTH - rule_w) / 2.0
    draw.line((rx0, y, rx0 + rule_w, y), fill=_GOLD, width=3)
    y += 26

    if layout == "cover":
        lead = _cover_lead(body)
        if lead:
            lead_font = _load_font(max(MIN_BODY_SIZE - 4, 40))
            lead_lines = _wrap_line(draw, lead, lead_font, max_w, max_w)
            for ln in lead_lines[:3]:
                lx, ly = _centered_text_xy(
                    lead_font, ln, (MARGIN, y, PAGE_WIDTH - MARGIN, y + 48)
                )
                draw.text((lx, ly), ln, font=lead_font, fill=_MUTED)
                y += 48
            y += 8
        y = _draw_step_cards(img, draw, cover_steps, y, max_w, body_font)
        foot = "挑股只認黃金買點。圖上紅箭頭不是買訊。"
        foot_font = _load_font(36, bold=True)
        fx, fy = _centered_text_xy(
            foot_font, foot, (MARGIN, y, PAGE_WIDTH - MARGIN, y + 52)
        )
        draw.text((fx, fy), foot, font=foot_font, fill=_GOLD_HI)
        y += 60
    else:
        badge_r = 24
        badge_hang = 72
        for row in body_rows:
            if row is None:
                y += gap_h
                continue
            indent, line = row
            m = re.match(r"^(\d{1,2})  (.+)$", line) if indent == 0 else None
            if m:
                num = int(m.group(1))
                rest = m.group(2)
                cy = y + body_lh // 2
                _draw_badge(draw, num, MARGIN + badge_r, cy, r=badge_r)
                draw.text((MARGIN + badge_hang, y), rest, font=body_font, fill=_INK)
            else:
                draw.text((MARGIN + indent, y), line, font=body_font, fill=_INK)
            y += body_lh

    text_end = y
    y_floor = max(shot_top_min, text_end + TEXT_SHOT_GAP)
    avail_h = PAGE_HEIGHT - BOTTOM_PAD - y_floor
    shot = _page_shot(slug)
    if shot is not None and avail_h >= 80:
        card = _shot_card(shot, max_w, avail_h)
        card_h = card.size[1]
        y_shot = PAGE_HEIGHT - BOTTOM_PAD - card_h
        if y_shot < y_floor:
            y_shot = y_floor
        img.paste(card, (MARGIN, y_shot))
    elif layout == "editorial":
        pills = PAGE_PILLS.get(slug) or ()
        panel_top = max(y_floor, int(PAGE_HEIGHT * 0.58))
        panel_bot = PAGE_HEIGHT - BOTTOM_PAD - 64
        if pills and panel_bot - panel_top >= 180:
            _draw_legend_panel(
                draw,
                PAGE_PANEL.get(slug, "WayneBot"),
                pills,
                (MARGIN, panel_top, PAGE_WIDTH - MARGIN, panel_bot),
            )
        foot = "WayneBot  ·  只認高低卡表  ·  紅箭頭不是買訊"
        foot_font = _load_font(28, bold=True)
        fy = PAGE_HEIGHT - BOTTOM_PAD - 36
        fx, fyy = _centered_text_xy(
            foot_font, foot, (MARGIN, fy, PAGE_WIDTH - MARGIN, fy + 36)
        )
        draw.text((fx, fyy), foot, font=foot_font, fill=_MUTED)
    _save_page_image(img, out_path)
    return out_path


def picture_guide_dir(charts_dir: str | None = None) -> str:
    if not charts_dir:
        try:
            from config import get_charts_dir

            charts_dir = get_charts_dir()
        except Exception:
            charts_dir = os.path.join("data", "charts")
    path = os.path.join(str(charts_dir), "picture_guide", CACHE_VER)
    os.makedirs(path, exist_ok=True)
    return path


def ensure_page(slug: str, out_dir: str | None = None, *, force: bool = False) -> str:
    """只渲這一張。第一次按圖文不必先做完十六張。"""
    dest = out_dir or picture_guide_dir()
    os.makedirs(dest, exist_ok=True)
    title, body = page_copy(slug)
    path = _page_path(dest, slug)
    if force or not os.path.isfile(path) or os.path.getsize(path) < 8_000:
        render_page(slug, title, body, path)
    return path


def render_picture_guide(out_dir: str | None = None, *, force: bool = False) -> List[str]:
    """產出 16 張長圖；已有快取就沿用。測試／本機對圖用；話筒走 ensure_page。"""
    dest = out_dir or picture_guide_dir()
    os.makedirs(dest, exist_ok=True)
    return [ensure_page(slug, dest, force=force) for slug, _t, _b in PAGES]


def render_flip_gif(
    src_path: str,
    dst_path: str,
    out_path: str,
    *,
    forward: bool = True,
) -> str:
    """舊頁滑出、新頁滑入。半尺寸 GIF，換頁後再換成原圖。"""
    from PIL import Image, ImageDraw, ImageEnhance

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    a = Image.open(src_path).convert("RGB").resize((FLIP_W, FLIP_H), Image.Resampling.LANCZOS)
    b = Image.open(dst_path).convert("RGB").resize((FLIP_W, FLIP_H), Image.Resampling.LANCZOS)
    frames = []
    n = FLIP_FRAMES
    for i in range(n):
        t = (i + 1) / float(n)
        e = t * t * (3.0 - 2.0 * t)
        dx = int(round(FLIP_W * e))
        canvas = Image.new("RGB", (FLIP_W, FLIP_H), _BG)
        if forward:
            canvas.paste(a, (-dx, 0))
            canvas.paste(b, (FLIP_W - dx, 0))
            seam = FLIP_W - dx
        else:
            canvas.paste(a, (dx, 0))
            canvas.paste(b, (dx - FLIP_W, 0))
            seam = dx
        overlay = Image.new("RGBA", (FLIP_W, FLIP_H), (0, 0, 0, 0))
        od = ImageDraw.Draw(overlay)
        glow = max(8, int(28 * (1.0 - abs(0.5 - t) * 2)))
        x0 = max(0, seam - glow)
        x1 = min(FLIP_W - 1, seam + glow)
        od.rectangle((x0, 0, x1, FLIP_H), fill=_ACCENT + (int(90 * (1.0 - abs(0.5 - t) * 2)),))
        mixed = Image.alpha_composite(canvas.convert("RGBA"), overlay).convert("RGB")
        if i == 0:
            mixed = ImageEnhance.Brightness(mixed).enhance(1.08)
        frames.append(mixed)
    frames[0].save(
        out_path,
        save_all=True,
        append_images=frames[1:],
        duration=FLIP_MS,
        loop=1,
        optimize=True,
        disposal=2,
    )
    return out_path


def ensure_flip_gif(
    src_slug: str,
    dst_slug: str,
    out_dir: str,
    *,
    force: bool = False,
) -> Optional[str]:
    src_i = page_index(src_slug)
    dst_i = page_index(dst_slug)
    if src_i == dst_i:
        return None
    src = ensure_page(src_slug, out_dir)
    dst = ensure_page(dst_slug, out_dir)
    path = _flip_path(out_dir, src_i, dst_i)
    if force or not os.path.isfile(path) or os.path.getsize(path) < 4_000:
        render_flip_gif(src, dst, path, forward=dst_i > src_i)
    return path


def parse_guide_callback(data: str) -> Tuple[Optional[int], int]:
    """pg:3 或 pg:2-3 → (from_page, to_page)。舊按鈕只有目標頁。"""
    rest = str(data or "")
    if rest.startswith("pg:"):
        rest = rest[3:]
    rest = rest.strip()
    if "-" in rest:
        a, b = rest.split("-", 1)
        return int(a), int(b)
    return None, int(rest or "0")


def page_copy_blob() -> str:
    return "\n".join(f"{slug}\n{title}\n{body}" for slug, title, body in PAGES)
