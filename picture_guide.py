# -*- coding: utf-8 -*-
"""哥哥圖文說明：手機長圖 8 頁，說明頁「圖文」一次一張、按第 N 張換頁。

藍底白字青標對齊產業圖卡／大盤頁；金線當層次。一次只渲正在看的那一張。
"""
from __future__ import annotations

import os
import re
from typing import Dict, List, Optional, Sequence, Tuple

CACHE_VER = "v32"
# 八頁同一張 9:16 一屏。超長海報在話筒裡會整張縮小，字會小到不能看。
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
TEXT_SHOT_GAP = 88
SHOT_TOP_RATIO = 0.52
EDITORIAL_PANEL_H = 300
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
        "這本說明給手機看。一次只看一張。現在共 8 張。按「第 2 張」看下一張。\n"
        "\n"
        "1  點四格鍵盤圖示叫出兩排。不見就打 /menu\n"
        "2  直接打代號看圖，例如 2330、0050、0052、00631L、00981A。不要先按「刷新」\n"
        "3  三張圖出來後，最上是產業／報導／K線；下一排籌碼、營收、觀察、記買入\n"
        "\n"
        "挑股只認高低卡表的黃金買點。圖上紅箭頭不是買訊。",
    ),
    (
        "menu",
        "兩排主選單在哪",
        "不在訊息最下面。點輸入列旁邊的四格鍵盤圖示展開兩排。也可打 /menu。\n"
        "\n"
        "第一排（左到右）\n"
        "說明　海選　持股　觀察　刷新　回報\n"
        "\n"
        "第二排（左到右）\n"
        "大盤　資金　當沖　隔日沖　AI倉　連買區\n"
        "\n"
        "說明＝這本使用說明。海選＝昨天收盤掃出的名單。持股＝你手記的真實買入。觀察＝還沒買的自選。刷新＝只重畫上一檔，不是海選。打「決策卡」或「刷新上一檔」也行。回報＝畫面怪告訴偉權。\n"
        "打「精簡選單」或「精簡鍵盤」只留說明／海選／持股、觀察／刷新／回報（都是兩個字）；「完整選單」或「完整鍵盤」恢復十二顆。還沒查過請直接打代號（股票或 ETF）。",
    ),
    (
        "lookup",
        "查一檔：一次三張圖",
        "打 2330、0050、00631L、00981A。不要先按「刷新」。國字打不準就點左邊確認。ETF 可含 L／R／A。"
        "一次三張：介紹圖／決策卡／導航圖。圖下產業（一張圖卡，細項小框沒抓到不畫）、報導、K線（可改15分／五日／月線）。下一排籌碼、營收、記買入。零股「200股」。"
        "黃金買點＝獲利剛離 0。重點觀察＝近 60 日。月K還在往上不是買訊。興櫃用日均價。",
    ),
    (
        "lists",
        "三種清單不要搞混",
        "觀察＝自選，還沒買。查股或海選旁邊的 + ，或按「觀察」。\n"
        "持股＝你按過「記買入」的真實部位。頁下方有成交、復盤；每檔可按賣出。打「持倉」也會開持股。\n"
        "AI倉＝假錢對照組，不是你口袋的股票。平常最多用 1 份，超跌才第 2 份，第 3 份留現金。打「持倉報告／模擬持倉／AI模擬倉」才是 AI倉。\n"
        "\n"
        "AI操盤立刻跑一輪、不推播。進化只調倍數，不改黃金買點。",
    ),
    (
        "screen",
        "海選怎麼轉 LINE",
        "依最近一次官方收盤掃全市場，不是盤中即時。主選單「海選」按一次等，不要連按。紅圈只標位置。\n"
        "1  左鍵＝這檔完整圖；右 + ＝觀察\n"
        "2  「開 LINE・傳這檔」＝只傳這一檔\n"
        "3  「一鍵傳 LINE」＝開啟手機 LINE，選要傳給誰\n"
        "黃金買點才是進場表。重點觀察先看。20 日高標「少追」。興櫃海選／興櫃名單不混進上市櫃。小動圖。優先看、周帶量、半年高、站上季線、止跌。",
    ),
    (
        "sell",
        "如何賣",
        "如何賣：最高價＝20日高，對最高溫。只協助出場，不是買訊，不自動賣，不改海選。\n"
        "\n"
        "高點跟熱度都沒了 → 這波先當結束。\n"
        "有持股先看決策卡這兩格。紅箭頭不是買訊，也不是賣訊。",
    ),
    (
        "more",
        "其餘按鈕、一天什麼時候動",
        "大盤頁：第二排最左。加權、漲跌家數、法人、台指期、美股上一收盤。美股當天沒開、台股國定假或北市全日／上午停班會寫原因。\n"
        "資金：盤後產業法人買超／賣超，只當佈局對照。當沖平日 09:00–13:30 才有。隔日沖尾盤佈局明早。連買區先選外資／投信／外資+投信再點天數。\n"
        "也可以傳語音，聽成文字後跟打字同一條（打代號看圖）。雲端要有聽寫金鑰才聽得懂；沒金鑰請改打字。\n"
        "一天什麼時候動（台灣）：06:30 早報（早上海選）、12:45 尾盤、16:30 官方收盤寫庫（興櫃日均價也在這時寫獨立表）、20:00 AI倉模擬買賣不推播。台股休市當日不寄 06:30 與 12:45。",
    ),
    (
        "oops",
        "按錯了怎麼辦",
        "亂按沒關係。下面幾條最常見。\n"
        "\n"
        "1  一打開先按了「刷新」：還沒查過就直接打代號。打「決策卡」也是同一顆\n"
        "2  「當沖」沒名單：週末／收盤後本來就空。平日 09:00–13:30 才有\n"
        "3  「海選」等很久：掃全市場；不要連按。觀察＝還沒買；持股＝按過記買入才會在\n"
        "4  找不到產業或報導或K線：在圖下面最上那一排。K線先開日K，可改15分／五日／月線。想看怎麼賣：打代號，圖底下會寫\n"
        "5  「回報」按下去又反悔：改按其他按鈕即可，不會送出。連買選到一半按錯：改按別顆就取消。主選單不見：點四格鍵盤圖示，或打 /menu。畫面怪按第一排最右「回報」。不用給密鑰或密碼",
    ),
)

PAGE_SLUGS = tuple(slug for slug, _title, _body in PAGES)

# 每頁對應真實截圖（側欄已裁）。按鈕順序已改，舊紅圈不拿來當位置依據。
PAGE_SHOTS = {
    "cover": "cover_menu.png",
    "lookup": "charts.png",
    "screen": "lists.png",
}

PAGE_KICKERS: Dict[str, str] = {
    "cover": "說明書",
    "menu": "鍵盤",
    "lookup": "查股",
    "lists": "清單",
    "screen": "海選",
    "sell": "如何賣",
    "more": "其餘",
    "oops": "按錯",
}

PAGE_LAYOUT: Dict[str, str] = {
    "cover": "cover",
    "menu": "editorial",
    "lookup": "visual",
    "lists": "editorial",
    "screen": "visual",
    "sell": "editorial",
    "more": "editorial",
    "oops": "editorial",
}

PAGE_PILLS: Dict[str, Tuple[str, ...]] = {
    "menu": ("說明", "海選", "持股", "精簡選單", "完整選單"),
    "lists": ("觀察", "持股", "AI倉", "成交", "復盤", "賣出"),
    "sell": ("如何賣", "20日高", "最高溫", "不是買訊"),
    "more": ("大盤", "資金", "當沖", "隔日沖", "連買區", "原因"),
    "oops": ("刷新", "當沖沒名單", "海選不要連按", "連買", "/menu"),
}

PAGE_PANEL: Dict[str, str] = {
    "menu": "第一週常用在第一排",
    "lists": "三種清單",
    "sell": "出場只看這兩格",
    "more": "第二排與一天時鐘",
    "oops": "先記住這幾句",
}

# 對齊產業圖卡／大盤頁：深藍底、白字、青標；金線當層次。
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
    if name == "cover_menu.png" and w >= 900:
        # 封面要看到四格圖示＋兩排在哪；鈕名以第 2 張文字為準。
        left = int(w * 0.10)
        right = int(w * 0.92)
        top = int(h * 0.36)
        return im.crop((left, top, right, h))
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


def _shot_card(shot, max_w: int, max_h: int, *, keep: str = "center", fill_h: bool = False):
    """截圖等比放入卡片。不硬鋪滿、不裁按鈕、不留底欄殘字；不夠高就留深藍。

    fill_h=True：卡片高度仍佔滿下半帶（八張同一框），圖本身仍等比、不裁按鈕。
    """
    from PIL import Image, ImageDraw

    pad = 14
    inner_w = max(1, max_w - pad * 2)
    inner_h = max(1, max_h - pad * 2)
    if keep == "cover":
        shot = _fit_cover(shot, inner_w, inner_h, keep="center")
        card_h = max_h
    else:
        shot = _fit_box(shot, inner_w, inner_h)
        card_h = max_h if fill_h else min(max_h, shot.size[1] + pad * 2)
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
    """金／青進度條。"""
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
        if y + row_h > y1 - 72:
            break
        pill = (x, y, x + w, y + row_h)
        draw.rounded_rectangle(pill, 29, fill=_LABEL_BG, outline=_GOLD, width=2)
        px, py = _centered_text_xy(font, lab, pill)
        draw.text((px, py), lab, font=font, fill=_GOLD_HI)
        x += w + gap
    foot = "只認高低卡表  ·  紅箭頭不是買訊"
    foot_font = _load_font(26, bold=True)
    fx, fy = _centered_text_xy(foot_font, foot, (x0, y1 - 56, x1, y1 - 16))
    draw.text((fx, fy), foot, font=foot_font, fill=_MUTED)


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
        text_budget = PAGE_HEIGHT - BOTTOM_PAD - EDITORIAL_PANEL_H - TEXT_SHOT_GAP
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

    # 有截圖：下半從 0.52 起同一框。說明頁：底部固定金框，不要有的有框有的沒框。
    panel_bot = PAGE_HEIGHT - BOTTOM_PAD
    shot = _page_shot(slug)
    if shot is not None:
        y_floor = shot_top_min
        avail_h = panel_bot - y_floor
        if avail_h >= 80:
            card = _shot_card(shot, max_w, avail_h, fill_h=True)
            img.paste(card, (MARGIN, y_floor))
    elif layout == "editorial":
        pills = PAGE_PILLS.get(slug) or ()
        y_floor = panel_bot - EDITORIAL_PANEL_H
        if pills:
            _draw_legend_panel(
                draw,
                PAGE_PANEL.get(slug, "WayneBot"),
                pills,
                (MARGIN, y_floor, PAGE_WIDTH - MARGIN, panel_bot),
            )
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
    """只渲這一張。第一次按圖文不必先做完八張。"""
    dest = out_dir or picture_guide_dir()
    os.makedirs(dest, exist_ok=True)
    title, body = page_copy(slug)
    path = _page_path(dest, slug)
    if force or not os.path.isfile(path) or os.path.getsize(path) < 8_000:
        render_page(slug, title, body, path)
    return path


def render_picture_guide(out_dir: str | None = None, *, force: bool = False) -> List[str]:
    """產出 8 張長圖；已有快取就沿用。測試／本機對圖用；話筒走 ensure_page。"""
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


# 主選單、打字指令、查股／海選／清單表面：八章文案都要出現。
FEATURE_PHRASES: Tuple[str, ...] = (
    "說明",
    "海選",
    "持股",
    "觀察",
    "刷新",
    "回報",
    "大盤",
    "資金",
    "當沖",
    "隔日沖",
    "AI倉",
    "連買區",
    "精簡選單",
    "精簡鍵盤",
    "完整選單",
    "完整鍵盤",
    "刷新上一檔",
    "決策卡",
    "興櫃海選",
    "興櫃名單",
    "介紹圖",
    "導航圖",
    "籌碼",
    "營收",
    "產業",
    "報導",
    "K線",
    "15分",
    "五日",
    "月線",
    "記買入",
    "200股",
    "ETF",
    "00981A",
    "成交",
    "復盤",
    "賣出",
    "持倉",
    "持倉報告",
    "模擬持倉",
    "AI模擬倉",
    "黃金買點",
    "重點觀察",
    "開 LINE・傳這檔",
    "一鍵傳 LINE",
    "少追",
    "優先看",
    "周帶量",
    "半年高",
    "站上季線",
    "止跌",
    "小動圖",
    "如何賣",
    "20日高",
    "最高溫",
    "06:30",
    "12:45",
    "16:30",
    "20:00",
    "進化",
    "/menu",
    "不用給密鑰",
    "外資+投信",
    "一張圖卡",
    "細項小框",
    "紅圈",
    "這波先當結束",
    "官方收盤掃全市場",
    "月K還在往上",
    "日均價",
    "語音",
    "AI操盤",
    "零股",
    "連買選到一半",
)
